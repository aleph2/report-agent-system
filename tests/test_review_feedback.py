"""Actual native graph feedback; scripted models test mechanics, not report quality."""
import hashlib
import json
import traceback

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.errors import ActionForbidden
from report_agent.knowledge_state import project_state
from report_agent.review import reconcile_review, review_delivery
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, call, events, invoke, observation


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")

    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden in review integration tests")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(deep_runtime, "load_rules", lambda: "The report states daytime access and its source.")
    original = deep_runtime.error_data
    def capture(exc):
        traceback.print_exception(exc)
        return original(exc)
    monkeypatch.setattr(deep_runtime, "error_data", capture)
    store = Store(tmp_path)
    store.set("acceptance_mode", "legacy")  # This suite verifies the historical rubric protocol.
    store.initialize({"goal": "Compile daytime access.", "sources": [
        {"id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete"}]})
    result = Workspace(store)
    result.initialize()
    return result


def save(body, replaces=""):
    return invoke("submit_result", title="Report", body=body, source_ids=["s"],
                  input_ids=[], replaces_id=replaces)


def select(messages):
    return invoke("select_delivery", draft_id=observation(messages, "submit_result")["id"])


def verdict(status, gap=""):
    criterion = {"name": "Report states daytime access and its source", "passed": status == "satisfied"}
    if not criterion["passed"]:
        criterion["gap"] = gap
    return AIMessage(content="", tool_calls=[call("GraderResponse", {
        "result": status, "explanation": gap or "Evidence present.", "criteria": [criterion]})])


async def test_native_feedback_reaches_worker_and_revised_version_is_graded(ws):
    grades = []

    def grade(messages):
        grades.append(messages)
        return verdict("needs_revision", "Add daytime restriction and source s.") if len(grades) == 1 else verdict("satisfied")

    def revise(messages):
        assert "Add daytime restriction and source s." in str([m.content for m in messages])
        return save("Daytime access only [s].", ws.results()[0]["id"])

    driver = Driver(coordinator=[save("Access."), select, AIMessage(content="Ready."),
                                 revise, select, AIMessage(content="Revised." )],
                    rubric_grader=[grade])
    result = await _historical_feedback_run(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    assert len(grades) == 2
    records = ws.store.get("rubric_reviews")
    assert [r["result"] for r in records] == ["needs_revision", "satisfied"]
    assert records[0]["target"]["draft_id"] != records[1]["target"]["draft_id"]
    assert records[1]["target"]["preview_version"]
    assert len([r for r in ws.results() if r["kind"] == "review"]) == 0
    assert project_state(Workspace(Store(ws.store.root)))["status"] == "reviewed_draft"


async def _historical_terminal_component(ws, driver, *, grader_tools=(), grader_middleware=(), body="Daytime access only [s]."):
    """Retained native terminal/error mechanics; no retired production entrypoint."""
    from copy import deepcopy
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review, reviewer_prompt
    task = ws.request_task("draft", "Historical terminal-boundary artifact", [])
    draft = ws.submit(task["id"], actor="writer", title="Report", body=body,
        source_ids=["s"], input_ids=[])
    ws.select_delivery(draft["id"], "")
    originals = deepcopy(ws.results()), deepcopy(ws.tasks()), deepcopy(ws.store.manifest["sources"])
    commits = deepcopy(events(ws, "result_committed"))
    rules = deep_runtime.load_rules()
    ws.store.set("active_rubric_hash", digest(rules))
    ws.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
    config = {"configurable": {"thread_id": "historical-terminal-component"}}
    # This actual path is also read by the existing native events projector.
    path = str(ws.store.root / "checkpoints.db")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"), middleware=[native_review(ws,
            driver("rubric_grader"), list(grader_tools), rules, middleware=list(grader_middleware))], checkpointer=saver)
        await graph.ainvoke({"messages": [HumanMessage(content="Assess this historical saved draft once and explain a terminal limitation.")],
            "rubric": rules}, config)
        native = await graph.aget_state(config)
        assert not native.next and not native.interrupts
        assert native.values["rubric_terminal_handoff"] is False
        assert len(native.values["_rubric_evaluations"]) == 1
        notices = [m for m in native.values["messages"] if getattr(m, "name", None) == "rubric_terminal_feedback"]
        assert len(notices) == 1
        reconcile_review(ws, native.values)
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1 and records[0]["origin"] == "native_rubric_checkpoint"
    assert records[0]["grading_run_id"] == native.values["_rubric_evaluations"][0]["grading_run_id"]
    assert records[0]["iteration"] == 0 and records[0]["target"]["draft_id"] == draft["id"]
    assert records[0]["target"]["draft_body_sha256"] == hashlib.sha256(draft["body"].encode()).hexdigest()
    assert sum(role == "coordinator" for role, _, _ in driver.calls) == 2
    reopened = Workspace(Store(ws.store.root))
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        saved = await saver.aget_tuple(config)
        assert saved.checkpoint["channel_values"]["_rubric_evaluations"] == native.values["_rubric_evaluations"]
        reconcile_review(reopened, saved.checkpoint["channel_values"])
    assert reopened.store.get("rubric_reviews") == records
    assert (reopened.results(), reopened.tasks(), reopened.store.manifest["sources"]) == originals
    assert events(reopened, "result_committed") == commits and len(commits) == 1
    return review_delivery(reopened, draft["id"]), native


