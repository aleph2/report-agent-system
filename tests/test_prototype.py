from report_agent import report_state
import json
import asyncio
from pathlib import Path
from typing import Any

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from report_agent.models import TextAnalysis
from report_agent.store import Store
from report_agent.tools import material_tools
from test_task_supervision import ws as native_ws


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def project(tmp_path, reuse=False):
    store = Store(tmp_path)
    name = "materials-reuse.json" if reuse else "materials-new.json"
    store.initialize(json.loads((EXAMPLES / name).read_text()))
    return store


class ScriptedModel(BaseLlm):
    """Protocol double only; never used as evidence of model autonomy."""

    model: str = "scripted-protocol-double"
    script: list[str] = Field(default_factory=list)
    requests: list[Any] = Field(default_factory=list, exclude=True)
    position: int = 0
    waiting: Any = Field(default=None, exclude=True)

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append(llm_request)
        action = self.script[self.position]
        self.position += 1
        if action == "fail":
            raise RuntimeError("Synthetic transport interruption")
        if action == "wait":
            self.waiting.set()
            await asyncio.Event().wait()
        if action == "error_event":
            yield LlmResponse(error_code="SYNTHETIC_UNAVAILABLE", error_message="Synthetic failure")
            return
        if action == "read":
            name, args = "read_sources", {"source_ids": ["access", "notice", "brief"]}
        elif action == "save":
            name, args = "save_material", {"title": "Protocol fixture", "body": "East footpath, 08:00-17:00 [access].",
                                            "source_ids": ["access"]}
        elif action == "select":
            saved = None
            for content in llm_request.contents:
                for part in content.parts or []:
                    if part.function_response and part.function_response.name == "save_material":
                        saved = part.function_response.response["artifact"]["id"]
            if saved is None:
                state = json.loads(llm_request.contents[0].parts[0].text)
                saved = state["artifacts"][0]["id"]
            name, args = "select_result", {"artifact_id": saved}
        elif action == "text":
            assert not llm_request.tools_dict
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="East footpath [access]; only daytime.")]))
            return
        elif action == "final":
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Draft selected; not reviewed.")]))
            return
        elif action == "length":
            yield LlmResponse(finish_reason=types.FinishReason.MAX_TOKENS,
                              content=types.Content(role="model", parts=[types.Part(text="Incomplete")]))
            return
        else:
            raise AssertionError(action)
        yield LlmResponse(content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name=name, args=args))]))


def test_receipt_survives_reopen_and_reordered_sources(tmp_path):
    store = project(tmp_path)
    first = store.save_material("Note", "Body", ["access", "notice"], owner="materials")
    reopened = Store(tmp_path)
    again = reopened.save_material("Note", "Body", ["notice", "access"], owner="materials")
    assert again["reused"]
    assert first["artifact"]["id"] == again["artifact"]["id"]
    assert len(reopened.artifacts()) == 1


def test_writer_cannot_save_upstream_and_foreign_source_rejected(tmp_path):
    store = project(tmp_path)
    with pytest.raises(PermissionError):
        store.save_material("Note", "Body", ["access"], owner="writer")
    with pytest.raises(ValueError, match="SOURCE_NOT_IN_PROJECT"):
        store.save_material("Note", "Body", ["another-project"], owner="materials")
    assert not store.artifacts()


def test_projects_are_isolated(tmp_path):
    first = project(tmp_path / "one", reuse=True)
    second = project(tmp_path / "two")
    with pytest.raises(ValueError, match="ARTIFACT_NOT_IN_PROJECT"):
        second.select_result(first.artifacts()[0]["id"])
    assert not second.artifacts()


def test_inputs_immutable(tmp_path):
    store = project(tmp_path)
    manifest = store.manifest
    manifest["goal"] = "Changed goal"
    with pytest.raises(ValueError, match="IMMUTABLE"):
        store.initialize(manifest)


