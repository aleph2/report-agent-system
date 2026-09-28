import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from openai import AsyncOpenAI

from report_agent.deep_models import GLMChatOpenAI, LocalAudit
from report_agent.store import Store


def model():
    return GLMChatOpenAI(model='glm-5.3', api_key='synthetic', base_url='https://model.invalid/v1',
                         use_responses_api=False, disable_streaming=True)


def response(reasoning='opaque-synthetic-sentinel\n  exact whitespace\n'):
    return {'id': 'synthetic', 'object': 'chat.completion', 'created': 1, 'model': 'glm-5.3',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': '', 'reasoning_content': reasoning,
                'tool_calls': [{'id': 'call-test', 'type': 'function', 'function': {
                    'name': 'add', 'arguments': '{"a":17,"b":25}'}}]}}]}


@pytest.mark.parametrize('reasoning', ['', 'opaque-synthetic-sentinel\n  exact whitespace\n', None])
async def test_sdk_receive_native_checkpoint_reopen_and_wire_preserve(tmp_path, reasoning):
    instance = model()
    requests = []

    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response(reasoning))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        sdk = AsyncOpenAI(api_key='synthetic', base_url='https://model.invalid/v1',
                          http_client=client, max_retries=0)
        instance.async_client = sdk.chat.completions
        answer = await instance.ainvoke('Synthetic checksum')
        assert answer.content == ''
        assert answer.tool_calls[0]['id'] == 'call-test'
        if reasoning is None:
            assert 'reasoning_content' not in answer.additional_kwargs
        else:
            assert answer.additional_kwargs['reasoning_content'] == reasoning
        messages = [SystemMessage('system'), HumanMessage('old question'), AIMessage('old answer'),
                    HumanMessage('checksum'), answer, ToolMessage('42', tool_call_id='call-test')]
        graph = StateGraph(MessagesState)
        graph.add_node('noop', lambda state: {})
        graph.add_edge(START, 'noop')
        graph.add_edge('noop', END)
        config = {'configurable': {'thread_id': 'protocol'}}
        path = str(tmp_path / 'checkpoints.db')
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await graph.compile(checkpointer=saver).ainvoke({'messages': messages}, config)
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            saved = (await graph.compile(checkpointer=saver).aget_state(config)).values['messages']
        await instance.ainvoke(saved)
    wire = requests[1]['messages']
    assert 'reasoning_content' not in wire[2]
    assert wire[-1]['tool_call_id'] == wire[-2]['tool_calls'][0]['id'] == 'call-test'
    if reasoning is None:
        assert 'reasoning_content' not in wire[-2]
    else:
        assert wire[-2]['reasoning_content'] == reasoning


def test_multiple_messages_keep_their_own_fields_and_summary_has_no_fabricated_field():
    instance = model()
    first = AIMessage('first', additional_kwargs={'reasoning_content': 'first opaque'})
    second = AIMessage('second', additional_kwargs={'reasoning_content': 'second opaque'})
    wire = instance._get_request_payload([HumanMessage('native summary'), first, second])['messages']
    assert 'reasoning_content' not in wire[0]
    assert [item['reasoning_content'] for item in wire[1:]] == ['first opaque', 'second opaque']
    assert first.additional_kwargs == {'reasoning_content': 'first opaque'}


def test_audit_omits_protocol_content_without_mutating_native_message(tmp_path):
    instance = model()
    answer = instance._create_chat_result(response()).generations[0].message
    store = Store(tmp_path)
    audit = LocalAudit(store, 'coordinator')
    audit.on_chat_model_start({}, [[answer]], run_id='request')
    audit.on_llm_end(LLMResult(generations=[[ChatGeneration(message=answer)]]), run_id='response')
    serialized = json.dumps(store.events())
    assert 'opaque-synthetic-sentinel' not in serialized
    assert 'reasoning_content' not in serialized
    assert 'reasoning_length' in serialized
    assert answer.additional_kwargs['reasoning_content'] == response()['choices'][0]['message']['reasoning_content']


def test_no_silent_unsupported_protocol():
    instance = model()
    with pytest.raises(ValueError, match='NONSTREAMING_CHAT_COMPLETIONS'):
        instance._get_request_payload('x', stream=True)
    instance.use_responses_api = True
    with pytest.raises(ValueError, match='NONSTREAMING_CHAT_COMPLETIONS'):
        instance._get_request_payload('x')
    with pytest.raises(ValueError, match='UNSUPPORTED_GLM_REASONING_FIELD'):
        model()._create_chat_result(response(['unsupported']))
