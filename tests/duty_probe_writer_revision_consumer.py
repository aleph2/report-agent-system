"""P16 recorded R7 revision, followed by the unchanged native Writer handler.

The three preparatory Writer actions and their two independent responses are
explicit fixtures. ToolNode creates both receipts and the owned v1. There is
no host-created ToolMessage, receipt, adoption, provider, retry, or agent loop.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import Driver


ARCHIVE = Path(__file__).resolve().parents[1] / 'tests/fixtures/historical-duty/real/live-r7/text-revision-process'
ARCHIVE_HASHES = {
    'model-output.json': '20496f10683e9e6f7bfb483b73878236f58a2100247e76c4bc1b2bc17971330b',
    'independent-input.json': '1a3465ca971a94eb47d6cd1b2094cb22104e4d7a51ba601534261a3ae7ef7508',
    'result.json': '08583b4bbb28589f9db98666a18c0dd6a3e2b556a689f379e721beaa3e4bc660',
}


def load_revision_fixture():
    archived = {}
    for name, expected in ARCHIVE_HASHES.items():
        path = ARCHIVE / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path
        archived[name] = json.loads(path.read_text('utf-8'))
    packet = json.loads(archived['independent-input.json'][-1][1])
    objects = [e['object'] for e in packet['evidence'] if e['kind'] == 'saved_object']
    target = next(o for o in objects if o['ref']['type'] == 'ContentNode')
    sources = [o for o in objects if o['ref']['type'] == 'SourceArtifact']
    raw = archived['model-output.json']['content']
    delta = json.loads(raw)['payloads'][0]['qualifiers']
    expected = {**deepcopy(target['payload']), 'qualifiers': delta}
    assert archived['result.json']['tool_result']['payloads'] == [expected]
    return {'goal': packet['commission']['goal'], 'objective': packet['objective'],
        'initial_payload': target['payload'], 'expected_payload': expected,
        'expected_generation_notes': json.loads(raw).get('generation_notes', []),
        'recorded_raw_content': raw, 'recorded_raw_content_sha256': hashlib.sha256(raw.encode()).hexdigest(),
        'archived_packet': packet, 'archived_target': target, 'archived_sources': sources,
        'archive_files': [{'path': str(ARCHIVE / name), 'sha256': sha} for name, sha in ARCHIVE_HASHES.items()]}


class PreparedRevisionService:
    """Only the initial and recorded revision responses are fixtures."""
    def __init__(self, fixture, factory):
        self.factory, self.calls, self.mode, self.backend = factory, [], 'initial', None
        self.initial = Model(json.dumps(fixture['initial_payload'], ensure_ascii=False))
        self.initial.model_name = 'synthetic-initial-node-fixture-not-live'
        self.recorded = Model(fixture['recorded_raw_content'])
        self.recorded.model_name = 'recorded-R7-revision-fixture-not-live'

    def current(self):
        if self.mode == 'initial':
            return self.initial
        if self.mode == 'revision':
            return self.recorded
        if self.backend is None:
            self.backend = self.factory('text_tool')
        return self.backend

    def __getattr__(self, name):
        return getattr(self.current(), name)

    async def ainvoke(self, messages):
        from report_agent.evidence_analysis import model_identity
        if self.mode != 'consumer':
            assert len(self.calls) == (0 if self.mode == 'initial' else 1), 'No fixture replay'
        backend = self.current()
        entry = {'origin': self.mode, 'input': deepcopy(messages), 'model': model_identity(backend)}
        self.calls.append(entry)
        response = await backend.ainvoke(messages)
        entry['raw_response'] = response.model_dump()
        return response


class PrepareRevision(AgentMiddleware):
    def __init__(self, ws, fixture, service, events, held):
        self.ws, self.fixture, self.service = ws, fixture, service
        self.events, self.held, self.step = events, held, 0

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'explicit_fake_preparation' if self.step < 3 else 'native_writer_handler',
            'request_messages': messages_to_dict(request.messages),
            'actual_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]}
        self.events.append(event)
        if self.step == 0:
            response = action('process_report_content', 'initial-producer', operation_id='synthetic-original-node',
                objective='Record the supplied synthetic arithmetic statement and its qualifications.',
                object_type='ContentNode', input_refs=self.fixture['source_refs'])
        elif self.step == 1:
            actual = tool_reply(request.messages, 'initial-producer')
            assert actual.status == 'success', actual
            self.held['initial_public'] = result_value(actual)
            receipt = self.held['initial_public']['text_work_id']
            self.held['initial_receipt_before'] = deepcopy(self.ws.store.get('text_work_receipt:' + receipt))
            response = action('save_text_node', 'initial-adopt', operation_id='synthetic-original-adopt',
                              text_work_id=receipt, text_work_index=0)
        elif self.step == 2:
            actual = tool_reply(request.messages, 'initial-adopt')
            assert actual.status == 'success', actual
            self.held['target'] = result_value(actual)['result']['refs']['text']
            self.held['original_node'] = deepcopy(ContentStore(self.ws.store).read(self.held['target']))
            assert self.held['original_node']['payload'] == self.fixture['initial_payload']
            self.held['ref_rebinding'] = {'archived_target': self.fixture['archived_target']['ref'],
                'fresh_target': self.held['target'], 'archived_actor': self.fixture['archived_packet']['actor'],
                'fresh_owner': self.held['original_node']['owner_id'],
                'fresh_task_id': self.held['original_node']['task_id']}
            self.service.mode = 'revision'
            response = action('process_report_content', 'revision-producer',
                operation_id='synthetic-qualifier-candidate', objective=self.fixture['objective'],
                object_type='ContentNode', input_refs=self.fixture['source_refs'],
                revision={'scope': 'qualifiers', 'targets': [self.held['target']]})
        else:
            if self.step == 3:
                actual = tool_reply(request.messages, 'revision-producer')
                self.held['revision_public_message'] = actual.model_dump()
                if actual.status == 'success':
                    self.held['revision_public'] = result_value(actual)
                    receipt = self.held['revision_public']['text_work_id']
                    self.held['revision_receipt_before'] = deepcopy(self.ws.store.get('text_work_receipt:' + receipt))
            self.step += 1
            self.service.mode = 'consumer'
            result = await handler(request)
            event['response'] = messages_to_dict(result.result)
            return result
        self.step += 1
        event['response'] = response.model_dump()
        return ModelResponse(result=[response])


def observe_revision(ws, fixture, held):
    """Finite read-only storage oracle, distinct from model judgment or acceptance."""
    cs = ContentStore(ws.store)
    target = held.get('target')
    nodes = cs.list_objects('ContentNode')
    with ws.store.connect() as db:
        head = db.execute('SELECT version FROM content_heads WHERE type=? AND id=?',
            (target['type'], target['id'])).fetchone() if target else None
    current = cs.read({**target, 'version': head[0]}) if head else None
    original_ok = bool(target) and cs.read(target) == held['original_node']
    sources_ok = all(cs.read(o['ref']) == o for o in fixture['originals'])
    exact = bool(current and target and current['ref']['version'] == target['version'] + 1
        and current['payload'] == fixture['expected_payload']
        and current['owner_id'] == held['original_node']['owner_id']
        and current['task_id'] == held['original_node']['task_id']
        and current['previous_ref'] == target)
    if exact and original_ok and sources_ok:
        status = 'exact_revision_saved'
    elif current == held.get('original_node') and original_ok and sources_ok:
        status = 'revision_not_adopted'
    else:
        status = 'changed_or_incomplete_needs_review'
    receipts = {}
    for prefix in ('initial', 'revision'):
        public = held.get(prefix + '_public')
        if public:
            receipts[prefix] = {'unchanged': ws.store.get('text_work_receipt:' + public['text_work_id'])
                == held.get(prefix + '_receipt_before')}
    return {'status': status, 'target': target, 'current_node': current, 'nodes': nodes,
        'original_v1_unchanged': original_ok, 'source_originals_unchanged': sources_ok,
        'receipt_states': receipts, 'semantic_status': 'needs_semantic_review',
        'no_review_or_export': not cs.list_objects('ReviewRecord') and not cs.list_objects('ExportArtifact')}


async def capture_writer_revision_consumer(ws, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = load_revision_fixture()
    sources = [{'id': o['payload']['source_id'], 'title': o['payload']['source_metadata']['title'],
        'content': o['payload']['content'], 'coverage': o['payload']['coverage']} for o in fixture['archived_sources']]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': fixture['goal'], 'sources': sources})
    cs = ContentStore(ws.store)
    imported = cs.import_inputs(actor_for('coordinator'), 'revision-fixture-inputs', [s['id'] for s in sources])['result']
    fixture['source_refs'] = imported['source_refs']
    fixture['source_ref_rebinding'] = [{'archived': old['ref'], 'fresh': new}
        for old, new in zip(fixture['archived_sources'], fixture['source_refs'], strict=True)]
    fixture['originals'] = [deepcopy(cs.read(r)) for r in [imported['requirement_ref'], *fixture['source_refs']]]
    activate(ws)
    dump(folder / 'fixture.json', fixture)
    events, calls, models, held, parent = [], [], {}, {}, {}
    service = PreparedRevisionService(fixture, model_factory)
    hook = PrepareRevision(ws, fixture, service, events, held)

    def parent_result(messages):
        parent['task_return'] = tool_reply(messages, 'revision-consumer-task').model_dump()
        return AIMessage(content='Writer outcome received; no host adoption or semantic acceptance added.')

    coordinator = Driver(coordinator=[action('task', 'revision-consumer-task', subagent_type='writer',
        description=fixture['goal']), parent_result])

    def factory(role):
        if role == 'coordinator':
            return coordinator(role)
        if role == 'text_tool':
            return service
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]

    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
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
        capture = {'fixture': fixture, 'runtime_result': runtime, 'raised_error': error,
            'phase_events': events, 'native_model_calls': calls, 'text_service_calls': service.calls,
            'host_diagnostic_held': held, 'parent': parent, 'oracle': observe_revision(ws, fixture, held),
            'fixture_preparation_actions': sum(e['phase'] == 'explicit_fake_preparation' and 'response' in e for e in events),
            'expected_preparation_actions': 3, 'host_completion_actions': False,
            'limits': ['Initial producer, v1 adoption and revision request are explicit fake preparation through native ToolNode.',
                'The R7 response is replayed unchanged into a fresh task, not continuation of the old paid run.',
                'Subsequent Writer decisions and independent services use the injected factory without substituted completion.',
                'Stored diagnostics are not inserted into Writer input; full bodies count only when actually recovered.',
                'A saved revision is not semantic, rendering, report or engineering acceptance.']}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
    return capture
