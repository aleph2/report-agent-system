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
    store.set("acceptance_mode", "legacy")  # Preserve the historical delegated harness scenarios.
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
    if kind in {"deep_tool_start", "deep_tool_end", "deep_tool_rejected"}:
        # Historical assertions now inspect native evidence, not duplicate DB logs.
        from langgraph.checkpoint.sqlite import SqliteSaver
        from report_agent.native_trace import checkpoint_messages, checkpoint_agent
        path = ws.store.root / "checkpoints.db"
        if not path.exists():
            return []
        result, seen = [], set()
        with SqliteSaver.from_conn_string(str(path)) as saver:
            for row in reversed(list(saver.list(None))):
                namespace = row.config["configurable"].get("checkpoint_ns", "")
                role = (checkpoint_agent(row) or "").removeprefix("report_")
                for _, message in checkpoint_messages(row):
                    key = (namespace, message.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    if kind == "deep_tool_start" and isinstance(message, AIMessage):
                        result.extend({"role": role, "tool": c["name"], "arguments": c["args"],
                                       "tool_call_id": c["id"]} for c in message.tool_calls)
                    elif kind == "deep_tool_end" and isinstance(message, ToolMessage):
                        result.append({"role": role, "tool": message.name, "tool_call_id": message.tool_call_id})
                    elif kind == "deep_tool_rejected" and isinstance(message, ToolMessage) and message.status == "error":
                        error = json.loads(message.content).get("error", {})
                        result.append({"role": role, "tool": message.name, "tool_call_id": message.tool_call_id,
                                       **(error if isinstance(error, dict) else {})})
        return result
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


async def test_native_working_notes_and_todos_survive_reopen(tmp_path):
    """Protocol evidence only: the scripted model does not prove autonomous progress."""
    from test_task_supervision import ws as native_fixture
    ws = native_fixture.__wrapped__(tmp_path)
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
    result = await run(ws, driver)
    assert result["last_error"] is None, result
    reopened = Workspace(Store(ws.store.root))
    saved = await snapshot(reopened, driver)
    assert saved.values["todos"] == todos
    assert "Total: 14.0" in saved.values["files"]["/working-costs.md"]["content"]
    assert observation(saved.values["messages"], "calculate")["total"] == "14.0"
    assert not reopened.results()  # Scratch notes are not published report results.
    assert sum(e["tool"] == "calculate" for e in events(ws, "deep_tool_start")) == 1
    system = "\n".join(block["text"] for m in driver.calls[0][2] if m.type == "system"
                       for block in m.content_blocks if block["type"] == "text")
    from report_agent.hierarchical_tools import role_prompt
    assert role_prompt("coordinator").strip() in system


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


async def test_repeat_feedback_reaches_agent_after_native_failure_recovery(tmp_path, monkeypatch):
    from test_task_supervision import ws as native_fixture
    from report_agent.content_store import ContentStore
    ws = native_fixture.__wrapped__(tmp_path)
    original = deep_runtime.BusinessBoundary.awrap_tool_call

    async def old_failure(self, request, handler):
        if request.tool_call["id"] == "calc-2":
            raise RuntimeError("REPEATED_ACTION_WITHOUT_PROGRESS")
        return await original(self, request, handler)

    def react(messages):
        notice, = [json.loads(b['text'])['execution_observation'] for m in messages if m.type == 'system'
                   for b in m.content_blocks if b.get('text', '').startswith('{"execution_observation":')]
        assert notice == {'tool': 'calculate', 'identical_successful_exchanges': 3,
                          'semantic_progress_assessed': False}
        assert observation(messages, "calculate")["total"] == "1"
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer",
            "description": "Save one synthetic structural node after observing repeated arithmetic"}, "progress-after-repetition")])

    actions = [AIMessage(content="", tool_calls=[call("calculate", {"terms": [["1"]]}, f"calc-{i}")])
               for i in range(3)]
    driver = Driver(coordinator=[*actions, react, AIMessage(content="Observed repetition and chose useful next work.")],
        writer=[invoke("commit_objects", operation_id="structure-after-repeat-advisory", objects=[
            {"client_key": "progress", "type": "ContentNode", "payload": {"kind": "chapter",
             "body": {"text": "Synthetic structural progress after arithmetic"}, "qualifiers": {}, "claim_kind": "structure"}}]),
            AIMessage(content="Saved structure; no report-quality judgment.")])
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", old_failure)
    assert (await run(ws, driver))["status"] == "failed"
    assert len(events(ws, "deep_tool_end")) == 2
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", original)
    resumed = Workspace(Store(ws.store.root))
    fresh = Driver(**driver.scripts)
    result = await run(resumed, fresh)
    assert result["last_error"] is None, result
    cs = ContentStore(resumed.store)
    nodes, tasks = cs.list_objects("ContentNode"), cs.list_objects("DelegatedTask")
    assert len(nodes) == len(tasks) == 1
    assert nodes[0]["owner_id"] == "content:writer:" + tasks[0]["ref"]["id"]
    assert nodes[0]["task_id"] == tasks[0]["ref"]["id"]
    assert nodes[0]["ref"]["version"] == 1
    assert not cs.list_objects("ReviewRecord") and not resumed.results()
    complete = await snapshot(resumed, fresh)
    assert not complete.next and not complete.interrupts
    assert fresh.calls[0][:2] == ("coordinator", 3)
    assert len([e for e in events(ws, "deep_tool_end") if e["tool"] == "calculate"]) == 3
    assert events(ws, "deep_repetition_observed") == [{"role": "coordinator", "tool": "calculate"}]


