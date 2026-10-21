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


@pytest.mark.parametrize('strict', [False, True])
async def test_native_structured_grader_uses_supported_auto_then_persists_review(tmp_path, monkeypatch, strict, request):
    # Explicit legacy-entry migration: an assigned Reviewer invokes the bounded
    # checker. Its local saved judgment is not automatic whole-report acceptance.
    from report_agent import deep_runtime
    from report_agent.workspace import Workspace
    from report_agent.deepseek_strict import StrictCodec
    from test_deep_runtime import Driver
    from test_bounded_review import review_call
    from test_deepseek_strict import function
    from openai import AsyncOpenAI
    store = Store(tmp_path)
    store.initialize({"goal": "Check one adopted synthetic value against its supplied source.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "sources": [{"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
    current = Workspace(store)
    cs, _, refs, snapshot, _ = seed(current)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    assignment = review_call(snapshot, refs, reads=[source])
    assignment["args"].pop("supervision_plugin", None)
    configured(store.root, monkeypatch)
    monkeypatch.setenv("REPORT_DEEPSEEK_STRICT", "1" if strict else "0")
    checker = {"items": [{"scope_id": "rule-comparison", "checked_requirement_indexes": [0],
        "execution_state": "completed", "verdict": "not_satisfied",
        "observations": [{"evidence_index": 0, "locator": "claim", "observation": "Adopted B uses 70."},
                         {"evidence_index": 1, "locator": "source", "observation": "B permits 75 to 100."}],
        "check_results": [{"requirement_index": 0, "execution_state": "completed",
            "result": "70 is outside 75 to 100.", "observation_indexes": [0, 1], "remaining": ""}],
        "coverage": {"checked": ["Compared adopted value and original interval."], "unchecked": [], "blocked": [],
                     "basis": "Supplied source and claim."}, "reason": "70 is outside the supplied interval.", "findings": []}]}
    arguments = {"operation_id": "sdk-scoped-check", "scope_ids": ["rule-comparison"],
                 "source_selections": [], "content_selections": []}
    original_function = next(function(t) for t in deep_runtime.business_tools(current, "reviewer", None, None)
                             if t.__name__ == "perform_assigned_review")
    wires, responses, reviewer_turns, checker_packets, models = [], [], [], [], []
    async def handle(http_request):
        packet = json.loads(http_request.content)
        wires.append({"path": http_request.url.path, "body": packet})
        names = {t["function"]["name"] for t in packet.get("tools", [])}
        if names:
            assert "perform_assigned_review" in names and "HierarchicalResponse" not in names
            assert packet.get("tool_choice", "auto") == "auto"
            reviewer_turns.append(packet)
            if len(reviewer_turns) == 1:
                args = StrictCodec(original_function).encode(arguments) if strict else arguments
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "sdk-review-call",
                    "type": "function", "function": {"name": "perform_assigned_review", "arguments": json.dumps(args)}}]}
            else:
                feedback = next(m for m in reversed(packet["messages"]) if m["role"] == "tool")
                assert "review_ref" in feedback["content"] and "not_satisfied" in feedback["content"]
                message = {"role": "assistant", "content": "Local review saved. No whole-report acceptance claimed."}
        else:
            supplied = json.loads(packet["messages"][-1]["content"])
            checker_packets.append(supplied)
            assert supplied["assignment"]["review_requirements"][0]["required_checks"] == ["rule comparison"]
            assert supplied["evidence"][0]["object"]["ref"] == refs["claim"]
            assert supplied["evidence"][1]["object"]["ref"] == source
            assert "output_schema" in supplied
            message = {"role": "assistant", "content": json.dumps(checker)}
        response = {"id": "current-review-wire", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash", "choices": [{"index": 0,
            "finish_reason": "tool_calls" if message.get("tool_calls") else "stop", "message": message}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}}
        responses.append(response)
        return httpx.Response(200, json=response)
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[assignment]),
        AIMessage(content="Scoped review only; no delivery selected.")])
    before = cs.list_objects("ContentNode"), cs.list_objects("Criterion")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sdk = AsyncOpenAI(api_key="test-key", base_url="https://api.deepseek.com/beta" if strict else "https://api.deepseek.com",
                          http_client=client, max_retries=0)
        def factory(role):
            if role not in ("reviewer", "text_tool"):
                return driver(role)
            model = configured_model(store, role)
            model.async_client = sdk.chat.completions
            models.append(model)
            return model
        try:
            result = await deep_runtime.run_report(current, factory)
        finally:
            request.node.user_properties.append(("reviewer_mock_wire", json.dumps({"requests": wires,
                "responses": responses, "checker_packets": checker_packets}, ensure_ascii=False)))
            await sdk.close()
            for model in models:
                await model.http_async_client.aclose()
                model.http_client.close()
    assert result["last_error"] is None, result
    assert len(reviewer_turns) == 2 and len(checker_packets) == 1 and len(wires) == 3
    for wire in wires:
        if wire["body"].get("tools"):
            assert wire["path"] == ("/beta/chat/completions" if strict else "/chat/completions")
            assert all(t["function"].get("strict", False) is strict for t in wire["body"]["tools"])
    reviews = cs.list_objects("ReviewRecord")
    assert len(reviews) == 1
    review = reviews[0]
    assert review["payload"]["snapshot_ref"] == snapshot
    assert review["payload"]["items"][0]["verdict"] == "not_satisfied"
    tasks = cs.list_objects("DelegatedTask")
    assert len(tasks) == 1 and tasks[0]["payload"]["role"] == "reviewer"
    assert review["owner_id"] == "content:reviewer:" + tasks[0]["ref"]["id"]
    assert before == (cs.list_objects("ContentNode"), cs.list_objects("Criterion"))
    assert not store.get("content_delivery") and result["status"] != "reviewed_draft"
