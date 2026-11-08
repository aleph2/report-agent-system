"""System-bound slope pages; navigation candidates do not establish engineering relevance."""
from . import legacy_state as legacy
import base64
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import re
import unicodedata
from uuid import uuid4

from .errors import ActionForbidden, ActionRejected
from .store import digest


def _catalog_source(cs, db, source_id):
    source = next((s for s in cs.store.manifest['sources'] if s['id'] == source_id), None)
    if source is None:
        row = db.execute('SELECT data FROM source_versions WHERE id=?', (source_id,)).fetchone()
        source = json.loads(row[0]) if row else None
    if source is None:
        raise ActionRejected('WRITER_SOURCE_NOT_IN_PROJECT')
    if source.get('id') != source_id:
        raise ActionRejected('WRITER_SOURCE_CHANGED')
    return source


def _pin(cs, db, ref):
    record = cs._read(db, ref)
    if ref['type'] != 'SourceArtifact':
        raise ActionRejected('WRITER_SOURCE_ARTIFACT_REQUIRED')
    payload = record['payload']
    source = _catalog_source(cs, db, payload['source_id'])
    actual_digest = source.get('sha256') or digest(source['content'])
    if actual_digest != payload['file_digest'] or source['content'] != payload['content']:
        raise ActionRejected('WRITER_SOURCE_CHANGED')
    return record, digest([payload['source_id'], payload['file_digest'], payload['content']])


def bound_assignment(cs, db, actor):
    from .commission_plan import assert_writing_allowed, _confirmed, _citations, outside_boundary
    from .deliverables import source_authority
    plan = assert_writing_allowed(cs, db, actor)
    if plan is None:
        raise ActionRejected('WRITER_CONFIRMED_PLAN_REQUIRED')
    task_ref = {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1}
    task = cs._read(db, task_ref)
    if (actor.role != 'writer' or task['owner_id'] != 'content:coordinator'
            or task['payload'].get('delegated_by') != task['owner_id']):
        raise ActionForbidden('FORBIDDEN: writer assignment owner')
    object_id = task['payload'].get('assessment_object_id')
    obj = next((o for o in plan['payload']['objects'] if o['object_id'] == object_id), None)
    sections = task['payload'].get('section_ids', [])
    section = next((s for s in plan['payload']['sections'] if len(sections) == 1 and s['section_id'] == sections[0]), None)
    _, decision = _confirmed(cs, db)
    reduced = {r['object_id'] for r in decision['payload'].get('reductions', [])}
    if (obj is None or not obj['included'] or section is None or section['kind'] != 'extracted'
            or outside_boundary(plan['payload'], obj) or object_id in reduced):
        raise ActionRejected('WRITER_SINGLE_OBJECT_ASSIGNMENT_REQUIRED')
    pack = plan['payload'].get('method_pack')
    if not pack:
        raise ActionRejected('WRITER_CONFIRMED_METHOD_REQUIRED')
    citations = [*section['sources'], *list(_citations(obj)), *pack['sources']]
    sources, records, pins, seen = [], [], [], set()
    for citation in citations:
        ref = citation['source_ref']
        record, pin = _pin(cs, db, ref)
        records.append(record)
        if pin not in seen:
            seen.add(pin); sources.append(deepcopy(ref)); pins.append(pin)
    source_authority(cs, db, actor, records)
    identity = digest([task_ref, plan['ref'], decision['ref'], object_id, sections[0], list(zip(sources, pins))])
    return {'plan': plan, 'decision': decision, 'object': obj, 'section_id': sections[0], 'sources': sources,
            'task_ref': task_ref, 'assignment_digest': identity}


def _chainages(text):
    text = unicodedata.normalize('NFKC', text)
    values = set()
    for match in re.finditer(r'(?<![A-Za-z0-9])K\s*(\d+)\s*[+p]\s*(\d+(?:\.\d+)?)(?:\s*\+\s*(\d+(?:\.\d+)?))?', text, re.I):
        km, metres, offset = match.groups()
        if Decimal(metres) < 1000:
            values.add(Decimal(km) * 1000 + Decimal(metres) + Decimal(offset or '0'))
    return sorted(values)


def _object_stations(obj):
    labels = [obj['label'], obj['object_id']]
    labels += [v['value'] for attribute in obj.get('attributes', [])
               if re.search('mileage|chainage|里程|桩号', attribute['name'], re.I)
               for v in attribute['values'] if isinstance(v.get('value'), str)]
    return sorted({value for label in labels for value in _chainages(label)})


def _matches(text, stations):
    values = _chainages(text)
    return any((stations[0] <= value <= stations[1] if len(stations) == 2 else value in stations)
               for value in values)


