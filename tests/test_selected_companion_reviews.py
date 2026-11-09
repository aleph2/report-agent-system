"""Actual temporary DOCX/XLSX and persisted reviews; no model/visual acceptance."""
from report_agent import report_state
import pytest

from report_agent.content_delivery import current_delivery, obligations
from report_agent.content_export import export_snapshot, read_export
from report_agent.content_models import Ref
from report_agent.content_workbook import export_workbook
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.review_status import read_status
from test_content_workbook import prepared
from test_hierarchical_content import ws, submission, review_item


@pytest.fixture
def pair(ws):
    ws.store.set('manifest', {**ws.store.manifest, 'review_entrypoint': 'delegated-reviewer-v1'})
    cs, actor, old, snap, sheets = prepared(ws)
    members = cs.read(snap)['payload']['refs']
    refs = {'k': next(r for r in members if r['type'] == 'Criterion'),
            'support': next(r for r in members if r['type'] == 'Relation')}
    word = export_snapshot(cs, actor, 'word', snap)['result']['export_ref']
    excel = export_workbook(cs, actor, 'excel', snap, sheets, word)['result']['export_ref']
    select = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'select_content_delivery')
    select('select', Ref.model_validate(snap), Ref.model_validate(word), workbook_export_ref=Ref.model_validate(excel))
    return ws, cs, actor, snap, sheets, refs, word, excel, select


def save_review(pair, artifacts=None, *, op='joint', verdict='not_satisfied', checks=False):
    ws, cs, actor, snap, sheets, refs, word, excel, select = pair
    artifacts = [word, excel] if artifacts is None else artifacts
    reviewer = actor_for('reviewer')
    receipts = [read_export(cs, reviewer, r)['receipt_id'] for r in artifacts]
    item = review_item(snap, refs['k'], receipts[0], verdict=verdict)
    item.update(assessment_kind='export', artifact_refs=artifacts,
                observations=[{'receipt_id': r, 'locator': 'actual exported bytes',
                               'observation': 'Fixture scoped comparison, not semantic acceptance.'} for r in receipts])
    data = submission(snap, refs, item)
    if checks:
        data['delivery_checks'] = [{'kind': 'export', 'artifact_refs': artifacts,
            **{k: item[k] for k in ('execution_state', 'verdict', 'observations', 'coverage', 'reason')}}]
    ref = cs.submit_review(reviewer, op, data, {})['result']['review_ref']
    return ref, cs.read(ref)


def test_joint_review_survives_public_delivery_and_status_projection(pair):
    ws, cs, _, snap, _, _, word, excel, _ = pair
    ref, original = save_review(pair, checks=True)
    delivery = current_delivery(ws.store)
    assert delivery['workbook_export_ref'] == excel
    assert [i['review_ref'] for i in delivery['confirmed_violations']] == [ref]
    assert [i['review_ref'] for i in delivery['delivery_violations']] == [ref]
    assert not delivery['needs_recheck']
    assert delivery['overall_verdict'] is None and delivery['coverage_complete'] is None
    tools = {t.__name__: t for t in content_tools(ws, 'coordinator')}
    public = tools['read_review_status'](Ref.model_validate(snap), limit=100)['result']
    assert public['workbook_export_ref'] == excel
    assert word in public['returned_refs'] and excel in public['returned_refs']
    for export in (word, excel):
        obj = next(o for o in public['objects'] if o['target_ref'] == export)
        assert obj['has_current_review'] and not obj['needs_recheck']
    summary = cs.review_summary(snap, obligations(cs, snap), word, excel)
    assert summary['confirmed_violations'] and summary['delivery_violations']
    assert cs.read(ref) == original


@pytest.mark.parametrize('replacement', ['word_only', 'excel_only', 'linked_pair'])
def test_changing_selected_file_invalidates_old_joint_without_erasing_history(pair, replacement):
    ws, cs, actor, snap, sheets, _, word, excel, select = pair
    ref, original = save_review(pair)
    if replacement != 'excel_only':
        word = export_snapshot(cs, actor, 'word2', snap)['result']['export_ref']
    if replacement == 'word_only':
        select('select2', Ref.model_validate(snap), Ref.model_validate(word))
    else:
        excel = export_workbook(cs, actor, 'excel2', snap, sheets, word)['result']['export_ref']
        select('select2', Ref.model_validate(snap), Ref.model_validate(word), workbook_export_ref=Ref.model_validate(excel))
    current = current_delivery(ws.store)
    assert not current['confirmed_violations']
    assert current['needs_recheck'][0]['review_ref'] == ref
    assert current['needs_recheck'][0]['artifact_current'] is False
    assert cs.read(ref) == original