def test_exclusive_worker_lock(tmp_path):
    store = project(tmp_path)
    with store.run_lock():
        with pytest.raises(RuntimeError, match="PROJECT_ALREADY_RUNNING"):
            with Store(tmp_path).run_lock():
                pass


async def test_text_tool_is_bounded_and_cached(tmp_path):
    store = project(tmp_path)
    model = ScriptedModel(script=["text"])
    tool = next(t for t in material_tools(store, TextAnalysis(model), owner="materials") if t.__name__ == "analyze_sources")
    first = await tool(["access"], "Access arrangements")
    second = await tool(["access"], "Access arrangements")
    assert not first["reused"] and second["reused"]
    assert len(model.requests) == 1
    sent = json.loads(model.requests[0].contents[0].parts[0].text)
    assert [s["id"] for s in sent["sources"]] == ["access"]
    assert not store.artifacts()


async def test_incomplete_text_not_cached(tmp_path):
    store = project(tmp_path)
    model = ScriptedModel(script=["length"])
    tool = next(t for t in material_tools(store, TextAnalysis(model), owner="materials") if t.__name__ == "analyze_sources")
    with pytest.raises(RuntimeError, match="INCOMPLETE"):
        await tool(["access"], "Access")
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 0


def saved_native_delivery(workspace):
    from report_agent.content_export import export_snapshot, _bytes
    from test_hierarchical_content import seed
    cs, actor, _, snapshot, _ = seed(workspace)
    export = export_snapshot(cs, actor, "saved-export", snapshot)["result"]["export_ref"]
    payload = cs.read(export)["payload"]
    def export_bytes():
        return _bytes(workspace.store, payload["file_ref"], payload["file_digest"])
    return cs, actor, snapshot, export, export_bytes


async def test_adk_can_reuse_without_analysis(native_ws):
    """Historical reuse obligation through the current native runtime."""
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.content_delivery import current_delivery
    from test_deep_runtime import Driver, invoke
    cs, _, snapshot, export, export_bytes = saved_native_delivery(native_ws)
    objects, data = cs.list_objects(), export_bytes()
    driver = Driver(coordinator=[invoke("select_content_delivery", operation_id="reuse-saved",
        snapshot_ref=snapshot, export_ref=export), AIMessage(content="Saved draft reused; unreviewed.")])
    result = await deep_runtime.run_report(native_ws, driver)
    assert result["last_error"] is None, result
    selected = report_state.selected_delivery(native_ws.store)
    assert selected["snapshot_ref"] == snapshot and selected["export_ref"] == export
    assert cs.list_objects() == objects and export_bytes() == data
    assert all(role == "coordinator" for role, _, _ in driver.calls)
    assert current_delivery(native_ws.store)["overall_verdict"] is None


