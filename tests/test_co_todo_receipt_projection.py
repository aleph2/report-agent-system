from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from report_agent.prompt_provenance import project_plan_history
from report_agent.store import encode
from test_deliverable_declaration_v4 import case


def make_request(messages):
    todos = next((m.tool_calls[0]['args']['todos'] for m in reversed(messages) if isinstance(m, AIMessage) and m.tool_calls and 'todos' in m.tool_calls[0]['args']), [])
    request = SimpleNamespace(messages=messages, state={'messages': messages, 'todos':todos}, system_message=SystemMessage('Current task bindings and navigation previews.\n'+encode({'native_current_plan':todos})))
    request.override = lambda **changes: SimpleNamespace(**{**request.__dict__, **changes})
    return request


def exchange(name, todos):
    ai = AIMessage('', id='ai-'+name, tool_calls=[
        {'name': 'write_todos', 'args': {'todos': todos}, 'id': name, 'type': 'tool_call'}])
    result = ToolMessage(f'Updated todo list to {todos}', tool_call_id=name, id='result-'+name)
    return [ai, result]


@pytest.mark.parametrize('variant', ['same', 'changed', 'extra_text', 'failed', 'wrong_id',
                                     'separated', 'extra_call', 'duplicate_id', 'extra_args', 'foreign_state'])
def test_project_only_exact_successful_co_todo_receipt(variant):
    todos = [{'content': 'First part', 'status': 'in_progress'}, {'content': 'Second part', 'status': 'pending'}]
    messages = exchange('call-1', todos)
    ai, receipt = messages
    if variant == 'changed': receipt.content = "Updated todo list to []"
    if variant == 'extra_text': receipt.content += ' and an important warning'
    if variant == 'failed': receipt.status = 'error'
    if variant == 'wrong_id': receipt.tool_call_id = 'wrong'
    if variant == 'separated': messages.insert(1, HumanMessage('intervening content'))
    if variant == 'extra_call':
        ai.tool_calls.append({'name': 'calculate', 'args': {}, 'id': 'another', 'type': 'tool_call'})
    if variant == 'duplicate_id': messages += exchange('call-1', todos)
    if variant == 'extra_args': ai.tool_calls[0]['args']['other'] = 'extra'
    original = [m.model_dump(mode='json') for m in messages]
    request = make_request(messages)
    if variant == 'foreign_state': request.state = {'messages': exchange('different-task', todos)}
    projected = project_plan_history(request)
    assert projected.messages == messages
    assert receipt.tool_call_id == ('wrong' if variant == 'wrong_id' else 'call-1')
    assert receipt.id == 'result-call-1'
    assert [m.model_dump(mode='json') for m in messages] == original


def test_two_plan_versions_each_remain_at_their_own_call():
    first = [{'content':'old plan','status':'pending'}]
    second = [{'content':'changed plan','status':'in_progress'}]
    messages = exchange('one', first) + exchange('two', second)
    projected = project_plan_history(make_request(messages))
    assert projected.messages == messages
    assert [messages[i].tool_calls[0]['args']['todos'] for i in (0,2)] == [first, second]
    assert [m.content for m in messages if isinstance(m, ToolMessage)] == [
        f'Updated todo list to {first}', f'Updated todo list to {second}']

@pytest.mark.asyncio
@pytest.mark.parametrize('opt_in', [False, True])
@pytest.mark.parametrize('clear_plan', [False, True])
async def test_coordinator_native_sdk_wire_keeps_prior_plan_versions(case, opt_in, clear_plan):
    import json, httpx
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.workspace import Workspace
    from test_bounded_review import Model
    from test_prompt_native_sdk_inputs import completion
    from test_reviewer_native_profile import native

    cs, *_ = case
    ws = Workspace(cs.store)
    native(ws)
    if opt_in:
        cs.store.set('context_policy', 'stateful-tools-v1')
        cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    first = [{'content':'old plan','status':'pending'}]
    second = [] if clear_plan else [{'content':'revised plan','status':'in_progress'}]
    models, wires = {}, []
    def factory(role):
        if role == 'text_tool': return Model('synthetic')
        if role in models: return models[role]
        client = model_async_client(ws.store, role)
        async def respond(request):
            body = json.loads(request.content)
            wires.append((role, body))
            assert role == 'coordinator'
            step = len(wires) - 1
            if step < 2:
                response = completion(request, '', ('write_todos', {'todos': [first, second][step]}))
                payload = json.loads(response.content)
                payload['choices'][0]['message']['tool_calls'][0]['id'] = f'fixture-write-todos-{step}'
                return httpx.Response(200, json=payload)
            return completion(request, 'Fixture complete.')
        client._transport = httpx.MockTransport(respond)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fake', base_url='https://fixture.invalid/v1',
            use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result['last_error'] is None, result
        assert len(wires) == 3
        final = wires[-1][1]['messages']
        calls = [m['tool_calls'][0] for m in final if m.get('tool_calls')
                 and m['tool_calls'][0]['function']['name'] == 'write_todos']
        receipts = [m for m in final if m.get('role') == 'tool']
        assert len(calls) == len(receipts) == 2
        assert [json.loads(c['function']['arguments'])['todos'] for c in calls] == [first, second]
        assert [r['tool_call_id'] for r in receipts] == [c['id'] for c in calls]
        assert [r['content'] for r in receipts] == [f'Updated todo list to {first}', f'Updated todo list to {second}']
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
