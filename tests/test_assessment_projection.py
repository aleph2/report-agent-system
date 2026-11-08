"""Pinned rendering refs and plan selection survive a mixed historical/new case."""
import pytest

from report_agent import legacy_state
from report_agent.store import Store, digest, encode
from test_m1_g3_integration import method_commission
from test_system_assembler import assembly_input
from test_writer_indicator_outcomes import evidence, ranked


def ref(kind, key, version=1):
    return dict(type=kind, id=key, version=version)


def test_old_and_new_receipts_and_current_selection_are_independent(tmp_path):
    from report_agent.assessment_projection import assessment_receipt, record_assessment_projection, selected_assessment
    store = Store(tmp_path)
    plan = ref('CommissionPlan', 'p')
    old = ref('Assessment', 'old')
    first = ref('Assessment', 'a')
    other = ref('Assessment', 'b')
    archive = {'assessment_ref': old}
    store.set('g6_assessment:' + digest([plan, 's']), old)
    store.set('assessment_receipt:' + digest(old), archive)
    from report_agent.content_store import Actor, ContentStore
    cs = ContentStore(store)
    with store.connect() as db:
        assert selected_assessment(db, plan, 's') == old
        assert assessment_receipt(db, old) == {**archive, 'derivation_status': 'unverified'}
        for item, select in ((first, True), (other, False)):
            result = {'status': 'legacy_draft'}
            cs._insert(db, Actor('test-writer','writer','task'), 'Assessment',
                {'commission_plan_ref':plan, 'object_id':'s', 'result':result}, id=item['id'])
            record_assessment_projection(db, plan, 's', {'assessment_ref': item, 'result': result}, select=select)
        assert selected_assessment(db, plan, 's') == old
        assert selected_assessment(db, plan, 'other') is None
        assert selected_assessment(db, {**plan, 'version': 2}, 's') is None
        assert assessment_receipt(db, first)['assessment_ref'] == first
        assert assessment_receipt(db, {**first, 'version': 2}) is None
        assert assessment_receipt(db, old) == {**archive, 'derivation_status': 'unverified'}
        assert legacy_state.get_g6_assessment(db, digest([plan, 's'])) == old
        assert legacy_state.get_assessment_receipt(db, digest(first)) is None


def test_failed_projection_transaction_preserves_selection(tmp_path):
    from report_agent.assessment_projection import assessment_receipt, record_assessment_projection, selected_assessment
    store = Store(tmp_path)
    plan, item = ref('CommissionPlan', 'p'), ref('Assessment', 'a')
    with pytest.raises(RuntimeError):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record_assessment_projection(db, plan, 's', {'assessment_ref': item, 'result': {'status': 'scored'}}, select=True)
            raise RuntimeError
    with store.connect() as db:
        assert selected_assessment(db, plan, 's') is None
        assert assessment_receipt(db, item) is None


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_pending_native_score_is_inspectable_and_can_become_stale(ranked):
    from uuid import NAMESPACE_URL, uuid5

    from report_agent import assertions, writer_assessment
    from report_agent.assertion_host import AssertionHost, Grant
    from report_agent.assessment_projection import (assessment_receipt, record_assessment_projection,
                                                     score_blocker, selected_assessment)

    f = ranked
    for indicator in 'ABCD':
        step = writer_assessment.read_indicator_step(f.cs, f.actor)
        saved = writer_assessment.save_indicator_outcome(f.cs, f.actor, 'step-' + indicator,
                                                        indicator, evidence(f, step))
    selected = saved['result']['assessment_ref']
    host = AssertionHost(f.ws.store.root)
    with f.ws.store.connect() as db:
        current = selected_assessment(db, f.plan_ref, 'S1')
        assert current == selected
        record_assessment_projection(db, f.plan_ref, 'S1', {
            'assessment_ref': ref('Assessment', 'late-compatibility-render'), 'result': {'status': 'scored'}},
            select=True)
        assert selected_assessment(db, f.plan_ref, 'S1') == selected
        receipt = assessment_receipt(db, selected)
        assert score_blocker(receipt) == 'pending_review'
        assert float(receipt['result']['adopted']['total']) == 40
        from report_agent.errors import ActionRejected
        row = db.execute('SELECT receipt FROM assessment_projections WHERE ref=?', (encode(selected),)).fetchone()
        db.execute('UPDATE assessment_projections SET receipt=? WHERE ref=?',
                   (encode({**receipt, 'result': {'status': 'scored'}}), encode(selected)))
        with pytest.raises(ActionRejected, match='PROJECTION_MISMATCH'):
            assessment_receipt(db, selected)
        db.execute('UPDATE assessment_projections SET receipt=? WHERE ref=?', (row[0], encode(selected)))
        db.execute('UPDATE assessment_projections SET native=0 WHERE ref=?', (encode(selected),))
        with pytest.raises(ActionRejected, match='PROJECTION_MISMATCH'):
            assessment_receipt(db, selected)
        db.execute('UPDATE assessment_projections SET native=1 WHERE ref=?', (encode(selected),))
        original = host.recover_receipt(receipt['derive_operation_id'])
        assert original['result']['claim']['value'] is None
        from report_agent.risk_scoring import save_assessment_in_transaction
        from report_agent.writer_assignments import bound_assignment
        from report_agent.writer_judgments import read_progress

        judgments = original['result']['claim']['inputs']
        owner = str(uuid5(NAMESPACE_URL, 'test/owner'))
        for judgment in judgments:
            grant = Grant(owner, 'owner', 'review', judgment, digest(f.plan_ref),
                          {'S1'}, {judgment}, {'confirm'})
            confirmation = assertions.confirm(host.issue(grant, 'confirm', judgment), subject='S1',
                claim=dict(kind='act', effect='confirm', target=judgment, reason='Input reviewed.'))
        scope = bound_assignment(f.cs, db, f.actor)
        draft = read_progress(f.ws.store, scope['assignment_digest'], db)
        qualified = save_assessment_in_transaction(f.cs, db, f.actor, 'updated', scope=scope, draft=draft)
        current = qualified['assessment_ref']
        assert selected_assessment(db, f.plan_ref, 'S1') == current
        assert score_blocker(assessment_receipt(db, current)) is None
        assert score_blocker(assessment_receipt(db, selected)) == 'pending_review'
        withdraw = Grant(owner, 'owner', 'withdraw-review', '1', digest(f.plan_ref), {'S1'},
                         {confirmation['id']}, {'retract'})
        assertions.retract(host.issue(withdraw, 'retract', 'withdraw'), subject='S1',
            claim=dict(kind='act', effect='retract', target=confirmation['id'], reason='Review reopened.'))
        assert score_blocker(assessment_receipt(db, current)) == 'pending_review'
        judgment = judgments[0]
        grant = Grant(str(uuid5(NAMESPACE_URL, 'test/owner')), 'owner', 'correct-input', '1',
                      digest(f.plan_ref), {'S1'}, {judgment}, {'retract'})
        assertions.retract(host.issue(grant, 'retract', 'discard'), subject='S1',
            claim=dict(kind='act', effect='retract', target=judgment, reason='Source withdrawn.'))
        assert selected_assessment(db, f.plan_ref, 'S1') == current
        assert score_blocker(assessment_receipt(db, selected)) == 'stale'
        archive_path = f.ws.store.root / 'assertions.sqlite3'
        archive_path.rename(f.ws.store.root / 'unavailable-for-test.sqlite3')
        with pytest.raises(ActionRejected, match='DERIVATION_MISSING'):
            assessment_receipt(db, current)
        assert not archive_path.exists()