async def test_adk_tool_loop_and_recovery_of_committed_work(native_ws):
    from io import BytesIO
    from docx import Document
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from report_agent.content_export import _bytes
    from report_agent.hierarchical_tools import actor_for
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, invoke, observation, snapshot as checkpoint
    from test_text_work import content
    def commit_body(messages):
        work = observation(messages, "process_report_content")
        return invoke("commit_objects", operation_id="save-actual", objects=[
            {"client_key": "root", "type": "ContentNode", "payload": {"kind": "report",
                "body": {"text": "Synthetic report"}, "qualifiers": {}, "claim_kind": "structure"}},
            {"client_key": "body", "type": "ContentNode", "text_work_id": work["text_work_id"]},
            {"client_key": "edge", "type": "Relation", "payload": {
                "subject_ref": {"client_key": "root"}, "object_ref": {"client_key": "body"},
                "predicate": "contains", "position": 0, "provenance_kind": "adopted_during_generation"}}])
    def return_refs(messages):
        return AIMessage(content=json.dumps({"saved_refs": observation(messages, "commit_objects")["result"]["refs"]}))
    def freeze_actual(messages):
        saved = observation(messages, "task")["saved_refs"]
        inputs = observation(messages, "import_source_versions")["result"]
        return invoke("freeze_snapshot", operation_id="freeze-actual", root_ref=saved["root"],
            refs=[*saved.values(), inputs["requirement_ref"], *inputs["source_refs"]])
    def export_actual(messages):
        snap = observation(messages, "freeze_snapshot")["result"]["snapshot_ref"]
        return invoke("export_content_snapshot", operation_id="export-actual", snapshot_ref=snap)
    def select_actual(messages):
        return invoke("select_content_delivery", operation_id="select-actual",
            snapshot_ref=observation(messages, "freeze_snapshot")["result"]["snapshot_ref"],
            export_ref=observation(messages, "export_content_snapshot")["result"]["export_ref"])
    def tail_failure(messages):
        assert observation(messages, "select_content_delivery")["ok"]
        raise RuntimeError("SYNTHETIC_POST_COMMIT_FAILURE")
    driver = Driver(coordinator=[invoke("import_source_versions", operation_id="actual-inputs", source_ids=["s"]),
        invoke("task", subagent_type="writer", description="Compile the supplied rule as a scoped draft."),
        freeze_actual, export_actual, select_actual, tail_failure],
        writer=[invoke("process_report_content", operation_id="actual-produce", objective="Describe the supplied rule",
            object_type="ContentNode", source_selections=[{"source_id": "s"}]), commit_body, return_refs],
        text_tool=[AIMessage(content=json.dumps(content()))])
    first = await deep_runtime.run_report(native_ws, driver)
    assert first["status"] == "failed" and first["last_error"]["message"] == "SYNTHETIC_POST_COMMIT_FAILURE"
    assert (await checkpoint(native_ws, driver)).next
    cs, selected = ContentStore(native_ws.store), report_state.selected_delivery(native_ws.store)
    export = cs.read(selected["export_ref"])["payload"]
    data = _bytes(native_ws.store, export["file_ref"], export["file_digest"])
    assert content()["body"]["text"] in "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    objects = cs.list_objects()
    def receipts():
        with native_ws.store.connect() as db:
            return db.execute("SELECT * FROM content_operations ORDER BY operation_id").fetchall()
    saved_receipts = receipts()
    assert cs.receipt(actor_for("coordinator"), "select-actual")["state"] == "known_success"
    resumed = Driver(coordinator=[*([AIMessage(content="Must not replay completed work")] * 5),
        AIMessage(content="Saved Word draft retained; no review or engineering acceptance.")])
    second = await deep_runtime.run_report(Workspace(Store(native_ws.store.root)), resumed)
    assert second["last_error"] is None, second
    assert [(role, step) for role, step, _ in resumed.calls] == [("coordinator", 5)]
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    assert cs.list_objects() == objects and receipts() == saved_receipts
    assert report_state.selected_delivery(native_ws.store) == selected
    assert _bytes(native_ws.store, export["file_ref"], export["file_digest"]) == data
    assert not cs.list_objects("ReviewRecord")


async def test_final_text_alone_does_not_complete_task(native_ws):
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from report_agent.content_delivery import current_delivery
    from test_deep_runtime import Driver
    driver = Driver(coordinator=[AIMessage(content="The report is complete and approved.")])
    result = await deep_runtime.run_report(native_ws, driver)
    assert result["last_error"] is None, result
    assert result["execution_status"] == "completed"
    cs = ContentStore(native_ws.store)
    assert not cs.list_objects()
    assert report_state.selected_delivery(native_ws.store) is None
    assert current_delivery(native_ws.store)["overall_verdict"] is None


