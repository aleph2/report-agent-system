"""Source-owned commission anchors and one authority check, independent of plans."""
from . import legacy_state as legacy
from io import BytesIO
import re
from typing import Literal

from pydantic import Field

from .content_models import Contract, Ref
from .content_store import Actor
from .errors import ActionForbidden, ActionRejected
from .store import Store, digest

CONTRACT = 'commission-requirements-v1'
Capability = Literal['method_pack', 'weight_binding', 'table_specs', 'scope_boundary',
    'inventory_reconciliation', 'section', 'fixed_text', 'result_bindings', 'inventory',
    'deliverables', 'material_issues', 'source_priority', 'assumptions']


class RequirementItem(Contract):
    anchor_id: str = Field(min_length=1)
    status: Literal['required', 'not_applicable', 'unresolved']
    interpretation: str = Field(min_length=1)
    capabilities: list[Capability]
    table_roles: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    reviewed_entry_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


def enabled(store):
    from .handoff_release import manifest
    value = manifest(store).get('commission_requirements_contract')
    if value not in (None, CONTRACT):
        raise ActionRejected('UNKNOWN_COMMISSION_REQUIREMENTS_CONTRACT')
    return value == CONTRACT


def _source(cs, ref):
    if ref is None:
        return None
    if Ref.model_validate(ref).type != 'SourceArtifact':
        raise ActionRejected('COMMISSION_REQUIREMENTS_SOURCE_REQUIRED')
    return cs.read(ref)['payload']


def _blocks(cs, source):
    with cs.store.connect() as db:
        return list(db.execute('SELECT ordinal,locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal',
                              (source['source_id'],)))


def _citation(ref, rows, text, locator=None):
    matching = [row for row in rows if (locator is None or row[1].split('; chars ')[0] == locator)
                and text in row[2]]
    if not matching:
        raise ActionRejected('COMMISSION_ANCHOR_TEXT_NOT_LOCATED')
    return {'source_ref': ref, 'locator': matching[0][1], 'quote': text}


def _anchor(kind, citation, **extra):
    value = {'kind': kind, 'source': citation, **extra}
    return {'id': digest(value), **value}


def _word_paragraphs(data):
    """Read actual styles and decimal numbering; unsupported numbering stays explicit."""
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(BytesIO(data))
    numbering = doc.part.numbering_part.element
    counters = {}
    for ordinal, paragraph in enumerate(doc.paragraphs, 1):
        text = paragraph.text
        if not text.strip():
            continue
        properties = [paragraph._p.pPr]
        style, seen = paragraph.style, set()
        while style is not None and style.style_id not in seen:
            seen.add(style.style_id)
            properties.append(style.element.pPr)
            style = style.base_style
        def prop(name):
            return next((p.find(qn('w:' + name)) for p in properties
                         if p is not None and p.find(qn('w:' + name)) is not None), None)
        level = prop('outlineLvl')
        heading = level is not None and int(level.get(qn('w:val'))) < 9
        if not heading:
            heading = bool(re.match(r'heading\s+[1-9]$', paragraph.style.name, re.I))
        number, error = None, None
        num = prop('numPr')
        if heading and num is not None:
            numid, ilvl = num.find(qn('w:numId')), num.find(qn('w:ilvl'))
            if numid is not None and numid.get(qn('w:val')) != '0':
                identity = numid.get(qn('w:val'))
                depth = int(ilvl.get(qn('w:val'))) if ilvl is not None else 0
                definition = next((n for n in numbering.findall(qn('w:num'))
                                   if n.get(qn('w:numId')) == identity), None)
                abstract_id = definition.find(qn('w:abstractNumId')) if definition is not None else None
                abstract = next((n for n in numbering.findall(qn('w:abstractNum'))
                    if abstract_id is not None and n.get(qn('w:abstractNumId')) == abstract_id.get(qn('w:val'))), None)
                levels = {int(n.get(qn('w:ilvl'))): n for n in abstract.findall(qn('w:lvl'))} if abstract is not None else {}
                if (depth not in levels or any(levels.get(i) is None for i in range(depth + 1))
                        or definition.findall(qn('w:lvlOverride'))):
                    error = 'Unsupported or incomplete Word numbering definition'
                else:
                    counts = counters.setdefault(identity, {})
                    for i in range(depth + 1):
                        fmt = levels[i].find(qn('w:numFmt'))
                        if fmt is None or fmt.get(qn('w:val')) != 'decimal':
                            error = 'Only unambiguous decimal outline numbering is currently supported'
                        start = levels[i].find(qn('w:start'))
                        initial = int(start.get(qn('w:val'))) if start is not None else 1
                        counts[i] = counts.get(i, initial - 1) + 1 if i == depth else counts.get(i, initial)
                    for i in list(counts):
                        if i > depth:
                            del counts[i]
                    number = '.'.join(str(counts[i]) for i in range(depth + 1))
        yield ordinal, text, heading, number, error


