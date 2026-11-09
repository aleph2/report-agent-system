"""W06: recorded producer fixture followed by the unchanged native Writer loop.

Test-only hook verified in the installed LangChain middleware/types.py:598
(AgentMiddleware.awrap_model_call), :272 (ModelResponse), and DeepAgents
graph.py:272 (create_deep_agent), under the report-agent-system WSL venv.
Only the first Writer model step is a fixture. Its process_report_content call
runs in the real ToolNode. Later steps use handler(request) without rewriting
the request, tools, model or return. No stored body is inserted into a prompt.
"""
from report_agent import issue_state
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from duty_probe_agent_decisions import dump, traced_model
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import Driver, invoke


ARCHIVE = Path(__file__).resolve().parents[1] / 'tests/fixtures/historical-duty/real/live-r2'
CASES = ('full-adopt', 'missing-adopt', 'missing-read-handoff', 'missing-incomplete')


def load_recorded_fixture(case):
    family = 'full' if case == 'full-adopt' else 'missing'
    folder = ARCHIVE / ('text-' + family)
    paths = [folder / name for name in ('model-output.json', 'independent-input.json', 'result.json')]
    raw, old_input, old_result = [json.loads(p.read_text('utf-8')) for p in paths]
    packet = json.loads(old_input[-1][1])
    material = packet['evidence'][0]
    source = material['observation']['source']
    return {'case': case, 'scenario_family': family, 'recorded_raw_content': raw['content'],
        'source': {'id': source['id'], 'title': source['title'], 'coverage': source['coverage'],
                   'content': material['observation']['blocks'][0]['text']},
        'objective': packet['objective'], 'goal': packet['commission']['goal'],
        'source_selection': material['selection'],
        'expected_payloads': old_result['tool_result']['payloads'],
        'expected_generation_notes': old_result['tool_result']['generation_notes'],
        'archive_files': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        'limit': 'Related recorded scenarios, not a one-variable semantic pair. Historic usage is not new usage.'}


class OneRecordedProducer:
    """The actual client captured by business_tools; only its first call is fake."""
    def __init__(self, raw, factory):
        self.recorded, self.factory, self.calls = Model(raw), factory, []
        self.recorded.model_name = 'recorded-R2-producer-fixture-not-live'
        self.consumer_started = False
        self.backend = None

    def __getattr__(self, name):
        if self.consumer_started:
            if self.backend is None:
                self.backend = self.factory('text_tool')
            return getattr(self.backend, name)
        return getattr(self.recorded, name)

    async def ainvoke(self, messages):
        fixture = not self.calls
        if fixture:
            assert not self.consumer_started, 'Recorded preparation must precede the consumer.'
            backend = self.recorded
        else:
            assert self.consumer_started, 'Only the initial producer belongs to fixture preparation.'
            if self.backend is None:
                self.backend = self.factory('text_tool')
            backend = self.backend
        from report_agent.evidence_analysis import model_identity
        record = {'origin': 'recorded_R2_fixture' if fixture else 'injected_consumer_text_service',
                  'backend_type': type(backend).__name__, 'backend_model': getattr(backend, 'model_name', None),
                  'model_identity': model_identity(backend),
                  'input': deepcopy(messages)}
        self.calls.append(record)
        response = await backend.ainvoke(messages)
        record['raw_response'] = response.model_dump()
        return response


