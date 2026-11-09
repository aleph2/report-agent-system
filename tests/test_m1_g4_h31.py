"""H3.1 exclusion evidence guard; synthetic receipts, no providers or engineering decisions."""
from copy import deepcopy
import json

import pytest

from report_agent import plan_authority
from report_agent.catalog import Catalog
from report_agent.errors import ActionRejected
from report_agent.source_materials import issue, block_material, analysis_materials
from report_agent.store import digest
from test_ingestion import pdf_bytes
from test_m1_commission_plan import api, save, writer
from test_m1_g3_integration import method_commission
from test_m1_g4_requirements import anchored, required_case, capture, requirements, saved_historical_bundle
from test_m1_g4_planning_steps import entries, draft_case, planning, save_draft_parts
from test_m1_g4_h3 import returned_snippet, returned_image


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    def forbidden(*args, **kwargs):
        raise AssertionError('H31_NETWORK_FORBIDDEN')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


@pytest.fixture
def exclusion_case(draft_case):
    fixture = draft_case
    fixture.access_ref = capture(fixture, 'exclusion-pages.pdf',
        pdf_bytes(('Unrelated cover.', 'Page two candidate.', 'Unrelated page three.')), 'h31-pages')
    fixture.access_source = fixture.cs.read(fixture.access_ref)['payload']['source_id']
    fixture.plan['objects'][0].update(included=False, origin='interpretation',
        reason='Proposed exclusion based on the cited candidate page; owner decision remains separate.',
        sources=[{'source_ref': fixture.access_ref, 'locator': 'page 2; chars 1-19', 'quote': 'Page two candidate.'}])
    fixture.plan = api().CommissionPlan.model_validate(fixture.plan).model_dump()
    return fixture


def direct_text(fixture, *, source_id=None, offset=1):
    value = Catalog(fixture.ws.store).read(source_id or fixture.access_source, offset, 1)
    return issue(fixture.ws, fixture.co, 'read_source_page', json.dumps(value), block_material(value))


def helper_input(fixture):
    value = Catalog(fixture.ws.store).read(fixture.access_source, 1, 1)
    result = {'operation': 'synthetic-analysis', 'evidence': [{'kind': 'source_blocks', 'observation': value}]}
    return issue(fixture.ws, fixture.co, 'analyze_text', json.dumps({'interpretation': 'Synthetic interpretation.'}),
        analysis_materials(result))


GATES = ('submit', 'save', 'checkpoint', 'approval', 'approval-replay', 'writer')


def invoke_gate(fixture, gate):
    if gate == 'submit':
        save_draft_parts(fixture)
        return planning().submit_plan(fixture.cs, fixture.co, 'h31-submit')
    if gate == 'save':
        return save(fixture, operation='h31-save')
    bundle = saved_historical_bundle(fixture, fixture.plan, answered=gate not in ('approval', 'checkpoint'))
    if gate == 'checkpoint':
        return api().request_checkpoint(fixture.ws)
    if gate.startswith('approval'):
        return api().reply(fixture.ws, bundle.issue_id, bundle.decision)
    with fixture.cs.store.connect() as db:
        return api().assert_writing_allowed(fixture.cs, db, bundle.actor)


def exclusion_gaps(fixture):
    return [g for g in requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref)
        if g['code'] == 'EXCLUSION_SOURCE_NOT_DIRECTLY_RETURNED']


@pytest.mark.parametrize('gate', GATES)
@pytest.mark.parametrize('evidence', ['snippet', 'text-helper'])
def test_excluded_candidate_with_indirect_evidence_is_refused_at_every_gate(exclusion_case, gate, evidence):
    fixture = exclusion_case
    (returned_snippet if evidence == 'snippet' else helper_input)(fixture)
    with pytest.raises(ActionRejected, match='COMMISSION_REQUIREMENTS_INCOMPLETE') as exc:
        invoke_gate(fixture, gate)
    gaps = exc.value.diagnostic['gaps']
    gap = next(g for g in gaps if g['code'] == 'EXCLUSION_SOURCE_NOT_DIRECTLY_RETURNED')
    assert gap['path'] == 'objects.S1.sources'
    assert 'S1' in gap['message'] and '2' in gap['message']


@pytest.mark.parametrize('gate', GATES)
@pytest.mark.parametrize('evidence', ['direct-text', 'page-inspection', 'image-crop'])
def test_same_exclusion_with_verified_direct_candidate_page_passes_each_gate(exclusion_case, gate, evidence):
    fixture = exclusion_case
    if evidence == 'direct-text':
        direct_text(fixture)
    elif evidence == 'page-inspection':
        from report_agent.document_tools import source_page_info
        value = source_page_info(fixture.ws, fixture.access_source, 2)
        issue(fixture.ws, fixture.co, 'inspect_source_page', json.dumps(value), [{
            'source_id': fixture.access_source, 'kind': 'source_page_text_and_mechanical_tables',
            'selection': {'units': 'one-based physical PDF page', 'page': 2},
            'selected_value_digest': digest(value), 'coverage': {'complete_source': False}, 'limitations': value['limitations']}])
    else:
        returned_image(fixture, 2, [0.1, 0.1, 0.8, 0.8], 'incomplete')
    assert not exclusion_gaps(fixture)
    if gate in ('approval', 'approval-replay'):
        # An owner can approve only a proposal submitted by the Coordinator.
        saved = save(fixture, operation='h31-direct-for-approval')
        checkpoint = api().request_checkpoint(fixture.ws)
        decision = {'plan_ref': saved['plan_ref'], 'requirements_ref': fixture.requirements_ref,
            'approved': True, 'corrections': '', 'reductions': []}
        first = api().reply(fixture.ws, checkpoint['issue_id'], decision)
        assert first['resolved'] and first['decision_origin'] == 'operator'
        if gate == 'approval-replay':
            assert api().reply(fixture.ws, checkpoint['issue_id'], decision) == first
    else:
        assert invoke_gate(fixture, gate)


