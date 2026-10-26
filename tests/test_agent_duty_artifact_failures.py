"""Public Reviewer replay of a real checker output failure, with no paid calls.

Original R3 response bytes are retained. New temporary object/receipt identities
are explicitly rebound; this is trace-inspired replay, not an exact-identity run.
The original duplicate [0, 0] check indexes are never repaired here.
"""
from copy import deepcopy
import hashlib
import inspect
from importlib.metadata import version
import json
import os
from pathlib import Path
import traceback

from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage
from pydantic import ValidationError
import pytest

from duty_probe_visual_packets import prepare_visual
from report_agent.content_models import ReviewSubmission
from report_agent.deep_runtime import run_report
from test_agent_duty_learning_failures import tool_message
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline
from test_vision import VisionModel


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / 'tests/fixtures/historical-duty/real/live-r3/visual-artifact-pair'


def rebind_strings(value, identities, changes, path='$'):
    if isinstance(value, dict):
        return {k: rebind_strings(v, identities, changes, path + '.' + k) for k, v in value.items()}
    if isinstance(value, list):
        return [rebind_strings(v, identities, changes, f'{path}[{i}]') for i, v in enumerate(value)]
    if isinstance(value, str):
        result = value
        for old, new in identities.items():
            result = result.replace(old, new)
        if result != value:
            changes.append({'path': path, 'before': value, 'after': result})
        return result
    return value


