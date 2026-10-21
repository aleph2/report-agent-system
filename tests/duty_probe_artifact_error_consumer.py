"""P12 native Reviewer continuation after a recorded artifact-output refusal.

Preparation uses real public tools and actual synthetic Office/PNG files. Only
the four preparation decisions, first vision response and first checker response
are fake. The checker fixture variant is explicit; legacy is the default.
Later decisions/services use the supplied factories without a loop,
retry, completion substitution, or modification of the captured tool error.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_visual_packets import prepare_visual
from report_agent import deep_runtime
from report_agent.content_tasks import bound_actor
from report_agent.hierarchical_tools import actor_for
from report_agent.task_supervision import reconcile
from test_agent_duty_artifact_failures import rebind_strings
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model
from test_deep_runtime import Driver
from test_vision import VisionModel


ARCHIVE = Path(__file__).resolve().parents[1] / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/live-r3/visual-artifact-pair'
ARCHIVE_HASHES = {
    'model-output.json': '861a1009ca4ec565693d0a98f60bd59c75b7a90c714c3e2b81809d77654b8a53',
    'independent-input.json': 'dfdc75731ff95b8b5936491ef660ffbf646aaafc7cb8085439026ce741401b09',
    'visual-preparation.json': '8aeb5e180cc4f72b446f302806a3120bc0d5ef82f6fb168bc277cd608020b6ee',
}


def load_error_fixture(folder):
    archived = {}
    for name, sha in ARCHIVE_HASHES.items():
        path = ARCHIVE / name
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == sha, path
        (folder / ('original-' + name)).write_bytes(raw)
        archived[name] = json.loads(raw)
    message = archived['model-output.json']
    packet = json.loads(archived['independent-input.json'][1][1])
    output = json.loads(message['content'])
    assert [c['requirement_index'] for c in output['items'][0]['check_results']] == [0, 0]
    return {'original_message': message, 'original_packet': packet, 'original_output': output,
        'original_content_sha256': hashlib.sha256(message['content'].encode()).hexdigest(),
        'archive_files': [{'path': str(ARCHIVE / n), 'sha256': s} for n, s in ARCHIVE_HASHES.items()],
        'limits': 'Original raw files unchanged. Legacy replay changes temporary object/receipt UUIDs only; an explicit current-contract variant also projects the one recorded artifact_refs path.'}


def analysis_state(ws):
    with ws.store.connect() as db:
        return {'analyses': {r[0]: json.loads(r[1]) for r in db.execute('SELECT operation,data FROM analyses')},
            'reservations': {r[0]: json.loads(r[1]) for r in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'bounded_review_attempt:%' OR key LIKE 'artifact_text_work:%'")}}


class RecordedFailureService:
    def __init__(self, fixture, prepared, held, factory, fixture_variant):
        self.fixture, self.prepared, self.held, self.factory = fixture, prepared, held, factory
        assert fixture_variant in {'legacy_identity_only', 'current_contract_duplicate'}
        self.fixture_variant = fixture_variant
        self.calls, self.consumer, self.backend = [], False, None
        self.identity = Model()
        self.identity.model_name = 'recorded-R3-artifact-failure-fixture-not-live'

    def current(self):
        if not self.consumer:
            return self.identity
        if self.backend is None:
            self.backend = self.factory('text_tool')
        return self.backend

    def __getattr__(self, name):
        return getattr(self.current(), name)

    async def ainvoke(self, messages):
        entry = {'origin': 'consumer_factory' if self.consumer else 'recorded_R3_fixture',
                 'input': deepcopy(messages)}
        self.calls.append(entry)
        if self.consumer:
            response = await self.current().ainvoke(messages)
        else:
            assert len(self.calls) == 1, 'No repeated fixture checker response'
            content = messages[-1].content if hasattr(messages[-1], 'content') else messages[-1][1]
            packet = json.loads(content)
            old = self.fixture['original_packet']
            req, old_req = packet['requirements'][0], old['requirements'][0]
            assert req['required_checks'] == old_req['required_checks']
            identities = {old['snapshot_ref']['id']: packet['snapshot_ref']['id'],
                old_req['target_ref']['id']: req['target_ref']['id'],
                old_req['criterion_ref']['id']: req['criterion_ref']['id'],
                old_req['artifact_refs'][0]['id']: req['artifact_refs'][0]['id'],
                old_req['required_read_refs'][0]['id']: req['required_read_refs'][0]['id'],
                old['evidence'][2]['actual_observation']['source']['export_ref']['id']: self.prepared['export_ref']['id'],
                **{a['receipt_id']: b['receipt_id'] for a, b in zip(old['evidence'], packet['evidence'], strict=True)}}
            changes = []
            replay = rebind_strings(self.fixture['original_output'], identities, changes)
            original_rebound = deepcopy(replay)
            projection = None
            if self.fixture_variant == 'current_contract_duplicate':
                replay['items'][0]['artifact_refs'] = deepcopy(req['artifact_refs'])
                assert replay['items'][0]['artifact_refs']
                assert all(r['type'] in {'ExportArtifact', 'RenderArtifact'}
                           for r in replay['items'][0]['artifact_refs'])
                restored = deepcopy(replay)
                restored['items'][0]['artifact_refs'] = original_rebound['items'][0]['artifact_refs']
                assert restored == original_rebound
                projection = {'path': '$.items[0].artifact_refs',
                    'before': original_rebound['items'][0]['artifact_refs'],
                    'after': replay['items'][0]['artifact_refs']}
            assert [c['requirement_index'] for c in replay['items'][0]['check_results']] == [0, 0]
            self.held.update(checker_packet=packet, checker_output=replay,
                original_rebound_output=original_rebound, compatibility_projection=projection,
                fixture_variant=self.fixture_variant,
                identity_map=identities, identity_rebindings=changes)
            response = AIMessage(content=json.dumps(replay, ensure_ascii=False))
        entry['raw_response'] = response.model_dump()
        return response


class PrepareArtifactFailure(AgentMiddleware):
    def __init__(self, ws, prepared, service, events, held):
        self.ws, self.prepared, self.service = ws, prepared, service
        self.events, self.held, self.step = events, held, 0

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'explicit_fake_preparation' if self.step < 4 else 'native_reviewer_handler',
            'request_messages': messages_to_dict(request.messages),
            'actual_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]}
        self.events.append(event)
        if self.step == 0:
            self.held['actor'] = asdict(bound_actor(self.ws, 'reviewer', actor_for('reviewer')))
            self.held['receipts'] = []
            response = action('read_context', 'table', target_ref=self.prepared['refs']['table'])
        elif self.step == 1:
            value = result_value(tool_reply(request.messages, 'table'))
            assert value['ok'], value
            self.held['receipts'].append(value['receipt_id'])
            response = action('read_context', 'standard', target_ref=self.prepared['refs']['standard_source'])
        elif self.step == 2:
            value = result_value(tool_reply(request.messages, 'standard'))
            assert value['ok'], value
            self.held['receipts'].append(value['receipt_id'])
            response = action('inspect_rendered_page', 'page', render_ref=self.prepared['render_ref'],
                page=1, question=self.prepared['question'])
        elif self.step == 3:
            value = result_value(tool_reply(request.messages, 'page'))
            assert value['ok'] and value['result']['status'] == 'observed', value
            assert value['result']['source']['render_ref'] == self.prepared['render_ref']
            self.held['receipts'].append(value['receipt_id'])
            self.held['vision'] = value
            args = {'operation_id': 'r3-duplicate-output-replay', 'scope_ids': ['r3-visible-table'],
                'observation_receipts': list(self.held['receipts'])}
            self.held['actual_caller_args'] = args
            response = action('perform_assigned_artifact_review', 'compare', **args)
        else:
            if self.step == 4:
                self.held['first_consumer_error'] = tool_reply(request.messages, 'compare').model_dump()
                self.held['state_before_consumer'] = analysis_state(self.ws)
                self.held['review_records_before_consumer'] = self.prepared['cs'].list_objects('ReviewRecord')
                self.held['status_before_consumer'] = reconcile(self.prepared['cs'], self.held['actor']['task_id'])
            self.step += 1
            self.service.consumer = True
            result = await handler(request)
            event['response'] = messages_to_dict(result.result)
            return result
        self.step += 1
        event['response'] = response.model_dump()
        return ModelResponse(result=[response])


async def capture_artifact_error_consumer(ws, folder, model_factory, *, vision_client_factory,
                                        fixture_variant='legacy_identity_only'):
    """Caller supplies any later real services and owns their budgets/lifecycle.

    The public inspect_rendered_page owns/closes each vision client as usual.
    This helper only provides a fake client before the consumer begins. Later
    calls never fall back to a fake reply, even if the chosen recovery fails.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = load_error_fixture(folder)
    prepared = await prepare_visual(ws, folder)
    cs = prepared['cs']
    originals = deepcopy(cs.list_objects())
    events, calls, models, held, parent, vision_routes = [], [], {}, {}, {}, []
    service = RecordedFailureService(fixture, prepared, held, model_factory, fixture_variant)
    hook = PrepareArtifactFailure(ws, prepared, service, events, held)
    initial_vision = VisionModel(content=fixture['original_packet']['evidence'][2]['actual_observation']['observation'])

    def vision_factory():
        origin = 'consumer_factory' if service.consumer else 'recorded_vision_fixture'
        vision_routes.append({'origin': origin})
        if service.consumer:
            return vision_client_factory()
        assert len(vision_routes) == 1, 'No repeated fixture vision response'
        return initial_vision

    def parent_result(messages):
        parent['task_return'] = tool_reply(messages, prepared['call']['id']).model_dump()
        return action('read_task_supervision', 'parent-supervision')

    def parent_finish(messages):
        parent['supervision_message'] = tool_reply(messages, 'parent-supervision').model_dump()
        parent['supervision'] = result_value(tool_reply(messages, 'parent-supervision'))
        return AIMessage(content='Reviewer statement and saved remaining scope recorded separately; no host acceptance or retry.')

    coordinator = Driver(coordinator=[AIMessage(content='', tool_calls=[prepared['call']]), parent_result, parent_finish])

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
            if a['name'] == 'reviewer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build), patch(
                'report_agent.deep_models.configured_vision_client', vision_factory):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        records = cs.list_objects('ReviewRecord')
        current_status = reconcile(cs, held['actor']['task_id']) if held.get('actor') else None
        oracle = {'review_records': records, 'current_status': current_status,
            'recorded_checker_has_duplicate_indexes': bool(held.get('checker_output')) and
                [c['requirement_index'] for c in held['checker_output']['items'][0]['check_results']] == [0, 0],
            'original_objects_unchanged': all(cs.read(o['ref']) == o for o in originals),
            'analysis_state_after': analysis_state(ws), 'semantic_status': 'needs_semantic_review',
            'status': 'no_saved_review_incomplete' if not records and current_status and not current_status['execution_complete']
                else 'saved_state_requires_review',
            'limits': 'A normal final message is not a saved review or engineering acceptance. Natural-language truth is not inferred here.'}
        capture = {'fixture': fixture, 'fixture_variant': fixture_variant,
            'runtime_result': runtime, 'raised_error': error,
            'phase_events': events, 'native_model_calls': calls, 'text_service_calls': service.calls,
            'host_diagnostic_held': held, 'parent': parent, 'oracle': oracle,
            'vision_routes': vision_routes, 'fixture_vision_calls': len(initial_vision.calls),
            'fixture_vision_closed': initial_vision.closed,
            'fixture_preparation_actions': sum(e['phase'] == 'explicit_fake_preparation' and 'response' in e for e in events),
            'host_completion_actions': False,
            'limits': ['The first four Reviewer actions, Coordinator actions, initial vision/checker replies are fake preparation.',
                'All subsequent Reviewer/model decisions use the unchanged native handler and supplied factories.',
                'R3 raw bytes are retained. Default legacy replay changes identities only. Explicit current_contract_duplicate projects only assigned artifact_refs; duplicate indexes and every other field remain unchanged.',
                'No provider, retry, handoff requirement, guard or semantic verdict is added by this helper.']}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
    return capture