def extract_anchors(cs, scope_ref, outline_ref):
    """Enumerate customer structure, never infer the required engineering method."""
    from .document_tools import _original
    from .workspace import Workspace
    from markdown_it import MarkdownIt
    scope = _source(cs, scope_ref)
    if scope is None:
        raise ActionRejected('COMMISSION_SCOPE_SOURCE_REQUIRED')
    rows = _blocks(cs, scope)
    metadata, original = _original(Workspace(cs.store), scope['source_id'])
    if metadata['sha256'] != scope['file_digest']:
        raise ActionRejected('COMMISSION_REQUIREMENTS_SOURCE_PIN_MISMATCH')
    text = original.decode('utf-8-sig')
    # The flattened catalog inserts separators; parse original Markdown line numbers.
    lines = text.splitlines()
    tokens = MarkdownIt('commonmark').parse(text)
    headings = []
    for index, token in enumerate(tokens):
        if token.type == 'heading_open' and token.map:
            title = tokens[index + 1].content
            match = re.match(r'\s*([0-9]+)(?![0-9]|\.[0-9])', title)
            headings.append((token.map[0], token.map[1], match[1] if match else None, int(token.tag[1:])))
    result = []
    for start, body, number, level in headings:
        end = next((h[0] for h in headings if h[0] > start and h[3] <= level), len(lines))
        if number in ('1', '4'):
            for index, line in enumerate(lines[body:end], body):
                if line.strip():
                    result.append(_anchor('scope', _citation(scope_ref, rows, line, f'line {index + 1}'), scope_section=number))
        if number == '5':
            entries = [t for t in tokens if t.type == 'list_item_open' and t.map
                       and body <= t.map[0] < end
                       and re.match(r'\s*\d+[.)]\s+', lines[t.map[0]])]
            for entry in entries:
                first, last = entry.map
                citations = [_citation(scope_ref, rows, line, f'line {index + 1}')
                             for index, line in enumerate(lines[first:last], first) if line.strip()]
                result.append(_anchor('convention', citations[0], continuations=citations[1:]))
    for number in ('1', '4', '5'):
        if not any(a['kind'] == ('convention' if number == '5' else 'scope')
                   and (number == '5' or a.get('scope_section') == number) for a in result):
            cite = {'source_ref': scope_ref, 'locator': rows[0][1] if rows else 'document',
                    'quote': rows[0][2] if rows else ''}
            result.append(_anchor('instruction', cite, parse_error=f'Scope section {number} is missing or not parseable'))
    if outline_ref is None:
        result.append(_anchor('instruction', result[0]['source'], parse_error='Outline source is missing'))
        return result
    outline = _source(cs, outline_ref)
    outline_rows = _blocks(cs, outline)
    try:
        metadata, data = _original(Workspace(cs.store), outline['source_id'])
        if metadata['sha256'] != outline['file_digest']:
            raise ActionRejected('COMMISSION_REQUIREMENTS_SOURCE_PIN_MISMATCH')
        paragraphs = list(_word_paragraphs(data))
    except (ActionRejected, ValueError, KeyError) as exc:
        cite = {'source_ref': outline_ref, 'locator': outline_rows[0][1] if outline_rows else 'document',
                'quote': outline_rows[0][2] if outline_rows else ''}
        result.append(_anchor('instruction', cite, parse_error='Outline structure unavailable: ' + str(exc)))
        return result
    section_id = None
    for ordinal, value, heading, automatic_number, error in paragraphs:
        citation = _citation(outline_ref, outline_rows, value, f'body/paragraph {ordinal}')
        if heading:
            literal = re.match(r'\s*(\d+(?:\.\d+)*)(?:[.、)]?)(?=\s|[^\d.])', value)
            section_id = automatic_number or (literal[1] if literal else f'heading-{ordinal}')
            result.append(_anchor('section', citation, section_id=section_id,
                                  **({'parse_error': error} if error else {})))
        else:
            result.append(_anchor('instruction', citation, **({'section_id': section_id} if section_id else {})))
    # shortcut: table-contained outlines need structural support before they can be approved.
    for _, locator, value in outline_rows:
        if locator.startswith('body/table ') and value.strip():
            result.append(_anchor('instruction', {'source_ref': outline_ref, 'locator': locator, 'quote': value},
                                  parse_error='Table-contained outline text requires structural review'))
    sections = [a['section_id'] for a in result if a['kind'] == 'section']
    if not sections or len(sections) != len(set(sections)):
        result.append(_anchor('instruction', result[-1]['source'], parse_error='Outline headings missing or duplicated'))
    return result


