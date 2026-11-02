"""Step 0: an active offer authenticates the adapter's lossless history projection.

Only synthetic SDK MockTransport responses; no provider acceptance, model
judgment, business-tool execution, or paid accounting is claimed.
"""
from copy import deepcopy
import json
import socket

import httpx
import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.deep_models import GLMChatOpenAI
from report_agent.deep_runtime import BusinessBoundary
from report_agent.deepseek_strict import StrictCodec, VERSION
from report_agent.hierarchical_tools import role_prompt
from report_agent.live_messages import validate_wire
from report_agent.prompt_provenance import (AgentPromptBoundary, PromptCompositionError,
    _CALL, admit_prompt_request)
from report_agent.task_context import TaskContext
from test_deliverable_declaration_v4 import case
from test_host_delivery_bindings import commission, change_tail


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    def refused(*args, **kwargs):
        pytest.fail('Step 0 is offline; only SDK MockTransport may dispatch')
    monkeypatch.setattr(socket.socket, 'connect', refused)
    monkeypatch.setattr(socket, 'create_connection', refused)


CASES = [
    pytest.param('glm-5.3', False, 'plain', id='glm-plain'),
    pytest.param('glm-5.3', False, 'reasoning', id='glm-reasoning'),
    pytest.param('deepseek-flash', True, 'plain', id='deepseek-plain'),
    pytest.param('deepseek-flash', True, 'reasoning', id='deepseek-reasoning'),
    pytest.param('deepseek-flash', True, 'strict', id='deepseek-strict'),
    pytest.param('deepseek-flash', True, 'both', id='deepseek-both'),
    pytest.param('glm-5.3', False, 'v1', id='glm-native-v1-blocks'),
    pytest.param('deepseek-flash', True, 'v1', id='deepseek-native-v1-blocks'),
]


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
@pytest.mark.parametrize('model_name,strict,variant', CASES)
async def test_saved_sdk_protocol_history_passes_current_offer_without_losing_tamper_protection(
        case, role, model_name, strict, variant):
    with commission(case, role) as (ws, offered, _, cs):
        ws.store.set('context_policy', 'stateful-tools-v1')
        def read_fixture(query: str, limit: int | None = None) -> str:
            """Synthetic read schema; no business execution is permitted."""
            pytest.fail('No business tool may execute in a wire-projection test')
        read = StructuredTool.from_function(read_fixture)
        business_args = {'query': 'synthetic'}  # Omitted optional limit exercises reversible strict encoding.
        has_reasoning = variant in ('reasoning', 'both')
        has_call = variant in ('strict', 'both', 'v1') or (not strict and has_reasoning)
        reason = 'SYNTHETIC_OPAQUE_PROTOCOL_X'
        raw_args = StrictCodec(convert_to_openai_tool(read)['function']).encode(business_args) if strict else business_args
        raw_calls = [{'id': 'prior-read', 'type': 'function', 'function': {
            'name': read.name, 'arguments': json.dumps(raw_args, separators=(',', ':'))}}] if has_call else []
        expected_calls = deepcopy(raw_calls)
        if has_call and not strict:
            # The ordinary SDK parses and re-serializes arguments with its
            # default JSON spacing; only strict_wire promises exact raw replay.
            expected_calls[0]['function']['arguments'] = json.dumps(business_args, ensure_ascii=False)
        returned = {'role': 'assistant', 'content': 'Synthetic prior response.',
            **({'tool_calls': deepcopy(raw_calls)} if has_call else {}),
            **({'reasoning_content': reason} if has_reasoning else {})}
        dispatched = []
        async def admit(request):
            admit_prompt_request(request)
        async def transport(request):
            wire = json.loads(request.content)
            call = _CALL.get()
            if not dispatched:
                assert call is None, 'The prior synthetic response precedes the active task/review offer'
                reply = deepcopy(returned)
            else:
                assert len(dispatched) == 1, 'No hidden retry or duplicate physical request'
                assert call is not None and call['purpose'] == role
                validate_wire(wire, strict=strict)
                prior_wire, = [m for m in wire['messages'] if m['role'] == 'assistant']
                assert ('reasoning_content' in prior_wire) is has_reasoning
                assert prior_wire.get('reasoning_content') == (reason if has_reasoning else None)
                assert prior_wire.get('tool_calls', []) == expected_calls
                if variant == 'v1':
                    assert prior_wire['content'] == [{'type': 'text', 'text': 'Synthetic prior response.'}]
                if has_call:
                    position = wire['messages'].index(prior_wire)
                    assert wire['messages'][position + 1]['role'] == 'tool'
                    assert wire['messages'][position + 1]['tool_call_id'] == 'prior-read'

                changed_content = deepcopy(wire)
                changed_content['messages'][1]['content'] += 'x'
                changed_protocol = deepcopy(wire)
                target, = [m for m in changed_protocol['messages'] if m['role'] == 'assistant']
                target['reasoning_content'] = reason[:-1] + 'Y' if has_reasoning else 'x'
                corruptions = [changed_content, changed_protocol]
                if has_call:
                    changed_args = deepcopy(wire)
                    target, = [m for m in changed_args['messages'] if m['role'] == 'assistant']
                    target['tool_calls'][0]['function']['arguments'] += ' '
                    corruptions.append(changed_args)
                for changed in corruptions:
                    with pytest.raises(PromptCompositionError, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
                        validate_wire(changed, strict=strict)
                counters_only = change_tail(wire, lambda packet: packet['current_execution_observations'].update(
                    execution_resources={'reserved_http_attempts': 17},
                    execution_token_resources={'recorded_tokens': 29}))
                validate_wire(counters_only, strict=strict)
                reply = {'role': 'assistant', 'content': 'Synthetic next response; no business action.'}
            dispatched.append({'call_id': call['call_id'] if call else None})
            return httpx.Response(200, request=request, json={'id': 'offline-step0-' + str(len(dispatched)),
                'object': 'chat.completion', 'created': 1, 'model': model_name,
                'choices': [{'index': 0, 'finish_reason': 'tool_calls' if reply.get('tool_calls') else 'stop',
                    'message': reply}], 'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport), event_hooks={'request': [admit]}) as client:
            model = GLMChatOpenAI(model=model_name, api_key='offline-only',
                base_url='https://offline.invalid/beta' if strict else 'https://offline.invalid/v1',
                http_async_client=client, deepseek_strict=strict, max_retries=0,
                use_responses_api=False, disable_streaming=True)
            try:
                user = HumanMessage(content='Review the synthetic evidence within the current assignment.')
                previous = await model.bind_tools([read]).ainvoke([user])
                assert len(dispatched) == 1 and not previous.invalid_tool_calls
                assert ('reasoning_content' in previous.additional_kwargs) is has_reasoning
                assert previous.additional_kwargs.get('reasoning_content') == (reason if has_reasoning else None)
                if strict:
                    assert previous.additional_kwargs['strict_wire'] == {'version': VERSION, 'tool_calls': raw_calls}
                else:
                    assert 'strict_wire' not in previous.additional_kwargs
                assert previous.tool_calls == ([{'id': 'prior-read', 'type': 'tool_call',
                    'name': read.name, 'args': business_args}] if has_call else [])

                # Exercise actual adapter response metadata and the native message's
                # persisted JSON, not hand-injected additional_kwargs alone.
                original_previous = deepcopy(previous.model_dump(mode='json'))
                stored_message = previous
                if variant == 'v1':
                    # Native checkpoint content blocks, including a tool-call
                    # block, pass through the SDK's v1 compatibility conversion.
                    stored_message = previous.model_copy(update={'content': [
                        {'type': 'text', 'text': 'Synthetic prior response.',
                         'annotations': [{'type': 'non_standard_annotation', 'value': {'synthetic': True}}]},
                        {'type': 'tool_call', **deepcopy(previous.tool_calls[0])}]})
                saved = stored_message.model_dump(mode='json')
                ws.store.set('step0_saved_prior_message', saved)
                prior = AIMessage.model_validate(ws.store.get('step0_saved_prior_message'))
                unchanged = deepcopy(prior.model_dump(mode='json'))
                history = [user, prior, *([ToolMessage(content='Synthetic exact tool result.',
                    name=read.name, tool_call_id='prior-read')] if has_call else [])]
                request = ModelRequest(model=model, tools=[*offered, read], messages=history,
                    state={'messages': history}, system_message=SystemMessage(content=role_prompt(
                        role, interface_profile='review-interfaces-v4')))
                async def sdk(final):
                    return ModelResponse(result=[await model.bind_tools(final.tools).ainvoke([
                        final.system_message, *final.messages])])
                async def declared(bound):
                    return await AgentPromptBoundary(ws, role).awrap_model_call(bound, sdk)
                async def business(projected):
                    return await BusinessBoundary(ws, role).awrap_model_call(projected, declared)
                response = await TaskContext(ws, role).awrap_model_call(request, business)
                assert len(dispatched) == 2 and dispatched[1]['call_id']
                assert prior.model_dump(mode='json') == unchanged
                assert previous.model_dump(mode='json') == original_previous
                assert ws.store.get('step0_saved_prior_message') == saved
                answer = next(m for m in response.result if isinstance(m, AIMessage))
                offer = ws.store.get(answer.additional_kwargs['message_contract_offer'])
                assert offer['prompt_call_id'] == dispatched[1]['call_id']
                assert offer['owner'][0] == str(ws.store.root.resolve())
                assert not cs.list_objects('ReviewRecord'), 'Protocol authentication performs no review or save'
            finally:
                model.root_client.close()
                await model.root_async_client.close()


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
async def test_non_ai_native_content_is_not_rewritten_only_by_offer_projection(case, role):
    with commission(case, role) as (ws, tools, _, cs):
        ws.store.set('context_policy', 'stateful-tools-v1')
        content = [{'type': 'text', 'text': 'Synthetic human instruction.',
            'annotations': [{'type': 'non_standard_annotation', 'value': {'synthetic': 'keep this metadata'}}]}]
        human = HumanMessage(content=deepcopy(content))
        unchanged = deepcopy(human.model_dump(mode='json'))
        dispatched = []
        async def transport(request):
            wire = json.loads(request.content)
            call = _CALL.get()
            if dispatched:
                assert len(dispatched) == 1 and call is not None and call['purpose'] == role
                validate_wire(wire, strict=False)
            else:
                assert call is None
            original_human, = [m for m in wire['messages'] if m['role'] == 'user' and m['content'] == content]
            assert original_human['content'] == content
            dispatched.append(call['call_id'] if call else None)
            return httpx.Response(200, request=request, json={'id': 'offline-non-ai',
                'object': 'chat.completion', 'created': 1, 'model': 'glm-5.3',
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                    'role': 'assistant', 'content': 'Synthetic response.'}}],
                'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            model = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
                base_url='https://offline.invalid/v1', http_async_client=client,
                use_responses_api=False, disable_streaming=True, max_retries=0)
            try:
                await model.bind_tools(tools).ainvoke([human])
                assert dispatched == [None], 'First prove the real SDK preserves these non-AI blocks'
                request = ModelRequest(model=model, tools=tools, messages=[human], state={'messages': [human]},
                    system_message=SystemMessage(content=role_prompt(role, interface_profile='review-interfaces-v4')))
                async def sdk(final):
                    return ModelResponse(result=[await model.bind_tools(final.tools).ainvoke([
                        final.system_message, *final.messages])])
                async def declared(bound):
                    return await AgentPromptBoundary(ws, role).awrap_model_call(bound, sdk)
                async def business(projected):
                    return await BusinessBoundary(ws, role).awrap_model_call(projected, declared)
                await TaskContext(ws, role).awrap_model_call(request, business)
                assert len(dispatched) == 2 and dispatched[1]
                assert human.model_dump(mode='json') == unchanged
                assert not cs.list_objects('ReviewRecord')
            finally:
                model.root_client.close()
                await model.root_async_client.close()


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
@pytest.mark.parametrize('bad_reason', [None, {'synthetic': 'not a string'}], ids=['null', 'object'])
async def test_invalid_reasoning_type_cannot_be_silently_dropped_to_satisfy_offer(case, role, bad_reason):
    with commission(case, role) as (ws, tools, _, cs):
        ws.store.set('context_policy', 'stateful-tools-v1')
        def no_dispatch(request):
            pytest.fail('An invalid protocol field must be refused before SDK dispatch')
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_dispatch)) as client:
            model = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
                base_url='https://offline.invalid/v1', http_async_client=client,
                use_responses_api=False, disable_streaming=True, max_retries=0)
            history = [HumanMessage(content='Synthetic current instruction.'),
                AIMessage(content='Synthetic prior response.', additional_kwargs={'reasoning_content': bad_reason})]
            original = deepcopy([m.model_dump(mode='json') for m in history])
            request = ModelRequest(model=model, tools=tools, messages=history, state={'messages': history},
                system_message=SystemMessage(content=role_prompt(role, interface_profile='review-interfaces-v4')))
            async def sdk(final):
                return ModelResponse(result=[await model.bind_tools(final.tools).ainvoke([
                    final.system_message, *final.messages])])
            async def declared(bound):
                return await AgentPromptBoundary(ws, role).awrap_model_call(bound, sdk)
            async def business(projected):
                return await BusinessBoundary(ws, role).awrap_model_call(projected, declared)
            try:
                with pytest.raises(ValueError, match='UNSUPPORTED_GLM_REASONING_FIELD'):
                    await TaskContext(ws, role).awrap_model_call(request, business)
                assert [m.model_dump(mode='json') for m in history] == original
                assert not cs.list_objects('ReviewRecord')
            finally:
                model.root_client.close()
                await model.root_async_client.close()
