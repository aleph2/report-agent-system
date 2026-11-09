import sqlite3

import pytest

from report_agent.errors import ActionRejected
from report_agent import commission_plan, plan_authority
from support.plan_fixture import approve, confirmed_records, save
from test_m1_commission_plan import commission


def test_approval_requires_committed_owner_confirmation(commission):
    saved = save(commission)
    approve(commission, saved)
    plan, decision = confirmed_records(commission)
    with sqlite3.connect(commission.ws.store.root / 'assertions.sqlite3') as db:
        proposal_id = plan['plan_authority']['assertion_id']
        proof_id = decision['plan_authority']['assertion_id']
        assert db.execute('SELECT action,role FROM assertions WHERE id=?', (proposal_id,)).fetchone() == (
            'record_convention', 'coordinator')
        row = db.execute("SELECT action,role,body ->> '$.claim.target' FROM assertions WHERE id=?", (proof_id,))
        assert row.fetchone() == ('confirm', 'owner', proposal_id)
        db.execute('DELETE FROM assertions WHERE id=?', (proof_id,))
    with pytest.raises(ActionRejected, match='PLAN_AUTHORITY'):
        confirmed_records(commission)


def test_content_failure_rolls_back_native_proposal_and_owner_act(commission):
    cs = commission.cs
    def fail_on(kind):
        with cs.store.connect() as db:
            db.execute(f"CREATE TRIGGER injected_failure BEFORE INSERT ON content_versions WHEN NEW.type='{kind}' "
                       "BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    def unhook():
        with cs.store.connect() as db:
            db.execute("DROP TRIGGER injected_failure")
    def count():
        with sqlite3.connect(cs.store.root / 'assertions.sqlite3') as db:
            return db.execute('SELECT count(*) FROM assertions').fetchone()[0]
    fail_on('CommissionPlan')
    with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
        save(commission)
    assert plan_authority.plan_ref(cs.store) is None and count() == 0
    unhook()
    saved = save(commission)
    fail_on('CommissionDecision')
    with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
        approve(commission, saved)
    assert plan_authority.decision_ref(cs.store) is None and count() == 1
    unhook()
    approve(commission, saved)
    assert confirmed_records(commission)[0]['ref'] == saved['plan_ref'] and count() == 2


@pytest.mark.parametrize('kind', ['proposal', 'decision'])
def test_exact_business_retry_recovers_missing_native_commit(commission, kind):
    saved = save(commission)
    checkpoint, answer = approve(commission, saved)
    plan, decision = confirmed_records(commission)
    record = plan if kind == 'proposal' else decision
    link = record['plan_authority']
    with sqlite3.connect(commission.cs.store.root / 'assertions.sqlite3') as db:
        db.execute('DELETE FROM assertions WHERE id=?', (link['assertion_id'],))
        db.execute('DELETE FROM operations WHERE id=?', (link['operation_id'],))
    with pytest.raises(ActionRejected, match='PLAN_AUTHORITY_INVALID'):
        confirmed_records(commission)
    if kind == 'proposal':
        assert save(commission) == saved
    else:
        commission_plan.reply(commission.ws, checkpoint['issue_id'], answer)
    assert confirmed_records(commission) == (plan, decision)


@pytest.mark.parametrize('kind', ['proposal', 'decision'])
def test_exact_native_retry_recovers_missing_business_commit(commission, kind):
    cs = commission.cs
    if kind == 'decision':
        saved = save(commission)
        checkpoint = commission_plan.request_checkpoint(commission.ws)
        answer = dict(plan_ref=saved['plan_ref'], approved=True, corrections='', reductions=[])
    def replay():
        if kind == 'proposal':
            return save(commission)['plan_ref']
        commission_plan.reply(commission.ws, checkpoint['issue_id'], answer)
        return plan_authority.decision_ref(cs.store)
    # Restore only the previous business side to simulate a split multi-database WAL commit.
    with cs.store.connect() as db, sqlite3.connect(':memory:') as before:
        db.backup(before)
        ref = replay()
        before.backup(db)
    assert replay() == ref
    with sqlite3.connect(cs.store.root / 'assertions.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM assertions').fetchone()[0] == (1 if kind=='proposal' else 2)


def test_owner_choices_are_bound_to_the_exact_decision(commission):
    saved = save(commission)
    approve(commission, saved)
    _, decision = confirmed_records(commission)
    with commission.cs.store.connect() as db:
        db.execute("UPDATE content_versions SET data=json_set(data, '$.payload.reductions', json(?)) WHERE type=?",
                   ('[{"object_id":"S2","reason":"Tampered exclusion"}]', 'CommissionDecision'))
    with pytest.raises(ActionRejected, match='PLAN_AUTHORITY_INVALID'):
        confirmed_records(commission)


def test_superseded_plan_copy_keeps_only_the_selected_approval(commission, tmp_path_factory):
    from copy import deepcopy
    from report_agent.content_store import ContentStore
    from report_agent.probe_case import prepare_probe_case
    from report_agent.store import Store

    first = save(commission)
    approve(commission, first)
    previous_plan, previous_decision = confirmed_records(commission)
    revision = deepcopy(commission.plan)
    revision['open_questions'].append('Confirm the revision')
    second = save(commission, revision, 'second-plan')
    approve(commission, second)
    current_plan, current_decision = confirmed_records(commission)
    case = tmp_path_factory.mktemp('accepted-plan-copy') / 'business'
    prepare_probe_case(commission.cs.store.root, case, expected_plan_ref=current_plan['ref'],
                       expected_decision_ref=current_decision['ref'])
    copied = ContentStore(Store(case))
    with copied.store.connect() as db:
        assert commission_plan._confirmed(copied, db) == (current_plan, current_decision)
        assert copied._read(db, first['plan_ref']) == previous_plan
    with sqlite3.connect(case / 'assertions.sqlite3') as db:
        actions = dict(db.execute('SELECT id,action FROM assertions'))
    assert actions[previous_plan['plan_authority']['assertion_id']] == 'record_convention'
    assert previous_decision['plan_authority']['assertion_id'] not in actions
    assert not (case / 'assertion-access.sqlite3').exists()


def test_withdrawn_owner_confirmation_cannot_reissue_the_checklist(commission):
    from uuid import NAMESPACE_URL, uuid5
    from report_agent import assertions
    from report_agent.assertion_host import AssertionHost, Grant
    from report_agent.store import digest

    saved = save(commission)
    checkpoint, answer = approve(commission, saved)
    plan, decision = confirmed_records(commission)
    receipt = decision['plan_authority']['assertion_id']
    subject = plan['ref']['id']
    host = AssertionHost(commission.cs.store.root)
    grant = Grant(str(uuid5(NAMESPACE_URL, 'operator')), 'owner', 'withdraw-approval', 'direct',
                  digest(plan['ref']), {subject}, {receipt}, {'retract'})
    assertions.retract(host.issue_once(grant, 'retract', 'withdraw'), subject=subject,
                       claim=dict(kind='act', effect='retract', target=receipt, reason='Owner withdrew approval'))
    path = commission.cs.store.root / commission_plan._checklist_path(decision['ref'])
    path.unlink()
    with pytest.raises(ActionRejected, match='PLAN_AUTHORITY_INVALID'):
        commission_plan.reply(commission.ws, checkpoint['issue_id'], answer)
    assert not path.exists()


def test_owner_confirmation_binds_the_pinned_template_profile_payload(commission):
    from report_agent import plan_inputs
    from report_agent.store import digest, encode

    with commission.cs.store.connect() as db:
        ref = plan_inputs.save_text_profiles(db, {'template': 'original'})
    saved = save(commission)
    approve(commission, saved)
    plan, _ = confirmed_records(commission)
    assert plan['plan_authority']['inputs'] == [{'ref': ref, 'digest': digest({'template': 'original'})}]
    with commission.cs.store.connect() as db:
        profile = commission.cs._read(db, ref)
        profile['payload'] = {'template': 'wrong'}
        profile['payload_digest'] = digest(profile['payload'])
        db.execute('UPDATE content_versions SET data=? WHERE type=?', (encode(profile), 'PlanTextProfiles'))
    with pytest.raises(ActionRejected, match='AUTHORITY_INPUT_MISMATCH'):
        confirmed_records(commission)