async def test_selected_result_survives_tail_failure_without_replay(native_ws):
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, invoke, snapshot as checkpoint
    cs, actor, snapshot, export, export_bytes = saved_native_delivery(native_ws)
    objects, data = cs.list_objects(), export_bytes()
    def fail_after_selection(messages):
        raise RuntimeError("SYNTHETIC_POST_SELECTION_FAILURE")
    driver = Driver(coordinator=[invoke("select_content_delivery", operation_id="select-saved",
        snapshot_ref=snapshot, export_ref=export), fail_after_selection])
    first = await deep_runtime.run_report(native_ws, driver)
    assert first["status"] == "failed" and first["last_error"]["type"] == "RuntimeError"
    assert "SYNTHETIC_POST_SELECTION_FAILURE" in first["last_error"]["message"]
    selected = report_state.selected_delivery(native_ws.store)
    assert selected["snapshot_ref"] == snapshot and selected["export_ref"] == export
    receipt = cs.receipt(actor, "select-saved")
    assert receipt["state"] == "known_success"
    assert (await checkpoint(native_ws, driver)).next
    assert cs.list_objects() == objects and export_bytes() == data
    resumed = Driver(coordinator=[AIMessage(content="Must not repeat selection"),
        AIMessage(content="Saved delivery retained; no acceptance.")])
    result = await deep_runtime.run_report(Workspace(Store(native_ws.store.root)), resumed)
    assert result["last_error"] is None, result
    assert [(role, step) for role, step, _ in resumed.calls] == [("coordinator", 1)]
    assert report_state.selected_delivery(native_ws.store) == selected
    assert cs.receipt(actor, "select-saved") == receipt
    assert cs.list_objects() == objects and export_bytes() == data


@pytest.mark.parametrize('startup_delay', [0, 6], ids=['normal-startup', 'slow-startup'])
async def test_selected_result_survives_actual_task_cancellation(native_ws, monkeypatch, startup_delay):
    from contextlib import asynccontextmanager
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, invoke

    store = native_ws.store
    cs, actor, snapshot, export, export_bytes = saved_native_delivery(native_ws)
    saved_bytes = export_bytes()
    saved_objects = cs.list_objects()
    ready = asyncio.Event()
    waiting = asyncio.Event()

    class WaitingDriver(Driver):
        async def respond(self, role, messages):
            step = sum(isinstance(message, AIMessage) for message in messages)
            if role == "coordinator" and step == 1:
                self.calls.append((role, step, list(messages)))
                waiting.set()
                await asyncio.Event().wait()
            return await super().respond(role, messages)

    decision = WaitingDriver(coordinator=[invoke("select_content_delivery",
        operation_id="select-saved", snapshot_ref=snapshot, export_ref=export)])
    original_project_agent = deep_runtime.project_agent

    @asynccontextmanager
    async def observed_startup(*args, **kwargs):
        await asyncio.sleep(startup_delay)
        async with original_project_agent(*args, **kwargs) as agent:
            ready.set()
            yield agent

    with monkeypatch.context() as patch:
        patch.setattr(deep_runtime, 'project_agent', observed_startup)
        task = asyncio.create_task(deep_runtime.run_report(native_ws, decision))
        try:
            # Initialization is separate from the original five-second business wait.
            for phase, signal, timeout in [('startup', ready, 30), ('selected delivery', waiting, 5)]:
                signal_wait = asyncio.create_task(signal.wait())
                try:
                    done, _ = await asyncio.wait({task, signal_wait}, timeout=timeout,
                                                return_when=asyncio.FIRST_COMPLETED)
                    if task in done:
                        task.result()
                        pytest.fail(f'Report ended before {phase}: {store.get("report_error")}')
                    assert signal_wait in done, f'Timed out waiting for {phase}'
                finally:
                    signal_wait.cancel()
                    await asyncio.gather(signal_wait, return_exceptions=True)
            selection_receipt = cs.receipt(actor, 'select-saved')
            assert selection_receipt['state'] == 'known_success'
            assert report_state.selected_delivery(store)['snapshot_ref'] == snapshot
            assert report_state.selected_delivery(store)['export_ref'] == export
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert store.get("report_status") == "interrupted"
    assert store.get("report_error")["type"] == "CancelledError"
    selected = report_state.selected_delivery(store)
    assert selected["snapshot_ref"] == snapshot and selected["export_ref"] == export
    assert cs.list_objects() == saved_objects
    assert export_bytes() == saved_bytes

    # Current native recovery may ask Coordinator to confirm. It must not repeat
    # selection, export or substantive generation to recover committed delivery.
    resumed = Driver(coordinator=[AIMessage(content="Must not replay selection"),
        AIMessage(content="Saved delivery retained; no engineering acceptance.")])
    result = await deep_runtime.run_report(Workspace(Store(store.root)), resumed)
    assert result["last_error"] is None, result
    assert [(role, step) for role, step, _ in resumed.calls] == [("coordinator", 1)]
    assert not any(role in {"writer", "text_tool"} for role, _, _ in resumed.calls)
    assert report_state.selected_delivery(store) == selected
    assert cs.receipt(actor, 'select-saved') == selection_receipt
    assert cs.list_objects() == saved_objects
    assert export_bytes() == saved_bytes


