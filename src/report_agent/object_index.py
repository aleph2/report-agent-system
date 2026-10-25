"""Paged literal metadata before or after a snapshot; no content selection policy."""
import json
from collections import Counter

from .errors import ActionRejected
from .store import digest, encode


def object_index(contents, offset=0, limit=20, object_type='', owner_id='',
                 current_only=False, inventory_digest=''):
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 20:
        raise ActionRejected('INVALID_OBJECT_INDEX_PAGE: offset>=0, limit=1..20')
    if offset and not inventory_digest:
        raise ActionRejected('OBJECT_INDEX_DIGEST_REQUIRED: use the first page inventory_digest')
    # One SQLite read snapshot keeps versions and heads coherent. No writes,
    # observation receipts, inferred roots or automatic descendants are produced.
    with contents.store.connect() as db:
        db.execute('BEGIN')
        rows = db.execute('SELECT data FROM content_versions ORDER BY rowid').fetchall()
        heads = {(r[0], r[1]): r[2] for r in db.execute('SELECT type,id,version FROM content_heads')}
    records = [json.loads(r[0]) for r in rows]
    available_types = dict(Counter(r['ref']['type'] for r in records))
    selected = [r for r in records
                if (not object_type or r['ref']['type'] == object_type)
                and (not owner_id or r['owner_id'] == owner_id)
                and (not current_only or r['ref']['version'] == heads[(r['ref']['type'], r['ref']['id'])])]
    filters = {'object_type': object_type, 'owner_id': owner_id, 'current_only': current_only}
    # The continuation cursor binds this filtered inventory. Global type counts
    # are auxiliary discovery metadata, not members of the selected page set.
    fingerprint = digest({'filters': filters, 'objects': [
        {'ref': r['ref'], 'payload_digest': r['payload_digest'],
         'owner_id': r['owner_id'], 'task_id': r['task_id'],
         'head_version': heads[(r['ref']['type'], r['ref']['id'])]} for r in selected]})
    if inventory_digest and inventory_digest != fingerprint:
        raise ActionRejected('OBJECT_INDEX_CHANGED: restart at offset=0 without inventory_digest; do not combine pages')
    if offset > len(selected):
        raise ActionRejected('OBJECT_INDEX_OFFSET_OUT_OF_RANGE')
    result = {'inventory_digest': fingerprint, 'filters': filters,
              'total': len(selected), 'offset': offset, 'next_offset': None,
              'objects': [], 'available_types': available_types,
              'scope_note': 'Exact project metadata in creation order, not report order or review. '
                  'Read chosen refs with read_context. Pagination may return fewer than limit; use next_offset '
                  'and the same filters/inventory_digest. The digest binds selected objects, heads, ownership '
                  'and task metadata. available_types is a current project-wide discovery count and may '
                  'change independently between filtered pages. No bodies or implicit selection.'}
    for record in selected[offset:offset + limit]:
        entry = {k: record[k] for k in ('ref', 'previous_ref', 'owner_id', 'task_id', 'payload_digest')}
        entry['is_current'] = record['ref']['version'] == heads[(record['ref']['type'], record['ref']['id'])]
        payload = record['payload']
        if record['ref']['type'] == 'ContentNode':
            body = payload['body']
            title = str(body.get('text', body.get('title', ''))).split('\n', 1)[0]
            entry.update(kind=payload['kind'], claim_kind=payload['claim_kind'],
                         title_preview=title[:80], title_truncated=len(title) > 80)
        elif record['ref']['type'] == 'Relation':
            entry.update({k: payload[k] for k in ('subject_ref', 'object_ref', 'predicate', 'position') if k in payload})
        result['objects'].append(entry)
        end = offset + len(result['objects'])
        result['next_offset'] = end if end < len(selected) else None
        # Complete identities are never shortened or split over JSON fragments.
        if len(encode(result)) > 5800:
            result['objects'].pop()
            if not result['objects']:
                raise ActionRejected('OBJECT_INDEX_METADATA_ENTRY_TOO_LARGE')
            result['next_offset'] = offset + len(result['objects'])
            break
    return result


def status_metadata(value):
    """Discoverable index from a status observation, not a fresh-state claim."""
    objects = value.get('objects', [])
    return {'inventory_representation': 'paged-object-index-v1',
            'observed_object_count': len(objects),
            'observed_types': dict(Counter(o['ref']['type'] for o in objects)),
            'object_metadata_tool': 'read_object_index',
            'navigation_note': 'Use read_object_index for whole identity records before or after snapshot creation. '
                'This status is historical; the index reads current project metadata. '
                'No object body, evidence reading or semantic acceptance is implied.'}
