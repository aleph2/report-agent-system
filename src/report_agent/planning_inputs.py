"""Planning ingress contracts; stored evidence keeps the stricter canonical models."""
from copy import deepcopy
from bisect import bisect_right
from decimal import Decimal, InvalidOperation, localcontext
from functools import wraps
from inspect import signature
import re
from typing import get_type_hints

from pydantic import Field, ValidationError, create_model, field_validator

from .content_models import Contract, SourceCitation, InventoryValue, InventoryAttribute, InventoryObject
from .commission_plan import SourceSubstitution, Reconciliation
from .errors import ActionRejected


def reject(field, reason, choices=(), *, message=None, related_fields=(), code=None):
    issue = {'field': field, 'reason': reason, 'choices': list(choices)}
    if message:
        issue['message'] = message
    if related_fields:
        issue['related_fields'] = list(related_fields)
    raise ActionRejected(code or ('PLANNING_FIELD_INVALID: ' + field + ': ' + reason),
        diagnostic={'fields': [issue]})


def metres(value):
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError('Use metres or Kkm+metres[+offset] as a string')
    chainage = re.fullmatch(r'[Kk](\d+)\+(\d+(?:\.\d+)?)(?:\+(\d+(?:\.\d+)?))?', value)
    try:
        if chainage:
            if Decimal(chainage[2]) >= 1000:
                raise ValueError('Chainage metre part must be below 1000')
            with localcontext() as context:
                context.prec = max(28, len(value) + 10)
                number = Decimal(chainage[1]) * 1000 + Decimal(chainage[2]) + Decimal(chainage[3] or '0')
        elif re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', value):
            number = Decimal(value)
        else:
            raise ValueError('Use finite decimal metres or Kkm+metres[+offset]')
    except InvalidOperation:
        raise ValueError('Use finite decimal metres or Kkm+metres[+offset]') from None
    return format(number, 'f')


class PlanningCitation(SourceCitation):
    locator: str = Field(default='', description='Copy a returned source locator to select a repeated quote. Omit for unique exact quote lookup; the system records any locator it resolves.')
    quote: str = Field(default='', description='Exact source text. Required when locator is omitted; never paraphrase evidence.')


class QuotedPlanningCitation(PlanningCitation):
    quote: str = Field(min_length=1, pattern=r'\S', description='Required exact source quotation, verified against this source version.')


class BoundaryInput(Contract):
    start_meter: str = Field(max_length=128, description='Plain decimal metres or document chainage, e.g. K9000+000. System converts chainage to metres.')
    end_meter: str = Field(max_length=128, description='Plain decimal metres or chainage, e.g. K9002+450+12.5. Must be greater than start_meter.')
    source: QuotedPlanningCitation
    customer_basis_anchor_id: str = Field(min_length=1, description='ID of a scope requirement returned by read_planning_draft. System uses its verified quotation and locator.')
    expected_object_count: int | None = Field(default=None, strict=True, ge=1)

    @field_validator('start_meter', 'end_meter')
    @classmethod
    def numeric(cls, value):
        metres(value)
        return value

    @field_validator('end_meter')
    @classmethod
    def ordered(cls, value, info):
        if 'start_meter' in info.data and Decimal(metres(value)) <= Decimal(metres(info.data['start_meter'])):
            raise ValueError('end_meter must be greater than start_meter')
        return value


class PlanningInventoryValue(InventoryValue):
    source: PlanningCitation | None


class PlanningInventoryAttribute(InventoryAttribute):
    values: list[PlanningInventoryValue] = Field(min_length=1)


class PlanningInventoryObject(InventoryObject):
    attributes: list[PlanningInventoryAttribute] = Field(min_length=1)
    sources: list[PlanningCitation] = Field(min_length=1)


class PlanningSubstitution(SourceSubstitution):
    replacement_sources: list[PlanningCitation] = Field(min_length=1)
    customer_basis: QuotedPlanningCitation


class PlanningReconciliationInput(Reconciliation):
    reconciliation_id: str = Field(min_length=1)
    sources: list[PlanningCitation] = Field(min_length=2)


