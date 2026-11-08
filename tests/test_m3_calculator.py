"""Bounded scenarios for open positions under the confirmed rank-weight rule."""
from uuid import NAMESPACE_URL, uuid5

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.errors import ActionRejected
from report_agent.risk_scoring import save_assessment_in_transaction, save_assessment
from report_agent.store import digest
from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
from report_agent.writer_assignments import bound_assignment
from report_agent.writer_judgments import read_progress
from test_m1_g3_integration import method_commission
from test_writer_indicator_outcomes import evidence, ranked
from test_m1_g3_method_pack import pack_data
from test_m1_g3_scoring import assessment_data


def test_missing_value_has_method_bounds_without_an_adopted_value():
    from report_agent.assessment_results import unscored_result
    pack = pack_data()
    saved = {row['indicator_id']: {'kind': 'evidence', 'judgment': row, 'rank': row['rank']}
             for row in assessment_data()['indicators']}
    for entry in saved.values():
        entry['judgment'].update(basis_kind='direct_evidence', grade_id='g2', value='40', low=None, high=None)
    saved['D'] = {'kind': 'gap', 'rank': 4, 'claim': {'alternatives': ['g1', 'g2']}}
    result = unscored_result(pack, 'rank-lookup', ['A','B','C','D'], saved, {})
    assert result['status'] == 'unscored' and 'adopted' not in result
    assert result['missing_indicators'] == ['D']
    assert result['low'] == {'total': '36.0', 'level': 'II'}
    assert result['high'] == {'total': '40.9', 'level': 'II'}
    assert result['level_robust'] is True


def test_interrupted_position_uses_full_rule_domain_without_inventing_a_judgment():
    from report_agent.assessment_results import unscored_result
    result = unscored_result(pack_data(), 'rank-lookup', ['A','B','C','D'], {}, {'A': {}})
    assert result['missing_indicators'] == ['A','B','C','D']
    assert result['interrupted_indicators'] == ['A']
    assert result['low']['level'] == 'I' and result['high']['level'] == 'IV'
    assert result['level_robust'] is False and result['rows'] == []


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_native_derivation_keeps_draft_distinct_and_recomputes_from_immutable_submissions(ranked):
    f = ranked
    for indicator in ('A', 'B', 'C', 'D'):
        step = read_indicator_step(f.cs, f.actor)
        final = save_indicator_outcome(f.cs, f.actor, 'save-' + indicator, indicator, evidence(f, step))['result']
    projected = f.cs.read(final['assessment_ref'])['payload']
    bulk = {key: projected[key] for key in ('object_id', 'section_id', 'method_id', 'method_version',
                                              'weight_strategy_id', 'indicators')}
    with pytest.raises(ActionRejected, match='NATIVE_INPUTS_REQUIRED'):
        save_assessment(f.cs, f.actor, 'bypass-native-review', bulk)
    host = AssertionHost(f.cs.store.root)
    original = host.recover_receipt(projected['derive_operation_id'])
    calc, claim = original['binding']['actor'], original['result']['claim']
    assert original['result']['schema_version'] == 'm3-assessment-1'
    assert original['binding']['role'] == 'calculator' and calc != str(uuid5(NAMESPACE_URL, f.actor.id))
    assert claim['strength'] == 'undetermined' and claim['value'] is None
    assert claim['assessment']['status'] == 'pending_review' and 'adopted' not in claim['assessment']
    assert claim['assessment']['draft_arithmetic'] == projected['result']['adopted']
    with f.cs.store.connect() as db:
        scope = bound_assignment(f.cs, db, f.actor)
        draft = read_progress(f.cs.store, scope['assignment_digest'], db)
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected, match='ASSESSMENT_INPUT_MODE_MISMATCH'):
            save_assessment_in_transaction(f.cs, db, f.actor, 'mixed-inputs', bulk, scope=scope, draft=draft)
        with pytest.raises(ActionRejected, match='ASSESSMENT_ASSIGNMENT_CHANGED'):
            save_assessment_in_transaction(f.cs, db, f.actor, 'stale-assignment',
                                           scope={**scope, 'assignment_digest': 'old-assignment'}, draft=draft)
    assert [r['ref'] for r in f.cs.list_objects('Assessment')] == [final['assessment_ref']]
    ids = [draft['rows'][key]['assertion_id'] for key in ('A', 'B', 'C', 'D')]
    assert claim['inputs'] == ids
    assert claim['assessment']['low'] == claim['assessment']['high'] == projected['result']['adopted']
    for key in ids:
        grant = Grant(str(uuid5(NAMESPACE_URL, 'test/owner')), 'owner', 'test-review', key,
                      digest(scope['plan']['ref']), frozenset(['S1']), frozenset([key]), frozenset(['confirm']))
        ctx = host.issue_once(grant, 'confirm', 'review-' + key)
        assertions.confirm(ctx, subject='S1', claim=dict(kind='act', target=key, effect='confirm', reason='Reviewed input'))
    draft['rows']['A']['judgment']['value'] = '99'
    with f.cs.store.connect() as db:
        recalculated = save_assessment_in_transaction(f.cs, db, f.actor, 'reviewed-score', scope=scope, draft=draft)
        omitted = {**draft, 'rows': {k: v for k, v in draft['rows'].items() if k != 'A'}}
        with pytest.raises(ActionRejected, match='PROGRESS_MISMATCH'):
            save_assessment_in_transaction(f.cs, db, f.actor, 'omit-judgment', scope=scope, draft=omitted)
        swapped = {**draft, 'rows': {**draft['rows'], 'B': draft['rows']['A']}}
        with pytest.raises(ActionRejected, match='BINDING_MISMATCH'):
            save_assessment_in_transaction(f.cs, db, f.actor, 'wrong-indicator', scope=scope, draft=swapped)
    reviewed = host.recover_receipt(recalculated['derive_operation_id'])['result']['claim']
    assert reviewed['inputs'] == ids and reviewed['strength'] == 'determined'
    assert reviewed['assessment']['status'] == 'scored' and 'draft_arithmetic' not in reviewed['assessment']
    assert reviewed['assessment']['adopted'] == projected['result']['adopted']
    assert reviewed['value'] == projected['result']['adopted']['total']