@pytest.mark.parametrize("error", [False, True])
async def test_terminal_feedback_is_seen_without_another_grading_loop(ws, error):
    grades, notices = [], []

    def grade(messages):
        grades.append(messages)
        if error:
            raise RuntimeError("private provider endpoint")
        return verdict("failed", "The available rubric cannot be evaluated.")

    def explain(messages):
        notice = next(m for m in messages if m.name == "rubric_terminal_feedback")
        notices.append(json.loads(notice.content))
        return AIMessage(content="Draft retained; review unavailable, not approved.")

    driver = Driver(coordinator=[AIMessage(content="Historical artifact ready."), explain],
                    rubric_grader=[grade])
    delivery, _ = await _historical_terminal_component(ws, driver, body="Access.")
    assert len(grades) == len(notices) == 1
    assert notices[0]["status"] == ("grader_error" if error else "failed")
    assert "private provider endpoint" not in str(notices)
    assert delivery["status"] != "reviewed_draft"
    assert "private provider endpoint" not in str(delivery)


def test_missing_or_wrong_target_cannot_project_success(ws):
    task = ws.request_task("draft", "Write", [])
    draft = ws.submit(task["id"], actor="writer", title="Draft", body="Text", source_ids=["s"], input_ids=[])
    ws.store.set("active_rubric_hash", digest("rules"))
    evaluation = {"grading_run_id": "g", "iteration": 0, "result": "satisfied", "criteria": [], "unverified": False}
    reconcile_review(ws, {"_rubric_evaluations": [evaluation], "_rubric_status": "satisfied"})
    assert review_delivery(ws, draft["id"])["status"] == "unreviewed_draft"
    ws.store.set("rubric_targets", {"g:1": {"draft_id": draft["id"],
        "draft_body_sha256": hashlib.sha256(b"Text").hexdigest(), "rubric_hash": digest("different")}})
    reconcile_review(ws, {"_rubric_evaluations": [{**evaluation, "iteration": 1}]})
    assert review_delivery(ws, draft["id"])["status"] == "unreviewed_draft"


def test_recording_issue_does_not_require_pausing_or_resolve_it(ws):
    tools = {t.__name__: t for t in deep_runtime.business_tools(ws, "coordinator", None, None)}
    result = tools["ask_human"]("source_conflict", "Two source values need a human decision.", ["s"], pause=False)
    assert result["waiting_for_human"] and not result["execution_paused"]
    assert not result["issue"]["resolved"]
    assert ws.store.get("report_issues")[0]["id"] == result["issue"]["id"]


async def review_snapshot(workspace, driver):
    async with deep_runtime.project_agent(workspace, driver, rules=deep_runtime.load_rules()) as agent:
        return await agent.aget_state({"configurable": {"thread_id": "report"}}, subgraphs=True)


