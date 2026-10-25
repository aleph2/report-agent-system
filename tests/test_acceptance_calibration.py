"""Offline isolation and prompt-boundary checks, not evidence of grader quality."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from report_agent.review import load_rules, native_review, reviewer_prompt, review_delivery
from report_agent.review_context import bind_context_experiment, configure_context_experiment
from report_agent.store import Store, digest
from test_deep_runtime import Driver
from test_review_context import workspace


CONTROL = {"input_mode": "artifact", "grounded_verdict": True}
CANDIDATE = {**CONTROL, "calibrated_acceptance": True}


def fresh_import(store):
    store.set("review_import017", {"next": ["FeedbackRubric.after_agent"], "attempt_id": "offline"})
    store.set("checkpoint_resume", True)


@pytest.mark.parametrize("invalid", [
    {**CONTROL, "calibrated_acceptance": "true"},
    {**CONTROL, "calibrated_acceptance": 1},
    {**CONTROL, "unknown": True},
    {**CANDIDATE, "input_mode": "transcript"},
    {**CANDIDATE, "grounded_verdict": False},
])
def test_invalid_candidate_configuration_does_not_mutate_fresh_fork(workspace, invalid):
    fresh_import(workspace.store)
    with pytest.raises(ValueError, match="INVALID_REVIEW_CONTEXT_EXPERIMENT"):
        configure_context_experiment(workspace.store, invalid)
    assert workspace.store.get("review_context_experiment") is None
    assert workspace.store.get("review_context_binding") is None


@pytest.mark.parametrize("replacement", [CONTROL, {**CONTROL, "calibrated_acceptance": False}, None])
def test_candidate_binding_survives_reopen_and_cannot_be_removed(workspace, replacement):
    store = workspace.store
    fresh_import(store)
    configure_context_experiment(store, CANDIDATE)
    reopened = Store(store.root)
    bind_context_experiment(reopened)
    binding = reopened.get("review_context_binding")
    reopened.set("review_context_experiment", replacement)
    with pytest.raises(RuntimeError, match="SWITCH_REQUIRES_FRESH_FORK"):
        bind_context_experiment(reopened)
    assert reopened.get("review_context_binding") == binding


def test_candidate_changes_native_prompt_and_identity_without_changing_tools_or_old_approval(workspace):
    from report_agent.review_context import ACCEPTANCE_INSTRUCTION

    base = reviewer_prompt(CONTROL)
    assert reviewer_prompt({**CONTROL, "calibrated_acceptance": False}) == base
    assert reviewer_prompt(CANDIDATE) == base + "\n\n# Acceptance boundaries\n\n" + ACCEPTANCE_INSTRUCTION
    prompts, catalogs, targets = {}, {}, {}
    for name, config in (("control", CONTROL), ("candidate", CANDIDATE)):
        workspace.store.set("review_context_experiment", config)
        review = native_review(workspace, Driver(rubric_grader=[AIMessage("Unused")])("rubric_grader"), [], load_rules())
        review._grader_input({"messages": [HumanMessage("Current commission"), AIMessage("AUTHOR_ASSERTION")],
                              "rubric": load_rules(), "_current_grading_run_id": name}, 0)
        prompts[name] = review._system_prompt
        catalogs[name] = [(t.name, t.description, t.args) for t in review._tools]
        targets[name] = workspace.store.get("rubric_targets")[name + ":0"]
        assert prompts[name] == reviewer_prompt(config)
        assert targets[name]["reviewer_prompt_hash"] == digest(prompts[name])
        assert targets[name]["review_context_experiment"] == config
    assert catalogs["control"] == catalogs["candidate"]
    for field in ("draft_id", "draft_body_sha256", "rubric_hash", "export_configuration_hash"):
        assert targets["control"][field] == targets["candidate"][field]

    store = workspace.store
    store.set("active_rubric_hash", digest(load_rules()))
    store.set("review_context_experiment", CONTROL)
    store.set("active_reviewer_prompt_hash", digest(prompts["control"]))
    store.set("rubric_reviews", [{"result": "satisfied", "unverified": False, "target": targets["control"]}])
    draft_id = targets["control"]["draft_id"]
    assert review_delivery(workspace, draft_id)["status"] == "reviewed_draft"
    store.set("review_context_experiment", CANDIDATE)
    store.set("active_reviewer_prompt_hash", digest(prompts["candidate"]))
    assert review_delivery(workspace, draft_id)["status"] == "unreviewed_draft"
