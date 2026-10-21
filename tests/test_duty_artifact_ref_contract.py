"""R12 trace replay and model-visible artifact type contract, without repairs.

The historical native cases use exact response prose with complete UUID
rebinding to independent synthetic fixtures. Only the control's artifact_refs
field changes. Neither replay is a retry or repair of the historical paid run.
The schema negatives are intentionally ordinary assertions, never xfail.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from duty_probe_visual_packets import prepare_visual, perform_public_visual_and_artifact
from report_agent.content_models import ReviewSubmission
from test_agent_duty_repro_artifacts import save_evidence
from test_bounded_review import Model
from test_task_supervision import ws, offline
from test_vision import VisionModel


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/live-r12/visual-artifact-columns-complete'
PINNED = {
    'wire-responses.json': '3f5b921e9872e4d689d5a5d19fa7862d9981cfbc4ae83527b06ca4dcac34bb70',
    'wire-requests.json': '37962f2c9c6b71a2d30d3750e8a30a9022280900cadcf46c6974b46be05b84ae',
    'model-output.json': 'fe2add6cf244fd28c1f0f82b691a681ddd3f0b0a3677d18eb6dbe70cc79fd937',
    'independent-input.json': '67bbb217db9abd61c47f8c4a6afc8dedf83b0ceeb2d0aafa5f968efd1087174f',
    'visual-preparation.json': 'a94439dba225b4d2987eade330d119e64b0181ad1c5cce1c9981fb1fd2659aa8',
    'result.json': '786e84cc6672811faec3bdef95a6812b538e8c3a8cadbbfa05e9e37e5d09c71a',
}
UUID_TEXT = re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F])')


def load_original(folder):
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, expected in PINNED.items():
        raw = (ORIGINAL / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected, ('Historical evidence changed', name)
        (folder / ('original-' + name)).write_bytes(raw)
        files[name] = json.loads(raw)
    wire, = [x for x in files['wire-responses.json'] if x['role'] == 'artifact']
    raw_content = json.loads(wire['body'])['choices'][0]['message']['content']
    assert raw_content == files['model-output.json']['content']
    (folder / 'original-artifact-content.txt').write_text(raw_content, encoding='utf-8')
    packet = json.loads(files['independent-input.json'][1][1])
    sent, = [x for x in files['wire-requests.json'] if x['role'] == 'artifact']
    assert json.loads(sent['body']['messages'][-1]['content']) == packet
    output = json.loads(raw_content)
    assert [c['requirement_index'] for c in output['items'][0]['check_results']] == [0, 1]
    assert [r['type'] for r in output['items'][0]['artifact_refs']] == ['RenderArtifact', 'ContentNode', 'SourceArtifact']
    # These are actual recorded requests/responses, not SDK retry configuration.
    assert Counter(x['role'] for x in files['wire-requests.json']) == {'vision': 1, 'artifact': 1}
    assert Counter(x['role'] for x in files['wire-responses.json']) == {'vision': 1, 'artifact': 1}
    assert all(x['http_status'] == 200 for x in files['wire-responses.json'])
    assert files['result.json']['automatic_logical_retry'] is False
    return {'packet': packet, 'output': output, 'content_sha256': hashlib.sha256(raw_content.encode()).hexdigest(),
            'historical_wire_requests': 2, 'historical_wire_responses': 2,
            'historical_recorded_retry_or_fallback': 0, 'pinned_files': PINNED}


def rebind_complete_uuids(value, mapping, changes, path='$'):
    if isinstance(value, dict):
        return {k: rebind_complete_uuids(v, mapping, changes, path + '.' + k) for k, v in value.items()}
    if isinstance(value, list):
        return [rebind_complete_uuids(v, mapping, changes, f'{path}[{i}]') for i, v in enumerate(value)]
    if isinstance(value, str):
        updated = UUID_TEXT.sub(lambda match: mapping.get(match.group(), match.group()), value)
        if updated != value:
            changes.append({'path': path, 'before': value, 'after': updated})
        return updated
    return value


class ReplayModel(Model):
    def __init__(self, original, *, declared_only):
        super().__init__()
        self.original, self.declared_only = original, declared_only
        self.packet = self.response_value = self.rebound_original = None
        self.mapping, self.changes = {}, []

    async def ainvoke(self, messages):
        self.packet = json.loads(messages[-1].content if hasattr(messages[-1], 'content') else messages[-1][1])
        old, new = self.original['packet'], self.packet
        a, b = old['requirements'][0], new['requirements'][0]
        self.mapping = {
            old['snapshot_ref']['id']: new['snapshot_ref']['id'],
            old['task_id']: new['task_id'],
            a['target_ref']['id']: b['target_ref']['id'],
            a['criterion_ref']['id']: b['criterion_ref']['id'],
            a['artifact_refs'][0]['id']: b['artifact_refs'][0]['id'],
            a['required_read_refs'][0]['id']: b['required_read_refs'][0]['id'],
            old['criteria'][0]['payload']['requirement_refs'][0]['id']: new['criteria'][0]['payload']['requirement_refs'][0]['id'],
            old['evidence'][2]['actual_observation']['source']['export_ref']['id']:
                new['evidence'][2]['actual_observation']['source']['export_ref']['id'],
            **{x['receipt_id']: y['receipt_id'] for x, y in zip(old['evidence'], new['evidence'], strict=True)}}
        for before, after in self.mapping.items():
            UUID(before)
            UUID(after)
        # Historical protocol remains pinned above; this request uses the active contract.
        assert new['output_schema'] == ReviewSubmission.model_json_schema()
        assert a['required_checks'] == b['required_checks']
        assert old['evidence'][2]['actual_observation']['image_sha256'] == new['evidence'][2]['actual_observation']['image_sha256']
        self.rebound_original = rebind_complete_uuids(self.original['output'], self.mapping, self.changes)
        self.response_value = deepcopy(self.rebound_original)
        if self.declared_only:
            # The only control difference after identical complete UUID rebinding.
            self.response_value['items'][0]['artifact_refs'] = deepcopy(b['artifact_refs'])
        # Send the actual received payload, even when invalid. A fake service must
        # not perform the application's output validation before returning it.
        self.response = json.dumps(self.response_value, ensure_ascii=False)
        return await super().ainvoke(messages)


@pytest.mark.parametrize('declared_only', [False, True], ids=['original-artifact-field', 'declared-render-only'])
async def test_r12_received_artifact_ref_contract_through_public_tool(ws, request, declared_only):
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro'))) / request.node.name
    original = load_original(folder)
    prepared = await prepare_visual(ws, folder, include_note_column=True)
    cs = prepared['cs']
    protected = [*prepared['refs'].values(), prepared['snapshot'], prepared['export_ref'], prepared['render_ref']]
    before = [cs.read(r) for r in protected]
    service = VisionModel(content=original['packet']['evidence'][2]['actual_observation']['observation'])
    model = ReplayModel(original, declared_only=declared_only)
    observed = {'original': original, 'declared_only': declared_only,
        'replay_kind': 'Historical response prose retained with complete UUID rebinding into fresh synthetic native task.',
        'legal_control_is_not_a_paid_retry_or_repair': True}
    try:
        result = await perform_public_visual_and_artifact(ws, prepared, folder,
            vision_client=service, artifact_model=model, operation_prefix='r12-ref-contract')
        observed.update(result=result, fake_vision_calls=len(service.calls), fake_checker_calls=len(model.calls),
            checker_packet=model.packet, checker_output=model.response_value,
            rebound_original=model.rebound_original, identity_map=model.mapping, identity_rebindings=model.changes)
        observed['review_records'] = cs.list_objects('ReviewRecord')
        with ws.store.connect() as db:
            observed['raw_analyses'] = {r[0]: json.loads(r[1]) for r in db.execute('SELECT operation,data FROM analyses')}
            observed['reservations'] = {r[0]: json.loads(r[1]) for r in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'artifact_text_work:%'")}
        assert result['runtime_result']['last_error'] is None, result
        assert len(service.calls) == len(model.calls) == 1
        assert service.closed and not result['automatic_retry']
        assert before == [cs.read(r) for r in protected]
        assert [c['requirement_index'] for c in model.response_value['items'][0]['check_results']] == [0, 1]
        input_schema = next(s['parameters'] for s in result['bindings']['reviewer'][0]
                            if s['name'] == 'perform_assigned_artifact_review')
        Draft202012Validator(input_schema).validate(result['actual_caller_args'])
        observed['registered_caller_schema'] = input_schema
        raw, = [v for v in observed['raw_analyses'].values() if 'analysis' in v]
        assert json.loads(raw['analysis']) == model.response_value
        assert result['next_reviewer_tool_message'] and result['next_coordinator_tool_message']
        if not declared_only:
            assert model.response_value == model.rebound_original
            with pytest.raises(ValidationError) as rejected:
                ReviewSubmission.model_validate(model.response_value)
            errors = rejected.value.errors(include_input=False, include_context=False)
            observed['actual_current_contract_errors'] = errors
            public = result['next_reviewer_tool_message']['content']
            assert 'ARTIFACT_REVIEW_OUTPUT_CONTRACT_INVALID' in public
            diagnostic = json.loads(result['artifact']['message'].split(': ', 1)[1])
            assert any(error['loc'] == ['items', 0, 'artifact_refs', 1, 'type']
                       and error['type'] == 'literal_error' for error in diagnostic['errors'])
            if 'ArtifactRef' in model.packet['output_schema'].get('$defs', {}):
                assert any(e['type'] == 'literal_error' and tuple(e['loc']) ==
                           ('items', 0, 'artifact_refs', 1, 'type') for e in errors)
            assert not observed['review_records'] and result['saved_review'] is None
            assert not result['artifact_check_completed']
            assert result['reconcile']['remaining']
        else:
            restored = deepcopy(model.response_value)
            restored['items'][0]['artifact_refs'] = model.rebound_original['items'][0]['artifact_refs']
            assert restored == model.rebound_original
            # Approved R8 oracle correction: fixing ArtifactRef types does not
            # repair this historical check's missing required source citation.
            ReviewSubmission.model_validate(model.response_value)
            assert result['artifact']['code'] == 'COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL'
            assert result['artifact']['ok'] is False and result['artifact']['accepted'] is False
            assert 'COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL' in result['next_reviewer_tool_message']['content']
            assert 'COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL' in str(result['next_coordinator_tool_message']['content'])
            assert not observed['review_records'] and result['saved_review'] is None
            assert not result['artifact_check_completed'] and result['reconcile']['remaining']
            observed['test_disposition'] = 'Exact rejection of historical counterexample; not successful review or repaired model response.'
    finally:
        save_evidence(request, ws, observed)


@pytest.mark.parametrize('forbidden_type', ['ContentNode', 'SourceArtifact'])
def test_actual_model_schema_expresses_existing_artifact_ref_type_constraint(ws, request, forbidden_type):
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro'))) / request.node.name
    original = load_original(folder)
    schema = ReviewSubmission.model_json_schema()
    valid = deepcopy(original['output'])
    valid['items'][0]['artifact_refs'] = deepcopy(original['packet']['requirements'][0]['artifact_refs'])
    Draft202012Validator(schema).validate(valid)
    ReviewSubmission.model_validate(valid)
    invalid = deepcopy(valid)
    invalid['items'][0]['artifact_refs'][0]['type'] = forbidden_type
    restored = deepcopy(invalid)
    restored['items'][0]['artifact_refs'][0]['type'] = 'RenderArtifact'
    assert restored == valid
    with pytest.raises(ValidationError) as backend:
        ReviewSubmission.model_validate(invalid)
    errors = list(Draft202012Validator(schema).iter_errors(invalid))
    observed = {'original': original, 'valid_baseline': valid, 'single_type_variant': invalid,
        'changed_path': '$.items[0].artifact_refs[0].type', 'backend_errors': backend.value.errors(include_url=False, include_context=False),
        'model_visible_schema_errors': [{'message': e.message, 'instance_path': list(e.path), 'schema_path': list(e.schema_path)} for e in errors],
        'schema_origin': 'Current ReviewSubmission schema; independently pinned historical paid schema retained separately.',
        'existing_backend_rule': 'ReviewItem.consistent: only ExportArtifact or RenderArtifact in artifact_refs.',
        'assertion_scope': 'This simple type restriction must be expressed in the actual model-visible schema; not all semantic rules.',
        'identity_limit': 'The type mutation tests JSON structure only; it does not claim a ContentNode/SourceArtifact exists under the RenderArtifact ID.',
        'fake_model_calls': 0, 'paid_calls': 0}
    save_evidence(request, ws, observed)
    # Intentionally red when the actual schema accepts a backend-forbidden type.
    assert errors, ('MODEL_VISIBLE_ARTIFACT_REF_TYPE_NOT_EXPRESSED', forbidden_type)


async def test_independent_legal_artifact_response_saves_complete_material_links(ws, request):
    """New synthetic positive control, never a repair/relabel of historical raw."""
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro'))) / request.node.name
    prepared = await prepare_visual(ws, folder, include_note_column=True)
    cs = prepared['cs']
    protected = [*prepared['refs'].values(), prepared['snapshot'], prepared['export_ref'], prepared['render_ref']]
    before = [cs.read(ref) for ref in protected]

    class LegalSyntheticModel(Model):
        async def ainvoke(self, messages):
            self.packet = json.loads(messages[-1].content if hasattr(messages[-1], 'content') else messages[-1][1])
            packet = self.packet
            requirement, = packet['requirements']
            assert len(requirement['required_checks']) == 2 and len(packet['evidence']) == 3
            observations = [{'receipt_id': evidence['receipt_id'], 'locator': 'Actual supplied material ' + str(i),
                'observation': json.dumps(evidence['actual_observation'], ensure_ascii=False),
                'limitations': 'Synthetic single-page observation only.'} for i, evidence in enumerate(packet['evidence'])]
            self.value = {'target_ref': requirement['target_ref'], 'snapshot_ref': packet['snapshot_ref'],
                'scope': 'Explicit synthetic single-page artifact checks',
                'criteria_refs': [requirement['criterion_ref']],
                'dependency_refs': packet['criteria'][0]['payload']['requirement_refs'],
                'items': [{'target_ref': requirement['target_ref'], 'criterion_ref': requirement['criterion_ref'],
                    'scope': 'Exact supplied page and source only', 'scope_id': requirement['scope_id'],
                    'assessment_kind': 'render', 'artifact_refs': requirement['artifact_refs'],
                    'execution_state': 'completed', 'verdict': 'not_satisfied',
                    'checked_requirement_indexes': [0, 1], 'observations': observations,
                    'check_results': [{'requirement_index': i, 'execution_state': 'completed',
                        'result': result, 'observation_indexes': [0, 1, 2]} for i, result in enumerate([
                            'Synthetic row score 70 conflicts with the supplied source score 75.',
                            'The supplied table and page observation contain all four source-required columns.'])],
                    'outside_assignment_notes': ['Unobserved pages and engineering acceptance are outside this single-page assignment.'],
                    'coverage': {'checked': requirement['required_checks'], 'unchecked': [],
                        'blocked': [], 'basis': 'Complete supplied table, independent standard and one actual page-observation receipt.'},
                    'reason': 'Local synthetic score discrepancy; no whole-report acceptance.'}]}
            self.response = json.dumps(self.value, ensure_ascii=False)
            return await super().ainvoke(messages)

    model = LegalSyntheticModel()
    service = VisionModel(content='Synthetic full-page observation: Indicator, Class, Score, Note; TEST-OBJECT B 70; independent source rule score 75.')
    observed = {'control_kind': 'independently authored legal synthetic positive; not historical model output'}
    try:
        result = await perform_public_visual_and_artifact(ws, prepared, folder,
            vision_client=service, artifact_model=model, operation_prefix='r8-independent-legal')
        observed.update(result=result, supplied_response=model.value, actual_packet=model.packet)
        assert result['runtime_result']['last_error'] is None, result
        assert len(model.calls) == len(service.calls) == 1 and service.closed
        saved = result['saved_review']
        assert saved is not None and cs.list_objects('ReviewRecord') == [saved]
        assert saved['owner_id'] == result['actor']['id'] and saved['task_id'] == result['actor']['task_id']
        assert result['artifact_check_completed'] and result['reconcile']['execution_complete']
        assert result['artifact']['review'] == saved['payload']
        assert all(check['observation_indexes'] == [0, 1, 2] for check in saved['payload']['items'][0]['check_results'])
        assert result['next_reviewer_tool_message'] and result['next_coordinator_tool_message']
        assert before == [cs.read(ref) for ref in protected]
    finally:
        save_evidence(request, ws, observed)
