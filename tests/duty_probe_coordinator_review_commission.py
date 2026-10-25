"""C5: native Coordinator defines a review; only initial reads/child are fake.

Recorded R1 supplies short saved objects, never a prefilled Coordinator action.
The child honestly stops before reviewing. No checker, acceptance, host-created
ToolMessage or replacement agent loop is introduced.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_reviewer_consumer import prepare_reviewer_fixture
from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.content_tasks import bound_actor
from report_agent.task_context import exact_task_context
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import action, result_value
from test_decision_data import activate


CHILD_FINAL = ('Synthetic child control: I have read the immutable assignment, '
               'but have performed no comparison or review. All assigned checks remain unperformed.')
PARENT_FINAL = ('Both requested objects have been assigned for independent review. '
                'The child has not performed that review; no criterion has been accepted.')


class PreparedCommissionReads(AgentMiddleware):
    def __init__(self, fixture, events):
        self.fixture, self.events, self.started = fixture, events, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            refs = [o['ref'] for o in self.fixture['originals']
                    if o['ref']['type'] in {'Requirement', 'Criterion', 'SourceArtifact'}]
            refs += self.fixture['evidence_refs'][:2] + [self.fixture['snapshot_ref']]
            refs = list({json.dumps(r, sort_keys=True): r for r in refs}.values())
            answer = AIMessage(content='', tool_calls=[{
                'name': 'read_context', 'id': 'c5-prepare-' + str(i), 'type': 'tool_call',
                'args': {'target_ref': ref},
            } for i, ref in enumerate(refs)])
            self.events.append({'phase': 'explicit_fake_original_reads',
                                'messages': messages_to_dict(request.messages), 'response': answer.model_dump()})
            return ModelResponse(result=[answer])
        event = {'phase': 'unchanged_coordinator_handler', 'messages': messages_to_dict(request.messages)}
        self.events.append(event)
        response = await handler(request)
        event['response'] = messages_to_dict(response.result)
        return response


class UnperformedReviewer(AgentMiddleware):
    """Explicit fake child, with real assignment read and native recovery."""
    def __init__(self, ws, events):
        self.ws, self.events, self.tasks = ws, events, {}

    async def awrap_model_call(self, request, handler):
        context = exact_task_context(self.ws, 'reviewer')
        task_id = bound_actor(self.ws, 'reviewer', None).task_id
        state = self.tasks.setdefault(task_id, {'pages': [], 'read_started': False, 'done': False})
        event = {'phase': 'explicit_fake_unperformed_reviewer', 'task_id': task_id,
                 'server_context': deepcopy(context), 'messages': messages_to_dict(request.messages)}
        self.events.append(event)
        if not state['read_started']:
            state['read_started'] = True
            answer = action('read_task_assignment', 'c5-assignment-' + task_id)
        elif not state['done']:
            message = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage))
            value = result_value(message)
            assert message.status == 'success', value
            event['actual_assignment_tool'] = message.model_dump()
            if 'observation_ref' in value and 'text' in value:
                assert value['offset'] == sum(len(p['text']) for p in state['pages'])
                state['pages'].append(deepcopy(value))
                if value['next_offset'] is not None:
                    answer = action('read_tool_observation', 'c5-assignment-page-' + task_id,
                                    observation_ref=value['observation_ref'],
                                    offset=value['next_offset'], characters=6000)
                    event['response'] = answer.model_dump()
                    return ModelResponse(result=[answer])
                value = json.loads(''.join(p['text'] for p in state['pages']))
            assert value['assignment'] == context['assignment']
            event['received_assignment'] = deepcopy(value)
            state['done'] = True
            answer = AIMessage(content=CHILD_FINAL)
        else:
            # A selected native supervision plugin may invoke the same child
            # again. Its follow-up is retained; this fixture still did no review.
            answer = AIMessage(content=CHILD_FINAL)
        event['response'] = answer.model_dump()
        return ModelResponse(result=[answer])


async def capture_coordinator_review_commission(ws, case, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_reviewer_fixture(ws, 'full')
    fixture['goal'] = ('Arrange independent review of both existing report claims against their '
        'respective saved criteria and original sources in the existing snapshot. Define checks '
        'and required materials for both objects. Assignment is not review completion. '
        'Do not change the report.\n' + fixture['original_packet']['commission']['goal'])
    ws.store.set('manifest', {**ws.store.manifest, 'goal': fixture['goal']})
    activate(ws)
    # The historical task_call/assignment remain host-only oracle data. Neither
    # this preparation nor a model wrapper sends them to the Coordinator.
    dump(folder / 'fixture.json', fixture)
    cs, calls, phases, child_events, models = ContentStore(ws.store), [], [], [], {}
    prepared = PreparedCommissionReads(fixture, phases)
    child = UnperformedReviewer(ws, child_events)

    def factory(role):
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]

    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['middleware'] = [*kwargs.get('middleware', []), prepared]
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), child]}
                                  if a['name'] == 'reviewer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        # Preserve the actual native outcome before any derived observer work
        # can fail. Preparation.response is a dict, consumer.response a list.
        dump(folder / 'raw-capture.json', {'case': case, 'fixture': fixture,
            'runtime': runtime, 'raised_error': error, 'phase_events': phases,
            'fake_child_events': child_events, 'native_model_calls': calls})
        tasks = cs.list_objects('DelegatedTask')
        review_tasks = [t for t in tasks if t['payload'].get('review_requirements')]
        finals, observer_errors = [], []
        for index, event in enumerate(phases):
            if event['phase'] != 'unchanged_coordinator_handler' or 'response' not in event:
                continue
            messages = event['response']
            if not isinstance(messages, list) or any(not isinstance(m, dict) or
                    not isinstance(m.get('data'), dict) or not isinstance(m.get('type'), str) for m in messages):
                observer_errors.append({'code': 'C5_OBSERVER_RESPONSE_SHAPE', 'phase_event_index': index})
                continue
            finals.extend(m['data']['content'] for m in messages
                          if m['type'] == 'ai' and not m['data'].get('tool_calls'))
        capture = {'case': case, 'fixture': fixture, 'runtime': runtime, 'raised_error': error,
            'phase_events': phases, 'fake_child_events': child_events, 'native_model_calls': calls,
            'observer_errors': observer_errors,
            'saved_tasks': tasks, 'saved_reviews': cs.list_objects('ReviewRecord'),
            'saved_task_status': [reconcile(cs, t['ref']['id']) for t in review_tasks], 'finals': finals,
            'originals_unchanged': all(cs.read(o['ref']) == o for o in fixture['originals']),
            'host_completion_actions': False, 'semantic_status': 'not_semantically_assessed',
            'limits': ['Initial object reads and the Reviewer child are explicit fake preparation/control.',
                'Coordinator subsequent choices use the unchanged handler and actual native ToolNode.',
                'Historical task/requirements/checker output are host-only oracle data, never prefilled actions.',
                'The child does no review; assignment, execution completeness and verdict acceptance differ.',
                'A missing object is a semantic control; no new runtime goal-coverage guard is assumed.',
                'Any chosen supervision plugin follows the original runtime; no plugin is removed to force success.',
                'Fresh delegation does not validate recovery of an old task, a whole report, or engineering use.']}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
        if observer_errors:
            raise RuntimeError('C5_OBSERVER_RESPONSE_SHAPE: see preserved raw-capture.json')
    return capture