def test_partial_envelope_outside_defined_risk_bands_preserves_bounds_without_claiming_robustness():
    from report_agent.assessment_results import unscored_result
    pack = pack_data()
    pack['risk_bands'] = pack['risk_bands'][1:]
    result = unscored_result(pack, 'rank-lookup', ['A','B','C','D'], {}, {})
    assert result['low'] == {'total': '0.0', 'level': None} and result['high']['level'] == 'IV'
    assert result['level_robust'] is None and 'adopted' not in result


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_raw_first_system_writer_keeps_a_draft_without_selecting_or_qualifying_a_score(ranked):
    from report_agent.assessment_projection import assessment_receipt, selected_assessment, score_blocker
    from report_agent.risk_scoring import validate_outcome
    from test_m1_g3_integration import persistence_input
    f = ranked
    raw = save_assessment(f.cs, f.actor, 'fresh-bulk', persistence_input(f))['result']
    with f.cs.store.connect() as db:
        plan = f.cs._read(db, f.plan_ref)
        ref = raw['assessment_ref']
        assert selected_assessment(db, f.plan_ref, 'S1') is None
        assert score_blocker(assessment_receipt(db, ref)) == 'legacy_draft'
        from report_agent.risk_scoring import create_planned_section_in_transaction
        with pytest.raises(ActionRejected, match='PLANNED_SECTION_REVIEWED_SCORE_REQUIRED: legacy_draft'):
            create_planned_section_in_transaction(f.cs, db, f.actor, plan, '5', [ref])
        with pytest.raises(ActionRejected, match='REVIEWED_SCORE_REQUIRED'):
            validate_outcome(f.cs, db, plan, 'S1', raw['evaluation_ref'], raw['level_ref'], [raw['evidence_ref']], [])
        from report_agent.store import encode
        db.execute('UPDATE assessment_projections SET native=1,selected=1 WHERE ref=?', (encode(ref),))
        with pytest.raises(ActionRejected, match='PROJECTION_MISMATCH'):
            selected_assessment(db, f.plan_ref, 'S1')
    assert raw['result']['adopted'] and 'derived_assertion_id' not in raw
    assert '草稿' in f.cs.read(raw['level_ref'])['payload']['body']['text']


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_legacy_g3_score_cannot_be_promoted_by_switching_the_case_to_native_writing(ranked):
    from report_agent.assessment_projection import assessment_receipt, score_blocker
    from test_m1_g3_integration import persistence_input

    f = ranked
    manifest = f.cs.store.manifest
    f.cs.store.set('manifest', {k: v for k, v in manifest.items() if k != 'assembly_contract'})
    raw = save_assessment(f.cs, f.actor, 'legacy-g3', persistence_input(f))['result']
    with f.cs.store.connect() as db:
        assert score_blocker(assessment_receipt(db, raw['assessment_ref'])) is None
    f.cs.store.set('manifest', manifest)
    with f.cs.store.connect() as db:
        assert score_blocker(assessment_receipt(db, raw['assessment_ref'])) == 'legacy_draft'
