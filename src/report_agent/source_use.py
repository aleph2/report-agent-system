"""Host-recorded exact source-use versions, shared by actual material consumers.

This is not source discovery, relevance selection, or an Agent grant tool.
"""
import json

from . import commission_imports
from .errors import ActionForbidden, ActionRejected
from .store import digest


def validate_declaration(value, source_ids=None):
    if (not isinstance(value, dict) or set(value) != {'source_ids', 'authorization_origin'}
            or not isinstance(value['source_ids'], list) or not value['source_ids']
            or any(not isinstance(v, str) or not v.strip() for v in value['source_ids'])
            or not isinstance(value['authorization_origin'], str)
            or not value['authorization_origin'].strip()):
        raise ActionRejected('SOURCE_USE_DECLARATION_INVALID')
    ids = sorted(set(value['source_ids']))
    if source_ids is not None and not set(ids) <= set(source_ids):
        raise ActionRejected('SOURCE_NOT_IN_PROJECT')
    return {'source_ids': ids, 'authorization_origin': value['authorization_origin']}


def immutable_version_digest(payload):
    # Only Catalog's computed current flag is dynamic. All content, file digest,
    # coverage and every other metadata field remain inside the version hash.
    return digest({**payload, 'source_metadata': {
        k: v for k, v in payload['source_metadata'].items() if k != 'current'}})


def _commission(store):
    from .handoff_release import manifest
    value = manifest(store)
    return digest({k: value.get(k) for k in ('report_id', 'goal', 'scope_instruction', 'report_category')})


def _policy(store, ref, db=None):
    from .content_store import ContentStore
    if isinstance(ref, dict):
        if db is None:
            with store.connect() as connection:
                return _policy(store, ref, connection)
        if 'planning_inputs' in ref:
            return _supplied_policy(store, db, ref['planning_inputs'])
        if ref != commission_imports.source_policy_ref(db):
            raise ActionRejected('SOURCE_USE_AUTHORITY_INVALID')
        value = ContentStore._read(db, ref)['payload']
    else:
        value = store.get('source_use_authority:' + ref)
        if not value or digest(value) != ref:
            raise ActionRejected('SOURCE_USE_AUTHORITY_INVALID')
    if value.get('contract') != 'source-use-v1' or value.get('commission_binding') != _commission(store):
        raise ActionRejected('SOURCE_USE_AUTHORITY_INVALID')
    return value


def _version_policy(store, declaration, db=None):
    from .catalog import Catalog
    from .content_store import ContentStore
    if db is None:
        with store.connect() as connection:
            return _version_policy(store, declaration, connection)
    manifest = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
    available = {s['id']: s for s in Catalog.read_sources(db, manifest)}
    ids = declaration['source_ids']
    if not set(ids) <= available.keys():
        raise ActionRejected('SOURCE_NOT_IN_PROJECT')
    sources = [available[source_id] for source_id in ids]
    if any(not s.get('current', True) for s in sources):
        raise ActionRejected('SOURCE_USE_VERSION_NOT_CURRENT')
    return {'contract': 'source-use-v1', 'commission_binding': _commission(store),
              'declaration': declaration,
              'versions': [{'source_id': s['id'],
                            'source_payload_digest': digest(ContentStore.source_payload(s)),
                            'immutable_version_digest': immutable_version_digest(ContentStore.source_payload(s))} for s in sources]}


def _supplied_inputs(db):
    return [r for r in commission_imports.frozen_refs(db)
            if r['type'] in ('CommissionSourceManifest', 'CommissionSourceRoles')]


def _supplied_policy(store, db, refs):
    from .content_store import ContentStore
    declaration = store.get('manifest', {}).get('source_use')
    if declaration:
        # If preparation stopped after committing an explicit subset, it still bounds planning.
        return _version_policy(store, validate_declaration(declaration), db)
    ids = set()
    for ref in refs:
        payload = ContentStore._read(db, ref)['payload']
        if ref['type'] == 'CommissionSourceManifest':
            ids.update(item['id'] for item in payload['sources'])
        elif ref['type'] == 'CommissionSourceRoles':
            ids.update(item['id'] for item in payload.values())
    return _version_policy(store, {'source_ids': sorted(ids), 'authorization_origin': 'Supplied commission files'}, db)


def _planning_binding(store, db, *, planning=True):
    ref = commission_imports.source_policy_ref(db)
    if not ref:
        if commission_imports.requires_source_policy(db):
            if planning:
                return {'planning_inputs': _supplied_inputs(db)}
            raise ActionRejected('SOURCE_USE_OWNER_APPROVAL_REQUIRED')
        row = db.execute("SELECT value FROM state WHERE key='source_use_authority_binding'").fetchone()
        ref = json.loads(row[0]) if row else None
    if ref:
        _policy(store, ref, db)
    return ref


