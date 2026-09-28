"""Context completeness/privacy and native integration; no model quality claims."""
import json
from hashlib import sha256

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from report_agent.review import native_review, load_rules, reviewer_prompt
from report_agent.review_context import (ReviewContext, bind_context_experiment,
                                       public_history, CONTEXT_VERSION)
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from test_deep_runtime import Driver


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile a source-grounded limited draft.", "sources": [
        {"id": "s", "title": "Source", "content": "There are 8 gates.", "coverage": "complete"}]})
    ws = Workspace(store)
    ws.initialize()
    task = ws.request_task("draft", "Compile", [])
    draft = ws.submit(task["id"], actor="writer", title="Report", body="8 gates [s].",
                      source_ids=["s"], input_ids=[])
    ws.select_delivery(draft["id"], "")
    store.set("knowledge_enabled", False)
    return ws


def test_public_history_excludes_private_fields_and_preserves_provenance():
    messages = [AIMessage(content=["Plain list text", {"type": "text", "text": "Public statement."},
                                  {"type": "reasoning", "reasoning": "opaque-block"}],
                          additional_kwargs={"reasoning_content": "opaque-provider"},
                          response_metadata={"secret": "opaque-metadata"}),
                HumanMessage("Framework feedback", additional_kwargs={"lc_source": "rubric_grader"}),
                HumanMessage("User message")]
    rows = public_history(messages)
    encoded = json.dumps(rows)
    assert "opaque" not in encoded
    assert rows[0]["text"] == "Plain list text\nPublic statement."
    assert rows[0]["non_text_content_omitted"]
    assert rows[1]["message_source"] == "rubric_grader"
    assert rows[2]["message_source"] == "conversation_observation"


def test_long_assignment_and_late_decision_are_completely_pageable(workspace):
    workspace.store.set("report_issues", [{"resolved": True, "decision_origin": "operator", "decision": "x" * 17000 + "TAIL_DECISION"}])
    messages = [HumanMessage("Original request"), *[AIMessage("Long author text" * 1000) for _ in range(35)],
                HumanMessage("LAST_REAL_FEEDBACK"),
                HumanMessage("PRIOR_NATIVE_GAP", additional_kwargs={"lc_source": "rubric_grader"})]
    context = ReviewContext(workspace)
    target = {"draft_id": "selected"}
    packet = context.capture(messages, target)
    assert len(json.dumps(packet, ensure_ascii=False)) <= 4000
    assert packet["assignment"]["inline"] is False
    assert target["review_context_version"] == CONTEXT_VERSION
    assert "PRIOR_NATIVE_GAP" in context.sections["assignment"]
    for section, marker in (("assignment", "TAIL_DECISION"), ("history", "LAST_REAL_FEEDBACK")):
        pages, offset = [], 0
        while offset is not None:
            value = context.read(section, offset, 8000)
            pages.append(value["content"])
            offset = value["next_offset"]
        assert "".join(pages) == context.sections[section]
        assert marker in "".join(pages)
    before = context.read("assignment")
    workspace.store.set("report_issues", [])
    assert context.read("assignment") == before  # A running attempt has a frozen view.
    with pytest.raises(Exception, match="SECTION_UNAVAILABLE"):
        context.read("../../other-project")
    with pytest.raises(Exception, match="INVALID_RANGE"):
        context.read("history", -1)


def test_binding_requires_fresh_fork_and_cannot_switch_or_remove(workspace):
    from report_agent.review_context import configure_context_experiment
    store = workspace.store
    selected = {"input_mode": "artifact", "grounded_verdict": False}
    with store.run_lock():
        with pytest.raises(RuntimeError, match="PROJECT_ALREADY_RUNNING"):
            configure_context_experiment(store, selected)
    assert store.get("review_context_experiment") is None
    assert store.get("review_context_binding") is None
    with pytest.raises(RuntimeError, match="REQUIRES_FRESH_FORK"):
        configure_context_experiment(store, selected)
    assert store.get("review_context_experiment") is None
    store.set("review_context_experiment", selected)
    with pytest.raises(RuntimeError, match="REQUIRES_FRESH_FORK"):
        bind_context_experiment(store)
    store.set("review_import017", {"next": ["FeedbackRubric.after_agent"], "attempt_id": "synthetic-test"})
    store.set("checkpoint_resume", True)
    bind_context_experiment(store)
    store.set("rubric_reviews", [{"result": "satisfied"}])
    bind_context_experiment(store)
    for replacement in ({**selected, "grounded_verdict": True}, None):
        store.set("review_context_experiment", replacement)
        with pytest.raises(RuntimeError, match="SWITCH_REQUIRES_FRESH_FORK"):
            bind_context_experiment(store)


