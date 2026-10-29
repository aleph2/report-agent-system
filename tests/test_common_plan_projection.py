import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from report_agent.prompt_provenance import project_plan_history
from report_agent.store import encode
from test_deliverable_declaration_v4 import case


def call_pair(call_id, todos):
    ai = AIMessage('', id='ai-'+call_id, tool_calls=[
        {'name':'write_todos', 'args':{'todos':todos}, 'id':call_id, 'type':'tool_call'}])
    tool = ToolMessage(f'Updated todo list to {todos}', tool_call_id=call_id, id='tool-'+call_id)
    return [ai, tool]


def request_for(todos, messages, role='coordinator', visible=True):
    context = {'actor_id':'fixture:'+role, 'role':role}
    if visible: context['native_current_plan'] = todos
    request = SimpleNamespace(state={'todos':todos, 'messages':messages}, messages=messages,
        system_message=SystemMessage('Current task bindings and navigation previews.\n' + encode(context)))
    request.override = lambda **changes: SimpleNamespace(**{**request.__dict__, **changes})
    return request


@pytest.mark.parametrize('role', ['coordinator', 'reviewer', 'writer'])
def test_common_view_hides_prior_plan_calls_but_keeps_original_and_explicit_history(role):
    old = [{'content':'old plan','status':'pending'}]
    current = [{'content':'new plan','status':'in_progress'}]
    human = HumanMessage('Explicit past plan: keep this text.')
    pairs = call_pair('old', old) + call_pair('current', current)
    external = ToolMessage('Explicit trace: old plan retained here.', tool_call_id='external')
    messages = [human, *pairs, external]
    request = request_for(current, messages, role)
    projected = project_plan_history(request)
    assert projected.messages == messages
    assert projected.messages[0] == human and projected.messages[-1] == external
    assert request.state['messages'] == messages
    assert pairs[0].tool_calls[0]['args']['todos'] == old
    assert pairs[2].tool_calls[0]['args']['todos'] == current


@pytest.mark.parametrize('variant', ['no_plan', 'system_missing', 'wrong_current', 'failed',
                                     'mixed_content', 'extra_call', 'wrong_id', 'extra_text', 'foreign_state',
                                     'ai_extra', 'receipt_extra', 'refusal', 'state_duplicate'])
def test_ambiguous_or_unverified_pairs_are_preserved(variant):
    todos = [{'content':'current','status':'pending'}]
    messages = call_pair('call', todos)
    ai, receipt = messages
    if variant == 'failed': receipt.status = 'error'
    if variant == 'mixed_content': ai.content = 'Important observed fact.'
    if variant == 'extra_call':
        ai.tool_calls.append({'name':'other', 'args':{}, 'id':'other', 'type':'tool_call'})
    if variant == 'wrong_id': receipt.tool_call_id = 'other'
    if variant == 'extra_text': receipt.content += ' and important extra text'
    if variant == 'ai_extra': ai.additional_kwargs['important'] = 'keep'
    if variant == 'refusal': ai.additional_kwargs['refusal'] = 'actual refusal'
    if variant == 'receipt_extra': receipt.additional_kwargs['important'] = 'keep'
    request = request_for(todos, messages, visible=variant != 'system_missing')
    if variant == 'no_plan': request.state.pop('todos')
    if variant == 'wrong_current':
        request.system_message = SystemMessage('Current task bindings and navigation previews.\n' +
            encode({'role':'coordinator', 'native_current_plan':[{'content':'different','status':'pending'}]}))
    if variant == 'foreign_state': request.state = {'todos':todos, 'messages':call_pair('other', todos)}
    if variant == 'state_duplicate': request.state = {'todos':todos, 'messages': messages + call_pair('call', todos)}
    assert project_plan_history(request).messages == messages


@pytest.mark.parametrize('same', [False, True])
def test_structured_review_plan_only_redacts_ai_content_and_preserves_other_calls(same):
    current = [{'content':'current','status':'pending'}]
    old = current if same else [{'content':'different historical plan','status':'completed'}]
    ai = AIMessage(json.dumps({'review_plan':{'todos':old}}), id='a',
                   tool_calls=[{'name':'read_context','args':{},'id':'read','type':'tool_call'}])
    receipt = ToolMessage('source observation', tool_call_id='read')
    messages = [ai, receipt]
    request = request_for(current, messages, 'reviewer')
    projected = project_plan_history(request)
    assert projected.messages[0].content == ai.content
    assert projected.messages[0].tool_calls == ai.tool_calls
    assert projected.messages[1] == receipt
    assert ai.content == json.dumps({'review_plan':{'todos':old}})


def test_plan_json_mixed_with_prose_is_not_removed():
    todos = [{'content':'current','status':'pending'}]
    ai = AIMessage(json.dumps({'review_plan':{'todos':todos}}) + '\nImportant finding.')
    messages = [ai]
    assert project_plan_history(request_for(todos, messages)).messages == messages


