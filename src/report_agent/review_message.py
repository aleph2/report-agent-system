"""Single-check message model and assembler for the existing ReviewRecord contract."""
import hashlib
import json


from .content_tasks import bound_actor
from .errors import ActionForbidden, ActionRejected
from .store import digest
from .workspace import Workspace


def _task(contents, actor):
    if actor.role != 'reviewer' or bound_actor(Workspace(contents.store), 'reviewer', None) != actor:
        raise ActionForbidden('REVIEW_MESSAGE_TASK_BINDING_REQUIRED')
    task = contents.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    if task['payload'].get('role') != 'reviewer':
        raise ActionForbidden('REVIEW_MESSAGE_TASK_BINDING_REQUIRED')
    return task


def bind_review_message(contents, actor, receipt_ids):
    """Freeze an internal evidence directory; this does not read materials anew."""
    task = _task(contents, actor)
    if len(set(receipt_ids)) != len(receipt_ids):
        raise ActionRejected('DUPLICATE_EVIDENCE_REFERENCE')
    with contents.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        task = contents._read(db, task['ref'])
        receipts = []
        for receipt in receipt_ids:
            row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (receipt,)).fetchone()
            if not row or row[0] != actor.id:
                raise ActionForbidden('EVIDENCE_NOT_AUTHORIZED')
            receipts.append({'receipt_id': receipt, 'sha256': hashlib.sha256(row[1].encode()).hexdigest()})
        snapshot = contents._read(db, task['payload']['review_snapshot_ref'])
        from .review_coverage import inventory
        binding = {'actor_id': actor.id, 'task_id': actor.task_id, 'task_sha256': digest(task), 'receipts': receipts,
                   'snapshot_sha256': digest(snapshot), 'coverage_refs': inventory(snapshot)}
        # Compare and append in one write transaction, including receipt capture.
        latest_key = 'review_message_latest:' + actor.id
        row = db.execute('SELECT value FROM state WHERE key=?', (latest_key,)).fetchone()
        if row:
            previous = json.loads(row[0])
            previous_ids = [r['receipt_id'] for r in previous['receipts']]
            if receipt_ids[:len(previous_ids)] != previous_ids:
                raise ActionRejected('EVIDENCE_DIRECTORY_REORDERED')
            if receipts[:len(previous_ids)] != previous['receipts']:
                raise ActionRejected('RECEIPT_BINDING_CHANGED')
        encoded = json.dumps(binding, sort_keys=True, ensure_ascii=False)
        db.execute('INSERT OR IGNORE INTO state(key,value) VALUES (?,?)',
                   ('review_message_binding:' + digest(binding), encoded))
        db.execute('INSERT OR REPLACE INTO state(key,value) VALUES (?,?)', (latest_key, encoded))
    return binding


def verified_source_observation(contents, actor, value):
    """Use the existing native source receipt verifier, including exact public-return bytes."""
    native = value.get('native_source_material_receipt')
    if not native:
        return None
    record = contents.store.get('source_material:' + native)
    original = contents.store.get('tool_observation:' + record['body_ref']) if record else None
    if not record or not original:
        raise ActionRejected('SOURCE_MATERIAL_ORIGINAL_CHANGED')
    from .source_materials import verify
    return verify(Workspace(contents.store), actor, native, original['text'], record['tool'])


def validate_message_binding(contents, db, actor, binding):
    """Revalidate the original directory inside the existing review save transaction."""
    if binding.get('actor_id') != actor.id or binding.get('task_id') != actor.task_id:
        raise ActionForbidden('REVIEW_MESSAGE_BINDING_CHANGED')
    row = db.execute('SELECT value FROM state WHERE key=?',
                     ('review_message_binding:' + digest(binding),)).fetchone()
    if not row or json.loads(row[0]) != binding:
        raise ActionRejected('REVIEW_MESSAGE_BINDING_UNAVAILABLE')
    task = contents._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    if binding['task_sha256'] != digest(task):
        raise ActionRejected('REVIEW_MESSAGE_BINDING_CHANGED')
    snapshot = contents._read(db, task['payload']['review_snapshot_ref'])
    from .review_coverage import inventory
    if binding['snapshot_sha256'] != digest(snapshot) or binding['coverage_refs'] != inventory(snapshot):
        raise ActionRejected('REVIEW_MESSAGE_BINDING_CHANGED')
    for receipt in binding['receipts']:
        row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                         (receipt['receipt_id'],)).fetchone()
        if not row or row[0] != actor.id or hashlib.sha256(row[1].encode()).hexdigest() != receipt['sha256']:
            raise ActionRejected('RECEIPT_BINDING_CHANGED')
        verified_source_observation(contents, actor, json.loads(row[1]))
