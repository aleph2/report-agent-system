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
from report_agent.deep_models import configured_model
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


async def test_all_native_and_business_tools_compile(ws):
    seed(ws)
    d = Driver(coordinator=[invoke('task', subagent_type='writer', description='Inspect only; return observations.'),
                            AIMessage(content='Unresolved; no delivery selected.')],
               writer=[AIMessage(content='No content changes.')])
    result = await run_report(ws, d)
    assert result['last_error'] is None, result
    assert any(role == 'writer' for role, _, _ in d.calls)
    functions = [s for bindings in d.bindings.values() for batch in bindings for s in batch]
    for role in ('coordinator', 'writer', 'reviewer', 'rubric_grader'):
        functions.extend(function(t) for t in business_tools(ws, role, None, d('text_tool')))
    functions.append(convert_to_openai_tool(HierarchicalResponse)['function'])
    for f in functions:
        schema_check(StrictCodec(f).function['parameters'])


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
