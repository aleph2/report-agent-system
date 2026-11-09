import pytest

from report_agent import commission_assertions as records
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import Store


@pytest.mark.parametrize('kind', ['plan', 'requirements'])
def test_answer_is_bound_to_exact_checkpoint_and_owner(tmp_path, kind):
    store = Store(tmp_path)
    cs = ContentStore(store)
    coordinator = Actor('content:coordinator', 'coordinator', 'content-task:coordinator')
    owner = Actor('operator', 'operator', 'checkpoint:one')
    with store.connect() as db:
        base = cs._insert(db, coordinator, 'CommissionPlan' if kind == 'plan' else 'CommissionRequirements', {})
        other = cs._insert(db, coordinator, base['type'], {})
        if kind == 'plan':
            answer = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': base})
            wrong = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': other})
        else:
            records_before = records.requirements_results(db)
            answer = cs._insert(db, owner, base['type'], {}, id=base['id'], version=2, previous_ref=base)
            wrong = cs._insert(db, owner, base['type'], {}, id=other['id'], version=2, previous_ref=other)
    field = 'plan_ref' if kind == 'plan' else 'requirements_ref'
    data = {field: base, 'brief_path': 'outputs/brief.md'}
    records.ask_checkpoint(store, coordinator, 'issue', kind, 'issue', data)
    from report_agent.commission_plan import project_checkpoint_issue
    from report_agent.workspace import Workspace
    project_checkpoint_issue(store, 'issue', 'Owner reply required', [])
    with pytest.raises(ActionRejected, match='TYPED_CHECKPOINT_REQUIRES_COMMISSION_REPLY'):
        Workspace(store).decide_issue('issue', 'approve', resolved=True)
    assert records.checkpoint(store, kind, 'issue') == data
    assert records.checkpoint_answer(store, kind, 'issue') is None
    with pytest.raises(ActionForbidden):
        records.answer_checkpoint(store, coordinator, 'issue', kind, 'issue', answer)
    with pytest.raises(ActionRejected):
        records.answer_checkpoint(store, owner, 'issue', kind, 'issue', wrong)
    first = records.answer_checkpoint(store, owner, 'issue', kind, 'issue', answer)
    assert records.answer_checkpoint(store, owner, 'issue', kind, 'issue', answer) == first
    assert records.checkpoint_answer(store, kind, 'issue') == answer
    if kind == 'requirements':
        assert records.requirements_results(store) == records_before | {(base['id'], 2)}


def test_native_interpretation_requires_committed_coordinator_work(tmp_path):
    store = Store(tmp_path)
    cs = ContentStore(store)
    coordinator = Actor('content:coordinator', 'coordinator', 'content-task:coordinator')
    host = Actor('host', 'host', 'prepare')
    with store.connect() as db:
        prepared = cs._insert(db, host, 'CommissionRequirements', {})
        interpreted = cs._insert(db, coordinator, 'CommissionRequirements', {}, id=prepared['id'],
                                 version=2, previous_ref=prepared)
    assert not records.requirements_results(store)
    with pytest.raises(ActionRejected):
        records.record_interpretation(store, coordinator, 'interpret', prepared)
    alien_task = Actor(coordinator.id, coordinator.role, 'different-task')
    with pytest.raises(ActionRejected):
        records.record_interpretation(store, alien_task, 'new', interpreted)
    records.record_interpretation(store, coordinator, 'interpret', interpreted)
    assert records.requirements_results(store) == {(prepared['id'], 2)}


def test_clean_import_carries_only_selected_authenticated_chain(tmp_path):
    source, copied = tmp_path / 'original', tmp_path / 'import'
    store = Store(source)
    cs = ContentStore(store)
    coordinator = Actor('content:coordinator', 'coordinator', 'coord')
    owner = Actor('operator', 'operator', 'operator:one')
    with store.connect() as db:
        plan = cs._insert(db, coordinator, 'CommissionPlan', {})
        answer = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': plan})
        other = cs._insert(db, coordinator, 'CommissionPlan', {})
        alternatives = cs._insert(db, owner, 'CommissionDecision', {'plan_ref': other})
        req = cs._insert(db, coordinator, 'CommissionRequirements', {})
    records.record_interpretation(store, coordinator, 'requirements', req)
    for issue, version, result in [('accepted', plan, answer), ('other', other, alternatives)]:
        data = {'plan_ref': version}
        records.ask_checkpoint(store, coordinator, issue, 'plan', issue, data)
        records.answer_checkpoint(store, owner, issue, 'plan', issue, result)
    records.copy_planning_evidence(source, copied, [cs.read(r) for r in (plan, answer, req)], plan=plan, decision=answer)
    assert records.checkpoint_answer(copied, 'plan', 'accepted') == answer
    assert records.requirements_results(copied) == {(req['id'], req['version'])}
    assert records.checkpoint(copied, 'plan', 'other') is None
    assert not (copied / 'assertion-access.sqlite3').exists()


def test_withdrawn_answer_is_never_revived_by_retry_or_clean_import(tmp_path):
    from uuid import NAMESPACE_URL, uuid5
    from report_agent import assertions
    from report_agent.assertion_host import AssertionHost, Grant
    from report_agent.store import encode

    source, destination = tmp_path / 'source', tmp_path / 'copy'
    store = Store(source)
    cs = ContentStore(store)
    coordinator = Actor('content:coordinator', 'coordinator', 'coord')
    owner = Actor('operator', 'operator', 'operator')
    with store.connect() as db:
        base = cs._insert(db, coordinator, 'CommissionRequirements', {})
        result = cs._insert(db, owner, base['type'], {}, id=base['id'], version=2, previous_ref=base)
    ask = records.ask_checkpoint(store, coordinator, 'issue', 'requirements', 'issue', {'requirements_ref': base})
    saved = records.answer_checkpoint(store, owner, 'issue', 'requirements', 'issue', result)
    host = AssertionHost(source)
    grant = Grant(str(uuid5(NAMESPACE_URL, owner.id)), 'owner', 'withdraw', 'one', encode(base),
                  frozenset([ask['subject']]), frozenset([saved['id']]), frozenset(['retract']))
    assertions.retract(host.issue_once(grant, 'retract', 'withdraw'), subject=ask['subject'],
                       claim={'kind': 'act', 'effect': 'retract', 'target': saved['id'], 'reason': 'Correct the answer'})
    assert records.checkpoint_answer(store, 'requirements', 'issue') is None
    assert records.answer_checkpoint(store, owner, 'issue', 'requirements', 'issue', result) == saved
    assert not records.requirements_results(store)
    records.copy_planning_evidence(source, destination, [cs.read(base), cs.read(result)], plan=None, decision=None)
    assert not records.requirements_results(destination)
    assert records.checkpoint_answer(destination, 'requirements', 'issue') is None
