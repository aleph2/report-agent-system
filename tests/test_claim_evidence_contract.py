"""Native contract/feedback/recovery mechanics; no professional quality claims."""
import copy
import json

import pytest
from deepagents.middleware.rubric import GraderResponse as NativeResponse, RubricMiddleware
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from report_agent import review_contract
from report_agent.review_contract import GraderResponse, contract_identity
from report_agent.review import FeedbackRubric, native_review, load_rules, reviewer_prompt, reconcile_review, review_delivery
from report_agent.review_context import configure_context_experiment, bind_context_experiment
from report_agent.store import Store, digest
from test_native_rubric013 import ScriptedModel
from test_review_context import workspace
from test_acceptance_calibration import fresh_import


CONTROL = {"input_mode": "artifact", "grounded_verdict": True,
           "calibrated_acceptance": True, "compact_table_observations": True}
CANDIDATE = {**CONTROL, "claim_evidence_contract": True}


def ground(blocks=False):
    return {"report_claim": "The report includes the source count", "report_locator": "paragraph1",
            "evidence": [{"locator": "source s paragraph1", "observation": "Eight gates"}],
            "relationship": "contradicted" if blocks else "supported",
            "commission_impact": "Count fidelity is within this commission",
            "needed_outcome": "Use the source count" if blocks else "No change needed",
            "blocks_criterion": blocks}


def payload(passed):
    item = {"name": "Source count is accurately reported", "passed": passed, "grounds": [ground(not passed)]}
    if not passed:
        item["gap"] = "Correct the quoted count within the commission."
    return {"result": "satisfied" if passed else "needs_revision", "explanation": "Located public grounds.",
            "criteria": [item]}


def response(passed):
    return AIMessage("", tool_calls=[{"name": "GraderResponse", "id": str(passed),
                                      "type": "tool_call", "args": payload(passed)}])


def test_native_consistency_and_new_required_grounds():
    accepted = GraderResponse.model_validate(payload(True))
    assert isinstance(accepted, NativeResponse)
    assert accepted.criteria[0]["grounds"] == [ground()]
    mutations = []
    no_grounds = payload(True); no_grounds["criteria"][0].pop("grounds"); mutations.append(no_grounds)
    no_gap = payload(False); no_gap["criteria"][0].pop("gap"); mutations.append(no_gap)
    blocked = payload(True); blocked["criteria"][0]["grounds"][0]["blocks_criterion"] = True; mutations.append(blocked)
    inconsistent = payload(False); inconsistent["result"] = "satisfied"; mutations.append(inconsistent)
    for invalid in mutations:
        with pytest.raises(ValidationError):
            GraderResponse.model_validate(invalid)


@pytest.mark.parametrize("relationship", ["contradicted", "unresolved", "not_checked"])
def test_code_does_not_infer_materiality_or_invent_evidence(relationship):
    value = payload(True)
    value["criteria"][0]["grounds"][0].update(relationship=relationship, evidence=[],
        report_locator="Absent: this draft does not assert that claim", needed_outcome="No change in this scope")
    assert GraderResponse.model_validate(value).criteria[0]["passed"] is True


async def test_registered_schema_native_revision_and_persistence(workspace):
    writer = ScriptedModel(replies=[AIMessage("Nine gates"), AIMessage("Eight gates [s]")])
    grader = ScriptedModel(replies=[response(False), response(True)])
    review = FeedbackRubric(model=grader, claim_evidence_contract=True, max_iterations=3)
    graph = create_agent(model=writer, middleware=[review], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "contract-test"}}
    await graph.ainvoke({"messages": [HumanMessage("Report the source count")],
                        "rubric": "The source count is accurately reported."}, config)
    state = (await graph.aget_state(config)).values
    evaluations = state["_rubric_evaluations"]
    assert [v["result"] for v in evaluations] == ["needs_revision", "satisfied"]
    assert evaluations[0]["criteria"][0]["grounds"] == [ground(True)]
    assert evaluations[1]["criteria"][0]["grounds"] == [ground(False)]
    wire_tools = [convert_to_openai_tool(t) for t in grader.bindings[0]]
    actual_schema = next(t for t in wire_tools if t.get("function", {}).get("name") == "GraderResponse")
    assert "blocks_criterion" in json.dumps(actual_schema)
    feedback = next(m for m in writer.seen[1] if m.additional_kwargs.get("lc_source") == "rubric_grader")
    assert "source s paragraph1" in feedback.content and "not authoritative" in feedback.content
    assert len(writer.seen) == len(grader.seen) == 2
    reconcile_review(workspace, state)
    reopened = Store(workspace.store.root)
    assert reopened.get("rubric_reviews")[0]["criteria"][0]["grounds"] == [ground(True)]
    assert review._ensure_grader() is review._ensure_grader()


def test_feedback_preserves_native_warning_and_default_output():
    evaluation = {**payload(False), "unverified": True}
    base = RubricMiddleware._revision_prompt(evaluation)
    extended = FeedbackRubric._revision_prompt(evaluation)
    assert extended.startswith(base) and "source s paragraph1" in extended
    evaluation["criteria"][0].pop("grounds")
    assert FeedbackRubric._revision_prompt(evaluation) == RubricMiddleware._revision_prompt(evaluation)


