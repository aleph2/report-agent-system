"""Source-bound planning steps; reviewed data stays on the server."""
from . import issue_state
from . import commission_assertions, commission_imports, plan_inputs
from . import legacy_state as legacy
from copy import deepcopy
import re
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .content_models import Contract, Ref, SourceCitation, InventoryObject
from .errors import ActionForbidden, ActionRejected
from .method_pack import MethodPack, reviewed_method_questions
from .table_spec import TableSpec, validate_table_specs
from .commission_plan import (_state, _set, _citations, ScopeBoundary, SourceSubstitution,
                              Reconciliation, ResultBinding, LiteralReplacement, SourceView)
from .store import digest
from .commission_requirements import Capability, publish_interpretation, save_revision
from .planning_inputs import (BoundaryInput, PlanningCitation, PlanningInventoryObject, PlanningSubstitution,
    PlanningReconciliationInput, resolve_citations, model_value, reject, expose, metres)

CATALOG = 'commission_reviewed_entries'
CONTRACT = 'commission-planning-v1'


def enabled(store):
    from .handoff_release import manifest
    value = manifest(store).get('commission_planning_contract')
    if value not in (None, CONTRACT):
        raise ActionRejected('UNKNOWN_COMMISSION_PLANNING_CONTRACT')
    return value == CONTRACT


class TextProfile(Contract):
    id: str = Field(min_length=1)
    source_ref: Ref
    file_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    header_lines: list[str] = Field(default_factory=list)
    footer_lines: list[str] = Field(default_factory=list)
    page_number_offset: int | None = Field(default=None, strict=True)
    page_number_position: Literal['header', 'footer'] = 'footer'
    join_lines: Literal['paragraph'] = 'paragraph'


class SourceSpan(Contract):
    source_ref: Ref
    start_page: int = Field(strict=True, ge=1)
    end_page: int = Field(strict=True, ge=1)
    start_sentence: str = Field(min_length=1)
    end_sentence: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)


def install_text_profile(cs, profile):
    """Host-owned, source-specific normalization; no agent-authored regex rules."""
    profile = TextProfile.model_validate(profile).model_dump(mode='json')
    if profile['source_ref']['type'] != 'SourceArtifact':
        raise ActionRejected('TEXT_PROFILE_SOURCE_REQUIRED')
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if cs._read(db, profile['source_ref'])['payload']['file_digest'] != profile['file_digest']:
            raise ActionRejected('TEXT_PROFILE_SOURCE_CHANGED')
        profiles = plan_inputs.get_text_profiles(db, {})
        if profile['id'] in profiles and profiles[profile['id']] != profile:
            raise ActionRejected('TEXT_PROFILE_IMMUTABLE')
        profiles[profile['id']] = profile
        plan_inputs.save_text_profiles(db, profiles)
    return profile


