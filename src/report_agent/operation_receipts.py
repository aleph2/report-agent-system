"""Read the caller's distinct content-write and bounded text-work outcomes."""
import json

from .store import digest, encode
from .errors import ActionForbidden


def archived_input(db, actor, request_hash):
    matches = []
    for raw, in db.execute("SELECT data FROM events WHERE kind='evidence_analysis_input' "
                           "AND json_extract(data, '$.input.actor.id')=?", (actor.id,)):
        event = json.loads(raw)
        fingerprint = digest({'packet': event['input'], 'model': event['model'],
                              'prompt': event['system_prompt']})
        if fingerprint == request_hash:
            if encode(event) not in {encode(item) for item in matches}:
                matches.append(event)
    # Ambiguous or absent history is not a licence to guess the latest attempt.
    return matches[0] if len(matches) == 1 else None


def archived_attempt(db, actor, request_hash):
    event = archived_input(db, actor, request_hash)
    return event['operation'] if event else None


def operation_receipt(contents, actor, operation_id):
    store = contents.store
    content = contents.receipt(actor, operation_id)
    # The current actor is server-bound. A different task's text attempt is not
    # disclosed, even when it chose the same caller operation id.
    with store.connect() as db:
        row = db.execute('SELECT value FROM state WHERE key=?',
                         ('text_work:' + actor.id + ':' + operation_id,)).fetchone()
        if not row:
            return content
        work = json.loads(row[0])
        if 'actor' in work and work['actor'] != actor.__dict__:
            raise ActionForbidden('FORBIDDEN: text attempt owner mismatch')
        result = work.get('result', {})
        if (('actor_id' in result and result['actor_id'] != actor.id)
                or ('task_id' in result and result['task_id'] != actor.task_id)):
            raise ActionForbidden('FORBIDDEN: text result owner mismatch')
        raw_operation = work.get('operation') or work.get('result', {}).get('operation')
        if not raw_operation:
            raw_operation = archived_attempt(db, actor, work['request_hash'])
        rejected = None
        unresolved = None
        if raw_operation:
            rejection = db.execute("SELECT data FROM events WHERE kind='evidence_analysis_rejected_response' "
                                   "AND json_extract(data, '$.operation')=? ORDER BY sequence DESC LIMIT 1",
                                   (raw_operation,)).fetchone()
            rejected = json.loads(rejection[0]) if rejection else None
            observation = db.execute("SELECT data FROM events WHERE kind='evidence_analysis_unresolved' "
                                     "AND json_extract(data, '$.operation')=? ORDER BY sequence DESC LIMIT 1",
                                     (raw_operation,)).fetchone()
            unresolved = json.loads(observation[0]) if observation else None
    result = work.get('result', {})
    attempt = {'state': work['state'], 'request_hash': work['request_hash'],
               'actor_id': actor.id, 'task_id': actor.task_id,
               'raw_operation': raw_operation,
               'text_work_id': result.get('text_work_id'),
               'raw_response_received': work.get('raw_response_received',
                                                 True if work['state'] == 'completed' else None),
               'semantic_correctness_verified': False}
    for key in ('failure_phase', 'diagnostic'):
        if key in work:
            attempt[key] = work[key]
    if work['state'] == 'not_dispatched':
        attempt.update(provider_outcome='not_dispatched', raw_response_received=False,
                       usage=None, adoptable_result=False,
                       failure_phase='local_request_admission', admission_proof=work['admission_proof'])
    elif rejected:
        attempt.update(state='known_rejected_response', stored_state=work['state'],
                       raw_response_received=True, finish_reason=rejected.get('finish_reason'),
                       duration_seconds=rejected.get('duration_seconds'), usage=rejected.get('usage'),
                       failure_phase='incomplete_or_invalid_response', adoptable_result=False)
    elif unresolved:
        attempt.update(state='outcome_unresolved', stored_state=work['state'],
                       raw_response_received=False, provider_outcome='unknown', usage=None,
                       deadline_seconds=unresolved['deadline_seconds'],
                       local_elapsed_seconds=unresolved['local_elapsed_seconds'],
                       failure_phase='local_request_deadline', adoptable_result=False)
    return {**content,
            'state': content['state'] if content['state'] != 'unknown' else 'known_text_attempt',
            'operation_id': operation_id, 'content_operation': content, 'text_work': attempt,
            'note': 'Content writes and text generation are separate. A completed text payload is not an adopted content write or semantic acceptance. A stored reservation alone does not establish a received response; consult the observed outcome above. An unresolved outcome does not establish that the provider is running or that no work occurred. Changing an id or wording does not resolve an earlier unknown outcome; this query grants no retry authority.'}
