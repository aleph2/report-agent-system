"""Proposed S2 contract. Production actions and stores do not import these types."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Refs = Annotated[tuple[Id, ...], Field(min_length=1)]
JudgmentKind = Literal["evidence", "assumption", "conditional", "gap"]
Purpose = Literal["classification", "assumption", "adjustment", "context", "input"]


def is_canonical_id(value: object) -> bool:
    """SQLite predicate for IDs in trusted projection rows, which bypass Shape validation."""
    return isinstance(value, str) and bool(value) and value == value.strip()


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Citation(Shape):
    source_version: Id
    page: int = Field(ge=1)
    quote: Id


class Ground(Shape):
    assertion_id: Id
    purpose: Purpose
    proposition: Id
    transfer_convention: Id | None = None


class Source(Shape):
    kind: Literal["source"]
    predicate: Id
    state: Literal["value", "no_value", "unknown"]
    value: str | int | Decimal | bool | None = None
    unit: Id | None = None
    coverage: Id
    period: Id | None = None
    citation: Citation | None = None
    evidence_receipts: tuple[Id, ...] = ()

    @model_validator(mode="after")
    def check_observation(self):
        if (self.state == "value") != (self.value is not None):
            raise ValueError("Only a value observation carries a value")
        if self.state != "unknown" and self.citation is None:
            raise ValueError("C2: cite the source that explicitly establishes the observation")
        return self


class Conflict(Shape):
    kind: Literal["conflict"]
    observations: Annotated[tuple[Id, ...], Field(min_length=2)]
    precedence_convention: Id | None = None

    @model_validator(mode="after")
    def check_distinct_observations(self):
        if len(set(self.observations)) != len(self.observations):
            raise ValueError("A conflict requires distinct observations")
        return self


class Convention(Shape):
    kind: Literal["convention"]
    rule: Id
    scope: Id
    criterion_version: Id | None = None


class Warrant(Shape):
    criterion: Id
    criterion_version: Id
    rationale: Id


class ValueProposal(Shape):
    proposed: Decimal
    disposition: Literal["accepted_with_flag", "refused_midpoint_retained"]
    rationale: Id
    ground_ids: tuple[Id, ...] = ()


class Judgment(Shape):
    kind: Literal["judgment"]
    basis: JudgmentKind
    warrant: Warrant
    classification: Id | None = None
    value: Decimal | None = None
    alternatives: tuple[Id, ...] = ()
    defeaters: tuple[Id, ...] = ()
    question: Id | None = None
    adjustment: ValueProposal | None = None
    review_flags: tuple[Id, ...] = ()

    @model_validator(mode="after")
    def check_basis(self):
        if self.basis in {"conditional", "gap"}:
            if self.classification is not None or self.value is not None or not self.question:
                raise ValueError("Open outcomes must identify their question and remain unscored")
        elif self.classification is None:
            raise ValueError("A supported outcome must identify its classification")
        if self.basis in {"conditional", "assumption"} and len(set(self.alternatives)) < 2:
            raise ValueError("List the distinct plausible alternatives")
        if self.adjustment is not None:
            if self.value is None or not self.review_flags:
                raise ValueError("An adjustment requires an effective value and a visible review flag")
            accepted = self.adjustment.disposition == "accepted_with_flag"
            if accepted != (self.value == self.adjustment.proposed):
                raise ValueError("Adjustment disposition disagrees with the effective value")
        if self.basis == "assumption" and not self.defeaters:
            raise ValueError("C8: state which observations could overturn the assumption")
        return self


class Derived(Shape):
    kind: Literal["derived"]
    rule_version: Id
    inputs: Refs
    strength: Literal["undetermined", "provisional", "determined"]
    value: Decimal | None = None


class Recommendation(Shape):
    kind: Literal["recommendation"]
    statement: Id
    basis: Refs


class Finding(Shape):
    kind: Literal["finding"]
    target: Id
    snapshot: Id
    conclusion: Id


class PresentationCheck(Shape):
    kind: Literal["presentation_check"]
    snapshot: Id
    artifact_digest: Digest
    check: Id
    outcome: Literal["passed", "failed"]


class Question(Shape):
    kind: Literal["question"]
    text: Id
    affects: Literal["classification", "value", "presentation", "other"]


class Pair(Shape):
    snapshot: Id
    records: Refs
    word_sha256: Digest
    excel_sha256: Digest

    @model_validator(mode="after")
    def check_unique(self):
        if len(set(self.records)) != len(self.records):
            raise ValueError("The snapshot must identify each record once")
        return self


class Decision(Shape):
    kind: Literal["decision"]
    effect: Literal["answer", "dismiss_challenge", "deliver_draft", "release"]
    reason: Id
    target: Id
    pair: Pair | None = None
    disclosed_gaps: tuple[Id, ...] = ()

    @model_validator(mode="after")
    def check_delivery(self):
        if (self.effect in {"deliver_draft", "release"}) != (self.pair is not None):
            raise ValueError("Delivery decisions bind the file pair and exact records")
        return self


class Act(Shape):
    kind: Literal["act"]
    effect: Literal["endorse", "challenge", "confirm", "supersede", "retract", "sign_off"]
    target: Id
    reason: Id
    successor: Id | None = None

    @model_validator(mode="after")
    def check_successor(self):
        if (self.effect == "supersede") != (self.successor is not None):
            raise ValueError("Supersession must name its replacement")
        return self


Claims = Annotated[
    Source | Conflict | Convention | Judgment | Derived | Recommendation | Finding
    | PresentationCheck | Question | Decision | Act, Field(discriminator="kind")
]


class Assertion(Shape):
    id: Id
    subject: Id
    claim: Claims
    grounds: tuple[Ground, ...]
    was_attributed_to: Id
    was_generated_by: Id
    operation_id: Id
    observed_at: AwareDatetime
    recorded_at: AwareDatetime
    schema_version: Literal["s2-proposal-1"]
    check_version: Literal["s2-proposal-2"]
