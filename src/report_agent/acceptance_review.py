"""Domain acceptance outcomes on the native rubric response/feedback protocol."""
from typing import Annotated, Literal, Self

from deepagents.middleware.rubric import (
    CriterionPass as NativePass, CriterionFail as NativeFail,
    GraderResponse as NativeResponse,
)
from pydantic import Field, model_validator
from typing_extensions import TypedDict

from .review_contract import EvidenceObservation
from .store import digest


class Assessment(TypedDict):
    status: Literal["satisfied", "not_satisfied", "undetermined"]
    evidence: Annotated[list[EvidenceObservation], Field(description="Located observations supporting this conclusion, including counterevidence. Empty is honest when no evidence is available; it does not prove a defect.")]
    explanation: Annotated[str, Field(min_length=1, description="Why the observations justify this criterion outcome, with actual coverage and limitations.")]
    needed_outcome: Annotated[str, Field(description="What remains necessary within the commission and responsible party's authority, or no change needed. Unknown is not a request to invent a report correction.")]


class CriterionPass(NativePass, Assessment):
    pass


class CriterionFail(NativeFail, Assessment):
    pass


class GraderResponse(NativeResponse):
    """Acceptance of every named standard, distinct from permission to share a draft."""

    result: Literal["satisfied", "needs_revision", "undetermined", "failed"] = Field(
        description="satisfied only if all standards are satisfied; needs_revision for any established not_satisfied; undetermined if only unresolved assessment remains; failed only for an invalid rubric.")
    criteria: list[Annotated[CriterionPass | CriterionFail, Field(discriminator="passed")]]

    @model_validator(mode="after")
    def consistent_outcomes(self) -> Self:
        for item in self.criteria:
            if item["passed"] != (item["status"] == "satisfied"):
                raise ValueError("passed must agree with the domain status")
        if self.result != "failed":
            if not self.criteria:
                raise ValueError("Acceptance requires per-standard outcomes")
            statuses = {c["status"] for c in self.criteria}
            expected = ("needs_revision" if "not_satisfied" in statuses else
                        "undetermined" if "undetermined" in statuses else "satisfied")
            if self.result != expected:
                raise ValueError("Overall acceptance must agree with criterion outcomes")
        return self


def contract_identity():
    return {"version": "requirement-acceptance-v1",
            "sha256": digest(GraderResponse.model_json_schema())}