@pytest.mark.parametrize('role', ['coordinator', 'reviewer', 'writer'])
@pytest.mark.parametrize('with_plan', [False, True])
@pytest.mark.parametrize('policy', [None, 'stateful-tools-v1'])
async def test_shared_task_context_emits_only_current_agent_plan(case, monkeypatch, role, with_plan, policy):
    import report_agent.task_context as task_context
    import report_agent.decision_data as decision_data
    import report_agent.decision_state as decision_state
    from report_agent.workspace import Workspace
    cs, *_ = case
    ws = Workspace(cs.store)
    if policy is not None:
        cs.store.set('context_policy', policy)
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    from report_agent.prompt_provenance import bind_history_projection
    bind_history_projection(ws)
    monkeypatch.setattr(task_context, 'exact_task_context',
                        lambda workspace, current_role: {'role':current_role, 'actor_id':'fixture:'+current_role})
    monkeypatch.setattr(task_context, 'progress_enabled', lambda workspace: False)
    monkeypatch.setattr(decision_state, 'compact_context', lambda value: value)
    monkeypatch.setattr(decision_data, 'deliver_controls', lambda workspace, current_role, message: message)
    todos = [{'content':'independent plan for '+role,'status':'pending'}]
    request = request_for(todos if with_plan else [], [HumanMessage('Current assignment')], role)
    request.system_message = SystemMessage('Role instructions.')
    captured = []
    async def handler(req):
        captured.append(req)
        return req
    await task_context.TaskContext(ws, role).awrap_model_call(request, handler)
    block = captured[0].system_message.content_blocks[-1]['text']
    context = json.loads(block.rsplit('\n', 1)[-1])
    assert context['role'] == role
    assert context.get('native_current_plan') == (todos if with_plan else [])


@pytest.mark.parametrize('role', ['coordinator', 'reviewer', 'writer'])
def test_explicit_empty_current_plan_hides_prior_verified_plan(role):
    old = [{'content':'old pending plan','status':'pending'}]
    messages = [HumanMessage('Current goal.'), *call_pair('old', old), *call_pair('clear', [])]
    request = request_for([], messages, role)
    projected = project_plan_history(request)
    assert projected.messages == messages
    assert request.state['messages'] == messages


@pytest.mark.parametrize('role', ['coordinator', 'reviewer', 'writer'])
async def test_absent_todo_state_does_not_inject_plan(case, monkeypatch, role):
    import report_agent.task_context as task_context
    import report_agent.decision_data as decision_data
    import report_agent.decision_state as decision_state
    from report_agent.workspace import Workspace
    cs, *_ = case
    ws = Workspace(cs.store)
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    from report_agent.prompt_provenance import bind_history_projection
    bind_history_projection(ws)
    monkeypatch.setattr(task_context, 'exact_task_context',
                        lambda workspace, current_role: {'role':current_role, 'actor_id':'fixture:'+current_role})
    monkeypatch.setattr(task_context, 'progress_enabled', lambda workspace: False)
    monkeypatch.setattr(decision_state, 'compact_context', lambda value: value)
    monkeypatch.setattr(decision_data, 'deliver_controls', lambda workspace, current_role, message: message)
    request = request_for([], [HumanMessage('Current assignment')], role)
    request.state.pop('todos')
    request.system_message = SystemMessage('Role instructions.')
    captured = []
    async def handler(req):
        captured.append(req)
        return req
    await task_context.TaskContext(ws, role).awrap_model_call(request, handler)
    context = json.loads(captured[0].system_message.content_blocks[-1]['text'].rsplit('\n',1)[-1])
    assert 'native_current_plan' not in context


async def test_common_plan_follows_captured_release_even_if_store_binding_changes(case, monkeypatch):
    import report_agent.task_context as task_context
    import report_agent.decision_data as decision_data
    import report_agent.decision_state as decision_state
    from langchain_core.runnables.config import var_child_runnable_config
    from report_agent.handoff_release import release
    from report_agent.prompt_provenance import bind_history_projection
    from test_review_work_units import configured
    cs, _, ws, _ = configured(case)
    original = {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'}
    cs.store.set('manifest', original)
    bind_history_projection(ws)
    bound = release(original)
    middleware = task_context.TaskContext(ws, 'coordinator')
    monkeypatch.setattr(task_context, 'exact_task_context',
                        lambda workspace, role: {'role':role, 'actor_id':'fixture:'+role})
    monkeypatch.setattr(task_context, 'progress_enabled', lambda workspace: False)
    monkeypatch.setattr(decision_state, 'compact_context', lambda value:value)
    monkeypatch.setattr(decision_data, 'deliver_controls', lambda workspace, role, message:message)
    cs.store.set('history_projection_binding', None)
    cs.store.set('manifest', {k:v for k,v in original.items() if k != 'history_projection_profile'})
    todos = [{'content':'Captured graph plan','status':'pending'}]
    request = request_for(todos, [HumanMessage('Fixture.')])
    request.system_message = SystemMessage('Role instructions.')
    seen = []
    async def handler(req):
        seen.append(req)
        return req
    token = var_child_runnable_config.set({'metadata':{'report_handoff_release':bound,
        'report_review_interface_profile':'review-interfaces-v4'}})
    try:
        await middleware.awrap_model_call(request, handler)
    finally:
        var_child_runnable_config.reset(token)
    context = json.loads(seen[0].system_message.content_blocks[-1]['text'].rsplit('\n',1)[-1])
    assert context['native_current_plan'] == todos