class PrepareRecordedCandidate(AgentMiddleware):
    def __init__(self, fixture, service, events):
        self.fixture, self.service, self.events = fixture, service, events
        self.prepared = False

    async def awrap_model_call(self, request, handler):
        if not self.prepared:
            self.prepared = True
            action = invoke('process_report_content', operation_id='recorded-producer-fixture',
                object_type='ContentNode', output_count=1, objective=self.fixture['objective'],
                source_selections=[self.fixture['source_selection']])
            self.events.append({'phase': 'fixture_action', 'request_messages': messages_to_dict(request.messages),
                                'fixture_action': action.model_dump()})
            return ModelResponse(result=[action])
        self.service.consumer_started = True
        self.events.append({'phase': 'unchanged_consumer_handler', 'request_messages': messages_to_dict(request.messages),
            'native_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]})
        return await handler(request)


def assess(ws, fixture):
    """Read-only finite oracle. Exact storage does not establish model semantics."""
    cs = ContentStore(ws.store)
    nodes = cs.list_objects('ContentNode')
    exact = [n for n in nodes if n['payload'] == fixture['expected_payloads'][0]]
    issues = deepcopy(issue_state.get_report_issues(ws.store, []))
    handoffs = cs.list_objects('HandlingRecord')
    original_ok = all(cs.read(item['ref']) == item for item in fixture['originals'])
    untouched = not cs.list_objects('ReviewRecord') and not cs.list_objects('ExportArtifact')
    if any(n['payload'] != fixture['expected_payloads'][0] for n in nodes):
        status = 'saved_content_differs_needs_review'
    elif exact:
        status = 'exact_qualified_candidate_saved'
    elif issues or handoffs:
        status = 'unresolved_issue_saved'
    else:
        status = 'incomplete'
    return {'status': status, 'nodes': nodes, 'issues': issues, 'handoffs': handoffs, 'exact_candidates': exact,
            'originals_unchanged': original_ok, 'no_review_or_export': untouched,
            'semantic_limit': 'No autonomous decision or rendering pass inferred from fake controls.'}


async def capture_writer_adoption(ws, case, folder, model_factory):
    if case not in CASES:
        raise ValueError(case)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = load_recorded_fixture(case)
    ws.store.set('manifest', {**ws.store.manifest, 'goal': fixture['goal'], 'sources': [fixture['source']]})
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'recorded-fixture-inputs', ['s'])['result']
    fixture['originals'] = [deepcopy(cs.read(ref)) for ref in [inputs['requirement_ref'], *inputs['source_refs']]]
    activate(ws)
    dump(folder / 'fixture.json', fixture)
    service = OneRecordedProducer(fixture['recorded_raw_content'], model_factory)
    events, calls, models = [], [], {}
    hook = PrepareRecordedCandidate(fixture, service, events)
    coordinator = Driver(coordinator=[invoke('task', subagent_type='writer', description=fixture['goal']),
        AIMessage(content='Delegated Writer returned. No host adoption or review acceptance is inferred.')])

    def factory(role):
        if role == 'coordinator':
            return coordinator(role)
        if role == 'text_tool':
            return service
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]

    original_builder = deep_runtime.create_deep_agent
    def with_fixture_hook(*args, **kwargs):
        kwargs['subagents'] = [{**agent, 'middleware': [*agent.get('middleware', []), hook]}
                              if agent['name'] == 'writer' else agent for agent in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', with_fixture_hook):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = repr(exc)
    finally:
        with ws.store.connect() as db:
            receipts = [{'key': row[0], 'value': json.loads(row[1])} for row in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'text_work_receipt:%'")]
        # Diagnostic only: these records are never added to a model request.
        oracle = assess(ws, fixture)
        capture = {'case': case, 'runtime': runtime, 'raised_error': error, 'oracle': oracle,
            'phase_events': events, 'native_model_calls': calls, 'text_service_calls': service.calls,
            'host_diagnostic_receipts': receipts,
            'fixture_coordinator_calls': [{'role': r, 'step': n, 'messages': messages_to_dict(m)} for r, n, m in coordinator.calls],
            'fixture_producer_calls': sum(c['origin'] == 'recorded_R2_fixture' for c in service.calls),
            'later_text_calls': sum(c['origin'] != 'recorded_R2_fixture' for c in service.calls),
            'host_completion_actions': False,
            'limits': ['Fake controls do not prove autonomous semantic choices.',
                       'No document export; known body.footnote rendering defect remains open.',
                       'Initial process action is explicit fixture preparation, not a Writer decision.']}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events(),
                                         'issues': issue_state.get_report_issues(ws.store, [])})
    return capture
