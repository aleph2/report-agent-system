"""Frozen clarification pointers, shared by Word and Excel; never evidence objects."""
from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .content_models import Ref, CellMerge as TableMerge
from .errors import ActionRejected
from .position_anchors import ParagraphAnchor, comment_position


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=False)


class IssueSource(StrictRecord):
    document: str = Field(min_length=1)
    page: int | str

    @model_validator(mode="after")
    def locator_present(self):
        if (isinstance(self.page, int) and self.page < 1) or (isinstance(self.page, str) and not self.page.strip()):
            raise ValueError("source page/locator required")
        return self

    def readable(self):
        if isinstance(self.page, int):
            locator = f"PDF第{self.page}页"
        else:
            locator = self.page.strip()
            if locator == "manifest text":
                locator = "全文"
            elif match := re.fullmatch(r"(line|body/paragraph) ([1-9][0-9]*)(?:; chars [1-9][0-9]*-[1-9][0-9]*)?", locator):
                locator = f"第{match[2]}{'行' if match[1] == 'line' else '段'}"
            else:
                match = re.fullmatch(r"(?:page\s+)?(\d+)(?:;.*)?", locator, re.IGNORECASE)
                if match:
                    locator = f"PDF第{match[1]}页"
        return f"{self.document}（{locator}）"


class CellAnchor(StrictRecord):
    row: int = Field(ge=0)
    column: int = Field(ge=0)


class PassageAnchor(StrictRecord):
    text: str = Field(min_length=1)


LABELS = {"conflict": "资料冲突", "unclear": "资料不明确", "missing": "资料缺失",
          "indirect_assumption": "间接证据假设", "no_evidence_assumption": "无证据假设"}


class MaterialIssue(StrictRecord):
    id: str = Field(min_length=1)
    kind: Literal["conflict", "unclear", "missing", "indirect_assumption", "no_evidence_assumption"]
    object_label: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    sources: list[IssueSource]
    adopted_value: str = Field(min_length=1)
    question: str = Field(min_length=1)
    anchor: CellAnchor | PassageAnchor | ParagraphAnchor
    affects_level: bool = Field(description="Assumptions: calculated sensitivity. Other source issues: True conservatively flags unresolved grade impact; False requires proof this item is outside the current calculation.")

    @model_validator(mode="after")
    def meaningful_fields(self):
        if any(not value.strip() for value in (self.id, self.object_label, self.basis, self.adopted_value, self.question)):
            raise ValueError("blank issue field")
        if any(not source.document.strip() for source in self.sources):
            raise ValueError("blank source document")
        if self.kind == "indirect_assumption" and not self.sources:
            raise ValueError("indirect assumption requires source pages")
        if self.kind == "no_evidence_assumption" and self.sources:
            raise ValueError("no-evidence assumption cannot claim source evidence")
        return self

    def source_text(self):
        return "；".join(dict.fromkeys(source.readable() for source in self.sources)) or "无可用证据"

    def impact_text(self):
        if self.kind in {'indirect_assumption', 'no_evidence_assumption'}:
            return '是' if self.affects_level else '否'
        return '待复核（不能排除）' if self.affects_level else '本次评分未计入该事项；不评价实际工程风险'

    def comment(self):
        return (f"{LABELS[self.kind]}｜{self.object_label}\n依据：{self.basis}\n资料：{self.source_text()}"
                f"\n采用值：{self.adopted_value}\n待确认：{self.question}"
                + ("\n影响等级：" if self.kind in {'indirect_assumption', 'no_evidence_assumption'} else "\n等级影响：")
                + self.impact_text()
                + ("，补充资料后需复核。" if self.kind in {'indirect_assumption', 'no_evidence_assumption'} and self.affects_level else ""))


class CellComment(StrictRecord):
    text: str = Field(min_length=1)
    value: str = Field(min_length=1)
    anchor: CellAnchor

    @model_validator(mode="after")
    def meaningful(self):
        if not self.text.strip() or not self.value.strip():
            raise ValueError("blank cell comment")
        return self