def _index(cs, db, bound):
    from .document_tools import physical_page_number
    from .source_tables import source_tables
    from .workspace import Workspace
    stations = _object_stations(bound['object'])
    from .commission_plan import _citations
    inventory = list(_citations(bound['object']))
    entries = []
    for number, ref in enumerate(bound['sources'], 1):
        payload = cs._read(db, ref)['payload']; source_id = payload['source_id']
        rows = db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal', (source_id,)).fetchall()
        pages = {}
        def add(page, reason, locator=None):
            row = pages.setdefault(page, {'page': page, 'reasons': [], 'locators': [], 'table_rows': [], 'row_status': 'not_checked'})
            if reason not in row['reasons']: row['reasons'].append(reason)
            if locator and locator not in row['locators']: row['locators'].append(locator)
        source_pin = _pin(cs, db, ref)[1]
        for citation in inventory:
            if _pin(cs, db, citation['source_ref'])[1] != source_pin:
                continue
            page = physical_page_number(citation['locator'])
            if page:
                add(page, 'inventory_citation', citation['locator'])
        for locator, text in rows:
            page = physical_page_number(locator)
            if page and stations and _matches(text, stations):
                add(page, 'chainage_interval_hit' if len(stations) == 2 else 'chainage_hit', locator)
        if pages:
            for view in source_tables(Workspace(cs.store), source_id, sorted(pages)):
                row = pages[view['page']]
                for table in view.get('tables', []):
                    for row_number, cells in enumerate(table.get('rows', []), 1):
                        if stations and _matches(' '.join(str(cell or '') for cell in cells), stations):
                            row['table_rows'].append({'table': table['table'], 'row': row_number})
                count = len(row['table_rows'])
                row['row_status'] = ('ambiguous_candidates' if count > 1 else 'unique_candidate' if count else
                                     'no_matching_row' if view.get('status') == 'extracted' else 'table_view_unavailable')
        entries.append({'source_ref': ref, 'source_pin': source_pin, 'source_handle': 'source-' + str(number),
                        'title': payload['source_metadata'].get('title') or 'Source ' + str(number),
                        'pages': [pages[p] for p in sorted(pages)],
                        'status': 'page_candidates' if pages else 'physical_pages_unresolved'})
    return {'assignment_digest': bound['assignment_digest'], 'sources': entries,
            'limitations': ['Page/row hits are navigation candidates, not relevance or evidence-sufficiency judgments.',
                           'Hints are not a whitelist: any original page of an authorized source can be read.',
                           'Unlocated or image-only extraction does not establish absent information.',
                           *(['Drawing-page discovery has no unique approved chainage interval.'] if len(stations) != 2 else [])]}


def _cached_index(cs, db, bound):
    from .commission_plan import _state
    index = _state(db, 'writer_assignment_pages:' + bound['assignment_digest'])
    if index is None:
        return None
    expected = [(ref, _pin(cs, db, ref)[1], 'source-' + str(n)) for n, ref in enumerate(bound['sources'], 1)]
    try:
        actual = [(source['source_ref'], source['source_pin'], source['source_handle']) for source in index['sources']]
        valid = index['assignment_digest'] == bound['assignment_digest'] and actual == expected
    except (KeyError, TypeError):
        valid = False
    if not valid:
        raise ActionRejected('WRITER_ASSIGNMENT_INDEX_CHANGED')
    return index


def prepare_assignment_pages(cs, actor):
    from .commission_plan import _set
    with cs.store.connect() as db:
        bound = bound_assignment(cs, db, actor)
        key = 'writer_assignment_pages:' + bound['assignment_digest']
        index = _cached_index(cs, db, bound)
        if index is None:
            index = _index(cs, db, bound)
            _set(db, key, index)
    public = deepcopy(index)
    for source in public['sources']:
        source.pop('source_ref'); source.pop('source_pin')
    public['index_digest'] = digest(index)
    return public


def read_assignment_pages(cs, actor):
    return prepare_assignment_pages(cs, actor)


def _prepared(cs, db, actor):
    bound = bound_assignment(cs, db, actor)
    index = _cached_index(cs, db, bound)
    if index is None:
        raise ActionRejected('WRITER_ASSIGNMENT_PAGE_INDEX_REQUIRED')
    return bound, index