async def test_startup_error_is_visible(native_ws):
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    attempts = []

    def fail_model_factory(role):
        attempts.append(role)
        raise RuntimeError("SYNTHETIC_NATIVE_STARTUP_FAILURE")

    result = await deep_runtime.run_report(native_ws, fail_model_factory)
    assert result["status"] == "failed"
    assert result["last_error"]["type"] == "RuntimeError"
    assert "SYNTHETIC_NATIVE_STARTUP_FAILURE" in result["last_error"]["message"]
    assert attempts
    assert not ContentStore(native_ws.store).list_objects()
    errors = [event for event in native_ws.store.events() if event["kind"] == "deep_run_error"]
    assert len(errors) == 1
    assert "SYNTHETIC_NATIVE_STARTUP_FAILURE" in json.dumps(errors)


async def test_error_event_is_not_success(native_ws, monkeypatch, request):
    """Current adapter/SDK failure; replaced HTTP client does not test factory hooks."""
    import httpx
    from openai import AsyncOpenAI
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from report_agent.deep_models import configured_model
    from test_deep_runtime import Driver
    clear_provider_configuration(monkeypatch)
    for field, value in (("MODEL", "glm-5.3"), ("BASE_URL", "https://model.invalid/v1"),
                         ("API_KEY", "fake-private-key"), ("SDK_RETRIES", "0")):
        monkeypatch.setenv("REPORT_" + field, value)
    sent = []
    async def handle(http_request):
        sent.append(json.loads(http_request.content))
        return httpx.Response(403, json={"error": {"message": "fake-private-provider-message", "type": "test"}})
    model = configured_model(native_ws.store, "coordinator")
    unused = Driver()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    sdk = AsyncOpenAI(api_key="fake-private-key", base_url="https://model.invalid/v1", http_client=client, max_retries=0)
    model.async_client = sdk.chat.completions
    try:
        result = await deep_runtime.run_report(native_ws, lambda role: model if role == "coordinator" else unused(role))
    finally:
        await sdk.close()
        await model.http_async_client.aclose()
        model.http_client.close()
    assert client.is_closed and model.http_async_client.is_closed and model.http_client.is_closed
    assert result["status"] == "failed"
    assert result["last_error"]["http_status"] == 403
    assert result["last_error"]["message"] == "MODEL_PERMISSION_DENIED"
    assert native_ws.store.get("report_error") == result["last_error"]
    assert len(sent) == 1 and sent[0]["model"] == "glm-5.3" and sent[0]["tools"]
    assert not unused.calls
    assert not ContentStore(native_ws.store).list_objects() and report_state.selected_delivery(native_ws.store) is None
    events = native_ws.store.events()
    assert any(event["kind"] == "deep_run_error" for event in events)
    public = json.dumps({"result": result, "events": events})
    assert "fake-private-key" not in public and "fake-private-provider-message" not in public
    request.node.user_properties.append(("local_http_request_without_headers", json.dumps(sent[0])))


