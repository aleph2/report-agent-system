"""Versioned business contracts; validation establishes structure, not truth."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "hierarchical-review-v1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RenderState(Contract):
    """This operation's renderer facts, not visual review or host-wide support."""
    execution_state: Literal["not_attempted", "completed", "failed", "blocked"]
    capability_state: Literal["not_probed", "available", "unavailable", "unsupported", "unknown"]


class Ref(Contract):
    type: str
    id: str = Field(min_length=1)
    version: int = Field(ge=1, strict=True)

    def key(self):
        return (self.type, self.id, self.version)


class ArtifactRef(Ref):
    type: Literal["ExportArtifact", "RenderArtifact"]


class SnapshotReplacement(Contract):
    previous_ref: Ref = Field(description="Exact existing member of the immutable base snapshot.")
    new_ref: Ref = Field(description="Explicit saved version of the same logical type/id; never inferred from current head.")

    @model_validator(mode="after")
    def same_identity(self) -> Self:
        if (self.previous_ref.type, self.previous_ref.id) != (self.new_ref.type, self.new_ref.id):
            raise ValueError("SNAPSHOT_REPLACEMENT_REQUIRES_SAME_IDENTITY")
        return self


class SourceCitation(Contract):
    source_ref: Ref
    locator: str
    quote: str = ''


class InventoryValue(Contract):
    value: str | None
    source: SourceCitation | None
    reason: str



class InventoryAttribute(Contract):
    name: str
    values: list[InventoryValue]


class InventoryObject(Contract):
    object_id: str = Field(min_length=1)
    label: str
    included: bool = Field(strict=True)
    reason: str
    origin: str
    attributes: list[InventoryAttribute]
    sources: list[SourceCitation]


class Requirement(Contract):
    text: str
    origin: str
    scope: str
    inventory_object: InventoryObject | None = Field(default=None, exclude_if=lambda value: value is None)


class Criterion(Contract):
    requirement_refs: list[Ref]
    purpose: str
    scope: str
    expected_outcome: str
    evidence_expectation: str
    allowed_limits: str


class CellMerge(Contract):
    start_row: int = Field(strict=True)
    end_row: int = Field(strict=True)
    start_col: int = Field(strict=True)
    end_col: int = Field(strict=True)


class TableBody(Contract):
    """One table-shape declaration for published schema and runtime validation."""
    model_config = ConfigDict(extra="allow")
    columns: list[Any] = Field(strict=True)
    rows: list[Annotated[list[Any], Field(strict=True)]] = Field(strict=True,
        description="Every row must have exactly the same number of cells as columns; validated by the application.")
    header_rows: list[list[str]] | None = Field(default=None, exclude_if=lambda value: value is None,
        description="Rendered header matrix; body row indexes do not include these header rows.")
    header_merges: list[CellMerge] = Field(default_factory=list, exclude_if=lambda value: not value,
        description="Header-relative spans, separate from data-row merges and issue anchors.")

    @model_validator(mode="after")
    def rectangular(self) -> Self:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("TABLE_REQUIRES_NAMED_COLUMNS_AND_RECTANGULAR_ROWS")
        if self.header_rows is not None and (not self.header_rows or
                any(len(row) != len(self.columns) for row in self.header_rows)):
            raise ValueError("TABLE_HEADER_REQUIRES_RECTANGULAR_ROWS")
        if self.header_merges and self.header_rows is None:
            raise ValueError("TABLE_HEADER_ROWS_REQUIRED")
        return self


def _table_body_schema():
    # This schema is embedded manually; local definitions must not escape into the parent model.
    schema = TableBody.model_json_schema()
    definitions = schema.pop('$defs', {})
    def inline(value):
        if isinstance(value, dict):
            if '$ref' in value:
                return inline(definitions[value['$ref'].removeprefix('#/$defs/')])
            return {key: inline(child) for key, child in value.items()}
        return [inline(child) for child in value] if isinstance(value, list) else value
    return inline(schema)