def cell_comments(node):
    raw = node['body'].get('cell_comments', [])
    if not isinstance(raw, list):
        raise ActionRejected('CELL_COMMENT_LIST_REQUIRED')
    try:
        return [CellComment.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ActionRejected('CELL_COMMENT_INVALID: ' + str(exc)) from exc


def _merges(rows, raw, prefix):
    if not isinstance(raw, list):
        raise ActionRejected(prefix + '_LIST_REQUIRED')
    try:
        merges = [TableMerge.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ActionRejected(prefix + '_INVALID: ' + str(exc)) from exc
    occupied, covered = set(), set()
    for merge in merges:
        if (merge.start_row > merge.end_row or merge.start_col > merge.end_col
                or merge.end_row >= len(rows) or merge.end_col >= len(rows[merge.start_row])):
            raise ActionRejected(prefix + '_BOUNDS')
        cells = {(r, c) for r in range(merge.start_row, merge.end_row + 1)
                 for c in range(merge.start_col, merge.end_col + 1)}
        if occupied & cells:
            raise ActionRejected(prefix + '_OVERLAP')
        primary = (merge.start_row, merge.start_col)
        value = str(rows[primary[0]][primary[1]])
        if any(str(rows[r][c]) not in ('', value) for r, c in cells):
            raise ActionRejected(prefix + '_WOULD_LOSE_TEXT')
        occupied |= cells
        covered |= cells - {primary}
    return merges, covered


def table_header(body):
    """Shared header projection; all body anchors remain zero-based data indices."""
    rows = body.get('header_rows')
    if rows is None:
        if body.get('header_merges'):
            raise ActionRejected('TABLE_HEADER_ROWS_REQUIRED')
        rows = [body['columns']]
    if (not isinstance(rows, list) or not rows
            or any(not isinstance(row, list) or len(row) != len(body['columns']) for row in rows)):
        raise ActionRejected('TABLE_HEADER_RECTANGULAR_ROWS_REQUIRED')
    if body.get('header_rows') is not None and any(not isinstance(value, str) for row in rows for value in row):
        raise ActionRejected('TABLE_HEADER_TEXT_REQUIRED')
    merges, _ = _merges(rows, body.get('header_merges', []), 'TABLE_HEADER_MERGE')
    return rows, merges


def _cell_anchor(node, anchor, value, covered, prefix):
    body = node['body']
    if (node['kind'] != 'table' or anchor.row >= len(body['rows'])
            or anchor.column >= len(body['columns'])):
        raise ActionRejected(prefix + '_ANCHOR_BOUNDS')
    if (anchor.row, anchor.column) in covered:
        raise ActionRejected(prefix + '_MERGED_AWAY_ANCHOR')
    if str(body['rows'][anchor.row][anchor.column]) != value:
        raise ActionRejected(prefix + '_VALUE_MISMATCH')


def validate_node(node, node_ref=None):
    try:
        return _validate_node(node)
    except ActionRejected as exc:
        raw = node.get('body', {}).get('material_issues', [])
        ids = [item.get('id', '?') for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
        raise ActionRejected(f"{exc}; issues={ids}; node={node_ref}") from exc


def _validate_node(node):
    """Validate actual body positions before export; return typed issues and merges."""
    body = node["body"]
    raw_issues, raw_merges = body.get("material_issues", []), body.get("merges", [])
    if not isinstance(raw_issues, list):
        raise ActionRejected("MATERIAL_ISSUE_LIST_REQUIRED")
    if not isinstance(raw_merges, list):
        raise ActionRejected("TABLE_MERGE_LIST_REQUIRED")
    try:
        issues = [MaterialIssue.model_validate(item) for item in raw_issues]
    except ValidationError as exc:
        raise ActionRejected("MATERIAL_ISSUE_INVALID: " + str(exc)) from exc
    if node['kind'] == 'table':
        table_header(body)
    elif raw_merges:
        raise ActionRejected('TABLE_MERGE_BOUNDS')
    merges, covered = _merges(body.get('rows', []), raw_merges, 'TABLE_MERGE')
    for annotation in cell_comments(node):
        _cell_anchor(node, annotation.anchor, annotation.value, covered, 'CELL_COMMENT')
    seen = set()
    for issue in issues:
        if issue.id in seen:
            raise ActionRejected("MATERIAL_ISSUE_DUPLICATE_ID: " + issue.id)
        seen.add(issue.id)
        anchor = issue.anchor
        if isinstance(anchor, CellAnchor):
            _cell_anchor(node, anchor, issue.adopted_value, covered, 'MATERIAL_ISSUE')
        elif isinstance(anchor, ParagraphAnchor):
            if node['kind'] in {'table', 'figure'}:
                raise ActionRejected('MATERIAL_ISSUE_POSITION_INVALID: ' + issue.id)
        elif (node["kind"] in {"table", "figure"}
              or body.get("text", "").count(anchor.text) != 1):
            raise ActionRejected("MATERIAL_ISSUE_PASSAGE_NOT_UNIQUE: " + issue.id)
    return issues, merges


def rendered_issues(records, root_ref):
    """Only root containment contributes comments/clarifications, never dependencies."""
    edges = {}
    for record in records.values():
        p = record["payload"]
        if record["ref"]["type"] == "Relation" and p["predicate"] == "contains":
            edges.setdefault(Ref.model_validate(p["subject_ref"]).key(), []).append((p["position"], p["object_ref"]))
    result, visited, ids = [], set(), set()
    def visit(ref):
        key = Ref.model_validate(ref).key()
        if key in visited:
            return
        visited.add(key)
        issues, _ = validate_node(records[key]["payload"], ref)
        for issue in issues:
            if issue.id in ids:
                raise ActionRejected(f"MATERIAL_ISSUE_DUPLICATE_ID: {issue.id}; node={ref}")
            ids.add(issue.id)
            result.append((ref, issue))
        for _, child in sorted(edges.get(key, []), key=lambda pair: pair[0]):
            visit(child)
    visit(root_ref)
    return result


def validate_required_issues(contents, db, snapshot, records, issue_records):
    """Approved obligations come from frozen confirmation, never mutable live state."""
    plan_ref = snapshot['payload'].get('commission_plan_ref')
    if not plan_ref:
        return
    plan_record = records.get(Ref.model_validate(plan_ref).key())
    if plan_record is None or plan_ref['type'] != 'CommissionPlan':
        raise ActionRejected('MATERIAL_ISSUE_CONFIRMATION_PLAN_NOT_FROZEN')
    confirmation_ref = snapshot['payload'].get('commission_confirmation_ref')
    required = None
    if confirmation_ref:
        decision = records.get(Ref.model_validate(confirmation_ref).key())
        if (confirmation_ref['type'] != 'CommissionDecision' or decision is None
                or decision.get('owner_id') != 'operator'
                or decision['payload'].get('approved') is not True
                or decision['payload'].get('plan_ref') != plan_ref):
            raise ActionRejected('MATERIAL_ISSUE_CONFIRMATION_INVALID')
        required = decision['payload'].get('required_material_issues')
    if required is None:
        from .commission_plan import required_material_issues
        if required_material_issues(contents, db, plan_ref, plan_record['payload']):
            raise ActionRejected('MATERIAL_ISSUE_CONFIRMATION_REQUIRED')
        return
    if not isinstance(required, list):
        raise ActionRejected('MATERIAL_ISSUE_CONFIRMATION_REGISTRY_INVALID')
    actual = {issue.id: issue.model_dump() for _, issue in issue_records}
    fields = ('id', 'kind', 'object_label', 'basis', 'sources', 'question')
    seen = set()
    for expected in required:
        if (not isinstance(expected, dict) or any(key not in expected for key in fields)
                or not isinstance(expected['id'], str) or expected['id'] in seen):
            raise ActionRejected('MATERIAL_ISSUE_CONFIRMATION_REGISTRY_INVALID')
        seen.add(expected['id'])
        issue = actual.get(expected['id'])
        if issue is None:
            raise ActionRejected('REQUIRED_MATERIAL_ISSUE_NOT_RENDERED: ' + expected['id'])
        if any(issue[key] != expected[key] for key in fields):
            raise ActionRejected('REQUIRED_MATERIAL_ISSUE_MISMATCH: ' + expected['id'])


def comment_passage(doc, paragraphs, issue, node_ref):
    if isinstance(issue.anchor, ParagraphAnchor):
        return comment_position(doc, paragraphs, issue, node_ref)
    """Split existing runs at exact anchor boundaries, preserving their formatting."""
    from copy import deepcopy
    from docx.text.run import Run
    target = issue.anchor.text
    matches = [paragraph for paragraph in paragraphs if target in paragraph.text]
    if len(matches) != 1 or matches[0].text.count(target) != 1:
        raise ActionRejected(f"MATERIAL_ISSUE_RENDERED_PASSAGE_NOT_UNIQUE: {issue.id}; node={node_ref}")
    paragraph = matches[0]
    start = paragraph.text.index(target)
    stop = start + len(target)
    position, selected = 0, []
    for run in list(paragraph.runs):
        original = run.text
        end = position + len(original)
        cuts = sorted({0, len(original), max(0, min(len(original), start-position)), max(0, min(len(original), stop-position))})
        last = run._r
        for index, (left, right) in enumerate(zip(cuts, cuts[1:])):
            if index == 0:
                fragment = run
            else:
                element = deepcopy(run._r)
                last.addnext(element)
                fragment = Run(element, paragraph)
                last = element
            fragment.text = original[left:right]
            if position + left >= start and position + right <= stop:
                selected.append(fragment)
        position = end
    if "".join(run.text for run in selected) != target:
        raise ActionRejected(f"MATERIAL_ISSUE_RENDERED_RUNS_UNSUPPORTED: {issue.id}; node={node_ref}")
    doc.add_comment(selected, issue.comment(), author="工程资料澄清", initials="审")


def export_issue_records(contents, db, snapshot, records):
    """Use assembled owner positions only after receipt and unchanged issue checks."""
    from .system_assembler import require_assembled
    from .commission_owner_records import frozen_material_issues
    receipt = require_assembled(contents, db, snapshot, records)
    issues = rendered_issues(records, snapshot['payload']['root_ref'])
    owner = frozen_material_issues(contents, snapshot, records)
    if receipt is None:
        if {i.id for _, i in issues} & {i.id for i in owner}:
            raise ActionRejected('OWNER_OPEN_FACT_IS_SYSTEM_OWNED')
        return issues + [(snapshot['payload']['root_ref'], issue) for issue in owner], owner
    actual = {i.id: (ref, i) for ref, i in issues}
    for expected in owner:
        target = actual.get(expected.id)
        if (target is None or receipt['issue_targets'].get(expected.id) != target[0]
                or records[Ref.model_validate(target[0]).key()]['payload']['body'].get('section_id') != '1.3'
                or target[1].model_dump(exclude={'anchor'}) != expected.model_dump(exclude={'anchor'})):
            raise ActionRejected('ASSEMBLED_OWNER_ISSUE_MISMATCH: ' + expected.id)
    return issues, []
