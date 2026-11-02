"""Offline probe of the actual production middleware, SDK and save path."""
from contextvars import ContextVar
from copy import deepcopy
import asyncio
import json
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

from report_agent import review_message
from report_agent.content_store import ContentStore
from report_agent.deep_models import GLMChatOpenAI
from report_agent.deep_runtime import BusinessBoundary
from report_agent.deepseek_strict import StrictCodec
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import content_tools, role_prompt
from report_agent.prompt_provenance import AgentPromptBoundary
from report_agent.message_fields import field_dictionary
from report_agent.native_operation_tools import native_write_tools
from report_agent.operation_identity import write_id
from report_agent.review_scope_selectors import CONTRACT, IDENTITY_FIELDS
from report_agent.store import digest, encode

_CONTEXT = ContextVar('offline_review_entry', default=None)
_SAVE = ContentStore.submit_review
_VALIDATE = review_message.validate_message_binding


async def sdk_response(function, value, packet, strict, requests, raw_calls, call_id, messages=None):
    """Use the real configured adapter/SDK serialization over an in-memory HTTP transport."""
    values = value if isinstance(value, list) else [value]
    calls = []
    for index, item in enumerate(values):
        wire_args = StrictCodec(function).encode(item) if strict else item
        identity = call_id + '-' + str(index) if isinstance(value, list) else call_id
        raw_calls.append({'id': identity, 'args': deepcopy(wire_args)})
        calls.append({'id': identity, 'type': 'function',
            'function': {'name': function['name'], 'arguments': json.dumps(wire_args)}})
    async def handle(request):
        requests.append(json.loads(request.content))
        await asyncio.sleep(0)  # Exercise interleaved SDK responses, not only sequential mocks.
        return httpx.Response(200, json={'id': 'offline-' + call_id, 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                'message': {'role': 'assistant', 'content': '', 'tool_calls': calls}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        async with AsyncOpenAI(api_key='offline-not-a-secret', base_url='https://model.invalid/beta',
                               http_client=client) as sdk:
            model = GLMChatOpenAI(model='deepseek-flash', api_key='offline-not-a-secret',
                base_url='https://model.invalid/beta', use_responses_api=False, deepseek_strict=strict)
            model.async_client = sdk.chat.completions
            try:
                return await model.bind_tools([{'type': 'function', 'function': function}]).ainvoke(
                    messages if messages is not None else [HumanMessage(content=encode(packet))])
            finally:
                model.root_client.close()
                await model.root_async_client.close()


class ReviewEntryProbe:
    """Exercise production request binding and native saving; hooks inject failures only."""
    def __init__(self, workspace, monkeypatch):
        self.ws = workspace
        self.requests, self.raw_calls, self.final_checks, self.executed_identities = [], [], [], []
        self.before_save = self.before_send = None
        self.function = {'name': 'submit_review', 'description': 'Offline contract probe only.',
                         'parameters': review_message.ReviewMessage.model_json_schema()}
        def validate(contents, db, actor, binding):
            _VALIDATE(contents, db, actor, binding)
            if db.in_transaction:
                self.final_checks.append({'binding_present': binding is not None, 'transaction': True})
        def save(contents, actor, operation, submission, identity, delivery_export_ref=None, *, review_message_binding=None):
            if self.before_save:
                action, self.before_save = self.before_save, None
                action()
            self.executed_identities.append(operation)
            return _SAVE(contents, actor, operation, submission, identity, delivery_export_ref,
                         review_message_binding=review_message_binding)
        monkeypatch.setattr(ContentStore, 'submit_review', save)
        monkeypatch.setattr(review_message, 'validate_message_binding', validate)
        self.tools = native_write_tools(workspace, 'reviewer', [t for t in content_tools(workspace, 'reviewer')
            if t.__name__ == 'submit_review'])
        self.native = BusinessBoundary(workspace, 'reviewer')
        self.node = ToolNode(self.tools, awrap_tool_call=self.native.awrap_tool_call)

    async def request(self, actor, receipts, value, *, strict=False, call_id='review-save'):
        from langchain.agents.middleware.types import ModelRequest, ModelResponse
        from langchain_core.messages import SystemMessage
        from langchain_core.utils.function_calling import convert_to_openai_tool
        model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta',
                             deepseek_strict=strict)
        request = ModelRequest(model=model, tools=self.tools, state={'messages': []},
            system_message=SystemMessage(role_prompt('reviewer')), messages=[])
        async def handler(changed):
            from support.task_state_contract import moved_blocks
            field, = [p for p in moved_blocks(changed) if p['source'] == 'field_dictionary/current_request']
            packet = json.loads(field['text'])
            if self.before_send:
                self.before_send(packet)
            # Preserve the actual model-built system and schema. Corruption is tested before HTTP.
            from report_agent.live_messages import validate_wire
            function = convert_to_openai_tool(changed.tools[0])['function']
            if self.function['parameters']['properties']['evidence_indexes'].get('uniqueItems'):
                function['parameters']['properties']['evidence_indexes']['uniqueItems'] = True
            if self.before_send:
                from langchain_openai.chat_models.base import _convert_message_to_dict
                corrupted = [_convert_message_to_dict(m) for m in [changed.system_message, *changed.messages]]
                tail = json.loads(corrupted[-1]['content'].split('\n', 1)[1])
                target, = [p for p in tail['moved_blocks'] if p['source'] == 'field_dictionary/current_request']
                target['text'] = encode(packet)
                corrupted[-1]['content'] = '[host-observations]\n' + encode(tail)
                validate_wire({'tools': [{'type':'function','function':function}],
                    'messages':corrupted}, strict=False)
            answer = await sdk_response(function, value, packet, strict, self.requests, self.raw_calls,
                                        call_id, messages=[changed.system_message, *changed.messages])
            return ModelResponse(result=[answer])
        try:
            async def final_boundary(changed):
                return await AgentPromptBoundary(self.ws, 'reviewer').awrap_model_call(changed, handler)
            return (await self.native.awrap_model_call(request, final_boundary)).result[0]
        finally:
            model.root_client.close()
            await model.root_async_client.close()

    def remove_link(self, actor, answer):
        owner = [str(self.ws.store.root.resolve()), actor.id, actor.task_id]
        key = 'message_call:' + digest([owner, answer.tool_calls[0]['id']])
        with self.ws.store.connect() as db:
            db.execute('DELETE FROM state WHERE key=?', (key,))

    def graph(self, *, checkpointer=None, interrupt_before=None):
        graph = StateGraph(MessagesState)
        graph.add_node('tools', self.node)
        graph.add_edge(START, 'tools'); graph.add_edge('tools', END)
        return graph.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)

    @staticmethod
    def context_is_clear():
        from report_agent.live_messages import _TOOL, _MODEL
        return _TOOL.get() is None