@pytest.mark.parametrize("status,error,expected", [
    ("failed", None, 2), ("interrupted", None, 2), ("needs_attention", None, 2),
    ("completed", {"type": "RuntimeError"}, 2), ("completed", None, 0),
])
def test_cli_exit_code(native_ws, monkeypatch, capsys, status, error, expected):
    from report_agent import cli

    calls = []
    public_status = 'not_assessed' if status == 'completed' else status
    result = {'status': public_status, 'execution_status': status, 'last_error': error,
              'report_review_required': True, 'whole_report_acceptance': None}
    async def stub(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(result)

    from report_agent import deep_runtime
    monkeypatch.setattr(deep_runtime, "run_report", stub)
    monkeypatch.setattr("sys.argv", ["report-agent", "report-run", "--project", str(native_ws.store.root)])
    assert cli.main() == expected
    assert len(calls) == 1 and calls[0][1] == {"decision_only": False}
    assert json.loads(capsys.readouterr().out) == result


def test_retired_cli_run_cannot_execute_or_change_saved_history(tmp_path, monkeypatch, capsys):
    from report_agent import cli, runtime
    store = project(tmp_path, reuse=True)
    saved = store.artifacts()

    async def forbidden(*args, **kwargs):
        pytest.fail("Retired runtime must not execute")

    monkeypatch.setattr(runtime, "run_task", forbidden)
    monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
    with pytest.raises(SystemExit) as rejected:
        cli.main()
    assert rejected.value.code == 2
    assert "Historical prototype execution is inactive" in capsys.readouterr().err
    assert store.artifacts() == saved


async def test_explicit_feedback_reopens_without_mutating_saved_materials(tmp_path):
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from report_agent.workspace import Workspace
    from test_agent_duty_trace_cases import result_value
    from test_deep_runtime import Driver, invoke
    store = Store(tmp_path)
    store.initialize({"goal": "Compile the supplied daytime access notice.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "context_policy": "stateful-tools-v1", "decision_data_policy": "reference-data-v1",
        "sources": [{"id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete"}]})
    ws, cs, seen = Workspace(store), ContentStore(store), {}
    original_sources = store.manifest["sources"]
    initial = {"kind": "block", "body": {"text": "Daytime access only [s]."},
               "qualifiers": {}, "claim_kind": "fact"}
    revised = {**initial, "body": {"text": "Daytime access only [s]. Exact hours remain unverified."}}
    def received(messages, name):
        return result_value(next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == name))
    def initial_producer(messages):
        packet = json.loads(messages[-1].content)
        assert packet["evidence"][0]["observation"]["blocks"][0]["text"] == "Daytime access only."
        seen["actor"] = packet["actor"]
        return AIMessage(content=json.dumps(initial))
    def initial_produce(messages):
        seen["assignment"] = received(messages, "read_decision_state")["value"]
        return invoke("process_report_content", operation_id="initial-produce",
            objective="Compile the supplied access restriction.", object_type="ContentNode",
            source_selections=[{"source_id": "s"}])
    def adopt_initial(messages):
        seen["first_work"] = received(messages, "process_report_content")["text_work_id"]
        return invoke("save_text_node", operation_id="initial-adopt", text_work_id=seen["first_work"])
    def read_indexed_node(messages):
        page = received(messages, "read_object_index")
        assert page["total"] == 1 and page["next_offset"] is None
        return invoke("read_context", target_ref=page["objects"][0]["ref"])
    def retain_old(messages):
        seen["old_public"] = received(messages, "read_context")["result"]["objects"][0]
        return AIMessage(content="Saved daytime draft; no review claimed.")
    first_delegation = invoke("task", subagent_type="writer", description="Compile the supplied access notice.")
    first_delegation.tool_calls[0]["id"] = "initial-writer"
    first_driver = Driver(coordinator=[first_delegation,
        invoke("read_object_index", object_type="ContentNode", current_only=True), read_indexed_node, retain_old],
        writer=[invoke("read_decision_state", path=["assignment"]), initial_produce, adopt_initial,
                AIMessage(content="Saved exact initial output.")], text_tool=[initial_producer])
    first = await deep_runtime.run_report(ws, first_driver)
    assert first["last_error"] is None, first
    old = seen["old_public"]
    assert old["payload"] == initial and old["ref"]["version"] == 1
    assert old["task_id"] == seen["actor"]["task_id"]
    old_receipt = store.get("text_work_receipt:" + seen["first_work"])
    assert old_receipt is not None
    feedback = store.add_feedback("Add a concise source-grounded timing limitation.")

    def resume_from_feedback(messages):
        actual = received(messages, "read_decision_state")
        assert actual["value"] == [feedback] and actual["complete_value"]
        previous = received(messages, "read_context")["result"]["objects"][0]
        description = (actual["value"][0]["message"] + " Revise ContentNode Ref "
            f"type={previous['ref']['type']} id={previous['ref']['id']} version={previous['ref']['version']}.")
        continuation = invoke("task", subagent_type="writer", description=description,
                              resume_content_task_id=previous["task_id"])
        continuation.tool_calls[0]["id"] = "feedback-writer"
        return continuation
    def read_current_instruction(messages):
        actual = received(messages, "read_decision_state")["value"]
        assert actual == [feedback]
        seen["writer_feedback"] = actual[0]
        return invoke("read_decision_state", path=["current_invocation"])
    def read_original_assignment(messages):
        current = received(messages, "read_decision_state")["value"]
        assert seen["writer_feedback"]["message"] in current["description"]
        assert old["ref"]["id"] in current["description"]
        return invoke("read_decision_state", path=["assignment"])
    def read_original_content(messages):
        assert received(messages, "read_decision_state")["value"] == seen["assignment"]
        return invoke("read_context", target_ref=old["ref"])
    def request_revision(messages):
        actual = received(messages, "read_context")["result"]["objects"][0]
        assert actual == old
        return invoke("process_report_content", operation_id="feedback-revision",
            objective=seen["writer_feedback"]["message"], object_type="ContentNode",
            input_refs=[actual["ref"]], source_selections=[{"source_id": "s"}])
    def revision_producer(messages):
        packet = json.loads(messages[-1].content)
        assert packet["actor"] == seen["actor"]
        assert packet["objective"] == feedback["message"]
        selected = [item["object"] for item in packet["evidence"] if item["kind"] == "saved_object"]
        assert selected == [old]
        assert [block["text"] for item in packet["evidence"] if item["kind"] == "source_blocks"
                for block in item["observation"]["blocks"]] == ["Daytime access only."]
        return AIMessage(content=json.dumps(revised))
    def adopt_revision(messages):
        work = received(messages, "process_report_content")
        return invoke("save_text_node", operation_id="feedback-adopt", text_work_id=work["text_work_id"], previous_ref=old["ref"])
    def read_new(messages):
        current = received(messages, "read_context")["result"]["objects"][0]
        assert current["ref"] == {**old["ref"], "version": 2}
        assert current["owner_id"] == old["owner_id"] and current["task_id"] == old["task_id"]
        assert current["payload"] == revised
        return AIMessage(content="Saved source-grounded revision; independent review remains open.")
    second_driver = Driver(coordinator=[*([AIMessage(content="Must not replay completed work")] * 4),
        invoke("read_decision_state", path=["operator_feedback"]), resume_from_feedback,
        invoke("read_object_index", object_type="ContentNode", current_only=True), read_indexed_node, read_new],
        writer=[invoke("read_decision_state", path=["operator_feedback"]), read_current_instruction,
            read_original_assignment, read_original_content, request_revision, adopt_revision,
            AIMessage(content="Saved exact revised output.")], text_tool=[revision_producer])
    second = await deep_runtime.run_report(Workspace(Store(store.root)), second_driver)
    assert second["last_error"] is None, second
    assert second_driver.calls[0][:2] == ("coordinator", 4)
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert [node["ref"]["version"] for node in cs.list_objects("ContentNode")] == [1, 2]
    assert cs.read(old["ref"]) == old
    assert store.get("text_work_receipt:" + seen["first_work"]) == old_receipt
    assert store.manifest["sources"] == original_sources
    assert sum(role == "text_tool" for driver in (first_driver, second_driver) for role, _, _ in driver.calls) == 2
    assert not cs.list_objects("ReviewRecord") and report_state.selected_delivery(store) is None


