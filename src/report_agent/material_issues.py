"""Frozen clarification pointers, shared by Word and Excel; never evidence objects."""
from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .content_models import Ref
from .errors import ActionRejected


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
            locator = f"第{self.page}页"
        else:
            locator = self.page.strip()
            if locator == "manifest text":
                locator = "全文"
            elif match := re.fullmatch(r"line ([1-9][0-9]*)", locator):
                locator = f"第{match[1]}行"
            else:
                match = re.fullmatch(r"(?:page\s+)?(\d+)", locator, re.IGNORECASE)
                if match:
                    locator = f"第{match[1]}页"
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
    anchor: CellAnchor | PassageAnchor
    affects_level: bool

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
        return "；".join(source.readable() for source in self.sources) or "无可用证据"

    def comment(self):
        return (f"{LABELS[self.kind]}｜{self.object_label}\n依据：{self.basis}\n资料：{self.source_text()}"
                f"\n采用值：{self.adopted_value}\n待确认：{self.question}"
                + ("\n影响等级：是，补充资料后需复核。" if self.affects_level else "\n影响等级：否"))


class TableMerge(StrictRecord):
    start_row: int = Field(ge=0)
    end_row: int = Field(ge=0)
    start_col: int = Field(ge=0)
    end_col: int = Field(ge=0)


def validate_node(node):
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
    try:
        merges = [TableMerge.model_validate(item) for item in raw_merges]
    except ValidationError as exc:
        raise ActionRejected("TABLE_MERGE_INVALID: " + str(exc)) from exc
    occupied = set()
    covered = set()
    for merge in merges:
        if (node["kind"] != "table" or merge.start_row > merge.end_row or merge.start_col > merge.end_col
                or merge.end_row >= len(body["rows"]) or merge.end_col >= len(body["columns"])):
            raise ActionRejected("TABLE_MERGE_BOUNDS")
        cells = {(r, c) for r in range(merge.start_row, merge.end_row + 1)
                 for c in range(merge.start_col, merge.end_col + 1)}
        if occupied & cells:
            raise ActionRejected("TABLE_MERGE_OVERLAP")
        primary = (merge.start_row, merge.start_col)
        value = str(body["rows"][primary[0]][primary[1]])
        if any(str(body["rows"][r][c]) not in ("", value) for r, c in cells):
            raise ActionRejected("TABLE_MERGE_WOULD_LOSE_TEXT")
        occupied |= cells
        covered |= cells - {primary}
    seen = set()
    for issue in issues:
        if issue.id in seen:
            raise ActionRejected("MATERIAL_ISSUE_DUPLICATE_ID: " + issue.id)
        seen.add(issue.id)
        anchor = issue.anchor
        if isinstance(anchor, CellAnchor):
            if (node["kind"] != "table" or anchor.row >= len(body["rows"])
                    or anchor.column >= len(body["columns"])):
                raise ActionRejected("MATERIAL_ISSUE_ANCHOR_BOUNDS: " + issue.id)
            if (anchor.row, anchor.column) in covered:
                raise ActionRejected("MATERIAL_ISSUE_MERGED_AWAY_ANCHOR: " + issue.id)
            if str(body["rows"][anchor.row][anchor.column]) != issue.adopted_value:
                raise ActionRejected("MATERIAL_ISSUE_VALUE_MISMATCH: " + issue.id)
        elif (node["kind"] in {"table", "figure"} or anchor.text != issue.adopted_value
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
        issues, _ = validate_node(records[key]["payload"])
        for issue in issues:
            if issue.id in ids:
                raise ActionRejected("MATERIAL_ISSUE_DUPLICATE_ID: " + issue.id)
            ids.add(issue.id)
            result.append((ref, issue))
        for _, child in sorted(edges.get(key, []), key=lambda pair: pair[0]):
            visit(child)
    visit(root_ref)
    return result


def comment_passage(doc, paragraphs, issue):
    """Split existing runs at exact anchor boundaries, preserving their formatting."""
    from copy import deepcopy
    from docx.text.run import Run
    target = issue.adopted_value
    matches = [paragraph for paragraph in paragraphs if target in paragraph.text]
    if len(matches) != 1 or matches[0].text.count(target) != 1:
        raise ActionRejected("MATERIAL_ISSUE_RENDERED_PASSAGE_NOT_UNIQUE: " + issue.id)
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
        raise ActionRejected("MATERIAL_ISSUE_RENDERED_RUNS_UNSUPPORTED: " + issue.id)
    doc.add_comment(selected, issue.comment(), author="工程资料澄清", initials="审")