def read_assigned_page(cs, actor, source_handle, page, *, include_image=True):
    from .commission_plan import _set
    from .document_tools import source_page_info, source_page_png
    from .workspace import Workspace
    prepare_assignment_pages(cs, actor)
    with cs.store.connect() as db:
        bound, index = _prepared(cs, db, actor)
        source = next((s for s in index['sources'] if s['source_handle'] == source_handle), None)
        if source is None:
            raise ActionRejected('WRITER_SOURCE_HANDLE_UNKNOWN')
        record, pin = _pin(cs, db, source['source_ref'])
    result = source_page_info(Workspace(cs.store), record['payload']['source_id'], page)
    if result['sha256'] != record['payload']['file_digest']:
        raise ActionRejected('WRITER_SOURCE_CHANGED')
    if not include_image:
        from .source_tables import source_tables
        tables = source_tables(Workspace(cs.store), record['payload']['source_id'], [page])
        with cs.store.connect() as db:
            current = bound_assignment(cs, db, actor)
            if current['assignment_digest'] != bound['assignment_digest']:
                raise ActionRejected('WRITER_ASSIGNMENT_CHANGED_DURING_READ')
        return {**result, 'table_view': tables[0],
            'visual_evidence': 'SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE',
            'limitation': 'Native page text and mechanical table geometry only. The configured Writer is text-only; drawing-only evidence remains unverified, not absent.'}
    pixels = source_page_png(Workspace(cs.store), record['payload']['source_id'], page)
    image_sha256 = hashlib.sha256(pixels).hexdigest()
    handle = 'page-' + uuid4().hex
    receipt = {'actor': actor.__dict__, 'assignment_digest': bound['assignment_digest'],
               'source_ref': source['source_ref'], 'source_pin': pin, 'page': page,
               'image_sha256': image_sha256, 'image_delivered': False}
    with cs.store.connect() as db:
        current = bound_assignment(cs, db, actor)
        if current['assignment_digest'] != bound['assignment_digest']:
            raise ActionRejected('WRITER_ASSIGNMENT_CHANGED_DURING_READ')
        legacy.set_writer_page_read(db, handle, receipt)
    return {**result, 'page_handle': handle, 'image_sha256': image_sha256,
            'image_data_url': 'data:image/png;base64,' + base64.b64encode(pixels).decode('ascii')}


def _page_receipt(cs, db, actor, handle):
    from .commission_plan import _state
    bound = bound_assignment(cs, db, actor)
    receipt = legacy.get_writer_page_read(db, handle)
    if (not receipt or receipt.get('actor') != actor.__dict__
            or receipt.get('assignment_digest') != bound['assignment_digest']):
        raise ActionForbidden('FORBIDDEN: writer visual page receipt')
    _, pin = _pin(cs, db, receipt['source_ref'])
    if pin != receipt['source_pin']:
        raise ActionRejected('WRITER_SOURCE_CHANGED')
    return receipt


def mark_visual_page_delivered(cs, actor, page_handle, image_sha256):
    """Host-only: native wrapper calls after constructing an actual image block, not a JSON reference."""
    from .commission_plan import _set
    with cs.store.connect() as db:
        receipt = _page_receipt(cs, db, actor, page_handle)
        if receipt['image_sha256'] != image_sha256:
            raise ActionRejected('WRITER_VISUAL_IMAGE_DIGEST_MISMATCH')
        legacy.set_writer_page_read(db, page_handle, {**receipt, 'image_delivered': True})


def resolve_visual_pages(cs, db, actor, handles):
    citations = []
    for handle in dict.fromkeys(handles):
        receipt = _page_receipt(cs, db, actor, handle)
        if not receipt['image_delivered']:
            raise ActionRejected('WRITER_VISUAL_PAGE_NOT_DELIVERED')
        citations.append({'source_ref': receipt['source_ref'], 'locator': 'page ' + str(receipt['page']), 'quote': ''})
    return citations


def page_view(result, view='text'):
    """Project one returned page without changing its source or read authority."""
    if view not in ('text', 'native_text', 'tables'):
        raise ActionRejected('WRITER_PAGE_VIEW_INVALID')
    blocks = result.get('frozen_text_blocks') or []
    native = result.get('native_text') or ''
    frozen_available = any(block['text'].strip() for block in blocks)
    public = deepcopy({key: result[key] for key in (
        'source_handle', 'page', 'page_count', 'locator', 'page_handle',
        'status', 'coverage', 'text_coverage', 'native_text_coverage',
        'frozen_text_coverage', 'visual_evidence', 'limitations', 'limitation',
        'frozen_text_note') if key in result})
    public.update(view=view, text_channels={
        'frozen_text_blocks': ('available' if frozen_available else
                              'empty' if 'frozen_text_blocks' in result else 'unavailable'),
        'native_text': ('available' if native.strip() else
                        'empty' if 'native_text' in result else 'unavailable')})
    tables = result.get('table_view') or {}
    public['table_status'] = tables.get('status', 'unavailable')
    if view == 'tables':
        public['table_view'] = deepcopy({key: tables[key] for key in (
            'status', 'error', 'derived', 'extractor', 'page', 'page_count',
            'locator', 'coverage', 'limitations', 'limitation') if key in tables})
        public['table_view'].setdefault('status', 'unavailable')
        public['table_view']['tables'] = [
            {'table': table['table'], 'rows': deepcopy(table['rows'])}
            for table in tables.get('tables', [])]
    else:
        channel = 'frozen_text_blocks' if view == 'text' and frozen_available else 'native_text'
        public['text_channel'] = channel
        public[channel] = deepcopy(blocks if channel == 'frozen_text_blocks' else native)
    return public