async def test_repeated_submit_keeps_receipt_and_allows_progress(tmp_path):
    from test_task_supervision import ws as native_fixture
    from test_text_work import content, writer_call
    from report_agent.content_store import ContentStore
    ws = native_fixture.__wrapped__(tmp_path)
    saved = []
    def adopt(messages, identity):
        work = observation(messages, "process_report_content")
        return AIMessage(content="", tool_calls=[call("save_text_node", {
            "operation_id": "adopt-identical", "text_work_id": work["text_work_id"]}, identity)])
    def observe_receipt(messages):
        returned = [m for m in messages if isinstance(m, ToolMessage) and m.name == "save_text_node"]
        assert [m.tool_call_id for m in returned] == ["adopt-1", "adopt-2", "adopt-3"]
        assert all(m.status == "success" for m in returned)
        saved.extend(json.loads(m.content)["result"]["refs"]["text"] for m in returned)
        assert saved[0] == saved[1] == saved[2]
        return AIMessage(content="Exact saved node reused; no review verdict.")
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[writer_call()]),
        AIMessage(content="Saved draft remains unreviewed.")], writer=[
        invoke("process_report_content", operation_id="produce-once", objective="Describe the selected rule",
               object_type="ContentNode", source_selections=[{"source_id": "s"}]),
        lambda m: adopt(m, "adopt-1"), lambda m: adopt(m, "adopt-2"),
        lambda m: adopt(m, "adopt-3"), observe_receipt],
        text_tool=[AIMessage(content=json.dumps(content()))])
    result = await run(ws, driver)
    assert result["last_error"] is None, result
    nodes = ContentStore(ws.store).list_objects("ContentNode")
    assert len(nodes) == 1 and nodes[0]["ref"] == saved[0] and saved[0]["version"] == 1
    assert nodes[0]["payload"] == content()
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    with ws.store.connect() as db:
        operations = db.execute("SELECT actor_id FROM content_operations WHERE operation_id=?",
                                ("adopt-identical",)).fetchall()
    assert operations == [(nodes[0]["owner_id"],)]


async def test_root_draft_native_reviewer_delivery_without_mandatory_chain(tmp_path, monkeypatch, failure_stacks):
    # Current interface migration: actual owner Writer and independent text
    # producer/checker replace the retired direct-root author/grader aliases.
    from hierarchical_fixtures import current_native_access_review
    from test_acceptance_runtime import ws as access_fixture, native_access_ws
    base = access_fixture.__wrapped__(tmp_path / "commission", monkeypatch)
    current = native_access_ws.__wrapped__(tmp_path, base)
    cs, driver, captured, body, result = await current_native_access_review(current)
    assert result["last_error"] is None, (result, failure_stacks)
    node, = cs.list_objects("ContentNode")
    review, = cs.list_objects("ReviewRecord")
    assert node["payload"] == body and node["owner_id"].startswith("content:writer:")
    assert review["owner_id"].startswith("content:reviewer:") and review["owner_id"] != node["owner_id"]
    assert review["task_id"] != node["task_id"]
    assert review["payload"]["items"][0]["target_ref"] == node["ref"] == captured["node"]
    assert review["payload"]["items"][0]["verdict"] == "satisfied"
    assert review["payload"]["snapshot_ref"] == captured["snapshot"]
    assert cs.read(captured["snapshot"])["payload"]["root_ref"] == node["ref"]
    selected = current.store.get("content_delivery")
    assert selected["snapshot_ref"] == captured["snapshot"] and selected["export_ref"] == captured["export"]
    assert cs.read(selected["export_ref"])["payload"]["snapshot_ref"] == selected["snapshot_ref"]
    starts = events(current, "deep_tool_start")
    assert any(e["role"] == "coordinator" and e["tool"] == "task" for e in starts)
    assert any(e["role"] == "reviewer" and e["tool"] == "read_content_export" for e in starts)
    roles = {role for role, _, _ in driver.calls}
    assert {"coordinator", "writer", "reviewer", "text_tool"} <= roles
    assert not roles.intersection({"knowledge", "purpose", "plan", "planner", "materials", "layout"})
    assert (current.store.root / "checkpoints.db").stat().st_size > 0
    final = await snapshot(current, driver)
    assert not final.next and not final.interrupts