def requirements_ref(storage, default=None):
    """Select a host-prepared version, a published interpretation, or an owner's answer."""
    from . import commission_assertions, plan_authority
    if isinstance(storage, Store):
        with storage.connect() as db:
            return requirements_ref(db, default)
    db = storage
    historical = (legacy.get_commission_requirements(db)
                  or plan_authority.imported_historical_ref(db, 'CommissionRequirements'))
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_versions'").fetchone():
        return historical or default
    published = None
    rows = db.execute("""SELECT id,version,json_extract(data,'$.owner_id') FROM content_versions
                         WHERE type='CommissionRequirements' ORDER BY version DESC""")
    for identity, version, owner in rows:
        ref = {'type': 'CommissionRequirements', 'id': identity, 'version': version}
        if ref == historical or owner == 'host':
            return ref
        if published is None:
            published = commission_assertions.requirements_results(db)
        if (identity, version) in published:
            return ref
    return historical or default


def save_revision(cs, db, actor, previous, payload):
    # An independently committed version can await publication. Never reuse its number.
    version = db.execute("SELECT max(version) FROM content_versions WHERE type=? AND id=?",
                         (previous['type'], previous['id'])).fetchone()[0] + 1
    return cs._insert(db, actor, 'CommissionRequirements', payload, id=previous['id'],
                      version=version, previous_ref=previous)


def publish_interpretation(cs, actor, operation_id, ref):
    from .commission_assertions import record_interpretation
    if cs.read(ref)['owner_id'] == actor.id:
        record_interpretation(cs.store, actor, operation_id, ref)


def read_requirements(cs, ref=None, *, db=None):
    if db is None:
        with cs.store.connect() as connection:
            return read_requirements(cs, ref, db=connection)
    ref = ref or requirements_ref(db)
    if not ref:
        raise ActionRejected('COMMISSION_REQUIREMENTS_REQUIRED')
    if Ref.model_validate(ref).type != 'CommissionRequirements':
        raise ActionRejected('COMMISSION_REQUIREMENTS_REF_INVALID')
    return cs._read(db, ref)


def install_requirements(cs, scope_ref, outline_ref):
    """Trusted preparation entry, never a model tool. No plan is seeded."""
    from .commission_plan import _state, _set
    anchors = extract_anchors(cs, scope_ref, outline_ref)
    refs = [r for r in (scope_ref, outline_ref) if r]
    pins = [{'ref': r, 'file_digest': _source(cs, r)['file_digest']} for r in refs]
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old = requirements_ref(db)
        if old:
            payload = cs._read(db, old)['payload']
            if payload['source_pins'] != pins or payload['anchors'] != anchors:
                raise ActionRejected('COMMISSION_REQUIREMENTS_SOURCES_CHANGED')
            return old
        payload = {'contract': CONTRACT, 'source_pins': pins, 'anchors': anchors,
            'items': [{'anchor_id': a['id'], 'status': 'unresolved',
                       'interpretation': 'Awaiting source-linked interpretation', 'capabilities': []} for a in anchors]}
        ref = cs._insert(db, Actor('host', 'host', 'commission-requirements'), 'CommissionRequirements', payload)
        _set(db, 'manifest', {**_state(db, 'manifest'), 'commission_requirements_contract': CONTRACT})
        return ref