def report_binding(store, *, db=None, snapshot=None):
    from . import plan_authority
    from .content_store import ContentStore
    if db is None:
        with store.connect() as connection:
            return report_binding(store, db=connection, snapshot=snapshot)
    from .page_bindings import sheet_route
    selected = plan_authority.plan_ref(db)
    if selected and sheet_route(store, selected):
        pins = ({"plan": snapshot.get("commission_plan_ref"),
                 "decision": snapshot.get("commission_confirmation_ref")} if snapshot else {})
        plan_authority.confirmed_refs(db, **pins)
        return None
    if case_sources(store) is not None:
        return None
    ref = _planning_binding(store, db, planning=False)
    if isinstance(ref, dict):
        # Only a genuine, currently approved proposal can authorize these host inputs.
        pins = {}
        if snapshot is not None:
            pins = {'plan': snapshot.get('commission_plan_ref'), 'decision': snapshot.get('commission_confirmation_ref')}
            if not all(pins.values()):
                raise ActionRejected('SOURCE_USE_OWNER_APPROVAL_REQUIRED')
        try:
            plan, _ = plan_authority.confirmed_refs(db, **pins)
        except ActionRejected as error:
            raise ActionRejected('SOURCE_USE_OWNER_APPROVAL_REQUIRED') from error
        inputs = ContentStore._read(db, plan).get('plan_input_refs', [])
        scope = [r for r in commission_imports.frozen_refs(db) if r['type'] == 'CommissionSourceManifest']
        if not plan_authority.has_proposal(db, plan) or any(r not in inputs for r in [ref, *scope]):
            raise ActionRejected('SOURCE_USE_OWNER_APPROVAL_REQUIRED')
    return ref


def resolve_source_use_binding(workspace, actor):
    if actor is not None and actor.role == 'coordinator':
        from .hierarchical_tools import actor_for
        if actor != actor_for('coordinator'):
            raise ActionForbidden('FORBIDDEN: source use coordinator identity')
        with workspace.store.connect() as db:
            return _planning_binding(workspace.store, db)
    active = report_binding(workspace.store)
    if actor is None or actor.role not in {'writer', 'reviewer', 'layout'} or actor.id != 'content:' + actor.role + ':' + actor.task_id:
        if active:
            raise ActionForbidden('FORBIDDEN: source use requires actual task identity')
        return None
    from . import plan_authority
    from .page_bindings import sheet_route
    with workspace.store.connect() as db:
        selected = plan_authority.plan_ref(db)
    if selected and sheet_route(workspace.store, selected):
        from .content_tasks import bound_actor
        if bound_actor(workspace, actor.role, None) != actor:
            raise ActionForbidden('FORBIDDEN: source use requires current task binding')
        return None
    ref = workspace.store.get('source_use_task_binding:' + actor.task_id)
    if isinstance(active, dict) and active != ref:
        raise ActionForbidden('FORBIDDEN: task lacks the approved source policy')
    if active or ref:
        from .content_tasks import bound_actor
        if bound_actor(workspace, actor.role, None) != actor:
            raise ActionForbidden('FORBIDDEN: source use requires current task binding')
    if ref:
        from .content_store import ContentStore
        task = ContentStore(workspace.store).read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
        if task['payload']['role'] != actor.role:
            raise ActionForbidden('FORBIDDEN: source use task role')
        _policy(workspace.store, ref)
    return ref


def case_sources(store):
    """IDs supplied at intake or explicitly enrolled in this case's source roles."""
    from .content_store import ContentStore
    with store.connect() as db:
        refs = _supplied_inputs(db)
        ids = set()
        for ref in refs:
            payload = ContentStore._read(db, ref)["payload"]
            entries = payload["sources"] if ref["type"] == "CommissionSourceManifest" else payload.values()
            ids.update(item["id"] for item in entries)
        native = commission_imports.requires_source_policy(db)
    return ids if native else None


def check_case_sources(workspace, source_ids=(), source_refs=(), materials=()):
    """No policy or digest: file membership is the case access boundary."""
    from .content_store import ContentStore
    allowed = case_sources(workspace.store)
    if allowed is None:
        return False
    ids = set(source_ids) | {m["source_id"] for m in materials}
    for ref in source_refs:
        if ref["type"] != "SourceArtifact":
            raise ActionRejected("CASE_SOURCE_ARTIFACT_REQUIRED")
        ids.add(ContentStore(workspace.store).read(ref)["payload"]["source_id"])
    if not ids <= allowed:
        raise ActionRejected("CASE_SOURCE_NOT_SUPPLIED")
    return True


def validate_source_versions(workspace, actor, source_ids=(), source_refs=(), materials=()):
    if check_case_sources(workspace, source_ids, source_refs, materials):
        return None
    ref = resolve_source_use_binding(workspace, actor)
    if not ref:
        return None
    _check_versions(workspace, _policy(workspace.store, ref), source_ids, source_refs, materials)
    return ref


