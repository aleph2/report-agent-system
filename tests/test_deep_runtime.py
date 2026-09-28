"""Task006 infrastructure evidence: real DeepAgents, scripted offline chat models.

These tests do not establish model autonomy, report quality or engineering approval.
No ADK imports, paid model calls, real project inputs or external graph writes.
"""
from __future__ import annotations

import asyncio
import json
import traceback
from collections import Counter
from typing import Any

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from report_agent import deep_runtime
from report_agent.store import Store
from report_agent.workspace import Workspace


class ScriptedChat(BaseChatModel):
    model_name: str = "offline-runtime-test"
    role: str
    driver: Any = Field(exclude=True)

    @property
    def _llm_type(self):
        return "offline-scripted-chat"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "openai", "ls_model_name": self.model_name,
                "ls_model_type": "chat"}

    def bind_tools(self, tools, **kwargs):
        schemas = [convert_to_openai_tool(tool)["function"] for tool in tools]
        self.driver.bindings.setdefault(self.role, []).append(schemas)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("Tests must execute the asynchronous graph")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return await self.driver.respond(self.role, messages)


class Driver:
    def __init__(self, **scripts):
        self.scripts = scripts
        self.bindings = {}
        self.calls = []
        self.created = []
        self.fail_once = None
        self.failed = False
        self.active_children = 0
        self.max_active_children = 0
        self.delay_children = False

    def __call__(self, role):
        self.created.append(role)
        return ScriptedChat(role=role, driver=self)

    async def respond(self, role, messages):
        step = sum(isinstance(message, AIMessage) for message in messages)
        self.calls.append((role, step, list(messages)))
        if self.fail_once == (role, step) and not self.failed:
            self.failed = True
            raise httpx.ReadTimeout("offline injected transient read failure")
        if self.delay_children and role != "coordinator":
            self.active_children += 1
            self.max_active_children = max(self.max_active_children, self.active_children)
            try:
                await asyncio.sleep(0.05)
            finally:
                self.active_children -= 1
        script = self.scripts.get(role, [])
        if step >= len(script):
            raise AssertionError(f"Unexpected model call: {role} step {step}")
        item = script[step]
        response = item(messages) if callable(item) else item
        return ChatResult(generations=[ChatGeneration(message=response)])


def call(name, arguments, identity=None):
    return {"name": name, "args": arguments, "id": identity or name,
            "type": "tool_call"}


def invoke(name, **arguments):
    return AIMessage(content="", tool_calls=[call(name, arguments)])


def observation(messages, name):
    message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == name)
    return json.loads(message.content)


def final_receipt(messages):
    return AIMessage(content=json.dumps(observation(messages, "submit_result")))


def draft_call(source_id="source"):
    return invoke("submit_result", kind="draft", title="Synthetic access report",
                  body="The east path is open in daytime [source]. No engineering sign-off.",
                  source_ids=[source_id], input_ids=[])


def delegate_review(messages):
    draft = observation(messages, "submit_result")
    assert draft.get("kind") == "draft", draft
    return invoke("task", subagent_type="reviewer",
                  description=json.dumps({"draft_id": draft["id"]}))


def read_delegated_draft(messages):
    request = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
    return invoke("read_result", result_id=json.loads(request.content)["draft_id"])


def submit_review(messages):
    draft = observation(messages, "read_result")
    assert draft.get("kind") == "draft", draft
    return invoke("submit_result", kind="review", title="Independent review",
                  body="Checked the supplied draft and its limited synthetic scope.",
                  source_ids=draft["source_ids"], input_ids=[draft["id"]],
                  target_id=draft["id"], outcome="accepted")


def deliver(messages):
    review = observation(messages, "task")
    assert review.get("kind") == "review", review
    return invoke("select_delivery", draft_id=review["target_id"], review_id=review["id"])


