"""Versioned commission proposals; only operator replies authorize writing or reductions."""
from pathlib import Path
import json
import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content_models import Contract, Ref, SourceCitation, InventoryObject, refs_in
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode
from .method_pack import MethodPack
from .table_spec import TableSpec, compile_header, validate_table_specs


class LiteralReplacement(Contract):
    old: str = Field(min_length=1)
    new: str = Field(min_length=1)


class ResultBinding(Contract):
    old: str = Field(min_length=1, description='Unique exact template passage to replace, retained in the approved plan.')
    object_id: str | None = None
    field: Literal['total', 'level', 'assessment_text', 'object_count', 'level_count']
    level: str | None = None

    @model_validator(mode='after')
    def target(self):
        aggregate = self.field in ('object_count', 'level_count')
        if aggregate != (self.object_id is None) or (not aggregate and not self.object_id.strip()):
            raise ValueError('RESULT_BINDING_TARGET_REQUIRED')
        if (self.field == 'level_count') != (self.level is not None):
            raise ValueError('RESULT_BINDING_LEVEL_REQUIRED')
        return self


class ScopeBoundary(Contract):
    start_meter: str
    end_meter: str
    source: SourceCitation
    customer_basis: SourceCitation | None = None
    expected_object_count: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode='after')
    def ordered(self):
        from .method_pack import number
        if number(self.start_meter) >= number(self.end_meter) or not self.source.quote.strip():
            raise ValueError('COMMISSION_BOUNDARY_SOURCE_AND_ORDER_REQUIRED')
        return self


class MethodConvention(Contract):
    key: str = Field(min_length=1)
    source: SourceCitation | None
    interpretation: str = Field(min_length=1)
    status: Literal['specified', 'default_unagreed']
    method_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)

    @model_validator(mode='after')
    def authority(self):
        if (self.status == 'specified') != (self.source is not None):
            raise ValueError('METHOD_CONVENTION_SOURCE_OR_DEFAULT_REQUIRED')
        if self.source and not self.source.quote.strip():
            raise ValueError('METHOD_CONVENTION_EXACT_QUOTE_REQUIRED')
        return self


class SourceSubstitution(Contract):
    # shortcut: replacements only; add a distinct resolution when an original document is later located.
    requested_source: str = Field(min_length=1)
    replacement_sources: list[SourceCitation] = Field(min_length=1)
    customer_basis: SourceCitation
    reason: str = Field(min_length=1, description='Agent interpretation of why these actual sources fit the commissioned scope; separate from the customer quotation.')


class SourceView(Contract):
    source_indexes: list[Annotated[int, Field(strict=True, ge=0)]] = Field(min_length=1)
    page: int = Field(strict=True, ge=1)
    crop: list[Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=1)]] = Field(min_length=4, max_length=4)

    @model_validator(mode='after')
    def ordered(self):
        if self.source_indexes != list(range(self.source_indexes[0], self.source_indexes[0] + len(self.source_indexes))):
            raise ValueError('SOURCE_VIEW_CONTIGUOUS_INDEXES_REQUIRED')
        if not (self.crop[0] < self.crop[2] and self.crop[1] < self.crop[3]):
            raise ValueError('SOURCE_VIEW_CROP_INVALID')
        return self


class SectionPlan(Contract):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: Literal['fixed', 'extracted', 'derived']
    outline: SourceCitation
    sources: list[SourceCitation]
    pending_sources: list[str] = Field(default_factory=list,
        description='Retain named source obligations, including those resolved by a cited substitution; unresolved names block approval.')
    source_substitutions: list[SourceSubstitution] = Field(default_factory=list, exclude_if=lambda value: not value,
        description='Section-specific proposed replacements backed by exact customer quotations. Ordinary owner confirmation of this plan is still required.')
    text: str = ''
    extraction: dict | None = Field(default=None, exclude_if=lambda value: value is None)
    substitutions: list[str] = Field(default_factory=list)
    replacements: list[LiteralReplacement] = Field(default_factory=list, exclude_if=lambda value: not value)
    result_bindings: list[ResultBinding] = Field(default_factory=list, exclude_if=lambda value: not value)
    source_views: list[SourceView] = Field(default_factory=list, exclude_if=lambda value: not value,
        description='Fixed source-table excerpts rendered from the cited PDF region; quotes remain canonical. Review crop completeness in the existing checkpoint/layout review.')
    derived_from: list[str] = Field(default_factory=list)
    rule: str = ''
    examples: list[SourceCitation] = Field(default_factory=list,
        description='Outline drawing examples identify what to inspect; they are not project facts.')

    @model_validator(mode='after')
    def basis(self):
        if not self.sources and not self.pending_sources:
            raise ValueError('SECTION_SOURCE_OR_PENDING_SOURCE_REQUIRED')
        if any(not name.strip() for name in self.pending_sources):
            raise ValueError('SECTION_PENDING_SOURCE_NAME_REQUIRED')
        names = [s.requested_source for s in self.source_substitutions]
        if len(set(self.pending_sources)) != len(self.pending_sources) or len(set(names)) != len(names):
            raise ValueError('SECTION_SOURCE_RESOLUTION_DUPLICATE')
        available = {(s.source_ref.key(), s.locator) for s in self.sources}
        for substitution in self.source_substitutions:
            if substitution.requested_source not in self.pending_sources:
                raise ValueError('SECTION_SUBSTITUTION_SOURCE_NOT_REQUESTED')
            if not substitution.customer_basis.quote.strip() or not substitution.reason.strip():
                raise ValueError('SECTION_SUBSTITUTION_QUOTED_BASIS_REQUIRED')
            if any((s.source_ref.key(), s.locator) not in available for s in substitution.replacement_sources):
                raise ValueError('SECTION_SUBSTITUTION_REPLACEMENT_NOT_IN_PLAN')
        if not self.outline.quote.strip():
            raise ValueError('SECTION_OUTLINE_QUOTE_REQUIRED')
        if self.kind == 'fixed' and not self.text.strip() and not (self.sources and all(s.quote.strip() for s in self.sources)):
            raise ValueError('FIXED_SECTION_TEXT_REQUIRED')
        if self.kind == 'derived' and (not self.derived_from or not self.rule.strip()):
            raise ValueError('DERIVED_SECTION_RULE_REQUIRED')
        last = -1
        for view in self.source_views:
            if self.kind != 'fixed' or view.source_indexes[0] <= last or view.source_indexes[-1] >= len(self.sources):
                raise ValueError('SOURCE_VIEW_FIXED_ORDERED_SOURCES_REQUIRED')
            selected = [self.sources[i] for i in view.source_indexes]
            if any(c.source_ref != selected[0].source_ref or not c.quote.strip()
                   or not re.fullmatch(rf'page {view.page}(?:;.*)?', c.locator) for c in selected):
                raise ValueError('SOURCE_VIEW_SAME_SOURCE_PAGE_REQUIRED')
            last = view.source_indexes[-1]
        return self


