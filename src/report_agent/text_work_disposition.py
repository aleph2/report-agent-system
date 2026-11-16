"""Host-only, one-request exception for evidenced distinct work after uncertainty.

Not registered as an agent tool, not a semantic classifier or retry mechanism.
The host evaluates relevance and existing user authority. This record grants
admission only; it cannot change owners, content versions or unknown spending.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .errors import ActionRejected
from .store import digest, encode


def conflict_bindings(conflicts):
    return sorted(({'operation_id':c['original_operation_id'],
                    'request_hash':c['original_request_hash'],
                    'raw_operation':c['raw_operation']} for c in conflicts),
                  key=lambda c:c['operation_id'])


def disposition_key(actor_id, operation_id, request_hash):
    return 'text_work_disposition:'+digest([actor_id, operation_id, request_hash])


def authorize_distinct_work(workspace, actor, operation_id, request_hash,
                            material_identity, conflicts, *, rationale,
                            evidence_path, evidence_sha256, authorization_basis):
    """Host supplies an inspected exact blocked request, never a blanket release."""
    if (not operation_id.strip() or not rationale.strip() or not authorization_basis.strip()
            or not conflicts or any(not c['original_input_verified'] for c in conflicts)):
        raise ActionRejected('TEXT_WORK_DISPOSITION_REQUIRES_VERIFIED_BASIS')
    if any(c['same_material_established'] for c in conflicts):
        raise ActionRejected('TEXT_WORK_DISPOSITION_UNCHANGED_MATERIAL')
    for value in (request_hash, material_identity, evidence_sha256):
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ActionRejected('TEXT_WORK_DISPOSITION_INVALID_DIGEST')
    evidence_path = Path(evidence_path).resolve(strict=True)
    if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != evidence_sha256:
        raise ActionRejected('TEXT_WORK_DISPOSITION_EVIDENCE_CHANGED')
    bindings = conflict_bindings(conflicts)
    key = disposition_key(actor.id, operation_id, request_hash)
    with workspace.store.run_lock(), workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for binding in bindings:
            row = db.execute('SELECT value FROM state WHERE key=?',
                ('text_work:'+actor.id+':'+binding['operation_id'],)).fetchone()
            prior = json.loads(row[0]) if row else None
            if (not prior or prior['request_hash'] != binding['request_hash']
                    or prior['state'] in {'completed','known_failed'}):
                raise ActionRejected('TEXT_WORK_DISPOSITION_UNKNOWN_BINDING_CHANGED')
        if db.execute('SELECT 1 FROM state WHERE key=?', (key,)).fetchone():
            raise ActionRejected('TEXT_WORK_DISPOSITION_ALREADY_REGISTERED')
        value = {'state':'authorized', 'actor':actor.__dict__, 'operation_id':operation_id,
            'request_hash':request_hash, 'material_identity':material_identity,
            'unresolved_attempts':bindings, 'rationale':rationale,
            'evidence_path':str(evidence_path), 'evidence_sha256':evidence_sha256,
            'authorization_basis':authorization_basis,
            'registered_at':datetime.now(timezone.utc).isoformat()}
        db.execute('INSERT INTO state VALUES (?,?)', (key, encode(value)))
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)',
                   ('text_work_distinct_disposition_registered', encode(value)))
    return key


def matching_disposition(db, actor, operation_id, request_hash, material_identity, conflicts):
    """Read-only match; reservation still rechecks and consumes transactionally."""
    key = disposition_key(actor.id, operation_id, request_hash)
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    if not row:
        return None
    value = json.loads(row[0])
    if (value['state'] != 'authorized' or value['actor'] != actor.__dict__
            or value['operation_id'] != operation_id or value['request_hash'] != request_hash
            or value['material_identity'] != material_identity
            or value['unresolved_attempts'] != conflict_bindings(conflicts)
            or any(not c['original_input_verified'] or c['same_material_established'] for c in conflicts)):
        return None
    path = Path(value['evidence_path'])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != value['evidence_sha256']:
        return None
    return value


def consume_disposition(db, actor, operation_id, request_hash, material_identity, conflicts):
    """Called inside the same transaction as the new production reservation."""
    value = matching_disposition(db, actor, operation_id, request_hash, material_identity, conflicts)
    if value is None:
        return False
    key = disposition_key(actor.id, operation_id, request_hash)
    value.update(state='consumed', consumed_at=datetime.now(timezone.utc).isoformat())
    db.execute('UPDATE state SET value=? WHERE key=?', (encode(value), key))
    db.execute('INSERT INTO events(kind,data) VALUES (?,?)',
               ('text_work_distinct_disposition_consumed', encode(value)))
    return True