def _write_items(cs, db, actor, previous, items, *, relink_anchor=None):
    from .commission_planning import classified_item
    previous_ref = previous['ref']
    if requirements_ref(db) != previous_ref:
        raise ActionRejected('COMMISSION_REQUIREMENTS_VERSION_STALE')
    items = [RequirementItem.model_validate(i).model_dump() for i in items]
    old = {i['anchor_id']: i for i in previous['payload']['items']}
    for item in items:
        before = old.get(item['anchor_id'], {}).get('reviewed_entry_id')
        if item['anchor_id'] != relink_anchor and before != item.get('reviewed_entry_id'):
            raise ActionRejected('COMMISSION_REQUIREMENTS_EXPLICIT_LINK_REQUIRED')
    items = [classified_item(cs, db, previous, item) for item in items]
    anchors = {a['id']: a for a in previous['payload']['anchors']}
    ids = [i['anchor_id'] for i in items]
    if len(ids) != len(set(ids)) or set(ids) != set(anchors):
        raise ActionRejected('COMMISSION_REQUIREMENTS_ANCHOR_SET_MISMATCH')
    if items == previous['payload']['items']:
        return previous_ref
    return save_revision(cs, db, actor, previous_ref, {**previous['payload'], 'items': items})


def propose_requirements(cs, actor, operation_id, requirements_ref, items):
    if actor.role != 'coordinator' or actor.id != 'content:coordinator':
        raise ActionForbidden('FORBIDDEN: requirement interpretation belongs to coordinator')
    items = [RequirementItem.model_validate(i).model_dump() for i in items]
    def save(db):
        previous = read_requirements(cs, requirements_ref, db=db)
        ref = _write_items(cs, db, actor, previous, items)
        return {'requirements_ref': ref}
    result = cs.operation(actor, operation_id, {'requirements_ref': requirements_ref, 'items': items}, save)
    ref = result['result']['requirements_ref']
    if ref != requirements_ref:
        publish_interpretation(cs, actor, operation_id, ref)
    return result


def check_plan(cs, plan, requirements_ref=None, *, db=None):
    """Report every missing obligation without changing a proposal or saved record."""
    if db is None:
        with cs.store.connect() as connection:
            return check_plan(cs, plan, requirements_ref, db=connection)
    from .commission_owner_records import validate_owner_records
    validate_owner_records(cs, db, plan)
    from .commission_skeleton import validate_skeleton, disposition_gaps
    validate_skeleton(cs, db, plan)
    record = read_requirements(cs, requirements_ref, db=db)
    anchors = record['payload']['anchors']
    from .commission_carryover import gaps as carryover_gaps
    gaps = disposition_gaps(cs, db, plan) + carryover_gaps(cs, db, plan)
    def gap(anchor, path, code, message):
        gaps.append({'anchor_id': anchor['id'], 'path': path, 'code': code, 'message': message})
    for pin in record['payload']['source_pins']:
        source = cs._read(db, pin['ref'])['payload']
        if source['file_digest'] != pin['file_digest']:
            for anchor in anchors:
                if anchor['source']['source_ref'] == pin['ref']:
                    gap(anchor, 'source_pins', 'SOURCE_PIN_MISMATCH', 'Requirement source version no longer matches its frozen hash')
    if (record['ref'] != read_requirements(cs, db=db)['ref'] or plan.get('requirements_ref') != record['ref']):
        gap(anchors[0], 'requirements_ref', 'REQUIREMENTS_VERSION', 'Use the current complete requirement record')
    sections = {s.get('section_id'): s for s in plan.get('sections', [])}
    for section in sections.values():
        if section.get('extraction'):
            from .commission_planning import resolve_source_span
            from pydantic import ValidationError
            extraction = section['extraction']
            try:
                resolved = resolve_source_span(cs, extraction['selection'])
                valid = extraction == {'selection': extraction['selection'], **resolved} and section['sources'] == resolved['sources']
            except (ActionRejected, ValidationError, KeyError, TypeError):
                valid = False
            if not valid:
                anchor = next((a for a in anchors if a.get('section_id') == section['section_id']), anchors[0])
                gap(anchor, 'sections.' + section['section_id'] + '.extraction', 'SECTION_EXTRACTION_CHANGED',
                    'Use the system extraction of the exact source selection and normalization profile')
    return gaps


