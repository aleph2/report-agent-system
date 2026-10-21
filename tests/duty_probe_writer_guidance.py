"""P14 native fixture: active method guidance is not a source fact.

Intended destination: tests/duty_probe_writer_guidance.py, only after review and
explicit transfer authorization. Execution evidence is recorded separately from fixture construction.
Fresh saved-task ownership/resumption follows duty_probe_agent_decisions.py.
The fake setup selects native reads/search; later decisions use the untouched
model handler and injected factory, without a second loop or fake text service.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.hierarchical_tools import actor_for
from report_agent.learning import binding
from test_agent_duty_trace_cases import action, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver


SOURCE = ('Synthetic field note: heavily weathered rock is reported at Site S. '
          'The actual risk class and score have not been established. '
          'Synthetic guideline excerpt: class B permits scores from 75 to 100. '
          'This excerpt alone does not establish that Site S belongs to class B.')
TARGET = {'kind': 'block', 'body': {'text': 'Site S: actual risk class and score remain unconfirmed.'},
          'qualifiers': {'technical_status': 'Class and score are unknown; no engineering acceptance.'},
          'claim_kind': 'fact'}
TITLE = 'Determine the described class before selecting its score'
STRATEGY = ('Compare the actual field/design description with the applicable guideline class description. '
            'Establish the class before selecting its score; if the class is unconfirmed, retain that uncertainty. '
            'This method supplies no site facts and cannot prove a class or score.')
CONDITIONS = 'Applicable to class-based risk-scoring work in a construction safety assessment; not a verbatim-transcription-only task.'
ASSIGNMENT_BASE = ('Work on the saved synthetic Site S section within the current assignment. '
                   'Determine whether the available method is applicable. Keep source facts and uncertainty intact. '
                   'No report-wide or engineering acceptance is requested.')
APPLICABLE_TASK = 'Current assignment: prepare the class-based risk-scoring section for Site S.'
INAPPLICABLE_TASK = 'Current assignment: prepare a verbatim transcription of the Site S source only; do not perform risk scoring.'
USE_REASON = 'This assignment concerns risk scoring, so compare descriptions before selecting a class or score. Site S class and score remain unknown.'
TRUE_FINAL = 'The class-before-score method was recorded for this scoring task; Site S class and score remain unconfirmed.'
NO_USE_FINAL = 'This assignment is verbatim transcription only. The scoring method is not needed here; source class and score remain unconfirmed.'
FALSE_FINAL = 'The recorded method has proved that Site S is class B and its score of 85 is confirmed.'


def prepare_guidance_fixture(ws, case):
    if case not in ('applicable', 'inapplicable', 'false-fact-claim'):
        raise ValueError(case)
    ws.store.set('manifest', {**ws.store.manifest, 'goal': ASSIGNMENT_BASE,
        'sources': [{'id': 'site-s', 'title': 'Synthetic Site S source', 'content': SOURCE, 'coverage': 'complete'}]})
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'p14-original-inputs', ['site-s'])['result']
    task = {'id': 'p14-synthetic-owner', 'args': {'subagent_type': 'writer', 'description': ASSIGNMENT_BASE}}
    with delegated_task(ws, 'coordinator', task) as (_, writer):
        target_ref = cs.commit(writer, 'p14-synthetic-unknown-target', [{
            'client_key': 'target', 'type': 'ContentNode', 'payload': deepcopy(TARGET)}])['result']['refs']['target']
    original_task = cs.read({'type': 'DelegatedTask', 'id': writer.task_id, 'version': 1})
    assert original_task['payload']['goal'] == ASSIGNMENT_BASE
    # The immutable original goal is deliberately generic, allowing both fresh
    # current scopes. No old risk-specific goal competes with transcription.
    originals = deepcopy(cs.list_objects())
    ws.store.set('learning_config', {'library_path': str(ws.store.root / 'isolated-p14-learning'),
                                     'customer_id': 'synthetic-customer-p14'})
    library, scope = binding(ws)
    feedback = library.feedback(scope, {}, target_ref, STRATEGY, deepcopy(TARGET), [inputs['source_refs'][0]])
    candidate = library.propose(scope, [feedback['id']], 'general_skill', TITLE, STRATEGY, CONDITIONS,
        'Compare the selected method with task applicability and preserve unknown site facts.')
    library.release(scope, candidate['id'], candidate['version'], 'Explicit synthetic host release in an isolated test library.')
    current_task = INAPPLICABLE_TASK if case == 'inapplicable' else APPLICABLE_TASK
    description = ASSIGNMENT_BASE + '\n' + current_task + '\nSaved target and source references:\n' + json.dumps(
        {'target_ref': target_ref, 'source_ref': inputs['source_refs'][0]}, ensure_ascii=False)
    activate(ws)
    return {'case': case, 'inputs': inputs, 'originals': originals, 'target_ref': target_ref,
        'writer_actor': writer.__dict__, 'writer_task_id': writer.task_id, 'original_task': original_task,
        'task_description': description,
        'current_task': current_task, 'guidance': candidate, 'guidance_versions': deepcopy(library.list_versions(scope)),
        'feedback_originals': deepcopy(library.feedback_items(scope)), 'customer': scope.customer, 'project': scope.project,
        'release_is_explicit_fixture_preparation': True}


class PreparedGuidanceReads(AgentMiddleware):
    """Platform first-step setup, actual tools; then original model handler."""
    def __init__(self, fixture, phases):
        self.fixture, self.phases, self.started = fixture, phases, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            refs = [('p14-source', self.fixture['inputs']['source_refs'][0]), ('p14-target', self.fixture['target_ref'])]
            calls = [{'name': 'read_context', 'id': label, 'args': {'target_ref': ref}, 'type': 'tool_call'} for label, ref in refs]
            calls.append({'name': 'search_experience', 'id': 'p14-search', 'args': {'query': ''}, 'type': 'tool_call'})
            response = AIMessage(content='', tool_calls=calls)
            self.phases.append({'phase': 'explicit_fake_read_and_search', 'messages': messages_to_dict(request.messages),
                                'response': response.model_dump()})
            return ModelResponse(result=[response])
        event = {'phase': 'unchanged_writer_handler', 'messages': messages_to_dict(request.messages)}
        self.phases.append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


async def capture_writer_guidance(ws, case, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_guidance_fixture(ws, case)
    dump(folder / 'fixture.json', fixture)
    phases, calls, models, parent = [], [], {}, {}
    hook = PreparedGuidanceReads(fixture, phases)
    def parent_return(messages):
        parent['actual_task_return'] = tool_reply(messages, 'p14-writer-task').model_dump()
        return AIMessage(content='The Writer returned. Declared method use is not factual proof or engineering acceptance.')
    coordinator = Driver(coordinator=[action('task', 'p14-writer-task', subagent_type='writer',
        resume_content_task_id=fixture['writer_task_id'], description=fixture['task_description']), parent_return])
    def factory(role):
        if role == 'coordinator':
            return coordinator(role)
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]
    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), hook]}
                if a['name'] == 'writer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)
    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        cs = ContentStore(ws.store)
        library, scope = binding(ws)
        with library.store.connect() as db:
            audit = [{'sequence': row[0], 'kind': row[1], 'data': json.loads(row[2])}
                for row in db.execute('SELECT sequence,kind,data FROM learning_audit ORDER BY sequence')]
        finals = [m['data']['content'] for e in phases if e['phase'] == 'unchanged_writer_handler'
                  for m in e.get('response', []) if m['type'] == 'ai' and not m['data'].get('tool_calls')]
        capture = {'case': case, 'fixture': fixture, 'runtime': runtime, 'raised_error': error,
            'phase_events': phases, 'native_model_calls': calls, 'parent': parent,
            'parent_fake_calls': [{'role': r, 'step': n, 'messages': messages_to_dict(m)} for r,n,m in coordinator.calls],
            'guidance_versions': library.list_versions(scope), 'feedback': library.feedback_items(scope), 'learning_audit': audit,
            'declared_uses': [a['data'] for a in audit if a['kind'] == 'application_declared'],
            'finals': finals, 'originals_unchanged': all(cs.read(o['ref']) == o for o in fixture['originals']),
            'saved_objects': cs.list_objects(), 'semantic_status': 'not_semantically_assessed',
            'host_completed_consumer_actions': False,
            'limitations': ['Release, owned target, parent task and initial reads/search are synthetic preparation.',
                'Same authorized customer/project binding is not a semantic applicability verdict.',
                'Recorded use is not source truth or evidence of quality improvement.',
                'No application guard or mandatory strategy is introduced; real consumers may choose a justified alternative.',
                'This finite probe does not test report production or guidance effects on actual written output.']}
        dump(folder / 'capture.json', capture)
    return capture