def resolve_source_span(cs, selection):
    selection = SourceSpan.model_validate(selection).model_dump(mode='json')
    if selection['end_page'] < selection['start_page']:
        raise ActionRejected('SOURCE_SPAN_PAGE_ORDER')
    from .document_tools import physical_page_number
    with cs.store.connect() as db:
        profile = plan_inputs.get_text_profiles(db, {}).get(selection['profile_id'])
        if not profile or profile['source_ref'] != selection['source_ref']:
            reject('source_span.profile_id', 'SOURCE_SPAN_PROFILE_REQUIRED',
                   [key for key, item in plan_inputs.get_text_profiles(db, {}).items() if item['source_ref'] == selection['source_ref']],
                   related_fields=['source_span.source_ref'],
                   message='Choose a reviewed profile bound to this exact source. For an extracted section, use sources citations and omit source_span; a fixed section requires a reviewed template profile. Do not reuse a template profile for a design source.')
        source = cs._read(db, selection['source_ref'])['payload']
        if source['file_digest'] != profile['file_digest']:
            raise ActionRejected('TEXT_PROFILE_SOURCE_CHANGED')
        rows = list(db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal', (source['source_id'],)))
    sources, pages = [], []
    for page in range(selection['start_page'], selection['end_page'] + 1):
        found = [(loc, text) for loc, text in rows if physical_page_number(loc) == page]
        if not found or not any(text.strip() for _, text in found):
            reject('source_span.' + ('start_page' if page == selection['start_page'] else 'end_page' if page == selection['end_page'] else 'page_range'), 'SOURCE_SPAN_PAGE_TEXT_UNAVAILABLE: ' + str(page), sorted({physical_page_number(loc) for loc, text in rows if text.strip() and physical_page_number(loc) is not None}))
        sources += [{'source_ref': selection['source_ref'], 'locator': loc, 'quote': text} for loc, text in found]
        pages.append(normalize_text('\n'.join(text for _, text in found), page, profile))
    normalized = '\n\n'.join(pages)
    start, end = selection['start_sentence'], selection['end_sentence']
    for field, sentence in [('start_sentence', start), ('end_sentence', end)]:
        if normalized.count(sentence) != 1:
            reject('source_span.' + field, 'SOURCE_SPAN_ENDPOINT_AMBIGUOUS_OR_MISSING', [m.start() for m in re.finditer(re.escape(sentence), normalized)])
    first, last = normalized.index(start), normalized.index(end) + len(end)
    if last < first + len(start):
        raise ActionRejected('SOURCE_SPAN_ENDPOINT_ORDER')
    text = normalized[first:last]
    # Keep exact original spans, including furniture inside the selected range.
    def endpoint(sentence, page, field):
        candidates = []
        pattern = r'\s*'.join(re.escape(char) for char in sentence if not char.isspace())
        for index, citation in enumerate(sources):
            if physical_page_number(citation['locator']) == page:
                candidates += [(index, match.start(), match.end()) for match in re.finditer(pattern, citation['quote'])]
        if len(candidates) != 1:
            reject('source_span.' + field, 'SOURCE_SPAN_RAW_ENDPOINT_AMBIGUOUS_OR_MISSING', [sources[index]['locator'] for index, _, _ in candidates])
        return candidates[0]
    start_index, start_offset, _ = endpoint(start, selection['start_page'], 'start_sentence')
    end_index, _, end_offset = endpoint(end, selection['end_page'], 'end_sentence')
    selected = []
    for index in range(start_index, end_index + 1):
        citation = sources[index]
        selected.append({**citation, 'quote': citation['quote'][start_offset if index == start_index else 0:
                            end_offset if index == end_index else len(citation['quote'])]})
    sources = selected
    return {'sources': sources, 'text': text, 'normalization': {'profile_id': profile['id'],
            'profile': profile, 'raw_digest': digest(sources), 'output_digest': digest(text)}}


def normalize_text(text, page, profile):
    lines = text.strip().splitlines()
    number = str(page + profile['page_number_offset']) if profile['page_number_offset'] is not None else None
    while lines and (lines[0].strip() in profile['header_lines'] or
                     profile['page_number_position'] == 'header' and lines[0].strip() == number):
        lines.pop(0)
    while lines and (lines[-1].strip() in profile['footer_lines'] or
                     profile['page_number_position'] == 'footer' and lines[-1].strip() == number):
        lines.pop()
    paragraphs, heading_before = [], False
    for line in lines:
        line = line.strip()
        heading = bool(re.match(r'^(?:第.+章|\d+(?:\.\d+)*[、.\s])', line))
        item = bool(re.match(r'^[\[（(]\d+[\]）)]', line))
        if not line:
            if paragraphs and paragraphs[-1] != '':
                paragraphs.append('')
        elif not paragraphs or not paragraphs[-1] or heading or item or heading_before:
            paragraphs.append(line)
        else:
            previous = paragraphs[-1]
            space = '' if re.search(r'[\u3400-\u9fff，。；：、]$', previous) and re.match(r'[\u3400-\u9fff]', line) else ' '
            paragraphs[-1] += space + line
        heading_before = heading
    return '\n'.join(paragraphs).strip()


class SourcePin(Contract):
    ref: Ref
    file_digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class ReviewedEntry(Contract):
    id: str = Field(min_length=1)
    kind: Literal['method', 'weight', 'table']
    label: str = Field(min_length=1)
    method_pack: MethodPack | None = None
    strategy_id: str | None = None
    table_specs: dict[str, TableSpec] = Field(default_factory=dict)
    source_pins: list[SourcePin] = Field(min_length=1)


class Classification(Contract):
    anchor_id: str = Field(min_length=1)
    entry_ids: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    table_roles: list[str] = Field(default_factory=list)


def _classifications(cs, db, record, values, note):
    from .commission_requirements import RequirementItem
    if not isinstance(note, str) or not note.strip():
        raise ActionRejected('REQUIREMENT_CLASSIFICATION_NOTE_REQUIRED')
    values = [Classification.model_validate(v).model_dump() for v in values]
    anchors = {a['id'] for a in record['payload']['anchors']}
    if len({v['anchor_id'] for v in values}) != len(values) or any(v['anchor_id'] not in anchors for v in values):
        raise ActionRejected('REQUIREMENT_CLASSIFICATION_ANCHOR_INVALID')
    for value in values:
        if value['entry_ids'] and (value['capabilities'] or value['table_roles']):
            raise ActionRejected('REQUIREMENT_CLASSIFICATION_EXCLUSIVE')
        if len(set(value['entry_ids'])) != len(value['entry_ids']):
            raise ActionRejected('REQUIREMENT_CLASSIFICATION_ENTRY_DUPLICATE')
        if len(set(value['capabilities'])) != len(value['capabilities']) or value['table_roles']:
            raise ActionRejected('REQUIREMENT_CLASSIFICATION_CAPABILITIES_INVALID')
        for identity in value['entry_ids']:
            reviewed_entry(cs, db, identity)
        RequirementItem.model_validate({'anchor_id': value['anchor_id'], 'status': 'required',
            'interpretation': note, 'capabilities': value['capabilities'], 'table_roles': value['table_roles']})
        if {'method_pack', 'weight_binding', 'table_specs'} & set(value['capabilities']):
            raise ActionRejected('COMPUTATION_CLASSIFICATION_REQUIRES_REVIEWED_ENTRY')
    return values


def install_classifications(cs, classifications, review_note):
    """Trusted review of this immutable source-anchor set; no model tool."""
    from .commission_requirements import read_requirements
    from .content_store import Actor
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        record = read_requirements(cs, db=db)
        values = _classifications(cs, db, record, classifications, review_note)
        existing = deepcopy(record['payload'].get('classifications', {}))
        for value in values:
            entry = {**value, 'origin': 'reviewed', 'note': review_note}
            old = existing.get(value['anchor_id'])
            if old and old != entry:
                raise ActionRejected('REQUIREMENT_CLASSIFICATION_IMMUTABLE')
            existing[value['anchor_id']] = entry
        if existing == record['payload'].get('classifications', {}):
            return record['ref']
        return save_revision(cs, db, Actor('host', 'host', 'commission-classification'),
                             record['ref'], {**record['payload'], 'classifications': existing})


def classified_item(cs, db, record, item):
    if not enabled(cs.store):
        return apply_entry(cs, db, item)
    classification = record['payload'].get('classifications', {}).get(item['anchor_id'])
    if not classification:
        if item['capabilities']:
            raise ActionRejected('REQUIREMENT_CLASSIFICATION_REQUIRED')
        return {**item, 'capabilities': [], 'table_roles': []}
    identity = item.get('reviewed_entry_id')
    if identity:
        if identity not in classification['entry_ids']:
            reject('entry_id', 'REQUIREMENT_ENTRY_NOT_ELIGIBLE', classification['entry_ids'])
        return apply_entry(cs, db, item)
    if classification['entry_ids']:
        obligations = [entry_obligations(reviewed_entry(cs, db, identity)) for identity in classification['entry_ids']]
        return {**item, 'capabilities': sorted({c for caps, _ in obligations for c in caps}),
                'table_roles': sorted({r for _, roles in obligations for r in roles})}
    return {**item, 'capabilities': classification['capabilities'], 'table_roles': classification['table_roles']}


def classification_gaps(cs, db, record, item):
    if not enabled(cs.store) or item['status'] != 'required':
        return []
    classification = record['payload'].get('classifications', {}).get(item['anchor_id'])
    if not classification:
        return ['The owner or a source-bound review must classify this requirement']
    if classification['entry_ids'] and item.get('reviewed_entry_id') not in classification['entry_ids']:
        return ['Link one of the reviewed entries eligible for this requirement']
    expected = classified_item(cs, db, record, item)
    if item['capabilities'] != expected['capabilities'] or item.get('table_roles', []) != expected.get('table_roles', []):
        return ['Retain the capabilities derived from the source-bound classification']
    return []


def install_reviewed_entries(cs, entries):
    """Trusted host registration, never a model tool; existing IDs cannot change."""
    entries = [ReviewedEntry.model_validate(e).model_dump(mode='json', exclude_none=True) for e in entries]
    if len({e['id'] for e in entries}) != len(entries):
        raise ActionRejected('REVIEWED_ENTRY_DUPLICATE_ID')
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        catalog = _state(db, CATALOG, {})
        for entry in entries:
            pack = entry.get('method_pack')
            if entry['kind'] in ('method', 'weight'):
                if not pack or reviewed_method_questions(cs, db, pack):
                    raise ActionRejected('REVIEWED_ENTRY_METHOD_NOT_REVIEWED')
                if entry['table_specs']:
                    raise ActionRejected('REVIEWED_ENTRY_KIND_MISMATCH')
                if entry['kind'] == 'weight' and not any(t['id'] == entry.get('strategy_id') for t in pack['weight_tables']):
                    raise ActionRejected('REVIEWED_ENTRY_WEIGHT_STRATEGY_REQUIRED')
            elif pack or entry.get('strategy_id') or not entry['table_specs']:
                raise ActionRejected('REVIEWED_ENTRY_TABLES_REQUIRED')
            else:
                validate_table_specs(entry['table_specs'])
            refs = {Ref.model_validate(c['source_ref']).key(): c['source_ref']
                    for c in _citations(pack or entry['table_specs'])}
            expected = {key: cs._read(db, ref)['payload']['file_digest'] for key, ref in refs.items()}
            actual = {Ref.model_validate(p['ref']).key(): p['file_digest'] for p in entry['source_pins']}
            if expected != actual or len(actual) != len(entry['source_pins']):
                raise ActionRejected('REVIEWED_ENTRY_SOURCE_PINS_REQUIRED')
            if entry['id'] in catalog and catalog[entry['id']] != entry:
                raise ActionRejected('REVIEWED_ENTRY_ID_IMMUTABLE')
            catalog[entry['id']] = entry
        _set(db, CATALOG, catalog)
        return deepcopy(catalog)


def reviewed_entry(cs, db, entry_id):
    entry = _state(db, CATALOG, {}).get(entry_id)
    if entry is None:
        reject('entry_id', 'REVIEWED_ENTRY_NOT_OFFERED', _state(db, CATALOG, {}))
    for pin in entry['source_pins']:
        if cs._read(db, pin['ref'])['payload']['file_digest'] != pin['file_digest']:
            raise ActionRejected('REVIEWED_ENTRY_SOURCE_CHANGED')
    return entry


def entry_obligations(entry):
    if entry['kind'] == 'weight':
        return ['method_pack', 'weight_binding'], []
    if entry['kind'] == 'method':
        return ['method_pack'], []
    return ['table_specs'], sorted(entry['table_specs'])


def apply_entry(cs, db, item):
    if item.get('reviewed_entry_id'):
        entry = reviewed_entry(cs, db, item['reviewed_entry_id'])
        capabilities, roles = entry_obligations(entry)
        item = {**item, 'capabilities': capabilities}
        if roles:
            item['table_roles'] = roles
        else:
            item.pop('table_roles', None)
    return item


def entry_plan_gaps(cs, db, item, plan):
    if not item.get('reviewed_entry_id'):
        return []
    entry = reviewed_entry(cs, db, item['reviewed_entry_id'])
    capabilities, roles = entry_obligations(entry)
    gaps = []
    if item['capabilities'] != capabilities or item.get('table_roles', []) != roles:
        gaps.append(('requirements.' + item['anchor_id'], 'Retain obligations derived from the reviewed entry'))
    def same(model, actual, expected):
        try:
            return model.model_validate(actual).model_dump(mode='json') == model.model_validate(expected).model_dump(mode='json')
        except ValidationError:
            return False
    if entry['kind'] in ('method', 'weight') and not same(MethodPack, plan.get('method_pack'), entry['method_pack']):
        gaps.append(('method_pack', 'Attach the exact reviewed method entry'))
    if entry['kind'] == 'weight':
        bindings = [b for b in plan.get('method_conventions', []) if b.get('key') == 'weights']
        if len(bindings) != 1 or bindings[0].get('strategy_id') != entry['strategy_id']:
            gaps.append(('method_conventions', 'Use the linked reviewed weight strategy'))
    for role, spec in entry['table_specs'].items():
        if not same(TableSpec, plan.get('table_specs', {}).get(role), spec):
            gaps.append(('table_specs.' + role, 'Attach the exact reviewed table specification'))
    return gaps


def _edit_requirement(cs, actor, operation_id, anchor_id, change, *, relink=False):
    from .commission_requirements import read_requirements, _write_items
    if actor.role != 'coordinator' or actor.id != 'content:coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    def save(db):
        if plan_inputs.get_skeleton(db):
            raise ActionRejected('SKELETON_REQUIREMENT_IS_SYSTEM_OWNED')
        previous = read_requirements(cs, db=db)
        items = deepcopy(previous['payload']['items'])
        item = next((i for i in items if i['anchor_id'] == anchor_id), None)
        if item is None:
            reject('anchor_id', 'COMMISSION_REQUIREMENT_ANCHOR_UNKNOWN', [i['anchor_id'] for i in items])
        item.update(change)
        ref = _write_items(cs, db, actor, previous, items, relink_anchor=anchor_id if relink else None)
        return {'requirements_ref': ref, 'changed': ref != previous['ref']}
    result = cs.operation(actor, operation_id, {'anchor_id': anchor_id, 'change': change, 'relink': relink}, save)
    if result['result']['changed']:
        publish_interpretation(cs, actor, operation_id, result['result']['requirements_ref'])
    return result


def set_requirement_status(cs, actor, operation_id, anchor_id, status, interpretation, capabilities=None):
    change = {'status': status, 'interpretation': interpretation}
    if enabled(cs.store):
        change['capabilities'] = []
    if capabilities is not None:
        change['capabilities'] = capabilities
    return _edit_requirement(cs, actor, operation_id, anchor_id, change)



class RequirementStatusInput(Contract):
    anchor_id: str
    status: Literal['required', 'not_applicable', 'unresolved']
    interpretation: str


def set_requirement_statuses(cs, actor, operation_id, items):
    from .commission_requirements import read_requirements, _write_items
    if actor.role != 'coordinator' or actor.id != 'content:coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    if not isinstance(items, list) or not items:
        raise ActionRejected('PLANNING_NONEMPTY_ITEM_BATCH_REQUIRED')
    def save(db):
        if plan_inputs.get_skeleton(db):
            raise ActionRejected('SKELETON_REQUIREMENT_IS_SYSTEM_OWNED')
        previous = read_requirements(cs, db=db)
        values = deepcopy(previous['payload']['items'])
        errors, seen = [], set()
        for index, raw in enumerate(items):
            db.execute('SAVEPOINT planning_status')
            try:
                item = model_value(RequirementStatusInput, raw, 'status').model_dump()
                identity = item.pop('anchor_id')
                if identity in seen:
                    raise ActionRejected('PLANNING_DUPLICATE_ITEM_ID')
                seen.add(identity)
                proposed = deepcopy(values)
                target = next((v for v in proposed if v['anchor_id'] == identity), None)
                if target is None:
                    reject('anchor_id', 'COMMISSION_REQUIREMENT_ANCHOR_UNKNOWN', [v['anchor_id'] for v in values])
                target.update(item)
                if enabled(cs.store):
                    target['capabilities'] = []
                # Reuse the complete-list checks, then commit just one final revision.
                _write_items(cs, db, actor, previous, proposed)
                values = proposed
            except (ActionRejected, ActionForbidden, ValidationError) as error:
                errors.append(_batch_error(index, error, 'status'))
            finally:
                db.execute('ROLLBACK TO planning_status')
                db.execute('RELEASE planning_status')
        if errors:
            _reject_batch(errors)
        ref = _write_items(cs, db, actor, previous, values)
        return {'requirements_ref': ref, 'changed': ref != previous['ref']}
    result = cs.operation(actor, operation_id, {'requirement_statuses': deepcopy(items)}, save)
    if result['result']['changed']:
        publish_interpretation(cs, actor, operation_id, result['result']['requirements_ref'])
    return result


def link_convention(cs, actor, operation_id, anchor_id, entry_id, interpretation):
    return _edit_requirement(cs, actor, operation_id, anchor_id,
        {'status': 'required', 'interpretation': interpretation, 'reviewed_entry_id': entry_id}, relink=True)



class PlanningSectionInput(Contract):
    section_id: str
    title: str
    kind: Literal['fixed', 'extracted', 'derived']
    outline_anchor_id: str = Field(min_length=1, description='Returned section requirement ID matching section_id, not its locator or heading.')
    source_span: SourceSpan | None = Field(default=None, description='Reviewed fixed PDF template selector; mutually exclusive with sources.')
    sources: list[PlanningCitation] = Field(default_factory=list, description='Source citations for extracted sections, derived evidence, or exact fixed Word-template paragraphs. Omit source_span; do not attach a template profile to a design source.')
    pending_sources: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    rule: str = ''
    result_bindings: list[ResultBinding] = Field(default_factory=list)
    replacements: list[LiteralReplacement] = Field(default_factory=list)
    source_views: list[SourceView] = Field(default_factory=list)
    examples: list[PlanningCitation] = Field(default_factory=list)


class SectionJudgment(Contract):
    section_id: str = Field(min_length=1)
    sources: list[SourceCitation] = Field(default_factory=list)
    examples: list[SourceCitation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CandidateDisposition(Contract):
    object_id: str = Field(min_length=1)
    status: Literal['included', 'owner_excluded', 'proposed_exclusion']
    reason: str = Field(min_length=1)
    owner_record_id: str | None = None


class PlanDetails(Contract):
    report_title: str = ''
    inventory_attributes: list[str] = Field(min_length=1)
    deliverables: list[str] = Field(min_length=1)


class PlanningQuestion(Contract):
    question_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    resolved: bool = Field(strict=True)


class PlanningReconciliation(Reconciliation):
    reconciliation_id: str = Field(min_length=1)


def _owner_rank_binding(conventions, indicators):
    """Recognize only an explicit numbered permutation in the customer's rank declaration."""
    pattern = r'(?:[0-9]+[.)]\s+)?本委托的重要性顺序（1\s*为首位）对各坡段相同[：:]\s*(.+?)[。.]?'
    expected = {rule['id'] for rule in indicators}
    binding = None
    for convention in conventions:
        source = convention['source']
        match = re.fullmatch(pattern, source['quote'].strip())
        if match is None:
            continue
        entries = [re.fullmatch(r'([1-9][0-9]*)\s+([A-Za-z][A-Za-z0-9_-]*)', pair.strip())
                   for pair in re.split(r'[,，]', match[1])]
        if (any(entry is None for entry in entries)
                or [int(entry[1]) for entry in entries] != list(range(1, len(expected) + 1))
                or {entry[2] for entry in entries} != expected):
            raise ActionRejected('PLANNING_OWNER_RANK_ORDER_INVALID')
        if binding is not None:
            raise ActionRejected('PLANNING_OWNER_RANK_ORDER_AMBIGUOUS')
        binding = {'indicator_ids': [entry[2] for entry in entries], 'source': deepcopy(source)}
    return binding


def _assemble(cs, db):
    from .commission_requirements import read_requirements
    from .commission_plan import CommissionPlan
    requirements = read_requirements(cs, db=db)
    draft = plan_inputs.get_draft(db, {'revision': 0, 'items': {}})
    items = draft['items']
    plan = {key: list(items.get(kind, {}).values()) for kind, key in
            [('section', 'sections'), ('object', 'objects'), ('reconciliation', 'reconciliations'), ('question', 'open_questions')]}  # type: dict
    plan.update(items.get('details', {}).get('details', {}))
    plan['open_questions'] = [q['text'] for q in plan['open_questions'] if not q['resolved']]
    plan['reconciliations'] = [{k: v for k, v in r.items() if k != 'reconciliation_id'} for r in plan['reconciliations']]
    plan['requirements_ref'] = requirements['ref']
    plan['conventions'] = []
    plan['method_conventions'], plan['table_specs'] = [], {}
    if items.get('boundary'):
        plan['scope_boundary'] = items['boundary']['boundary']
    anchors = {a['id']: a for a in requirements['payload']['anchors']}
    order = {a['section_id']: index for index, a in enumerate(anchors.values()) if a['kind'] == 'section'}
    plan['sections'].sort(key=lambda s: (order.get(s['section_id'], len(order)), s['section_id']))
    def attach(key, value):
        if key in plan and plan[key] != value:
            raise ActionRejected('PLANNING_REVIEWED_ENTRY_CONFLICT: ' + key)
        plan[key] = deepcopy(value)
    for item in requirements['payload']['items']:
        anchor = anchors[item['anchor_id']]
        if item['status'] != 'required':
            continue
        if anchor['kind'] == 'convention':
            plan['conventions'].append({'requirement_anchor_id': anchor['id'], 'source': anchor['source'],
                                        'interpretation': item['interpretation']})
        if not item.get('reviewed_entry_id'):
            continue
        entry = reviewed_entry(cs, db, item['reviewed_entry_id'])
        if entry.get('method_pack'):
            attach('method_pack', MethodPack.model_validate(entry['method_pack']).model_dump(mode='json'))
        if entry['kind'] == 'weight':
            binding = {'key': 'weights', 'source': anchor['source'], 'interpretation': item['interpretation'],
                       'status': 'specified', 'method_id': entry['method_pack']['method_id'], 'strategy_id': entry['strategy_id']}
            if plan['method_conventions'] and plan['method_conventions'] != [binding]:
                raise ActionRejected('PLANNING_WEIGHT_LINK_CONFLICT')
            plan['method_conventions'] = [binding]
        for role, table in entry['table_specs'].items():
            table = TableSpec.model_validate(table).model_dump(mode='json')
            if role in plan['table_specs'] and plan['table_specs'][role] != table:
                raise ActionRejected('PLANNING_TABLE_LINK_CONFLICT: ' + role)
            plan['table_specs'][role] = deepcopy(table)
    if pack := plan.get('method_pack'):
        if binding := _owner_rank_binding(plan['conventions'], pack['indicators']):
            plan['indicator_rank_order'] = binding
    from .commission_skeleton import apply_skeleton
    plan = apply_skeleton(cs, db, plan)
    for judgment in items.get('section_judgment', {}).values():
        for section in plan['sections']:
            if section['section_id'] == judgment['section_id']:
                section.update({k: v for k, v in judgment.items() if k != 'section_id'})
    from .commission_owner_records import decorate_plan
    plan = decorate_plan(cs, db, plan)
    for substitution in items.get('substitution', {}).values():
        section = next((s for s in plan['sections'] if s['section_id'] == substitution['section_id']), None)
        if section:
            value = substitution['substitution']
            section['source_substitutions'] = [s for s in section.get('source_substitutions', []) if s['requested_source'] != value['requested_source']] + [value]
    from .commission_skeleton import apply_dispositions
    plan = apply_dispositions(cs, db, plan)
    from .commission_carryover import decorate
    return draft, requirements, decorate(db, plan)


def _gaps(cs, plan, db):
    from .commission_requirements import check_plan
    from .commission_plan import CommissionPlan
    try:
        gaps = check_plan(cs, plan, db=db)
    except ActionRejected as error:
        fields = (getattr(error, 'diagnostic', None) or {}).get('fields', [])
        gaps = [{'anchor_id': None, 'path': f.get('section_id', 'plan') + '.' + f.get('field', 'plan'),
                 'code': f.get('reason', 'PLAN_INCOMPLETE'), 'message': str(error), 'item_id': f.get('item_id')}
                for f in fields] or [{'anchor_id': None, 'path': 'plan', 'code': 'PLAN_INCOMPLETE', 'message': str(error)}]
    for question in plan.get('skeleton_questions', []):
        gaps.append({'anchor_id': None, 'path': 'skeleton_questions.' + question['question_id'], 'code': 'SKELETON_QUESTION_UNRESOLVED', 'message': question['reason']})
    draft = plan_inputs.get_draft(db, {'items': {}})
    for value in draft['items'].get('substitution', {}).values():
        if value['section_id'] not in {s['section_id'] for s in plan['sections']}:
            gaps.append({'anchor_id': None, 'path': 'substitutions.' + value['section_id'],
                         'code': 'SUBSTITUTION_SECTION_REQUIRED', 'message': 'Add the section named by this substitution'})
    try:
        CommissionPlan.model_validate(plan)
    except ValidationError as error:
        from .planning_inputs import inventory_error_fields
        for issue in error.errors(include_input=False, include_url=False):
            fields = inventory_error_fields(issue)
            if fields:
                gaps.extend({'anchor_id': None, 'path': field['field'], 'code': field['reason'],
                             'message': 'Use exactly the inventory attribute contract for this object.',
                             **{k: v for k, v in field.items() if k not in {'field', 'reason'}}}
                            for field in fields)
            else:
                gaps.append({'anchor_id': None, 'path': '.'.join(map(str, issue['loc'])),
                             'code': 'PLAN_FIELD_REQUIRED', 'message': issue['msg']})
    return gaps


def read_draft(cs, actor):
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    with cs.store.connect() as db:
        draft, requirements, plan = _assemble(cs, db)
        return {'revision': draft['revision'], 'plan': plan, 'requirements': requirements,
                'entries': [{'id': e['id'], 'kind': e['kind'], 'label': e['label'],
                             'capabilities': entry_obligations(e)[0], 'table_roles': entry_obligations(e)[1]}
                            for e in _state(db, CATALOG, {}).values()],
                'text_profiles': list(plan_inputs.get_text_profiles(db, {}).values()), 'gaps': _gaps(cs, plan, db)}



DRAFT_COLLECTIONS = Literal['summary', 'requirements', 'sections', 'objects', 'reconciliations',
    'questions', 'substitutions', 'settings', 'entries', 'text_profiles', 'gaps', 'carried_items', 'source_assertions', 'page_bindings']


def read_draft_page(cs, actor, collection='summary', page=1, page_size=5, item_id='',
                    offset=0, characters=3000, view_ref='', gap_page=1):
    """Bound model observations before platform eviction; retain canonical data server-side."""
    if collection in ('source_assertions', 'page_bindings'):
        from .planning_assertions import read_source_index
        return read_source_index(cs, actor, item_id, page, page_size, view_ref, bindings=collection == "page_bindings")
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    from .store import encode
    with cs.store.connect() as db:
        db.execute('BEGIN')
        draft, requirements, plan = _assemble(cs, db)
        gaps = _gaps(cs, plan, db)
        items = draft['items']
        statuses = {i['anchor_id']: i for i in requirements['payload']['items']}
        collections = {
            'requirements': [(a['id'], {'anchor': a, 'requirement': statuses[a['id']],
                'classification': requirements['payload'].get('classifications', {}).get(a['id'])})
                for a in requirements['payload']['anchors']],
            **{name: list(items.get(kind, {}).items()) for name, kind in (
                ('sections', 'section'), ('objects', 'object'), ('questions', 'question'),
                ('reconciliations', 'reconciliation'), ('substitutions', 'substitution'))},
            'settings': [(k, v) for k, v in plan.items() if k not in
                         {'sections', 'objects', 'open_questions', 'reconciliations'}],
            'entries': [(e['id'], {'id': e['id'], 'kind': e['kind'], 'label': e['label'],
                'capabilities': entry_obligations(e)[0], 'table_roles': entry_obligations(e)[1]})
                for e in _state(db, CATALOG, {}).values()],
            'text_profiles': list(plan_inputs.get_text_profiles(db, {}).items()),
            'gaps': [(str(i), g) for i, g in enumerate(gaps)],
        }
        from .commission_carryover import rows
        collections['carried_items'] = [(r['item_id'],r) for r in rows(db,plan,True)]
        collections.update(sections=[(s['section_id'], s) for s in plan['sections']],
                           objects=[(o['object_id'], o) for o in plan['objects']])
    current = digest({'revision': draft['revision'], 'requirements_ref': requirements['ref'], 'collections': collections})
    if view_ref and view_ref != current:
        reject('view_ref', 'PLANNING_VIEW_CHANGED', [current], message='Reread summary; do not combine different draft versions.')
    if (offset or page > 1 or gap_page > 1) and not view_ref:
        reject('view_ref', 'PLANNING_VIEW_REF_REQUIRED', [current], message='Pass the summary view_ref for continuation.')
    # Full diagnostics are readable by gap index; compact controls never include source bodies.
    gap_pages, batch = [], []
    for index, gap in enumerate(gaps):
        compact = {**{k: gap.get(k) for k in ('anchor_id', 'path', 'code')}, 'detail_id': str(index)}
        for key, value in list(compact.items()):
            if isinstance(value, str) and len(value) > 240:
                compact[key] = value[:240]
                compact['abbreviated'] = True
        if batch and len(encode([*batch, compact])) > 4000:
            gap_pages.append(batch)
            batch = []
        batch.append(compact)
    gap_pages.append(batch)
    if gap_page > len(gap_pages):
        reject('gap_page', 'PLANNING_GAP_PAGE_OUT_OF_RANGE', list(range(1, len(gap_pages) + 1)))
    result = {'gaps': gap_pages[gap_page - 1], 'gap_count': len(gaps), 'gap_page': gap_page,
        'next_gap_page': gap_page + 1 if gap_page < len(gap_pages) else None,
        'view_ref': current, 'revision': draft['revision'], 'requirements_ref': requirements['ref'],
        'counts': {key: len(value) for key, value in collections.items()}, 'page_data': None,
        'read_next': 'Choose collection and page or exact item_id. Pass view_ref on continuations. Details are JSON text; concatenate next_offset chunks before decoding. Gaps describe missing work, not plan approval.'}
    if collection == 'summary':
        if item_id or offset or page != 1:
            reject('collection', 'PLANNING_SUMMARY_HAS_NO_ITEMS', collections.keys())
        return result
    rows = collections[collection]
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    if item_id:
        matches = [(key, value) for key, value in rows if key == item_id]
        if not matches:
            reject('item_id', 'PLANNING_ITEM_UNKNOWN', [key for key, _ in rows[:10]], message='Read collection pages for the exact item IDs; choices show the first ten.')
        selected, next_page = matches[0][1], None
    else:
        if page > total_pages:
            reject('page', 'PLANNING_PAGE_OUT_OF_RANGE', [1, total_pages])
        selected = [{'id': key, 'value': value} for key, value in rows[(page - 1) * page_size:page * page_size]]
        next_page = page + 1 if page < total_pages else None
    text = encode(selected)
    if offset > len(text):
        reject('offset', 'PLANNING_OFFSET_OUT_OF_RANGE', [0, len(text)])
    end = min(offset + characters, len(text))
    result['page_data'] = {'collection': collection, 'page': page, 'page_size': page_size,
        'item_id': item_id, 'total_items': len(rows), 'total_pages': total_pages,
        'text': text[offset:end], 'offset': offset, 'next_offset': end if end < len(text) else None,
        'total_characters': len(text), 'next_page': next_page, 'complete_page': offset == 0 and end == len(text)}
    return result

def _save_item(cs, actor, db, kind, item):
    from .commission_plan import SectionPlan, ScopeBoundary, Reconciliation, SourceSubstitution, _validate_sources, fixed_section_text
    from .content_models import InventoryObject
    value = deepcopy(item)
    if kind == 'section' and 'outline_anchor_id' in value:
        from .commission_requirements import read_requirements
        available = read_requirements(cs, db=db)['payload']['anchors']
        identity = value.pop('outline_anchor_id')
        anchor = next((a for a in available if a['id'] == identity and
                       a['kind'] == 'section' and a['section_id'] == value['section_id']), None)
        if anchor is None:
            reject('outline_anchor_id', 'SECTION_OUTLINE_ANCHOR_REQUIRED',
                [a['id'] for a in available if a['kind'] == 'section' and a['section_id'] == value['section_id']],
                message='Choose the returned section requirement ID matching section_id. A source locator or heading text is not an anchor ID.')
        value['outline'] = anchor['source']
        if value.get('source_span') is None:
            value.pop('source_span', None)
            if value['kind'] == 'fixed':
                records = [cs._read(db, c['source_ref']) for c in value['sources']]
                if not records or any(not r['payload']['source_metadata'].get('filename', '').lower().endswith('.docx') for r in records):
                    raise ActionRejected('FIXED_SECTION_SOURCE_SPAN_REQUIRED')
                value['text'] = '\n'.join(c['quote'] for c in value['sources'])
        elif value['sources']:
            reject('sources', 'SOURCE_SPAN_OR_CITATIONS_REQUIRED', ['source_span', 'sources'], related_fields=['source_span'],
                message='Choose one source mode. For extracted sections, supply sources and omit source_span. For fixed sections, use the reviewed template source_span and omit sources; the system produces the canonical citations.')
        else:
            value.pop('sources')
    if plan_inputs.get_skeleton(db) and kind in ('section', 'details'):
        raise ActionRejected('SKELETON_STRUCTURE_IS_SYSTEM_OWNED')
    if kind in ('section_judgment', 'disposition') and not plan_inputs.get_skeleton(db):
        raise ActionRejected('SKELETON_REGISTRY_REQUIRED')
    if kind == 'section_judgment':
        if set(value) - {'section_id', 'sources', 'examples', 'notes'}:
            raise ActionRejected('SKELETON_JUDGMENT_FIELDS_ONLY')
        original = next((s for s in plan_inputs.get_skeleton(db)['sections'] if s['section_id'] == value.get('section_id')), None)
        if not original or original['kind'] == 'fixed' or original.get('extraction'):
            raise ActionRejected('SKELETON_JUDGMENT_SECTION_INVALID')
    if kind == 'disposition':
        value = model_value(CandidateDisposition, value, 'disposition').model_dump(mode='json', exclude_none=True)
        if value['status'] == 'owner_excluded':
            raise ActionRejected('OWNER_EXCLUSION_IS_SYSTEM_OWNED')
    if kind == 'section' and 'source_span' in value:
        if any(key in value for key in ('text', 'extraction', 'sources')):
            raise ActionRejected('SECTION_OUTPUT_IS_SYSTEM_OWNED')
        selection = SourceSpan.model_validate(value.pop('source_span')).model_dump(mode='json')
        resolved = resolve_source_span(cs, selection)
        value.update(sources=resolved['sources'], extraction={'selection': selection, **resolved})
        value['text'] = fixed_section_text(value)
    elif kind == 'section' and value.get('extraction'):
        raise ActionRejected('SECTION_OUTPUT_IS_SYSTEM_OWNED')
    models = {'section': SectionPlan, 'object': InventoryObject, 'boundary': ScopeBoundary,
              'reconciliation': PlanningReconciliation, 'details': PlanDetails, 'question': PlanningQuestion}
    basis_binding = None
    if kind == 'boundary' and 'customer_basis_anchor_id' in value:
        from .commission_requirements import read_requirements
        boundary = model_value(BoundaryInput, value, 'boundary').model_dump(mode='json')
        record = read_requirements(cs, db=db)
        anchors = {a['id']: a for a in record['payload']['anchors'] if a['kind'] == 'scope'}
        identity = boundary.pop('customer_basis_anchor_id')
        if identity not in anchors or (anchors[identity].get('parse_error') and identity not in record['payload'].get('parse_resolutions', {})):
            reject('boundary.customer_basis_anchor_id', 'current_scope_anchor_required', anchors)
        boundary['chainage_inputs'] = {key: boundary[key] for key in ('start_meter', 'end_meter')}
        boundary['start_meter'], boundary['end_meter'] = metres(boundary['start_meter']), metres(boundary['end_meter'])
        basis = anchors[identity]['source']
        pins = [pin for pin in record['payload']['source_pins'] if pin['ref'] == basis['source_ref']]
        if len(pins) != 1 or cs._read(db, basis['source_ref'])['payload']['file_digest'] != pins[0]['file_digest']:
            reject('boundary.customer_basis_anchor_id', 'requirement_source_pin_mismatch', anchors)
        boundary['customer_basis'] = deepcopy(basis)
        basis_binding = {'anchor_id': identity, 'requirements_ref': record['ref']}
        value = boundary
    from .commission_owner_records import decorate_plan, refuse
    if commission_imports.owner_records(db):
        if kind == 'section':
            value = decorate_plan(cs, db, {'sections': [value], 'objects': []})['sections'][0]
        if kind == 'substitution' and not value.get('substitution', {}).get('document_id'):
            refuse(value.get('section_id'), 'source_substitutions', value.get('substitution', {}).get('requested_source', 'unknown'), 'document ID required')
    resolutions = resolve_citations(cs, db, actor, value, kind, planning=True)
    if kind in models:
        value = model_value(models[kind], value, kind).model_dump(mode='json')
    elif kind == 'substitution':
        if set(value) != {'section_id', 'substitution'} or not isinstance(value['section_id'], str) or not value['section_id'].strip():
            raise ActionRejected('SECTION_SUBSTITUTION_TARGET_REQUIRED')
        value['substitution'] = model_value(SourceSubstitution, value['substitution'], 'substitution').model_dump(mode='json')
    elif kind == 'section_judgment':
        value = model_value(SectionJudgment, value, 'section_judgment').model_dump(mode='json', exclude_unset=True)
    elif kind != 'disposition':
        raise ActionRejected('PLANNING_ITEM_KIND_UNKNOWN')
    _validate_sources(cs, db, actor, value, planning=True)
    key = (value['section_id'] if kind in ('section', 'section_judgment') else value['object_id'] if kind in ('object', 'disposition') else
           kind if kind in ('details', 'boundary') else
           value['section_id'] + ':' + value['substitution']['requested_source'] if kind == 'substitution' else
           value['question_id'] if kind == 'question' else value['reconciliation_id'])
    draft = plan_inputs.get_draft(db, {'revision': 0, 'items': {}})
    previous = draft['items'].setdefault(kind, {}).get(key)
    changed = previous != value
    if changed:
        draft['items'][kind][key] = value
        draft['revision'] += 1
        plan_inputs.save_draft(db, draft, actor=actor)
    return {'revision': draft['revision'], 'changed': changed, 'citation_resolutions': resolutions, 'customer_basis_binding': basis_binding}


def save_item(cs, actor, operation_id, kind, item):
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    return cs.operation(actor, operation_id, {'kind': kind, 'item': deepcopy(item)},
        lambda db: _save_item(cs, actor, db, kind, item))


def _batch_error(index, error, item_kind):
    diagnostic = deepcopy(getattr(error, 'diagnostic', None))
    def relative(path):
        return '' if path == item_kind else path.removeprefix(item_kind + '.')
    for field in (diagnostic or {}).get('fields', []):
        field['field'] = relative(field['field'])
        if field.get('related_fields'):
            field['related_fields'] = [relative(value) for value in field['related_fields']]
    return {'index': index, 'code': str(error).split(':')[0],
            'message': str(error), 'diagnostic': diagnostic}


def _reject_batch(errors):
    fields = []
    for error in errors:
        prefix = 'items.' + str(error['index'])
        details = (error['diagnostic'] or {}).get('fields') or [{'field': '', 'reason': error['code'], 'message': error['message']}]
        for field in details:
            fields.append({**field, 'field': prefix + ('.' + field['field'] if field['field'] else ''),
                **({'related_fields': [prefix + '.' + value for value in field['related_fields']]}
                   if field.get('related_fields') else {})})
    summary = '; '.join(str(error['index']) + ': ' + error['message'] for error in errors)
    raise ActionRejected('PLANNING_BATCH_INVALID: ' + summary, diagnostic={'items': errors, 'fields': fields})


def save_items(cs, actor, operation_id, kind, items):
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: planning belongs to coordinator')
    key_field = {'section': 'section_id', 'object': 'object_id',
                 'question': 'question_id', 'reconciliation': 'reconciliation_id'}.get(kind)
    if not key_field or not isinstance(items, list) or not items:
        raise ActionRejected('PLANNING_NONEMPTY_ITEM_BATCH_REQUIRED')
    def save(db):
        errors, saved, seen = [], [], set()
        for index, item in enumerate(items):
            db.execute('SAVEPOINT planning_item')
            try:
                identity = item.get(key_field)
                if isinstance(identity, str) and identity in seen:
                    raise ActionRejected('PLANNING_DUPLICATE_ITEM_ID')
                if isinstance(identity, str):
                    seen.add(identity)
                saved.append(_save_item(cs, actor, db, kind, item))
            except (ActionRejected, ActionForbidden, ValidationError) as error:
                db.execute('ROLLBACK TO planning_item')
                errors.append(_batch_error(index, error, kind))
            finally:
                db.execute('RELEASE planning_item')
        if errors:
            _reject_batch(errors)
        return {'revision': saved[-1]['revision'], 'changed': any(r['changed'] for r in saved), 'items': saved}
    return cs.operation(actor, operation_id, {'kind': kind, 'items': deepcopy(items)}, save)


def submit_plan(cs, actor, operation_id):
    from .commission_plan import save_plan
    draft = read_draft(cs, actor)
    if draft['gaps']:
        raise ActionRejected('COMMISSION_REQUIREMENTS_INCOMPLETE', diagnostic={'gaps': draft['gaps']})
    from .commission_plan import CommissionPlan
    from . import plan_authority
    proposed = CommissionPlan.model_validate(draft['plan']).model_dump()
    with cs.store.connect() as db:
        ref = plan_authority.plan_ref(db)
        saved = cs._read(db, ref) if ref else None
    # A new submit command may reuse unchanged content; its own operation ID still binds the request.
    if saved and CommissionPlan.model_validate({k:v for k,v in saved['payload'].items()
            if k in CommissionPlan.model_fields}).model_dump() == proposed:
        return cs.operation(actor, operation_id, {'commission_plan': proposed},
            lambda db: {'plan_ref': ref, 'inventory_refs': saved['payload']['inventory_refs']})
    return save_plan(cs, actor, operation_id, proposed)


def requirement_lines(cs, db, record):
    names = {'scope': '范围', 'convention': '约定', 'section': '章节', 'instruction': '编写要求'}
    states = {'required': '需要落实', 'not_applicable': '建议不适用，须确认', 'unresolved': '待明确'}
    labels = {'method_pack': '计算方法', 'weight_binding': '权重依据', 'table_specs': '表格规格',
              'scope_boundary': '合同范围边界', 'inventory_reconciliation': '资料间对象核对',
              'section': '章节计划', 'fixed_text': '模板固定内容', 'result_bindings': '关联计算结果',
              'inventory': '评估对象清单', 'deliverables': '交付物', 'material_issues': '重要问题',
              'source_priority': '资料采用顺序', 'assumptions': '假设及依据'}
    items = {i['anchor_id']: i for i in record['payload']['items']}
    lines = []
    convention = 0
    for anchor in record['payload']['anchors']:
        item = items[anchor['id']]
        if anchor['kind'] == 'convention':
            convention += 1
        title = names[anchor['kind']] + (str(convention) if anchor['kind'] == 'convention' else anchor.get('section_id', ''))
        result = '、'.join(labels[c] for c in item['capabilities']) or '待明确执行方式'
        if item.get('reviewed_entry_id'):
            entry = reviewed_entry(cs, db, item['reviewed_entry_id'])
            result = entry['label']
            if entry['kind'] == 'weight':
                result = '权重：' + result + f"，{len(entry['method_pack']['indicators'])}项行"
        lines += [f"- {title} → {result}（{states[item['status']]}）", '  原文：' + anchor['source']['quote'],
                  '  位置：' + anchor['source']['locator'], '  解释：' + item['interpretation']]
        lines += ['  续文：' + c['quote'] for c in anchor.get('continuations', [])]
        if anchor.get('parse_error'):
            lines.append('  解析异常：' + anchor['parse_error'])
        resolution = record['payload'].get('parse_resolutions', {}).get(anchor['id'])
        if resolution:
            lines.append('  用户处理说明：' + resolution['note'])
    return lines


def request_requirements_checkpoint(workspace, operation_id=None, actor=None):
    from .content_store import ContentStore, Actor
    from .commission_requirements import read_requirements
    from .plan_authority import stable_id
    cs = ContentStore(workspace.store)
    actor = actor or Actor('content:coordinator', 'coordinator', 'content-task:coordinator')
    if actor.role != 'coordinator' or actor.id != 'content:coordinator':
        raise ActionForbidden('FORBIDDEN: requirement checkpoint belongs to coordinator')
    operation_id = operation_id or 'requirements-checkpoint:' + digest(read_requirements(cs)['ref'])
    def create(db):
        record = read_requirements(cs, db=db)
        pending = [a['id'] for a in record['payload']['anchors'] if
                   (a.get('parse_error') and a['id'] not in record['payload'].get('parse_resolutions', {})) or
                   a['id'] not in record['payload'].get('classifications', {})]
        if not pending:
            reject('requirements', 'no_pending_parse_or_classification')
        relative = 'outputs/requirements-checkpoint-' + digest(record['ref']) + '.md'
        description = 'Resolve commission requirements ' + digest(record['ref']) + '. Brief: ' + relative
        source_ids = [cs._read(db, p['ref'])['payload']['source_id'] for p in record['payload']['source_pins']]
        identity = stable_id(actor, 'requirements-checkpoint', record['ref'])
        checkpoint = {'requirements_ref': record['ref'], 'anchor_ids': pending, 'brief_path': relative}
        return {'issue_id': identity, **checkpoint, 'description': description, 'source_ids': source_ids}
    checkpoint = cs.operation(actor, operation_id, {}, create)['result']
    record = read_requirements(cs, checkpoint['requirements_ref'])
    pending, identity = checkpoint['anchor_ids'], checkpoint['issue_id']
    path = workspace.store.root / checkpoint['brief_path']
    with cs.store.connect() as db:
        lines = ['# 要求解析与分类确认', '', '请逐项说明解析异常的处理或要求的执行方式。本次处理不批准报告计划。',
                 '涉及未识别结构时，请在说明中交代是否存在遗漏章节/约定；需要补充文件时先更新输入。', '']
        lines += requirement_lines(cs, db, record)
        available_entries = [{'id': e['id'], 'kind': e['kind'], 'label': e['label'], 'source_pins': e['source_pins']}
                             for e in _state(db, CATALOG, {}).values()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    import json
    sidecar = {'issue_id': identity, 'requirements_ref': record['ref'],
        'reply_command': 'report-agent commission-reply --project CASE --issue-id ' + identity + ' --file DECISION.json',
        'decision_shape': {'decision': 'resolve_requirements', 'requirements_ref': record['ref'],
                           'resolutions': [{'anchor_id': identity, 'note': ''} for identity in pending]},
        'pending': [{'anchor_id': a['id'], 'kind': a['kind'], 'section_id': a.get('section_id'),
                     'source': a['source'], 'parse_error': a.get('parse_error'),
                     'classification': record['payload'].get('classifications', {}).get(a['id'])}
                    for a in record['payload']['anchors'] if a['id'] in pending],
        'classification_shape': {'anchor_id': 'same anchor ID', 'entry_ids': [], 'capabilities': [], 'table_roles': []},
        'reviewed_entries': available_entries,
        'classification_note': 'For unclassified items, supply either eligible reviewed entry_ids or ordinary capabilities, with a written basis. Never type computational capabilities; choose reviewed entries. This decision does not approve a plan.',
        'decision_schema': RequirementDecision.model_json_schema()}
    path.with_suffix('.json').write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    commission_assertions.ask_checkpoint(workspace.store, actor, identity, 'requirements', identity,
        {k: checkpoint[k] for k in ('requirements_ref', 'anchor_ids', 'brief_path')})
    from .commission_plan import project_checkpoint_issue
    project_checkpoint_issue(workspace.store, identity, checkpoint['description'], checkpoint['source_ids'])
    return checkpoint


class RequirementResolution(Contract):
    anchor_id: str = Field(min_length=1)
    note: str = Field(min_length=1)
    classification: Classification | None = None


class RequirementDecision(Contract):
    decision: Literal['resolve_requirements']
    requirements_ref: Ref
    resolutions: list[RequirementResolution] = Field(min_length=1)


def reply_requirements(workspace, issue_id, decision):
    """Trusted operator CLI only. A requirement decision never grants writing authority."""
    from .content_store import ContentStore, Actor
    from .commission_requirements import read_requirements
    from .store import encode
    decision = RequirementDecision.model_validate(decision).model_dump(mode='json')
    cs = ContentStore(workspace.store)
    with workspace.store.run_lock(), workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        checkpoint = commission_assertions.checkpoint(db, 'requirements', issue_id)
        issues = issue_state.get_report_issues(db, [])
        issue = next((i for i in issues if i['id'] == issue_id), None)
        if not issue or not checkpoint or checkpoint['requirements_ref'] != decision['requirements_ref']:
            raise ActionRejected('REQUIREMENTS_CHECKPOINT_REPLY_STALE')
        answer = encode(decision)
        answered = commission_assertions.checkpoint_answer(db, 'requirements', issue_id)
        historical = legacy.get_commission_requirements_checkpoint(db, issue_id)
        if issue.get('decision_origin') == 'operator' and (historical or
                answered and issue.get('requirements_result_ref') == answered):
            if issue.get('decision') != answer:
                raise ActionRejected('REQUIREMENTS_CHECKPOINT_ALREADY_ANSWERED')
            return issue
        owner = Actor('operator', 'operator', 'requirements-checkpoint:' + issue_id)
        record = read_requirements(cs, decision['requirements_ref'], db=db)
        if not answered and read_requirements(cs, db=db)['ref'] != record['ref']:
            raise ActionRejected('REQUIREMENTS_CHECKPOINT_REPLY_STALE')
        selected = [r['anchor_id'] for r in decision['resolutions']]
        if len(set(selected)) != len(selected) or not set(selected) <= set(checkpoint['anchor_ids']):
            raise ActionRejected('REQUIREMENTS_RESOLUTION_ANCHOR_INVALID')
        payload = deepcopy(record['payload'])
        anchors = {a['id']: a for a in payload['anchors']}
        for resolution in decision['resolutions']:
            identity, note = resolution['anchor_id'], resolution['note']
            if not note.strip():
                raise ActionRejected('REQUIREMENTS_RESOLUTION_NOTE_REQUIRED')
            if enabled(cs.store) and identity not in payload.get('classifications', {}) and not resolution['classification']:
                raise ActionRejected('REQUIREMENTS_RESOLUTION_CLASSIFICATION_REQUIRED')
            if anchors[identity].get('parse_error'):
                payload.setdefault('parse_resolutions', {})[identity] = {'origin': 'operator', 'issue_id': issue_id, 'note': note}
            if resolution['classification']:
                if resolution['classification']['anchor_id'] != identity:
                    raise ActionRejected('REQUIREMENTS_CLASSIFICATION_TARGET_MISMATCH')
                value = _classifications(cs, db, record, [resolution['classification']], note)[0]
                payload.setdefault('classifications', {})[identity] = {**value, 'origin': 'operator', 'issue_id': issue_id, 'note': note}
        def prepare(db):
            return {'requirements_ref': save_revision(cs, db, owner, record['ref'], payload)}
        db.commit()
        try:
            prepared = cs.operation(owner, 'requirements-owner:' + issue_id, decision, prepare)
        except ActionRejected as exc:
            if str(exc) == 'OPERATION_CONFLICT':
                raise ActionRejected('REQUIREMENTS_CHECKPOINT_ALREADY_ANSWERED') from exc
            raise
        ref = prepared['result']['requirements_ref']
        current = read_requirements(cs)['ref']
        answered = commission_assertions.checkpoint_answer(workspace.store, 'requirements', issue_id)
        if current != decision['requirements_ref'] and answered != ref:
            raise ActionRejected('REQUIREMENTS_CHECKPOINT_REPLY_STALE')
        commission_assertions.answer_checkpoint(workspace.store, owner, issue_id, 'requirements', issue_id, ref)
        db.execute('BEGIN IMMEDIATE')
        issues = issue_state.get_report_issues(db, [])
        issue = next(i for i in issues if i['id'] == issue_id)
        if issue.get('requirements_result_ref') == ref and issue.get('decision_origin') == 'operator':
            if issue.get('decision') != answer:
                raise ActionRejected('REQUIREMENTS_CHECKPOINT_ALREADY_ANSWERED')
            return issue
        issue.update(decision=answer, decision_origin='operator', resolved=True, requirements_result_ref=ref)
        issue_state.set_report_issues(db, issues)
        _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
        _set(db, 'report_status', 'ready')
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('commission_requirement_decision', encode({'issue_id': issue_id, 'requirements_ref': ref})))
        return issue


def planning_tools(cs, actor):
    """Small independent judgments; prepared payloads and authority stay server-owned."""
    from .planning_assertions import planning_assertion_tools
    assertion_tools = planning_assertion_tools(cs, actor)

    def publish_planning_draft(operation_id: str) -> dict:
        """Publish a complete saved draft as a plan version for page-binding proposals.

        Returns plan_ref without asking for approval or authorizing writing.
        After proposing page bindings, submit_plan publishes the owner confirmation sheet.
        """
        return submit_plan(cs, actor(), operation_id)

    def read_planning_draft(collection: DRAFT_COLLECTIONS = 'summary',
            page: Annotated[int, Field(ge=1)] = 1, page_size: Annotated[int, Field(ge=1, le=10)] = 5,
            item_id: str = '', offset: Annotated[int, Field(ge=0)] = 0,
            characters: Annotated[int, Field(ge=1, le=3000)] = 3000,
            view_ref: str = '', gap_page: Annotated[int, Field(ge=1)] = 1) -> dict:
        """Read compact gaps first with counts; default returns no large draft bodies.

        Read details by collection/page or exact item_id. requirements rows contain
        anchor IDs, exact quotes, statuses and classifications. sections/objects retain
        exact citations; settings contains methods, tables and boundary by their keys.
        Pages contain bounded JSON text: concatenate next_offset chunks before decoding.
        Use the returned view_ref on every continuation; changed drafts require a fresh
        summary. next_gap_page explicitly continues large gap lists.
        Use propose_page_binding for object/indicator page applicability, record_conflict for disagreements, and ask
        for unresolved questions about planning inventory objects. Read
        page_bindings with the inventory object ID as item_id for applicability proposals; source_assertions retains historical source
        IDs; continue using its own view_ref. No tool order is required.
        """
        return read_draft_page(cs, actor(), collection, page, page_size, item_id, offset, characters, view_ref, gap_page)

    def set_status(operation_id: str, items: Annotated[list[RequirementStatusInput], Field(min_length=1)]) -> dict:
        """Set requirement statuses atomically. Every item passes the existing checks; any error refuses the whole list with indexed problems. Capabilities remain system-owned; reductions need owner confirmation."""
        return set_requirement_statuses(cs, actor(), operation_id, [i.model_dump(mode='json') for i in items])
    set_status.__name__ = 'set_requirement_status'

    def link(operation_id: str, anchor_id: str, entry_id: str, interpretation: str) -> dict:
        """Link one convention to an eligible reviewed entry ID. The system attaches its data and derives obligations; never transcribe methods, weights or tables."""
        return link_convention(cs, actor(), operation_id, anchor_id, entry_id, interpretation)
    link.__name__ = 'link_convention'

    def set_scope_boundary(operation_id: str, boundary: BoundaryInput) -> dict:
        """Save the boundary using document chainage or metres, an exact source quote, and a scope requirement anchor ID. Unique quotes get recorded source locators automatically. Object inclusion remains a separate judgment."""
        return save_item(cs, actor(), operation_id, 'boundary', boundary.model_dump(mode='json'))

    def set_planning_details(operation_id: str, details: PlanDetails) -> dict:
        """Save the commissioned inventory attribute names and deliverables; this does not submit or approve a plan."""
        return save_item(cs, actor(), operation_id, 'details', details.model_dump(mode='json'))

    def add_object(operation_id: str, items: Annotated[list[PlanningInventoryObject], Field(min_length=1)]) -> dict:
        """Add or revise objects atomically by stable IDs, retaining sources, unknowns and exclusion reasons. All problems are indexed; no partial object list is saved. Only the owner approves reductions."""
        return save_items(cs, actor(), operation_id, 'object', [i.model_dump(mode='json') for i in items])

    def add_section(operation_id: str, items: Annotated[list[PlanningSectionInput], Field(min_length=1)]) -> dict:
        """Save outline sections atomically; any invalid section refuses the entire list. Fixed PDF text uses template page/end-sentence selectors, fixed Word text exact template quotations; the system copies it. Derived sections bind saved result fields. No model-written fixed body or proof is accepted."""
        return save_items(cs, actor(), operation_id, 'section', [i.model_dump(mode='json') for i in items])

    def add_substitution(operation_id: str, section_id: str, substitution: PlanningSubstitution) -> dict:
        """Save a proposed document replacement for one section, with the customer's exact permission and source evidence. Requires final owner confirmation."""
        return save_item(cs, actor(), operation_id, 'substitution', {'section_id': section_id, 'substitution': substitution.model_dump(mode='json')})

    def add_reconciliation(operation_id: str, items: Annotated[list[PlanningReconciliationInput], Field(min_length=1)]) -> dict:
        """Add or revise source comparisons atomically by stable IDs. Preserve factual differences and interpretations; any invalid comparison refuses the whole list with indexed problems."""
        return save_items(cs, actor(), operation_id, 'reconciliation', [i.model_dump(mode='json') for i in items])

    def add_question(operation_id: str, items: Annotated[list[PlanningQuestion], Field(min_length=1)]) -> dict:
        """Add, revise or answer questions atomically by stable IDs. Any invalid question refuses the whole list. This records planning progress, not owner authorization."""
        return save_items(cs, actor(), operation_id, 'question', [i.model_dump(mode='json') for i in items])

    def set_section_judgment(operation_id: str, judgment: SectionJudgment) -> dict:
        """Attach section evidence and notes; outline, fixed text and result bindings are system-owned."""
        return save_item(cs, actor(), operation_id, 'section_judgment', judgment.model_dump(mode='json', exclude_unset=True))

    def set_candidate_disposition(operation_id: str, disposition: CandidateDisposition) -> dict:
        """State included or proposed exclusion with a reason. Proposed exclusion always creates an owner question; owner records are attached by the system."""
        return save_item(cs, actor(), operation_id, 'disposition', disposition.model_dump(mode='json', exclude_none=True))

    def resolve_skeleton_choice(operation_id: str, question_id: str, expected_digest: str, choice_id: str = '', selection: SourceSpan | None = None) -> dict:
        """Answer one current structural ambiguity by its offered source-span ID. If no heading match is offered, select an actual template heading and its exact next-heading boundary with selection. No replacement text or structure is accepted."""
        from .commission_skeleton import resolve_skeleton_question
        return resolve_skeleton_question(cs, actor(), operation_id, question_id, expected_digest, choice_id, selection.model_dump(mode='json') if selection else None)

    from .commission_carryover import CarriedReview
    def review_carried_items(operation_id: str, reviews: list[CarriedReview]) -> dict:
        """Recheck current imported judgments against new sources; acknowledge each exact digest as confirmed or revised with a reason. No prior approval is carried."""
        from .commission_carryover import review_carried_items as review
        return review(cs, actor(), operation_id, [r.model_dump(mode='json') for r in reviews])

    if plan_inputs.get_skeleton(cs.store):
        return assertion_tools + [expose(f) for f in [publish_planning_draft, read_planning_draft, set_scope_boundary, add_object, set_section_judgment,
            set_candidate_disposition, resolve_skeleton_choice, add_substitution, add_reconciliation, add_question, review_carried_items]]
    return assertion_tools + [expose(function) for function in [publish_planning_draft, read_planning_draft, set_status, link, set_scope_boundary, set_planning_details,
            add_object, add_section, add_substitution, add_reconciliation, add_question]]


def install_prepared_planning(cs, source_refs):
    """Host preparation loads reviewed pilot data only when the original hashes match."""
    import json
    import hashlib
    from importlib.resources import files
    from .method_pack import bind_guideline
    from .table_spec import read_prepared_tables
    from .commission_requirements import read_requirements
    resources = files('report_agent').joinpath('methods')
    tables = json.loads(resources.joinpath('high_slope_tables.json').read_text(encoding='utf-8'))
    profile = json.loads(resources.joinpath('pilot_planning.json').read_text(encoding='utf-8'))
    sources = {cs.read(ref)['payload']['file_digest']: ref for ref in source_refs}
    bound = {role: sources.get(sha) for role, sha in tables['source_hashes'].items()}
    if all(bound.values()):
        guide, template = bound['guideline'], bound['template']
        gh, th = tables['source_hashes']['guideline'], tables['source_hashes']['template']
        pack = bind_guideline(guide, gh, template, th)
        specs = read_prepared_tables(guide, gh, template, th)
        pins = [{'ref': guide, 'file_digest': gh}, {'ref': template, 'file_digest': th}]
        entries = [{**entry, 'source_pins': pins,
                    **({'table_specs': specs} if entry['kind'] == 'table' else {'method_pack': pack})}
                   for entry in profile['entries']]
        install_reviewed_entries(cs, entries)
    record = read_requirements(cs)
    classifications = []
    with cs.store.connect() as db:
        offered = _state(db, CATALOG, {})
        for anchor in record['payload']['anchors']:
            source = cs._read(db, anchor['source']['source_ref'])['payload']
            matches = [row for row in profile['classifications'] if row['source_hash'] == source['file_digest'] and
                       row['locator'] == anchor['source']['locator'] and row['kind'] == anchor['kind'] and
                       row['quote_hash'] == hashlib.sha256(anchor['source']['quote'].encode()).hexdigest()]
            if len(matches) == 1 and set(matches[0]['entry_ids']) <= offered.keys():
                classifications.append({'anchor_id': anchor['id'], **{k: matches[0][k] for k in ('entry_ids', 'capabilities', 'table_roles')}})
    if classifications:
        install_classifications(cs, classifications, profile['review_note'])
    for text_profile in profile['text_profiles']:
        ref = sources.get(text_profile['file_digest'])
        if not ref:
            continue
        source = cs.read(ref)['payload']
        with cs.store.connect() as db:
            lines = [line.strip() for row in db.execute('SELECT text FROM source_blocks WHERE source_id=?', (source['source_id'],)) for line in row[0].splitlines()]
        headers = sorted({line for line in lines if hashlib.sha256(line.encode()).hexdigest() in text_profile['header_line_hashes']})
        if len(headers) != len(text_profile['header_line_hashes']):
            raise ActionRejected('PREPARED_TEXT_HEADER_NOT_FOUND')
        install_text_profile(cs, {k: v for k, v in text_profile.items() if k != 'header_line_hashes'} |
                             {'source_ref': ref, 'header_lines': headers})
    return {'classification_count': len(classifications), 'requirements_ref': read_requirements(cs)['ref']}