async def test_optional_calculator_and_actual_export_observations(tmp_path, failure_stacks):
    # Explicit migration: optional arithmetic and actual OOXML observation,
    # without the retired flat-draft/automatic-review workflow.
    import hashlib
    from report_agent.content_store import ContentStore
    from report_agent.content_export import _bytes
    current_store = Store(tmp_path)
    current_store.initialize({"goal": "Compile the supplied access statement.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "sources": [{"id": "s", "content": "Use the east path during daytime.", "coverage": "complete"}]})
    current = Workspace(current_store)
    cs, observed = ContentStore(current_store), {}
    body = {"kind": "block", "body": {"text": "Use the east path during daytime."},
            "qualifiers": {}, "claim_kind": "fact"}
    def calculated(messages):
        value = observation(messages, "calculate")
        assert value["total"] == "1.50" and value["rounded"] is False
        return invoke("import_source_versions", operation_id="calculator-inputs", source_ids=["s"])
    def adopt(messages):
        work = observation(messages, "process_report_content")
        return invoke("commit_objects", operation_id="calculator-adopt", objects=[
            {"client_key": "root", "type": "ContentNode", "payload": {"kind": "report",
                "body": {"text": "Synthetic access report"}, "qualifiers": {}, "claim_kind": "structure"}},
            {"client_key": "body", "type": "ContentNode", "text_work_id": work["text_work_id"]},
            {"client_key": "edge", "type": "Relation", "payload": {"subject_ref": {"client_key": "root"},
                "object_ref": {"client_key": "body"}, "predicate": "contains", "position": 0,
                "provenance_kind": "adopted_during_generation"}}])
    def returned(messages):
        return AIMessage(content=json.dumps({"saved_refs": observation(messages, "commit_objects")["result"]["refs"]}))
    def freeze(messages):
        refs = observation(messages, "task")["saved_refs"]
        inputs = observation(messages, "import_source_versions")["result"]
        return invoke("freeze_snapshot", operation_id="calculator-snapshot", root_ref=refs["root"],
            refs=[*refs.values(), inputs["requirement_ref"], *inputs["source_refs"]])
    def export(messages):
        return invoke("export_content_snapshot", operation_id="calculator-word",
            snapshot_ref=observation(messages, "freeze_snapshot")["result"]["snapshot_ref"])
    def read_actual(messages):
        observed["export_ref"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
        return invoke("read_content_export", export_ref=observed["export_ref"])
    def inspected(messages):
        receipt = observation(messages, "read_content_export")
        value = receipt["result"]
        artifact = cs.read(observed["export_ref"])["payload"]
        data = _bytes(current_store, artifact["file_ref"], artifact["file_digest"])
        assert value["export_ref"] == observed["export_ref"]
        assert value["file_digest"] == artifact["file_digest"] == hashlib.sha256(data).hexdigest()
        assert body["body"]["text"] in value["text"]
        assert value["limitation"] == "Actual OOXML content; not visual observation."
        with current_store.connect() as db:
            row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (receipt["receipt_id"],)).fetchone()
        from report_agent.hierarchical_tools import actor_for
        assert row[0] == actor_for("coordinator").id and json.loads(row[1]) == value
        observed["receipt"] = receipt
        return AIMessage(content="Actual file read; no visual or semantic acceptance claimed.")
    driver = Driver(coordinator=[invoke("calculate", terms=[["50", "0.03"]]), calculated,
        invoke("task", subagent_type="writer", description="Compile only the supplied source statement."),
        freeze, export, read_actual, inspected],
        writer=[invoke("process_report_content", operation_id="calculator-produce", objective="Compile supplied daytime east-path restriction.",
            object_type="ContentNode", source_selections=[{"source_id": "s"}]), adopt, returned],
        text_tool=[AIMessage(content=json.dumps(body))])
    status = await run(current, driver)
    assert status["last_error"] is None, (status, failure_stacks)
    assert observed["receipt"]["ok"] is True
    assert not cs.list_objects("ReviewRecord") and not cs.list_objects("RenderArtifact")
    assert len(cs.list_objects("ExportArtifact")) == 1
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    names = {schema["name"] for schema in driver.bindings["coordinator"][-1]}
    assert {"calculate", "read_content_export", "export_content_snapshot"} <= names
    assert status["status"] != "reviewed_draft"


async def test_native_reviewer_can_use_exported_text_without_duplicate_read(tmp_path):
    # Explicit current artifact checker route; no retired grader/global pass claim.
    from hierarchical_fixtures import current_native_export_read_review
    _, _, seen, result = await current_native_export_read_review(tmp_path)
    assert result["last_error"] is None and seen["packet"]


@pytest.mark.parametrize("role", ["coordinator", "writer"])
async def test_native_interrupt_rebuild_and_resume_without_recommitting(tmp_path, failure_stacks, role):
    from copy import deepcopy
    from langgraph.types import interrupt
    from report_agent.content_store import ContentStore
    from report_agent.task_context import exact_task_context
    from test_task_supervision import ws as native_fixture
    ws = native_fixture.__wrapped__(tmp_path)
    cs = ContentStore(ws.store)
    payload = {"kind": "chapter", "body": {"text": "Synthetic saved structure"},
        "qualifiers": {}, "claim_kind": "structure"}
    save = invoke("commit_objects", operation_id="before-human", objects=[
        {"client_key": "section", "type": "ContentNode", "payload": payload}])
    saved, captures = {}, []
    # Writer has no ask_human permission. Its variant deliberately uses a real
    # synthetic native child checkpoint, not a fabricated Writer tool call.
    issue = ws.issue("requirement", "Synthetic child checkpoint: confirm scope", []) if role == "writer" else None
    def writer_after_save(messages):
        returned = observation(messages, "commit_objects")
        assert returned["ok"], returned
        ref = returned["result"]["refs"]["section"]
        saved.setdefault("node", deepcopy(cs.read(ref)))
        assert cs.read(ref) == saved["node"]
        if role == "writer":
            captures.append(deepcopy(exact_task_context(ws, "writer")))
            answer = interrupt({"issue_id": issue["id"], "kind": "synthetic_test_checkpoint"})
            assert answer == "Operator confirms daytime scope"
        return AIMessage(content="Saved structure retained; no second commit.")
    task = invoke("task", subagent_type="writer", description="Save one synthetic structural node before scope clarification")
    ask = invoke("ask_human", category="source_conflict", description="Confirm daytime scope", source_ids=["s"], pause=True)
    scripts = {"coordinator": [task, ask, AIMessage(content="Human answer recorded")],
        "writer": [save, writer_after_save]}
    if role == "writer":
        scripts["coordinator"] = [task, AIMessage(content="Human answer recorded")]
    driver = Driver(**scripts)
    first = await run(ws, driver)
    assert first["status"] == "needs_human", (first, failure_stacks)
    pending = await snapshot(ws, driver)
    assert pending.next and len(pending.interrupts) == 1
    issue_id = pending.interrupts[0].value["issue_id"]
    assert issue_id == first["issues"][0]["id"]
    retained = deepcopy(cs.list_objects("ContentNode"))
    tasks = deepcopy(cs.list_objects("DelegatedTask"))
    assert len(retained) == len(tasks) == 1
    assert retained[0] == saved["node"] and retained[0]["ref"]["version"] == 1
    assert sum(e["tool"] == "commit_objects" for e in events(ws, "deep_tool_start")) == 1
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**scripts)
    waiting = await run(reopened, fresh)
    assert waiting["status"] == "needs_human" and not fresh.calls
    reopened.decide_issue(issue_id, "Operator confirms daytime scope", resolved=True)
    resumed = await run(reopened, fresh)
    assert resumed["last_error"] is None, (resumed, failure_stacks)
    complete = await snapshot(reopened, fresh)
    assert not complete.next and not complete.interrupts
    assert ContentStore(reopened.store).list_objects("ContentNode") == retained
    assert ContentStore(reopened.store).list_objects("DelegatedTask") == tasks
    assert len(events(reopened, "issue_recorded")) == len(events(reopened, "human_decision")) == 1
    assert sum(e["tool"] == "commit_objects" for e in events(reopened, "deep_tool_start")) == 1
    assert events(reopened, "deep_run_started")[-1]["resume"] is True
    if role == "coordinator":
        replies = [m for r, _, messages in fresh.calls if r == role for m in messages
            if isinstance(m, ToolMessage) and m.name == "ask_human"]
        assert replies and "Operator confirms daytime scope" in replies[-1].content
    else:
        assert len(captures) == 2
        for key in ("actor_id", "assignment", "current_invocation"):
            assert captures[0][key] == captures[1][key]
        assert all(t["name"] != "ask_human" for bound in fresh.bindings["writer"] for t in bound)
    assert not reopened.results()  # Native typed save replaces retired flat submit_result.


class ForbiddenKnowledge:
    """Only a write tripwire; no claims about Neo4j or vector quality."""

    def __init__(self):
        self.writes = []

    def put(self, *args, **kwargs):
        self.writes.append((args, kwargs))
        raise AssertionError("Downstream role reached shared knowledge mutation")


@pytest.mark.parametrize("role,foreign_kind", [("writer", "materials"), ("reviewer", "draft")])
async def test_child_permissions_are_enforced_in_native_tool_calls(tmp_path, failure_stacks, role, foreign_kind):
    from test_task_supervision import ws as native_fixture
    from test_hierarchical_content import seed
    # Resolve the current fixture's plain builder without changing the historical
    # module fixture used by unrelated storage/compatibility scenarios.
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, review_snapshot, _ = seed(ws)
    foreign = cs.read(refs["root"])
    before_objects = cs.list_objects()
    unauthorized_update = call("commit_objects", {"operation_id": "foreign-update", "objects": [{
        "client_key": "foreign", "type": "ContentNode", "previous_ref": refs["root"],
        "payload": {"kind": "report", "body": {"text": "Unauthorized heading"},
                    "claim_kind": "structure", "qualifiers": {}}}]})
    forbidden = [call("knowledge_put", {"title": "Unauthorized", "body": "Must not persist",
                                        "source_ids": ["s"]}), unauthorized_update,
                 call("task", {"subagent_type": "knowledge", "description": "Nested delegation"}),
                 call("execute", {"command": "echo forbidden"})]
    if role == "reviewer":
        from test_bounded_review import review_call
        assignment = AIMessage(content="", tool_calls=[review_call(review_snapshot, refs)])
    else:
        assignment = invoke("task", subagent_type=role, description="Boundary probe")
    driver = Driver(coordinator=[assignment,
                                 AIMessage(content="Checked")],
                    **{role: [AIMessage(content="", tool_calls=forbidden), AIMessage(content="Checked")]})
    knowledge = ForbiddenKnowledge()
    status = await asyncio.wait_for(deep_runtime.run_report(ws, driver, knowledge=knowledge), 30)
    assert status["last_error"] is None, (status, failure_stacks)
    schemas = driver.bindings[role][0]
    names = {schema["name"] for schema in schemas}
    assert not names & {"knowledge_put", "knowledge_link", "knowledge_retract", "task", "execute"}
    messages = next(messages for r, step, messages in driver.calls if r == role and step == 1)
    responses = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    assert set(responses) == {c["id"] for c in forbidden}
    assert responses["commit_objects"].status == "error"
    if role == "writer":
        commit_schema = next(s for s in schemas if s["name"] == "commit_objects")
        assert not {"actor", "owner", "task_id", "runtime"} & commit_schema["parameters"]["properties"].keys()
        assert json.loads(responses["commit_objects"].content)["message"] == "FORBIDDEN: object owner"
    else:
        assert "commit_objects" not in names
        assert "not a valid tool" in responses["commit_objects"].content
    for name in ("knowledge_put", "task", "execute"):
        assert responses[name].status == "error", responses[name]
    assert not knowledge.writes and not ws.results()
    assert cs.read(refs["root"]) == foreign
    assert cs.list_objects("ContentNode") == [o for o in before_objects if o["ref"]["type"] == "ContentNode"]
    assert not any(o["payload"].get("body", {}).get("text") == "Unauthorized heading" for o in cs.list_objects("ContentNode"))


async def test_general_purpose_subagent_unavailable(tmp_path, failure_stacks):
    from test_task_supervision import ws as native_fixture
    ws = native_fixture.__wrapped__(tmp_path)
    driver = Driver(coordinator=[invoke("task", subagent_type="general-purpose", description="Do anything"),
                                 AIMessage(content="Rejected")])
    status = await run(ws, driver)
    assert status["last_error"] is None, (status, failure_stacks)
    messages = driver.calls[-1][2]
    response = next(m for m in messages if isinstance(m, ToolMessage) and m.name == "task")
    assert response.status == "error"
    assert json.loads(response.content)["code"] == "INVALID_CONTENT_DELEGATION"
    assert all(role == "coordinator" for role, _, _ in driver.calls)
    assert "execute" not in {s["name"] for s in driver.bindings["coordinator"][0]}
    from report_agent.content_store import ContentStore
    assert not ContentStore(ws.store).list_objects("DelegatedTask")


async def test_multiple_native_tasks_are_serialized_by_middleware(tmp_path):
    from test_task_supervision import ws as native_fixture
    from test_bounded_review import review_call
    from test_hierarchical_content import seed
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, snapshot_ref, _ = seed(ws)  # Static protocol material, not generated report quality.
    original_nodes = cs.list_objects("ContentNode")
    review = review_call(snapshot_ref, refs, id="task-b")
    review["args"].pop("supervision_plugin", None)
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[
        call("task", {"subagent_type": "writer", "description": "Independent probe A"}, "task-a"),
        review]),
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
    for kind in ("deep_tool_start", "deep_tool_end"):
        assert {e["tool_call_id"] for e in events(ws, kind)
                if e["role"] == "coordinator" and e["tool"] == "task"} == {"task-a", "task-b"}

    assert sum(role == "writer" for role, _, _ in driver.calls) == 1
    assert sum(role == "reviewer" for role, _, _ in driver.calls) == 1
    assert len(cs.list_objects("DelegatedTask")) == 2
    assert not cs.list_objects("ReviewRecord")
    assert cs.list_objects("ContentNode") == original_nodes


