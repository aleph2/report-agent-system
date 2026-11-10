"""Disclosed drafts retain real open rows without acquiring an adopted score."""
import pytest
from report_agent.assessment_projection import assessment_receipt, score_blocker
from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
from test_m1_g3_integration import method_commission
from test_writer_indicator_outcomes import evidence, ranked


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_unscored_projection_has_every_indicator_and_actual_gap_reason(ranked):
    f = ranked
    for key in ('A', 'B', 'C'):
        step = read_indicator_step(f.cs, f.actor)
        save_indicator_outcome(f.cs, f.actor, 'save-' + key, key, evidence(f, step))
    final = save_indicator_outcome(f.cs, f.actor, 'deferred-D', 'D',
        dict(kind='gap', missing='Deferred for engineering review', question='Confirm the conditional grades?'))['result']
    with f.cs.store.connect() as db:
        receipt = assessment_receipt(db, final['assessment_ref'])
    assert receipt['derivation_status'] == score_blocker(receipt) == 'unscored'
    assert 'adopted' not in receipt['result']
    assert all(receipt.get(k) for k in ('ranking_ref', 'evaluation_ref', 'level_ref', 'evidence_ref'))
    table = f.cs.read(receipt['evaluation_ref'])['payload']['body']
    assert len(table['rows']) == 4
    assert all(any(rule['label'] in str(cell) for row in table['rows'] for cell in row)
               for rule in f.cs.read(f.plan_ref)['payload']['method_pack']['indicators'])
    row = next(row for row in table['rows'] if 'Deferred for engineering review' in str(row))
    assert '未评分' in row
    assert '未确定' in f.cs.read(receipt['level_ref'])['payload']['body']['text']
    assert any(i['kind']=='missing' and i['adopted_value']=='未评分' for i in table['material_issues'])


@pytest.mark.parametrize('status', ['unscored', 'pending_review', 'stale', 'challenged', 'retracted', 'superseded', 'unverified', 'legacy_draft'])
def test_draft_eligibility_does_not_turn_into_score_eligibility(status):
    from report_agent.assessment_projection import draft_blocker
    receipt = dict(derivation_status=status, derived_assertion_id='native-result')
    assert score_blocker(receipt) == status
    assert (draft_blocker(receipt) is None) == (status in ('unscored', 'pending_review'))
    if status in ('unscored', 'pending_review'):
        assert draft_blocker(dict(derivation_status=status)) == status