async def test_received_artifact_output_error_is_not_attributed_to_valid_reviewer_arguments(ws, monkeypatch, request):
    import langgraph.prebuilt.tool_node as tool_node
    base = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro')))
    folder = base / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    originals = {}
    for name in ('model-output.json', 'independent-input.json', 'visual-preparation.json'):
        raw = (ORIGINAL / name).read_bytes()
        (folder / ('original-' + name)).write_bytes(raw)
        originals[name] = {'source': str(ORIGINAL / name), 'sha256': hashlib.sha256(raw).hexdigest()}
    original_message = json.loads((ORIGINAL / 'model-output.json').read_text())
    original_output = json.loads(original_message['content'])
    old_packet = json.loads(json.loads((ORIGINAL / 'independent-input.json').read_text())[1][1])
    assert [c['requirement_index'] for c in original_output['items'][0]['check_results']] == [0, 0]
    with pytest.raises(ValidationError) as original_error:
        ReviewSubmission.model_validate(original_output)
    prepared = await prepare_visual(ws, folder)
    cs, refs = prepared['cs'], prepared['refs']
    observed = {'originals': originals, 'original_content_sha256': hashlib.sha256(original_message['content'].encode()).hexdigest(),
        'replay_kind': 'Synthetic current-contract derivative: identities rebound and artifact_refs projected to assigned render refs; original duplicate indexes and all other fields preserved.',
        'original_output_errors': original_error.value.errors(include_url=False, include_context=False),
        'original_response_usage_not_new_usage': original_message['usage_metadata'],
        'paid_calls': 0, 'receipts': [], 'actual_exception_constructions': []}
    # Real actual image goes through the public vision entry. Only the SDK reply
    # is replayed, with its current-task observation receipt made by the program.
    service = VisionModel(content=old_packet['evidence'][2]['actual_observation']['observation'])
    monkeypatch.setattr('report_agent.deep_models.configured_vision_client', lambda: service)
    constructor = tool_node.ToolInvocationError.__init__

    def observe_error(self, tool_name, source, tool_kwargs, filtered_errors=None):
        constructor(self, tool_name, source, tool_kwargs, filtered_errors)
        if tool_name == 'perform_assigned_artifact_review':
            observed['actual_exception_constructions'].append({'tool_name': tool_name, 'source_schema': source.title,
                'source_errors': source.errors(include_url=False, include_context=False),
                'tool_kwargs': deepcopy(tool_kwargs), 'formatted_message': self.message,
                'stack': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                          for f in traceback.extract_stack()[-20:]]})

    monkeypatch.setattr(tool_node.ToolInvocationError, '__init__', observe_error)

    def read_standard(messages):
        response = result_value(tool_reply(messages, 'table'))
        assert response['ok'], response
        observed['receipts'].append(response['receipt_id'])
        return action('read_context', 'standard', target_ref=refs['standard_source'])

    def inspect_page(messages):
        response = result_value(tool_reply(messages, 'standard'))
        assert response['ok'], response
        observed['receipts'].append(response['receipt_id'])
        return action('inspect_rendered_page', 'page', render_ref=prepared['render_ref'], page=1, question=prepared['question'])

    def compare(messages):
        response = result_value(tool_reply(messages, 'page'))
        assert response['ok'] and response['result']['status'] == 'observed', response
        assert response['result']['source']['render_ref'] == prepared['render_ref']
        observed['receipts'].append(response['receipt_id'])
        observed['visual_observation'] = response
        args = {'operation_id': 'r3-duplicate-output-replay', 'scope_ids': ['r3-visible-table'],
                'observation_receipts': list(observed['receipts'])}
        observed['actual_caller_args'] = args
        return action('perform_assigned_artifact_review', 'compare', **args)

    def checker(messages):
        packet = json.loads(messages[-1].content)
        observed['checker_packet'] = packet
        assert [e['receipt_id'] for e in packet['evidence']] == observed['receipts']
        assert packet['requirements'][0]['required_checks'] == old_packet['requirements'][0]['required_checks']
        req, old = packet['requirements'][0], old_packet['requirements'][0]
        identities = {old_packet['snapshot_ref']['id']: packet['snapshot_ref']['id'],
            old['target_ref']['id']: req['target_ref']['id'], old['criterion_ref']['id']: req['criterion_ref']['id'],
            old['artifact_refs'][0]['id']: req['artifact_refs'][0]['id'],
            old['required_read_refs'][0]['id']: req['required_read_refs'][0]['id'],
            old_packet['evidence'][2]['actual_observation']['source']['export_ref']['id']: prepared['export_ref']['id'],
            **{a['receipt_id']: b['receipt_id'] for a, b in zip(old_packet['evidence'], packet['evidence'], strict=True)}}
        changes = []
        replayed = rebind_strings(original_output, identities, changes)
        rebound = deepcopy(replayed)
        replayed['items'][0]['artifact_refs'] = deepcopy(req['artifact_refs'])
        restored = deepcopy(replayed)
        restored['items'][0]['artifact_refs'] = rebound['items'][0]['artifact_refs']
        assert restored == rebound
        observed['compatibility_projection'] = {'path': '$.items[0].artifact_refs',
            'before': rebound['items'][0]['artifact_refs'], 'after': replayed['items'][0]['artifact_refs']}
        observed.update(identity_map=identities, identity_rebindings=changes, checker_output=replayed)
        # This authentic failure is beyond JSON-shape constraints: the custom
        # output validator rejects duplicate indexes. Do not repair either one.
        Draft202012Validator(packet['output_schema']).validate(replayed)
        with pytest.raises(ValidationError, match='DUPLICATE_CHECK_RESULT') as failure:
            ReviewSubmission.model_validate(replayed)
        observed['replayed_output_errors'] = failure.value.errors(include_url=False, include_context=False)
        assert [c['requirement_index'] for c in replayed['items'][0]['check_results']] == [0, 0]
        return AIMessage(content=json.dumps(replayed, ensure_ascii=False))

    def child_finish(messages):
        public = tool_message(messages, 'perform_assigned_artifact_review')
        observed['next_reviewer_tool_message'] = public.model_dump()
        return AIMessage(content=str(public.content))

    def parent(messages):
        observed['next_coordinator_tool_message'] = tool_message(messages, 'task').model_dump()
        return AIMessage(content='Received checker failure retained; no retry, no artifact review acceptance.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[prepared['call']]), parent], reviewer=[
        action('read_context', 'table', target_ref=refs['table']), read_standard, inspect_page, compare, child_finish],
        text_tool=[checker])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    observed['fake_vision_calls'] = len(service.calls)
    observed['fake_checker_calls'] = sum(role == 'text_tool' for role, _, _ in driver.calls)
    observed['bindings'] = driver.bindings
    with ws.store.connect() as db:
        observed['raw_analyses'] = {r[0]: json.loads(r[1]) for r in db.execute('SELECT operation,data FROM analyses')}
        observed['reservations'] = {r[0]: json.loads(r[1]) for r in db.execute(
            "SELECT key,value FROM state WHERE key LIKE 'bounded_review_attempt:%' OR key LIKE 'artifact_text_work:%'")}
    observed['review_records'] = cs.list_objects('ReviewRecord')
    framework = Path(inspect.getsourcefile(tool_node))
    observed['framework'] = {'path': str(framework), 'sha256': hashlib.sha256(framework.read_bytes()).hexdigest(),
        'version': version('langgraph-prebuilt'), 'documented_exception_meaning': tool_node.ToolInvocationError.__doc__}
    (folder / 'framework-error-handler.py').write_text(inspect.getsource(tool_node.ToolNode._execute_tool_async)
        + '\n' + inspect.getsource(tool_node.ToolInvocationError), encoding='utf-8')
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    assert observed['fake_vision_calls'] == observed['fake_checker_calls'] == 1
    assert not observed['review_records']
    # Vision and checker share the raw-analysis table. Select the actual text
    # response instead of mistaking the second legitimate row for a retry.
    raw, = [v for v in observed['raw_analyses'].values() if 'analysis' in v]
    assert json.loads(raw['analysis']) == observed['checker_output']
    schema = next(s['parameters'] for s in driver.bindings['reviewer'][0] if s['name'] == 'perform_assigned_artifact_review')
    Draft202012Validator(schema).validate(observed['actual_caller_args'])
    assert 'check_results' not in observed['actual_caller_args']
    public = observed['next_reviewer_tool_message']['content']
    assert 'DUPLICATE_CHECK_RESULT' in public, public
    wrong_phase = [e for e in observed['actual_exception_constructions']
        if e['source_schema'] == 'ReviewSubmission' and e['tool_kwargs'] == observed['actual_caller_args']
        ]
    assert 'ARTIFACT_REVIEW_OUTPUT_CONTRACT_INVALID' in public, public
    assert raw['operation'] in public and 'raw_response_received' in public, public
    attribution = {'registered_input_schema': schema, 'input_schema_valid': True,
        'received_checker_response_invalid': True, 'failure_stage': 'ReviewSubmission output validation',
        'wrong_phase_records': wrong_phase,
        'oracle': 'A received invalid checker response must not be attributed to already-valid Reviewer tool arguments.'}
    (folder / 'phase-attribution.json').write_text(json.dumps(attribution, ensure_ascii=False, indent=2), encoding='utf-8')
    request.node.user_properties.append(('artifact_output_phase', json.dumps(attribution, ensure_ascii=False)))
    assert not wrong_phase, ('Received ReviewSubmission output failure was reported as invalid Reviewer arguments.', wrong_phase)
