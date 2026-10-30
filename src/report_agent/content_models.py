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
    type: str = Field(min_length=1)
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


class Requirement(Contract):
    text: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    scope: str = Field(min_length=1)


class Criterion(Contract):
    requirement_refs: list[Ref] = Field(min_length=1)
    purpose: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    expected_outcome: str = Field(min_length=1)
    evidence_expectation: str = Field(min_length=1)
    allowed_limits: str


class TableBody(Contract):
    """One table-shape declaration for published schema and runtime validation."""
    model_config = ConfigDict(extra="allow")
    columns: list[Any] = Field(min_length=1, strict=True)
    rows: list[Annotated[list[Any], Field(strict=True)]] = Field(strict=True,
        description="Every row must have exactly the same number of cells as columns; validated by the application.")

    @model_validator(mode="after")
    def rectangular(self) -> Self:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("TABLE_REQUIRES_NAMED_COLUMNS_AND_RECTANGULAR_ROWS")
        return self


class ContentNode(Contract):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"allOf": [
        {"if": {"properties": {"kind": {"enum": ["report", "chapter", "block", "cell", "claim"]}}, "required": ["kind"]},
         "then": {"properties": {"body": {"type": "object", "required": ["text"],
             "properties": {"text": {"type": "string", "minLength": 1, "description": "Complete rendered text; must contain non-whitespace content. Other fields do not replace text."}}}}}},
        {"if": {"properties": {"kind": {"const": "table"}}, "required": ["kind"]},
         "then": {"properties": {"body": TableBody.model_json_schema()}}},
        {"if": {"properties": {"kind": {"const": "figure"}}, "required": ["kind"]},
         "then": {"properties": {"body": {"type": "object", "required": ["source_id", "caption", "page"],
             "properties": {"source_id": {"type": "string", "minLength": 1},
                            "caption": {"type": "string", "minLength": 1},
                            "page": {"type": "integer", "minimum": 1,
                                "description": "Explicit 1-based physical PDF page index, not a printed page label or caption. Use integer 1 for a single raster image. No string labels, inferred page or implicit first-page selection."}}}}}}
    ]})
    kind: Literal["report", "chapter", "block", "table", "cell", "claim", "figure"]
    body: dict[str, Any] = Field(description="Kind-specific complete content: report/chapter/block/cell/claim require nonblank text; table requires named columns and rectangular rows; figure requires source_id, caption and page (a positive integer 1-based physical PDF page; integer 1 for a single raster image). Auxiliary fields do not substitute for these rendered fields. Tables may include a visible footnote string: nonblank text is exported verbatim, absent/null/blank adds no note, and non-text footnotes are explicitly rejected at export.")
    qualifiers: dict[str, Any] = Field(description="Report-visible technical qualifications, uncertainty and source attribution. Nonstructural keys and values are rendered in Word/Excel, not hidden metadata. Preserve real engineering unknowns and conflicting evidence here or in body. Processing/OCR diagnostics and model execution notes belong in the text-work result's separate generation_notes, not these report fields.")
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
    locator: str = Field(min_length=1)
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
    position: int | None = Field(default=None, ge=0)

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
    basis: str = Field(min_length=1)


class Observation(Contract):
    locator: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    receipt_id: str = Field(min_length=1)
    limitations: str = ""


class Finding(Contract):
    finding_type: Literal["candidate", "confirmed_defect", "unresolved", "suggestion"]
    locator_state: Literal["located", "absent", "ambiguous"]
    description: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    needed_outcome: str = Field(min_length=1)
    requirement_index: int | None = Field(default=None, ge=0)
    observation_indexes: list[int] | None = None
    basis_kind: Literal['supplied_content', 'snapshot_structure', 'input_gap'] | None = None


class CheckResult(Contract):
    """Execution account for one assigned check; linked evidence is not semantic proof."""
    requirement_index: int = Field(ge=0)
    execution_state: Literal["not_started", "partial", "completed", "blocked"]
    result: str = Field(min_length=1)
    observation_indexes: list[int] = Field(default_factory=list)
    remaining: str = ""

    @model_validator(mode="after")
    def supported_account(self) -> Self:
        if any(i < 0 for i in self.observation_indexes) or len(set(self.observation_indexes)) != len(self.observation_indexes):
            raise ValueError("CHECK_OBSERVATION_INDEXES_MUST_BE_DISTINCT_AND_NONNEGATIVE")
        if not self.result.strip():
            raise ValueError("CHECK_RESULT_REQUIRED")
        if self.execution_state == "completed" and (not self.observation_indexes or self.remaining.strip()):
            raise ValueError("COMPLETED_CHECK_REQUIRES_LINKED_OBSERVATIONS_AND_NO_REMAINING_WORK")
        if self.execution_state != "completed" and not self.remaining.strip():
            raise ValueError("UNFINISHED_CHECK_REQUIRES_REMAINING_REASON")
        return self