@pytest.mark.parametrize("failed_role,failed_step", [("coordinator", 2), ("reviewer", 1)])
async def test_transient_model_failure_resumes_checkpoint_without_repeating_submit(
        tmp_path, failure_stacks, failed_role, failed_step):
    from copy import deepcopy
    from report_agent.content_store import ContentStore
    from test_task_supervision import ws as native_fixture
    from test_bounded_review import review_call
    from test_hierarchical_content import seed
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, snapshot_ref, _ = seed(ws)
    source = next(r for r in cs.read(snapshot_ref)["payload"]["refs"] if r["type"] == "SourceArtifact")
    assigned = review_call(snapshot_ref, refs, reads=[source])
    assigned["args"].pop("supervision_plugin", None)
    payload = {"kind": "chapter", "body": {"text": "Durable synthetic structure before failure"},
        "qualifiers": {}, "claim_kind": "structure"}
    injected = []
    def reviewer_next(messages):
        assert observation(messages, "read_context")["result"]["objects"] == [cs.read(refs["claim"])]
        if failed_role == "reviewer" and not injected:
            injected.append(True)
            # Explicit fault-fixture migration: delegated HTTP failures are
            # intentionally semantic feedback now; ordinary model faults remain
            # graph failures. This does not claim HTTP and RuntimeError equivalence.
            raise RuntimeError("offline reviewer model checkpoint failure")
        return invoke("perform_assigned_review", operation_id="after-model-recovery", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[])
    response = {"items": [{"scope_id": "rule-comparison", "checked_requirement_indexes": [0],
        "execution_state": "completed", "verdict": "not_satisfied",
        "observations": [{"evidence_index": 0, "locator": "claim", "observation": "Synthetic claim."},
            {"evidence_index": 1, "locator": "source", "observation": "Synthetic rule."}],
        "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": "Synthetic local finding.",
            "observation_indexes": [0, 1], "remaining": ""}],
        "coverage": {"checked": ["Synthetic comparison"], "unchecked": [], "blocked": [], "basis": "Supplied literal fixture."},
        "reason": "Protocol negative, not engineering validation.", "findings": []}]}
    scripts = {"coordinator": [invoke("task", subagent_type="writer", description="Save one synthetic structural node"),
        invoke("content_status"), AIMessage(content="", tool_calls=[assigned]), AIMessage(content="Scoped finding retained.")],
        "writer": [invoke("commit_objects", operation_id="pre-model-failure", objects=[
            {"client_key": "saved", "type": "ContentNode", "payload": payload}]), AIMessage(content="Durable structure saved.")],
        "reviewer": [invoke("read_context", target_ref=refs["claim"]), reviewer_next, AIMessage(content="Local review saved.")],
        "text_tool": [AIMessage(content=json.dumps(response))]}
    driver = Driver(**scripts)
    if failed_role == "coordinator":
        driver.fail_once = (failed_role, failed_step)
    failed = await run(ws, driver)
    assert failed["status"] == ("needs_attention" if failed_role == "coordinator" else "failed"), (failed, failure_stacks)
    if failed_role == "coordinator":
        assert failed["last_error"]["failure_kind"] == "model_request_timeout"
        assert failed["last_error"]["automatic_resume"] is False
    assert failed["last_error"]["type"] == ("ReadTimeout" if failed_role == "coordinator" else "RuntimeError")
    assert driver.failed if failed_role == "coordinator" else injected == [True]
    saved = deepcopy(cs.list_objects("ContentNode"))
    tasks = deepcopy(cs.list_objects("DelegatedTask"))
    assert len([r for r in saved if r["payload"] == payload]) == 1
    assert not cs.list_objects("ReviewRecord")
    pending = await snapshot(ws, driver)
    assert pending.next and not pending.interrupts
    fresh = Driver(**scripts)
    reopened = Workspace(Store(ws.store.root))
    resumed = await run(reopened, fresh)
    assert resumed["last_error"] is None, (resumed, failure_stacks)
    assert fresh.calls[0][:2] == (failed_role, failed_step)
    current = ContentStore(reopened.store)
    assert current.list_objects("ContentNode") == saved
    for task in tasks:
        assert current.read(task["ref"]) == task
    reviews = current.list_objects("ReviewRecord")
    assert len(reviews) == 1 and reviews[0]["payload"]["items"][0]["verdict"] == "not_satisfied"
    assert sum(r == "text_tool" for r, _, _ in [*driver.calls, *fresh.calls]) == 1
    assert sum(e["tool"] == "commit_objects" for e in events(reopened, "deep_tool_start")) == 1
    assert events(reopened, "deep_run_started")[-1]["resume"] is True
    complete = await snapshot(reopened, fresh)
    assert not complete.next and not complete.interrupts
    assert not reopened.results() and not reopened.store.get("content_final_review")