def check_source_read(workspace, actor_for_read, source_ids=(), source_refs=()):
    """Apply the M5 selection at agent read tools. An implicit search covers just its allowed IDs."""
    supplied = case_sources(workspace.store)
    if supplied is not None:
        if source_ids is None:
            source_ids = sorted(supplied)
        check_case_sources(workspace, source_ids, source_refs)
        return source_ids
    with workspace.store.connect() as db:
        if not (commission_imports.source_policy_ref(db) or commission_imports.requires_source_policy(db)):
            return None
    ref = resolve_source_use_binding(workspace, actor_for_read())
    if ref is None:
        return source_ids
    policy = _policy(workspace.store, ref)
    if source_ids is None:
        source_ids = [entry['source_id'] for entry in policy['versions']]
    _check_versions(workspace, policy, source_ids, source_refs, ())
    return source_ids


def _check_versions(workspace, policy, source_ids, source_refs, materials):
    from .content_store import ContentStore
    cs = ContentStore(workspace.store)
    eligible = {v['source_id']: v for v in policy['versions']}
    payloads = []
    for source_ref in source_refs:
        obj = cs.read(source_ref)
        if obj['ref']['type'] != 'SourceArtifact':
            raise ActionRejected('SOURCE_USE_REQUIRES_SOURCE_ARTIFACT')
        payloads.append(obj['payload'])
    ids = set(source_ids) | {m['source_id'] for m in materials} | {p['source_id'] for p in payloads}
    if not ids <= eligible.keys():
        raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')
    if not ids:
        return
    current_payloads = {s['id']: cs.source_payload(s) for s in workspace.store.sources(list(ids))}
    payloads.extend(current_payloads[i] for i in source_ids)
    # Full saved payloads are required; metadata-only compiler representations
    # cannot stand in for originals. A replacement never inherits its old ID.
    for payload in payloads:
        enrolled = eligible.get(payload['source_id'])
        current = current_payloads[payload['source_id']]
        if (not enrolled or immutable_version_digest(payload) != enrolled['immutable_version_digest']
                or digest(payload) not in {enrolled['source_payload_digest'], digest(current)}):
            raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')
    for material in materials:
        enrolled = eligible.get(material['source_id'])
        if not enrolled:
            raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')
        current = current_payloads[material['source_id']]
        if (immutable_version_digest(current) != enrolled['immutable_version_digest'] or
                material['source_payload_digest'] not in {enrolled['source_payload_digest'], digest(current)}):
            raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')


def validate_observation_sources(workspace, actor, observation):
    """Known structured receipt fields only; no prose inference or link traversal."""
    source_ids, source_refs = [], []
    for obj in observation.get('objects', []):
        if obj['ref']['type'] == 'SourceArtifact':
            source_refs.append(obj['ref'])
        elif obj['ref']['type'] == 'Evidence':
            source_refs.extend(obj['payload']['source_refs'])
    for entry in observation.get('evidence', []):
        if entry.get('kind') == 'source_blocks':
            source_ids.append(entry['selection']['source_id'])
    provenance = observation.get('source', {})
    # hierarchical_tools.observe_evidence(kind='source') issues this exact
    # character-selection shape directly into content_observations.
    if all(k in observation for k in ('source_id', 'source_digest', 'text', 'range')):
        source_ids.append(observation['source_id'])
    if provenance.get('render_ref'):
        paired = provenance.get('presentation_reference')
        if paired:
            source_ids.append(paired['source_id'])
    elif provenance.get('source_id'):
        source_ids.append(provenance['source_id'])
    elif provenance.get('id'):
        source_ids.append(provenance['id'])
    return validate_source_versions(workspace, actor, source_ids, source_refs)


def verified_source_free_calculation(workspace, actor, record):
    """Recognize the existing calculation issuer, not arbitrary empty origins."""
    if record['tool'] != 'observe_evidence':
        return False
    try:
        value = json.loads(record['text'])
    except (ValueError, TypeError):
        return False
    if (not isinstance(value, dict) or value.get('ok') is not True
            or set(value) != {'ok', 'result', 'receipt_id'}
            or not isinstance(value['result'], dict)
            or set(value['result']) != {'terms', 'result', 'tool'}
            or value['result']['tool'] != 'sum_products'):
        return False
    with workspace.store.connect() as db:
        row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                         (value['receipt_id'],)).fetchone()
    return bool(row and row[0] == actor.id and json.loads(row[1]) == value['result'])


def source_version_material(cs, source_id):
    """Freeze all physically located text in this version; chunk offsets do not start new pages."""
    from .document_tools import physical_page_number
    source, = cs.store.sources([source_id])
    version = immutable_version_digest(cs.source_payload(source))
    pages = {}
    with cs.store.connect() as db:
        for locator, text in db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal',
                                        (source_id,)):
            page = physical_page_number(locator)
            if page is not None:
                chunks = pages.setdefault(str(page), [])
                if chunks and ('; chars ' not in locator or '; chars 1-' in locator):
                    chunks.append('\n')
                chunks.append(text)
    text = {page: ''.join(chunks) for page, chunks in pages.items()}
    return version, {'pages': text, 'image_pages': [int(p) for p, value in text.items() if not value.strip()]}