def trunk_driver(source_id="source"):
    return Driver(coordinator=[invoke("read_source_page", source_id=source_id),
                               draft_call(source_id), delegate_review, deliver, AIMessage(content="Delivered")],
                  reviewer=[read_delegated_draft, submit_review, final_receipt])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Historical harness/ownership scenarios exercise optional delegated review.
    # Task013 separately tests the native rubric feedback path with real middleware.
    monkeypatch.setattr(deep_runtime, "load_rules", lambda: "")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")

    def denied(*args, **kwargs):
        raise AssertionError("Network calls are forbidden in offline runtime tests")

    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)
    monkeypatch.setattr(deep_runtime, "configured_model", denied)


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path / "project")
    store.initialize({"goal": "Compile the supplied daytime access note; no new design.",
                      "sources": [{"id": "source", "title": "Synthetic source",
                                   "coverage": "complete", "content": "The east path is open in daytime."}]})
    workspace = Workspace(store)
    workspace.initialize()
    assert not workspace.results()
    return workspace


@pytest.fixture
def failure_stacks(monkeypatch):
    stacks = []
    original = deep_runtime.error_data

    def capture(exc):
        stacks.append("".join(traceback.format_exception(exc)))
        return original(exc)

    monkeypatch.setattr(deep_runtime, "error_data", capture)
    return stacks


async def run(ws, driver):
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)


def events(ws, kind):
    return [e["data"] for e in ws.store.events() if e["kind"] == kind]


def test_agent_view_excludes_internal_submission_tasks(ws):
    view = deep_runtime.project_view(ws)
    assert "tasks" not in view
    assert all("task" not in key for key in view["impact"])
    assert view["results"] == []
    assert view["sources"] == ws.status()["sources"]
    assert "tasks" in ws.status()  # Desktop audit retains the bookkeeping.


async def snapshot(ws, driver):
    async with deep_runtime.project_agent(ws, driver) as agent:
        return await agent.aget_state({"configurable": {"thread_id": "report"}}, subgraphs=True)


async def test_native_working_notes_and_todos_survive_reopen(ws):
    """Protocol evidence only: the scripted model does not prove autonomous progress."""
    def record_result(messages):
        total = observation(messages, "calculate")["total"]
        return invoke("write_file", file_path="/working-costs.md",
                      content=f"Adopted inputs: 10*0.6 + 20*0.4. Total: {total}. Remaining: draft.")

    todos = [{"content": "Batch A total verified: 14; inputs 10,20; weights 0.6,0.4",
              "status": "completed"},
             {"content": "Save comparison draft", "status": "pending"}]
    driver = Driver(coordinator=[invoke("calculate", terms=[["10", "0.6"], ["20", "0.4"]]),
                                record_result, invoke("write_todos", todos=todos),
                                AIMessage(content="Working state recorded")])
    await run(ws, driver)
    reopened = Workspace(Store(ws.store.root))
    saved = await snapshot(reopened, driver)
    assert saved.values["todos"] == todos
    assert "Total: 14.0" in saved.values["files"]["/working-costs.md"]["content"]
    assert observation(saved.values["messages"], "calculate")["total"] == "14.0"
    assert not reopened.results()  # Scratch notes are not published report results.
    assert sum(e["tool"] == "calculate" for e in events(ws, "deep_tool_start")) == 1
    system = "\n".join(block["text"] for m in driver.calls[0][2] if m.type == "system"
                       for block in m.content_blocks if block["type"] == "text")
    assert deep_runtime.WORK_STATE_GUIDANCE.strip() in system


def repeated_exchanges():
    messages = []
    for index in range(3):
        identity = f"calc-{index}"
        messages += [AIMessage(content="", tool_calls=[call("calculate", {"terms": [["1"]]}, identity)]),
                     ToolMessage(content='{"total":"1"}', name="calculate",
                                 tool_call_id=identity, status="success")]
    return messages


