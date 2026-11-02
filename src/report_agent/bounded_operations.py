"""Persistent admission facts for bounded calls, using the existing project store.

Callers own material/actor identity and policy. No retries, model decisions,
budget ledger or business-artifact authority are added here.
"""
import json
from .store import encode
from .errors import external_outcome_pending

UNRESOLVED_STATES = {'reserved', 'unknown'}


def reserve_once(store, key, record, *, check_new=None, new_parent=None):
    """Atomically inspect or reserve one operation; return an existing receipt."""
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        if row:
            prior = json.loads(row[0])
            if prior['state'] == 'not_dispatched' and new_parent is not None:
                parent_key, expected = new_parent
                parent_row = db.execute('SELECT value FROM state WHERE key=?', (parent_key,)).fetchone()
                parent = json.loads(parent_row[0]) if parent_row else None
                if (parent is None or parent.get('state') != 'reserved'
                        or parent_key in prior.get('linked_reservation_keys', [key])
                        or any(parent.get(k) != v for k, v in expected.items())):
                    return prior
                # A distinct, freshly reserved caller operation deliberately
                # selected this work. The old caller still returns its failure.
                db.execute('UPDATE state SET value=? WHERE key=?', (encode(record), key))
                db.execute('INSERT INTO events(kind,data) VALUES (?,?)', (
                    'bounded_operation_readmitted', encode({'key': key, 'previous': prior,
                        'new_parent_key': parent_key, 'new_parent_identity': expected})))
                return None
            return prior
        if check_new is not None:
            check_new(db)
        db.execute('INSERT INTO state VALUES (?,?)', (key, encode(record)))
    return None


def record_not_dispatched(store, reservations, proof, *, result=None):
    """CAS all linked operation reservations after a proven local refusal.

    Host reconciliation and live calls share this transition. No rearming,
    budget release, checkpoint change or cached successful analysis is created.
    """
    if (not reservations or proof.get('provider_outcome') != 'not_dispatched'
            or proof.get('admitted_http_attempts') != 0
            or type(proof.get('refused_before_send')) is not int
            or proof['refused_before_send'] < 1):
        raise ValueError('KNOWN_NOT_DISPATCHED_PROOF_REQUIRED')
    if len({key for key, _ in reservations}) != len(reservations):
        raise ValueError('DUPLICATE_OPERATION_RESERVATION')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = []
        for key, expected in reservations:
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            value = json.loads(row[0]) if row else None
            if value is None or any(value.get(k) != v for k, v in expected.items()):
                raise ValueError('NOT_DISPATCHED_RESERVATION_CAS_FAILED')
            if value['state'] == 'not_dispatched' and value.get('admission_proof') == proof:
                previous.append((key, value))
                continue
            if value['state'] != 'reserved':
                raise ValueError('NOT_DISPATCHED_RESERVATION_CAS_FAILED')
            previous.append((key, value))
        if all(value['state'] == 'not_dispatched' for _, value in previous):
            return False
        for key, value in previous:
            updated = {**value, 'state': 'not_dispatched', 'raw_response_received': False,
                       'provider_outcome': 'not_dispatched', 'admission_proof': proof,
                       'linked_reservation_keys': [item[0] for item in reservations]}
            if result is not None:
                updated['result'] = result
            db.execute('UPDATE state SET value=? WHERE key=?', (encode(updated), key))
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', (
            'bounded_operation_not_dispatched', encode({'previous': dict(previous), 'proof': proof})))
    return True


def record_outcome(store, key, state, *, result=None, cache_operation=None):
    """Record a received result and optional successful cache in one transaction.

    A reservation survives cancellation or persistence failure as unresolved.
    Only an actually received result can leave that state; missing usage is not
    invented, and transport budget settlement remains a separate responsibility.
    """
    if state not in {'unknown', 'received_invalid', 'completed'}:
        raise ValueError('INVALID_BOUNDED_OPERATION_OUTCOME')
    if state != 'unknown' and result is None:
        raise ValueError('RECEIVED_RESULT_REQUIRED')
    if cache_operation is not None and state != 'completed':
        raise ValueError('ONLY_COMPLETED_RESULT_IS_REUSABLE_SUCCESS')
    with external_outcome_pending(key), store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('BOUNDED_OPERATION_NOT_RESERVED')
        value = json.loads(row[0])
        value.update(state=state, raw_response_received=state != 'unknown')
        if result is not None:
            value['result'] = result
        db.execute('UPDATE state SET value=? WHERE key=?', (encode(value), key))
        if cache_operation is not None:
            db.execute('INSERT OR REPLACE INTO analyses VALUES (?,?)',
                       (cache_operation, encode(result)))

