"""Small source-bound table specifications projecting immutable saved records."""
from __future__ import annotations

from copy import deepcopy
import math
import re
from string import Formatter
from typing import Literal

from pydantic import Field, model_validator

from .content_models import Contract, Ref, SourceCitation
from .errors import ActionRejected


def _path(value):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*', value):
        raise ValueError('TABLE_SPEC_UNSUPPORTED_BINDING: ' + value)
    return value


class Header(Contract):
    text: str = Field(min_length=1)
    columns: list[str] | None = Field(default=None, min_length=1, exclude_if=lambda v: v is None)
    children: list[Header] | None = Field(default=None, min_length=1, exclude_if=lambda v: v is None)

    @model_validator(mode='after')
    def shape(self):
        if (self.columns is None) == (self.children is None):
            raise ValueError('TABLE_SPEC_HEADER_REQUIRES_LEAF_OR_GROUP')
        for key in self.columns or []:
            _path(key)
        return self


class MergeRule(Contract):
    axis: Literal['vertical', 'horizontal'] = 'vertical'
    columns: list[str] = Field(min_length=1)
    group_by: list[str] = Field(default_factory=list)
    when_empty: str | None = None

    @model_validator(mode='after')
    def supported(self):
        if (self.axis == 'vertical' and (not self.group_by or self.when_empty is not None)
                or self.axis == 'horizontal' and (len(self.columns) < 2 or self.group_by)):
            raise ValueError('TABLE_SPEC_UNSUPPORTED_MERGE')
        for field in self.columns + self.group_by + ([self.when_empty] if self.when_empty else []):
            _path(field)
        if len(set(self.columns)) != len(self.columns):
            raise ValueError('TABLE_SPEC_DUPLICATE_MERGE_COLUMN')
        return self


class RowGroup(Contract):
    binding: str
    merges: list[MergeRule] = Field(default_factory=list)

    @model_validator(mode='after')
    def path(self):
        _path(self.binding)
        return self


class SortRule(Contract):
    binding: str
    direction: Literal['ascending', 'descending'] = 'ascending'

    @model_validator(mode='after')
    def path(self):
        _path(self.binding)
        return self


def _leaves(headers):
    for header in headers:
        if header.columns is not None:
            yield header
        else:
            yield from _leaves(header.children)


class TableSpec(Contract):
    table_type: str = Field(min_length=1)
    version: int = Field(strict=True, ge=1)
    sources: list[SourceCitation] = Field(min_length=1)
    headers: list[Header] = Field(min_length=1)
    column_bindings: dict[str, str] = Field(min_length=1)
    row_groups: list[RowGroup] = Field(min_length=1)
    caption_pattern: str = Field(min_length=1)
    caption_bindings: dict[str, str] = Field(default_factory=dict)
    sort: list[SortRule] = Field(default_factory=list)
    level_labels: dict[str, str] = Field(default_factory=dict)
    column_weights: list[float] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode='after')
    def contract(self):
        keys = [key for leaf in _leaves(self.headers) for key in leaf.columns]
        if len(keys) != len(set(keys)) or set(keys) != set(self.column_bindings):
            raise ValueError('TABLE_SPEC_HEADER_BINDING_PARTITION')
        for field in list(self.column_bindings) + list(self.column_bindings.values()) + list(self.caption_bindings.values()):
            _path(field)
        fields = set()
        for _, field, formatting, conversion in Formatter().parse(self.caption_pattern):
            if field is not None:
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', field) or formatting or conversion:
                    raise ValueError('TABLE_SPEC_UNSUPPORTED_CAPTION_EXPRESSION')
                fields.add(field)
        if fields != set(self.caption_bindings):
            raise ValueError('TABLE_SPEC_CAPTION_BINDING_PARTITION')
        for group in self.row_groups:
            for rule in group.merges:
                if not set(rule.columns) <= set(keys):
                    raise ValueError('TABLE_SPEC_UNKNOWN_MERGE_COLUMN')
                positions = [keys.index(k) for k in rule.columns]
                if rule.axis == 'horizontal' and positions != list(range(positions[0], positions[-1] + 1)):
                    raise ValueError('TABLE_SPEC_NONCONTIGUOUS_MERGE_COLUMNS')
        return self


def column_keys(spec):
    spec = TableSpec.model_validate(spec)
    return [key for leaf in _leaves(spec.headers) for key in leaf.columns]