@pytest.mark.parametrize("change", ["arguments", "observation", "error", "human", "id", "multi"])
def test_repetition_notice_requires_matching_successful_exchanges(change):
    messages = repeated_exchanges()
    assert deep_runtime.repeated_observation(messages) == "calculate"
    if change == "arguments":
        messages[-2].tool_calls[0]["args"] = {"terms": [["2"]]}
    elif change == "observation":
        messages[-1].content = '{"total":"2"}'
    elif change == "error":
        messages[-1].status = "error"
    elif change == "human":
        messages.insert(-2, HumanMessage(content="A new observation"))
    elif change == "id":
        messages[-1].tool_call_id = "unrelated"
    else:
        messages[-2].tool_calls.append(call("project_status", {}))
    assert deep_runtime.repeated_observation(messages) is None


async def test_repeat_feedback_reaches_agent_after_native_failure_recovery(ws, monkeypatch):
    original = deep_runtime.BusinessBoundary.awrap_tool_call

    async def old_failure(self, request, handler):
        if request.tool_call["id"] == "calc-2":
            raise RuntimeError("REPEATED_ACTION_WITHOUT_PROGRESS")
        return await original(self, request, handler)

    def react(messages):
        system = "\n".join(b["text"] for m in messages if m.type == "system"
                           for b in m.content_blocks if b["type"] == "text")
        assert "last three successful calls to calculate" in system
        assert observation(messages, "calculate")["total"] == "1"
        return draft_call()

    actions = [AIMessage(content="", tool_calls=[call("calculate", {"terms": [["1"]]}, f"calc-{i}")])
               for i in range(3)]
    driver = Driver(coordinator=[*actions, react, final_receipt])
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", old_failure)
    assert (await run(ws, driver))["status"] == "failed"
    assert len(events(ws, "deep_tool_end")) == 2
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", original)
    resumed = Workspace(Store(ws.store.root))
    fresh = Driver(**driver.scripts)
    assert (await run(resumed, fresh))["status"] == "needs_attention"
    assert len(resumed.results()) == 1
    assert fresh.calls[0][:2] == ("coordinator", 3)
    assert len([e for e in events(ws, "deep_tool_end") if e["tool"] == "calculate"]) == 3
    assert events(ws, "deep_repetition_observed") == [{"role": "coordinator", "tool": "calculate"}]


async def test_repeated_submit_keeps_receipt_and_allows_progress(ws):
    def observe_receipt(messages):
        receipt = observation(messages, "submit_result")
        assert receipt["id"] == ws.results()[0]["id"]
        return AIMessage(content="Existing draft receipt recovered")

    driver = Driver(coordinator=[draft_call(), draft_call(), draft_call(), observe_receipt])
    assert (await run(ws, driver))["status"] == "needs_attention"
    assert len(ws.results()) == len(events(ws, "result_committed")) == 1
    assert len([e for e in events(ws, "deep_tool_end") if e["tool"] == "submit_result"]) == 3


async def test_root_draft_native_reviewer_delivery_without_mandatory_chain(ws, failure_stacks):
    driver = trunk_driver()
    status = await run(ws, driver)
    assert status["status"] == "reviewed_draft", (status, failure_stacks)
    assert [r["kind"] for r in ws.results()] == ["draft", "review"]
    draft, review = ws.results()
    assert review["target_id"] == draft["id"]
    assert (draft["owner"], review["owner"]) == ("writer", "reviewer")
    assert status["delivery"]["draft_id"] == draft["id"]
    starts = events(ws, "deep_tool_start")
    assert any(e["role"] == "coordinator" and e["tool"] == "task" for e in starts)
    assert any(e["role"] == "reviewer" and e["tool"] == "read_result" for e in starts)
    assert not any(role in {"knowledge", "writer", "text_tool"} for role, _, _ in driver.calls)
    assert (ws.store.root / "checkpoints.db").stat().st_size > 0
    assert not (await snapshot(ws, driver)).next


