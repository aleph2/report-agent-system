"""Case data holds immutable plan versions; signed proposal and owner acts select them."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from . import assertions, legacy_state as legacy
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import encode


def _directory(storage):
    if isinstance(storage, sqlite3.Connection):
        path = storage.execute("PRAGMA database_list").fetchone()[2]
        return Path(path).parent if path else None
    return Path(storage if isinstance(storage, (str, Path)) else storage.root)


def historical_refs(storage):
    """Read the retained pre-M4 pins, including the pins of an isolated historical import."""
    if not isinstance(storage, sqlite3.Connection):
        path = Path(storage if isinstance(storage, (str, Path)) else storage.root) / 'state.db'
        if not path.is_file():
            return None, None
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            return historical_refs(db)
    return (imported_historical_ref(storage, 'CommissionPlan') or legacy.get_commission_plan(storage),
            imported_historical_ref(storage, 'CommissionDecision') or legacy.get_commission_confirmation(storage))


def imported_historical_ref(db, kind):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='imported_historical_plan'").fetchone():
        row = db.execute("SELECT ref FROM imported_historical_plan WHERE kind=?", (kind,)).fetchone()
        if row:
            return json.loads(row[0])
    return None


def install_historical_refs(db, plan, decision, *, requirements=None):
    db.execute("CREATE TABLE imported_historical_plan(kind TEXT PRIMARY KEY, ref TEXT NOT NULL)")
    db.executemany("INSERT INTO imported_historical_plan VALUES (?,?)",
                   [(ref['type'], encode(ref)) for ref in (plan, decision, requirements) if ref])


def _actions(storage, *, live=False):
    root = _directory(storage)
    return Commission.plan_actions(root, live=live) if root else []


def _entries(actions):
    plans, decisions = [], []
    for action, body, status in actions:
        proposal = action == 'record_convention'
        text = body['claim']['rule' if proposal else 'reason']
        try:
            ref = json.loads(text)
        except ValueError:
            # A person's independent withdrawal can give an ordinary textual reason.
            continue
        if isinstance(ref, dict) and ref.get('type') == ('CommissionPlan' if proposal else 'CommissionDecision'):
            (plans if proposal else decisions).append((ref, body, status))
    return plans, decisions


def native_plan_ref(storage, default=None):
    plans, _ = _entries(_actions(storage))
    return plans[-1][0] if plans else default


def has_proposal(storage, plan):
    plans, _ = _entries(_actions(storage))
    return any(ref == plan for ref, _, _ in plans)


def plan_ref(storage, default=None):
    return native_plan_ref(storage) or historical_refs(storage)[0] or default


def decision_ref(storage, default=None):
    plans, decisions = _entries(_actions(storage))
    if plans:
        return decisions[-1][0] if decisions else default
    return historical_refs(storage)[1] or default


def stable_id(actor, call, item):
    return str(uuid5(NAMESPACE_URL, encode([actor.id, actor.task_id, call, item])))


def _context(host, actor, role, call, plan, action, target=None):
    grant = Grant(str(uuid5(NAMESPACE_URL, actor.id)), role, actor.task_id, 'plan-action:' + call,
                  encode(plan), frozenset([plan['id']]), frozenset([target] if target else []), frozenset([action]))
    return host.issue_once(grant, action, call)


def propose(store, actor, operation_id, plan):
    if actor.role != 'coordinator' or actor.id != 'content:coordinator':
        raise ActionForbidden('COMMISSION_PROPOSAL_COORDINATOR_REQUIRED')
    with store.connect() as db:
        record = ContentStore._read(db, plan)
    if plan['type'] != 'CommissionPlan' or record['owner_id'] != actor.id:
        raise ActionRejected('COMMISSION_PROPOSAL_VERSION_REQUIRED')
    host = AssertionHost(store.root)
    ctx = _context(host, actor, 'coordinator', operation_id, plan, 'record_convention')
    return assertions.record_convention(ctx, subject=plan['id'],
        claim=dict(kind='convention', scope='commission_plan', rule=encode(plan)))


def decide(store, owner, operation_id, plan, decision, approved):
    if owner.role != 'operator' or owner.id != 'operator':
        raise ActionForbidden('COMMISSION_CHECKPOINT_OWNER_REQUIRED')
    with store.connect() as db:
        record = ContentStore._read(db, decision)
    if (decision['type'] != 'CommissionDecision' or record['owner_id'] != owner.id
            or record['payload']['plan_ref'] != plan or record['payload']['approved'] is not approved):
        raise ActionRejected('COMMISSION_CHECKPOINT_DECISION_MISMATCH')
    plans, _ = _entries(_actions(store))
    proposal = next((body for ref, body, _ in reversed(plans) if ref == plan), None)
    if proposal is None:
        raise ActionRejected('COMMISSION_PLAN_AUTHORITY_NEW_PROPOSAL_REQUIRED')
    action = 'confirm' if approved else 'retract'
    host = AssertionHost(store.root)
    target = proposal['id']
    ctx = _context(host, owner, 'owner', operation_id, plan, action, target)
    try:
        return host.commission.decide_current(ctx, subject=plan['id'],
            claim=dict(kind='act', effect=action, target=target, reason=encode(decision)))
    except ValueError as exc:
        raise ActionRejected(str(exc)) from exc


def _approved(plans, decisions, plan, decision):
    if not plans or not decisions:
        raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_REQUIRED')
    plan = plans[-1][0] if plan is None else plan
    decision = decisions[-1][0] if decision is None else decision
    proposal = next((r for r in reversed(plans) if r[0] == plan), None)
    answer = next((r for r in reversed(decisions) if r[0] == decision), None)
    if not proposal or not answer or (answer[1]['claim']['effect'] != 'confirm'
            or answer[1]['claim']['target'] != proposal[1]['id']):
        raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_STALE')
    if (proposal[2]['status'] != 'confirmed' or any(not state['active'] or state['challenged'] or state['stale']
                                                    for state in (proposal[2], answer[2]))):
        raise ActionRejected('COMMISSION_PLAN_AUTHORITY_WITHDRAWN')
    return plan, decision


def confirmed_refs(storage, *, plan=None, decision=None):
    plans, decisions = _entries(_actions(storage, live=True))
    if plans:
        return _approved(plans, decisions, plan, decision)
    old_plan, old_decision = historical_refs(storage)
    if old_plan and old_decision and plan in (None, old_plan) and decision in (None, old_decision):
        if not isinstance(storage, sqlite3.Connection):
            path = Path(storage if isinstance(storage, (str, Path)) else storage.root) / 'state.db'
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                db.row_factory = sqlite3.Row
                record = ContentStore._read(db, old_decision)
        else:
            record = ContentStore._read(storage, old_decision)
        if record['owner_id'] == 'operator' and record['payload'].get('plan_ref') == old_plan and record['payload'].get('approved') is True:
            return old_plan, old_decision
    raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_REQUIRED')


def copy_plan_evidence(source, output, records, *, plan, decision):
    wanted = [r['ref'] for r in records]

    def select(snapshot):
        proposals, decisions = _entries(snapshot)
        if _approved(proposals, decisions, None, None) != (plan, decision) or plan not in wanted or decision not in wanted:
            raise ActionRejected('COMMISSION_PLAN_AUTHORITY_IMPORT_MISMATCH')
        return [body for ref, body, _ in proposals if ref in wanted] + [
            body for ref, body, _ in decisions if ref == decision]

    Commission(output).import_plan_actions(source, select)
