"""Opt-in, project-bound context for isolated native-review comparisons."""
from __future__ import annotations

from typing import Literal
from hashlib import sha256

from .errors import ActionRejected
from .store import digest, encode


GROUNDING_INSTRUCTION = """Support acceptance as well as requested revision with concise, locatable grounds
in your explanation and any failing criterion's gap. Make the scope of your verdict
and any material limitation clear. A citation or completed activity alone does not
establish that a consequential claim is supported. Choose your own investigation;
neither acceptance nor finding defects is a goal in itself.
"""
ACCEPTANCE_INSTRUCTION = """Assess materiality against the commissioned use and explain the impact.
Suitability for circulation as a staged draft does not by itself establish that
each rubric criterion is satisfied. Pending sign-off or methodological confirmation
cannot justify a known incorrect assertion or reconcile a contradiction. Where a
material defect prevents a criterion from being met, request correction or an
accurate limitation of the affected claim in the artifact itself. Disclosed
uncertainty and minor imperfections may remain when compatible with the commission
and the claims made.
"""
CONTEXT_VERSION = "review-context-v1"


def _validate_config(value):
    required = {"input_mode", "grounded_verdict"}
    if (not isinstance(value, dict)
            or not required <= set(value) <= required | {"calibrated_acceptance", "compact_table_observations", "claim_evidence_contract"}
            or value["input_mode"] not in {"transcript", "artifact"}
            or type(value["grounded_verdict"]) is not bool
            or ("calibrated_acceptance" in value and type(value["calibrated_acceptance"]) is not bool)
            or ("compact_table_observations" in value and type(value["compact_table_observations"]) is not bool)
            or ("claim_evidence_contract" in value and type(value["claim_evidence_contract"]) is not bool)
            or (value.get("claim_evidence_contract") and not value.get("compact_table_observations"))
            or (value.get("compact_table_observations") and not value.get("calibrated_acceptance"))
            or (value.get("calibrated_acceptance") and
                (value["input_mode"] != "artifact" or not value["grounded_verdict"]))):
        raise ValueError("INVALID_REVIEW_CONTEXT_EXPERIMENT")


def experiment_config(store):
    value = store.get("review_context_experiment")
    if value is None:
        return None
    _validate_config(value)
    return value


def bind_context_experiment(store):
    """A fresh fork may opt in; recovery cannot switch or remove its binding."""
    selected = experiment_config(store)
    from .review_contract import contract_identity
    contract = contract_identity(selected)
    bound = store.get("review_context_binding")
    if bound:
        if selected != bound["configuration"] or bound.get("version") != CONTEXT_VERSION:
            raise RuntimeError("REVIEW_CONTEXT_SWITCH_REQUIRES_FRESH_FORK")
        if bound.get("response_contract") != contract:
            raise RuntimeError("REVIEW_CONTRACT_SWITCH_REQUIRES_FRESH_FORK")
        return
    if selected is None:
        return
    receipt = store.get("review_import017") or {}
    if (receipt.get("next") != ["FeedbackRubric.after_agent"]
            or not store.get("checkpoint_resume") or store.get("rubric_targets")
            or store.get("rubric_reviews")):
        raise RuntimeError("REVIEW_CONTEXT_REQUIRES_FRESH_FORK")
    binding = {"configuration": selected,
              "version": CONTEXT_VERSION, "import_attempt_id": receipt["attempt_id"],
              "scope": "isolated_review_fork"}
    if contract:
        binding["response_contract"] = contract
    store.set("review_context_binding", binding)


def configure_context_experiment(store, selected):
    """Validate the trial before writing configuration onto an existing workspace."""
    with store.run_lock():
        _configure_context_experiment_locked(store, selected)


def _configure_context_experiment_locked(store, selected):
    _validate_config(selected)
    existing = experiment_config(store)
    if existing is not None and existing != selected:
        raise RuntimeError("REVIEW_CONTEXT_SWITCH_REQUIRES_FRESH_FORK")
    bound = store.get("review_context_binding")
    if bound:
        if bound["configuration"] != selected or bound.get("version") != CONTEXT_VERSION:
            raise RuntimeError("REVIEW_CONTEXT_SWITCH_REQUIRES_FRESH_FORK")
        from .review_contract import contract_identity
        if bound.get("response_contract") != contract_identity(selected):
            raise RuntimeError("REVIEW_CONTRACT_SWITCH_REQUIRES_FRESH_FORK")
    else:
        receipt = store.get("review_import017") or {}
        if (receipt.get("next") != ["FeedbackRubric.after_agent"]
                or not store.get("checkpoint_resume") or store.get("rubric_targets")
                or store.get("rubric_reviews")):
            raise RuntimeError("REVIEW_CONTEXT_REQUIRES_FRESH_FORK")
    store.set("review_context_experiment", selected)
    bind_context_experiment(store)