async def test_optional_calculator_and_actual_export_observations(ws, failure_stacks):
    def calculated(messages):
        value = observation(messages, "calculate")
        assert value["total"] == "1.50" and not value["rounded"]
        return draft_call()

    def preview(messages):
        return invoke("preview_report", draft_id=observation(messages, "submit_result")["id"])

    def inspected(messages):
        value = observation(messages, "preview_report")
        assert value["preview"]["docx"]["sha256"] == value["content"]["docx_sha256"]
        assert value["preview"]["render"]["visual_verification"] == "not_performed"
        assert "east path" in value["content"]["text"]
        return delegate_review(messages)

    driver = Driver(coordinator=[invoke("calculate", terms=[["50", "0.03"]]), calculated,
                                  preview, inspected, deliver, AIMessage(content="Delivered")],
                    reviewer=[read_delegated_draft, submit_review, final_receipt])
    status = await run(ws, driver)
    assert status["status"] == "reviewed_draft", (status, failure_stacks)
    for role in ("coordinator", "reviewer"):
        names = {schema["name"] for schema in driver.bindings[role][-1]}
        assert {"calculate", "inspect_source_page", "preview_report"} <= names
    assert len(ws.results()) == 2  # Tool inspection creates no semantic stage/results.


async def test_native_reviewer_can_use_exported_text_without_duplicate_read(ws, failure_stacks):
    def preview_target(messages):
        request = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        return invoke("preview_report", draft_id=json.loads(request.content)["draft_id"])

    def review_preview(messages):
        content = observation(messages, "preview_report")["content"]
        assert "east path" in content["text"]
        return invoke("submit_result", kind="review", title="Export review", body="Checked saved export text.",
                      source_ids=["source"], target_id=content["draft_id"], outcome="accepted")

    driver = trunk_driver()
    driver.scripts["reviewer"] = [preview_target, review_preview, final_receipt]
    status = await run(ws, driver)
    assert status["status"] == "reviewed_draft", (status, failure_stacks)
    assert not any(e["role"] == "reviewer" and e["tool"] == "read_result" for e in events(ws, "deep_tool_start"))
    schema = next(s for s in driver.bindings["reviewer"][-1] if s["name"] == "preview_report")
    assert "runtime" not in schema["parameters"]["properties"]


@pytest.mark.parametrize("role", ["coordinator", "writer"])
async def test_native_interrupt_rebuild_and_resume_without_recommitting(ws, failure_stacks, role):
    ask = invoke("ask_human", category="source_conflict", description="Confirm daytime scope",
                 source_ids=["source"])
    driver = Driver(coordinator=[draft_call(), ask, AIMessage(content="Human answer recorded")])
    if role == "writer":
        driver.scripts["coordinator"] = [
            invoke("task", subagent_type="writer", description="Save a draft, then ask about scope"),
            AIMessage(content="Human answer recorded")]
        driver.scripts["writer"] = [draft_call(), ask, AIMessage(content="Human answer recorded")]
    first = await run(ws, driver)
    assert first["status"] == "needs_human", (first, failure_stacks)
    saved_results = ws.results()
    pending = await snapshot(ws, driver)
    assert pending.next and pending.interrupts
    assert len(pending.interrupts) == 1
    issue_id = pending.interrupts[0].value["issue_id"]
    assert issue_id == first["issues"][0]["id"]
    assert len(events(ws, "result_committed")) == 1

    reopened = Workspace(Store(ws.store.root))
    fresh_driver = Driver(**driver.scripts)
    waiting = await run(reopened, fresh_driver)
    assert waiting["status"] == "needs_human"
    assert not fresh_driver.calls, "Unanswered interrupts must not make another model call"
    reopened.decide_issue(issue_id, "Operator confirms daytime scope", resolved=True)
    resumed = await run(reopened, fresh_driver)
    assert resumed["status"] == "needs_attention", (resumed, failure_stacks)
    complete = await snapshot(reopened, fresh_driver)
    assert not complete.next and not complete.interrupts
    assert reopened.results() == saved_results
    assert len(events(reopened, "result_committed")) == 1
    assert len(events(reopened, "issue_recorded")) == 1
    assert len(events(reopened, "human_decision")) == 1
    assert len([e for e in events(reopened, "deep_tool_start") if e["tool"] == "submit_result"]) == 1
    assert events(reopened, "deep_run_started")[-1]["resume"] is True
    replies = [m for r, _, messages in fresh_driver.calls if r == role for m in messages
               if isinstance(m, ToolMessage) and m.name == "ask_human"]
    assert replies and "Operator confirms daytime scope" in replies[-1].content