async def test_unknown_submit_outcome_replays_receipt_without_duplicate_commit(tmp_path, monkeypatch, failure_stacks):
    from copy import deepcopy
    from report_agent.content_store import ContentStore
    from test_task_supervision import ws as native_fixture
    ws = native_fixture.__wrapped__(tmp_path)
    cs = ContentStore(ws.store)
    operation = "native-lost-return-structural-commit"
    original = ContentStore.commit
    attempts, durable = [], {}
    def commit_then_lose_response(self, actor, operation_id, objects):
        if operation_id != operation:
            return original(self, actor, operation_id, objects)
        attempts.append({"actor": actor, "objects": deepcopy(objects)})
        response = original(self, actor, operation_id, objects)
        with self.store.connect() as db:
            row = db.execute("SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?", (operation,)).fetchone()
        if len(attempts) == 1:
            durable.update(response=deepcopy(response), row=row, actor=actor,
                node=deepcopy(self.read(response["result"]["refs"]["section"])))
            assert self.receipt(actor, operation)["state"] == "known_success"
            # Actual local transaction already succeeded. Caller lost the return;
            # this is not permission to repeat unresolved detached/external work.
            # Ordinary fault replaces retired submit_result's old HTTP fixture.
            raise RuntimeError("offline return lost after durable typed commit")
        assert response == durable["response"] and row == durable["row"]
        return response
    monkeypatch.setattr(ContentStore, "commit", commit_then_lose_response)
    payload = {"kind": "chapter", "body": {"text": "Synthetic durable structure"},
        "qualifiers": {}, "claim_kind": "structure"}
    def receipt_seen(messages):
        assert observation(messages, "commit_objects") == durable["response"]
        return AIMessage(content="Original durable receipt received after checkpoint recovery.")
    scripts = {"coordinator": [invoke("task", subagent_type="writer", description="Save one synthetic structural node"),
            AIMessage(content="Retained saved structure; no approval.")],
        "writer": [invoke("commit_objects", operation_id=operation, objects=[
            {"client_key": "section", "type": "ContentNode", "payload": payload}]), receipt_seen]}
    driver = Driver(**scripts)
    failed = await run(ws, driver)
    assert failed["status"] == "failed", (failed, failure_stacks)
    assert failed["last_error"]["type"] == "RuntimeError" and len(attempts) == 1
    committed = deepcopy(cs.list_objects("ContentNode"))
    tasks = deepcopy(cs.list_objects("DelegatedTask"))
    assert committed == [durable["node"]] and committed[0]["ref"]["version"] == 1
    pending = await snapshot(ws, driver)
    assert pending.next and not pending.interrupts
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**scripts)
    resumed = await run(reopened, fresh)
    assert resumed["last_error"] is None, (resumed, failure_stacks)
    assert fresh.calls[0][:2] == ("writer", 1)
    current = ContentStore(reopened.store)
    assert current.list_objects("ContentNode") == committed
    assert current.list_objects("DelegatedTask") == tasks and len(tasks) == 1
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    with reopened.store.connect() as db:
        rows = db.execute("SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?", (operation,)).fetchall()
    assert rows == [durable["row"]]
    receipt = current.receipt(durable["actor"], operation)
    assert receipt["state"] == "known_success" and receipt["response"] == durable["response"]
    assert len([e for e in events(reopened, "deep_tool_start") if e["tool"] == "commit_objects"]) == 1
    assert len([e for e in events(reopened, "deep_tool_end") if e["tool"] == "commit_objects"]) == 1
    complete = await snapshot(reopened, fresh)
    assert not complete.next and not complete.interrupts
    assert not current.list_objects("ReviewRecord") and not reopened.results()