class Convention(Contract):
    source: SourceCitation
    interpretation: str = Field(description='Agent interpretation, separate from the original customer quotation.')
    requirement_anchor_id: str | None = Field(default=None, exclude_if=lambda value: value is None)


class Reconciliation(Contract):
    sources: list[SourceCitation] = Field(min_length=2)
    result: str = Field(min_length=1)
    differences: list[str]


class CommissionPlan(Contract):
    requirements_ref: Ref | None = Field(default=None, exclude_if=lambda value: value is None)
    sections: list[SectionPlan] = Field(min_length=1)
    inventory_attributes: list[str] = Field(min_length=1,
        description='Required object attributes from this commission; record every one, using explicit unknowns rather than omissions.')
    objects: list[InventoryObject] = Field(min_length=1)
    conventions: list[Convention]
    deliverables: list[str] = Field(min_length=1)
    reconciliations: list[Reconciliation] = Field(min_length=1)
    open_questions: list[str] = Field(description='Only questions the supplied materials cannot settle.')
    method_pack: MethodPack | None = Field(default=None, exclude_if=lambda value: value is None)
    table_specs: dict[str, TableSpec] = Field(default_factory=dict, exclude_if=lambda value: not value)
    method_conventions: list[MethodConvention] = Field(default_factory=list, exclude_if=lambda value: not value)
    format_source: SourceCitation | None = Field(default=None, exclude_if=lambda value: value is None)
    scope_boundary: ScopeBoundary | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode='after')
    def complete_inventory(self):
        if self.table_specs:
            from .risk_scoring import TABLE_RECORD_CONTRACT
            validate_table_specs(self.table_specs, TABLE_RECORD_CONTRACT)
            if not self.method_pack or not {'ranking', 'evaluation'} <= set(self.table_specs):
                raise ValueError('ASSESSMENT_TABLE_SPECS_REQUIRE_METHOD_AND_BOTH_ROLES')
            if any(not i.presentation_rows for i in self.method_pack.indicators):
                raise ValueError('ASSESSMENT_TABLE_SOURCE_ROWS_REQUIRED')
            if not self.method_pack.display_labels.get('total', '').strip():
                raise ValueError('ASSESSMENT_TABLE_TOTAL_LABEL_REQUIRED')
            for role, field in (('ranking', 'indicator'), ('evaluation', 'value')):
                spec = self.table_specs[role]
                if (list(spec.column_bindings.values()).count(field) != 1 or
                        [g.binding for g in spec.row_groups].count(role + '.rows') != 1):
                    raise ValueError('ASSESSMENT_TABLE_ANNOTATION_BINDING_REQUIRED: ' + role)
                key = next(k for k, v in spec.column_bindings.items() if v == field)
                if any(rule.axis == 'horizontal' and key in rule.columns[1:]
                       for group in spec.row_groups if group.binding == role + '.rows' for rule in group.merges):
                    raise ValueError('ASSESSMENT_TABLE_ANNOTATION_ANCHOR_MERGED_AWAY: ' + role)
            levels = {b.level for b in self.method_pack.risk_bands}
            if set(self.table_specs['evaluation'].level_labels) != levels:
                raise ValueError('ASSESSMENT_TABLE_LEVEL_LABELS_REQUIRED')
        elif self.method_pack and any(getattr(i, 'presentation_rows', []) for i in self.method_pack.indicators):
            raise ValueError('ASSESSMENT_TABLE_SPECS_REQUIRED')
        if not self.method_pack and any(s.source_views for s in self.sections):
            raise ValueError('SOURCE_VIEWS_REQUIRE_REVIEWED_METHOD_PLAN')
        names = self.inventory_attributes
        if any(not n.strip() for n in names) or len(set(names)) != len(names):
            raise ValueError('COMMISSION_INVENTORY_ATTRIBUTE_CONTRACT_INVALID')
        for obj in self.objects:
            actual = [a.name for a in obj.attributes]
            if len(actual) != len(set(actual)) or set(actual) != set(names):
                raise ValueError('COMMISSION_INVENTORY_ATTRIBUTES_INCOMPLETE: ' + obj.object_id)
        return self


def fixed_source_views(section):
    def view_text(view):
        text = '\n'.join(section['sources'][i]['quote'] for i in view['source_indexes'])
        if section.get('extraction'):
            from .commission_planning import normalize_text
            text = normalize_text(text, view['page'], section['extraction']['normalization']['profile'])
        return text
    return [{'text': view_text(view),
             'source_ref': section['sources'][view['source_indexes'][0]]['source_ref'],
             'page': view['page'], 'crop': view['crop']} for view in section.get('source_views', [])]


def fixed_section_text(section):
    """Exact quoted source spans and owner-reviewed literal substitutions only."""
    if not section['sources'] or any(not c.get('quote', '').strip() for c in section['sources']):
        raise ActionRejected('FIXED_SECTION_EXACT_SOURCE_SPANS_REQUIRED: ' + section['section_id'])
    text = (section['extraction']['text'] if section.get('extraction') else
            '\n'.join(c['quote'] for c in section['sources']))
    views = fixed_source_views(section)
    if any(text.count(view['text']) != 1 for view in views):
        raise ActionRejected('FIXED_SOURCE_VIEW_PASSAGE_AMBIGUOUS')
    seen = set()
    for replacement in section.get('replacements', []):
        old, new = replacement['old'], replacement['new']
        if old in seen or old not in text:
            raise ActionRejected('FIXED_SECTION_REPLACEMENT_INVALID: ' + section['section_id'])
        for view in views:
            start = text.index(view['text'])
            end = start + len(view['text'])
            if any(match.start() < end and match.end() > start for match in re.finditer(re.escape(old), text)):
                raise ActionRejected('FIXED_SOURCE_VIEW_REPLACEMENT_OVERLAP')
        seen.add(old)
        text = text.replace(old, new)
        if any(text.count(view['text']) != 1 for view in views):
            raise ActionRejected('FIXED_SOURCE_VIEW_PASSAGE_AMBIGUOUS')
    return text