class ForbiddenKnowledge:
    """Only a write tripwire; no claims about Neo4j or vector quality."""

    def __init__(self):
        self.writes = []

    def put(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("Downstream role reached shared knowledge mutation")


@pytest.mark.parametrize("role,foreign_kind", [("writer", "materials"), ("reviewer", "draft")])
async def test_child_permissions_are_enforced_in_native_tool_calls(ws, failure_stacks, role, foreign_kind):
    forbidden = [call("knowledge_put", {"title": "Unauthorized", "body": "Must not persist",
                                        "source_ids": ["source"]}),
                 call("submit_result", {"kind": foreign_kind, "title": "Wrong owner", "body": "Blocked",
                                         "source_ids": ["source"], "input_ids": []}),
                 call("task", {"subagent_type": "knowledge", "description": "Nested delegation"}),
                 call("execute", {"command": "echo forbidden"})]
    driver = Driver(coordinator=[invoke("task", subagent_type=role, description="Boundary probe"),
                                 AIMessage(content="Checked")],
                    **{role: [AIMessage(content="", tool_calls=forbidden), AIMessage(content="Checked")]})
    knowledge = ForbiddenKnowledge()
    status = await asyncio.wait_for(deep_runtime.run_report(ws, driver, knowledge=knowledge), 30)
    assert status["status"] == "needs_attention", (status, failure_stacks)
    schemas = driver.bindings[role][0]
    names = {schema["name"] for schema in schemas}
    assert {"knowledge_search", "knowledge_read", "knowledge_traverse"} <= names
    assert not names & {"knowledge_put", "knowledge_link", "knowledge_retract", "task", "execute"}
    submit_schema = next(s for s in schemas if s["name"] == "submit_result")
    assert not {"actor", "owner", "task_id", "runtime"} & submit_schema["parameters"]["properties"].keys()
    messages = next(messages for r, step, messages in driver.calls if r == role and step == 1)
    responses = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    assert set(responses) == {c["id"] for c in forbidden}
    assert responses["submit_result"].status == "error"
    assert "kind: Input should be" in responses["submit_result"].content
    if role == "writer":
        assert not {"outcome", "target_id"} & submit_schema["parameters"]["properties"].keys()
    else:
        assert {"outcome", "target_id"} <= set(submit_schema["parameters"]["required"])
    for name in ("knowledge_put", "task", "execute"):
        assert responses[name].status == "error", responses[name]
    assert not knowledge.writes and not ws.results() and not ws.tasks()


async def test_general_purpose_subagent_unavailable(ws, failure_stacks):
    driver = Driver(coordinator=[invoke("task", subagent_type="general-purpose", description="Do anything"),
                                 AIMessage(content="Rejected")])
    status = await run(ws, driver)
    assert status["status"] == "needs_attention", (status, failure_stacks)
    messages = driver.calls[-1][2]
    response = next(m for m in messages if isinstance(m, ToolMessage) and m.name == "task")
    assert "general-purpose" in response.content and "does not exist" in response.content.lower()
    assert all(role == "coordinator" for role, _, _ in driver.calls)
    assert "execute" not in {s["name"] for s in driver.bindings["coordinator"][0]}


async def test_multiple_native_tasks_are_serialized_by_middleware(ws):
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[
        call("task", {"subagent_type": "writer", "description": "Independent probe A"}, "task-a"),
        call("task", {"subagent_type": "reviewer", "description": "Independent probe B"}, "task-b")]),
        AIMessage(content="Both finished")],
        writer=[AIMessage(content="Writer finished")], reviewer=[AIMessage(content="Reviewer finished")])
    driver.delay_children = True
    # Deliberately permit graph concurrency: the application's middleware must serialize.
    async with deep_runtime.project_agent(ws, driver) as agent:
        result = await asyncio.wait_for(agent.ainvoke(
            {"messages": [("user", "Run both probes")]},
            {"configurable": {"thread_id": "serial-probe"}, "max_concurrency": 8}), 30)
    assert result["messages"][-1].content == "Both finished"
    assert driver.max_active_children == 1
    spans = [(e["kind"], e["data"]["tool_call_id"]) for e in ws.store.events()
             if e["kind"] in {"deep_tool_start", "deep_tool_end"}
             and e["data"]["role"] == "coordinator" and e["data"]["tool"] == "task"]
    assert len(spans) == 4
    assert [kind for kind, _ in spans] == ["deep_tool_start", "deep_tool_end"] * 2
    assert spans[0][1] == spans[1][1] and spans[2][1] == spans[3][1]
    assert {spans[0][1], spans[2][1]} == {"task-a", "task-b"}