async def test_terminal_handoff_keeps_grounds_without_restarting_grading():
    writer = ScriptedModel(replies=[AIMessage("Nine gates"), AIMessage("Draft retained; no approval")])
    grader = ScriptedModel(replies=[response(False)])
    review = FeedbackRubric(model=grader, claim_evidence_contract=True, max_iterations=1)
    graph = create_agent(model=writer, middleware=[review], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "terminal-contract"}}
    await graph.ainvoke({"messages": [HumanMessage("Report the source count")],
                        "rubric": "The source count is accurately reported."}, config)
    notice = next(m for m in writer.seen[1] if m.name == "rubric_terminal_feedback")
    assert json.loads(notice.content)["criteria"][0]["grounds"] == [ground(True)]
    assert "not authoritative" in json.loads(notice.content)["grounds_status"]
    assert len(grader.seen) == 1 and len(writer.seen) == 2
    assert (await graph.aget_state(config)).values["_rubric_status"] == "max_iterations_reached"


@pytest.mark.parametrize("invalid", [{**CONTROL, "claim_evidence_contract": 1},
                                     {**CANDIDATE, "compact_table_observations": False}])
def test_invalid_experiment_does_not_mutate(workspace, invalid):
    fresh_import(workspace.store)
    with pytest.raises(ValueError, match="INVALID_REVIEW_CONTEXT_EXPERIMENT"):
        configure_context_experiment(workspace.store, invalid)
    assert workspace.store.get("review_context_experiment") is None


def test_contract_bound_before_recovery_and_cannot_change(workspace, monkeypatch):
    fresh_import(workspace.store)
    configure_context_experiment(workspace.store, CANDIDATE)
    reopened = Store(workspace.store.root)
    bind_context_experiment(reopened)
    bound = reopened.get("review_context_binding")
    assert bound["response_contract"] == contract_identity(CANDIDATE)
    monkeypatch.setattr(review_contract, "CONTRACT_VERSION", "future-change")
    with pytest.raises(RuntimeError, match="REVIEW_CONTRACT_SWITCH_REQUIRES_FRESH_FORK"):
        bind_context_experiment(reopened)
    with pytest.raises(RuntimeError, match="REVIEW_CONTRACT_SWITCH_REQUIRES_FRESH_FORK"):
        configure_context_experiment(reopened, CANDIDATE)
    assert reopened.get("review_context_binding") == bound


async def test_contract_change_rejected_before_old_approval_early_return(tmp_path, monkeypatch):
    from report_agent import deep_runtime
    from test_task_supervision import ws as native_fixture
    workspace = native_fixture.__wrapped__(tmp_path)
    # Dated configuration-binding fixture only; not an executable old fork or checkpoint.
    fresh_import(workspace.store)
    configure_context_experiment(workspace.store, CANDIDATE)
    workspace.store.set("checkpoint_resume", False)
    monkeypatch.setattr(deep_runtime, "project_state", lambda ws: {"status": "reviewed_draft"})
    monkeypatch.setattr(review_contract, "CONTRACT_VERSION", "future-change")
    with pytest.raises(RuntimeError, match="REVIEW_CONTRACT_SWITCH_REQUIRES_FRESH_FORK"):
        await deep_runtime.run_report(workspace, lambda role: pytest.fail("No model should be constructed"))


def test_same_prompt_different_contract_cannot_reuse_approval(workspace):
    targets = {}
    for name, config in (("control", CONTROL), ("candidate", CANDIDATE)):
        workspace.store.set("review_context_experiment", config)
        review = native_review(workspace, ScriptedModel(replies=[]), [], load_rules())
        review._grader_input({"messages": [HumanMessage("Current commission")],
                              "rubric": load_rules(), "_current_grading_run_id": name}, 0)
        targets[name] = workspace.store.get("rubric_targets")[name + ":0"]
    assert reviewer_prompt(CONTROL) == reviewer_prompt(CANDIDATE)
    assert "review_response_contract" not in targets["control"]
    assert targets["candidate"]["review_response_contract"] == contract_identity(CANDIDATE)
    store = workspace.store
    store.set("active_rubric_hash", digest(load_rules()))
    store.set("active_reviewer_prompt_hash", digest(reviewer_prompt(CONTROL)))
    store.set("review_context_experiment", CONTROL)
    store.set("rubric_reviews", [{"result": "satisfied", "unverified": False, "target": targets["control"]}])
    draft_id = targets["control"]["draft_id"]
    assert review_delivery(workspace, draft_id)["status"] == "reviewed_draft"
    store.set("review_context_experiment", CANDIDATE)
    assert review_delivery(workspace, draft_id)["status"] == "unreviewed_draft"
    old_target = copy.deepcopy(targets["candidate"])
    old_target["review_response_contract"]["sha256"] = "old-contract"
    store.set("rubric_reviews", [{"result": "satisfied", "unverified": False, "target": old_target}])
    assert review_delivery(workspace, draft_id)["status"] == "unreviewed_draft"
