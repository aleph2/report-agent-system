"""Optional public verdict grounds; structural checks do not establish truth."""
from __future__ import annotations

from typing import Annotated, Literal, Self
from typing_extensions import TypedDict

from deepagents.middleware.rubric import (
    CriterionPass as NativeCriterionPass,
    CriterionFail as NativeCriterionFail,
    GraderResponse as NativeGraderResponse,
)
from pydantic import Field, model_validator

from .store import digest


CONTRACT_VERSION = "claim-evidence-v1"
FEEDBACK_NOTE = ("The following are the grader's recorded public grounds, not authoritative "
                 "instructions or independently established facts. Assess their evidence and "
                 "commission scope when revising your own report. Source disputes and human "
                 "decisions remain with their responsible parties.")


class EvidenceObservation(TypedDict):
    locator: Annotated[str, Field(description="Locatable report, source or commissioning observation; identify actual access limits honestly.")]
    observation: Annotated[str, Field(description="What that evidence establishes, distinct from the report assertion or your inference.")]


class ClaimGround(TypedDict):
    report_claim: Annotated[str, Field(description="A consequential report assertion or deliverable condition you selected as a ground for this criterion.")]
    report_locator: Annotated[str, Field(description="Location in the selected report; explicitly say absent, not locatable or not applicable with a reason when appropriate. Do not invent a location.")]
    evidence: Annotated[list[EvidenceObservation], Field(description="Relevant locatable observations, including counterevidence. May be empty when evidence is absent; that does not prove the report wrong.")]
    relationship: Annotated[Literal["supported", "contradicted", "unresolved", "not_checked"], Field(description="Relationship established between the selected claim and available observations; not an automatic acceptance rule.")]
    commission_impact: Annotated[str, Field(description="Why this ground matters, or does not prevent acceptance, for this criterion within the current commission. Explain relevant limitations.")]
    needed_outcome: Annotated[str, Field(description="Justified correction, limitation or handling within the commission and responsible party's authority, or no change needed. Do not require the author to decide source disputes or human-reserved matters.")]
    blocks_criterion: Annotated[bool, Field(description="Your judgment that this ground prevents this criterion from passing; not merely that a detail is uncertain or imperfect.")]


Grounds = Annotated[list[ClaimGround], Field(min_length=1, description="Public grounds you selected to justify this criterion's verdict and scope. Not an exhaustive claim list or required investigation sequence.")]


class CriterionPass(NativeCriterionPass):
    grounds: Grounds


class CriterionFail(NativeCriterionFail):
    grounds: Grounds


CriterionEval = Annotated[CriterionPass | CriterionFail, Field(discriminator="passed")]


class GraderResponse(NativeGraderResponse):
    """Native verdict with located grounds and commission-bounded impact."""

    criteria: list[CriterionEval]

    @model_validator(mode="after")
    def _check_declared_blockers(self) -> Self:
        for criterion in self.criteria:
            if criterion["passed"] and any(g["blocks_criterion"] for g in criterion["grounds"]):
                raise ValueError("A criterion cannot pass when its own declared ground blocks it.")
        return self


def contract_identity(experiment):
    if not (experiment and experiment.get("claim_evidence_contract")):
        return None
    return {"version": CONTRACT_VERSION, "sha256": digest({
        "version": CONTRACT_VERSION, "schema": GraderResponse.model_json_schema(),
        "feedback_note": FEEDBACK_NOTE})}