@pytest.mark.parametrize("failed_role,failed_step", [("coordinator", 2), ("reviewer", 1)])
async def test_transient_model_failure_resumes_checkpoint_without_repeating_submit(
        ws, failure_stacks, failed_role, failed_step):
    driver = trunk_driver()
    driver.fail_once = (failed_role, failed_step)
    failed = await run(ws, driver)
    assert failed["status"] == "failed", (failed, failure_stacks)
    assert failed["last_error"]["type"] == "ReadTimeout"
    assert driver.failed
    saved = ws.results()
    assert len(saved) == 1 and saved[0]["kind"] == "draft"
    pending = await snapshot(ws, driver)
    assert pending.next and not pending.interrupts
    fresh = trunk_driver()
    reopened = Workspace(Store(ws.store.root))
    resumed = await run(reopened, fresh)
    assert resumed["status"] == "reviewed_draft", (resumed, failure_stacks)
    assert fresh.calls[0][:2] == (failed_role, failed_step)
    assert reopened.results()[0] == saved[0]
    commits = Counter(e["kind"] for e in events(reopened, "result_committed"))
    assert commits == {"draft": 1, "review": 1}
    submits = [e for e in events(reopened, "deep_tool_start")
               if e["role"] == "coordinator" and e["tool"] == "submit_result"]
    assert len(submits) == 1
    assert events(reopened, "deep_run_started")[-1] == {"resume": True, "native_checkpoint": True}


async def test_unknown_submit_outcome_replays_receipt_without_duplicate_commit(ws, monkeypatch, failure_stacks):
    original = ws.submit
    injected = False

    def commit_then_lose_response(*args, **kwargs):
        nonlocal injected
        receipt = original(*args, **kwargs)
        if not injected:
            injected = True
            raise httpx.ReadTimeout("offline response lost after durable commit")
        return receipt

    monkeypatch.setattr(ws, "submit", commit_then_lose_response)
    driver = Driver(coordinator=[draft_call(), final_receipt])
    failed = await run(ws, driver)
    assert failed["status"] == "failed", (failed, failure_stacks)
    assert failed["last_error"]["type"] == "ReadTimeout"
    committed = ws.results()
    assert len(committed) == len(events(ws, "result_committed")) == 1
    assert (await snapshot(ws, driver)).next
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**driver.scripts)
    resumed = await run(reopened, fresh)
    assert resumed["status"] == "needs_attention", (resumed, failure_stacks)
    assert reopened.results() == committed
    assert len(reopened.tasks()) == len(events(reopened, "result_committed")) == 1
    assert observation(fresh.calls[0][2], "submit_result")["id"] == committed[0]["id"]
    assert len([e for e in events(reopened, "deep_tool_start") if e["tool"] == "submit_result"]) == 2
    assert not (await snapshot(reopened, fresh)).next


