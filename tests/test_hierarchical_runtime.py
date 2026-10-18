"""Actual DeepAgents execution with offline scripted models, not quality evidence."""
import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_export import export_snapshot
from report_agent.content_models import Ref
from report_agent.hierarchical_tools import content_tools
from test_deep_runtime import Driver, call, invoke, observation
from test_hierarchical_content import ws, seed, review_item, submission
from hierarchical_fixtures import delivery_evidence, unchecked_delivery


def select(snapshot, export):
    return invoke("select_content_delivery", operation_id="select:" + snapshot["id"], snapshot_ref=snapshot, export_ref=export)


def grade(snapshot, refs, verdict, checks=None):
    def action(messages):
        receipt = observation(messages, "read_context")["receipt_id"]
        item = review_item(snapshot, refs["k"], receipt, verdict)
        return AIMessage(content="", tool_calls=[call("HierarchicalResponse", {"explanation": "Offline protocol fixture.", "review": {**submission(snapshot, refs, item), "delivery_checks": checks if checks is not None else unchecked_delivery()}})])
    return action


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    def denied(*a, **k):
        pytest.fail("Network forbidden for synthetic protocol tests")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


async def test_native_final_pass_and_effective_permissions(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected for review.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    assert result["content_final_review"]["overall_verdict"] == "satisfied"
    names = {t["name"] for t in driver.bindings["rubric_grader"][0]}
    assert {"read_context", "read_feedback", "observe_evidence"} <= names
    assert not {"submit_result", "commit_objects", "select_content_delivery", "task", "write_file"} & names
    prompt = str(next(messages[0].content for role, _, messages in driver.calls if role == "coordinator"))
    assert "save_acceptance_criteria" not in prompt
    assert "own the requirement" not in prompt or "criteria" in prompt


async def test_unexecuted_null_does_not_trigger_author_repair(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    answer = AIMessage(content="", tool_calls=[call("HierarchicalResponse", {
        "explanation": "Reading was blocked; no semantic conclusion.",
        "review": {**submission(snapshot, refs, review_item(snapshot, refs["k"], verdict=None)), "delivery_checks": unchecked_delivery()}})])
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), AIMessage(content="Unexecuted review retained; no approval.")], rubric_grader=[answer])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["content_final_review"]["overall_verdict"] is None
    assert result["status"] == "needs_attention"
    assert len([r for r in cs.list_objects("ContentNode")]) == 2
    assert "needs_revision" not in json.dumps(result["content_final_review"])

    # A fresh invocation of the same snapshot must re-open investigation, while
    # checkpoint continuation is handled without starting a new run.
    new_driver = Driver(coordinator=[AIMessage(content="Retry investigation after source recovery.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
    # Native coordinator history persists; adapt fixture indexing only.
    from langchain_core.outputs import ChatGeneration, ChatResult
    old_respond = new_driver.respond
    async def respond(role, messages):
        if role == "coordinator":
            new_driver.calls.append((role, 0, list(messages)))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Retry investigation after source recovery."))])
        return await old_respond(role, messages)
    new_driver.respond = respond
    retried = await deep_runtime.run_report(ws, new_driver)
    assert retried["last_error"] is None, retried
    assert retried["content_final_review"]["overall_verdict"] == "satisfied", retried
    assert len(cs.list_objects("ReviewRecord")) == 2


async def test_feedback_revision_recheck_runs_through_native_graph(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    revised = {}
    def commit(messages):
        assert "not_satisfied" in str(messages)
        assert observation(messages, "read_feedback")["result"]["total"] == 1
        return invoke("commit_objects", operation_id="fix", objects=[
            {"client_key": "claim", "type": "ContentNode", "previous_ref": refs["claim"], "payload": {
                **cs.read(refs["claim"])["payload"], "body": {"text": "Under class B, permitted range is 75 to 100; final selection unresolved."}}},
            {"client_key": "edge", "type": "Relation", "previous_ref": refs["edge"], "payload": {
                **cs.read(refs["edge"])["payload"], "object_ref": {"client_key": "claim"}}},
            {"client_key": "support", "type": "Relation", "previous_ref": refs["support"], "payload": {
                **cs.read(refs["support"])["payload"], "subject_ref": {"client_key": "claim"}}}])
    def freeze(messages):
        changed = observation(messages, "commit_objects")["result"]["refs"]
        new_refs = [r for r in all_refs if r not in [refs[k] for k in changed]] + list(changed.values())
        revised["refs"] = {**refs, **changed}
        return invoke("freeze_snapshot", operation_id="fixed-snapshot", root_ref=refs["root"], refs=new_refs)
    def export_new(messages):
        revised["snapshot"] = observation(messages, "freeze_snapshot")["result"]["snapshot_ref"]
        return invoke("export_content_snapshot", operation_id="fixed-export", snapshot_ref=revised["snapshot"])
    def select_new(messages):
        revised["export"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
        return select(revised["snapshot"], revised["export"])
    def read_new(messages):
        return invoke("read_context", target_ref=revised["snapshot"])
    def grade_new(messages):
        return grade(revised["snapshot"], revised["refs"], "undetermined", delivery_evidence(cs, revised["snapshot"], revised["export"]))(messages)
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), invoke("read_feedback"),
        commit, freeze, export_new, select_new, AIMessage(content="Revision selected."), AIMessage(content="Conditional revision; unresolved final choice retained.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "not_satisfied"), read_new, grade_new])
    # Each native grader attempt has a fresh message context; Driver counts globally by
    # role only through our separate closure so attempts get their respective script.
    original = driver.respond
    attempts = {"n": 0}
    async def respond(role, messages):
        if role == "rubric_grader":
            step = attempts["n"]
            attempts["n"] += 1
            from langchain_core.outputs import ChatGeneration, ChatResult
            driver.calls.append((role, step, list(messages)))
            item = driver.scripts[role][step]
            return ChatResult(generations=[ChatGeneration(message=item(messages) if callable(item) else item)])
        return await original(role, messages)
    driver.respond = respond
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["content_final_review"]["overall_verdict"] == "undetermined", result
    reviews = cs.list_objects("ReviewRecord")
    assert len(reviews) == 2
    assert reviews[0]["payload"]["items"][0]["verdict"] == "not_satisfied"
    assert reviews[1]["payload"]["snapshot_ref"] == revised["snapshot"]
    assert cs.read(refs["claim"])["payload"]["body"]["text"] == "For adopted class B use 70."


async def test_local_review_returns_feedback_without_finishing_or_revising(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    def local_review(messages):
        receipt = observation(messages, "read_context")["receipt_id"]
        return invoke("submit_review", operation_id="local-defect", review=submission(snapshot, refs,
            review_item(snapshot, refs["k"], receipt)))
    driver = Driver(coordinator=[invoke("task", subagent_type="reviewer", description="Assess the saved content version and return findings."),
        invoke("select_content_delivery", operation_id="stop-with-known-defect", snapshot_ref=snapshot, export_ref=export, ending_reason="preserve_unresolved"),
        AIMessage(content="Preserve unresolved findings."), AIMessage(content="Known defect remains; no approval.")],
        reviewer=[invoke("read_context", target_ref=snapshot), local_review, AIMessage(content="Saved local finding.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["content_final_review"]["overall_verdict"] == "not_satisfied", result
    assert result["status"] == "changes_required"
    assert len(cs.list_objects("ContentNode")) == 2
    assert len(cs.list_objects("ReviewRecord")) == 2
