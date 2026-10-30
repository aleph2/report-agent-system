"""Exact producer selections over saved versions; no discovery or acceptance judge."""
import json
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from .content_inputs import BatchRef
from .content_models import Contract, Ref, refs_in
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode

V4 = 'review-interfaces-v4'
CONTRACT = 'deliverable-declaration-v1'


class SavedReceipt(Contract):
    kind: Literal['saved_result', 'deliverable']
    operation_id: str = Field(min_length=1)


class SavedSnapshot(Contract):
    kind: Literal['snapshot']
    snapshot_ref: Ref


class DeliverableHandle(Contract):
    kind: Literal['deliverable']
    operation_id: str = Field(min_length=1)


class ExistingSnapshot(Contract):
    kind: Literal['existing_snapshot']
    snapshot_ref: Ref


class SavedWork(Contract):
    kind: Literal['saved_work']
    root_ref: BatchRef
    include_current_save: bool = Field(default=False, strict=True)
    members_from: list[Annotated[SavedReceipt | SavedSnapshot, Field(discriminator='kind')]]
    workbook_refs: list[BatchRef] = Field(default_factory=list)
    remove_refs: list[Ref] = Field(default_factory=list)

    @model_validator(mode='after')
    def explicit_pool(self):
        if not self.members_from and not self.include_current_save:
            raise ValueError('DELIVERABLE_EMPTY_POOL')
        return self


DeliverableSelection = Annotated[ExistingSnapshot | SavedWork, Field(discriminator='kind')]


def key(ref):
    return Ref.model_validate(ref).key()


def parent(cs, db, actor_id, role=None, task_id=None):
    """Published output retains authorship and is readable only under its parent."""
    if actor_id.startswith('content:writer:'):
        task_id = actor_id[len('content:writer:'):]
        task = cs._read(db, {'type': 'DelegatedTask', 'id': task_id, 'version': 1})
        if task['payload'].get('role') != 'writer' or task['payload'].get('delegated_by') != task['owner_id']:
            raise ActionForbidden('FORBIDDEN: deliverable producer')
        return task['owner_id']
    if role == 'coordinator' or actor_id == 'content:coordinator':
        return actor_id
    raise ActionForbidden('FORBIDDEN: deliverable producer')


def member_digest(value):
    return digest({name: sorted(value[name], key=key) if name != 'root_ref' else value[name]
                   for name in ('root_ref', 'member_refs', 'workbook_refs')})


def published(cs, db, actor, operation_id):
    row = db.execute('SELECT actor_id,response FROM content_operations WHERE operation_id=?',
                     (operation_id,)).fetchone()
    if row is None:
        raise ActionRejected('DELIVERABLE_SOURCE_NOT_FOUND')
    response = json.loads(row[1])
    value = (response.get('result') or {}).get('deliverable')
    if (not response.get('ok') or not isinstance(value, dict) or value.get('contract') != CONTRACT
            or value.get('operation_id') != operation_id or value.get('producer_actor_id') != row[0]):
        raise ActionRejected('DELIVERABLE_NOT_PUBLISHED')
    if (not isinstance(value.get('root_ref'), dict)
            or not isinstance(value.get('member_refs'), list) or not value['member_refs']
            or not isinstance(value.get('workbook_refs'), list)
            or not isinstance(value.get('member_digest'), str)
            or value.get('producer_role') not in {'writer', 'coordinator'}
            or not isinstance(value.get('producer_task_id'), str)
            or 'producer_task_ref' not in value or 'selection' not in value):
        raise ActionRejected('DELIVERABLE_DECLARATION_INVALID')
    try:
        root_key = key(value['root_ref'])
        members = [key(r) for r in value['member_refs']]
        [key(r) for r in value['workbook_refs']]
        TypeAdapter(DeliverableSelection).validate_python(value['selection'])
        if root_key not in members or len(set(members)) != len(members):
            raise ActionRejected('DELIVERABLE_DECLARATION_INVALID')
        if value['producer_role'] == 'writer' and (
                value['producer_actor_id'] != 'content:writer:' + value['producer_task_id']
                or value['producer_task_ref'] != {'type': 'DelegatedTask', 'id': value['producer_task_id'], 'version': 1}):
            raise ActionRejected('DELIVERABLE_DECLARATION_INVALID')
    except (ValidationError, TypeError):
        raise ActionRejected('DELIVERABLE_DECLARATION_INVALID') from None
    if (parent(cs, db, actor.id, actor.role, actor.task_id) !=
            parent(cs, db, row[0], value.get('producer_role'), value.get('producer_task_id'))):
        raise ActionForbidden('FORBIDDEN: deliverable parent')
    if value.get('member_digest') != member_digest(value):
        raise ActionRejected('DELIVERABLE_DIGEST_MISMATCH')
    source_authority(cs, db, actor, [cs._read(db, ref) for ref in value['member_refs']])
    return value