async def test_checkpoint_with_old_draft_summary_field_resumes_as_draft_only(ws, monkeypatch):
    # Explicit historical native checkpoint component, not the retired wrapper.
    from contextlib import asynccontextmanager
    from inspect import iscoroutinefunction
    from langchain.agents import create_agent
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    config = {"configurable": {"thread_id": "historical-old-draft-call"}}
    @asynccontextmanager
    async def graph_for(workspace, scripted):
        tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
                 else StructuredTool.from_function(t)
                 for t in deep_runtime.business_tools(workspace, "coordinator", None, None)]
        async with AsyncSqliteSaver.from_conn_string(str(workspace.store.root / "checkpoints.db")) as saver:
            graph = create_agent(model=scripted("coordinator"), tools=tools,
                system_prompt=deep_runtime.COORDINATOR,
                middleware=[deep_runtime.BusinessBoundary(workspace, "coordinator")],
                checkpointer=saver, name="report_coordinator")
            yield graph

    original = deep_runtime.BusinessBoundary.awrap_tool_call

    async def stop_before_tool(self, request, handler):
        if request.tool_call["name"] == "submit_result":
            raise RuntimeError("TEST_STOP_BEFORE_OLD_TOOL_CALL")
        return await original(self, request, handler)

    legacy = invoke("submit_result", kind="draft", title="Saved old request", body="Supplied daytime access",
                    source_ids=["source"], input_ids=[], outcome="A prose description, not an approval", target_id="")
    driver = Driver(coordinator=[legacy, final_receipt])
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", stop_before_tool)
    async with graph_for(ws, driver) as graph:
        with pytest.raises(RuntimeError, match="TEST_STOP_BEFORE_OLD_TOOL_CALL"):
            await graph.ainvoke({"messages": [HumanMessage(content="Save the supplied historical draft.")]}, config)
        pending = await graph.aget_state(config)
    assert pending.next and not ws.results()
    old_call = pending.values["messages"][-1].tool_calls[0]
    assert old_call["args"]["outcome"] == "A prose description, not an approval"
    monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", original)
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**driver.scripts)
    async with graph_for(reopened, fresh) as graph:
        await graph.ainvoke(None, config)
        final = await graph.aget_state(config)
    # The retired wrapper's needs_attention fallback was not an approval verdict.
    # Measure actual native completion and absence of approval without fabricating status.
    assert not final.next and not final.interrupts
    assert not reopened.store.get("delivery") and not reopened.store.get("rubric_reviews")
    assert not [r for r in reopened.results() if r["kind"] == "review"]
    result, = reopened.results()
    assert result["kind"] == "draft" and result["owner"] == "writer"
    assert result["outcome"] == result["target_id"] == ""
    assert fresh.calls[0][:2] == ("coordinator", 1)
    assert len(events(reopened, "result_committed")) == 1


