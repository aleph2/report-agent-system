import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.deep_models import configured_model, bind_grader_trial
from report_agent.store import Store
from report_agent.vision import _observe
from test_vision import VisionModel
from test_hierarchical_content import ws, seed


def configured(tmp_path, monkeypatch):
    for key, value in {"REPORT_MODEL": "deepseek-flash", "REPORT_BASE_URL": "https://api.deepseek.com",
                       "REPORT_API_KEY": "test-key", "REPORT_REASONING_EFFORT": "max"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("REPORT_GRADER_MODEL", raising=False)
    return Store(tmp_path)


async def test_official_wire_parameters_and_opaque_tool_turn_roundtrip(tmp_path, monkeypatch):
    store = configured(tmp_path, monkeypatch)
    sent = []
    async def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "ok", "reasoning_content": "opaque-test-field"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        from openai import AsyncOpenAI
        model = configured_model(store, "rubric_grader")
        model.async_client = AsyncOpenAI(api_key="test-key", base_url="https://api.deepseek.com", http_client=client, max_retries=0).chat.completions
        result = await model.ainvoke([HumanMessage(content="Check"), AIMessage(content="", additional_kwargs={"reasoning_content": "opaque-request-field"},
            tool_calls=[{"name": "read", "args": {}, "id": "t"}]), ToolMessage(content="data", tool_call_id="t")])
    assert result.content == "ok"
    assert sent[0]["max_tokens"] == 131072 and "max_completion_tokens" not in sent[0]
    assert sent[0]["thinking"] == {"type": "enabled"} and sent[0]["reasoning_effort"] == "max"
    assert sent[0]["messages"][1]["reasoning_content"] == "opaque-request-field"
    assert model.max_retries == 0
    assert "opaque-request-field" not in json.dumps(store.events())
    assert "opaque-test-field" not in json.dumps(store.events())


def test_official_trial_requires_explicit_isolation_and_preserves_binding(tmp_path, monkeypatch):
    store = configured(tmp_path, monkeypatch)
    store.initialize({"goal": "test", "sources": [{"id": "s", "content": "test", "coverage": "complete"}]})
    with pytest.raises(RuntimeError, match="ISOLATED"):
        bind_grader_trial(store)
    store.set("manifest", {**store.manifest, "trial_service": "deepseek-official"})
    bind_grader_trial(store)
    monkeypatch.setenv("REPORT_MODEL", "glm-5.3")
    with pytest.raises(RuntimeError, match="SWITCH_REQUIRES"):
        bind_grader_trial(store)


async def test_official_vision_uses_official_alias(tmp_path):
    model = VisionModel()
    model.base_url = "https://api.deepseek.com"
    model.returned_model = "deepseek-flash"
    result = await _observe(Store(tmp_path), b"fake-png", {"source_id": "s"}, "Read", model)
    assert result["status"] == "observed"
    assert model.calls[0]["model"] == "deepseek-flash"


async def test_native_structured_grader_uses_supported_auto_then_persists_review(ws, monkeypatch):
    from report_agent import deep_runtime
    from report_agent.content_export import export_snapshot
    from report_agent.hierarchical_tools import actor_for
    from test_review_coverage import covered_seed, review_data
    from hierarchical_fixtures import delivery_evidence
    from openai import AsyncOpenAI
    cs, actor, refs, snapshot, _ = covered_seed(ws)
    configured(ws.store.root, monkeypatch)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    ws.store.set("content_delivery", {"snapshot_ref": snapshot, "export_ref": export, "ending_reason": "preserve_unresolved"})
    data = review_data(cs, refs, snapshot)
    data["delivery_checks"] = delivery_evidence(cs, snapshot, export)
    wires = []
    async def handle(request):
        payload = json.loads(request.content)
        wires.append(payload)
        names = {t["function"]["name"] for t in payload.get("tools", [])}
        is_grader = "HierarchicalResponse" in names
        if is_grader:
            assert payload["tool_choice"] == "auto"
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": "grade", "type": "function", "function": {
                "name": "HierarchicalResponse", "arguments": json.dumps({"explanation": "Protocol fixture", "review": data})}}]}
        else:
            message = {"role": "assistant", "content": "Saved delivery selected."}
        return httpx.Response(200, json={"id": "native-wire-test", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "tool_calls" if is_grader else "stop", "message": message}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sdk = AsyncOpenAI(api_key="test-key", base_url="https://api.deepseek.com", http_client=client, max_retries=0)
        def factory(role):
            model = configured_model(ws.store, role)
            model.async_client = sdk.chat.completions
            return model
        result = await deep_runtime.run_report(ws, factory)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft"
    assert result["content_final_review"]["object_coverage"]["complete"]
    assert any("HierarchicalResponse" in {t["function"]["name"] for t in p.get("tools", [])} for p in wires)