def require_complete(cs, plan, *, db=None):
    from .commission_owner_records import validate_owner_records
    if db is None:
        with cs.store.connect() as connection:
            validate_owner_records(cs, connection, plan)
    else:
        validate_owner_records(cs, db, plan)
    if not enabled(cs.store):
        return
    gaps = check_plan(cs, plan, plan.get('requirements_ref'), db=db)
    if gaps:
        raise ActionRejected('COMMISSION_REQUIREMENTS_INCOMPLETE', diagnostic={'gaps': gaps})


def require_snapshot(cs, db, snapshot):
    """Check the selected immutable snapshot, not an unrelated newer plan."""
    from . import plan_authority
    anchored = enabled(cs.store)
    payload = snapshot['payload']
    plan_ref, decision_ref = payload.get('commission_plan_ref'), payload.get('commission_confirmation_ref')
    plan = cs._read(db, plan_ref) if plan_ref else {}
    decision = cs._read(db, decision_ref) if decision_ref else {}
    versioned_plan = bool(plan) and ('plan_input_refs' in plan
                                    or plan_authority.has_proposal(db, plan_ref))
    if not anchored and not versioned_plan:
        return  # Older snapshots use the existing material-issue and export checks.
    if not plan or not decision:
        raise ActionRejected('COMMISSION_REQUIREMENTS_SNAPSHOT_BINDING_REQUIRED')
    if anchored:
        require_complete(cs, plan['payload'], db=db)
    if (decision['owner_id'] != 'operator' or not decision['payload'].get('approved')
            or decision['payload'].get('plan_ref') != plan_ref
            or (anchored and decision['payload'].get('requirements_ref') != plan['payload'].get('requirements_ref'))):
        raise ActionRejected('COMMISSION_REQUIREMENTS_CONFIRMATION_REQUIRED')
    if versioned_plan:
        plan_authority.confirmed_refs(db, plan=plan_ref, decision=decision_ref)


def export_preflight(cs, actor, snapshot_ref, deliverable):
    """Export replay grants authority too; reading an old artifact remains separate."""
    from .commission_plan import enabled as checkpoint_enabled
    from . import commission_imports
    from .deliverables import resolve_snapshot, source_authority
    commission_checks = enabled(cs.store) or checkpoint_enabled(cs.store)
    with cs.store.connect() as db:
        source_checks = commission_imports.requires_source_policy(db) or commission_imports.source_policy_ref(db) is not None
        if commission_checks or source_checks:
            if deliverable is not None:
                snapshot_ref = resolve_snapshot(cs, db, actor, deliverable)
            record = cs._read(db, snapshot_ref)
            if commission_checks:
                require_snapshot(cs, db, record)
            if source_checks:
                payload = record['payload']
                source_authority(cs, db, actor, [cs._read(db, r) for r in payload['refs']], snapshot=payload)
        elif snapshot_ref is None:
            return
        from .report_state import require_current
        try:
            require_current(db, snapshot_ref)
        except ActionRejected:
            # Keep the existing affected-score diagnostics on both fresh and cached exports.
            from .g3_export import validate_export
            record = cs._read(db, snapshot_ref)
            records = {Ref.model_validate(ref).key(): cs._read(db, ref) for ref in record['payload']['refs']}
            validate_export(cs, record, records)
            raise
