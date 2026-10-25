"""Host-only exact-payload exceptions to the cumulative content revision limit.

This grants a single version transition, not extra general editing authority.
The native commit still enforces owner, compare-and-swap and normal contracts.
"""
import json

from .content_models import PAYLOADS
from .store import digest


def exact_exception(db, actor, prior, proposed):
    row = db.execute("SELECT value FROM state WHERE key='content_revision_exceptions'").fetchone()
    if not row:
        return None
    grants = json.loads(row[0])
    if not isinstance(grants, list):
        return None
    # Validate before hashing: omitted defaults are equivalent to explicit ones.
    payload = PAYLOADS['ContentNode'].model_validate(proposed).model_dump()
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        if (grant.get('previous_ref') == prior['ref']
                and grant.get('owner_id') == actor.id
                and grant.get('previous_payload_digest') == prior['payload_digest']
                and grant.get('approved_payload_digest') == digest(payload)
                and isinstance(grant.get('authorization_id'), str)
                and grant['authorization_id'].strip()
                and isinstance(grant.get('authorization_sha256'), str)
                and len(grant['authorization_sha256']) == 64):
            return grant
    return None


def record_use(db, grant, resulting_ref, operation_id):
    # Within the commit transaction: a failed batch rolls this audit back too.
    db.execute("INSERT INTO events(kind,data) VALUES (?,?)", (
        'content_revision_exception_used', json.dumps({
            'authorization_id': grant['authorization_id'],
            'authorization_sha256': grant['authorization_sha256'],
            'previous_ref': grant['previous_ref'], 'resulting_ref': resulting_ref,
            'owner_id': grant['owner_id'], 'approved_payload_digest': grant['approved_payload_digest'],
            'operation_id': operation_id, 'counts_reset': False}, ensure_ascii=False)))