def citation_paths(value, path=''):
    if isinstance(value, dict):
        if 'source_ref' in value and ('locator' in value or 'quote' in value):
            yield path, value
        else:
            for key, child in value.items():
                yield from citation_paths(child, path + '.' + key if path else key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from citation_paths(child, f'{path}[{index}]')


def quote_locations(rows, quote):
    if not quote:
        return []
    nonempty = [(loc, text) for loc, text in rows if text]
    starts, total = [], 0
    for _, text in nonempty:
        starts.append(total)
        total += len(text)
    joined = ''.join(text for _, text in nonempty)
    result = []
    for match in re.finditer('(?=' + re.escape(quote) + ')', joined):
        first = bisect_right(starts, match.start()) - 1
        last = bisect_right(starts, match.start() + len(quote) - 1) - 1
        left, right = nonempty[first][0], nonempty[last][0]
        if first == last:
            result.append(left)
        elif left.split(';', 1)[0] == right.split(';', 1)[0]:
            result.append(left.split(';', 1)[0])
        else:
            result.append(left + ' → ' + right)
    return result


def resolve_citations(cs, db, actor, value, root, *, planning=False):
    changes = []
    for path, citation in citation_paths(value, root):
        source = cs._read(db, citation['source_ref'])
        if citation['source_ref']['type'] != 'SourceArtifact':
            reject(path + '.source_ref', 'source_artifact_required')
        from .deliverables import source_authority
        try:
            source_authority(cs, db, actor, [source], planning=planning)
        except ActionRejected as error:
            reject(path + '.source_ref', str(error))
        rows = list(db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal', (source['payload']['source_id'],)))
        locator, quote = citation.get('locator', ''), citation.get('quote', '')
        located = [text for loc, text in rows if locator and (loc == locator or loc.startswith(locator + ';'))]
        if locator and located and (not quote or quote in ''.join(located)):
            continue
        if not quote.strip():
            if locator:
                continue  # Canonical validator also supports existing image-only page citations.
            reject(path + '.quote', 'quote_required_for_automatic_location')
        matches = quote_locations(rows, quote)
        if len(matches) != 1:
            reject(path + '.quote', 'quote_not_found' if not matches else 'quote_ambiguous', matches)
        selected = [text for loc, text in rows if loc == matches[0] or loc.startswith(matches[0] + ';')]
        if quote not in ''.join(selected):
            reject(path + '.quote', 'quote_spans_distinct_locations: cite a quote within one returned location', matches)
        citation['locator'] = matches[0]
        changes.append({'field': path + '.locator', 'original_locator': locator,
                        'resolved_locator': matches[0], 'reason': 'unique_exact_quote',
                        'source_ref': deepcopy(citation['source_ref'])})
    return changes


PLANNING_TOOLS = {'read_planning_draft', 'set_requirement_status', 'link_convention',
    'set_scope_boundary', 'set_planning_details', 'add_object', 'add_section',
    'add_substitution', 'add_reconciliation', 'add_question', 'submit_plan',
    'request_commission_confirmation', 'request_requirement_resolution'}


# Domain rules cannot all be expressed as JSON Schema. Keep their repair paths explicit.
ERROR_FIELDS = {
    'COMMISSION_REQUIREMENT_ANCHOR_UNKNOWN': 'anchor_id',
    'REQUIREMENT_CLASSIFICATION_REQUIRED': 'anchor_id',
    'REQUIREMENT_ENTRY_NOT_ELIGIBLE': 'entry_id',
    'REVIEWED_ENTRY_NOT_OFFERED': 'entry_id',
    'REVIEWED_ENTRY_SOURCE_CHANGED': 'entry_id',
    'SECTION_OUTLINE_ANCHOR_REQUIRED': 'outline_anchor_id',
    'FIXED_SECTION_SOURCE_SPAN_REQUIRED': 'source_span',
    'SOURCE_SPAN_OR_CITATIONS_REQUIRED': 'sources',
    'SOURCE_SPAN_PAGE_ORDER': 'source_span.end_page',
    'SOURCE_SPAN_PROFILE_REQUIRED': 'source_span.profile_id',
    'TEXT_PROFILE_SOURCE_CHANGED': 'source_span.source_ref',
    'SOURCE_SPAN_PAGE_TEXT_UNAVAILABLE': 'source_span.start_page',
    'SOURCE_SPAN_ENDPOINT_AMBIGUOUS_OR_MISSING': 'source_span.start_sentence',
    'SOURCE_SPAN_ENDPOINT_ORDER': 'source_span.end_sentence',
    'SOURCE_SPAN_RAW_ENDPOINT_AMBIGUOUS_OR_MISSING': 'source_span.start_sentence',
    'SECTION_SOURCE_OR_PENDING_SOURCE_REQUIRED': 'sources',
    'SECTION_PENDING_SOURCE_NAME_REQUIRED': 'pending_sources',
    'SECTION_SOURCE_RESOLUTION_DUPLICATE': 'pending_sources',
    'SECTION_SUBSTITUTION_NOT_REQUESTED': 'source_substitutions',
    'SECTION_SUBSTITUTION_REPLACEMENT_NOT_IN_PLAN': 'sources',
    'SECTION_OUTLINE_QUOTE_REQUIRED': 'outline',
    'FIXED_SECTION_TEXT_REQUIRED': 'source_span',
    'DERIVED_SECTION_RULE_REQUIRED': 'rule',
    'SOURCE_VIEW_FIXED_ORDERED_SOURCES_REQUIRED': 'source_views',
    'SOURCE_VIEW_SAME_SOURCE_PAGE_REQUIRED': 'source_views',
    'SOURCE_VIEW_CONTIGUOUS_INDEXES_REQUIRED': 'source_indexes',
    'SOURCE_VIEW_CROP_INVALID': 'crop',
    'RESULT_BINDING_TARGET_REQUIRED': 'object_id',
    'RESULT_BINDING_LEVEL_REQUIRED': 'level',
    'INVENTORY_VALUE_REQUIRES_SOURCE': 'source',
    'COMMISSION_BOUNDARY_SOURCE_AND_ORDER_REQUIRED': 'end_meter',
    'COMMISSION_BOUNDARY_CHAINAGE_MISMATCH': 'chainage_inputs',
}


def inventory_error_fields(issue, prefix=''):
    """Expand only our own structured inventory error; never expose arbitrary exception context."""
    if issue['type'] != 'commission_inventory_attributes_incomplete':
        return []
    return [{**field, 'field': '.'.join(filter(None, [prefix, field['field']]))}
            for field in issue['ctx']['inventory_fields']]


def model_value(model, value, prefix=''):
    try:
        return model.model_validate(value)
    except ValidationError as error:
        fields = []
        for issue in error.errors(include_input=False, include_url=False):
            path = '.'.join(str(x) for x in issue['loc'])
            inventory = inventory_error_fields(issue, '.'.join(filter(None, [prefix, path])))
            if inventory:
                fields.extend(inventory)
                continue
            code = issue['msg'].removeprefix('Value error, ')
            if code in ERROR_FIELDS:
                path = '.'.join(filter(None, [path, ERROR_FIELDS[code]]))
            fields.append({'field': '.'.join(filter(None, [prefix, path])) or prefix or 'input',
                           'reason': code, 'choices': []})
        summary = '; '.join(dict.fromkeys(field['field'] + ': ' + field['reason'] for field in fields))
        raise ActionRejected('PLANNING_FIELDS_INVALID: ' + summary, diagnostic={'fields': fields}) from None


def expose(function):
    hints = get_type_hints(function, include_extras=True)
    fields = {name: (hints.get(name, str), param.default if param.default is not param.empty else ...)
              for name, param in signature(function).parameters.items() if name != 'operation_id'}
    model = create_model(function.__name__ + 'Input', __base__=Contract, **fields)

    @wraps(function)
    def checked(*args, **kwargs):
        bound = signature(function).bind(*args, **kwargs)
        bound.apply_defaults()
        operation = bound.arguments.pop('operation_id', None)
        value = model_value(model, bound.arguments)
        try:
            return function(**({'operation_id': operation} if operation is not None else {}), **dict(value))
        except ActionRejected as error:
            if error.diagnostic:
                raise
            code = str(error).split(':', 1)[0]
            field = ERROR_FIELDS.get(code)
            if field:
                reject(field, code)
            raise
    checked.message_model = model
    return checked