def validate_table_specs(specs, record_contract=None):
    """Validate structure, then optional caller-supplied saved-record field capability."""
    parsed = {role: TableSpec.model_validate(spec) for role, spec in specs.items()}
    types = [spec.table_type for spec in parsed.values()]
    if len(types) != len(set(types)):
        raise ValueError('TABLE_SPEC_DUPLICATE_TYPE')
    if record_contract is not None:
        for spec in parsed.values():
            if not set(spec.caption_bindings.values()) <= set(record_contract['values']):
                raise ValueError('TABLE_SPEC_UNKNOWN_CAPTION_BINDING')
            for group in spec.row_groups:
                allowed = record_contract['rows'].get(group.binding)
                required = set(spec.column_bindings.values()) | {s.binding for s in spec.sort}
                for rule in group.merges:
                    required.update(rule.group_by)
                    if rule.when_empty:
                        required.add(rule.when_empty)
                if allowed is None or not required <= set(allowed):
                    raise ValueError('TABLE_SPEC_UNKNOWN_ROW_BINDING: ' + group.binding)
    return {role: spec.model_dump(mode='json') for role, spec in parsed.items()}


def compile_header(spec):
    spec = TableSpec.model_validate(spec)
    def depth(header):
        return 1 if header.columns is not None else 1 + max(depth(c) for c in header.children)
    height = max(depth(h) for h in spec.headers)
    keys = column_keys(spec)
    rows, merges = [[''] * len(keys) for _ in range(height)], []
    def put(header, row, column):
        width = sum(len(leaf.columns) for leaf in _leaves([header]))
        rows[row][column] = header.text
        end_row = height - 1 if header.columns is not None else row
        if width > 1 or end_row > row:
            merges.append(dict(start_row=row, end_row=end_row, start_col=column, end_col=column + width - 1))
        if header.children:
            next_column = column
            for child in header.children:
                next_column = put(child, row + 1, next_column)
        return column + width
    column = 0
    for header in spec.headers:
        column = put(header, 0, column)
    labels = [leaf.text for leaf in _leaves(spec.headers) for _ in leaf.columns]
    return dict(columns=labels, header_rows=rows, header_merges=merges)


def _lookup(record, path):
    value = record
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            raise ActionRejected('TABLE_SPEC_MISSING_BINDING: ' + path)
        value = value[key]
    return value


def _text(value):
    if type(value) not in (str, int, float, bool) or isinstance(value, float) and not math.isfinite(value):
        raise ActionRejected('TABLE_SPEC_NONSCALAR_VALUE')
    return str(value)