async def test_reviewer_read_survives_child_interrupt_and_graph_rebuild(tmp_path, failure_stacks):
    from copy import deepcopy
    from langgraph.types import interrupt
    from report_agent.content_store import ContentStore
    from report_agent.task_context import exact_task_context
    from test_task_supervision import ws as native_fixture
    from test_bounded_review import review_call
    from test_hierarchical_content import seed
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, snapshot_ref, _ = seed(ws)
    original_nodes = deepcopy(cs.list_objects("ContentNode"))
    source = next(r for r in cs.read(snapshot_ref)["payload"]["refs"] if r["type"] == "SourceArtifact")
    assigned = review_call(snapshot_ref, refs, reads=[source])
    assigned["args"].pop("supervision_plugin", None)
    issue = ws.issue("requirement", "Synthetic Reviewer checkpoint: confirm scope", [])
    captured, observed = [], {}
    def resume_after_read(messages):
        body = observation(messages, "read_context")
        assert body["ok"] is True
        assert body["result"]["objects"] == [cs.read(refs["claim"])]
        observed.setdefault("manual_read", deepcopy(body))
        assert body == observed["manual_read"]
        captured.append(deepcopy(exact_task_context(ws, "reviewer")))
        answer = interrupt({"issue_id": issue["id"], "kind": "synthetic_test_checkpoint"})
        assert answer == "Daytime scope confirmed"
        return invoke("perform_assigned_review", operation_id="after-interrupt", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[])
    def checker(messages):
        packet = json.loads(messages[-1].content)
        bodies = [entry["object"] for entry in packet["evidence"] if entry["kind"] == "saved_object"]
        assert cs.read(refs["claim"]) in bodies and cs.read(source) in bodies
        assert packet["evidence"][0]["object"] == cs.read(refs["claim"])
        assert packet["evidence"][1]["object"] == cs.read(source)
        observed["checker_packet"] = packet
        # Scripted protocol finding; does not validate engineering semantics.
        return AIMessage(content=json.dumps({"items": [{"scope_id": "rule-comparison",
            "checked_requirement_indexes": [0], "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": 0, "locator": "claim", "observation": "Synthetic claim observed."},
                {"evidence_index": 1, "locator": "source", "observation": "Synthetic source observed."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "Synthetic local finding.", "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["Synthetic comparison"], "unchecked": [], "blocked": [],
                "basis": "Supplied literal bodies."}, "reason": "Scripted local negative only.", "findings": []}]}))
    scripts = {"coordinator": [AIMessage(content="", tool_calls=[assigned]), AIMessage(content="Local review retained; no whole-report approval.")],
        "reviewer": [invoke("read_context", target_ref=refs["claim"]), resume_after_read,
            AIMessage(content="Saved scoped finding without manually reading the claim again.")], "text_tool": [checker]}
    driver = Driver(**scripts)
    paused = await run(ws, driver)
    assert paused["status"] == "needs_human", (paused, failure_stacks)
    pending = await snapshot(ws, driver)
    assert pending.next and len(pending.interrupts) == 1
    assert pending.interrupts[0].value["issue_id"] == issue["id"]
    receipt_id = observed["manual_read"]["receipt_id"]
    with ws.store.connect() as db:
        receipt = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (receipt_id,)).fetchone()
    assert receipt and receipt[0] == captured[0]["actor_id"]
    tasks = deepcopy(cs.list_objects("DelegatedTask"))
    assert len(tasks) == 1 and not cs.list_objects("ReviewRecord")
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(**scripts)
    waiting = await run(reopened, fresh)
    assert waiting["status"] == "needs_human" and not fresh.calls
    reopened.decide_issue(issue["id"], "Daytime scope confirmed", resolved=True)
    resumed = await run(reopened, fresh)
    assert resumed["last_error"] is None, (resumed, failure_stacks)
    complete = await snapshot(reopened, fresh)
    assert not complete.next and not complete.interrupts
    assert len(captured) == 2
    for key in ("actor_id", "assignment", "current_invocation"):
        assert captured[0][key] == captured[1][key]
    with reopened.store.connect() as db:
        assert db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (receipt_id,)).fetchone() == receipt
    current = ContentStore(reopened.store)
    reviews = current.list_objects("ReviewRecord")
    assert len(reviews) == 1 and reviews[0]["owner_id"] == receipt[0]
    assert reviews[0]["task_id"] == tasks[0]["ref"]["id"]
    assert reviews[0]["payload"]["items"][0]["verdict"] == "not_satisfied"
    assert current.list_objects("DelegatedTask") == tasks and current.list_objects("ContentNode") == original_nodes
    assert sum(e["tool"] == "read_context" and e["role"] == "reviewer" for e in events(reopened, "deep_tool_start")) == 1
    assert sum(r == "text_tool" for r, _, _ in [*driver.calls, *fresh.calls]) == 1
    assert observed["checker_packet"]  # Automatic fresh material receipts are separate from retained manual receipt.
    assert not reopened.store.get("content_final_review") and not reopened.results()


