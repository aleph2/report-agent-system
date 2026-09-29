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
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    assert len(grades) == 2
    records = ws.store.get("rubric_reviews")
    assert [r["result"] for r in records] == ["needs_revision", "satisfied"]
    assert records[0]["target"]["draft_id"] != records[1]["target"]["draft_id"]
    assert records[1]["target"]["preview_version"]
    assert len([r for r in ws.results() if r["kind"] == "review"]) == 0
    assert project_state(Workspace(Store(ws.store.root)))["status"] == "reviewed_draft"


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

    driver = Driver(coordinator=[save("Access."), select, AIMessage(content="Ready."), explain],
                    rubric_grader=[grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert len(grades) == len(notices) == 1
    assert notices[0]["status"] == ("grader_error" if error else "failed")
    assert "private provider endpoint" not in str(notices)
    assert result["status"] != "reviewed_draft"
    assert "private provider endpoint" not in str(result.get("delivery"))


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
    result = await deep_runtime.run_report(ws, driver)
    if fail_handoff:
        assert result["status"] == "failed", result
        assert result["last_error"]["type"] == "ReadTimeout"
        pending = await review_snapshot(ws, driver)
        assert pending.next and not pending.interrupts
        assert pending.values["rubric_terminal_handoff"] is True
        assert pending.values["_rubric_iterations"] == 3
        assert pending.values["_rubric_status"] == "max_iterations_reached"
        run_id = pending.values["_current_grading_run_id"]
        saved, targets = ws.results(), ws.store.get("rubric_targets")
        assert len(saved) == len(grades) == 3 and notices == []
        reopened = Workspace(Store(ws.store.root))
        fresh = Driver(**scripts)
        result = await deep_runtime.run_report(reopened, fresh)
        assert fresh.calls[0][:2] == ("coordinator", 9)
        assert all(role != "rubric_grader" for role, _, _ in fresh.calls)
        assert reopened.results() == saved
        assert reopened.store.get("rubric_targets") == targets
        ws, driver = reopened, fresh
        final = await review_snapshot(ws, driver)
        assert final.values["_current_grading_run_id"] == run_id
    else:
        final = await review_snapshot(ws, driver)
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
    event = ws.store.event
    failures = []

    def fail_observation(kind, data):
        if kind == "rubric_review_observed":
            failures.append(data)
            raise RuntimeError("SYNTHETIC_OBSERVATION_SINK_FAILURE")
        return event(kind, data)

    monkeypatch.setattr(ws.store, "event", fail_observation)
    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready.")],
                    rubric_grader=[verdict("satisfied")])
    result = await deep_runtime.run_report(ws, driver)
    assert len(failures) == 1
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    native = await review_snapshot(ws, driver)
    assert native.values["_rubric_status"] == "satisfied"
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1 and records[0]["origin"] == "native_rubric_checkpoint"
    assert records[0]["grading_run_id"] == native.values["_rubric_evaluations"][0]["grading_run_id"]
    assert records[0]["target"]["draft_id"] == ws.results()[0]["id"]
    reopened = Workspace(Store(ws.store.root))
    reconcile_review(reopened, native.values)
    assert reopened.store.get("rubric_reviews") == records
    assert len(reopened.results()) == len(events(reopened, "result_committed")) == 1
    assert not events(reopened, "rubric_review_observed")


async def test_native_grader_reads_exact_export_through_real_tool_node(ws):
    reads = []

    def grade_export(messages):
        page = observation(messages, "read_review_export")
        reads.append(page)
        assert "Daytime access only" in page["text"]
        assert page["unit"] == "text_blocks" and page["physical_page_numbers"] is None
        target = next(iter(ws.store.get("rubric_targets").values()))
        for field in ("draft_id", "preview_version", "draft_body_sha256", "docx_sha256"):
            assert page[field] == target[field]
        data = (ws.store.root / "previews" / page["preview_version"] / "report.docx").read_bytes()
        assert hashlib.sha256(data).hexdigest() == page["docx_sha256"]
        return verdict("satisfied")

    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready.")],
                    rubric_grader=[invoke("read_review_export", offset=0, limit=30), grade_export])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    assert len(reads) == 1
    assert len([entry for entry in driver.calls if entry[0] == "rubric_grader"]) == 2
    assert ws.store.get("rubric_reviews")[0]["target"]["preview_version"] == reads[0]["preview_version"]


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
    first = await deep_runtime.run_report(ws, driver)
    assert first["status"] == "needs_human", first
    old = await review_snapshot(ws, driver)
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
    waiting = await deep_runtime.run_report(reopened, fresh)
    assert waiting["status"] == "needs_human" and fresh.calls == []
    reopened.decide_issue(old.interrupts[0].value["issue_id"], "Operator confirms daytime scope", resolved=True)
    result = await deep_runtime.run_report(reopened, fresh)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    final = await review_snapshot(reopened, fresh)
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