@pytest.mark.parametrize('fault', ['unrelated-page', 'same-page-other-source', 'receipt-tamper',
    'claimed-owner-reason', 'same-source-wrong-digest', 'same-source-wrong-payload'])
def test_unrelated_or_unverified_access_cannot_authorize_exclusion(exclusion_case, fault):
    fixture = exclusion_case
    if fault == 'unrelated-page':
        direct_text(fixture, offset=2)
    elif fault == 'same-page-other-source':
        other = capture(fixture, 'other-exclusion-pages.pdf', pdf_bytes(('Other cover.', 'Other page two.')), 'h31-other')
        direct_text(fixture, source_id=fixture.cs.read(other)['payload']['source_id'])
    elif fault == 'receipt-tamper':
        receipt = direct_text(fixture)
        value = fixture.ws.store.get('source_material:' + receipt['receipt'])
        value['public_sha256'] = '0' * 64
        fixture.ws.store.set('source_material:' + receipt['receipt'], value)
    elif fault.startswith('same-source-wrong-'):
        direct_text(fixture)
        payload = deepcopy(fixture.cs.read(fixture.access_ref)['payload'])
        if fault.endswith('digest'):
            payload['file_digest'] = '0' * 64
        else:
            payload['coverage'] = 'Synthetic altered extraction coverage under the same source ID.'
        # Independent malformed saved input: a logical source ID cannot establish identity.
        with fixture.cs.store.connect() as db:
            mismatched = fixture.cs._insert(db, fixture.co, 'SourceArtifact', payload)
        fixture.plan['objects'][0]['sources'][0]['source_ref'] = mismatched
    else:
        fixture.plan['objects'][0].update(origin='customer', reason='The agent claims the owner approved this exclusion.')
    assert exclusion_gaps(fixture)
    with pytest.raises(ActionRejected, match='COMMISSION_REQUIREMENTS_INCOMPLETE'):
        save(fixture, operation='h31-invalid-evidence')


def test_shared_exclusion_check_uses_receipts_without_reading_pdf_originals(exclusion_case, monkeypatch):
    from report_agent import source_access
    fixture = exclusion_case
    direct_text(fixture)
    def forbidden(*args, **kwargs):
        raise AssertionError('Completeness must not read PDF originals merely to count pages.')
    monkeypatch.setattr(source_access, '_pdf_page', forbidden)
    assert not requirements().check_plan(fixture.cs, fixture.plan, fixture.requirements_ref)


def test_owner_can_reduce_retained_unread_candidate_with_persisted_reason(exclusion_case):
    fixture = exclusion_case
    candidate = fixture.plan['objects'][0]
    candidate.update(included=True, reason='Keep this unread candidate pending the owner decision.')
    saved = save(fixture, operation='h31-retain-for-owner')
    checkpoint = api().request_checkpoint(fixture.ws)
    assert not plan_authority.decision_ref(fixture.ws.store)
    reason = 'Owner explicitly removes this candidate from this commission; retain the decision and evidence gap.'
    decision = {'plan_ref': saved['plan_ref'], 'requirements_ref': fixture.requirements_ref,
        'approved': True, 'corrections': '', 'reductions': [{'object_id': 'S1', 'reason': reason}]}
    replied = api().reply(fixture.ws, checkpoint['issue_id'], decision)
    accepted = fixture.cs.read(plan_authority.decision_ref(fixture.ws.store))
    assert accepted['owner_id'] == 'operator' and accepted['payload']['reductions'] == decision['reductions']
    assert fixture.cs.read(saved['plan_ref'])['payload']['objects'][0]['included'] is True
    assigned = writer(fixture, saved)
    with fixture.cs.store.connect() as db:
        assert api().assert_writing_allowed(fixture.cs, db, assigned)['ref'] == saved['plan_ref']
    checklist = (fixture.ws.store.root / replied['confirmation_checklist_path']).read_text(encoding='utf-8')
    assert '用户排除决定' in checklist and 'S1' in checklist and candidate['label'] in checklist and reason in checklist
    assert api().reply(fixture.ws, checkpoint['issue_id'], decision) == replied
    from report_agent.review_coverage import commission_completion
    root = fixture.cs.commit(assigned, 'h31-owner-reduced-report', [{'client_key': 'root', 'type': 'ContentNode',
        'payload': {'kind': 'report', 'body': {'text': 'Synthetic owner-reduced report.'},
            'qualifiers': {}, 'claim_kind': 'structure', 'citations': []}}])['result']['refs']['root']
    frozen = fixture.cs.freeze(fixture.co, 'h31-owner-reduced-snapshot', root, [root])['result']['snapshot_ref']
    completion = commission_completion(fixture.cs, fixture.cs.read(frozen))
    assert completion['complete'] is True and completion['missing_objects'] == []
    assert len(completion['reduced_objects']) == 1
    assert completion['reduced_objects'][0]['object_id'] == 'S1'
    assert completion['reduced_objects'][0]['reason'] == reason
    assert completion['reduced_objects'][0]['decision_ref'] == accepted['ref']
