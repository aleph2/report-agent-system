"""Planning ingress contracts; stored evidence keeps the stricter canonical models."""
from copy import deepcopy
from bisect import bisect_right
from decimal import Decimal, InvalidOperation, localcontext
from functools import wraps
from inspect import signature
import re
from unicodedata import normalize
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


def compact_write_result(response, *, warning_count_only=False):
    """Project model replies after persistence; the complete operation receipt stays readable."""
    if not isinstance(response, dict) or response.get('ok') is not True:
        return response
    result = response.get('result')
    if (not isinstance(result, dict) or 'saved_item_ids' not in result
            or not {'revision', 'requirements_ref'} & result.keys()):
        return response
    compact = {key: result[key] for key in ('revision', 'requirements_ref', 'changed') if key in result}
    identities = result['saved_item_ids']
    if identities:
        compact['saved_item_ids'] = identities
    warnings = result.get('numeric_warnings', [])
    if warning_count_only:
        if warnings:
            compact['numeric_warning_count'] = len(warnings)
    else:
        current = []
        for warning in warnings:
            path = warning['field']
            if path.startswith('requirements.'):
                identity = next((key for key in identities if path.startswith('requirements.' + key + '.')), None)
                if identity is None:
                    continue
                field = path[len('requirements.' + identity + '.'):]
            elif path.startswith('items.'):
                _, index, field = path.split('.', 2)
                identity = identities[int(index)]
            else:
                identity = identities[0]
                field = path.split('.', 1)[1]
            current.append({'record_id': identity, 'field': field, 'number': warning['number']})
        if current:
            compact['numeric_warnings'] = current
    return {**response, 'result': compact}


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
            return compact_write_result(function(
                **({'operation_id': operation} if operation is not None else {}), **dict(value)))
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


def numeric_literal_warnings(value, path='', quotes=(), *, context=None):
    """Soft literal comparison only; a cited number does not certify arithmetic or meaning."""
    from .store import encode
    identifiers, method_evidence = set(), {}
    id_fields = {'id', 'object_id', 'section_id', 'question_id', 'reconciliation_id', 'anchor_id',
        'requirement_anchor_id', 'record_id', 'entry_id', 'reviewed_entry_id', 'method_id', 'strategy_id', 'indicator_id'}
    def method_link(pack, source, strategy=None):
        if strategy is None:
            values = [g for i in pack.get('indicators', []) for g in i.get('grades', [])] + pack.get('risk_bands', [])
        else:
            values = [row['weights'] for table in pack.get('weight_tables', []) if table['id'] == strategy
                      for row in table['rows'] if row['indicator_count'] == len(pack.get('indicators', []))]
        if values:
            method_evidence.setdefault(encode(source), []).append(encode(values))
    def register(record):
        if isinstance(record, list):
            for child in record:
                register(child)
        elif isinstance(record, dict):
            for key, child in record.items():
                values = [child] if key in id_fields else child if key == 'indicator_ids' else []
                for identity in values:
                    if isinstance(identity, str) and any(c.isalpha() for c in identity):
                        identifiers.add(normalize('NFKC', identity))
                if isinstance(child, (dict, list)):
                    register(child)
            pack = record.get('method_pack')
            if isinstance(pack, dict):
                for source in pack.get('sources', []):
                    method_link(pack, source)
                for table in pack.get('weight_tables', []):
                    method_link(pack, table['source'], table['id'])
                if record.get('source'):
                    method_link(pack, record['source'], record.get('strategy_id'))
                for link in record.get('method_conventions', []):
                    if link.get('method_id') == pack['method_id']:
                        method_link(pack, link['source'], link.get('strategy_id'))
    register(value)
    if context is not None:
        register(context)
    identifier_pattern = (r'(?<![A-Za-z0-9_])(?<![A-Za-z0-9_][.-])(?:' + '|'.join(re.escape(i) for i in sorted(identifiers, key=len, reverse=True))
                          + r')(?![A-Za-z0-9_]|[.-][A-Za-z0-9_])') if identifiers else None
    pattern = r'(?<![0-9_.])([+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|[+-]?\.[0-9]+)(?![0-9_]|\.[0-9])\s*([%°度]?)'
    def numbers(text):
        text = normalize('NFKC', text)
        if identifier_pattern:
            text = re.sub(identifier_pattern, '', text)
        for match in re.finditer(pattern, text):
            raw = match[1]
            if raw.startswith('-') and re.search(r'[0-9]\s*$', text[:match.start()]):
                raw = raw[1:]
            unit = '°' if match[2] == '度' else match[2]
            yield (Decimal(raw.replace(',', '')), unit), raw + unit
    text_fields = {'label', 'reason', 'interpretation', 'title', 'notes', 'text', 'rule',
        'result', 'differences', 'value', 'name', 'pending_sources', 'deliverables',
        'report_title', 'inventory_attributes', 'open_questions', 'requested_source', 'applicability_question', 'new'}
    citation_fields = {'source', 'sources', 'outline', 'customer_basis', 'replacement_sources'}
    skip = citation_fields | {'examples', 'extraction', 'method_pack', 'table_specs', 'source_span',
        'source_views', 'owner_records', 'carried_items'}
    warnings = []
    def check(text, field, evidence):
        if isinstance(text, str):
            cited = {key for quote in evidence for key, _ in numbers(quote)}
            seen = set()
            for key, literal in numbers(text):
                if key not in cited and key not in seen:
                    warnings.append({'field': field, 'number': literal, 'status': '待核'})
                    seen.add(key)
        elif isinstance(text, list):
            for index, item in enumerate(text):
                check(item, field + '.' + str(index), evidence)
    def walk(record, field, evidence):
        if isinstance(record, list):
            for index, item in enumerate(record):
                walk(item, field + '.' + str(index) if field else str(index), evidence)
        elif isinstance(record, dict):
            if 'source_ref' in record and ('quote' in record or 'locator' in record):
                return
            own = citation_fields & record.keys()
            if own:
                evidence = []
                for key in own:
                    citations = record[key] if isinstance(record[key], list) else [record[key]]
                    for citation in citations:
                        if isinstance(citation, dict):
                            evidence.extend([citation.get('quote', ''), *method_evidence.get(encode(citation), [])])
            elif {'object_id', 'section_id', 'question_id', 'reconciliation_id', 'anchor_id'} & record.keys():
                evidence = ()
            for key, child in record.items():
                child_path = field + '.' + key if field else key
                if key in text_fields:
                    check(child, child_path, evidence)
                if key not in skip and isinstance(child, (dict, list)):
                    walk(child, child_path, evidence)
    walk(value, path, quotes)
    return warnings


def requirement_numeric_warnings(payload, *, context=None):
    anchors = {a['id']: a for a in payload['anchors']}
    warnings = []
    for item in payload['items']:
        anchor = anchors[item['anchor_id']]
        warnings.extend(numeric_literal_warnings({'interpretation': item['interpretation'],
            'sources': [anchor['source'], *anchor.get('continuations', [])]},
            'requirements.' + item['anchor_id'], context=context))
    return warnings
