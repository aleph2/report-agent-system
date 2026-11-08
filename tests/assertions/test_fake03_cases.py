import pytest

from .cases import CASES, CURRENT_X51, grade_data, historical_action, evaluate, current_x51_gap
from .sqlite_probe import Packet, Store


@pytest.mark.parametrize('label', CASES)
def test_recorded_replay(tmp_path, label):
    store = Store.create(tmp_path / 'case.sqlite')
    action, original = historical_action(label)
    packet = Packet()
    store.assign(packet, [action.slope])
    result = store.perform(packet, action, evaluate)
    assert result == store.result(action.operation)
    verdict, detail = CASES[label]
    view = store.reviewer_view(action.operation)
    if verdict == 'refused':
        assert result['status'] == 'refused'
        assert all(token in result['reason'] for token in ('WRITER_CLAIM_UNSUPPORTED', detail, 'save_gap'))
        assert view is None
        assert store.counts() == (0, 0, 1, 0)
        return
    assert result['status'] == 'committed'
    row, checks = view
    assert row['kind'] == original['kind'] and row['grade'] == original['grade']
    assert row['question'] == original['question']
    assert bool(checks['semantic_review_required'])
    if label == 'A/X51':
        assert grade_data(action)['id'] == 'moderate'
        assert row['value'] == '37'
        adjustment = checks['adjustment']
        assert adjustment['status'] == 'refused_midpoint_retained'
        assert adjustment['proposed_value'] == original['value'] == '49'
        assert adjustment['original_rationale'] == original['rationale']
    else:
        for key in ('value', 'rationale', 'missing', 'basis_kind', 'plausible_grades'):
            assert row[key] == original[key]
    if label == 'A/X32':
        assert row['kind'] == 'assumption' and row['value'] == '27' and row['question']
        assert checks['seasonal_adjustment_target'] == 'in_band_value'
    if verdict == 'flagged':
        assert detail in checks['review_flags']
    else:
        assert not set(checks['review_flags']).intersection({'QUESTION_EFFECT_CONFLICT','UNSUPPORTED_ADJUSTMENT_RETAINED_MIDPOINT'})


def test_current_x51_deferral_separate_from_historical_midpoint(tmp_path):
    store = Store.create(tmp_path / 'case.sqlite')
    packet = Packet()
    store.assign(packet, ['A'])
    scored, _ = historical_action('A/X51')
    result = store.perform(packet, scored, current_x51_gap)
    assert result['status'] == 'refused' and 'WRITER_ENGINEERING_REVIEW_PENDING' in result['reason']
    assert store.reviewer_view(scored.operation) is None
    gap = scored.model_copy(update={'operation':'deferred-gap', 'proposal': {
        'kind':'gap', 'missing':CURRENT_X51['reason'], 'question':'Which low-band convention applies?',
        'fact_ids':['F03-A-SURVEY-SECTIONS','F03-A-BOREHOLES']}})
    assert store.perform(packet, gap, current_x51_gap)['status'] == 'committed'
    row, audit = store.reviewer_view(gap.operation)
    assert row['kind'] == 'gap' and row['value'] is None and row['grade'] is None
    assert audit['engineering_review']['conditional_grades'] == ['low', 'moderate']
    assert audit['engineering_review']['status'] == 'deferred_to_engineering'
