"""Small source-bound table specifications projecting immutable saved records."""
from __future__ import annotations

from string import Formatter
from typing import Literal

from pydantic import Field, model_validator

from .content_models import Contract, Ref, SourceCitation
from .errors import ActionRejected


def _path(value):
    return value


class Header(Contract):
    text: str
    columns: list[str] | None = Field(default=None, exclude_if=lambda v: v is None)
    children: list[Header] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode='after')
    def shape(self):
        for key in self.columns or []:
            _path(key)
        return self


class MergeRule(Contract):
    axis: Literal['vertical', 'horizontal'] = 'vertical'
    columns: list[str]
    group_by: list[str] = Field(default_factory=list)
    when_empty: str | None = None

    @model_validator(mode='after')
    def supported(self):
        for field in self.columns + self.group_by + ([self.when_empty] if self.when_empty else []):
            _path(field)
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
    table_type: str
    version: int = Field(strict=True, ge=1)
    sources: list[SourceCitation]
    headers: list[Header]
    column_bindings: dict[str, str]
    row_groups: list[RowGroup]
    caption_pattern: str
    caption_bindings: dict[str, str] = Field(default_factory=dict)
    sort: list[SortRule] = Field(default_factory=list)
    level_labels: dict[str, str] = Field(default_factory=dict)
    column_weights: list[float] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode='after')
    def contract(self):
        keys = [key for leaf in _leaves(self.headers) for key in leaf.columns]
        for field in list(self.column_bindings) + list(self.column_bindings.values()) + list(self.caption_bindings.values()):
            _path(field)
        fields = set()
        for _, field, formatting, conversion in Formatter().parse(self.caption_pattern):
            if field is not None:
                fields.add(field)
        for group in self.row_groups:
            for rule in group.merges:
                if not set(rule.columns) <= set(keys):
                    raise ValueError('TABLE_SPEC_UNKNOWN_MERGE_COLUMN')
                [keys.index(k) for k in rule.columns]
        return self


def column_keys(spec):
    spec = TableSpec.model_validate(spec)
    return [key for leaf in _leaves(spec.headers) for key in leaf.columns]


def validate_table_specs(specs):
    return {role: TableSpec.model_validate(spec).model_dump(mode='json') for role, spec in specs.items()}


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
        if not isinstance(value, dict):
            raise ActionRejected('TABLE_SPEC_MISSING_BINDING: ' + path)
        value = value[key]
    return value


def _text(value):
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
        rows[r0][c0]
        occupied.update(cells)
        merges.append(dict(start_row=r0, end_row=r1, start_col=c0, end_col=c1))
    for group in spec.row_groups:
        data = _lookup(saved_table_records, group.binding)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ActionRejected('TABLE_SPEC_ROWS_REQUIRED: ' + group.binding)
        indexed = list(enumerate(data))
        for order in reversed(spec.sort):
            indexed.sort(key=lambda pair: _lookup(pair[1], order.binding), reverse=order.direction == 'descending')
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
    _plan_key, _assessment_key = Ref.model_validate(plan_ref), Ref.model_validate(assessment_ref)
    plan = cs._read(db, plan_ref)['payload']
    assessment = cs._read(db, assessment_ref)['payload']
    matches = [s for s in plan.get('table_specs', {}).values() if s['table_type'] == table_type]
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
        return matches[0]
    issues, citations = [], []
    definitions = {r['id']:r for r in plan['payload']['method_pack']['indicators']}
    from .draft_assessment import display_rows
    for row in display_rows(result, plan['payload']['method_pack']):
        sources = []
        for citation in row['sources']:
            title = cs._read(db, citation['source_ref'])['payload']['source_metadata'].get('title')
            if not title:
                title = citation['source_ref']['id']
            sources.append({'document': title, 'page': citation['locator']})
            if citation not in citations:
                citations.append(citation)
        positions = [n for n, origin in enumerate(origins['evaluation'])
                     if origin['binding'] == 'evaluation.rows' and
                     table_records['evaluation']['rows'][origin['index']]['indicator_id'] == row['indicator_id']]
        issues.append({'id': digest([assessment_ref, row['indicator_id']]), 'kind': 'unclear' if row['basis_kind'] == 'missing' else row['basis_kind'],
            'object_label': label + ' / ' + definitions[row['indicator_id']].get('display_label', definitions[row['indicator_id']]['label']),
            'basis': row['rationale'], 'sources': sources,
            'adopted_value': row['value'], 'question': row['question'],
            'anchor': {'row': min(positions), 'column': column('evaluation', 'value')},
            'affects_level': result.get('affects_level', not result.get('level_robust', False))})
    bodies['evaluation']['material_issues'] = issues
    return bodies['ranking'], bodies['evaluation'], citations