def method_questions(plan):
    pack = plan.get('method_pack')
    if not pack:
        return []
    bindings = [b for b in plan.get('method_conventions', []) if b['key'] == 'weights']
    if len(bindings) != 1:
        return ['权重约定未链接唯一方法包条目']
    binding = bindings[0]
    table = next((t for t in pack['weight_tables'] if t['id'] == binding['strategy_id']), None)
    if binding['method_id'] != pack['method_id'] or table is None or not any(r['indicator_count'] == len(pack['indicators']) for r in table['rows']):
        return ['权重约定没有适用的方法包条目，不能临时编造']
    return []


def outside_boundary(plan, obj):
    """Only fully sourced mileage ranges can prove that an object is outside."""
    boundary = plan.get('scope_boundary')
    if not boundary:
        return False
    from decimal import Decimal
    from .method_pack import number
    values = [v for a in obj['attributes'] if a['name'] in ('mileage', '里程') for v in a['values']]
    ranges = []
    for value in values:
        if not value.get('source') or not value.get('value'):
            return False
        points = re.findall(r'(?:[A-Z]*K)?(\d+)\+(\d+(?:\.\d+)?)', value['value'], re.I)
        if len(points) != 2:
            return False
        start, end = [Decimal(k) * 1000 + Decimal(m) for k, m in points]
        if start > end:
            return False
        ranges.append((start, end))
    return bool(ranges) and all(end < number(boundary['start_meter']) or start > number(boundary['end_meter']) for start, end in ranges)


def boundary_questions(plan):
    boundary = plan.get('scope_boundary')
    if not boundary:
        return []
    objects = [o for o in plan['objects'] if not outside_boundary(plan, o)]
    questions = []
    if boundary.get('expected_object_count') is not None and len(objects) != boundary['expected_object_count']:
        questions.append(f"合同范围内对象数量{len(objects)}与约定{boundary['expected_object_count']}不一致，需确认")
    if any(o['included'] and outside_boundary(plan, o) for o in plan['objects']):
        questions.append('合同边界外对象被列为纳入，需更正对象清单')
    return questions


class Reduction(Contract):
    object_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class OwnerDecision(Contract):
    plan_ref: Ref
    requirements_ref: Ref | None = Field(default=None, exclude_if=lambda value: value is None)
    approved: bool = Field(strict=True)
    corrections: str
    reductions: list[Reduction]

    @model_validator(mode='after')
    def unambiguous(self):
        if (self.approved and self.corrections.strip()) or (not self.approved and not self.corrections.strip()):
            raise ValueError('COMMISSION_APPROVAL_OR_CORRECTIONS_REQUIRED')
        if not self.approved and self.reductions:
            raise ValueError('COMMISSION_REDUCTION_REQUIRES_APPROVAL')
        if any(not r.reason.strip() for r in self.reductions):
            raise ValueError('COMMISSION_REDUCTION_REASON_REQUIRED')
        return self


def enabled(store):
    from .handoff_release import manifest
    return manifest(store).get('commission_checkpoint_required') is True


def _state(db, key, default=None):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(value)))


def unresolved_sources(section):
    resolved = {s['requested_source'] for s in section.get('source_substitutions', [])}
    return [name for name in section['pending_sources'] if name not in resolved]


def read_plan(store):
    cs = ContentStore(store)
    with store.connect() as db:
        ref = _state(db, 'commission_plan')
        if not ref:
            return None
        record = cs._read(db, ref)
        confirmation = _state(db, 'commission_confirmation')
        if confirmation:
            decision = cs._read(db, confirmation)
            if (decision['owner_id'] == 'operator' and decision['payload'].get('approved') is True
                    and decision['payload'].get('plan_ref') == ref):
                record['commission_confirmation_ref'] = confirmation
                requirements = decision['payload'].get('required_material_issues')
                record['required_material_issues'] = (requirements if requirements is not None else
                    required_material_issues(cs, db, ref, record['payload']))
                path = _checklist_path(confirmation)
                if (store.root / path).is_file():
                    record['confirmation_checklist_path'] = path
        return record


def required_material_issues(cs, db, plan_ref, plan):
    """Derive obligations from retained plan facts, independently of writer selections."""
    def sources(citations):
        result = []
        for citation in citations:
            source = cs._read(db, citation['source_ref'])['payload']
            title = source.get('source_metadata', {}).get('title')
            if not title or not title.strip():
                raise ActionRejected('MATERIAL_ISSUE_READABLE_SOURCE_TITLE_REQUIRED')
            locator = citation['locator']
            if match := re.fullmatch(r'page ([1-9][0-9]*)(?:;.*)?', locator):
                locator = f'PDF第{match[1]}页'
            elif locator == 'manifest text':
                locator = '全文'
            elif match := re.fullmatch(r'line ([1-9][0-9]*)', locator):
                locator = f'第{match[1]}行'
            item = {'document': title, 'page': locator}
            if item not in result:
                result.append(item)
        return result

    issues = []
    def add(origin, label, basis, citations, question):
        issues.append({'id': digest([plan_ref, origin]), 'kind': 'conflict',
            'object_label': label, 'basis': basis, 'sources': sources(citations), 'question': question})

    for index, reconciliation in enumerate(plan.get('reconciliations', [])):
        for position, difference in enumerate(reconciliation['differences']):
            add(['reconciliation', index, position], '资料核对', difference,
                reconciliation['sources'], '请确认该资料差异及报告采用的解释。')
    for obj in plan['objects']:
        for attribute in obj['attributes']:
            values = attribute['values']
            if len({v['value'] for v in values}) <= 1:
                continue
            basis = attribute['name'] + '：' + '；'.join(
                (v['value'] if v['value'] is not None else '未知') + '（' + v['reason'] + '）' for v in values)
            add(['inventory', obj['object_id'], attribute['name']], obj['label'], basis,
                [v['source'] for v in values if v['source'] is not None],
                '请确认' + attribute['name'] + '的采用值及其依据。')
    return issues


