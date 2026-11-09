import sqlite3
from uuid import NAMESPACE_URL, uuid5

import pytest

from report_agent import assertions, plan_authority
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionRejected
from report_agent.store import Store, encode


def test_preparation_proposal_and_owner_action_are_separate(commission_case):
    store, cs, coordinator, owner = commission_case
    with store.connect() as db:
        plan = cs._insert(db, coordinator, 'CommissionPlan', {'sections': []})
    assert plan_authority.plan_ref(store) is None
    first = plan_authority.propose(store, coordinator, 'submit', plan)
    assert plan_authority.propose(store, coordinator, 'submit', plan) == first
    assert plan_authority.plan_ref(store) == plan
    assert plan_authority.decision_ref(store) is None
    with store.connect() as db:
        decision = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': plan, 'approved': True})
    with pytest.raises(ActionRejected):
        plan_authority.confirmed_refs(store)
    approved = plan_authority.decide(store, owner, 'owner-reply', plan, decision, True)
    assert plan_authority.confirmed_refs(store) == (plan, decision)
    assert plan_authority.decide(store, owner, 'owner-reply', plan, decision, True) == approved
    assert not any('plan_authority' in cs.read(ref) for ref in (plan, decision))
    with sqlite3.connect(store.root / 'assertions.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM assertions').fetchone()[0] == 2


@pytest.fixture
def commission_case(tmp_path):
    store = Store(tmp_path)
    return store, ContentStore(store), Actor('content:coordinator', 'coordinator', 'content-task:coordinator'), Actor(
        'operator', 'operator', 'commission-checkpoint:one')


def test_late_proposal_reads_by_version_and_rejected_checkpoint_cannot_approve(commission_case):
    store, cs, coordinator, owner = commission_case
    with store.connect() as db:
        older = cs._insert(db, coordinator, 'CommissionPlan', {})
        newer = cs._insert(db, coordinator, 'CommissionPlan', {}, id=older['id'], version=2, previous_ref=older)
        stale = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': older, 'approved': True})
        rejected = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': newer, 'approved': False})
    plan_authority.propose(store, coordinator, 'newer', newer)
    plan_authority.propose(store, coordinator, 'older', older)
    assert plan_authority.plan_ref(store) == newer
    with pytest.raises(ActionRejected, match='STALE'):
        plan_authority.decide(store, owner, 'late-owner-reply', older, stale, True)
    plan_authority.decide(store, owner, 'revise', newer, rejected, False)
    assert plan_authority.decision_ref(store) == rejected
    with pytest.raises(ActionRejected):
        plan_authority.confirmed_refs(store)


def test_owner_withdrawal_survives_exact_redo_and_blocks_copy(commission_case, tmp_path):
    store, cs, coordinator, owner = commission_case
    with store.connect() as db:
        plan = cs._insert(db, coordinator, 'CommissionPlan', {})
        decision = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': plan, 'approved': True})
    proposal = plan_authority.propose(store, coordinator, 'submit', plan)
    approval = plan_authority.decide(store, owner, 'owner-reply', plan, decision, True)
    assert proposal['claim']['rule'] == encode(plan) and approval['claim']['reason'] == encode(decision)
    assert approval['claim']['target'] == proposal['id']
    target = tmp_path / 'copy'
    plan_authority.copy_plan_evidence(store.root, target, [cs.read(plan), cs.read(decision)], plan=plan, decision=decision)
    assert plan_authority.confirmed_refs(target) == (plan, decision)
    host = AssertionHost(store.root)
    grant = Grant(str(uuid5(NAMESPACE_URL, 'operator')), 'owner', 'withdraw', 'direct', encode(plan),
                  frozenset([plan['id']]), frozenset([approval['id']]), frozenset(['retract']))
    assertions.retract(host.issue_once(grant, 'retract', 'withdraw'), subject=plan['id'],
                       claim=dict(kind='act', effect='retract', target=approval['id'], reason='Withdraw approval'))
    assert plan_authority.decide(store, owner, 'owner-reply', plan, decision, True) == approval
    with pytest.raises(ActionRejected, match='WITHDRAWN'):
        plan_authority.confirmed_refs(store, plan=plan, decision=decision)
    with pytest.raises(ActionRejected, match='WITHDRAWN'):
        plan_authority.copy_plan_evidence(store.root, tmp_path/'refused', [cs.read(plan), cs.read(decision)],
                                          plan=plan, decision=decision)


def test_new_proposal_requires_its_own_approval_in_a_pre_m4_case(commission_case):
    store, cs, coordinator, owner = commission_case
    with store.connect() as db:
        old = cs._insert(db, coordinator, 'CommissionPlan', {})
        old_decision = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': old, 'approved': True})
        plan_authority.install_historical_refs(db, old, old_decision)
        new = cs._insert(db, coordinator, 'CommissionPlan', {}, id=old['id'], version=2, previous_ref=old)
    assert plan_authority.confirmed_refs(store.root) == (old, old_decision)
    assert plan_authority.propose(store, coordinator, 'replacement', new)
    assert plan_authority.plan_ref(store) == new
    with pytest.raises(ActionRejected):
        plan_authority.confirmed_refs(store)
