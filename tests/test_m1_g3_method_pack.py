"""Synthetic reviewed data checks; these fixtures are not guideline transcriptions."""
from copy import deepcopy

import pytest


def citation(source='guideline', quote='Synthetic method data for unit tests.'):
    return {'source_ref': {'type': 'SourceArtifact', 'id': source, 'version': 1},
            'locator': 'page 1', 'quote': quote}


def pack_data():
    return {
        'method_id': 'synthetic-four', 'version': 1, 'sources': [citation()],
        'indicators': [
            {'id': name, 'label': 'Indicator ' + name, 'category': 'Synthetic',
             'notes': 'Use the supplied source interpretation.', 'grades': [
                 {'id': 'g1', 'min_value': '0', 'max_value': '24', 'description': 'First'},
                 {'id': 'g2', 'min_value': '25', 'max_value': '49', 'description': 'Second'},
                 {'id': 'g3', 'min_value': '50', 'max_value': '74', 'description': 'Third'},
                 {'id': 'g4', 'min_value': '75', 'max_value': '100', 'description': 'Fourth'}]}
            for name in ('A', 'B', 'C', 'D')],
        'risk_bands': [
            {'level': 'I', 'lower': '0', 'upper': '25'},
            {'level': 'II', 'lower': '25', 'upper': '50'},
            {'level': 'III', 'lower': '50', 'upper': '75'},
            {'level': 'IV', 'lower': '75', 'upper': '100', 'upper_inclusive': True}],
        'weight_tables': [
            {'id': 'rank-lookup', 'source': citation(), 'rows': [
                {'indicator_count': 2, 'weights': ['0.6', '0.4']},
                {'indicator_count': 4, 'weights': ['0.4', '0.3', '0.2', '0.1']}]},
            {'id': 'alternative-lookup', 'source': citation(), 'rows': [
                {'indicator_count': 4, 'weights': ['0.31', '0.29', '0.21', '0.19']}]}]}


def validate(pack):
    from report_agent.method_pack import MethodPack
    return MethodPack.model_validate(pack)


def test_pack_preserves_source_versions_grade_notes_and_multiple_available_tables():
    raw = pack_data()
    saved = validate(raw).model_dump(mode='json')
    assert saved['sources'] == raw['sources']
    assert saved['indicators'] == raw['indicators']
    assert saved['weight_tables'] == raw['weight_tables']
    assert saved['risk_bands'][-1]['upper_inclusive'] is True
    assert 'weight_strategy_id' not in saved


@pytest.mark.parametrize('fault', [
    'duplicate-indicator', 'duplicate-grade', 'reversed-grade', 'duplicate-table',
    'duplicate-count', 'wrong-weight-count', 'negative-weight', 'nan-weight',
    'infinite-grade', 'overlapping-grades', 'reversed-risk-band', 'overlapping-risk-bands',
    'risk-band-gap', 'empty-indicators',
])
def test_ambiguous_or_unusable_method_data_is_rejected(fault):
    pack = pack_data()
    if fault == 'duplicate-indicator':
        pack['indicators'].append(deepcopy(pack['indicators'][0]))
    elif fault == 'duplicate-grade':
        pack['indicators'][0]['grades'][1]['id'] = 'g1'
    elif fault == 'reversed-grade':
        pack['indicators'][0]['grades'][0]['min_value'] = '30'
    elif fault == 'duplicate-table':
        pack['weight_tables'][1]['id'] = 'rank-lookup'
    elif fault == 'duplicate-count':
        pack['weight_tables'][0]['rows'].append(deepcopy(pack['weight_tables'][0]['rows'][0]))
    elif fault == 'wrong-weight-count':
        pack['weight_tables'][0]['rows'][0]['weights'].pop()
    elif fault == 'negative-weight':
        pack['weight_tables'][0]['rows'][0]['weights'][0] = '-0.6'
    elif fault == 'nan-weight':
        pack['weight_tables'][0]['rows'][0]['weights'][0] = 'NaN'
    elif fault == 'infinite-grade':
        pack['indicators'][0]['grades'][0]['max_value'] = 'Infinity'
    elif fault == 'overlapping-grades':
        pack['indicators'][0]['grades'][0]['max_value'] = '25'
    elif fault == 'reversed-risk-band':
        pack['risk_bands'][0]['lower'] = '30'
    elif fault == 'overlapping-risk-bands':
        pack['risk_bands'][0]['upper_inclusive'] = True
    elif fault == 'risk-band-gap':
        pack['risk_bands'][1]['lower'] = '26'
    else:
        pack['indicators'] = []
    with pytest.raises(ValueError):
        validate(pack)


def test_two_indicator_pack_is_valid_without_assuming_eleven_indicators():
    pack = pack_data()
    pack['indicators'] = pack['indicators'][:2]
    assert len(validate(pack).indicators) == 2


def test_known_guideline_binding_rejects_numeric_changes_despite_genuine_source_identity():
    import json
    from importlib.resources import files
    from types import SimpleNamespace
    from report_agent.errors import ActionRejected
    from report_agent.method_pack import bind_guideline, reviewed_method_questions
    data = json.loads(files('report_agent').joinpath('methods/high_slope_guideline.json').read_text(encoding='utf-8'))
    source_ref = citation()['source_ref']
    source_hash = data['metadata']['file_sha256']
    pack = bind_guideline(source_ref, source_hash)
    cs = SimpleNamespace(_read=lambda db, ref: {'payload': {'file_digest': source_hash}})
    assert reviewed_method_questions(cs, None, pack) == []
    altered = deepcopy(pack)
    row = next(row for row in altered['weight_tables'][0]['rows'] if row['indicator_count'] == 11)
    row['weights'][0], row['weights'][1] = row['weights'][1], row['weights'][0]
    with pytest.raises(ActionRejected, match='REVIEWED_DATA_CHANGED'):
        reviewed_method_questions(cs, None, altered)
    with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
        bind_guideline(source_ref, '0' * 64)


def test_generic_pack_registration_requires_explicit_review_and_exact_data(tmp_path):
    from report_agent.method_pack import register_reviewed_method_pack
    from report_agent.store import Store, digest
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic method registry', 'sources': [
        {'id': 'synthetic', 'content': 'Synthetic method data.', 'coverage': 'complete'}]})
    pack = pack_data()
    canonical = validate(pack).model_dump(mode='json')
    key = 'reviewed_method_pack:' + digest(canonical)
    with pytest.raises(ValueError, match='REVIEW_NOTE_REQUIRED'):
        register_reviewed_method_pack(store, pack, '')
    assert store.get(key) is None
    register_reviewed_method_pack(store, pack, 'Independent synthetic method review.')
    assert store.get(key) == {'reviewer': 'operator', 'review_note': 'Independent synthetic method review.'}
    altered = deepcopy(canonical)
    altered['weight_tables'][0]['rows'][1]['weights'].reverse()
    assert store.get('reviewed_method_pack:' + digest(altered)) is None
    with pytest.raises(ValueError, match='VERSION_ALREADY_REVIEWED'):
        register_reviewed_method_pack(store, altered, 'Attempted overwrite of the reviewed version.')
    assert store.get(key) == {'reviewer': 'operator', 'review_note': 'Independent synthetic method review.'}
    assert store.get('reviewed_method_pack:' + digest(altered)) is None
