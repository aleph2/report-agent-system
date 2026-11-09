"""Versioned planning decisions and their native assertion proofs."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from . import legacy_state as legacy
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import ContentStore
from .errors import ActionRejected
from .store import digest, encode


def _has(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()


def _latest(storage, kind, default):
    if not isinstance(storage, sqlite3.Connection):
        with storage.connect() as db:
            return _latest(db, kind, default)
    if _has(storage, 'content_versions'):
        row = storage.execute("""SELECT id,version FROM content_versions WHERE type=?
            AND json_type(data,'$.plan_authority') IS NOT NULL ORDER BY version DESC, rowid DESC LIMIT 1""", (kind,)).fetchone()
        if row:
            return dict(type=kind, id=row[0], version=row[1])
    if _has(storage, 'imported_historical_plan'):
        row = storage.execute("SELECT ref FROM imported_historical_plan WHERE kind=?", (kind,)).fetchone()
        if row:
            return json.loads(row[0])
    read = legacy.get_commission_plan if kind == 'CommissionPlan' else legacy.get_commission_confirmation
    return read(storage, default)


def plan_ref(storage, default=None):
    return _latest(storage, 'CommissionPlan', default)


def decision_ref(storage, default=None):
    return _latest(storage, 'CommissionDecision', default)


def install_historical_refs(db, plan, decision):
    """Trusted import of the two verified pre-M4 pins into an empty probe case."""
    db.execute("CREATE TABLE imported_historical_plan(kind TEXT PRIMARY KEY, ref TEXT NOT NULL)")
    db.executemany("INSERT INTO imported_historical_plan VALUES (?,?)",
                   [(ref['type'], encode(ref)) for ref in (plan, decision)])


def stable_id(actor, call, item):
    return str(uuid5(NAMESPACE_URL, encode([actor.id, actor.task_id, call, item])))


def _claim(ref, payload, inputs, proposal_id):
    if ref['type'] == 'CommissionPlan':
        return 'record_convention', dict(kind='convention', scope='commission_plan', rule=digest([ref, payload, inputs]))
    effect = 'confirm' if payload['approved'] else 'retract'
    return effect, dict(kind='act', effect=effect, target=proposal_id, reason=digest([ref, payload]))


def publish(cs, db, actor, call, ref, payload, *, inputs=(), proposal_id=None):
    bindings = [{'ref': r, 'digest': digest(ContentStore._read(db, r)['payload'])} for r in inputs]
    action, claim = _claim(ref, payload, bindings, proposal_id)
    plan = ref if action == 'record_convention' else payload['plan_ref']
    role = 'coordinator' if action == 'record_convention' else 'owner'
    host = AssertionHost(cs.store.root)
    grant = Grant(str(uuid5(NAMESPACE_URL, actor.id)), role, actor.task_id, 'plan-action:' + call,
                  digest(plan), frozenset([plan['id']]), frozenset([proposal_id] if proposal_id else []),
                  frozenset([action]))
    ctx = host.issue_once(grant, action, call)
    saved = host.commission.publish_in_case(db, ctx, subject=plan['id'], claim=claim)
    return {'assertion_id': saved['id'], 'operation_id': saved['operation_id'],
            **({'inputs': bindings} if bindings else {})}


def recover_publication(cs, db, actor, call, record, plan):
    """An exact business replay repairs the native side of an interrupted WAL commit."""
    link = record.get('plan_authority')
    if not link:
        return
    committed = Commission.committed_projection(cs.store.root, link['operation_id'], link['assertion_id'])
    if committed:
        _verify(record, plan, committed)
        return
    inputs = [item['ref'] for item in link.get('inputs', ())]
    restored = publish(cs, db, actor, call, record['ref'], record['payload'], inputs=inputs,
                       proposal_id=None if record['ref']['type'] == 'CommissionPlan' else plan['plan_authority']['assertion_id'])
    if restored != link or not db.execute(
            "SELECT 1 FROM plan_assertions.assertions WHERE id=?", (link['assertion_id'],)).fetchone():
        raise ActionRejected('COMMISSION_PLAN_AUTHORITY_RECOVERY_MISMATCH')


def _verify(record, plan, committed, *, approved=False):
    link = record.get('plan_authority')
    if link is None:
        if plan.get('plan_authority'):
            raise ActionRejected('COMMISSION_PLAN_AUTHORITY_MISSING')
        return
    target = plan.get('plan_authority', {}).get('assertion_id')
    ref = record['ref']
    action, claim = _claim(ref, record['payload'], link.get('inputs', ()), target)
    if committed:
        binding, assertion, state, _ = committed
        role = 'coordinator' if action == 'record_convention' else 'owner'
        author = 'content:coordinator' if role == 'coordinator' else 'operator'
        if (state['action'] == action and binding['role'] == role and record['owner_id'] == author
                and binding['actor'] == str(uuid5(NAMESPACE_URL, author)) and binding['task'] == record['task_id']
                and binding['plan'] == digest(plan['ref']) and assertion['subject'] == plan['ref']['id']
                and all(assertion['claim'].get(k) == v for k, v in claim.items())
                and (not approved or state['active'] and not state['stale'] and not state['challenged']
                     and (role != 'coordinator' or state['status'] == 'confirmed'))):
            return
    raise ActionRejected('COMMISSION_PLAN_AUTHORITY_INVALID')


def verify(case, plan, decision=None):
    inputs = plan.get('plan_authority', {}).get('inputs', ())
    if inputs:
        with closing(sqlite3.connect((Path(case) / 'state.db').as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            for item in inputs:
                if digest(ContentStore._read(db, item['ref'])['payload']) != item['digest']:
                    raise ActionRejected('COMMISSION_PLAN_AUTHORITY_INPUT_MISMATCH')
    approved = bool(decision and decision['payload']['approved'])
    records = [plan, decision] if decision else [plan]
    pins = [(link['operation_id'], link['assertion_id']) for r in records if (link := r.get('plan_authority'))]
    proofs = Commission.committed_projections(case, pins)
    for record in records:
        _verify(record, plan, proofs.get(record.get('plan_authority', {}).get('assertion_id')), approved=approved)


def copy_plan_evidence(source, output, records):
    """Copy only the pinned plan actions in an approved business closure to its clean case."""
    records = list(records)
    links = [r['plan_authority'] for r in records if 'plan_authority' in r]
    if not links:
        return
    with closing(sqlite3.connect((Path(source) / 'state.db').as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        plan = ContentStore._read(db, plan_ref(db))
        decision = ContentStore._read(db, decision_ref(db))
        if (decision['payload']['plan_ref'] != plan['ref'] or not decision['payload']['approved']
                or plan not in records or decision not in records):
            raise ActionRejected('COMMISSION_PLAN_AUTHORITY_IMPORT_MISMATCH')
        verify(source, plan, decision)
    Commission(output).import_plan_actions(source, links)
