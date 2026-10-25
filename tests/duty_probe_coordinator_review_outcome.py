"""P09: native Coordinator consumption after explicit recorded-review setup.

The initial task, checker and Reviewer choices, plus the parent supervision read,
are fake preparation through actual ToolNodes. Subsequent actions use the original
handler/injected factory. No host-created ToolMessage, second loop or new guard.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_reviewer_consumer import RecordedChecker, prepare_reviewer_fixture
from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate


TRUE_FINAL = ('Both assigned comparisons have execution_complete=true, but both verdicts are '
              'not_satisfied. No comparison remains unperformed; this is not engineering acceptance.')
FALSE_FINAL = 'All assigned criteria have passed and the report is accepted for engineering use.'


class PreparedReviewer(AgentMiddleware):
    def __init__(self, shared):
        self.shared, self.step = shared, 0

    async def awrap_model_call(self, request, handler):
        if self.shared.get('consumer_started') or self.step >= 2:
            return await handler(request)
        self.step += 1
        if self.step == 1:
            answer = action('perform_assigned_review', 'recorded-checker', operation_id='recorded-R1-preparation',
                scope_ids=['rule-comparison', 'second-comparison'], source_selections=[], content_selections=[])
            phase = 'explicit_fake_checker_selection'
        else:
            message = tool_reply(request.messages, 'recorded-checker')
            value = result_value(message)
            assert message.status == 'success' and value.get('review_ref'), value
            self.shared['reviewer_public_tool'] = message.model_dump()
            self.shared['reviewer_public_result'] = deepcopy(value)
            # Full recorded result, received from the actual tool, not a stored
            # body inserted by the host. The current full fixture is inline.
            answer = AIMessage(content=json.dumps(value, ensure_ascii=False))
            phase = 'explicit_fake_reviewer_return'
        self.shared['preparation_events'].append({'phase': phase, 'messages': messages_to_dict(request.messages),
                                                   'response': answer.model_dump()})
        return ModelResponse(result=[answer])


class PreparedCoordinator(AgentMiddleware):
    def __init__(self, ws, fixture, service, shared):
        self.ws, self.fixture, self.service, self.shared = ws, fixture, service, shared
        self.step, self.advertised, self.pages = 0, None, []

    def prepared(self, request, answer, phase):
        self.shared['preparation_events'].append({'phase': phase, 'messages': messages_to_dict(request.messages),
                                                   'response': answer.model_dump()})
        return ModelResponse(result=[answer])

    async def awrap_model_call(self, request, handler):
        if not self.shared.get('consumer_started'):
            if self.step == 0:
                self.step = 1
                return self.prepared(request, AIMessage(content='', tool_calls=[self.fixture['task_call']]),
                                     'explicit_fake_task_assignment')
            if self.step == 1:
                self.step = 2
                self.shared['native_task_return'] = tool_reply(request.messages, 'recorded-review-task').model_dump()
                return self.prepared(request, action('read_task_supervision', 'p09-supervision'),
                                     'explicit_fake_parent_supervision_read')
            message = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage))
            value = result_value(message)
            self.shared.setdefault('supervision_tool_returns', []).append(message.model_dump())
            if message.name == 'read_task_supervision' and value.get('complete_tool_result') is False:
                assert value['exact_data_tool'] == 'read_tool_observation'
                self.advertised = deepcopy(value)
                return self.prepared(request, action('read_tool_observation', 'p09-recovery',
                    observation_ref=value['observation_ref'], offset=0, characters=6000), 'explicit_fake_advertised_recovery')
            if message.name == 'read_tool_observation':
                assert value['observation_ref'] == self.advertised['observation_ref']
                assert value['offset'] == sum(len(p['text']) for p in self.pages)
                self.pages.append(deepcopy(value))
                if value['next_offset'] is not None:
                    return self.prepared(request, action('read_tool_observation', 'p09-recovery',
                        observation_ref=value['observation_ref'], offset=value['next_offset'], characters=6000),
                        'explicit_fake_advertised_recovery')
                value = json.loads(''.join(p['text'] for p in self.pages))
            assert value['ok'] is True and len(value['result']['tasks']) == 1
            self.shared['supervision_received'] = deepcopy(value)
            self.shared['preparation_recovery_pages'] = deepcopy(self.pages)
            cs = ContentStore(self.ws.store)
            self.shared['saved_reviews_before_consumer'] = deepcopy(cs.list_objects('ReviewRecord'))
            self.shared['saved_tasks_before_consumer'] = deepcopy(cs.list_objects('DelegatedTask'))
            self.shared['consumer_started'] = self.service.consumer_started = True
        # No reconstructed value is appended to the request. Its original
        # ToolMessages (including recovery pages) are the consumer's inputs.
        event = {'phase': 'unchanged_coordinator_handler', 'messages': messages_to_dict(request.messages)}
        self.shared['consumer_events'].append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


async def capture_coordinator_review_outcome(ws, case, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_reviewer_fixture(ws, 'full')
    activate(ws)
    dump(folder / 'fixture.json', fixture)
    shared = {'preparation_events': [], 'consumer_events': [], 'consumer_started': False}
    service = RecordedChecker(ws, fixture, model_factory)
    coordinator = PreparedCoordinator(ws, fixture, service, shared)
    reviewer = PreparedReviewer(shared)
    calls, models = [], {}
    def factory(role):
        if role == 'text_tool':
            return service
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]
    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['middleware'] = [*kwargs.get('middleware', []), coordinator]
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), reviewer]}
                if a['name'] == 'reviewer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)
    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        cs = ContentStore(ws.store)
        records, tasks = cs.list_objects('ReviewRecord'), cs.list_objects('DelegatedTask')
        finals = [m['data']['content'] for event in shared['consumer_events'] for m in event.get('response', [])
                  if m['type'] == 'ai' and not m['data'].get('tool_calls')]
        capture = {'case': case, 'runtime': runtime, 'raised_error': error, 'fixture': fixture,
            'prepared': shared, 'native_model_calls': calls, 'checker_calls': service.calls,
            'saved_reviews': records, 'saved_tasks': tasks,
            'saved_task_status': [reconcile(cs, t['ref']['id']) for t in tasks], 'finals': finals,
            'originals_unchanged': all(cs.read(o['ref']) == o for o in fixture['originals']),
            'host_completion_actions': False, 'semantic_status': 'not_semantically_assessed',
            'limitations': ['Initial assignment/checker/Reviewer and parent read/recovery choices are explicit fake preparation.',
                'Only later model_factory calls are consumer decisions; subsequent roles and independent tools are not faked.',
                'No whole-report, engineering or general model decision acceptance is implied.',
                'A false final is a known semantic calibration, not a newly required runtime rejection.']}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
    return capture