@pytest.mark.parametrize("fail_handoff", [False, True], ids=["normal", "reopen-pending-handoff"])
async def test_three_native_grades_one_terminal_handoff_without_budget_reset(ws, fail_handoff):
    grades, notices = [], []

    def grade(messages):
        grades.append(messages)
        return verdict("needs_revision", "Add a verifiable source citation.")

    def revise(messages):
        assert "Add a verifiable source citation." in str([m.content for m in messages])
        previous = observation(messages, "submit_result")["id"]
        return save(f"Daytime access revision {len(grades)}.", previous)

    def explain(messages):
        terminal = [m for m in messages if m.name == "rubric_terminal_feedback"]
        assert len(terminal) == 1
        notice = json.loads(terminal[0].content)
        assert notice["status"] == "max_iterations_reached"
        assert notice["criteria"][0]["gap"] == "Add a verifiable source citation."
        notices.append(notice)
        return AIMessage(content="Draft saved; source citation remains unverified. Not approved.")

    scripts = {
        "coordinator": [save("Access."), select, AIMessage(content="Ready."),
                        revise, select, AIMessage(content="Revision one."),
                        revise, select, AIMessage(content="Revision two."), explain],
        "rubric_grader": [grade],
    }
    driver = Driver(**scripts)
    if fail_handoff:
        driver.fail_once = ("coordinator", 9)
    if fail_handoff:
        # Explicit wrapper migration: inspect the real native exception rather than fabricating an error envelope.
        with pytest.raises(httpx.ReadTimeout, match="offline injected transient read failure"):
            await _historical_feedback_run(ws, driver)
    else:
        result = await _historical_feedback_run(ws, driver)
    if fail_handoff:
        pending = await _historical_feedback_snapshot(ws, driver)
        assert pending.next and not pending.interrupts
        assert pending.values["rubric_terminal_handoff"] is True
        assert pending.values["_rubric_iterations"] == 3
        assert pending.values["_rubric_status"] == "max_iterations_reached"
        run_id = pending.values["_current_grading_run_id"]
        saved, targets = ws.results(), ws.store.get("rubric_targets")
        assert len(saved) == len(grades) == 3 and notices == []
        reopened = Workspace(Store(ws.store.root))
        fresh = Driver(**scripts)
        result = await _historical_feedback_run(reopened, fresh, resume=True)
        assert fresh.calls[0][:2] == ("coordinator", 9)
        assert all(role != "rubric_grader" for role, _, _ in fresh.calls)
        assert reopened.results() == saved
        assert reopened.store.get("rubric_targets") == targets
        ws, driver = reopened, fresh
        final = await _historical_feedback_snapshot(ws, driver)
        assert final.values["_current_grading_run_id"] == run_id
    else:
        final = await _historical_feedback_snapshot(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "changes_required", result
    assert len(grades) == 3 and len(notices) == 1
    assert not final.next and not final.interrupts
    assert final.values["rubric_terminal_handoff"] is False
    assert final.values["_rubric_iterations"] == 3
    assert final.values["_rubric_status"] == "max_iterations_reached"
    records = ws.store.get("rubric_reviews")
    assert [r["result"] for r in records] == ["needs_revision", "needs_revision", "max_iterations_reached"]
    assert [r["iteration"] for r in records] == [0, 1, 2]
    assert len({r["grading_run_id"] for r in records}) == 1
    assert len({r["target"]["draft_id"] for r in records}) == 3
    assert len(ws.results()) == len(events(ws, "result_committed")) == 3
    assert len([m for m in final.values["messages"] if m.name == "rubric_terminal_feedback"]) == 1
    reconcile_review(ws, final.values)
    assert ws.store.get("rubric_reviews") == records


async def test_observation_callback_failure_reconciles_from_native_checkpoint(ws, monkeypatch):
    # Explicit retained historical middleware integration. This exercises the
    # actual same-run callback suppression and saver, not the retired production
    # entrypoint or a failure/reopen substitution for successful execution.
    from copy import deepcopy
    from langchain_core.messages import HumanMessage
    from langchain.agents import create_agent
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review, reviewer_prompt
    task = ws.request_task("draft", "Dated synthetic saved draft for middleware compatibility", [])
    draft = ws.submit(task["id"], actor="writer", title="Synthetic report", body="Daytime access only [s].",
        source_ids=["s"], input_ids=[])
    ws.select_delivery(draft["id"], "")
    original_results, original_sources = deepcopy(ws.results()), deepcopy(ws.store.manifest["sources"])
    rules = deep_runtime.load_rules()
    ws.store.set("active_rubric_hash", digest(rules))
    ws.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
    event, failures = ws.store.event, []
    def fail_observation(kind, data):
        if kind == "rubric_review_observed":
            failures.append(deepcopy(data))
            raise RuntimeError("SYNTHETIC_OBSERVATION_SINK_FAILURE")
        return event(kind, data)
    monkeypatch.setattr(ws.store, "event", fail_observation)
    driver = Driver(coordinator=[AIMessage(content="Historical saved artifact selected; synthetic protocol only.")],
        rubric_grader=[verdict("satisfied")])
    path = str(ws.store.root / "historical-observer-checkpoints.db")
    config = {"configurable": {"thread_id": "historical-observer-component"}}
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"),
            middleware=[native_review(ws, driver("rubric_grader"), [], rules)], checkpointer=saver)
        # Must finish this invocation normally despite the actual callback fault.
        await graph.ainvoke({"messages": [HumanMessage(content="Review the selected synthetic historical draft.")],
            "rubric": rules}, config)
        native = await graph.aget_state(config)
        assert not native.next and not native.interrupts
        assert native.values["_rubric_status"] == "satisfied"
        evaluations = native.values["_rubric_evaluations"]
        assert len(evaluations) == 1 and evaluations[0]["result"] == "satisfied"
        # Reconcile immediately from the same successful native invocation.
        reconcile_review(ws, native.values)
    assert len(failures) == 1
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1 and records[0]["origin"] == "native_rubric_checkpoint"
    assert records[0]["grading_run_id"] == evaluations[0]["grading_run_id"]
    assert records[0]["iteration"] == evaluations[0]["iteration"] == 0
    assert records[0]["target"]["draft_id"] == draft["id"]
    assert records[0]["target"]["draft_body_sha256"] == hashlib.sha256(draft["body"].encode()).hexdigest()
    assert review_delivery(ws, draft["id"])["status"] == "reviewed_draft"
    assert sum(role == "rubric_grader" for role, _, _ in driver.calls) == 1
    assert sum(role == "coordinator" for role, _, _ in driver.calls) == 1
    reopened = Workspace(Store(ws.store.root))
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        checkpoint = await saver.aget_tuple(config)
        assert checkpoint is not None
        persisted = checkpoint.checkpoint["channel_values"]
        assert persisted["_rubric_evaluations"] == evaluations
        reconcile_review(reopened, persisted)
    assert reopened.store.get("rubric_reviews") == records
    assert reopened.results() == original_results == [draft]
    assert reopened.store.manifest["sources"] == original_sources
    assert len(events(reopened, "result_committed")) == 1
    assert not events(reopened, "rubric_review_observed")
    assert review_delivery(reopened, draft["id"])["status"] == "reviewed_draft"