class ContentNode(Contract):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"allOf": [
        {"if": {"properties": {"kind": {"enum": ["report", "chapter", "block", "cell", "claim"]}}, "required": ["kind"]},
         "then": {"properties": {"body": {"type": "object", "required": ["text"],
             "properties": {"text": {"type": "string", "minLength": 1, "description": "Complete rendered text; must contain non-whitespace content. Other fields do not replace text."}}}}}},
        {"if": {"properties": {"kind": {"const": "table"}}, "required": ["kind"]},
         "then": {"properties": {"body": _table_body_schema()}}},
        {"if": {"properties": {"kind": {"const": "figure"}}, "required": ["kind"]},
         "then": {"properties": {"body": {"type": "object", "required": ["source_id", "caption", "page"],
             "properties": {"source_id": {"type": "string", "minLength": 1},
                            "caption": {"type": "string", "minLength": 1},
                            "page": {"type": "integer", "minimum": 1,
                                "description": "Explicit 1-based physical PDF page index, not a printed page label or caption. Use integer 1 for a single raster image. No string labels, inferred page or implicit first-page selection."}}}}}}
    ]})
    kind: Literal["report", "chapter", "block", "table", "cell", "claim", "figure"]
    body: dict[str, Any] = Field(description="Kind-specific complete content: report/chapter/block/cell/claim require nonblank text; table requires named columns and rectangular rows; figure requires source_id, caption and page (a positive integer 1-based physical PDF page; integer 1 for a single raster image). Auxiliary fields do not substitute for these rendered fields. Tables may include a visible footnote string: nonblank text is exported verbatim, absent/null/blank adds no note, and non-text footnotes are explicitly rejected at export.")
    qualifiers: dict[str, Any] = Field(description="Report-visible technical qualifications. Material gaps and conflicts belong in body.material_issues for anchored Word comments and the Excel list. Execution notes belong in working_notes.")
    citations: list[SourceCitation] = Field(default_factory=list, exclude_if=lambda value: not value)
    working_notes: str = Field(default='', exclude_if=lambda value: not value,
        description='Audit-only working notes, never exported as report content.')
    claim_kind: Literal["fact", "calculation", "inference", "recommendation", "structure"]

    @model_validator(mode="after")
    def actual_content(self) -> Self:
        if self.kind == "table":
            TableBody.model_validate(self.body)
        elif self.kind == "figure":
            if not self.body.get("source_id") or not self.body.get("caption"):
                raise ValueError("FIGURE_REQUIRES_SOURCE_AND_CAPTION")
            if type(self.body.get("page")) is not int or self.body["page"] < 1:
                raise ValueError("FIGURE_REQUIRES_EXPLICIT_POSITIVE_INTEGER_PHYSICAL_PAGE")
        elif not isinstance(self.body.get("text"), str) or not self.body["text"].strip():
            raise ValueError("ACTUAL_CONTENT_REQUIRED")
        return self


class SourceArtifact(Contract):
    source_id: str
    file_digest: str
    coverage: str
    source_metadata: dict[str, Any]
    content: str


class SourceRef(Ref):
    type: Literal['SourceArtifact']


class Evidence(Contract):
    source_refs: list[SourceRef] = Field(description='Actual supplied SourceArtifact version refs; catalog source IDs are not business refs.')
    locator: str
    excerpt: str
    extraction_ref: Ref | None = None
    input_refs: list[Ref] = Field(default_factory=list)
    method: str = ""
    tool_receipt: str = ""
    result: Any = None

    @model_validator(mode="after")
    def reproducible(self) -> Self:
        if not self.source_refs and not (self.input_refs and self.method and self.tool_receipt):
            raise ValueError("SOURCE_OR_REPRODUCIBLE_CALCULATION_REQUIRED")
        return self


