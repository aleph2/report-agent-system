"""Host-recorded exact source-use versions, shared by actual material consumers.

This is not source discovery, relevance selection, or an Agent grant tool.
"""
import json

from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


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


def _policy(store, ref):
    value = store.get('source_use_authority:' + ref)
    if (not value or digest(value) != ref or value.get('contract') != 'source-use-v1'
            or value.get('commission_binding') != _commission(store)):
        raise ActionRejected('SOURCE_USE_AUTHORITY_INVALID')
    return value


def configure_source_use(store, source_ids, authorization_origin):
    """Trusted host API. Same declaration is idempotent, never re-enrolls versions."""
    declaration = validate_declaration(dict(source_ids=source_ids, authorization_origin=authorization_origin))
    prior = store.get('source_use_authority_binding')
    if prior:
        policy = _policy(store, prior)
        if policy['declaration'] != declaration:
            raise ActionRejected('SOURCE_USE_AUTHORITY_IMMUTABLE')
        return prior
    from .content_store import ContentStore
    sources = store.sources(declaration['source_ids'])
    if any(not s.get('current', True) for s in sources):
        raise ActionRejected('SOURCE_USE_VERSION_NOT_CURRENT')
    policy = {'contract': 'source-use-v1', 'commission_binding': _commission(store),
              'declaration': declaration,
              'versions': [{'source_id': s['id'],
                            'source_payload_digest': digest(ContentStore.source_payload(s)),
                            'immutable_version_digest': immutable_version_digest(ContentStore.source_payload(s))} for s in sources]}
    ref = digest(policy)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM state WHERE key='source_use_authority_binding'").fetchone()
        if row and json.loads(row[0]) != ref:
            raise ActionRejected('SOURCE_USE_AUTHORITY_IMMUTABLE')
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)', ('source_use_authority:' + ref, encode(policy)))
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)', ('source_use_authority_binding', encode(ref)))
    return ref


def report_binding(store):
    ref = store.get('source_use_authority_binding')
    if ref:
        _policy(store, ref)
    elif store.manifest.get('source_use') is not None:
        raise ActionRejected('SOURCE_USE_DECLARED_BUT_UNBOUND')
    return ref


def resolve_source_use_binding(workspace, actor):
    active = report_binding(workspace.store)
    if actor is None:
        if active:
            raise ActionForbidden('FORBIDDEN: source use requires actual actor')
        return None
    if actor.role == 'coordinator':
        from .hierarchical_tools import actor_for
        if actor != actor_for('coordinator'):
            raise ActionForbidden('FORBIDDEN: source use coordinator identity')
        return active
    if actor.role not in {'writer', 'reviewer', 'layout'} or actor.id != 'content:' + actor.role + ':' + actor.task_id:
        if active:
            raise ActionForbidden('FORBIDDEN: source use task identity')
        return None
    ref = workspace.store.get('source_use_task_binding:' + actor.task_id)
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
    return ref  # Missing legacy task binding never inherits a later report grant.


def validate_source_versions(workspace, actor, source_ids=(), source_refs=(), materials=()):
    ref = resolve_source_use_binding(workspace, actor)
    if not ref:
        return None
    from .content_store import ContentStore
    cs = ContentStore(workspace.store)
    policy = _policy(workspace.store, ref)
    eligible = {v['source_id']: v for v in policy['versions']}
    payloads = [cs.source_payload(s) for s in workspace.store.sources(list(source_ids))]
    for source_ref in source_refs:
        obj = cs.read(source_ref)
        if obj['ref']['type'] != 'SourceArtifact':
            raise ActionRejected('SOURCE_USE_REQUIRES_SOURCE_ARTIFACT')
        payloads.append(obj['payload'])
    # Full saved payloads are required; metadata-only compiler representations
    # cannot stand in for originals. A replacement never inherits its old ID.
    for payload in payloads:
        enrolled = eligible.get(payload['source_id'])
        current = cs.source_payload(workspace.store.sources([payload['source_id']])[0])
        if (not enrolled or immutable_version_digest(payload) != enrolled['immutable_version_digest']
                or digest(payload) not in {enrolled['source_payload_digest'], digest(current)}):
            raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')
    for material in materials:
        enrolled = eligible.get(material['source_id'])
        if not enrolled:
            raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')
        current = cs.source_payload(workspace.store.sources([material['source_id']])[0])
        if (immutable_version_digest(current) != enrolled['immutable_version_digest'] or
                material['source_payload_digest'] not in {enrolled['source_payload_digest'], digest(current)}):
            raise ActionRejected('SOURCE_USE_VERSION_NOT_AUTHORIZED')
    return ref


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