def source_authority(cs, db, actor, records):
    """Use the existing host-enrolled source versions, inside the current transaction."""
    binding = ('source_use_authority_binding' if actor.role == 'coordinator'
               else 'source_use_task_binding:' + actor.task_id)
    row = db.execute('SELECT value FROM state WHERE key=?', (binding,)).fetchone()
    if row is None:
        from .handoff_release import manifest
        if manifest(cs.store).get('source_use') is not None:
            raise ActionRejected('SOURCE_USE_DECLARED_BUT_UNBOUND')
        active = db.execute("SELECT value FROM state WHERE key='source_use_authority_binding'").fetchone()
        if active:
            raise ActionForbidden('FORBIDDEN: deliverable source binding')
        return
    policy_ref = json.loads(row[0])
    policy_row = db.execute('SELECT value FROM state WHERE key=?',
                            ('source_use_authority:' + policy_ref,)).fetchone()
    policy = json.loads(policy_row[0]) if policy_row else None
    from .source_use import _commission
    if (not policy or digest(policy) != policy_ref or policy.get('contract') != 'source-use-v1'
            or policy.get('commission_binding') != _commission(cs.store)):
        raise ActionRejected('SOURCE_USE_AUTHORITY_INVALID')
    from .source_use import immutable_version_digest
    allowed = {r['source_id']: r['immutable_version_digest'] for r in policy['versions']}
    for record in records:
        if record['ref']['type'] == 'SourceArtifact':
            payload = record['payload']
            if allowed.get(payload['source_id']) != immutable_version_digest(payload):
                raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')


def snapshot_selection(cs, db, actor, ref):
    record = cs._read(db, ref)
    if ref['type'] != 'DocumentSnapshot':
        raise ActionRejected('DELIVERABLE_SNAPSHOT_REQUIRED')
    if (parent(cs, db, actor.id, actor.role, actor.task_id) !=
            parent(cs, db, record['owner_id'], 'coordinator' if record['owner_id'] == actor.id
                   and actor.role == 'coordinator' else None)):
        raise ActionForbidden('FORBIDDEN: deliverable snapshot parent')
    return record['payload']