def _citations(value):
    if isinstance(value, dict):
        if 'source_ref' in value and 'locator' in value:
            yield value
        else:
            for child in value.values():
                yield from _citations(child)
    elif isinstance(value, list):
        for child in value:
            yield from _citations(child)


def _validate_sources(cs, db, actor, plan):
    from .deliverables import source_authority
    records = {}
    for citation in _citations(plan):
        ref = citation['source_ref']
        key = Ref.model_validate(ref).key()
        source = records.setdefault(key, cs._read(db, ref))
        if ref['type'] != 'SourceArtifact':
            raise ActionRejected('COMMISSION_SOURCE_ARTIFACT_REQUIRED')
        payload = source['payload']
        rows = list(db.execute('SELECT locator,text FROM source_blocks WHERE source_id=?',
                               (payload['source_id'],)))
        located = [text for loc, text in rows if loc == citation['locator'] or loc.startswith(citation['locator'] + ';')]
        quote = citation.get('quote', '')
        if quote and quote not in ''.join(located):
            raise ActionRejected('COMMISSION_QUOTE_NOT_AT_SOURCE_LOCATION')
        if not located:
            # Image-only PDF pages have no extracted text; verify physical page existence.
            page = re.fullmatch(r'page ([1-9][0-9]*)', citation['locator'])
            if page is None or quote:
                raise ActionRejected('COMMISSION_SOURCE_LOCATION_UNAVAILABLE')
            from .document_tools import _original
            from .workspace import Workspace
            from pypdf import PdfReader
            from io import BytesIO
            _, data = _original(Workspace(cs.store), payload['source_id'])
            if int(page[1]) > len(PdfReader(BytesIO(data)).pages):
                raise ActionRejected('COMMISSION_SOURCE_PAGE_OUTSIDE_DOCUMENT')
    source_authority(cs, db, actor, list(records.values()))


def save_plan(cs, actor, operation_id, plan):
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: commission proposal owner')
    if not enabled(cs.store):
        raise ActionRejected('COMMISSION_CHECKPOINT_NOT_ENABLED')
    from .commission_requirements import require_complete
    require_complete(cs, plan)
    plan = CommissionPlan.model_validate(plan).model_dump()
    ids = [o['object_id'] for o in plan['objects']]
    sections = [s['section_id'] for s in plan['sections']]
    if len(set(ids)) != len(ids) or len(set(sections)) != len(sections):
        raise ActionRejected('COMMISSION_DUPLICATE_OBJECT_OR_SECTION')
    if any(not set(s['derived_from']) <= set(sections) or s['section_id'] in s['derived_from'] for s in plan['sections']):
        raise ActionRejected('COMMISSION_DERIVED_SECTION_INVALID')
    dependencies = {s['section_id']: s['derived_from'] for s in plan['sections']}
    visited, active = set(), set()
    def visit(section):
        if section in active:
            raise ActionRejected('COMMISSION_DERIVED_SECTION_CYCLE')
        if section not in visited:
            active.add(section)
            for dependency in dependencies[section]:
                visit(dependency)
            active.remove(section)
            visited.add(section)
    for section in sections:
        visit(section)
    if any(not c['source']['quote'].strip() for c in plan['conventions']):
        raise ActionRejected('COMMISSION_CONVENTION_QUOTE_REQUIRED')
    def save(db):
        require_complete(cs, plan, db=db)
        _validate_sources(cs, db, actor, plan)
        roles = _state(db, 'commission_source_roles', {})
        customer_sources = {r['id'] for r in (roles or {}).values() if r['purpose'] == 'commission'}
        questions = method_questions(plan) + boundary_questions(plan)
        boundary = plan.get('scope_boundary')
        if boundary:
            numeric_id = cs._read(db, boundary['source']['source_ref'])['payload']['source_id']
            basis = boundary.get('customer_basis') or boundary['source']
            if (not basis.get('quote', '').strip()
                    or cs._read(db, basis['source_ref'])['payload']['source_id'] not in customer_sources):
                raise ActionRejected('COMMISSION_BOUNDARY_CUSTOMER_SELECTION_REQUIRED')
            if numeric_id not in customer_sources:
                factual = {Ref.model_validate(c['source_ref']).key() for s in plan['sections'] if s['kind'] == 'extracted' for c in s['sources']}
                method_sources = {Ref.model_validate(c['source_ref']).key() for c in (plan.get('method_pack') or {}).get('sources', [])}
                template_ids = {r['id'] for r in roles.values() if r['purpose'] == 'template'}
                if (Ref.model_validate(boundary['source']['source_ref']).key() not in factual - method_sources
                        or numeric_id in template_ids):
                    raise ActionRejected('COMMISSION_BOUNDARY_FACTUAL_SOURCE_REQUIRED')
        if plan.get('method_pack'):
            from .method_pack import reviewed_method_questions
            questions += reviewed_method_questions(cs, db, plan['method_pack'])
            if plan.get('format_source'):
                from .g3_export import FORMAT_SOURCE_SHA256
                if cs._read(db, plan['format_source']['source_ref'])['payload']['file_digest'] != FORMAT_SOURCE_SHA256:
                    questions.append('格式标准没有对应的已审查排版能力，不能开始编写')
            for binding in plan.get('method_conventions', []):
                if binding['status'] == 'specified':
                    source = binding['source']
                    if (cs._read(db, source['source_ref'])['payload']['source_id'] not in customer_sources
                            or source not in [c['source'] for c in plan['conventions']]):
                        raise ActionRejected('METHOD_CONVENTION_REQUIRES_CUSTOMER_SOURCE_AND_QUOTE')
            for section in plan['sections']:
                if section['kind'] == 'fixed':
                    template_ids = {r['id'] for r in roles.values() if r['purpose'] == 'template'}
                    if any(cs._read(db, c['source_ref'])['payload']['source_id'] not in template_ids for c in section['sources']):
                        raise ActionRejected('FIXED_SECTION_TEMPLATE_SOURCE_REQUIRED')
                    expected = fixed_section_text(section)
                    if section['text'] and section['text'] != expected:
                        raise ActionRejected('FIXED_SECTION_DIFFERS_FROM_SOURCE: ' + section['section_id'])
                    section['text'] = expected
        for section in plan['sections']:
            for substitution in section.get('source_substitutions', []):
                basis = cs._read(db, substitution['customer_basis']['source_ref'])
                if basis['payload']['source_id'] not in customer_sources:
                    raise ActionRejected('COMMISSION_SUBSTITUTION_REQUIRES_CUSTOMER_SOURCE')
        if roles:
            if any(cs._read(db, c['source']['source_ref'])['payload']['source_id'] not in customer_sources
                   for c in plan['conventions']):
                raise ActionRejected('COMMISSION_CONVENTION_REQUIRES_CUSTOMER_SOURCE')
        old_ref = _state(db, 'commission_plan')
        old = cs._read(db, old_ref) if old_ref else None
        current_sections = {s['section_id']: s for s in plan['sections']}
        for section in old['payload']['sections'] if old else []:
            if not set(section['pending_sources']) <= set(current_sections.get(section['section_id'], {}).get('pending_sources', [])):
                raise ActionRejected('COMMISSION_SOURCE_OBLIGATION_MUST_BE_RETAINED')
        prior = {cs._read(db, r)['payload']['inventory_object']['object_id']: cs._read(db, r)
                 for r in old['payload']['inventory_refs']} if old else {}
        if not prior.keys() <= set(ids):
            raise ActionRejected('COMMISSION_OBJECT_REMOVAL_REQUIRES_RETAINED_RECORD')
        inventory = []
        for obj in plan['objects']:
            previous = prior.get(obj['object_id'])
            payload = {'text': obj['label'] + ': ' + obj['reason'], 'origin': obj['origin'],
                       'scope': 'assessment object', 'inventory_object': obj}
            if previous and previous['payload'] == payload:
                inventory.append(previous['ref'])
            else:
                inventory.append(cs._insert(db, actor, 'Requirement', payload,
                    **({'id': previous['ref']['id'], 'version': previous['ref']['version'] + 1,
                        'previous_ref': previous['ref']} if previous else {})))
        ref = cs._insert(db, actor, 'CommissionPlan', {**plan, 'inventory_refs': inventory,
            **({'method_questions': questions} if plan.get('method_pack') or plan.get('scope_boundary') else {})},
            **({'id': old_ref['id'], 'version': old_ref['version'] + 1, 'previous_ref': old_ref} if old_ref else {}))
        _set(db, 'commission_plan', ref)
        return {'plan_ref': ref, 'inventory_refs': inventory}
    return cs.operation(actor, operation_id, {'commission_plan': plan}, save)


