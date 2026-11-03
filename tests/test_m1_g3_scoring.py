"""Hand-derived scoring oracles; source-role/checkpoint integration is separate."""
from copy import deepcopy
from decimal import Decimal

import pytest

from report_agent.errors import ActionRejected
from test_m1_g3_method_pack import citation, pack_data


def assessment_data():
    return {'object_id': 'S1', 'method_id': 'synthetic-four', 'method_version': 1,
            'weight_strategy_id': 'rank-lookup', 'indicators': [
                {'indicator_id': name, 'rank': rank,
                 'grade_id': 'g4' if kind == 'no_evidence_assumption' else 'g2',
                 'value': '75' if kind == 'no_evidence_assumption' else '40',
                 'basis_kind': kind, 'sources': [] if kind == 'no_evidence_assumption' else [citation('design')],
                 'rationale': 'No indirect source exists.' if kind == 'no_evidence_assumption' else 'Located basis.',
                 'question': 'Confirm this value.' if 'assumption' in kind else '',
                 'low': '30' if 'assumption' in kind else None,
                 'high': '90' if kind == 'no_evidence_assumption' else '60' if 'assumption' in kind else None}
                for rank, (name, kind) in enumerate(zip(('A', 'B', 'C', 'D'), (
                    'direct_evidence', 'applied_guideline', 'indirect_assumption',
                    'no_evidence_assumption')), 1)]}


def calculate(pack=None, assessment=None):
    from report_agent.risk_scoring import calculate as score
    return score(pack or pack_data(), assessment or assessment_data())


def test_four_basis_classes_count_as_scored_and_bounds_do_not_change_the_level():
    result = calculate()
    assert Decimal(result['adopted']['total']) == Decimal('43.5')
    assert Decimal(result['low']['total']) == Decimal('37')
    assert Decimal(result['high']['total']) == Decimal('49')
    assert {result[key]['level'] for key in ('adopted', 'low', 'high')} == {'II'}
    assert result['affects_level'] is False
    assert {row['indicator_id'] for row in result['rows']} == {'A', 'B', 'C', 'D'}


def test_joint_extremes_detect_change_that_each_assumption_alone_misses():
    assessment = assessment_data()
    for index, row in enumerate(assessment['indicators']):
        row.update(value='40', grade_id='g2',
                   basis_kind='indirect_assumption' if index < 2 else 'direct_evidence',
                   sources=[citation('survey')], question='Confirm range.' if index < 2 else '',
                   low='30' if index < 2 else None, high='60' if index < 2 else None)
    result = calculate(assessment=assessment)
    assert Decimal(result['low']['total']) == Decimal('33')
    assert Decimal(result['high']['total']) == Decimal('54')
    assert result['adopted']['level'] == 'II'
    assert result['high']['level'] == 'III'
    assert result['affects_level'] is True
    for fixed in (0, 1):
        one = deepcopy(assessment)
        one['indicators'][fixed].update(low='40', high='40')
        assert calculate(assessment=one)['affects_level'] is False


def test_explicit_strategy_selects_available_data_and_rank_not_input_order():
    assessment = assessment_data()
    for row, value, grade in zip(assessment['indicators'], ('100', '0', '0', '0'), ('g4', 'g1', 'g1', 'g1')):
        row.update(value=value, grade_id=grade, basis_kind='direct_evidence',
                   sources=[citation('design')], low=None, high=None, question='')
    assert Decimal(calculate(assessment=assessment)['adopted']['total']) == Decimal('40')
    assessment['weight_strategy_id'] = 'alternative-lookup'
    assert Decimal(calculate(assessment=assessment)['adopted']['total']) == Decimal('31')
    assessment['indicators'][0]['rank'], assessment['indicators'][3]['rank'] = 4, 1
    assert Decimal(calculate(assessment=assessment)['adopted']['total']) == Decimal('19')
    assessment['indicators'].reverse()
    assert Decimal(calculate(assessment=assessment)['adopted']['total']) == Decimal('19')


@pytest.mark.parametrize('value,grade,level', [
    ('0', 'g1', 'I'), ('24', 'g1', 'I'), ('25', 'g2', 'II'),
    ('49', 'g2', 'II'), ('50', 'g3', 'III'), ('74', 'g3', 'III'),
    ('75', 'g4', 'IV'), ('100', 'g4', 'IV'),
])
def test_exact_risk_boundaries_and_final_inclusive_endpoint(value, grade, level):
    assessment = assessment_data()
    for row in assessment['indicators']:
        row.update(value=value, grade_id=grade, basis_kind='direct_evidence',
                   sources=[citation('design')], low=None, high=None, question='')
    result = calculate(assessment=assessment)
    assert result['adopted']['level'] == level
    assert Decimal(result['adopted']['total']) == Decimal(value)
    assert result['affects_level'] is False


def test_lookup_preserves_exact_decimals_without_rounding_to_integer():
    assessment = assessment_data()
    for row in assessment['indicators']:
        row.update(value='40.125', grade_id='g2', basis_kind='direct_evidence', sources=[citation('design')],
                   low=None, high=None, question='')
    assert Decimal(calculate(assessment=assessment)['adopted']['total']) == Decimal('40.125')