def declare(cs, db, actor, operation_id, selection, assigned):
    from .prompt_sources import review_interface_profile
    if review_interface_profile(cs.store) != V4:
        raise ActionRejected('DELIVERABLE_SELECTION_REQUIRES_V4')
    if actor.role not in {'writer', 'coordinator'}:
        raise ActionForbidden('FORBIDDEN: deliverable role')
    parent(cs, db, actor.id, actor.role, actor.task_id)
    selection = TypeAdapter(DeliverableSelection).validate_python(selection).model_dump()

    def resolved(ref):
        if set(ref) == {'client_key'}:
            if ref['client_key'] not in assigned:
                raise ActionRejected('UNKNOWN_CLIENT_KEY')
            return assigned[ref['client_key']]
        return Ref.model_validate(ref).model_dump()

    pool = {}
    if selection['kind'] == 'existing_snapshot':
        snap = snapshot_selection(cs, db, actor, selection['snapshot_ref'])
        root, workbooks = snap['root_ref'], snap.get('workbook_refs', [])
        pool = {key(r): cs._read(db, r) for r in snap['refs']}
        kept = set(pool)
    else:
        sources = list(assigned.values()) if selection['include_current_save'] else []
        for origin in selection['members_from']:
            if origin['kind'] == 'saved_result':
                sources.extend(cs._saved_reference_set(db, actor, origin['operation_id']).values())
            elif origin['kind'] == 'deliverable':
                sources.extend(published(cs, db, actor, origin['operation_id'])['member_refs'])
            else:
                sources.extend(snapshot_selection(cs, db, actor, origin['snapshot_ref'])['refs'])
        pool = {key(r): cs._read(db, r) for r in sources}
        root = resolved(selection['root_ref'])
        workbooks = [resolved(r) for r in selection['workbook_refs']]
        kept = {key(root), *(key(r) for r in workbooks)}
        removed = {key(r) for r in selection['remove_refs']}
        if not kept <= pool.keys():
            raise ActionRejected('DELIVERABLE_ROOT_OR_WORKBOOK_OUTSIDE_POOL')
        if not removed <= pool.keys() or removed & kept:
            raise ActionRejected('DELIVERABLE_INVALID_EXCLUSION')
        relations = [r for r in pool.values() if r['ref']['type'] == 'Relation']
        pending = list(kept)
        while pending:
            current = pending.pop()
            for relation in relations:
                p = relation['payload']
                if key(p['subject_ref']) != current or key(relation['ref']) in removed:
                    continue
                if p['predicate'] == 'contains' and key(p['object_ref']) in removed:
                    continue
                if key(relation['ref']) not in kept:
                    kept.add(key(relation['ref'])); pending.append(key(relation['ref']))
            for dependency in refs_in(pool[current]['payload']):
                dep = dependency.key()
                if dep in removed:
                    raise ActionRejected('DELIVERABLE_EXCLUDED_DEPENDENCY')
                if dep not in kept:
                    pool.setdefault(dep, cs._read(db, dependency.model_dump()))
                    kept.add(dep); pending.append(dep)
    if root['type'] != 'ContentNode':
        raise ActionRejected('DELIVERABLE_ROOT_REQUIRES_CONTENT')
    members = [pool[k]['ref'] for k in sorted(kept)]
    source_authority(cs, db, actor, [pool[k] for k in kept])
    cs._snapshot_payload(db, root, members, workbooks)
    value = {'contract': CONTRACT, 'operation_id': operation_id,
             'producer_actor_id': actor.id, 'producer_role': actor.role,
             'producer_task_id': actor.task_id,
             'producer_task_ref': {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1}
                                  if actor.role == 'writer' else None,
             'root_ref': root, 'member_refs': members, 'workbook_refs': sorted(workbooks, key=key),
             'selection': selection, 'semantic_acceptance': False,
             'unselected': {'counts': dict(Counter(pool[k]['ref']['type'] for k in pool.keys()-kept)),
                            'total': len(pool.keys()-kept)}}
    value['member_digest'] = member_digest(value)
    return value


def directory(cs, db, actor, producer_task_ref=None, *, full=False):
    """Parent-owned read projection, recomputed from immutable successful receipts."""
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: deliverable directory')
    tasks = db.execute("SELECT data FROM content_versions WHERE type='DelegatedTask' AND version=1 ORDER BY id").fetchall()
    entries = []
    for raw, in tasks:
        task = json.loads(raw)
        if (task['owner_id'] != actor.id or task['payload'].get('delegated_by') != actor.id
                or task['payload'].get('role') != 'writer'
                or producer_task_ref is not None and task['ref'] != producer_task_ref):
            continue
        owner = 'content:writer:' + task['ref']['id']
        for operation_id, response in db.execute(
                'SELECT operation_id,response FROM content_operations WHERE actor_id=? ORDER BY rowid', (owner,)):
            saved = json.loads(response)
            if not saved.get('ok') or not isinstance(saved.get('result', {}).get('deliverable'), dict):
                continue
            try:
                declared = published(cs, db, actor, operation_id)
            except (ActionRejected, ActionForbidden) as exc:
                entries.append({'operation_id': operation_id, 'producer_task_ref': task['ref'],
                                'status': 'unavailable', 'reason': str(exc), 'semantic_acceptance': False})
                continue
            entry = {k: declared[k] for k in ('operation_id', 'producer_task_ref', 'root_ref',
                       'member_digest', 'semantic_acceptance')}
            entry.update(selection_only=bool(saved['result'].get('selection_only')),
                         counts=dict(Counter(r['type'] for r in declared['member_refs'])),
                         workbook_count=len(declared['workbook_refs']),
                         title_preview=cs._read(db, declared['root_ref'])['payload']['body'].get('text', '')[:120])
            if full:
                entry.update(member_refs=declared['member_refs'], workbook_refs=declared['workbook_refs'])
            entries.append(entry)
    return entries


