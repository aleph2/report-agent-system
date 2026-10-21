"""Fresh R12 public artifact probe: scripted decisions and independent outputs.

Actual DOCX/PDF/PNG, versioned sources, native delegation and public ToolNode.
No network. Legal output saves two completed checks but never a satisfied item.
The duplicate-index calibration changes only the second check index, not inputs.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from duty_probe_visual_packets import prepare_visual, perform_public_visual_and_artifact
from report_agent.content_models import ReviewSubmission
from test_agent_duty_repro_artifacts import save_evidence
from test_bounded_review import Model
from test_task_supervision import ws, offline
from test_vision import VisionModel


def artifact_fixture(packet, *, note_present):
    """Independent synthetic checker response; never appended to its input."""
    req = packet['requirements'][0]
    texts = ['Table uses class B and score 70.', 'Source requires class B score 75 and four columns.',
             'Visible table has Indicator, Class, Score, Note.' if note_present
             else 'Visible table has Indicator, Class, Score; required Note column is absent.']
    return {'snapshot_ref': packet['snapshot_ref'], 'target_ref': packet['snapshot_ref'],
        'scope': 'Single synthetic page only', 'criteria_refs': [req['criterion_ref']],
        'dependency_refs': req['required_read_refs'], 'items': [{
            'target_ref': req['target_ref'], 'criterion_ref': req['criterion_ref'],
            'scope': 'Single physical page', 'scope_id': req['scope_id'], 'assessment_kind': 'render',
            'artifact_refs': req['artifact_refs'], 'execution_state': 'completed',
            'verdict': 'not_satisfied', 'checked_requirement_indexes': [0, 1],
            'observations': [{'locator': str(i), 'observation': text,
                'receipt_id': packet['evidence'][i]['receipt_id'],
                'limitations': 'Synthetic fake observation, not semantic or engineering acceptance.'}
                for i, text in enumerate(texts)],
            'check_results': [
                {'requirement_index': 0, 'execution_state': 'completed',
                 'result': '70 differs from the required score 75.', 'observation_indexes': [0, 1, 2], 'remaining': ''},
                {'requirement_index': 1, 'execution_state': 'completed',
                 'result': 'All four required columns are visible.' if note_present else 'The required Note column is absent.',
                 'observation_indexes': [0, 1, 2], 'remaining': ''}],
            'coverage': {'checked': ['score', 'columns'], 'unchecked': [], 'blocked': [],
                         'basis': 'Exact source plus bound full-page image observation.'},
            'reason': 'Score conflict remains; no engineering acceptance.', 'findings': []}],
        'delivery_checks': [], 'coverage_accounting': []}


class ContrastModel(Model):
    def __init__(self, note_present, duplicate_index):
        super().__init__()
        self.note_present, self.duplicate_index = note_present, duplicate_index
        self.packet = self.valid = self.output = None
        self.invalid_errors = None

    async def ainvoke(self, messages):
        self.packet = json.loads(messages[-1].content if hasattr(messages[-1], 'content') else messages[-1][1])
        self.valid = artifact_fixture(self.packet, note_present=self.note_present)
        ReviewSubmission.model_validate(self.valid)
        self.output = deepcopy(self.valid)
        if self.duplicate_index:
            self.output['items'][0]['check_results'][1]['requirement_index'] = 0
            with pytest.raises(ValidationError, match='DUPLICATE_CHECK_RESULT') as error:
                ReviewSubmission.model_validate(self.output)
            self.invalid_errors = error.value.errors(include_url=False, include_context=False)
        # Schema legality alone cannot detect duplicate check indexes: the
        # application's output model has an additional semantic validator.
        Draft202012Validator(self.packet['output_schema']).validate(self.output)
        self.response = json.dumps(self.output, ensure_ascii=False)
        return await super().ainvoke(messages)


@pytest.mark.parametrize('note_present,duplicate_index', [(False, False), (True, False), (True, True)],
                         ids=['original-three-columns', 'fresh-four-columns', 'fresh-duplicate-index'])
async def test_public_artifact_contrast_retains_two_checks_and_exact_page(ws, request, note_present, duplicate_index):
    base = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro')))
    folder = base / request.node.name
    prepared = await prepare_visual(ws, folder, include_note_column=note_present)
    cs, refs = prepared['cs'], prepared['refs']
    immutable_refs = [*refs.values(), prepared['snapshot'], prepared['export_ref'], prepared['render_ref']]
    before = [cs.read(ref) for ref in immutable_refs]
    preparation = json.loads((folder / 'visual-preparation.json').read_text())
    expected_matrix = [['Indicator', 'Class', 'Score'] + (['Note'] if note_present else []),
                       ['TEST-OBJECT', 'B', '70'] + (['Synthetic note'] if note_present else [])]
    docx_asset = next(a for a in preparation['assets'] if a['path'].endswith('.docx'))
    with ZipFile(docx_asset['path']) as archive:
        document = ET.fromstring(archive.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    matrices = [[[''.join(t.text or '' for t in cell.findall('.//w:t', ns))
                  for cell in row.findall('w:tc', ns)] for row in table.findall('w:tr', ns)]
                for table in document.findall('.//w:tbl', ns)]
    assert matrices == [expected_matrix]
    assert len(preparation['render_record']['payload']['page_assets']) == 1
    for asset in preparation['assets']:
        assert hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest() == asset['sha256']
    model = ContrastModel(note_present, duplicate_index)
    vision = VisionModel(content='Displayed rule: CLASS B uses SCORE 75. ' +
        ('Table: Indicator | Class | Score | Note. TEST-OBJECT | B | 70 | Synthetic note. Four required columns present.'
         if note_present else 'Table: Indicator | Class | Score. TEST-OBJECT | B | 70. Required Note column absent.') +
        ' Score 70 differs from reference 75. This fake observation does not prove visual accuracy or engineering acceptance.')
    observed = {'independent_expected_matrix': expected_matrix, 'actual_docx_matrices': matrices,
                'assets': preparation['assets'], 'note_present': note_present, 'duplicate_index': duplicate_index}
    try:
        result = await perform_public_visual_and_artifact(ws, prepared, folder,
            vision_client=vision, artifact_model=model, operation_prefix='r12-fake')
        observed.update(result=result, fake_vision_calls=len(vision.calls), fake_checker_calls=len(model.calls),
            actual_checker_input=model.packet, valid_checker_output=model.valid, actual_checker_output=model.output,
            invalid_output_errors=model.invalid_errors)
        with ws.store.connect() as db:
            observed['raw_analyses'] = {r[0]: json.loads(r[1]) for r in db.execute('SELECT operation,data FROM analyses')}
            observed['actual_receipt_records'] = [{'id': r[0], 'actor_id': r[1], 'data': json.loads(r[2])} for r in db.execute(
                'SELECT id,actor_id,data FROM content_observations WHERE id IN (%s)' % ','.join('?' for _ in result['receipts']),
                result['receipts'])]
            observed['reservations'] = {r[0]: json.loads(r[1]) for r in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'artifact_text_work:%'")}
        observed['review_records'] = cs.list_objects('ReviewRecord')
        assert result['runtime_result']['last_error'] is None, result
        assert len(vision.calls) == len(model.calls) == 1
        assert vision.closed
        assert before == [cs.read(ref) for ref in immutable_refs]
        requirement = prepared['call']['args']['review_requirements'][0]
        assert model.packet['requirements'][0]['required_checks'] == requirement['required_checks']
        assert len(requirement['required_checks']) == 2
        assert model.packet['criteria'] == [cs.read(refs['criterion'])]
        assert model.packet['snapshot_ref'] == prepared['snapshot']
        assert [e['receipt_id'] for e in model.packet['evidence']] == result['receipts']
        assert len(set(result['receipts'])) == 3
        assert all(r['actor_id'] == result['actor']['id'] for r in observed['actual_receipt_records'])
        actual = result['vision']['result']
        assert actual['source']['page'] == 1
        assert actual['source']['render_ref'] == prepared['render_ref']
        assert actual['source']['export_ref'] == prepared['export_ref']
        png = next(a for a in preparation['assets'] if a['path'].endswith('.png'))
        assert actual['image_sha256'] == png['sha256']
        schema = next(s['parameters'] for s in result['bindings']['reviewer'][0]
                      if s['name'] == 'perform_assigned_artifact_review')
        Draft202012Validator(schema).validate(result['actual_caller_args'])
        observed['registered_input_schema'] = schema
        raw, = [v for v in observed['raw_analyses'].values() if 'analysis' in v]
        assert json.loads(raw['analysis']) == model.output
        assert result['next_reviewer_tool_message']
        assert result['next_coordinator_tool_message']
        if duplicate_index:
            restored = deepcopy(model.output)
            restored['items'][0]['check_results'][1]['requirement_index'] = 1
            assert restored == model.valid
            assert [c['requirement_index'] for c in model.output['items'][0]['check_results']] == [0, 0]
            assert 'DUPLICATE_CHECK_RESULT' in result['next_reviewer_tool_message']['content']
            assert not observed['review_records'] and result['saved_review'] is None
            assert not result['artifact_check_completed']
            assert result['reconcile']['remaining']
        else:
            assert len(observed['review_records']) == 1
            saved = result['saved_review']
            assert saved == observed['review_records'][0]
            assert saved['owner_id'] == result['actor']['id']
            assert saved['task_id'] == result['actor']['task_id']
            assert saved['payload']['snapshot_ref'] == prepared['snapshot']
            assert result['artifact']['review'] == saved['payload']
            assert result['artifact_check_completed']
            item, = saved['payload']['items']
            assert item['execution_state'] == 'completed' and item['verdict'] == 'not_satisfied'
            assert item['check_results'] == ReviewSubmission.model_validate(model.valid).model_dump()['items'][0]['check_results']
            assert [c['requirement_index'] for c in item['check_results']] == [0, 1]
            assert all(c['execution_state'] == 'completed' for c in item['check_results'])
    finally:
        save_evidence(request, ws, observed)