async def test_native_grader_reads_exact_export_through_real_tool_node(tmp_path):
    # Explicit current artifact checker route; no retired grader/global pass claim.
    from hierarchical_fixtures import current_native_export_read_review
    _, _, seen, result = await current_native_export_read_review(tmp_path)
    assert result["last_error"] is None and seen["packet"]


async def test_legacy_child_interrupt_resumes_with_rubric_without_duplicate_result(ws, monkeypatch):
    rules = deep_runtime.load_rules()
    monkeypatch.setattr(deep_runtime, "load_rules", lambda: "")

    def select_child(messages):
        return invoke("select_delivery", draft_id=ws.results()[0]["id"])

    scripts = {
        "coordinator": [invoke("task", subagent_type="writer", description="Save draft and confirm scope"),
                        select_child, AIMessage(content="Saved report ready for grading.")],
        "writer": [save("Daytime access only [s]."),
                   invoke("ask_human", category="source_conflict", description="Confirm daytime scope", source_ids=["s"]),
                   AIMessage(content="Draft saved; operator scope recorded.")],
        "rubric_grader": [verdict("satisfied")],
    }
    driver = Driver(**scripts)
    # Explicit historical component migration: actual native child state replaces
    # the retired wrapper's needs_human envelope; no manufactured status.
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    from report_agent.review import reviewer_prompt
    config = {"configurable": {"thread_id": "report"}}
    with ws.store.run_lock():
        async with _historical_child_agent(ws, driver, rules="") as agent:
            await agent.ainvoke({"messages": [HumanMessage(content="Save the synthetic draft and confirm daytime scope.")]}, config)
            old = await agent.aget_state(config, subgraphs=True)
    assert old.next and len(old.interrupts) == 1
    assert not old.values.get("rubric")
    assert not old.values.get("_active_rubric")
    assert not old.values.get("_current_grading_run_id")
    saved = ws.results()
    assert len(saved) == len(events(ws, "result_committed")) == 1
    assert not any(role == "rubric_grader" for role, _, _ in driver.calls)

    monkeypatch.setattr(deep_runtime, "load_rules", lambda: rules)
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**scripts)
    reopened.store.set("active_rubric_hash", digest(rules))
    reopened.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
    with reopened.store.run_lock():
        async with _historical_child_agent(reopened, fresh, rules=rules) as agent:
            # Actually invoke without a resume answer; reading a checkpoint alone
            # would not establish the original zero-new-call waiting predicate.
            await agent.ainvoke(None, config)
            waiting = await agent.aget_state(config, subgraphs=True)
            assert [i.id for i in waiting.interrupts] == [i.id for i in old.interrupts]
            assert waiting.next and fresh.calls == [] and reopened.results() == saved
    # Real operator transaction acquires its own lock between native invocations.
    reopened.decide_issue(old.interrupts[0].value["issue_id"], "Operator confirms daytime scope", resolved=True)
    with reopened.store.run_lock():
        async with _historical_child_agent(reopened, fresh, rules=rules) as agent:
            waiting = await agent.aget_state(config, subgraphs=True)
            issues = {i["id"]: i for i in reopened.store.get("report_issues", [])}
            answers = {}
            for pending in waiting.interrupts:
                issue = issues[pending.value["issue_id"]]
                assert issue["decision_origin"] == "operator"
                answers[pending.id] = issue["decision"]
            update = agent.report_review_middleware.before_agent({**waiting.values, "rubric": rules}, None)
            assert update and update["_current_grading_run_id"]
            await agent.ainvoke(Command(resume=answers, update={"rubric": rules, **update}), config)
            final = await agent.aget_state(config, subgraphs=True)
            reconcile_review(reopened, final.values)
            result = project_state(reopened)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    assert not final.next and not final.interrupts
    assert final.values["rubric"] == rules
    assert final.values["_active_rubric"] == rules
    assert final.values["_rubric_iterations"] == 1
    run_id = final.values["_current_grading_run_id"]
    records = reopened.store.get("rubric_reviews")
    assert len(records) == 1
    assert records[0]["grading_run_id"] == run_id
    assert records[0]["iteration"] == 0
    assert records[0]["target"]["draft_id"] == saved[0]["id"]
    assert set(reopened.store.get("rubric_targets")) == {run_id + ":0"}
    assert len([entry for entry in fresh.calls if entry[0] == "rubric_grader"]) == 1
    assert reopened.results() == saved
    assert len(events(reopened, "result_committed")) == len(events(reopened, "human_decision")) == 1
    assert len(events(reopened, "issue_recorded")) == 1
    assert len([e for e in events(reopened, "deep_tool_start") if e["tool"] == "submit_result"]) == 1
    replies = [m for role, _, messages in fresh.calls if role == "writer" for m in messages
               if isinstance(m, ToolMessage) and m.name == "ask_human"]
    assert replies and "Operator confirms daytime scope" in replies[-1].content