def resolve_snapshot(cs, db, actor, selector):
    """Only an explicit existing export/delegation calls this transaction-bound resolver."""
    selector = selector.model_dump() if hasattr(selector, 'model_dump') else selector
    if not isinstance(selector, dict):
        raise ActionRejected('DELIVERABLE_SELECTOR_REQUIRED')
    if selector.get('kind') == 'snapshot' and set(selector) == {'kind', 'snapshot_ref'}:
        payload = snapshot_selection(cs, db, actor, selector['snapshot_ref'])
        source_authority(cs, db, actor, [cs._read(db, r) for r in payload['refs']])
        return selector['snapshot_ref']
    if selector.get('kind') != 'deliverable' or set(selector) != {'kind', 'operation_id'}:
        raise ActionRejected('DELIVERABLE_SELECTOR_INVALID')
    value = published(cs, db, actor, selector['operation_id'])
    if value['selection']['kind'] == 'existing_snapshot':
        ref = value['selection']['snapshot_ref']
        snapshot_selection(cs, db, actor, ref)
        return ref
    provenance = {'operation_id': selector['operation_id'], 'member_digest': value['member_digest']}
    rows = db.execute("SELECT data FROM content_versions WHERE type='DocumentSnapshot' "
        "AND json_extract(data,'$.payload.deliverable_provenance.operation_id')=? "
        "AND json_extract(data,'$.payload.deliverable_provenance.member_digest')=?", tuple(provenance.values())).fetchall()
    if len(rows) > 1:
        raise ActionRejected('DELIVERABLE_SNAPSHOT_CONFLICT')
    payload = cs._snapshot_payload(db, value['root_ref'], value['member_refs'], value['workbook_refs'])
    if rows:
        record = json.loads(rows[0][0])
        if any(record['payload'].get(k) != v for k, v in payload.items()):
            raise ActionRejected('DELIVERABLE_SNAPSHOT_CONFLICT')
        snapshot_selection(cs, db, actor, record['ref'])
        return record['ref']
    return cs._insert(db, actor, 'DocumentSnapshot', {**payload, 'deliverable_provenance': provenance})


def export_allowed(cs, db, actor, snapshot):
    """V4 selection grants read/export scope, never another producer's write identity."""
    if snapshot['ref']['type'] != 'DocumentSnapshot':
        raise ActionRejected('SNAPSHOT_REQUIRED')
    source_authority(cs, db, actor, [cs._read(db, ref) for ref in snapshot['payload']['refs']])
    if actor.role == 'coordinator':
        return parent(cs, db, snapshot['owner_id']) == actor.id
    if actor.role == 'writer':
        return snapshot['owner_id'] == actor.id and cs._read(db, snapshot['payload']['root_ref'])['owner_id'] == actor.id
    if actor.role == 'layout':
        task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
        return (actor.id == 'content:layout:'+actor.task_id and task['payload'].get('role') == 'layout'
                and task['payload'].get('layout_snapshot_ref') == snapshot['ref']
                and parent(cs, db, snapshot['owner_id']) == task['owner_id'])
    return False
