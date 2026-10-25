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
    attempts = owned_model_attempts(store, actor, operation_id)
    projection = {}
    if attempts:
        projection = {
                   'model_attempts': attempts[:20], 'model_attempts_total': len(attempts),
                   'model_attempts_truncated': len(attempts) > 20,
                   'model_attempt_note': 'Owned factual outcomes, not adopted content or engineering verdicts. '
                       'Query an individual raw_operation to inspect an omitted attempt. No retry authority.'}
    # The current actor is server-bound. A different task's text attempt is not
    # disclosed, even when it chose the same caller operation id.
    with store.connect() as db:
        row = db.execute('SELECT value FROM state WHERE key=?',
                         ('text_work:' + actor.id + ':' + operation_id,)).fetchone()
        if not row:
            return {**content, **projection, 'state': content['state'] if content['state'] != 'unknown' or not attempts else 'known_model_attempt'}
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
    return {**content, **projection,
            'state': content['state'] if content['state'] != 'unknown' else 'known_text_attempt',
            'operation_id': operation_id, 'content_operation': content, 'text_work': attempt,
            'note': 'Content writes and text generation are separate. A completed text payload is not an adopted content write or semantic acceptance. A stored reservation alone does not establish a received response; consult the observed outcome above. An unresolved outcome does not establish that the provider is running or that no work occurred. Changing an id or wording does not resolve an earlier unknown outcome; this query grants no retry authority.'}


def owned_model_attempts(store, actor, operation_id):
    """Project existing raw/vision reservations without disclosing inputs or responses.

    Old receipts lacking an authoritative owner are not guessed from role or IDs.
    Ownership metadata is recorded by server-bound callers on new reservations;
    it is outside paid request hashes and cannot clear any historical unknown.
    """
    with store.connect() as db:
        alias = None
        saved = db.execute('SELECT value FROM state WHERE key=?',
            ('bounded_review_result:' + actor.task_id + ':' + operation_id,)).fetchone()
        if saved:
            result = json.loads(saved[0]).get('result', {})
            ref = result.get('review_ref') or {}
            if ref.get('type') == 'ReviewRecord':
                row = db.execute('SELECT data FROM content_versions WHERE type=? AND id=? AND version=?',
                    (ref['type'], ref.get('id'), ref.get('version'))).fetchone()
                review = json.loads(row[0]) if row else {}
                identity = review.get('payload', {}).get('runtime_identity', {})
                if (review.get('owner_id') == actor.id and review.get('task_id') == actor.task_id
                        and review.get('payload', {}).get('task_ref') == actor.task_id
                        and result.get('analysis_operation') == identity.get('analysis_operation')):
                    alias = result.get('analysis_operation')
        rows = db.execute("SELECT value FROM state WHERE "
            "(key LIKE 'bounded_review_attempt:%' AND json_extract(value,'$.owner.id')=?) "
            "OR (key LIKE 'vision_attempt:%' AND json_extract(value,'$.actor.id')=?)",
            (actor.id, actor.id)).fetchall()
    result = []
    for raw, in rows:
        work = json.loads(raw)
        owner = work.get('owner') or work.get('actor')
        if owner != actor.__dict__:
            raise ActionForbidden('FORBIDDEN: model attempt owner mismatch')
        cache_alias = alias is not None and alias == work.get('operation')
        if operation_id not in (work.get('operation'), work.get('caller_operation_id')) and not cache_alias:
            continue
        outcome = work.get('result') or {}
        public = {k: outcome[k] for k in ('provider_outcome', 'raw_response_received',
            'usage', 'deadline_seconds', 'local_elapsed_seconds', 'failure_phase', 'model_call',
            'finish_reason', 'duration_seconds', 'admission_proof', 'raw_response_received_meaning',
            'model_response_parsed', 'http_body_complete', 'recorded_usage_by_attempt', 'usage_status',
            'capacity', 'handling') if k in outcome}
        if work.get('state') == 'not_dispatched':
            public.update(provider_outcome='not_dispatched', raw_response_received=False,
                          usage=None, admission_proof=work['admission_proof'])
        elif work.get('state') in {'reserved', 'unknown'}:
            public.setdefault('provider_outcome', 'unknown')
            if not public.get('recorded_usage_by_attempt'):
                public.setdefault('usage', None)
        else:
            public.setdefault('raw_response_received', True)
        result.append({**public, 'raw_operation': work['operation'], 'state': work['state'],
            **({'cache_reuse': True, 'new_http_attempt': False} if cache_alias and operation_id != work.get('caller_operation_id') else {}),
            'actor_id': actor.id, 'task_id': actor.task_id,
            'scope_ids': work.get('scope_ids', []), 'target_refs': work.get('target_refs', []),
            'adoptable_result': False, 'semantic_correctness_verified': False,
            'note': 'A completed raw response still requires its domain validation and adoption. '
                    'Changed wording or caller ID does not establish independent work. '
                    'General semantic equivalence is not inferred by this query.'})
    return result