def test_feedback_cannot_interrupt_active_worker(tmp_path):
    store = project(tmp_path)
    with store.run_lock():
        with pytest.raises(RuntimeError, match="PROJECT_ALREADY_RUNNING"):
            store.add_feedback("New feedback")
    assert not store.get("feedback")


def clear_provider_configuration(monkeypatch):
    for role in ("", "COORDINATOR_", "REVIEWER_", "WRITER_", "TEXT_TOOL_", "LAYOUT_", "RUBRIC_GRADER_", "GRADER_"):
        for field in ("MODEL", "BASE_URL", "API_KEY"):
            monkeypatch.delenv("REPORT_" + role + field, raising=False)


async def test_configuration_failure_is_persisted(native_ws, monkeypatch):
    import httpx
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    clear_provider_configuration(monkeypatch)
    sent = []
    def no_network(*args, **kwargs):
        sent.append(True)
        pytest.fail("Missing configuration must fail before a provider request")
    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    result = await deep_runtime.run_report(native_ws)
    assert result["status"] == "failed"
    assert result["last_error"]["type"] == "RuntimeError"
    assert result["last_error"]["message"] == "AUTHORIZED_GLM53_CONFIGURATION_REQUIRED"
    assert native_ws.store.get("report_error") == result["last_error"]
    assert not sent and not ContentStore(native_ws.store).list_objects()
    assert any(event["kind"] == "deep_run_error" for event in native_ws.store.events())


