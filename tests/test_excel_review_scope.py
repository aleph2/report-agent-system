import pytest

from test_hierarchical_content import ws, submission, review_item
from test_content_workbook import prepared
from report_agent.content_workbook import export_workbook
from report_agent.content_export import export_snapshot
from report_agent.hierarchical_tools import actor_for
from report_agent.errors import ActionRejected


@pytest.mark.parametrize('delivery_check', [False, True])
def test_excel_layout_rejected_but_content_and_export_remain_allowed(ws, delivery_check):
    cs, actor, _, snap, sheets = prepared(ws)
    members = cs.read(snap)['payload']['refs']
    refs = {'k': next(r for r in members if r['type'] == 'Criterion'),
            'support': next(r for r in members if r['type'] == 'Relation')}
    word = export_snapshot(cs, actor, 'word', snap)['result']['export_ref']
    excel = export_workbook(cs, actor, 'excel', snap, sheets, word)['result']['export_ref']
    reviewer = actor_for('reviewer')
    receipt = cs.read_context(reviewer, snap)['receipt_id']
    review = submission(snap, refs, review_item(snap, refs['k'], receipt))
    review['items'][0].update(assessment_kind='export', artifact_refs=[excel])
    cs.submit_review(reviewer, 'export-fidelity', review, {})
    review['items'][0].update(assessment_kind='content', artifact_refs=[])
    cs.submit_review(reviewer, 'content', review, {})
    if delivery_check:
        review['delivery_checks'] = [{'kind': 'render', 'artifact_refs': [excel],
            'execution_state': 'not_started', 'verdict': None,
            'observations': [],
            'coverage': {'checked': [], 'unchecked': ['layout'], 'blocked': [], 'basis': 'not performed'},
            'reason': 'Layout not performed.'}]
    else:
        review['items'][0].update(assessment_kind='render', artifact_refs=[word, excel])
    with pytest.raises(ActionRejected, match='EXCEL_LAYOUT_REVIEW_OUTSIDE_SCOPE'):
        cs.submit_review(reviewer, 'excel-layout', review, {})
    assert len(cs.list_objects('ReviewRecord')) == 2
    if not delivery_check:
        review['items'][0]['artifact_refs'] = [word]
        cs.submit_review(reviewer, 'word-layout', review, {})
