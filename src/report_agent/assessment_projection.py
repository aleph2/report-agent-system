"""Pinned report rendering records for calculator results and pre-migration cases."""
import json
from pathlib import Path

from . import legacy_state as legacy
from .assertions.launch import Commission
from .content_store import ContentStore
from .errors import ActionRejected
from .store import digest, encode


def record_assessment_projection(db, plan_ref, object_id, receipt, *, select):
    # The calculator transaction publishes all rendering refs together. Old snapshots
    # still address their original row after a later calculation is selected.
    db.execute("""CREATE TABLE IF NOT EXISTS assessment_projections(
        ref TEXT PRIMARY KEY NOT NULL, plan TEXT NOT NULL, subject TEXT NOT NULL,
        selected INTEGER NOT NULL, native INTEGER NOT NULL, receipt TEXT NOT NULL)""")
    native = 'derived_assertion_id' in receipt
    rendering = {k: v for k, v in receipt.items() if k != 'result'} if native else receipt
    db.execute("""INSERT INTO assessment_projections(ref, plan, subject, selected, native, receipt)
        VALUES(?,?,?,?,?,?)""", (encode(receipt['assessment_ref']), digest(plan_ref), object_id,
        select and native, native, encode(rendering)))


def _present(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assessment_projections'").fetchone()


def _native_started(db, plan_ref, subject):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assessment_producers'").fetchone():
        if db.execute("SELECT 1 FROM assessment_producers WHERE plan_object=? AND native=1",
                      (digest([plan_ref, subject]),)).fetchone():
            return True
    case = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    return Commission.preexisting_producer(case, digest(plan_ref), subject) is not None


def selected_assessment(db, plan_ref, object_id):
    if _present(db):
        row = db.execute("""SELECT ref FROM assessment_projections
            WHERE plan=? AND subject=? AND selected=1 AND native=1 ORDER BY rowid DESC LIMIT 1""",
            (digest(plan_ref), object_id)).fetchone()
        if row:
            ref = json.loads(row[0])
            payload = ContentStore._read(db, ref)['payload']
            if (not payload.get('derived_assertion_id') or not payload.get('derive_operation_id')
                    or payload.get('commission_plan_ref') != plan_ref or payload.get('object_id') != object_id):
                raise ActionRejected('ASSESSMENT_DERIVATION_PROJECTION_MISMATCH')
            return ref
    historic = legacy.get_g6_assessment(db, digest([plan_ref, object_id]))
    return historic if historic and not _native_started(db, plan_ref, object_id) else None


def assessment_receipt(db, assessment_ref):
    row = None
    if _present(db):
        row = db.execute("SELECT plan,subject,native,receipt FROM assessment_projections WHERE ref=?",
                         (encode(assessment_ref),)).fetchone()
    if row is None:
        historic = legacy.get_assessment_receipt(db, digest(assessment_ref))
        if not historic:
            return None
        if not historic.get('result'):
            return {**historic, 'derivation_status': 'unverified'}
        payload = ContentStore._read(db, assessment_ref)['payload']
        if (historic.get('assessment_ref') != assessment_ref or historic['result'] != payload.get('result')
                or 'derived_assertion_id' in payload or 'derive_operation_id' in payload):
            raise ActionRejected('ASSESSMENT_DERIVATION_PROJECTION_MISMATCH')
        if _native_started(db, payload['commission_plan_ref'], payload['object_id']):
            return {**historic, 'derivation_status': 'superseded_by_native'}
        if (not historic['result'].get('status') and historic['result'].get('adopted')
                and all(historic.get(k) for k in ('evidence_ref', 'level_ref', 'evaluation_ref'))):
            return {**historic, 'derivation_status': 'historical_scored'}
        return {**historic, 'derivation_status': 'unverified'}
    plan, subject, native, raw = row
    receipt = json.loads(raw)
    if receipt.get('assessment_ref') != assessment_ref:
        raise ActionRejected('ASSESSMENT_PROJECTION_REF_MISMATCH')
    payload = ContentStore._read(db, assessment_ref)['payload']
    has_native_pin = 'derived_assertion_id' in payload or 'derive_operation_id' in payload
    if (has_native_pin != bool(native) or has_native_pin != ('derived_assertion_id' in receipt)
            or has_native_pin != ('derive_operation_id' in receipt)
            or payload.get('object_id') != subject or digest(payload.get('commission_plan_ref')) != plan):
        raise ActionRejected('ASSESSMENT_DERIVATION_PROJECTION_MISMATCH')
    if not has_native_pin:
        if receipt.get('result') != payload.get('result'):
            raise ActionRejected('ASSESSMENT_DERIVATION_PROJECTION_MISMATCH')
        status = payload['result'].get('status')
        if _native_started(db, payload['commission_plan_ref'], subject):
            status = 'superseded_by_native'
        elif status == 'legacy_g3_scored':
            from types import SimpleNamespace
            from .commission_plan import _state
            from .section_writing import enabled
            if enabled(SimpleNamespace(manifest=_state(db, 'manifest', {}))):
                status = 'legacy_draft'
        receipt['derivation_status'] = status if status in ('legacy_g3_scored', 'legacy_draft', 'superseded_by_native') else 'unverified'
        return receipt
    case = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    committed = Commission.committed_projection(case, receipt['derive_operation_id'], receipt['derived_assertion_id'])
    if not committed:
        raise ActionRejected('ASSESSMENT_DERIVATION_MISSING')
    binding, assertion, state, inputs = committed
    claim = assertion['claim']
    result = payload['result']
    if (payload.get('derived_assertion_id') != assertion['id']
            or payload.get('derive_operation_id') != assertion['operation_id']
            or payload.get('object_id') != subject or digest(payload.get('commission_plan_ref')) != plan
            or 'result' in receipt or binding['role'] != 'calculator'
            or binding['plan'] != plan or assertion['subject'] != subject or claim['kind'] != 'derived'):
        raise ActionRejected('ASSESSMENT_DERIVATION_PROJECTION_MISMATCH')
    status = claim['assessment']['status']
    if state['stale']:
        status = 'stale'
    elif not state['active'] or state['challenged']:
        status = state['status']
    elif status == 'scored' and any(i.get('status') not in ('confirmed', 'endorsed') for i in inputs):
        status = 'pending_review'
    receipt.update(result=result, derivation_status=status)
    return receipt


def score_blocker(receipt):
    """Explain why a pinned result cannot produce an unqualified engineering score."""
    status = receipt.get('derivation_status')
    if status in ('scored', 'legacy_g3_scored', 'historical_scored'):
        return None
    return status or 'unverified'


def draft_blocker(receipt):
    """A verified native draft may disclose gaps; it never becomes a reviewed score."""
    if receipt.get('derived_assertion_id') and receipt.get('derivation_status') in ('unscored', 'pending_review'):
        return None
    return score_blocker(receipt)