def test_both_arms_have_same_tools_and_artifact_has_no_default_author_claim(workspace):
    messages = [HumanMessage("Original assignment"), AIMessage("AUTHOR_COMPLETION_CLAIM")]
    driver = Driver(rubric_grader=[AIMessage("Unused")])
    outputs, tool_names, prompts = {}, {}, {}
    for mode in ("transcript", "artifact"):
        workspace.store.set("review_context_experiment", {"input_mode": mode, "grounded_verdict": False})
        review = native_review(workspace, driver("rubric_grader"), [], load_rules())
        payload = review._grader_input({"messages": messages, "rubric": load_rules(),
                                       "_current_grading_run_id": mode}, 0)
        outputs[mode] = payload["messages"][0].content
        tool_names[mode] = [t.name for t in review._tools]
        prompts[mode] = review._system_prompt
        tool = next(t for t in review._tools if t.name == "read_review_context")
        assert "AUTHOR_COMPLETION_CLAIM" in tool.invoke({"section": "history"})["content"]
    assert prompts["transcript"] == prompts["artifact"] == reviewer_prompt()
    assert tool_names["transcript"] == tool_names["artifact"]
    assert "AUTHOR_COMPLETION_CLAIM" in outputs["transcript"]
    assert "AUTHOR_COMPLETION_CLAIM" not in outputs["artifact"]
    assert "Compile a source-grounded limited draft" in outputs["artifact"]
    snapshots = workspace.store.get("review_context_snapshots")
    assert set(snapshots) == {"transcript:0", "artifact:0"}


def test_same_attempt_snapshot_stable_after_execution_activity(workspace):
    workspace.store.set("review_context_experiment", {"input_mode": "artifact", "grounded_verdict": False})
    review = native_review(workspace, Driver(rubric_grader=[AIMessage("Unused")])("rubric_grader"), [], load_rules())
    state = {"messages": [HumanMessage("Request")], "rubric": load_rules(), "_current_grading_run_id": "stable"}
    review._grader_input(state, 0)
    previous = workspace.store.get("review_context_snapshots")
    workspace.store.set("report_activity", "rubric_grader")
    review._grader_input(state, 0, "Correct the response format")
    assert workspace.store.get("review_context_snapshots") == previous


def test_reconstructed_context_recovers_and_changed_input_cannot_relabel_snapshot(workspace):
    workspace.store.set("review_context_experiment", {"input_mode": "artifact", "grounded_verdict": False})
    state = {"messages": [HumanMessage("Request")], "rubric": load_rules(), "_current_grading_run_id": "recovery"}
    def build(ws):
        return native_review(ws, Driver(rubric_grader=[AIMessage("Unused")])("rubric_grader"), [], load_rules())
    build(workspace)._grader_input(state, 0)
    expected = workspace.store.get("review_context_snapshots")
    targets = workspace.store.get("rubric_targets")
    reopened = Workspace(Store(workspace.store.root))
    build(reopened)._grader_input(state, 0)
    assert reopened.store.get("review_context_snapshots") == expected
    assert reopened.store.get("rubric_targets") == targets
    reopened.store.set("feedback", [{"origin": "operator", "message": "A new decision"}])
    with pytest.raises(RuntimeError, match="IDENTITY_CHANGED|SNAPSHOT_CHANGED"):
        build(reopened)._grader_input(state, 0)
    assert reopened.store.get("review_context_snapshots") == expected
    assert reopened.store.get("rubric_targets") == targets


def test_old_approval_does_not_match_a_different_context(workspace):
    from report_agent.review import export_configuration, observation_version, review_delivery
    draft = workspace.results()[0]
    workspace.store.set("active_rubric_hash", digest(load_rules()))
    workspace.store.set("rubric_reviews", [{"result": "satisfied", "unverified": False, "target": {
        "draft_id": draft["id"], "draft_body_sha256": sha256(draft["body"].encode()).hexdigest(),
        "observation_version": observation_version(workspace, draft["id"]),
        "rubric_hash": digest(load_rules()), "export_configuration_hash": export_configuration(workspace)}}])
    assert review_delivery(workspace, draft["id"])["status"] == "reviewed_draft"
    workspace.store.set("review_context_experiment", {"input_mode": "artifact", "grounded_verdict": False})
    assert review_delivery(workspace, draft["id"])["status"] == "unreviewed_draft"
