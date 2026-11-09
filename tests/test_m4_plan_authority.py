import sqlite3

import pytest

from report_agent.errors import ActionRejected
from report_agent import commission_plan, plan_authority
from support.plan_fixture import approve, confirmed_records, plan_action_id, save
from test_m1_commission_plan import commission


def test_approval_requires_committed_owner_confirmation(commission):
    saved = save(commission)
    approve(commission, saved)
    plan, decision = confirmed_records(commission)
    with sqlite3.connect(commission.ws.store.root / 'assertions.sqlite3') as db:
        assert 'plan_authority' not in plan and 'plan_authority' not in decision
        proposal_id = plan_action_id(commission, 'record_convention', plan['ref'])
        proof_id = plan_action_id(commission, 'confirm', decision['ref'])
        assert db.execute('SELECT action,role FROM assertions WHERE id=?', (proposal_id,)).fetchone() == (
            'record_convention', 'coordinator')
        row = db.execute("SELECT action,role,body ->> '$.claim.target' FROM assertions WHERE id=?", (proof_id,))
        assert row.fetchone() == ('confirm', 'owner', proposal_id)
        db.execute('DELETE FROM assertions WHERE id=?', (proof_id,))
    with pytest.raises(ActionRejected, match='PLAN_AUTHORITY|CONFIRMATION_REQUIRED'):
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
        if not (cs.store.root / 'assertions.sqlite3').exists():
            return 0
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
    assert set(actions.values()) == {'record_convention', 'confirm'}
    assert len(actions) == 3
    assert actions[plan_action_id(commission, 'record_convention', previous_plan['ref'])] == 'record_convention'
    assert plan_action_id(commission, 'confirm', previous_decision['ref']) not in actions
    assert not (case / 'assertion-access.sqlite3').exists()


def test_withdrawn_owner_confirmation_cannot_reissue_the_checklist(commission):
    from uuid import NAMESPACE_URL, uuid5
    from report_agent import assertions
    from report_agent.assertion_host import AssertionHost, Grant
    from report_agent.store import encode

    saved = save(commission)
    checkpoint, answer = approve(commission, saved)
    plan, decision = confirmed_records(commission)
    receipt = plan_action_id(commission, 'confirm', decision['ref'])
    subject = plan['ref']['id']
    host = AssertionHost(commission.cs.store.root)
    grant = Grant(str(uuid5(NAMESPACE_URL, 'operator')), 'owner', 'withdraw-approval', 'direct',
                  encode(plan['ref']), {subject}, {receipt}, {'retract'})
    assertions.retract(host.issue_once(grant, 'retract', 'withdraw'), subject=subject,
                       claim=dict(kind='act', effect='retract', target=receipt, reason='Owner withdrew approval'))
    path = commission.cs.store.root / commission_plan._checklist_path(decision['ref'])
    path.unlink()
    with pytest.raises(ActionRejected, match='PLAN_AUTHORITY_WITHDRAWN'):
        commission_plan.reply(commission.ws, checkpoint['issue_id'], answer)
    assert not path.exists()


def test_owner_confirmation_keeps_pinned_input_version(commission):
    from report_agent import plan_inputs

    with commission.cs.store.connect() as db:
        ref = plan_inputs.save_text_profiles(db, {"template": "original"})
    saved = save(commission)
    approve(commission, saved)
    with commission.cs.store.connect() as db:
        revised = plan_inputs.save_text_profiles(db, {"template": "revised"})
    assert revised != ref
    plan, decision = confirmed_records(commission)
    assert plan["plan_input_refs"] == [ref]
    assert commission.cs.read(ref)["payload"] == {"template": "original"}
    assert decision["payload"]["plan_ref"] == saved["plan_ref"]


def test_independent_first_submissions_and_relocated_redo(commission, tmp_path_factory):
    from shutil import copytree
    from report_agent.content_store import ContentStore
    from report_agent.store import Store

    cs = commission.cs
    other = ContentStore(Store(copytree(cs.store.root, tmp_path_factory.mktemp('independent') / 'case')))
    saved = save(commission)
    moved = ContentStore(Store(copytree(cs.store.root, tmp_path_factory.mktemp('relocated') / 'case')))

    def submit(case):
        return commission_plan.save_plan(case, commission.co, 'save-plan', commission.plan)['result']

    independent = submit(other)
    assert independent['plan_ref'] != saved['plan_ref']
    assert set(r['id'] for r in independent['inventory_refs']).isdisjoint(r['id'] for r in saved['inventory_refs'])
    assert submit(moved) == saved