class ReviewItem(Contract):
    target_ref: Ref
    criterion_ref: Ref
    scope: str = Field(min_length=1)
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
    reason: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        for finding in self.findings:
            if finding.observation_indexes is not None:
                indexes = finding.observation_indexes
                if (not indexes or len(set(indexes)) != len(indexes) or
                        any(i < 0 or i >= len(self.observations) for i in indexes)):
                    raise ValueError('FINDING_REQUIRES_VALID_OBSERVATION_LINKS')
            if finding.finding_type == 'confirmed_defect' and finding.basis_kind == 'input_gap':
                raise ValueError('INPUT_GAP_IS_NOT_CONFIRMED_CONTENT_DEFECT')
        if self.check_results is not None:
            indexes = [c.requirement_index for c in self.check_results]
            if len(set(indexes)) != len(indexes):
                raise ValueError("DUPLICATE_CHECK_RESULT")
            if any(i >= len(self.observations) for c in self.check_results for i in c.observation_indexes):
                raise ValueError("CHECK_OBSERVATION_INDEX_OUTSIDE_ITEM")
            completed = {c.requirement_index for c in self.check_results if c.execution_state == "completed"}
            if self.checked_requirement_indexes is not None and set(self.checked_requirement_indexes) != completed:
                raise ValueError("CHECK_DECLARATION_CONFLICTS_WITH_RESULTS")
            if self.verdict == "satisfied" and any(c.execution_state != "completed" for c in self.check_results):
                raise ValueError("UNFINISHED_ASSIGNED_CHECK_CANNOT_PASS")
        if self.checked_requirement_indexes is not None and (
                any(i < 0 for i in self.checked_requirement_indexes) or
                len(set(self.checked_requirement_indexes)) != len(self.checked_requirement_indexes)):
            raise ValueError("CHECK_INDEXES_MUST_BE_DISTINCT_AND_NONNEGATIVE")
        if self.assessment_kind != "content" and not self.artifact_refs:
            raise ValueError("ARTIFACT_ASSESSMENT_REQUIRES_EXACT_EXPORT_OR_RENDER")
        if self.execution_state == "not_started" and self.verdict is not None:
            raise ValueError("UNEXECUTED_REVIEW_HAS_NO_VERDICT")
        if self.verdict is not None and not self.observations:
            raise ValueError("VERDICT_REQUIRES_ACTUAL_OBSERVATIONS")
        if self.verdict == "satisfied" and (self.execution_state != "completed" or
                self.coverage.unchecked or self.coverage.blocked or not self.coverage.checked):
            raise ValueError("SATISFACTION_REQUIRES_COMPLETED_DECLARED_SCOPE")
        if self.verdict == "satisfied" and any(f.finding_type == "confirmed_defect" for f in self.findings):
            raise ValueError("CONFIRMED_CRITERION_DEFECT_CANNOT_PASS")
        return self


class CoverageAccounting(Contract):
    target_refs: list[Ref] = Field(min_length=1)
    state: Literal["assessed", "partial", "not_assessed", "not_applicable"]
    item_indexes: list[int] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class ReviewSubmission(Contract):
    target_ref: Ref
    snapshot_ref: Ref
    scope: str = Field(min_length=1)
    criteria_refs: list[Ref] = Field(min_length=1)
    dependency_refs: list[Ref]
    items: list[ReviewItem] = Field(min_length=1)
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
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.verdict is not None:
            expected = "RenderArtifact" if self.kind == "render" else "ExportArtifact"
            if not self.observations or not any(r.type == expected for r in self.artifact_refs):
                raise ValueError("DELIVERY_JUDGMENT_REQUIRES_ARTIFACT_OBSERVATIONS")
        if self.execution_state == "not_started" and self.verdict is not None:
            raise ValueError("UNEXECUTED_REVIEW_HAS_NO_VERDICT")
        if self.verdict == "satisfied" and (self.execution_state != "completed" or
                self.coverage.unchecked or self.coverage.blocked or not self.coverage.checked):
            raise ValueError("SATISFACTION_REQUIRES_COMPLETED_DECLARED_SCOPE")
        return self


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
