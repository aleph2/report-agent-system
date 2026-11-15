"""Internal Reviewer step services; not registered in the current interface."""
import json


from .errors import ActionForbidden, ActionRejected
from .store import digest, encode
from . import review_handles as handles
from .review_message import (validate_message_binding)


def _get(db, key, default=None):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(value)))


def _open(db, actor):
    if _get(db, 'review_finished:' + actor.task_id):
        raise ActionRejected('REVIEW_FINISHED')


def finalize_mark(contents, db, actor, operation_id, review_ref, step):
    """Save replacement, lineage, draft state and immutable locations in one transaction."""
    _open(db, actor)
    key = 'review_check:' + actor.task_id + ':' + step['check']
    if _get(db, key) != step['old']:
        raise ActionRejected('REVIEW_CHECK_CHANGED')
    links = []
    for index, draft in enumerate(step['drafts']):
        draft_key = 'review_draft:' + actor.task_id + ':' + draft['finding']
        if _get(db, draft_key) != draft:
            raise ActionRejected('REVIEW_DRAFT_CHANGED')
        validate_message_binding(contents, db, actor, draft['binding'])
        links.append({k: draft[k] for k in ('finding', 'actor_id', 'snapshot_ref', 'location_ref')} |
                     {'review_ref': review_ref, 'item_index': 0, 'finding_index': index})
        _put(db, draft_key, {**draft, 'status': 'saved'})
    if step['old']:
        contents._supersede_review(db, actor, step['old'], review_ref, step['correction_reason'])
    _put(db, 'review_finding_locations:' + digest(review_ref), links)
    _put(db, key, review_ref)
    return {'open_checks': [h for h in step['checks'] if not _get(db, 'review_check:' + actor.task_id + ':' + h)]}


def metrics(store, task_id=None):
    with store.connect() as db:
        rows = db.execute("SELECT value FROM state WHERE key GLOB 'review_draft:*'").fetchall()
    drafts = [json.loads(r[0]) for r in rows if task_id is None or json.loads(r[0])['task_id'] == task_id]
    return {'drafts': len(drafts), 'withdrawals': sum(d['status'] == 'withdrawn' for d in drafts),
            'open_drafts': sum(d['status'] == 'open' for d in drafts)}


def saved_findings(contents, actor, review_ref):
    handles._task(contents, actor)
    record = contents.read(review_ref)
    if record['ref']['type'] != 'ReviewRecord' or record['owner_id'] != actor.id or record['task_id'] != actor.task_id:
        raise ActionForbidden('REVIEW_FINDINGS_NOT_AUTHORIZED')
    return contents.store.get('review_finding_locations:' + digest(review_ref), [])