def test_completed_result_does_not_require_provider_config(native_ws, monkeypatch, capsys):
    """Read saved output without a provider; does not promise provider-free execution."""
    from report_agent import cli, deep_runtime
    from report_agent.content_models import Ref
    from report_agent.hierarchical_tools import content_tools
    cs, _, snapshot, export, export_bytes = saved_native_delivery(native_ws)
    tools = {t.__name__: t for t in content_tools(native_ws, "coordinator")}
    tools["select_content_delivery"]("select-existing", Ref.model_validate(snapshot), Ref.model_validate(export))
    selected, objects, data = report_state.selected_delivery(native_ws.store), cs.list_objects(), export_bytes()
    clear_provider_configuration(monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail("Read-only access must not construct a provider model")
    monkeypatch.setattr(deep_runtime, "configured_model", forbidden)
    monkeypatch.setattr(deep_runtime, "run_report", forbidden)
    outputs = {}
    for command in ("report-status", "content-delivery"):
        monkeypatch.setattr("sys.argv", ["report-agent", command, "--project", str(native_ws.store.root)])
        assert cli.main() == 0
        outputs[command] = json.loads(capsys.readouterr().out)
    assert outputs["report-status"]["content_delivery"] == selected
    assert outputs["report-status"]["content_current_review"]["overall_verdict"] is None
    assert outputs["content-delivery"]["delivery"] == selected
    assert outputs["content-delivery"]["current_review"]["overall_verdict"] is None
    assert "review" in outputs["content-delivery"]["note"].lower()
    assert Path(outputs["content-delivery"]["path"]).read_bytes() == data
    assert cs.list_objects() == objects and export_bytes() == data
