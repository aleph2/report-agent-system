"""Task-scoped aliases for existing immutable objects and actual read receipts."""
from copy import deepcopy
import json

from .content_models import Ref, refs_in
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


def _task(contents, actor):
    from .review_message import _task as bound_task
    return bound_task(contents, actor)


def check_handles(task):
    return {'C' + str(i + 1): i for i, _ in enumerate(task['payload']['review_requirements'])}


def assign_evidence_handle(db, actor_id, receipt_id):
    """Allocate inside the receipt writer's transaction; never grant access."""
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT actor_id FROM content_observations WHERE id=?', (receipt_id,)).fetchone()
    if not row or row[0] != actor_id:
        raise ActionForbidden('EVIDENCE_NOT_AUTHORIZED')
    key = 'review_evidence_handles:' + actor_id
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    value = json.loads(row[0]) if row else {'handles': {}, 'receipts': {}}
    if receipt_id not in value['receipts']:
        handle = 'obs-' + str(len(value['handles']) + 1)
        value['handles'][handle] = receipt_id
        value['receipts'][receipt_id] = handle
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(value)))
    return value['receipts'][receipt_id]


def evidence_handles(contents, actor):
    _task(contents, actor)
    with contents.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT id FROM content_observations WHERE actor_id=? ORDER BY rowid', (actor.id,)).fetchall()
        result = {assign_evidence_handle(db, actor.id, row[0]): row[0] for row in rows}
    return dict(sorted(result.items(), key=lambda pair: int(pair[0][4:])))


def content_handles(contents, snapshot_ref):
    ref = Ref.model_validate(snapshot_ref).model_dump()
    if ref['type'] != 'DocumentSnapshot':
        raise ActionRejected('CONTENT_SELECTION_REQUIRES_SNAPSHOT')
    with contents.store.connect() as db:
        snapshot = contents._read(db, ref)
        key = 'review_content_handles:' + digest(snapshot)
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        if row:
            return dict(json.loads(row[0]))
        records = {encode(r): contents._read(db, r) for r in snapshot['payload']['refs']}
        edges, parents, positions = {}, set(), set()
        for record in records.values():
            value = record['payload']
            if record['ref']['type'] != 'Relation' or value['predicate'] != 'contains':
                continue
            parent, child = encode(value['subject_ref']), encode(value['object_ref'])
            position = value['position']
            if child in parents or (parent, position) in positions:
                raise ActionRejected('MULTIPLE_PARENTS_OR_POSITIONS')
            if parent not in records or child not in records:
                raise ActionRejected('INCOMPLETE_REFERENCE_CLOSURE')
            parents.add(child); positions.add((parent, position))
            edges.setdefault(parent, []).append((position, child))
        visited, active = set(), set()
        def validate(node):
            if node in active:
                raise ActionRejected('CONTAINS_CYCLE')
            if node in visited:
                return
            active.add(node)
            for _, child in edges.get(node, []):
                validate(child)
            active.remove(node); visited.add(node)
        for node in records:
            validate(node)
        root = encode(snapshot['payload']['root_ref'])
        if root in parents:
            raise ActionRejected('ROOT_HAS_PARENT')
        result = {}
        tables = 0
        def number(node, handle):
            nonlocal tables
            record = records[node]
            if record['ref']['type'] != 'ContentNode':
                raise ActionRejected('CONTENT_TREE_NODE_REQUIRED')
            result[handle] = record['ref']
            if record['payload']['kind'] == 'table':
                tables += 1
                result['T' + str(tables)] = record['ref']
            for i, (_, child) in enumerate(sorted(edges.get(node, [])), 1):
                number(child, handle + '.' + str(i))
        number(root, 'S1')
        # Aliases are structural positions, never inferred printed heading numbers.
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)', (key, encode(list(result.items()))))
        return result


def material_handles(contents, actor):
    task = _task(contents, actor)
    refs = {}
    for requirement in task['payload']['review_requirements']:
        for ref in refs_in([requirement.get('material_refs', []),
                           requirement.get('required_read_refs', []), requirement.get('required_materials', [])]):
            refs.setdefault(encode(ref.model_dump()), ref.model_dump())
    from .review_message import verified_source_observation
    with contents.store.connect() as db:
        rows = db.execute('SELECT data FROM content_observations WHERE actor_id=? ORDER BY rowid', (actor.id,)).fetchall()
    for row in rows:
        observation = json.loads(row[0])
        for ref in refs_in(observation):
            refs.setdefault(encode(ref.model_dump()), ref.model_dump())
        native = verified_source_observation(contents, actor, observation)
        for part in native['materials'] if native else []:
            descriptor = {k: part[k] for k in ('source_id', 'source_payload_digest', 'source_version_refs')}
            refs.setdefault(encode(descriptor), descriptor)
    key = 'review_material_handles:' + digest({'actor': actor.id, 'task': task})
    with contents.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        result = dict(json.loads(row[0])) if row else {}
        known = {encode(v) for v in result.values()}
        for identity, value in refs.items():
            if identity not in known:
                result['M' + str(len(result) + 1)] = value
                known.add(identity)
        db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(list(result.items()))))
    return result


