"""Versioned compatibility for pre-origin-receipt public observations only.

New source tools issue source-material-v1. This adapter preserves verifiable
historical observations without inventing a past origin receipt or re-reading.
"""
import hashlib
import json

from .content_inputs import SourceRef
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest

LEGACY_CONTRACT = 'legacy-source-return-shapes-v1'


def frozen_read_identity(workspace, actor, observation_ref, record):
    """Verify an old block read for admission only; never invent an origin receipt."""
    if record.get('owner') != actor.id or record.get('tool') != 'read_source_page':
        return None
    sha = hashlib.sha256(record['text'].encode('utf-8')).hexdigest()
    if record['sha256'] != sha or observation_ref != digest(
            {'owner':actor.id, 'tool':record['tool'], 'sha256':sha}):
        return None
    try:
        value = json.loads(record['text'])
    except (ValueError, TypeError):
        return None
    return frozen_read_materials(workspace, value)


def frozen_read_materials(workspace, value):
    """Associate only a block packet still verifiable against its original source.

    Old metadata or blocks never acquire the current source's version identity.
    Failure only withholds this additional view association, not other guards.
    """
    try:
        source_id = value['source']['id']
        source = workspace.store.sources([source_id])[0]
    except (ValueError, KeyError, IndexError, TypeError, ActionRejected):
        return None
    if not _matches(workspace, source, 'read_source_page', value, None):
        return None
    from .source_materials import block_material
    return [{**part, 'source_payload_digest':digest(ContentStore.source_payload(source))}
            for part in block_material(value)]


def _blocks_match(workspace, source, blocks):
    if not blocks or not isinstance(blocks, list):
        return False
    with workspace.store.connect() as db:
        for block in blocks:
            if not isinstance(block, dict) or type(block.get('ordinal')) is not int:
                return False
            row = db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? AND ordinal=?',
                             (source['id'], block['ordinal'])).fetchone()
            if not row or tuple(row) != (block.get('locator'), block.get('text')) or not row[1]:
                return False
    return True


def _search_match(workspace, source, match):
    if not isinstance(match, dict) or match.get('source_id') != source['id']:
        return False
    ordinals = match.get('ordinals', [match.get('ordinal')])
    if not ordinals or any(type(n) is not int for n in ordinals):
        return False
    if ordinals != list(range(ordinals[0], ordinals[0] + len(ordinals))):
        return False
    with workspace.store.connect() as db:
        rows = db.execute('SELECT ordinal,locator,text FROM source_blocks '
                          'WHERE source_id=? AND ordinal>=? AND ordinal<=? ORDER BY ordinal',
                          (source['id'], ordinals[0], ordinals[-1])).fetchall()
    if ([r[0] for r in rows] != ordinals or match.get('ordinal') != ordinals[0]
            or match.get('locators', [match.get('locator')]) != [r[1] for r in rows]):
        return False
    locator = rows[0][1] if len(rows) == 1 else rows[0][1] + ' through ' + rows[-1][1]
    text = match.get('text')
    if not isinstance(text, str) or not text or match.get('locator') != locator:
        return False
    # Search returns complete located blocks, including original separators.
    if text not in source['content'] or not text.startswith(rows[0][2]) or not text.endswith(rows[-1][2]):
        return False
    position = 0
    for _, _, block in rows:
        position = text.find(block, position)
        if position < 0:
            return False
        position += len(block)
    return True


def _has_page_material(value):
    return (bool(value.get('native_text', '').strip())
            or any(b.get('text') for b in value.get('frozen_text_blocks', []))
            or any(t.get('rows') for t in value.get('table_view', {}).get('tables', [])))


def _matches(workspace, source, tool, value, actor):
    if not isinstance(value, dict):
        return False
    if tool == 'read_source_page':
        metadata = {k: v for k, v in source.items() if k != 'content'}
        return value.get('source') == metadata and _blocks_match(workspace, source, value.get('blocks'))
    if tool == 'search_sources':
        return any(_search_match(workspace, source, m) for m in value.get('matches', []))
    if tool == 'inspect_source_page':
        return (value.get('source_id') == source['id'] and bool(source.get('sha256'))
                and value.get('sha256') == source['sha256'].lower()
                and type(value.get('page')) is int and value['page'] >= 1 and _has_page_material(value))
    if tool == 'analyze_source_image':
        provenance = value.get('source', {})
        return (value.get('status') in {'observed', 'incomplete'} and bool(value.get('observation', '').strip())
                and provenance.get('source_id') == source['id'] and bool(source.get('sha256'))
                and provenance.get('source_sha256') == source['sha256'].lower())
    if tool == 'observe_evidence':
        result = value.get('result', {})
        span = result.get('range', [])
        if (value.get('ok') is not True or result.get('source_id') != source['id']
                or result.get('source_digest') != digest(source)
                or len(span) != 2 or any(type(n) is not int for n in span)
                or not 0 <= span[0] < span[1] <= len(source['content'])
                or result.get('text') != source['content'][span[0]:span[1]]):
            return False
        with workspace.store.connect() as db:
            row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                             (value.get('receipt_id'),)).fetchone()
        return bool(row and row[0] == actor.id and json.loads(row[1]) == result)
    return False


def legacy_materials(workspace, actor, observation_ref, record, source_refs):
    if not actor or record['owner'] != actor.id:
        raise ActionForbidden('FORBIDDEN: source binding observation owner')
    sha = hashlib.sha256(record['text'].encode('utf-8')).hexdigest()
    if (sha != record['sha256'] or observation_ref != digest(
            {'owner':actor.id,'tool':record['tool'],'sha256':sha})):
        raise ActionRejected('TEXT_WORK_SOURCE_OBSERVATION_INTEGRITY_CHANGED')
    try:
        value = json.loads(record['text'])
    except ValueError:
        return []
    cs = ContentStore(workspace.store)
    materials = []
    for ref in source_refs:
        obj = cs.read(SourceRef.model_validate(ref).model_dump())
        source = workspace.store.sources([obj['payload']['source_id']])[0]
        if _matches(workspace,source,record['tool'],value,actor):
            materials.append({'source_id':source['id'],
                'source_payload_digest':digest(cs.source_payload(source)),
                'kind':LEGACY_CONTRACT+':'+record['tool'],
                'limitations':['Historical public shape verified; no origin receipt existed. '
                    'Interpretation/partial observations are not original facts or complete reading.']})
    return materials