@pytest.mark.parametrize('status', ['pending_review', 'unscored', 'stale', 'legacy_draft', 'superseded_by_native', 'unverified'])
def test_unavailable_scores_refused_by_assembly_and_export(assembly_input, status, monkeypatch):
    from report_agent import g3_export, system_assembler
    from report_agent.errors import ActionRejected
    from test_m1_g3_presentation import fixture as export_case

    f = assembly_input
    old = f.assessment
    receipt = {**old, 'derivation_status': status}
    monkeypatch.setattr(system_assembler, 'assessment_receipt', lambda db, ref: receipt)
    check = system_assembler.preflight_assembly(f.cs, f.co, **f.inputs)
    assert not check['ready']
    assert any(p.get('status') == status for p in check['problems'])
    args = list(export_case())
    args[0] = f.cs
    outcome = ref('AssessmentOutcome', 'outcome')
    args[1]['payload']['commission_outcome_refs'] = [outcome]
    args[2][('AssessmentOutcome', 'outcome', 1)] = {'ref': outcome, 'payload': {'assessment_ref': old['assessment_ref']}}
    monkeypatch.setattr(g3_export, 'assessment_receipt', lambda db, ref: receipt)
    with pytest.raises(ActionRejected, match='score unavailable: ' + status):
        g3_export.validate_export(*args)



@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_pinned_historical_receipt_loses_current_score_authority_after_native_judgment(ranked):
    from report_agent.assessment_projection import assessment_receipt, score_blocker
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    f = ranked
    # Represent a pre-migration content record and its existing sealed receipt without native judgments.
    result = dict(adopted=dict(total='40', level='II'))
    with f.cs.store.connect() as db:
        old = f.cs._insert(db, f.actor, 'Assessment', dict(commission_plan_ref=f.plan_ref, object_id='S1', result=result))
    receipt = dict(assessment_ref=old, result=result, level_ref=ref('ContentNode','old-level'),
                   evaluation_ref=ref('ContentNode','old-table'), evidence_ref=ref('Evidence','old-evidence'))
    f.cs.store.set('assessment_receipt:' + digest(old), receipt)
    with f.cs.store.connect() as db:
        assert score_blocker(assessment_receipt(db, old)) is None
        assert score_blocker({'result': {'status': 'scored'}}) == 'unverified'
    step = read_indicator_step(f.cs, f.actor)
    save_indicator_outcome(f.cs, f.actor, 'native-first', step['indicator_id'], evidence(f, step))
    with f.cs.store.connect() as db:
        assert score_blocker(assessment_receipt(db, old)) == 'superseded_by_native'
        assert legacy_state.get_assessment_receipt(db, digest(old)) == receipt