def compile_table(spec, saved_table_records):
    """Trusted projection core; production callers use render_saved_table's pinned refs."""
    spec = TableSpec.model_validate(spec)
    result = compile_header(spec)
    if spec.column_weights is not None:
        result['column_weights'] = spec.column_weights
    keys = column_keys(spec)
    rows, merges, origins, occupied = [], [], [], set()
    def merge(r0, r1, c0, c1):
        cells = {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
        first = rows[r0][c0]
        if cells & occupied or any(rows[r][c] not in ('', first) for r, c in cells):
            raise ActionRejected('TABLE_SPEC_MERGE_WOULD_ERASE_DATA_OR_OVERLAP')
        occupied.update(cells)
        merges.append(dict(start_row=r0, end_row=r1, start_col=c0, end_col=c1))
    for group in spec.row_groups:
        data = _lookup(saved_table_records, group.binding)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ActionRejected('TABLE_SPEC_ROWS_REQUIRED: ' + group.binding)
        indexed = list(enumerate(data))
        for order in reversed(spec.sort):
            try:
                indexed.sort(key=lambda pair: _lookup(pair[1], order.binding), reverse=order.direction == 'descending')
            except TypeError as exc:
                raise ActionRejected('TABLE_SPEC_INCOMPARABLE_SORT_VALUES') from exc
        start = len(rows)
        for index, row in indexed:
            rows.append([_text(_lookup(row, spec.column_bindings[key])) for key in keys])
            origins.append({'binding': group.binding, 'index': index})
        for rule in group.merges:
            columns = [keys.index(key) for key in rule.columns]
            if rule.axis == 'horizontal':
                for offset, (_, row) in enumerate(indexed):
                    if rule.when_empty and _lookup(row, rule.when_empty) != '':
                        continue
                    merge(start + offset, start + offset, columns[0], columns[-1])
            else:
                offset = 0
                groups = [tuple(_text(_lookup(row, field)) for field in rule.group_by) for _, row in indexed]
                while offset < len(indexed):
                    end = offset
                    while end + 1 < len(indexed) and groups[end + 1] == groups[offset]:
                        end += 1
                    if end > offset:
                        for column in columns:
                            merge(start + offset, start + end, column, column)
                    offset = end + 1
    caption = spec.caption_pattern.format(**{key: _text(_lookup(saved_table_records, path)) for key, path in spec.caption_bindings.items()})
    return {**result, 'rows': rows, 'merges': merges, 'caption': caption, 'row_origins': origins}


def render_saved_table(cs, db, plan_ref, assessment_ref, table_type):
    plan_key, assessment_key = Ref.model_validate(plan_ref), Ref.model_validate(assessment_ref)
    if plan_key.type != 'CommissionPlan' or assessment_key.type != 'Assessment':
        raise ActionRejected('TABLE_SPEC_SAVED_PLAN_AND_ASSESSMENT_REQUIRED')
    plan = cs._read(db, plan_ref)['payload']
    assessment = cs._read(db, assessment_ref)['payload']
    if assessment.get('commission_plan_ref') != plan_ref:
        raise ActionRejected('TABLE_SPEC_ASSESSMENT_PLAN_MISMATCH')
    matches = [s for s in plan.get('table_specs', {}).values() if s['table_type'] == table_type]
    if len(matches) != 1:
        raise ActionRejected('TABLE_SPEC_CONFIRMED_TYPE_REQUIRED')
    if not isinstance(assessment.get('table_records'), dict):
        raise ActionRejected('TABLE_SPEC_SAVED_RECORDS_REQUIRED')
    return compile_table(matches[0], assessment['table_records'])


def assessment_tables(cs, db, plan, assessment_ref, table_records, result, label):
    from .store import digest
    bodies, origins = {}, {}
    for role in ('ranking', 'evaluation'):
        spec = plan['payload']['table_specs'][role]
        bodies[role] = render_saved_table(cs, db, plan['ref'], assessment_ref, spec['table_type'])
        origins[role] = bodies[role].pop('row_origins')
        bodies[role]['assessment_part'] = role
    # Semantic field bindings locate annotations even when a specification reorders columns or rows.
    def column(role, field):
        spec = plan['payload']['table_specs'][role]
        keys = column_keys(spec)
        matches = [n for n, key in enumerate(keys) if spec['column_bindings'][key] == field]
        if len(matches) != 1:
            raise ActionRejected('TABLE_SPEC_ANNOTATION_BINDING_REQUIRED: ' + field)
        return matches[0]
    issues, citations = [], []
    definitions = {r['id']:r for r in plan['payload']['method_pack']['indicators']}
    from .draft_assessment import display_rows
    for row in display_rows(result, plan['payload']['method_pack']):
        sources = []
        for citation in row['sources']:
            title = cs._read(db, citation['source_ref'])['payload']['source_metadata'].get('title')
            if not title:
                raise ActionRejected('ASSESSMENT_READABLE_SOURCE_TITLE_REQUIRED')
            sources.append({'document': title, 'page': citation['locator']})
            if citation not in citations:
                citations.append(citation)
        if row['basis_kind'] != 'missing' and not row['basis_kind'].endswith('assumption'):
            continue
        positions = [n for n, origin in enumerate(origins['evaluation'])
                     if origin['binding'] == 'evaluation.rows' and
                     table_records['evaluation']['rows'][origin['index']]['indicator_id'] == row['indicator_id']]
        if not positions:
            raise ActionRejected('TABLE_SPEC_ASSUMPTION_ROW_REQUIRED')
        issues.append({'id': digest([assessment_ref, row['indicator_id']]), 'kind': 'unclear' if row['basis_kind'] == 'missing' else row['basis_kind'],
            'object_label': label + ' / ' + definitions[row['indicator_id']].get('display_label', definitions[row['indicator_id']]['label']),
            'basis': row['rationale'], 'sources': sources,
            'adopted_value': row['value'], 'question': row['question'],
            'anchor': {'row': min(positions), 'column': column('evaluation', 'value')},
            'affects_level': result.get('affects_level', not result.get('level_robust', False))})
    bodies['evaluation']['material_issues'] = issues
    return bodies['ranking'], bodies['evaluation'], citations


def read_prepared_tables(guideline_ref, guideline_digest, template_ref, template_digest):
    import json
    from importlib.resources import files
    data = json.loads(files('report_agent').joinpath('methods/high_slope_tables.json').read_text(encoding='utf-8'))
    refs = {'guideline': guideline_ref, 'template': template_ref}
    hashes = {'guideline': guideline_digest, 'template': template_digest}
    for role, expected in data['source_hashes'].items():
        if hashes[role] != expected:
            raise ValueError('TABLE_SPEC_SOURCE_HASH_MISMATCH: ' + role)
    specs = deepcopy(data['table_specs'])
    for spec in specs.values():
        spec['sources'] = [{'source_ref': refs[role], 'locator': f'page {page}', 'quote': ''}
                           for role, pages in spec.pop('source_pages').items() for page in pages]
    return validate_table_specs(specs)