class TextEvidence(Evidence):
    """Text producer route; deterministic calculation/extraction use their own tools."""
    source_refs: list[SourceRef] = Field(min_length=1,
        description='At least one genuine source ref from the prepared material; never infer a ref from objective prose.')
    extraction_ref: None = Field(default=None, description='No extraction receipt is minted by text processing.')
    tool_receipt: Literal[''] = Field(default='', description='No deterministic calculation receipt is minted by text processing.')


class Relation(Contract):
    subject_ref: Ref
    predicate: Literal["contains", "supported_by", "contradicted_by", "depends_on", "references", "expresses"]
    object_ref: Ref
    provenance_kind: Literal["adopted_during_generation", "found_during_review", "observed_only"]
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    basis_refs: list[Ref] = Field(default_factory=list)
    position: int | None = Field(default=None)

    @model_validator(mode="after")
    def endpoints(self) -> Self:
        if self.predicate == "contains" and (self.position is None or
                self.subject_ref.type != "ContentNode" or self.object_ref.type != "ContentNode"):
            raise ValueError("CONTAINS_REQUIRES_POSITION_AND_CONTENT_ENDPOINTS")
        if self.predicate in {"supported_by", "contradicted_by"} and (
                self.subject_ref.type != "ContentNode" or self.object_ref.type != "Evidence"):
            raise ValueError("SUPPORT_RUNS_FROM_CONTENT_TO_EVIDENCE")
        return self


class Coverage(Contract):
    checked: list[str]
    unchecked: list[str]
    blocked: list[str]
    basis: str


class Observation(Contract):
    locator: str
    observation: str
    receipt_id: str = Field(min_length=1)
    limitations: str = ""


class Finding(Contract):
    finding_type: Literal["candidate", "confirmed_defect", "unresolved", "suggestion"]
    locator_state: Literal["located", "absent", "ambiguous"]
    description: str
    impact: str
    needed_outcome: str
    requirement_index: int | None = Field(default=None, ge=0)
    observation_indexes: list[int] | None = None
    basis_kind: str | None = None


class CheckResult(Contract):
    """Execution account for one assigned check; linked evidence is not semantic proof."""
    requirement_index: int = Field(ge=0)
    execution_state: Literal["not_started", "partial", "completed", "blocked"]
    result: str
    observation_indexes: list[int] = Field(default_factory=list)
    remaining: str = ""

    @model_validator(mode="after")
    def supported_account(self) -> Self:
        if any(i < 0 for i in self.observation_indexes):
            raise ValueError("CHECK_OBSERVATION_INDEXES_MUST_BE_DISTINCT_AND_NONNEGATIVE")
        if not self.result.strip():
            raise ValueError("CHECK_RESULT_REQUIRED")
        return self


class ReviewItem(Contract):
    target_ref: Ref
    criterion_ref: Ref
    scope: str
    scope_id: str | None = Field(default=None, min_length=1)
    checked_requirement_indexes: list[int] | None = Field(default=None,
        description="Zero-based indexes of actually performed required_checks in the saved task's matching scope_id. Wording may differ; indexes do not establish correctness.")
    dependency_refs: list[Ref] | None = None
    assessment_kind: Literal["content", "export", "render"] = "content"
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    execution_state: Literal["not_started", "running", "completed", "blocked"]
    verdict: Literal["satisfied", "not_satisfied", "undetermined"] | None
    observations: list[Observation]
    check_results: list[CheckResult] | None = None
    outside_assignment_notes: list[str] = Field(default_factory=list,
        description="Explicitly outside this saved task. Does not waive an assigned check or establish full commissioned coverage.")
    coverage: Coverage
    reason: str
    findings: list[Finding] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        for finding in self.findings:
            if finding.observation_indexes is not None:
                indexes = finding.observation_indexes
                if any(i < 0 or i >= len(self.observations) for i in indexes):
                    raise ValueError('FINDING_REQUIRES_VALID_OBSERVATION_LINKS')
        if self.check_results and any(
                i >= len(self.observations) for c in self.check_results for i in c.observation_indexes):
            raise ValueError("CHECK_OBSERVATION_INDEX_OUTSIDE_ITEM")
        if self.checked_requirement_indexes is not None and (
                any(i < 0 for i in self.checked_requirement_indexes)
        ):
            raise ValueError("CHECK_INDEXES_MUST_BE_DISTINCT_AND_NONNEGATIVE")
        return self