def resolve(contents, actor, kind, handle):
    task = _task(contents, actor)
    if kind == 'check':
        mapping = {h: task['payload']['review_requirements'][i] for h, i in check_handles(task).items()}
    elif kind == 'evidence':
        mapping = evidence_handles(contents, actor)
    elif kind == 'content':
        mapping = content_handles(contents, task['payload']['review_snapshot_ref'])
    elif kind == 'material':
        mapping = material_handles(contents, actor)
    else:
        raise ActionRejected('UNKNOWN_HANDLE_KIND')
    if not isinstance(handle, str) or handle not in mapping:
        raise ActionRejected('UNKNOWN_REVIEW_HANDLE', diagnostic={
            'kind': kind, 'handle': handle, 'valid_handles': list(mapping)})
    return deepcopy(mapping[handle])


def resolve_content(contents, actor, ref):
    if isinstance(ref, str):
        return resolve(contents, actor, 'content', ref)
    task = _task(contents, actor)
    value = Ref.model_validate(ref.model_dump() if isinstance(ref, Ref) else ref).model_dump()
    snapshot = contents.read(task['payload']['review_snapshot_ref'])
    if value['type'] != 'ContentNode' or value not in snapshot['payload']['refs']:
        raise ActionForbidden('CONTENT_SELECTION_OUTSIDE_SNAPSHOT')
    return value


def project_read(contents, actor, value):
    _task(contents, actor)
    if not isinstance(value, dict):
        return value  # Native source ToolMessages are enriched before signing.
    result = deepcopy(value)
    receipt = result.get('receipt_id')
    if receipt:
        with contents.store.connect() as db:
            result['evidence_handle'] = assign_evidence_handle(db, actor.id, receipt)
    structure = result.get('result', {}).get('snapshot_structure')
    if structure:
        handles = content_handles(contents, structure['snapshot_ref'])
        reverse = {}
        for handle, ref in handles.items():
            reverse.setdefault(encode(ref), []).append(handle)
        for node in structure['nodes']:
            aliases = reverse.get(encode(node['ref']), [])
            if aliases:
                node['handle'] = aliases[0]
                node['handles'] = aliases
    return result


def read_tools(contents, actor, tools):
    """Opt-in factory projection; the deployed tool catalog stays unchanged."""
    from functools import wraps
    import inspect
    from typing import get_type_hints
    from .content_selection import ContentSelection

    class HandleContentSelection(ContentSelection):
        ref: Ref | str

    names = {'read_context', 'read_content_index', 'read_content_selection', 'observe_evidence',
             'read_content_export', 'inspect_rendered_page', 'read_source_page', 'search_sources',
             'inspect_source_page', 'analyze_source_image', 'analyze_evidence'}

    def wrap(fn):
        signature = inspect.signature(fn)
        annotations = get_type_hints(fn, include_extras=True)
        if 'target_ref' in signature.parameters:
            annotations['target_ref'] = Ref | str
        for key in ('selections', 'content_selections'):
            if key in signature.parameters:
                annotations[key] = list[HandleContentSelection] if key == 'selections' else list[HandleContentSelection] | None
        def arguments(args, kwargs):
            owner = actor()
            task = _task(contents, owner)
            bound = signature.bind(*args, **kwargs)
            target = bound.arguments.get('target_ref')
            used_handle = isinstance(target, str)
            if isinstance(target, str):
                bound.arguments['target_ref'] = Ref.model_validate(resolve(contents, owner, 'content', target))
            for key in ('selections', 'content_selections'):
                if bound.arguments.get(key) is not None:
                    selections = []
                    for raw in bound.arguments[key]:
                        value = raw.model_dump() if hasattr(raw, 'model_dump') else dict(raw)
                        if isinstance(value['ref'], str):
                            used_handle = True
                            value['ref'] = resolve(contents, owner, 'content', value['ref'])
                        selections.append(ContentSelection.model_validate(value))
                    bound.arguments[key] = selections
            snapshot = bound.arguments.get('snapshot_ref')
            if used_handle and snapshot is not None:
                snapshot = snapshot.model_dump() if isinstance(snapshot, Ref) else snapshot
                if snapshot != task['payload']['review_snapshot_ref']:
                    raise ActionRejected('CONTENT_HANDLE_SNAPSHOT_MISMATCH')
            return owner, bound
        @wraps(fn)
        def sync(*args, **kwargs):
            owner, bound = arguments(args, kwargs)
            return project_read(contents, owner, fn(*bound.args, **bound.kwargs))
        @wraps(fn)
        async def asynchronous(*args, **kwargs):
            owner, bound = arguments(args, kwargs)
            return project_read(contents, owner, await fn(*bound.args, **bound.kwargs))
        wrapper = asynchronous if inspect.iscoroutinefunction(fn) else sync
        wrapper.__annotations__ = annotations
        wrapper.__signature__ = signature.replace(parameters=[p.replace(annotation=annotations.get(k, p.annotation))
            for k, p in signature.parameters.items()], return_annotation=annotations.get('return', signature.return_annotation))
        return wrapper
    return [wrap(fn) if getattr(fn, '__name__', None) in names else fn for fn in tools]