async def test_checkpoint_with_old_draft_summary_field_resumes_as_draft_only(ws, monkeypatch):
    original = deep_runtime.BusinessBoundary.awrap_tool_call

    async def stop_before_tool(self, request, handler):
        if request.tool_call["name"] == "submit_result":
            raise RuntimeError("TEST_STOP_BEFORE_OLD_TOOL_CALL")
        return await original(self, request, handler)

    legacy = invoke("submit_result", kind="draft", title="Saved old request", body="Supplied daytime access",
                    source_ids=["source"], input_ids=[], outcome="A prose description, not an approval", target_id="")
    driver = Driver(coordinator=[legacy, final_receipt])
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", stop_before_tool)
    assert (await run(ws, driver))["status"] == "failed"
    pending = await snapshot(ws, driver)
    assert pending.next and not ws.results()
    old_call = pending.values["messages"][-1].tool_calls[0]
    assert old_call["args"]["outcome"] == "A prose description, not an approval"
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", original)
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**driver.scripts)
    assert (await run(reopened, fresh))["status"] == "needs_attention"
    result, = reopened.results()
    assert result["kind"] == "draft" and result["owner"] == "writer"
    assert result["outcome"] == result["target_id"] == ""
    assert fresh.calls[0][:2] == ("coordinator", 1)
    assert len(events(reopened, "result_committed")) == 1


async def test_reviewer_read_survives_child_interrupt_and_graph_rebuild(ws, failure_stacks):
    driver = trunk_driver()
    driver.scripts["reviewer"].insert(1, invoke(
        "ask_human", category="source_conflict", description="Confirm scope before review",
        source_ids=["source"]))
    paused = await run(ws, driver)
    assert paused["status"] == "needs_human", (paused, failure_stacks)
    before = ws.results()
    assert len(before) == 1
    pending = await snapshot(ws, driver)
    assert pending.next and pending.interrupts
    reopened = Workspace(Store(ws.store.root))
    reopened.decide_issue(paused["issues"][0]["id"], "Daytime scope confirmed", resolved=True)
    fresh = Driver(**driver.scripts)
    resumed = await run(reopened, fresh)
    assert resumed["status"] == "reviewed_draft", (resumed, failure_stacks)
    draft, review = reopened.results()
    assert draft == before[0]
    assert review["target_id"] == draft["id"]
    assert draft["id"] in review["observed_result_ids"]
    assert Counter(e["kind"] for e in events(reopened, "result_committed")) == {"draft": 1, "review": 1}
    assert len([e for e in events(reopened, "deep_tool_start")
                if e["role"] == "reviewer" and e["tool"] == "read_result"]) == 1
    assert not (await snapshot(reopened, fresh)).next


@pytest.mark.parametrize("same_turn", [False, True])
async def test_separate_reviewer_delegations_cannot_share_read_observations(ws, failure_stacks, same_turn):
    def reviewer_request(messages):
        request = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        data = json.loads(request.content)
        if data.get("mode") == "submit_without_read":
            return invoke("submit_result", kind="review", title="Unread review", body="Must be rejected",
                          source_ids=[], input_ids=[data["draft_id"]], target_id=data["draft_id"],
                          outcome="accepted")
        return invoke("read_result", result_id=data["draft_id"])

    def second_review(messages):
        draft = observation(messages, "submit_result")
        return invoke("task", subagent_type="reviewer", description=json.dumps(
            {"draft_id": draft["id"], "mode": "submit_without_read"}))

    driver = Driver(coordinator=[draft_call(), delegate_review, second_review, AIMessage(content="Checked")],
                    reviewer=[reviewer_request, AIMessage(content="Probe finished")])
    if same_turn:
        def both_reviews(messages):
            first = delegate_review(messages).tool_calls[0]
            second = second_review(messages).tool_calls[0]
            return AIMessage(content="", tool_calls=[{**first, "id": "read-context"},
                                                     {**second, "id": "unread-context"}])

        driver.scripts["coordinator"] = [draft_call(), both_reviews, AIMessage(content="Checked")]
    status = await run(ws, driver)
    assert status["status"] == "needs_attention", (status, failure_stacks)
    assert [r["kind"] for r in ws.results()] == ["draft"]
    responses = [m for role, _, messages in driver.calls if role == "reviewer" for m in messages
                 if isinstance(m, ToolMessage) and m.name == "submit_result"]
    assert len(responses) == 1
    assert json.loads(responses[0].content)["error"]["message"] == "REVIEW_TARGET_NOT_OBSERVED"
    assert len([e for e in events(ws, "deep_tool_start") if e["tool"] == "task"]) == 2
