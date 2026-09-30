"""Versioned business contracts; validation establishes structure, not truth."""
from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "hierarchical-review-v1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ref(Contract):
    type: str = Field(min_length=1)
    id: str = Field(min_length=1)
    version: int = Field(ge=1, strict=True)

    def key(self):
        return (self.type, self.id, self.version)


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


class ContentNode(Contract):
    kind: Literal["report", "chapter", "block", "table", "cell", "claim", "figure"]
    body: dict[str, Any]
    qualifiers: dict[str, Any]
    claim_kind: Literal["fact", "calculation", "inference", "recommendation", "structure"]

    @model_validator(mode="after")
    def actual_content(self) -> Self:
        if self.kind == "table":
            if (not self.body.get("columns") or not isinstance(self.body.get("rows"), list)
                    or any(len(row) != len(self.body["columns"]) for row in self.body["rows"])):
                raise ValueError("TABLE_REQUIRES_NAMED_COLUMNS_AND_RECTANGULAR_ROWS")
        elif self.kind == "figure":
            if not self.body.get("source_id") or not self.body.get("caption"):
                raise ValueError("FIGURE_REQUIRES_SOURCE_AND_CAPTION")
        elif not isinstance(self.body.get("text"), str) or not self.body["text"].strip():
            raise ValueError("ACTUAL_CONTENT_REQUIRED")
        return self


class SourceArtifact(Contract):
    source_id: str
    file_digest: str
    coverage: str
    source_metadata: dict[str, Any]
    content: str


class Evidence(Contract):
    source_refs: list[Ref]
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


class ReviewItem(Contract):
    target_ref: Ref
    criterion_ref: Ref
    scope: str = Field(min_length=1)
    assessment_kind: Literal["content", "export", "render", "combined"] = "content"
    artifact_refs: list[Ref] = Field(default_factory=list)
    execution_state: Literal["not_started", "running", "completed", "blocked"]
    verdict: Literal["satisfied", "not_satisfied", "undetermined"] | None
    observations: list[Observation]
    coverage: Coverage
    reason: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.assessment_kind != "content" and not self.artifact_refs:
            raise ValueError("ARTIFACT_ASSESSMENT_REQUIRES_EXACT_EXPORT_OR_RENDER")
        if any(r.type not in {"ExportArtifact", "RenderArtifact"} for r in self.artifact_refs):
            raise ValueError("ARTIFACT_REF_TYPE_REQUIRED")
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
    artifact_refs: list[Ref] = Field(default_factory=list)
    execution_state: Literal["not_started", "running", "completed", "blocked"]
    verdict: Literal["satisfied", "not_satisfied", "undetermined"] | None
    observations: list[Observation]
    coverage: Coverage
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if any(r.type not in {"ExportArtifact", "RenderArtifact"} for r in self.artifact_refs):
            raise ValueError("ARTIFACT_REF_TYPE_REQUIRED")
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
        return (Ref.model_validate(item["target_ref"]).key(), Ref.model_validate(item["criterion_ref"]).key(), item["scope"])
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
