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
from report_agent.runtime import run_task
from report_agent.store import Store
from report_agent.tools import material_tools


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


async def test_adk_can_reuse_without_analysis(tmp_path):
    store = project(tmp_path, reuse=True)
    decision = ScriptedModel(script=["select", "final"])
    unused_text = ScriptedModel(script=[])
    status = await run_task(store, decision, unused_text)
    assert status["status"] == "draft_ready"
    assert not unused_text.requests
    assert len(store.artifacts()) == 1
    assert store.artifacts()[0]["origin"] == "fixture_existing"


async def test_adk_tool_loop_and_recovery_of_committed_work(tmp_path):
    store = project(tmp_path)
    interrupted = await run_task(store, ScriptedModel(script=["read", "save", "fail"]), ScriptedModel())
    assert interrupted["status"] == "failed"
    assert interrupted["last_error"]["type"] == "RuntimeError"
    artifact_id = store.artifacts()[0]["id"]
    reopened = Store(tmp_path)
    status = await run_task(reopened, ScriptedModel(script=["select", "final"]), ScriptedModel())
    assert status["status"] == "draft_ready"
    assert status["selected_artifact"] == artifact_id
    assert len(reopened.artifacts()) == 1
    assert any(e["kind"] == "agent_event" for e in reopened.events())


async def test_final_text_alone_does_not_complete_task(tmp_path):
    store = project(tmp_path)
    status = await run_task(store, ScriptedModel(script=["final"]), ScriptedModel())
    assert status["status"] == "needs_attention"


async def test_selected_result_survives_tail_failure_without_replay(tmp_path):
    store = project(tmp_path, reuse=True)
    decision = ScriptedModel(script=["select", "fail"])
    await run_task(store, decision, ScriptedModel())
    assert store.status()["status"] == "draft_ready"
    assert store.status()["last_error"]["result_committed"]
    unused = ScriptedModel()
    reopened = await run_task(Store(tmp_path), unused, ScriptedModel())
    assert reopened["status"] == "draft_ready"
    assert not unused.requests


async def test_selected_result_survives_actual_task_cancellation(tmp_path):
    store = project(tmp_path, reuse=True)
    waiting = asyncio.Event()
    task = asyncio.create_task(run_task(store, ScriptedModel(script=["select", "wait"], waiting=waiting), ScriptedModel()))
    await asyncio.wait_for(waiting.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.get("status") == "draft_ready"
    assert store.get("last_error")["result_committed"]
    unused = ScriptedModel()
    await run_task(Store(tmp_path), unused, ScriptedModel())
    assert not unused.requests


async def test_startup_error_is_visible(tmp_path, monkeypatch):
    async def fail_session(*args, **kwargs):
        raise RuntimeError("Synthetic session startup failure")

    monkeypatch.setattr("report_agent.runtime.InMemorySessionService.create_session", fail_session)
    store = project(tmp_path)
    result = await run_task(store, ScriptedModel(), ScriptedModel())
    assert result["status"] == "failed"
    assert result["last_error"]["type"] == "RuntimeError"


async def test_error_event_is_not_success(tmp_path):
    result = await run_task(project(tmp_path), ScriptedModel(script=["error_event"]), ScriptedModel())
    assert result["status"] == "failed"


@pytest.mark.parametrize("status,error,expected", [
    ("failed", None, 1), ("interrupted", None, 1), ("needs_attention", None, 2),
    ("draft_ready", {"type": "RuntimeError"}, 2), ("draft_ready", None, 0),
])
def test_cli_exit_code(tmp_path, monkeypatch, status, error, expected):
    from report_agent import cli

    project(tmp_path)
    async def stub(*args, **kwargs):
        return {"status": status, "last_error": error}

    from report_agent import runtime
    monkeypatch.setattr(runtime, "run_task", stub)
    monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
    assert cli.main() == expected


async def test_explicit_feedback_reopens_without_mutating_saved_materials(tmp_path):
    store = project(tmp_path, reuse=True)
    old = store.artifacts()[0]
    store.select_result(old["id"])
    feedback = store.add_feedback("Add a concise source-grounded timing limitation.")
    assert store.get("status") == "ready"
    assert store.get("selected_artifact") is None
    assert store.artifacts()[0] == old
    model = ScriptedModel(script=["read", "save", "select", "final"])
    result = await run_task(store, model, ScriptedModel())
    sent = json.loads(model.requests[0].contents[0].parts[0].text)
    assert sent["feedback"] == [feedback]
    assert result["status"] == "draft_ready"
    assert result["selected_artifact"] != old["id"]
    assert store.artifacts()[0] == old
    assert len(store.artifacts()) == 2


def test_feedback_cannot_interrupt_active_worker(tmp_path):
    store = project(tmp_path)
    with store.run_lock():
        with pytest.raises(RuntimeError, match="PROJECT_ALREADY_RUNNING"):
            store.add_feedback("New feedback")
    assert not store.get("feedback")


async def test_configuration_failure_is_persisted(tmp_path, monkeypatch):
    monkeypatch.delenv("REPORT_MODEL", raising=False)
    result = await run_task(project(tmp_path))
    assert result["status"] == "failed"
    assert result["last_error"]["type"] == "ValueError"


async def test_completed_result_does_not_require_provider_config(tmp_path, monkeypatch):
    monkeypatch.delenv("REPORT_MODEL", raising=False)
    store = project(tmp_path, reuse=True)
    store.select_result(store.artifacts()[0]["id"])
    result = await run_task(store)
    assert result["status"] == "draft_ready"
    assert result["last_error"] is None