async def test_grader_corrects_invalid_result_page_in_same_native_invocation(ws):
    body = "Daytime access only [s]."
    corrected = []

    def invalid_read(messages):
        return AIMessage(content="", tool_calls=[call("read_result", {
            "result_id": ws.results()[0]["id"], "offset": 0, "characters": 16001,
        }, "invalid-read")])

    def correct_read(messages):
        reply = next(m for m in messages if isinstance(m, ToolMessage)
                     and m.tool_call_id == "invalid-read")
        assert reply.name == "read_result" and reply.status == "error"
        error = json.loads(reply.content)
        assert error["accepted"] is False
        assert error["error"]["type"] == "ActionRejected"
        assert error["error"]["message"] == "INVALID_RESULT_PAGE"
        assert body not in reply.content
        corrected.append(error)
        return AIMessage(content="", tool_calls=[call("read_result", {
            "result_id": ws.results()[0]["id"], "offset": 0, "characters": 16000,
        }, "corrected-read")])

    def grade_read(messages):
        replies = [m for m in messages if isinstance(m, ToolMessage) and m.name == "read_result"]
        assert [(m.tool_call_id, m.status) for m in replies] == [
            ("invalid-read", "error"), ("corrected-read", "success")]
        page = json.loads(replies[-1].content)
        assert page["id"] == ws.results()[0]["id"]
        assert page["body"] == body and page["next_offset"] is None
        return verdict("satisfied")

    driver = Driver(coordinator=[save(body), select, AIMessage(content="Ready.")],
                    rubric_grader=[invalid_read, correct_read, grade_read])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    assert len(corrected) == 1
    assert [step for role, step, _ in driver.calls if role == "rubric_grader"] == [0, 1, 2]
    assert [step for role, step, _ in driver.calls if role == "coordinator"] == [0, 1, 2]
    native = await review_snapshot(ws, driver)
    assert native.values["_rubric_iterations"] == 1
    assert native.values["_rubric_status"] == "satisfied"
    assert not native.next and not native.interrupts
    assert not any(m.name == "rubric_terminal_feedback" for m in native.values["messages"])
    assert len(ws.store.get("rubric_reviews")) == len(ws.store.get("rubric_targets")) == 1
    assert len(events(ws, "rubric_review_started")) == len(events(ws, "deep_run_started")) == 1
    assert len(ws.results()) == len(events(ws, "result_committed")) == 1
    reads = [e for e in events(ws, "deep_tool_start")
             if e["role"] == "rubric_grader" and e["tool"] == "read_result"]
    assert [e["arguments"]["characters"] for e in reads] == [16001, 16000]
    rejected = [e for e in events(ws, "deep_tool_rejected") if e["role"] == "rubric_grader"]
    assert len(rejected) == 1
    assert rejected[0]["tool_call_id"] == "invalid-read"
    assert rejected[0]["message"] == "INVALID_RESULT_PAGE"


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

    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready."), explain],
                    rubric_grader=[attempt_read] if unknown else [attempt_read, observe_denial])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] != "reviewed_draft"
    assert len(terminal) == 1 and terminal[0]["status"] == ("grader_error" if unknown else "failed")
    assert len(errors_seen) == (0 if unknown else 1)
    assert len([entry for entry in driver.calls if entry[0] == "rubric_grader"]) == (1 if unknown else 2)
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1
    assert records[0]["result"] == ("grader_error" if unknown else "failed")
    assert "invalid.example" not in json.dumps(records)
    assert len(ws.results()) == len(events(ws, "result_committed")) == 1
    rejected = [e for e in events(ws, "deep_tool_rejected") if e["role"] == "rubric_grader"]
    assert len(rejected) == (0 if unknown else 1)
    if not unknown:
        assert rejected[0]["type"] == "ActionForbidden"
        assert rejected[0]["message"] == "RESULT_ACCESS_FORBIDDEN"