def _confirmed(cs, db):
    ref = _state(db, 'commission_plan')
    confirmation = _state(db, 'commission_confirmation')
    if not ref or not confirmation:
        raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_REQUIRED')
    decision = cs._read(db, confirmation)
    plan = cs._read(db, ref)
    from .commission_requirements import require_complete, enabled as requirements_enabled
    require_complete(cs, plan['payload'], db=db)
    if requirements_enabled(cs.store) and decision['payload'].get('requirements_ref') != plan['payload'].get('requirements_ref'):
        raise ActionRejected('COMMISSION_REQUIREMENTS_CONFIRMATION_REQUIRED')
    if (decision['owner_id'] != 'operator' or decision['payload'].get('plan_ref') != ref
            or decision['payload'].get('approved') is not True):
        raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_STALE')
    return plan, decision


def assert_writing_allowed(cs, db, actor):
    if not enabled(cs.store):
        return None
    plan, _ = _confirmed(cs, db)
    if actor.role != 'writer':
        raise ActionForbidden('FORBIDDEN: commissioned writing belongs to assigned writer')
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    payload = task['payload']
    if (actor.id != 'content:writer:' + actor.task_id or payload.get('role') != 'writer'
            or payload.get('commission_plan_ref') != plan['ref'] or not payload.get('section_ids')):
        raise ActionRejected('COMMISSION_WRITER_TASK_STALE_OR_UNASSIGNED')
    if not set(payload['section_ids']) <= {s['section_id'] for s in plan['payload']['sections']}:
        raise ActionRejected('COMMISSION_SECTION_NOT_IN_PLAN')
    return plan


def writer_assignment(cs, db, section_ids):
    plan, _ = _confirmed(cs, db)
    if not section_ids or len(set(section_ids)) != len(section_ids):
        raise ActionRejected('COMMISSION_SECTION_ASSIGNMENT_REQUIRED')
    selected = [s for s in plan['payload']['sections'] if s['section_id'] in section_ids]
    if len(selected) != len(section_ids):
        raise ActionRejected('COMMISSION_SECTION_NOT_IN_PLAN')
    return {'commission_plan_ref': plan['ref'], 'section_ids': section_ids,
            'section_plan': selected, 'customer_conventions': plan['payload']['conventions']}


def _table_spec_lines(specs, source_read):
    lines = []
    for role, spec in specs.items():
        lines += ['', '## 表型确认：' + spec['table_type'], '',
                  f"- 用途：{role}；版本：{spec['version']}；规格摘要：{digest(spec)}",
                  '- 以下表头由规格渲染；请与所引原表核对。本次确认后同一表型在本计划内复用。']
        header = compile_header(spec)
        lines += ['<table>']
        from html import escape
        spans = {(m['start_row'], m['start_col']): m for m in header['header_merges']}
        covered = {(r, c) for m in header['header_merges']
                   for r in range(m['start_row'], m['end_row'] + 1)
                   for c in range(m['start_col'], m['end_col'] + 1)
                   if (r, c) != (m['start_row'], m['start_col'])}
        for r, row in enumerate(header['header_rows']):
            cells = []
            for c, text in enumerate(row):
                if (r, c) in covered:
                    continue
                span = spans.get((r, c), {'end_row': r, 'end_col': c})
                cells.append(f'<th rowspan="{span["end_row"] - r + 1}" colspan="{span["end_col"] - c + 1}">{escape(text)}</th>')
            lines.append('<tr>' + ''.join(cells) + '</tr>')
        lines += ['</table>', '', '- 标题格式：' + spec['caption_pattern']]
        for citation in spec['sources']:
            source = source_read(citation['source_ref'])
            lines.append('- 原表：' + source['source_metadata'].get('title', '') + ' / ' + citation['locator'])
    return lines