@pytest.mark.parametrize('value,grade,level', [
    ('30', 'g2', 'I'), ('30.001', 'g2', 'II'), ('45', 'g2', 'II'),
    ('45.001', 'g2', 'III'), ('60', 'g3', 'III'), ('60.001', 'g3', 'IV'),
    ('100', 'g4', 'IV'),
])
def test_guideline_style_upper_inclusive_boundaries(value, grade, level):
    # Bounds independently read from supplied guideline physical page 24, Table 3-3.
    pack, assessment = pack_data(), assessment_data()
    pack['risk_bands'] = [
        {'level': 'I', 'lower': '0', 'upper': '30', 'upper_inclusive': True},
        {'level': 'II', 'lower': '30', 'upper': '45', 'lower_inclusive': False, 'upper_inclusive': True},
        {'level': 'III', 'lower': '45', 'upper': '60', 'lower_inclusive': False, 'upper_inclusive': True},
        {'level': 'IV', 'lower': '60', 'upper': '100', 'lower_inclusive': False, 'upper_inclusive': True}]
    for row in assessment['indicators']:
        row.update(value=value, grade_id=grade, basis_kind='direct_evidence',
                   sources=[citation('design')], low=None, high=None, question='')
    assert calculate(pack, assessment)['adopted']['level'] == level


def test_no_evidence_fallback_cannot_select_a_more_favourable_grade():
    assessment = assessment_data()
    assessment['indicators'][3].update(grade_id='g2', value='40', low='30', high='90')
    with pytest.raises(ActionRejected, match='ASSESSMENT_INVALID:'):
        calculate(assessment=assessment)


@pytest.mark.parametrize('fault', [
    'wrong-method', 'stale-version', 'unknown-strategy', 'missing-indicator',
    'extra-indicator', 'duplicate-indicator', 'duplicate-rank', 'rank-zero',
    'rank-too-large', 'unknown-grade', 'value-outside-grade', 'missing-value',
    'nan-value', 'infinite-bound', 'reversed-bound', 'adopted-outside-bounds',
    'missing-bound', 'missing-question', 'missing-direct-source',
    'missing-indirect-source', 'missing-rationale', 'unknown-basis',
])
def test_invalid_assessment_is_rejected_without_filling_or_omitting_values(fault):
    assessment = assessment_data()
    first, assumed = assessment['indicators'][0], assessment['indicators'][2]
    if fault == 'wrong-method':
        assessment['method_id'] = 'other'
    elif fault == 'stale-version':
        assessment['method_version'] = 2
    elif fault == 'unknown-strategy':
        assessment['weight_strategy_id'] = 'invented-formula'
    elif fault == 'missing-indicator':
        assessment['indicators'].pop()
    elif fault == 'extra-indicator':
        assessment['indicators'].append(dict(first, indicator_id='E', rank=5))
    elif fault == 'duplicate-indicator':
        assessment['indicators'][1]['indicator_id'] = 'A'
    elif fault == 'duplicate-rank':
        first['rank'] = 2
    elif fault == 'rank-zero':
        first['rank'] = 0
    elif fault == 'rank-too-large':
        first['rank'] = 5
    elif fault == 'unknown-grade':
        first['grade_id'] = 'invented'
    elif fault == 'value-outside-grade':
        first['value'] = '90'
    elif fault == 'missing-value':
        first.pop('value')
    elif fault == 'nan-value':
        first['value'] = 'NaN'
    elif fault == 'infinite-bound':
        assumed['high'] = 'Infinity'
    elif fault == 'reversed-bound':
        assumed.update(low='60', high='30')
    elif fault == 'adopted-outside-bounds':
        assumed.update(low='45', high='60')
    elif fault == 'missing-bound':
        assumed['low'] = None
    elif fault == 'missing-question':
        assumed['question'] = ''
    elif fault == 'missing-direct-source':
        first['sources'] = []
    elif fault == 'missing-indirect-source':
        assumed['sources'] = []
    elif fault == 'missing-rationale':
        assessment['indicators'][3]['rationale'] = ''
    else:
        first['basis_kind'] = 'unresolved'
    with pytest.raises(ActionRejected, match='ASSESSMENT_INVALID:'):
        calculate(assessment=assessment)


def test_validation_reports_independent_input_problems_together():
    assessment = assessment_data()
    assessment['indicators'][0]['rank'] = 2
    assessment['indicators'][1]['value'] = 'NaN'
    assessment['indicators'][2]['question'] = ''
    with pytest.raises(ActionRejected, match='ASSESSMENT_INVALID:') as error:
        calculate(assessment=assessment)
    message = str(error.value).lower()
    assert 'rank' in message
    assert 'value' in message or 'finite' in message
    assert 'question' in message


def test_two_indicator_calculation_selects_the_matching_count_row():
    pack, assessment = pack_data(), assessment_data()
    pack['indicators'] = pack['indicators'][:2]
    assessment['indicators'] = assessment['indicators'][:2]
    assessment['indicators'][0].update(value='100', grade_id='g4')
    assessment['indicators'][1].update(value='0', grade_id='g1')
    assert Decimal(calculate(pack, assessment)['adopted']['total']) == Decimal('60')