async def delegate(workspace, arguments, child, strict, requests, call_id='co-delegate'):
    from deepagents.backends import StateBackend
    from deepagents.middleware.subagents import SubAgentMiddleware, CompiledSubAgent
    from langchain_core.runnables import RunnableLambda
    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.messages import SystemMessage
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from test_native_task_error_boundary import native_node
    middleware = SubAgentMiddleware(backend=StateBackend(), subagents=[CompiledSubAgent(
        name='reviewer', description='Actual independent assigned review.', runnable=RunnableLambda(child))])
    tools = [t for t in middleware.tools if t.name == 'task']
    boundary = BusinessBoundary(workspace, 'coordinator')
    model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta',
                         deepseek_strict=strict)
    async def handler(changed):
        function = convert_to_openai_tool(changed.tools[0])['function']
        answer = await sdk_response(function, arguments, {}, strict, requests, [], call_id,
                                    messages=[changed.system_message, *changed.messages])
        return ModelResponse(result=[answer])
    try:
        request = ModelRequest(model=model, tools=tools, state={'messages': []},
            system_message=SystemMessage(role_prompt('coordinator')), messages=[])
        async def final_boundary(changed):
            return await AgentPromptBoundary(workspace, 'coordinator').awrap_model_call(changed, handler)
        answer = (await boundary.awrap_model_call(request, final_boundary)).result[0]
        result = await native_node(ToolNode(tools, awrap_tool_call=boundary.awrap_tool_call), {'messages':[answer]})
        return result, answer
    finally:
        model.root_client.close()
        await model.root_async_client.close()
