"""Actual tool schemas and native boundaries; fake responses do not prove report quality."""
from copy import deepcopy
import json
import socket

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai import AsyncOpenAI
from pydantic import ValidationError

from report_agent import deep_runtime, deepseek_strict
from report_agent.content_models import ContentNode
from report_agent.content_store import ContentStore
from report_agent.deep_models import configured_model
from report_agent.deepseek_strict import StrictCodec, WireError, json_value
from report_agent.tool_argument_feedback import InvalidToolFeedback
from test_deep_runtime import Driver, call, invoke
from test_deepseek_strict import function, schema_check
from test_official_deepseek import configured
from test_task_supervision import ws


@pytest.fixture(autouse=True)
def deny_real_network(monkeypatch):
    """Deny actual sockets; preserve HTTPX MockTransport's real SDK path."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    for name in ("connect", "connect_ex", "sendto"):
        original = getattr(socket.socket, name)
        def deny(sock, *args, _original=original, **kwargs):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise OSError("STRICT_TEST_NETWORK_DENIED")
            return _original(sock, *args, **kwargs)
        monkeypatch.setattr(socket.socket, name, deny)


def exact_json(value):
    # JSON distinguishes true from 1, unlike Python's nested dict equality.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def actual_commit(ws):
    return next(function(t) for t in deep_runtime.business_tools(ws, "writer", None, None)
                if t.__name__ == "commit_objects")


PAYLOADS = [
    {"kind": "block", "body": {"text": "Source-grounded paragraph.", "aux": {"a": [None, True, 1, 1.5]}},
     "qualifiers": {"condition": None}, "claim_kind": "fact"},
    {"kind": "table", "body": {"columns": ["A", {"label": "B"}],
        "rows": [[None, {"values": [False, 2, 2.5]}]], "footnote": None,
        "auxiliary": {"kind": "present", "extra": []}}, "qualifiers": {}, "claim_kind": "inference"},
    {"kind": "figure", "body": {"source_id": "s", "caption": "Source figure", "page": 1,
        "auxiliary": [None, {"preserve": True}]}, "qualifiers": {}, "claim_kind": "fact"},
]


def arguments(payload):
    return {"operation_id": "strict-test", "objects": [{"client_key": "n", "type": "ContentNode", "payload": payload}]}


@pytest.mark.parametrize("payload", PAYLOADS, ids=["text", "open-table", "figure"])
def test_actual_commit_roundtrip_preserves_conditionals_and_open_fields(ws, payload):
    codec = StrictCodec(actual_commit(ws))
    original = arguments(deepcopy(payload))
    frozen = deepcopy(original)
    wire = codec.encode(original)
    schema_check(codec.function["parameters"])
    assert codec.function["strict"] is True
    assert "previous_ref" in wire["objects"][0]  # The outer typed wire remains inspectable.
    assert exact_json(codec.decode(wire)) == exact_json(original) == exact_json(frozen)
    assert not ContentStore(ws.store).list_objects()


@pytest.mark.parametrize("kind,missing", [("block", "text"), ("figure", "page")])
def test_required_content_fields_are_rejected_on_encode_and_received_wire(ws, kind, missing):
    codec = StrictCodec(actual_commit(ws))
    payload = deepcopy(PAYLOADS[0] if kind == "block" else PAYLOADS[2])
    valid = arguments(payload)
    wire = codec.encode(valid)
    invalid = deepcopy(payload)
    del invalid["body"][missing]
    with pytest.raises(WireError, match="Business schema"):
        codec.encode(arguments(invalid))
    # Deliberately malformed model response: bypass only the fake encoder's
    # validation, never the real decoder or original business schema.
    assert wire["objects"][0]["payload"]["kind"] == "present"
    wire["objects"][0]["payload"]["value"] = json_value(invalid, True)
    with pytest.raises(WireError):
        codec.decode(wire)
    assert not ContentStore(ws.store).list_objects()


def test_local_definitions_and_union_branches_retain_root_context():
    schema = {"$defs": {"ObjectValue": {"type": "object", "properties": {"count": {"type": "integer"}},
        "required": ["count"], "additionalProperties": True}}, "type": "object", "properties": {
        "choice": {"anyOf": [{"$ref": "#/$defs/ObjectValue"}, {"type": "string", "minLength": 2}]},
        "optional": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["choice"], "additionalProperties": False}
    codec = StrictCodec({"name": "local_refs", "parameters": schema})
    for value in [{"choice": "ok"}, {"choice": {"count": 2, "extra": [None, False]}},
                  {"choice": {"count": 3}, "optional": None}, {"choice": "ok", "optional": ""}]:
        assert exact_json(codec.decode(codec.encode(value))) == exact_json(value)
    for value in [{"choice": {"count": True}}, {"choice": "x"}, {}]:
        with pytest.raises(WireError):
            codec.encode(value)
    # Explicit null remains different from absent in the existing outer envelope.
    assert codec.encode({"choice": "ok"}) != codec.encode({"choice": "ok", "optional": None})


@pytest.mark.parametrize("reference", ["https://schema.invalid/private", "file:///private/schema", "../schema.json"])
def test_external_schema_references_are_rejected_before_retrieval(monkeypatch, reference):
    retrievals = []
    def forbidden(uri):
        retrievals.append(uri)
        raise AssertionError("Schema retrieval must not be attempted")
    monkeypatch.setattr(deepseek_strict, "deny_schema_retrieval", forbidden)
    with pytest.raises(WireError, match="External schema references"):
        StrictCodec({"name": "remote", "parameters": {"type": "object", "properties": {"value": {"$ref": reference}},
            "additionalProperties": True}})
    assert retrievals == []


def test_adapted_subtree_still_rejects_unknown_schema_keywords():
    with pytest.raises(WireError, match="Unsupported.*patternProperties"):
        StrictCodec({"name": "unknown", "parameters": {"type": "object", "properties": {"value": {
            "type": "object", "properties": {"x": {"type": "string"}},
            "additionalProperties": True, "patternProperties": {"x": {"type": "string"}}}}}})


async def test_ragged_table_model_rule_and_raw_native_admission_never_save(ws):
    malformed = deepcopy(PAYLOADS[1])
    malformed["body"]["rows"] = [[1]]
    codec = StrictCodec(actual_commit(ws))
    received = codec.decode(codec.encode(arguments(malformed)))
    # Rectangularity is an existing business-model rule, not a JSON Schema promise.
    ContentNode.model_validate(PAYLOADS[1])
    with pytest.raises(ValidationError, match="RECTANGULAR_ROWS"):
        ContentNode.model_validate(received["objects"][0]["payload"])
    def rejection(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "commit_objects")
        # Raw substantive writes are rejected before Store payload validation.
        error = json.loads(message.content)
        assert message.status == "error"
        assert error["accepted"] is False and error["ok"] is False
        assert error["code"] == "SUBSTANTIVE_CONTENT_REQUIRES_TEXT_WORK"
        return AIMessage(content="Raw substantive write rejected; no report saved.")
    driver = Driver(coordinator=[invoke("task", subagent_type="writer", description="Check the received table boundary."),
        AIMessage(content="No successful result or review is claimed.")],
        writer=[AIMessage(content="", tool_calls=[call("commit_objects", received)]), rejection])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert not ContentStore(ws.store).list_objects("ContentNode")
    assert not ContentStore(ws.store).list_objects("ReviewRecord")
    assert not any(role == "text_tool" for role, _, _ in driver.calls)


async def test_actual_sdk_strict_wire_keeps_history_and_rejects_invalid_business_subtree(ws, monkeypatch, request):
    configured(ws.store.root, monkeypatch)
    monkeypatch.setenv("REPORT_DEEPSEEK_STRICT", "1")
    f = actual_commit(ws)
    codec = StrictCodec(f)
    encoded = codec.encode(arguments(PAYLOADS[0]))
    bad = deepcopy(encoded)
    missing_text = deepcopy(PAYLOADS[0])
    del missing_text["body"]["text"]
    bad["objects"][0]["payload"]["value"] = json_value(missing_text, True)
    requests, responses = [], []
    async def handle(request):
        requests.append(json.loads(request.content))
        value = encoded if len(requests) == 1 else bad
        response = {"id": "strict-local", "object": "chat.completion", "created": 1,
            "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "received", "type": "function",
                    "function": {"name": f["name"], "arguments": json.dumps(value)}}]}}]}
        responses.append(deepcopy(response))
        return httpx.Response(200, json=response)
    model = configured_model(ws.store, "coordinator")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sdk = AsyncOpenAI(api_key="test", base_url="https://api.deepseek.com/beta", http_client=client, max_retries=0)
        model.async_client = sdk.chat.completions
        try:
            bound = model.bind_tools([{"type": "function", "function": f}])
            first = await bound.ainvoke([HumanMessage(content="Synthetic I/O contract only.")])
            assert exact_json(first.tool_calls[0]["args"]) == exact_json(arguments(PAYLOADS[0]))
            second = await bound.ainvoke([HumanMessage(content="Synthetic I/O contract only."), first,
                ToolMessage(content="Observed only; no business dispatch.", tool_call_id="received")])
        finally:
            request.node.user_properties.append(("strict_mock_wire", exact_json({
                "requests": requests, "responses": responses,
                "valid_wire": encoded, "invalid_wire": bad})))
            await sdk.close()
            await model.http_async_client.aclose()
            model.http_client.close()
    for request in requests:
        assert all(t["function"]["strict"] is True for t in request["tools"])
        for tool in request["tools"]:
            schema_check(tool["function"]["parameters"])
    replayed = requests[1]["messages"][1]["tool_calls"][0]["function"]["arguments"]
    assert exact_json(json.loads(replayed)) == exact_json(encoded)
    assert not second.tool_calls and len(second.invalid_tool_calls) == 1
    update = await InvalidToolFeedback().aafter_model({"messages": [second]}, None)
    feedback = json.loads(update["messages"][0].content)
    assert feedback["code"] == "STRICT_WIRE_DECODE_FAILED"
    assert feedback["execution_state"] == "not_executed"
    assert not ContentStore(ws.store).list_objects()