class CoverageAccounting(Contract):
    target_refs: list[Ref]
    state: Literal["assessed", "partial", "not_assessed", "not_applicable"]
    item_indexes: list[int] = Field(default_factory=list)
    reason: str


class ReviewSubmission(Contract):
    target_ref: Ref
    snapshot_ref: Ref
    scope: str
    criteria_refs: list[Ref]
    dependency_refs: list[Ref]
    items: list[ReviewItem]
    delivery_checks: list["DeliveryCheck"] = Field(default_factory=list)
    coverage_accounting: list[CoverageAccounting] = Field(default_factory=list)


class DeliveryCheck(Contract):
    """System delivery responsibilities, separate from business criteria and methods."""
    kind: Literal["export", "render"]
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    execution_state: Literal["not_started", "running", "completed", "blocked"]
    verdict: Literal["satisfied", "not_satisfied", "undetermined"] | None
    observations: list[Observation]
    coverage: Coverage
    reason: str



ReviewSubmission.model_rebuild()


def delivery_aggregate(content: dict, checks: list[dict]) -> dict:
    """Missing work stays unexecuted; a confirmed defect survives partial execution."""
    by_kind = {c["kind"]: c for c in checks}
    missing = [kind for kind in ("export", "render") if kind not in by_kind]
    complete = content["coverage_complete"] and not missing and all(
        c["execution_state"] == "completed" and not c["coverage"]["unchecked"] and not c["coverage"]["blocked"]
        for c in checks)
    verdicts = [content["overall_verdict"], *[c["verdict"] for c in checks]]
    verdict = ("not_satisfied" if "not_satisfied" in verdicts else None if not complete or None in verdicts
               else "undetermined" if "undetermined" in verdicts else "satisfied")
    return {**content, "overall_verdict": verdict, "coverage_complete": bool(complete),
            "missing_delivery_checks": missing}


PAYLOADS = {c.__name__: c for c in (Requirement, Criterion, ContentNode, SourceArtifact, Evidence, Relation)}


def refs_in(value):
    """Only typed references, never IDs inferred from prose."""
    if isinstance(value, dict):
        if set(value) == {"type", "id", "version"}:
            yield Ref.model_validate(value)
        else:
            for child in value.values():
                yield from refs_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs_in(child)


def aggregate(items: list[dict], required: list[dict]) -> dict:
    """Aggregate explicit scope obligations, never infer parent coverage from children."""
    def key(item):
        return (Ref.model_validate(item["target_ref"]).key(), Ref.model_validate(item["criterion_ref"]).key(), item.get("scope_id") or item["scope"])
    selected = {}
    for item in items:
        current = selected.get(key(item))
        if current is None or current["verdict"] != "not_satisfied":
            selected[key(item)] = item
    rows = [selected.get(key(r)) for r in required]
    complete = bool(rows) and all(r and r["execution_state"] == "completed" and
                                  not r["coverage"]["unchecked"] and not r["coverage"]["blocked"] for r in rows)
    if any(r and r["verdict"] == "not_satisfied" for r in rows):
        verdict = "not_satisfied"
    elif not complete:
        verdict = None
    elif any(r["verdict"] == "undetermined" for r in rows):
        verdict = "undetermined"
    elif all(r["verdict"] == "satisfied" for r in rows):
        verdict = "satisfied"
    else:
        verdict = None
    return {"overall_verdict": verdict, "coverage_complete": complete,
            "missing_obligations": [r for r in required if key(r) not in selected]}
