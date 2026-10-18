"""Native pause for pre-provider unknown-admission denials, not a new agent loop.

Ordinary tool errors and already dispatched deadline outcomes retain their normal
observations. Only a detected unresolved-work admission denial pauses its exact
native tool call. Host dispositions never clear unknowns or rewrite checkpoints.
"""
import json

from .content_store import Actor
from .errors import ActionRejected
from .store import digest
from .text_work_disposition import disposition_key, matching_disposition
from .native_admission import exact_call_key, wait_for_exact_resume

KIND = 'text_work_unknown_admission'
CODES = {'TEXT_WORK_RELATED_OUTCOME_UNRESOLVED',
         'TEXT_WORK_SAME_EVIDENCE_OUTCOME_UNRESOLVED',
         'TEXT_WORK_OUTCOME_UNRESOLVED'}


def resume_answer(workspace, event):
    """Return an exact resume token only for a still valid host disposition."""
    if not isinstance(event, dict) or event.get('kind') != KIND:
        return None
    pending = workspace.store.get(event['pending_key'])
    if not pending or pending['event'] != event or pending.get('invalidated'):
        return None
    details = event['details']
    if not details.get('conflicts') or not details.get('candidate_request_hash'):
        return None  # An unchanged original unknown cannot be released as new work.
    actor = Actor(**event['actor'])
    request_hash = details['candidate_request_hash']
    with workspace.store.connect() as db:
        grant = matching_disposition(db, actor, event['operation_id'], request_hash,
                                     details['candidate_material_identity'], details['conflicts'])
        if grant is None:
            # A tool can finish before its checkpoint write. Replay may reuse only
            # that exact completed receipt, never a consumed unknown reservation.
            key = disposition_key(actor.id, event['operation_id'], request_hash)
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            grant = json.loads(row[0]) if row else {}
            row = db.execute('SELECT value FROM state WHERE key=?',
                ('text_work:'+actor.id+':'+event['operation_id'],)).fetchone()
            work = json.loads(row[0]) if row else {}
            if (grant.get('state') != 'consumed' or grant.get('actor') != actor.__dict__
                    or grant.get('request_hash') != request_hash
                    or work.get('state') != 'completed' or work.get('request_hash') != request_hash):
                return None
    return {'kind': KIND, 'pending_key': event['pending_key'],
            'request_hash': request_hash, 'call_digest': event['call_digest']}


async def admitted_call(workspace, role, call, handler):
    """Keep interrupts in stable order before handler replay and grant consumption."""
    from .text_work import actor_for_tool
    actor = actor_for_tool(workspace, role)
    store = workspace.store
    call_digest = digest(call)
    key = exact_call_key('text_work_interrupt:', actor.__dict__, call)
    pending = store.get(key)
    while True:
        if pending:
            wait_for_exact_resume(pending['event'], lambda event: resume_answer(workspace, event))
        try:
            return await handler()
        except ActionRejected as exc:
            code, _, raw = str(exc).partition(':')
            if code not in CODES:
                if not pending:
                    raise
                # A changed contract/material can fail before grant consumption.
                # Do not turn that stale host authorization into ordinary replanning.
                details = pending['event']['details']
                grant = store.get(disposition_key(actor.id, call['args']['operation_id'],
                                                  details.get('candidate_request_hash')))
                if not grant or grant['state'] != 'authorized':
                    raise  # Already dispatched output validation stays observable.
            if pending:
                pending = {**pending, 'invalidated': {'code': code, 'message': str(exc)}}
                store.set(key, pending)
                store.event('text_work_interrupt_invalidated', {'pending_key': key, 'code': code})
            else:
                details = json.loads(raw) if code != 'TEXT_WORK_OUTCOME_UNRESOLVED' else {}
                event = {'kind': KIND, 'pending_key': key, 'actor': actor.__dict__,
                    'tool': call['name'], 'tool_call_id': call['id'], 'call_digest': call_digest,
                    'operation_id': call['args']['operation_id'], 'code': code,
                    'producer_invoked': False, 'details': details}
                pending = {'event': event}
                store.set(key, pending)
                store.event('text_work_admission_paused', event)