async def test_grader_corrects_invalid_result_page_in_same_native_invocation(tmp_path):
    # Explicit migration: today's Reviewer corrects a public read_result page
    # in one invocation; a historical note is data, not an automatic grader run.
    from report_agent.content_store import ContentStore
    from report_agent.store import encode
    from test_task_supervision import ws as native_ws
    from test_hierarchical_content import seed
    from test_bounded_review import review_call
    current = native_ws.__wrapped__(tmp_path)
    cs, _, refs, frozen, _ = seed(current)
    body = "Daytime access only [s]."
    historical = {"id": "dated-read-page-note", "kind": "note", "body": body,
                  "source_ids": ["s"], "input_ids": [], "fact_ids": [],
                  "origin": "dated-format-static-read-only-fixture"}
    with current.store.connect() as db:
        db.execute("INSERT INTO results VALUES (?,?,?)", (historical["id"], "dated-static-note", encode(historical)))
    corrected = []
    def invalid_read(messages):
        return AIMessage(content="", tool_calls=[call("read_result", {
            "result_id": historical["id"], "offset": 0, "characters": 16001}, "invalid-read")])
    def correct_read(messages):
        reply = next(m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == "invalid-read")
        assert reply.name == "read_result" and reply.status == "error"
        error = json.loads(reply.content)
        assert error["accepted"] is False and error["ok"] is False
        assert error["error"]["type"] == "ActionRejected"
        assert error["code"] == "INVALID_RESULT_PAGE" and error["message"] == "INVALID_RESULT_PAGE"
        assert body not in reply.content
        corrected.append(error)
        return AIMessage(content="", tool_calls=[call("read_result", {
            "result_id": historical["id"], "offset": 0, "characters": 16000}, "corrected-read")])
    def finish_read(messages):
        replies = [m for m in messages if isinstance(m, ToolMessage) and m.name == "read_result"]
        assert [(m.tool_call_id, m.status) for m in replies] == [
            ("invalid-read", "error"), ("corrected-read", "success")]
        page = json.loads(replies[-1].content)
        assert page["id"] == historical["id"]
        assert page["body"] == body and page["next_offset"] is None
        return AIMessage(content="Read-only material observed; no review verdict claimed.")
    assignment = review_call(frozen, refs)
    assignment["args"].pop("supervision_plugin", None)
    assignment["args"]["description"] = "Read historical note " + historical["id"] + "; correct invalid pagination, return observations only."
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[assignment]),
                                 AIMessage(content="Read-only task returned; no delivery selected.")],
                    reviewer=[invalid_read, correct_read, finish_read])
    before = cs.list_objects("ContentNode"), cs.list_objects("Criterion")
    result = await deep_runtime.run_report(current, driver)
    assert result["last_error"] is None, result
    assert len(corrected) == 1
    assert [step for role, step, _ in driver.calls if role == "reviewer"] == [0, 1, 2]
    assert not any(role in {"text_tool", "rubric_grader"} for role, _, _ in driver.calls)
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert not cs.list_objects("ReviewRecord")
    assert before == (cs.list_objects("ContentNode"), cs.list_objects("Criterion"))
    assert current.result(historical["id"]) == historical
    assert result["status"] != "reviewed_draft"