def request_checkpoint(workspace):
    cs = ContentStore(workspace.store)
    record = read_plan(workspace.store)
    if not record:
        raise ActionRejected('COMMISSION_PLAN_REQUIRED')
    plan, ref = record['payload'], record['ref']
    from .commission_requirements import require_complete, enabled as requirements_enabled, read_requirements
    require_complete(cs, plan)
    path = workspace.store.root / 'outputs' / ('commission-checkpoint-' + digest(ref) + '.md')
    lines = ['# 编制计划确认', '', '请确认本版本计划，或提出修改意见。',
             '代理建议的排除不等于范围缩减；缩减须由提交者明确确认并说明原因。', '', '## 评估对象', '']
    if requirements_enabled(workspace.store):
        requirements = read_requirements(cs, plan['requirements_ref'])
        lines += ['## 委托要求确认', '', '本次批准同时确认此版本要求记录及明确列出的不适用项。',
                  '要求版本：' + encode(requirements['ref']), '']
        from .commission_planning import requirement_lines
        with cs.store.connect() as db:
            lines += requirement_lines(cs, db, requirements)
    def citation_location(citation):
        if citation is None:
            return '无来源（未知值，原因见上）'
        source = cs.read(citation['source_ref'])['payload']
        return source['source_metadata'].get('title', citation['source_ref']['id']) + ' / ' + citation['locator']
    for obj in plan['objects']:
        lines.append(f"- {obj['object_id']} — {obj['label']}：{'纳入' if obj['included'] else '建议排除'}；{obj['reason']}（{'客户约定' if obj['origin'] == 'customer' else '代理解释'}）")
        lines += ['  对象依据：' + citation_location(c) for c in obj['sources']]
        for attribute in obj['attributes']:
            values = '；'.join((v['value'] or '未知') + '：' + v['reason'] for v in attribute['values'])
            lines.append('  ' + attribute['name'] + ': ' + values)
            lines += ['  属性依据：' + citation_location(v['source']) for v in attribute['values']]
    if plan.get('scope_boundary'):
        boundary = plan['scope_boundary']
        lines += ['', '## 合同范围边界', '', f"{boundary['start_meter']}–{boundary['end_meter']}米；约定对象数{boundary.get('expected_object_count') or '未指定'}",
                  '原文依据：' + boundary['source']['quote']]
        if boundary.get('customer_basis'):
            lines.append('客户范围选择原文：' + boundary['customer_basis']['quote'])
    lines += ['', '## 章节计划', '']
    for section in plan['sections']:
        locations = ', '.join(cs.read(c['source_ref'])['payload']['source_metadata'].get('title', c['source_ref']['id']) + ' / ' + c['locator'] for c in section['sources'])
        if unresolved_sources(section):
            locations += '；待解决资料：' + '；'.join(unresolved_sources(section))
        kind = {'fixed': '固定内容', 'extracted': '资料提取', 'derived': '依据其他章节形成'}[section['kind']]
        lines.append(f"- {section['section_id']} {section['title']} — {kind}：{locations}")
        for view in section.get('source_views', []):
            lines.append(f"  原表呈现：第{view['page']}页，区域{view['crop']}；需核对裁剪完整性，原文仍逐字保留。")
    lines += ['', '## 资料替代', '']
    for section in plan['sections']:
        for substitution in section.get('source_substitutions', []):
            replacements = '；'.join(cs.read(c['source_ref'])['payload']['source_metadata'].get('title', c['source_ref']['id']) + ' / ' + c['locator'] for c in substitution['replacement_sources'])
            basis = substitution['customer_basis']
            title = cs.read(basis['source_ref'])['payload']['source_metadata'].get('title', basis['source_ref']['id'])
            lines += [f"- 章节{section['section_id']}：{substitution['requested_source']} → {replacements}",
                      f"  客户原文依据（{title} / {basis['locator']}）：{basis['quote']}",
                      '  代理解释：' + substitution['reason']]
    lines += ['', '## 交付物', '', *['- ' + item for item in plan['deliverables']], '', '## 客户约定', '']
    for convention in plan['conventions']:
        lines += ['- 客户原文：' + convention['source']['quote'], '  代理解释：' + convention['interpretation']]
    if plan.get('method_pack'):
        lines += ['', '## 方法包约定链接', '']
        for binding in plan.get('method_conventions', []):
            label = '默认，未约定' if binding['status'] == 'default_unagreed' else '客户约定'
            lines.append(f"- {binding['key']}（{label}）→ {binding['method_id']} / {binding['strategy_id']}；代理解释：{binding['interpretation']}")
        lines.append(f"- 指标及等级数据：{plan['method_pack']['method_id']}，版本{plan['method_pack']['version']}，{len(plan['method_pack']['indicators'])}项")
        if plan.get('format_source'):
            source = cs.read(plan['format_source']['source_ref'])['payload']
            lines.append('- 排版能力链接：' + source['source_metadata'].get('title', '') + ' / ' + plan['format_source']['locator'])
        lines += ['- 待解决：' + question for question in plan.get('method_questions', method_questions(plan))]
    lines += _table_spec_lines(plan.get('table_specs', {}), lambda ref: cs.read(ref)['payload'])
    lines += ['', '## 资料核对', '']
    for item in plan['reconciliations']:
        lines += ['- ' + item['result'], *['  - ' + text for text in item['differences']]]
        lines += ['  核对依据：' + citation_location(c) for c in item['sources']]
    from .source_access import coverage, lines as access_lines
    access = coverage(cs, plan)
    lines += access_lines(access)
    lines += ['', '## 待确认问题', '', *['- ' + item for item in plan['open_questions']]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    description = 'Confirm commission plan ' + digest(ref) + '. Brief: ' + str(path.relative_to(workspace.store.root))
    source_ids = list(dict.fromkeys(cs.read(c['source_ref'])['payload']['source_id'] for c in _citations(plan)))
    issue = workspace.issue('requirement', description, source_ids)
    requirement_binding = {'requirements_ref': plan['requirements_ref']} if plan.get('requirements_ref') else {}
    workspace.store.set('commission_checkpoint:' + issue['id'], {'plan_ref': ref, **requirement_binding, 'brief_path': str(path.relative_to(workspace.store.root))})
    path.with_suffix('.json').write_text(json.dumps({'issue_id': issue['id'], 'plan_ref': ref, 'source_access': access,
        'reply_command': 'report-agent commission-reply --project CASE --issue-id ISSUE_ID --file DECISION.json',
        'decision_shape': {'plan_ref': ref, **requirement_binding, 'approved': True, 'corrections': '', 'reductions': []},
        'note': 'Approve only after reviewing the brief. Explicit reductions require object_id and reason. Corrections use approved=false.'}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'issue_id': issue['id'], 'plan_ref': ref, **requirement_binding, 'brief_path': str(path.relative_to(workspace.store.root)),
            'description': description, 'source_ids': source_ids}


def _confirmed_rules(plan):
    pack = plan.get('method_pack')
    return {
        **({'requirements_ref': plan['requirements_ref']} if plan.get('requirements_ref') else {}),
        'method': ({'id': pack['method_id'], 'version': pack['version'], 'digest': digest(pack)} if pack else None),
        'tables': {role: {'id': spec['table_type'], 'version': spec['version'], 'digest': digest(spec)}
                   for role, spec in plan.get('table_specs', {}).items()},
        'conventions_digest': digest(plan['conventions']),
    }


def _checklist_path(confirmation):
    return str(Path('outputs') / ('confirmation-checklist-' + digest(confirmation) + '.md'))


def _write_confirmation_checklist(workspace, cs, db, issue, checkpoint):
    ref = _state(db, 'commission_confirmation')
    decision = cs._read(db, ref)
    if decision['owner_id'] != 'operator' or decision['payload'].get('approved') is not True:
        return
    plan_ref = decision['payload']['plan_ref']
    if plan_ref != checkpoint['plan_ref']:
        raise ActionRejected('COMMISSION_CHECKLIST_CONFIRMATION_MISMATCH')
    plan = cs._read(db, plan_ref)['payload']
    rules = decision['payload'].get('confirmed_rules', _confirmed_rules(plan))
    lines = ['# 已确认规则与表式清单', '', '复用范围：规则与表式；不复用历史报告数值。',
             '本文件是已保存确认的可读清单；单独编辑本文件不会变更确认。',
             '跨报告使用时，在《报告编写范围说明》中引用清单条目和版本，并核对适用条件与资料版本。',
             '适用条件或规格发生变化，须返回确认节点；本清单不替代新项目范围确认或工程签审。', '',
             '- 确认记录：' + encode(ref), '- 计划版本：' + encode(plan_ref),
             '- 适用章节：' + '、'.join(s['section_id'] + ' ' + s['title'] for s in plan['sections'])]
    if decision['payload']['reductions']:
        labels = {obj['object_id']: obj['label'] for obj in plan['objects']}
        lines += ['', '## 用户排除决定', '', '以下为用户在确认点记录的决定，不是代理的排除建议。']
        lines += ['- ' + item['object_id'] + ' — ' + labels[item['object_id']] + '：' + item['reason']
                  for item in decision['payload']['reductions']]
    if rules.get('requirements_ref'):
        requirements = cs._read(db, rules['requirements_ref'])
        anchors = {a['id']: a for a in requirements['payload']['anchors']}
        lines += ['', '## 已确认委托要求', '', '- 要求版本：' + encode(requirements['ref'])]
        for item in requirements['payload']['items']:
            anchor = anchors[item['anchor_id']]
            lines += ['- ' + item['status'] + ' / ' + ', '.join(item['capabilities']) + '：' + item['interpretation'],
                      '  原文：' + anchor['source']['quote'], '  位置：' + anchor['source']['locator']]
    if rules['method']:
        lines += ['', '## 计算规则', '', '- 方法：' + encode(rules['method'])]
    for convention in plan.get('method_conventions', []):
        lines.append('- ' + convention['key'] + '：' + convention['strategy_id'] + '；' + convention['interpretation'])
        if convention.get('source'):
            lines.append('  客户原文：' + convention['source']['quote'])
    lines += _table_spec_lines(plan.get('table_specs', {}), lambda r: cs._read(db, r)['payload'])
    lines += ['', '## 资料版本', '']
    sources = {}
    for citation in _citations({'method': plan.get('method_pack'), 'tables': plan.get('table_specs'),
                               'conventions': plan['conventions']}):
        source = cs._read(db, citation['source_ref'])['payload']
        key = (source['file_digest'], citation['locator'])
        sources[key] = '- ' + source['source_metadata'].get('title', '') + ' / ' + citation['locator'] + ' / SHA256 ' + source['file_digest']
    lines += list(sources.values())
    relative = _checklist_path(ref)
    path = workspace.store.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    temporary.replace(path)
    issue['confirmation_checklist_path'] = relative
    checkpoint['confirmation_checklist_path'] = relative
    _set(db, 'commission_checkpoint:' + issue['id'], checkpoint)


def reply(workspace, issue_id, decision):
    """Trusted operator entry point, deliberately absent from agent tools."""
    if decision.get('decision') == 'resume_planning':
        from .planning_guard import resume_planning
        return resume_planning(workspace, issue_id, decision)
    if decision.get('decision') == 'resolve_requirements':
        from .commission_planning import reply_requirements
        return reply_requirements(workspace, issue_id, decision)
    decision = OwnerDecision.model_validate(decision).model_dump()
    cs = ContentStore(workspace.store)
    with workspace.store.run_lock(), workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        checkpoint = _state(db, 'commission_checkpoint:' + issue_id)
        if (not checkpoint or checkpoint['plan_ref'] != decision['plan_ref']
                or _state(db, 'commission_plan') != decision['plan_ref']):
            raise ActionRejected('COMMISSION_CHECKPOINT_REPLY_STALE')
        issues = _state(db, 'report_issues', [])
        issue = next((i for i in issues if i['id'] == issue_id), None)
        if issue is None:
            raise ActionRejected('COMMISSION_CHECKPOINT_ISSUE_MISSING')
        plan = cs._read(db, decision['plan_ref'])['payload']
        if decision['approved']:
            from .commission_requirements import require_complete, enabled as requirements_enabled
            require_complete(cs, plan, db=db)
            if requirements_enabled(cs.store) and (decision.get('requirements_ref') != plan.get('requirements_ref')
                    or checkpoint.get('requirements_ref') != plan.get('requirements_ref')):
                raise ActionRejected('COMMISSION_REQUIREMENTS_CONFIRMATION_REQUIRED')
        answer = encode(decision)
        if issue.get('decision_origin') == 'operator':
            if issue.get('decision') != answer:
                raise ActionRejected('COMMISSION_CHECKPOINT_ALREADY_ANSWERED')
            if decision['approved']:
                _write_confirmation_checklist(workspace, cs, db, issue, checkpoint)
                _set(db, 'report_issues', issues)
            return issue
        pending = list(dict.fromkeys(name for s in plan['sections'] for name in unresolved_sources(s)))
        if decision['approved'] and pending:
            raise ActionRejected('COMMISSION_PENDING_SOURCES: ' + '; '.join(pending))
        if decision['approved'] and plan.get('method_questions', method_questions(plan)):
            raise ActionRejected('COMMISSION_METHOD_QUESTIONS: ' + '; '.join(plan.get('method_questions', method_questions(plan))))
        reduced = [r['object_id'] for r in decision['reductions']]
        if len(set(reduced)) != len(reduced) or not set(reduced) <= {o['object_id'] for o in plan['objects']}:
            raise ActionRejected('COMMISSION_REDUCTION_OBJECT_INVALID')
        owner = Actor('operator', 'operator', 'commission-checkpoint:' + issue_id)
        accepted = {**decision, **({'required_material_issues': required_material_issues(
            cs, db, decision['plan_ref'], plan), 'confirmed_rules': _confirmed_rules(plan)} if decision['approved'] else {})}
        ref = cs._insert(db, owner, 'CommissionDecision', accepted)
        issue.update(decision=answer, decision_origin='operator', resolved=True)
        _set(db, 'commission_confirmation', ref)
        _set(db, 'report_issues', issues)
        _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
        _set(db, 'report_status', 'ready')
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('commission_owner_decision', encode({'issue_id': issue_id, 'decision_ref': ref})))
        if decision['approved']:
            # Commit authority first; a failed file projection can be regenerated by the same reply.
            db.commit()
            _write_confirmation_checklist(workspace, cs, db, issue, checkpoint)
            _set(db, 'report_issues', issues)
        return issue


def snapshot_inventory(cs, db, refs):
    if not enabled(cs.store):
        return refs, None, None
    plan, decision = _confirmed(cs, db)
    found = {Ref.model_validate(r).key(): r for r in refs}
    if len(found) != len(refs):
        raise ActionRejected('INVALID_MANIFEST')
    pending = [decision['ref'], plan['ref'], *plan['payload']['inventory_refs']]
    while pending:
        ref = pending.pop()
        key = Ref.model_validate(ref).key()
        if key not in found:
            found[key] = ref
            pending.extend(r.model_dump() for r in refs_in(cs._read(db, ref)['payload']))
    return list(found.values()), plan['ref'], decision['ref']


def snapshot_outcomes(cs, db, plan_ref, refs):
    """Freeze matching producer outcomes, so later drafts cannot alter selected evidence."""
    members = {Ref.model_validate(r).key() for r in refs}
    result = []
    for obj in cs._read(db, plan_ref)['payload']['objects']:
        if outside_boundary(cs._read(db, plan_ref)['payload'], obj):
            continue
        prefix = 'commission_outcome:' + digest([plan_ref, obj['object_id']]) + ':'
        matches = []
        for (value,) in db.execute('SELECT value FROM state WHERE key>=? AND key<? ORDER BY key', (prefix, prefix[:-1] + ';')):
            ref = json.loads(value)
            outcome = cs._read(db, ref)['payload']
            dependencies = [outcome['object_ref'], outcome['section_ref'], outcome['score_ref'],
                            outcome['level_ref'], *outcome['basis_refs']]
            if all(Ref.model_validate(r).key() in members for r in dependencies):
                matches.append(ref)
        if len(matches) > 1:
            raise ActionRejected('COMMISSION_OUTCOME_SELECTION_AMBIGUOUS')
        result.extend(matches)
    return result


def record_outcome(cs, actor, operation_id, object_id, section_ref, score_ref, level_ref, basis_refs, unresolved):
    request = {'object_id': object_id, 'section_ref': section_ref, 'score_ref': score_ref,
               'level_ref': level_ref, 'basis_refs': basis_refs, 'unresolved': unresolved}
    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        if plan is None or not basis_refs:
            raise ActionRejected('COMMISSION_OUTCOME_BASIS_REQUIRED')
        object_ref = next((ref for ref in plan['payload']['inventory_refs']
            if cs._read(db, ref)['payload']['inventory_object']['object_id'] == object_id), None)
        if object_ref is None:
            raise ActionRejected('COMMISSION_OUTCOME_OBJECT_NOT_IN_PLAN')
        for ref in (section_ref, score_ref, level_ref):
            record = cs._read(db, ref)
            if ref['type'] != 'ContentNode' or record['owner_id'] != actor.id:
                raise ActionForbidden('FORBIDDEN: commission outcome writer ownership')
        for ref in basis_refs:
            if ref['type'] != 'Evidence':
                raise ActionRejected('COMMISSION_OUTCOME_EVIDENCE_REQUIRED')
            cs._read(db, ref)
        assessment_ref = None
        if plan['payload'].get('method_pack'):
            from .risk_scoring import validate_outcome
            assessment_ref = validate_outcome(cs, db, plan, object_id, score_ref, level_ref, basis_refs, unresolved)
        ref = cs._insert(db, actor, 'CommissionOutcome', {**request,
            'commission_plan_ref': plan['ref'], 'object_ref': object_ref,
            **({'assessment_ref': assessment_ref} if assessment_ref else {})})
        _set(db, 'commission_outcome:' + digest([plan['ref'], object_id]) + ':' + digest(actor.id), ref)
        return {'outcome_ref': ref}
    from .commission_requirements import enabled as requirements_enabled
    binding = (lambda db, result: _confirmed(cs, db)[0]['ref']) if requirements_enabled(cs.store) else None
    return cs.operation(actor, operation_id, {'commission_outcome': request}, save, binding_identity=binding)