def test_word_only_evidence_keeps_exact_scope_with_selected_companion(pair):
    ws, cs, _, snap, _, _, word, excel, _ = pair
    ref, _ = save_review(pair, [word], verdict='satisfied')
    item = current_delivery(ws.store)['items'][0]
    assert item['review_ref'] == ref and item['artifact_refs'] == [word]
    assert current_delivery(ws.store)['overall_verdict'] is None
    assert not read_status(cs, snap, excel)['objects'][0]['has_current_review']
    assert cs.item_applies(item, snap, word)  # Historical single-export default.


def test_unselected_sibling_cannot_borrow_selected_pair(pair):
    ws, cs, actor, snap, _, _, word, excel, _ = pair
    sibling = export_snapshot(cs, actor, 'sibling', snap)['result']['export_ref']
    ref, _ = save_review(pair, [sibling, excel])
    current = current_delivery(ws.store)
    assert not current['items'] and current['needs_recheck'][0]['artifact_current'] is False
    sibling_status = read_status(cs, snap, sibling)
    row = sibling_status['objects'][0]
    assert not row['has_current_review']
    assert row['review_history'][0]['recheck_reasons'] == ['artifact_version_mismatch']
    assert 'workbook_export_ref' not in sibling_status
    assert sibling not in read_status(cs, snap, limit=100)['returned_refs']


def test_selected_renders_normalize_to_exact_pair_and_appear_in_inventory(pair):
    ws, cs, actor, snap, _, refs, word, excel, _ = pair
    sibling = export_snapshot(cs, actor, 'sibling', snap)['result']['export_ref']
    # Render identities are fixtures; this test does not claim real page rendering.
    with ws.store.connect() as db:
        renders = [cs._insert(db, actor, 'RenderArtifact', {'snapshot_ref': snap, 'export_ref': e})
                   for e in (word, excel, sibling)]
    reviewer = actor_for('reviewer')
    receipt = cs.read_context(reviewer, snap)['receipt_id']
    data = submission(snap, refs, review_item(snap, refs['k'], receipt))
    data['items'][0].update(assessment_kind='render', artifact_refs=[renders[0]])
    cs.submit_review(reviewer, 'render-review', data, {})
    save_review(pair)  # Workbook content review; no Excel visual acceptance.
    assert current_delivery(ws.store)['confirmed_violations']
    status = read_status(cs, snap, limit=100)
    assert all(r in status['returned_refs'] for r in renders[:2])
    assert renders[2] not in status['returned_refs']
    for target in (word, excel, renders[0]):
        selected = read_status(cs, snap, target)['objects'][0]
        assert selected['has_current_review'] and not selected['needs_recheck']
    assert not read_status(cs, snap, renders[1])['objects'][0]['has_current_review']
    assert cs.item_applies({**data['items'][0], 'artifact_refs': renders[:2]}, snap, word, excel)
    assert not cs.item_applies(data['items'][0], snap, sibling)
    data['items'][0]['artifact_refs'] = renders[:2]
    with pytest.raises(ActionRejected, match='EXCEL_LAYOUT_REVIEW_OUTSIDE_SCOPE'):
        cs.submit_review(reviewer, 'excel-visual-not-authorized', data, {})


def test_no_selection_does_not_infer_pair_from_same_snapshot(pair):
    ws, cs, _, snap, _, _, word, excel, _ = pair
    _, record = save_review(pair)
    report_state.set_content_delivery(ws.store, None)
    assert not cs.item_applies(record['payload']['items'][0], snap, word)
    assert not read_status(cs, snap, word)['objects'][0]['has_current_review']
    assert not current_delivery(ws.store)['items']


def test_pair_selection_guard_still_rejects_wrong_word_link(pair):
    _, cs, actor, snap, _, _, word, excel, select = pair
    word2 = export_snapshot(cs, actor, 'word2', snap)['result']['export_ref']
    with pytest.raises(ActionRejected, match='COMPANION_EXPORT_VERSION_MISMATCH'):
        select('bad-pair', Ref.model_validate(snap), Ref.model_validate(word2), workbook_export_ref=Ref.model_validate(excel))


def test_content_and_old_mixed_negative_protection_unchanged(pair):
    _, cs, _, snap, _, _, word, excel, _ = pair
    _, record = save_review(pair)
    item = record['payload']['items'][0]
    assert cs.item_applies({**item, 'assessment_kind': 'content'}, snap)
    assert cs.item_applies({**item, 'assessment_kind': 'combined'}, snap)
    assert not cs.item_applies({**item, 'assessment_kind': 'combined', 'verdict': 'satisfied'}, snap)