@pytest.mark.parametrize("unknown", [False, True], ids=["permission-denied", "unknown-tool-error"])
async def test_grader_adapter_keeps_permission_denial_and_does_not_mask_unknown_errors(ws, monkeypatch, unknown):
    original_result = ws.result
    armed, errors_seen, terminal = [], [], []

    def protected_result(result_id):
        if armed:
            armed.pop()
            if unknown:
                raise RuntimeError("synthetic private provider body https://invalid.example/key")
            raise ActionForbidden("RESULT_ACCESS_FORBIDDEN")
        return original_result(result_id)

    monkeypatch.setattr(ws, "result", protected_result)

    def attempt_read(messages):
        result_id = ws.results()[0]["id"]
        armed.append(True)
        return invoke("read_result", result_id=result_id, offset=0, characters=100)

    def observe_denial(messages):
        reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_result")
        assert reply.status == "error"
        payload = json.loads(reply.content)
        assert payload["accepted"] is False
        assert payload["error"]["type"] == "ActionForbidden"
        assert payload["error"]["message"] == "RESULT_ACCESS_FORBIDDEN"
        assert "Daytime access only" not in reply.content
        errors_seen.append(payload)
        return verdict("failed", "Cannot verify the report because access was denied.")

    def explain(messages):
        notice = next(m for m in messages if m.name == "rubric_terminal_feedback")
        terminal.append(json.loads(notice.content))
        assert "invalid.example" not in notice.content
        assert "synthetic private" not in notice.content
        return AIMessage(content="Report retained, not approved; review unavailable.")

    driver = Driver(coordinator=[AIMessage(content="Historical artifact ready."), explain],
                    rubric_grader=[attempt_read] if unknown else [attempt_read, observe_denial])
    read_tool = next(t for t in deep_runtime.business_tools(ws, "reviewer", None, None) if t.__name__ == "read_result")
    delivery, _ = await _historical_terminal_component(ws, driver, grader_tools=[read_tool],
        grader_middleware=[deep_runtime.BusinessBoundary(ws, "rubric_grader")])
    assert delivery["status"] != "reviewed_draft"
    assert len(terminal) == 1 and terminal[0]["status"] == ("grader_error" if unknown else "failed")
    assert len(errors_seen) == (0 if unknown else 1)
    assert len([entry for entry in driver.calls if entry[0] == "rubric_grader"]) == (1 if unknown else 2)
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1
    assert records[0]["result"] == ("grader_error" if unknown else "failed")
    assert "invalid.example" not in json.dumps(records)
    assert "invalid.example" not in str(delivery) and "synthetic private" not in str(delivery)
    assert len(ws.results()) == len(events(ws, "result_committed")) == 1
    rejected = [e for e in events(ws, "deep_tool_rejected") if e["role"] == "rubric_grader"]
    assert len(rejected) == (0 if unknown else 1)
    if not unknown:
        assert rejected[0]["type"] == "ActionForbidden"
        assert rejected[0]["message"] == "RESULT_ACCESS_FORBIDDEN"