@pytest.mark.parametrize("same_turn", [False, True])
async def test_separate_reviewer_delegations_cannot_share_read_observations(tmp_path, failure_stacks, same_turn):
    # Explicit migration: native task-owned Word receipts, with adversarial
    # knowledge of a real foreign ID. It is not the attacker's own observation.
    from copy import deepcopy
    from report_agent.task_context import exact_task_context
    from test_task_supervision import ws as native_fixture
    from test_hierarchical_content import seed
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, frozen, _ = seed(ws)
    originals = deepcopy(cs.list_objects("ContentNode")), deepcopy(cs.list_objects("SourceArtifact"))
    seen = {"reads": {}}
    def request(identity):
        return call("task", {"subagent_type": "reviewer", "description": "Check exact saved Word identity only.",
            "review_snapshot_ref": frozen, "review_requirements": [{"target_ref": refs["claim"],
                "criterion_ref": refs["k"], "scope_id": "saved-word", "assessment_kind": "export",
                "artifact_refs": [seen["export"]], "required_checks": ["Check exact saved Word identity"]}]}, identity)
    def assign(messages):
        seen["export"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
        first = request("read-context")
        return AIMessage(content="", tool_calls=[first, request("unread-context")] if same_turn else [first])
    def second(messages):
        return AIMessage(content="", tool_calls=[request("unread-context")])
    def read_word(messages):
        return AIMessage(content="", tool_calls=[call("read_content_export", {"export_ref": seen["export"]}, "first-owned-read")])
    def classify(messages):
        actual = observation(messages, "read_content_export")
        assert actual["ok"] and actual["result"]["export_ref"] == seen["export"]
        task = exact_task_context(ws, "reviewer")["actor_id"]
        seen["reads"][task] = deepcopy(actual)
        if "donor" not in seen:
            seen["donor"] = task
            return AIMessage(content="Read-only donor task complete; no judgment.")
        assert task != seen["donor"]
        seen["attacker"] = task
        assert not cs.list_objects("ReviewRecord") and not any(r == "text_tool" for r, _, _ in driver.calls)
        # Deliberately malicious fake output knows another task's real receipt;
        # no claim that a public tool disclosed that foreign receipt to it.
        return AIMessage(content="Adversarial fixture: attempt another task's receipt.", tool_calls=[call(
            "perform_assigned_artifact_review", {"operation_id": "foreign-attempt", "scope_ids": ["saved-word"],
                "observation_receipts": [seen["reads"][seen["donor"]]["receipt_id"]]}, "foreign-attempt")])
    def own_read_after_denial(messages):
        reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.tool_call_id == "foreign-attempt")
        denial = json.loads(reply.content)
        assert reply.status == "error" and denial["accepted"] is False
        assert denial["code"] == "ARTIFACT_OBSERVATION_REQUIRES_CURRENT_TASK_RECEIPT"
        assert not cs.list_objects("ReviewRecord") and not any(r == "text_tool" for r, _, _ in driver.calls)
        seen["negative_before_positive"] = deepcopy(denial)
        return AIMessage(content="", tool_calls=[call("read_content_export", {"export_ref": seen["export"]}, "after-denial-read")])
    def own_check(messages):
        actual = observation(messages, "read_content_export")
        seen["own"] = deepcopy(actual)
        assert actual["receipt_id"] != seen["reads"][seen["donor"]]["receipt_id"]
        assert exact_task_context(ws, "reviewer")["actor_id"] == seen["attacker"]
        return invoke("perform_assigned_artifact_review", operation_id="own-positive", scope_ids=["saved-word"],
            observation_receipts=[actual["receipt_id"]])
    def checker(messages):
        packet = json.loads(messages[-1].content)
        assert seen["negative_before_positive"]
        assert packet["evidence"] == [{"receipt_id": seen["own"]["receipt_id"], "actual_observation": seen["own"]["result"]}]
        assert packet["snapshot_ref"] == frozen and packet["criteria"] == [cs.read(refs["k"])]
        seen["checker"] = deepcopy(packet)
        item = {"target_ref": refs["claim"], "criterion_ref": refs["k"], "scope": "saved Word",
            "scope_id": "saved-word", "assessment_kind": "export", "artifact_refs": [seen["export"]],
            "execution_state": "completed", "verdict": "satisfied",
            "observations": [{"receipt_id": seen["own"]["receipt_id"], "locator": "Word identity",
                "observation": "Exact own saved export observed; scripted protocol only."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": "Own receipt accepted.",
                "observation_indexes": [0], "remaining": ""}],
            "coverage": {"checked": ["saved Word identity"], "unchecked": [], "blocked": [], "basis": "Own OOXML read only."},
            "reason": "Synthetic scoped protocol positive, not global/visual acceptance.", "findings": []}
        return AIMessage(content=json.dumps({"snapshot_ref": frozen, "target_ref": refs["claim"], "scope": "saved Word",
            "criteria_refs": [refs["k"]], "dependency_refs": [seen["export"]], "items": [item], "delivery_checks": []}))
    driver = Driver(coordinator=[invoke("export_content_snapshot", operation_id="two-reviewer-word", snapshot_ref=frozen),
        assign, *([] if same_turn else [second]), AIMessage(content="Independent task boundary exercised; no global approval.")],
        reviewer=[read_word, classify, own_read_after_denial, own_check, AIMessage(content="Own scoped check saved.")],
        text_tool=[checker])
    result = await run(ws, driver)
    assert result["last_error"] is None, (result, failure_stacks)
    assert seen["negative_before_positive"] and seen["checker"]
    tasks, records = cs.list_objects("DelegatedTask"), cs.list_objects("ReviewRecord")
    assert len(tasks) == 2 and len({t["ref"]["id"] for t in tasks}) == 2
    assert len(records) == 1 and records[0]["owner_id"] == seen["attacker"] != seen["donor"]
    assert records[0]["payload"]["items"][0]["observations"][0]["receipt_id"] == seen["own"]["receipt_id"]
    assert (cs.list_objects("ContentNode"), cs.list_objects("SourceArtifact")) == originals
    assert sum(r == "text_tool" for r, _, _ in driver.calls) == 1
    assert sum(e["tool"] == "task" for e in events(ws, "deep_tool_start")) == 2
    parent_turns = [m for r, _, messages in driver.calls if r == "coordinator" for m in messages if isinstance(m, AIMessage)
        and any(c["name"] == "task" for c in m.tool_calls)]
    assert parent_turns
    assert max(sum(c["name"] == "task" for c in m.tool_calls) for m in parent_turns) == (2 if same_turn else 1)
    assert not ws.store.get("content_final_review") and not ws.results()
