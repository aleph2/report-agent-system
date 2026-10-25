"""Strict protocol roundtrip and real native graph, with synthetic offline inputs."""
import json
from inspect import iscoroutinefunction

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import AsyncOpenAI

from report_agent.deepseek_strict import StrictCodec, WireError
from report_agent.deep_models import configured_model, strict_wire_audit
from report_agent.deep_runtime import business_tools, run_report
from report_agent.hierarchical_review import HierarchicalResponse
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import ws, seed
from test_official_deepseek import configured


def function(tool):
    return convert_to_openai_tool(StructuredTool.from_function(
        coroutine=tool) if iscoroutinefunction(tool) else StructuredTool.from_function(tool))['function']


def schema_check(s):
    assert not {'oneOf', 'discriminator', 'default', 'minLength', 'minItems'} & s.keys()
    if s.get('type') == 'object':
        assert s['additionalProperties'] is False
        assert set(s['required']) == set(s['properties'])
    for k in ('properties', '$defs'):
        for child in s.get(k, {}).values():
            schema_check(child)
    for child in s.get('anyOf', []):
        schema_check(child)
    if 'items' in s:
        schema_check(s['items'])


async def test_all_native_and_business_tools_compile(tmp_path):
    # Explicit migration: compile today's published roles and native bindings;
    # the retired automatic rubric_grader/HierarchicalResponse is not an entrypoint.
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.content_store import ContentStore
    from test_bounded_review import review_call
    store = Store(tmp_path)
    store.initialize({"goal": "Inspect synthetic tool contracts only.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "sources": [{"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
    current = Workspace(store)
    cs, _, refs, snapshot, _ = seed(current)
    review = review_call(snapshot, refs)
    review["args"].pop("supervision_plugin", None)
    writer_call = invoke("task", subagent_type="writer", description="Inspect only; return observations.")
    writer_call.tool_calls[0]["id"] = "compile-writer"
    layout_call = invoke("task", subagent_type="layout", description="Inspect this assigned snapshot only.",
                         layout_snapshot_ref=snapshot)
    layout_call.tool_calls[0]["id"] = "compile-layout"
    d = Driver(coordinator=[
        writer_call,
        AIMessage(content="", tool_calls=[review]),
        layout_call,
        AIMessage(content="Unresolved; no delivery selected.")],
        writer=[AIMessage(content="No content changes.")],
        reviewer=[AIMessage(content="No independent judgment claimed.")],
        layout=[AIMessage(content="No layout or visual judgment claimed.")])
    before = cs.list_objects("ContentNode"), cs.list_objects("Criterion")
    result = await run_report(current, d)
    assert result["last_error"] is None, result
    roles = {"coordinator", "writer", "reviewer", "layout"}
    assert {role for role, _, _ in d.calls} == roles
    assert set(d.bindings) == roles
    functions = [f for batches in d.bindings.values() for batch in batches for f in batch]
    for role in sorted(roles):
        functions.extend(function(t) for t in business_tools(current, role, None, d("text_tool")))
    assert functions
    for f in functions:
        schema_check(StrictCodec(f).function["parameters"])
    assert before == (cs.list_objects("ContentNode"), cs.list_objects("Criterion"))
    assert not cs.list_objects("ReviewRecord")


def test_optional_absent_null_empty_and_open_nested_json_are_distinct():
    codec = StrictCodec({'name': 'save', 'parameters': {'type': 'object', 'properties': {
        'body': {'type': 'object', 'additionalProperties': True},
        'optional': {'anyOf': [{'type': 'string'}, {'type': 'null'}]}}, 'required': ['body']}})
    for extra in ({}, {'optional': None}, {'optional': ''}, {'optional': 'x'}):
        original = {'body': {'array': [None, True, 2, 2.5, {'kind': 'absent', 'entries': []}], 'text': 'quoted "title"\n中文'}, **extra}
        assert codec.decode(codec.encode(original)) == original
    wire = codec.encode({'body': {'a': 1}})
    wire['body']['entries'].append({'key': 'a', 'value': 2})
    with pytest.raises(WireError, match='unique'):
        codec.decode(wire)
    with pytest.raises(WireError, match='Unsupported'):
        StrictCodec({'name': 'x', 'parameters': {'type': 'object', 'patternProperties': {}}})


async def test_wire_history_preserved_and_decode_error_is_feedback(ws, monkeypatch):
    configured(ws.store.root, monkeypatch)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '1')
    f = {'name': 'save', 'parameters': {'type': 'object', 'properties': {
        'body': {'type': 'object', 'additionalProperties': True}}, 'required': ['body']}}
    encoded = StrictCodec(f).encode({'body': {'text': 'nested'}})
    wires = []
    async def handle(request):
        wires.append(json.loads(request.content))
        args = encoded if len(wires) == 1 else {'body': {'entries': [
            {'key': 'x', 'value': 1}, {'key': 'x', 'value': 2}]}}
        return httpx.Response(200, json={'id': 's', 'object': 'chat.completion', 'created': 1,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'actual-call', 'type': 'function',
                'function': {'name': 'save', 'arguments': json.dumps(args)}}]}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        m = configured_model(ws.store, 'coordinator')
        m.async_client = AsyncOpenAI(api_key='test', base_url='https://api.deepseek.com/beta', http_client=client).chat.completions
        bound = m.bind_tools([{'type': 'function', 'function': f}])
        first = await bound.ainvoke([HumanMessage(content='test')])
        assert first.tool_calls[0]['args'] == {'body': {'text': 'nested'}}
        second = await bound.ainvoke([HumanMessage(content='test'), first,
            ToolMessage(content='saved', tool_call_id='actual-call')])
    assert json.loads(wires[1]['messages'][1]['tool_calls'][0]['function']['arguments']) == encoded
    assert not second.tool_calls and len(second.invalid_tool_calls) == 1
    from report_agent.tool_argument_feedback import InvalidToolFeedback
    update = await InvalidToolFeedback().aafter_model({'messages': [second]}, None)
    assert update['jump_to'] == 'model'
    feedback = json.loads(update['messages'][0].content)
    assert feedback['code'] == 'STRICT_WIRE_DECODE_FAILED'
    assert feedback['execution_state'] == 'not_executed'


def test_actual_union_failure_reports_missing_wire_field(ws):
    f = next(function(t) for t in business_tools(ws, 'coordinator', None, None) if t.__name__ == 'commit_objects')
    from test_content_tool_inputs import node
    codec = StrictCodec(f)
    wire = codec.encode({'operation_id': 'diagnostic', 'objects': [node('n')]})
    del wire['objects'][0]['previous_ref']
    with pytest.raises(WireError, match=r"objects: \[0\].*missing=\['previous_ref'\]"):
        codec.decode(wire)


async def test_actual_http_audit_excludes_headers_messages_and_reasoning(ws):
    schema = {'type': 'function', 'function': {'name': 'x', 'strict': True, 'parameters': {'type': 'object'}}}
    payload = {'model': 'deepseek-flash', 'thinking': {'type': 'enabled'}, 'reasoning_effort': 'max',
        'tools': [schema], 'messages': [{'role': 'assistant', 'reasoning_content': 'private-test-reasoning'}]}
    request = httpx.Request('POST', 'https://api.deepseek.com/beta/chat/completions',
        headers={'Authorization': 'Bearer secret-test-key'}, json=payload)
    await strict_wire_audit(ws.store, 'coordinator')(request)
    events = json.dumps(ws.store.events())
    assert 'private-test-reasoning' not in events and 'secret-test-key' not in events
    assert 'deep_model_wire' in events and '/beta/chat/completions' in events