from contextlib import asynccontextmanager


@asynccontextmanager
async def _historical_feedback_graph(ws, driver):
    """Retained legacy native feedback with actual tools and checkpoint lifecycle."""
    from inspect import iscoroutinefunction
    from langchain.agents import create_agent
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review, reviewer_prompt

    rules = deep_runtime.load_rules()
    ws.store.set("active_rubric_hash", digest(rules))
    ws.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
    config = {"configurable": {"thread_id": "historical-feedback-behavior"}}
    tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
             else StructuredTool.from_function(t)
             for t in deep_runtime.business_tools(ws, "coordinator", None, None)]
    async with AsyncSqliteSaver.from_conn_string(str(ws.store.root / "checkpoints.db")) as saver:
        graph = create_agent(model=driver("coordinator"), tools=tools,
            system_prompt=deep_runtime.COORDINATOR,
            middleware=[deep_runtime.BusinessBoundary(ws, "coordinator"),
                native_review(ws, driver("rubric_grader"), [], rules=rules)], checkpointer=saver)
        yield graph, config, rules


async def _historical_feedback_run(ws, driver, *, resume=False):
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    async with _historical_feedback_graph(ws, driver) as (graph, config, rules):
        request = Command(update={"rubric": rules}) if resume else {
            "messages": [HumanMessage(content="Complete the original historical report task.")], "rubric": rules}
        await graph.ainvoke(request, config)
        state = await graph.aget_state(config)
        assert not state.next and not state.interrupts
        reconcile_review(ws, state.values)
        return project_state(ws)


async def _historical_feedback_snapshot(ws, driver):
    async with _historical_feedback_graph(ws, driver) as (graph, config, _):
        return await graph.aget_state(config)


from contextlib import asynccontextmanager


@asynccontextmanager
async def _historical_child_agent(workspace, driver, *, rules):
    """Actual historical child/tool/saver topology; never a production entrypoint."""
    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review
    co_tools = [t for t in deep_runtime.business_tools(workspace, "coordinator", None, None)
                if t.__name__ == "select_delivery"]
    writer_tools = [t for t in deep_runtime.business_tools(workspace, "writer", None, None)
                    if t.__name__ in {"submit_result", "ask_human"}]
    middleware = native_review(workspace, driver("rubric_grader"), [], rules,
        middleware=[deep_runtime.BusinessBoundary(workspace, "rubric_grader")]) if rules else None
    async with AsyncSqliteSaver.from_conn_string(str(workspace.store.root / "checkpoints.db")) as saver:
        agent = create_deep_agent(model=driver("coordinator"), tools=co_tools,
            system_prompt=deep_runtime.COORDINATOR, backend=StateBackend(),
            middleware=[deep_runtime.BusinessBoundary(workspace, "coordinator"), *([middleware] if middleware else [])],
            subagents=[{"name": "writer", "description": "Historical synthetic draft owner",
                "system_prompt": "Save the assigned synthetic draft and ask the human about scope.",
                "model": driver("writer"), "tools": writer_tools,
                "middleware": [deep_runtime.BusinessBoundary(workspace, "writer")]}],
            checkpointer=saver, name="report_coordinator")
        agent.report_review_middleware = middleware
        yield agent
