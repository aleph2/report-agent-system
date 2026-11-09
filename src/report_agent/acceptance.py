"""Requirement-derived acceptance versions; storage facts are not semantic approval."""
from __future__ import annotations
from . import issue_state
from . import legacy_state as legacy

import hashlib
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


MODE = "requirement-derived-v1"
LEGACY = "legacy"


class AcceptanceCriterionInput(BaseModel):
    """An observable outcome and its located requirement basis, not a tool sequence."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = ""
    requirement_refs: list[str] = Field(min_length=1)
    condition: str = Field(min_length=1, description=(
        "Required outcome within the commission, with a clear boundary between "
        "meeting it, a material violation, and an unresolved determination. "
        "Describe results, not investigation steps or known-case answers."))
    scope: str = Field(default="", description=(
        "Claims and commissioned coverage to which this criterion applies."))
    evidence_expectation: str = Field(default="", description=(
        "What evidence would establish the outcome at this scope, including how "
        "material contrary or missing evidence affects the conclusion. A citation "
        "or activity alone is not proof. Do not prescribe a tool sequence."))
    allowed_limitations: str = Field(default="", description=(
        "Which disclosed limitations remain compatible with this outcome and why; "
        "distinguish these from unsupported definite claims or known errors. "
        "Pending confirmation is not a general exemption from the condition."))

    @field_validator("requirement_refs")
    @classmethod
    def located_references(cls, refs):
        if any(not ref.strip() for ref in refs):
            raise ValueError("Requirement references must be nonempty located descriptions")
        return [ref.strip() for ref in refs]


def enabled(workspace):
    return workspace.store.get("acceptance_mode") == MODE


def _has_checkpoint_history(path):
    """Inspection may create an empty database; only persisted state is history."""
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('checkpoints', 'writes')")}
            return any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
                       for table in ("checkpoints", "writes") if table in tables)
    except sqlite3.Error as exc:
        raise ActionRejected("ACCEPTANCE_CHECKPOINT_HISTORY_UNREADABLE") from exc


def bind_mode(workspace):
    """Persist the policy before starting a new runtime; preserve historical runs."""
    bound = workspace.store.get("acceptance_mode")
    if bound is not None:
        if bound not in {MODE, LEGACY}:
            raise ActionRejected("INVALID_ACCEPTANCE_MODE")
        return bound
    store = workspace.store
    default = store.get("acceptance_default", LEGACY)
    if default not in {MODE, LEGACY}:
        raise ActionRejected("INVALID_ACCEPTANCE_DEFAULT")
    historical = (default == LEGACY or store.get("runtime") is not None
                  or store.get("checkpoint_resume", False)
                  or store.get("review_context_experiment") is not None
                  or any(r["kind"] in {"draft", "review"} for r in workspace.results())
                  or _has_checkpoint_history(store.root / "checkpoints.db"))
    mode = LEGACY if historical else default
    store.set("acceptance_mode", mode)
    return mode


def requirement_basis(workspace):
    """Only actual requirement inputs invalidate this basis, not agent-raised issues."""
    store = workspace.store
    return {
        "goal": store.manifest["goal"],
        "scope_instruction": store.manifest.get("scope_instruction"),
        "document_uses": store.manifest.get("document_uses", {}),
        "operator_feedback": [entry for entry in store.get("feedback", [])
                              if entry.get("origin") == "operator"],
        "operator_decisions": [
            {key: entry.get(key) for key in
             ("id", "category", "description", "source_ids", "decision", "resolved")}
            for entry in issue_state.get_report_issues(store, [])
            if entry.get("decision_origin") == "operator"
        ],
    }


def _payload(record):
    if record.get("kind") != "acceptance":
        raise ActionRejected("ACCEPTANCE_RESULT_REQUIRED")
    try:
        data = json.loads(record["body"])
        if (data["version"] != MODE or not data["criteria"]
                or data["basis_hash"] != digest(data["requirement_basis"])):
            raise ValueError("Invalid acceptance payload")
        criteria = [AcceptanceCriterionInput.model_validate(row).model_dump()
                    for row in data["criteria"]]
        if any(not row["id"] for row in criteria) or len({r["id"] for r in criteria}) != len(criteria):
            raise ValueError("Invalid criterion identity")
        return {**data, "criteria": criteria}
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ActionRejected("INVALID_ACCEPTANCE_RESULT") from exc


def criteria_identity(record):
    data = _payload(record)
    return {"criteria_id": record["id"],
            "body_hash": hashlib.sha256(record["body"].encode()).hexdigest(),
            "basis_hash": data["basis_hash"]}


def active_criteria(workspace):
    """Return the latest unreplaced version even when changed inputs make it stale."""
    records = [r for r in workspace.results() if r["kind"] == "acceptance"]
    replaced = {r["replaces_id"] for r in records if r.get("replaces_id")}
    latest = next((r for r in reversed(records) if r["id"] not in replaced), None)
    if latest is None:
        return None
    data = _payload(latest)
    basis_current = data["basis_hash"] == digest(requirement_basis(workspace))
    stale = latest["id"] in workspace.impact()["affected_result_ids"]
    return {**latest, "criteria": data["criteria"], "basis_hash": data["basis_hash"],
            "basis_current": basis_current, "stale": stale,
            "current": basis_current and not stale}


def required_criteria(workspace, criteria_id=""):
    if not enabled(workspace):
        raise ActionRejected("REQUIREMENT_DERIVED_ACCEPTANCE_NOT_ENABLED")
    current = active_criteria(workspace)
    if current is None:
        raise ActionRejected("ACCEPTANCE_CRITERIA_REQUIRED_BEFORE_DRAFT")
    if criteria_id and criteria_id != current["id"]:
        raise ActionRejected("ACCEPTANCE_CRITERIA_VERSION_MISMATCH")
    if not current["basis_current"]:
        raise ActionRejected("ACCEPTANCE_REQUIREMENT_BASIS_CHANGED")
    if current["stale"]:
        raise ActionRejected("ACCEPTANCE_CRITERIA_INPUTS_CHANGED")
    return current


def draft_criteria(workspace, draft):
    # Workspace also passes the pending draft's declared inputs before committing.
    if draft.get("kind", "draft") != "draft":
        raise ActionRejected("DRAFT_REQUIRED")
    adopted = [workspace.result(ref) for ref in draft.get("input_ids", [])]
    criteria = [r for r in adopted if r["kind"] == "acceptance"]
    if len(criteria) != 1:
        raise ActionRejected("DRAFT_REQUIRES_ONE_EXPLICIT_ACCEPTANCE_VERSION")
    return required_criteria(workspace, criteria[0]["id"])


def criteria_rules(record):
    """Dynamic native-rubric text; outcome coverage does not prescribe investigation."""
    data = _payload(record)
    return ("Assess the exact saved report against every acceptance criterion below. "
            "Use each criterion's id verbatim as its criterion name; do not add, merge, "
            "rename or omit criteria. These are requirement-derived acceptance outcomes, "
            "not a prescribed verification sequence. Choose and adapt your strategy and "
            "tools from actual observations. Record the supporting evidence and limits "
            "for each outcome. A usable limited draft is distinct from all criteria being "
            "satisfied. Report uncertainty without inventing a defect or an answer.\n\n"
            + encode({"acceptance_identity": criteria_identity(record),
                      "criteria": data["criteria"]}))


def _ids(values):
    if not isinstance(values, (list, tuple)) or any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in values):
        raise ActionRejected("ACCEPTANCE_REFERENCES_REQUIRE_NONEMPTY_IDS")
    return sorted(set(values))


def save_criteria(workspace, *, actor, title, criteria, source_ids, input_ids,
                  reason, replaces_id=""):
    """Coordinator-only immutable commit; exact replay recovers before new IDs."""
    if actor != "coordinator":
        raise ActionForbidden("ACCEPTANCE_OWNER_MISMATCH")
    if not isinstance(title, str) or not title.strip():
        raise ActionRejected("ACCEPTANCE_TITLE_REQUIRED")
    if not isinstance(reason, str) or (replaces_id and not reason.strip()):
        raise ActionRejected("ACCEPTANCE_REVISION_REASON_REQUIRED")
    if not isinstance(criteria, list) or not criteria:
        raise ActionRejected("ACCEPTANCE_CRITERIA_REQUIRED")
    try:
        entries = [AcceptanceCriterionInput.model_validate(row).model_dump() for row in criteria]
    except ValidationError as exc:
        raise ActionRejected("INVALID_ACCEPTANCE_CRITERION: " + str(exc)) from exc
    sources, inputs = _ids(source_ids), _ids(input_ids)
    request = {"kind": "acceptance", "actor": actor, "title": title, "criteria": entries,
               "source_ids": sources, "input_ids": inputs, "reason": reason,
               "replaces_id": replaces_id}
    submission_id = digest(request)
    receipt = workspace.submission_receipt(submission_id)
    if receipt is not None:
        return receipt
    if bind_mode(workspace) != MODE:
        raise ActionRejected("HISTORICAL_PROJECT_CANNOT_ADD_PREPRODUCTION_CRITERIA")
    current = active_criteria(workspace)
    if current and replaces_id != current["id"]:
        raise ActionRejected("ACCEPTANCE_REVISION_REQUIRES_ACTIVE_VERSION")
    if not current and replaces_id:
        raise ActionRejected("ACCEPTANCE_REVISION_REQUIRES_ACTIVE_VERSION")
    if current is None and any(r["kind"] == "draft" for r in workspace.results()):
        raise ActionRejected("ACCEPTANCE_CRITERIA_MUST_PRECEDE_FIRST_DRAFT")
    workspace.store.sources(sources)
    for result_id in inputs:
        if workspace.result(result_id)["kind"] in {"draft", "review", "acceptance"}:
            raise ActionRejected("ACCEPTANCE_REQUIRES_UPSTREAM_REQUIREMENT_INPUTS")
    old_ids = {r["id"] for r in current["criteria"]} if current else set()
    explicit = [r["id"] for r in entries if r["id"]]
    if len(set(explicit)) != len(explicit):
        raise ActionRejected("DUPLICATE_ACCEPTANCE_CRITERION_ID")
    if set(explicit) - old_ids:
        raise ActionRejected("ACCEPTANCE_CRITERION_ID_NOT_IN_PREDECESSOR")
    entries = [{**entry, "id": entry["id"] or "criterion_" + uuid4().hex} for entry in entries]
    basis = requirement_basis(workspace)
    body = encode({"version": MODE, "requirement_basis": basis, "basis_hash": digest(basis),
                   "criteria": entries, "reason": reason})
    if replaces_id:
        task = workspace.request_revision(replaces_id, reason + ": " + submission_id)
    else:
        task = workspace.request_task("acceptance", title + ": " + submission_id, inputs)
    return workspace.submit(task["id"], actor=actor, title=title, body=body,
                            source_ids=sources, input_ids=inputs, submission_id=submission_id)
