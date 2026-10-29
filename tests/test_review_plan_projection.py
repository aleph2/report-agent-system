import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from report_agent.content_tasks import delegated_task
from report_agent.prompt_provenance import project_plan_history
from report_agent.store import encode
from report_agent.review_work_units import validate_todos
from test_deliverable_declaration_v4 import case
from test_review_work_units import configured, unit_todo


def request_for(todos, messages):
    request = SimpleNamespace(state={'todos': todos, 'messages':messages}, messages=messages,
                              system_message=SystemMessage('Current task bindings and navigation previews.\n'+encode({'native_current_plan':todos})))
    request.override = lambda **kw: request_for_override(request, kw)
    return request


def request_for_override(request, kw):
    result = SimpleNamespace(**{**request.__dict__, **kw})
    result.override = lambda **more: request_for_override(result, more)
    return result


@pytest.mark.parametrize('variant', ['same', 'changed', 'mixed', 'duplicate_key', 'wrong_binding',
                                     'missing_system', 'foreign_task'])
async def test_plan_projection_preserves_bound_history_and_tool_pair(case, variant):
    cs, output, ws, task = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    with delegated_task(ws, 'coordinator', task):
        stamped = validate_todos(ws, [todo], declaration=True)
        original = deepcopy(stamped)
        old = deepcopy(todo)
        if variant == 'changed':
            old['review_unit']['remaining_work'] = 'Different historical status.'
        content = json.dumps({'review_plan': {'todos': [old]}})
        if variant == 'mixed': content += '\nOther important observations.'
        if variant == 'duplicate_key': content = content[:-1] + ',"review_plan":{}}'
        if variant == 'wrong_binding': stamped[0]['review_unit']['_binding'] = 'invalid'
        message = AIMessage(content, id='historical-plan', tool_calls=[
            {'name':'read_context','args':{'target_ref':'x'},'id':'paired','type':'tool_call'}])
        messages = [HumanMessage('Begin'), message, ToolMessage('receipt', tool_call_id='paired')]
        prepared = request_for(stamped, messages)
        if variant == 'missing_system':
            prepared.system_message = SystemMessage('No current plan.')
        if variant == 'foreign_task':
            with delegated_task(ws, 'coordinator', {**task, 'id':'another-task'}):
                projected = project_plan_history(prepared, ws)
        else:
            projected = project_plan_history(prepared, ws)
        assert message.content == content
        assert original[0]['review_unit']['method'] in prepared.system_message.text or variant == 'missing_system'
        assert projected.messages[1].content == content
        assert projected.messages[1].id == message.id
        assert projected.messages[1].tool_calls == message.tool_calls
        assert projected.messages[2] == messages[2]
        assert prepared.state['todos'] == stamped

async def test_native_reviewer_sees_one_current_plan_and_original_checkpoint(case):
    from report_agent.deep_runtime import build_agent
    from test_deep_runtime import Driver, invoke, call
    cs, output, ws, task = configured(case)
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    todo = unit_todo(output['refs']['a-body'])
    content = json.dumps({'review_plan': {'todos': [todo]}})
    declaration = AIMessage(content, id='plan-declaration',
        tool_calls=[call('observe_evidence', {'kind': 'calculation', 'terms': [['9', '120']]}, 'calc')])
    seen = []
    def inspect(messages):
        plan = next(m for m in messages if getattr(m, 'id', None) == 'plan-declaration')
        seen.append(plan)
        assert plan.content == content
        assert plan.tool_calls[0]['id'] == 'calc'
        assert any(getattr(m, 'tool_call_id', None) == 'calc' for m in messages)
        assert todo['review_unit']['method'] in messages[0].text
        return AIMessage('Fixture finished.')
    driver = Driver(coordinator=[AIMessage('',tool_calls=[{**task,'type':'tool_call'}]), AIMessage('Done.')],
                    reviewer=[declaration, inspect])
    await build_agent(ws, driver, None).ainvoke({'messages':[HumanMessage('Review fixture.')]})
    assert len(seen) == 1
    assert declaration.content == content

async def test_projected_message_reaches_actual_sdk_wire(case):
    import httpx
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from test_prompt_native_sdk_inputs import completion

    cs, output, ws, task = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    original = json.dumps({'review_plan': {'todos': [todo]}})
    wire = []
    async def respond(request):
        wire.append(json.loads(request.content))
        return completion(request, 'Synthetic response.')
    client = model_async_client(ws.store, 'reviewer')
    client._transport = httpx.MockTransport(respond)
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='fake', base_url='https://fixture.invalid/v1',
                          use_responses_api=False, http_async_client=client,
                          max_retries=0, disable_streaming=True)
    try:
        with delegated_task(ws, 'coordinator', task):
            stamped = validate_todos(ws, [todo], declaration=True)
            msg = AIMessage(original, id='plan', tool_calls=[{'name':'read_context', 'args':{'target_ref':'x'}, 'id':'paired', 'type':'tool_call'}])
            receipt = ToolMessage('fixture receipt', tool_call_id='paired')
            req = request_for(stamped, [HumanMessage('Review.'),msg,receipt])
            projected = project_plan_history(req, ws)
            await model.ainvoke([projected.system_message, *projected.messages])
        assert len(wire) == 1
        assert any(m.get('content') == original for m in wire[0]['messages'])
        assert todo['review_unit']['method'] in json.dumps(wire[0], ensure_ascii=False)
        assert msg.content == original
        assert any(m.get('tool_calls', [{}])[0].get('id') == 'paired' for m in wire[0]['messages'] if m.get('tool_calls'))
        assert any(m.get('tool_call_id') == 'paired' for m in wire[0]['messages'])
    finally:
        await model.root_async_client.close()
        model.root_client.close()


@pytest.mark.parametrize('variant', ['no_candidate', 'no_current_system'])
async def test_no_candidate_does_not_query_material_bindings(case, monkeypatch, variant):
    import report_agent.review_work_units as units
    cs, output, ws, task = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    with delegated_task(ws, 'coordinator', task):
        stamped = validate_todos(ws, [todo], declaration=True)
        text = json.dumps({'review_plan': {'todos': [todo]}})
        messages = [AIMessage(text if variant == 'no_current_system' else 'Ordinary historical note.')]
        req = request_for(stamped, messages)
        if variant == 'no_current_system': req.system_message = SystemMessage('No current plan.')
        def forbidden(*args, **kwargs):
            raise AssertionError('Unexpected complete material lookup')
        monkeypatch.setattr(units, 'validate_todos', forbidden)
        result = project_plan_history(req, ws)
        assert result.messages == messages


async def test_review_plan_projection_sqlite_checkpoint_reopen_keeps_original(case):
    from langchain.agents import create_agent
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command, interrupt
    from report_agent.deep_runtime import business_tools, BusinessBoundary
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.prompt_provenance import AgentPromptBoundary
    from report_agent.prompt_sources import (context_source, load_prompt, report_expression_profile,
        report_prompt_profile, review_interface_profile)
    from report_agent.review_work_units import ReviewPlanning, bind_contract
    from report_agent.task_context import TaskContext
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, call

    cs, output, ws, task = configured(case)
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    bind_contract(ws, ws.store.manifest)
    todo = unit_todo(output['refs']['a-body'])
    original = json.dumps({'review_plan': {'todos': [todo]}})
    declaration = AIMessage(original, id='recoverable-plan', tool_calls=[
        call('observe_evidence', {'kind':'calculation','terms':[['9','120']]}, 'check-calc')])
    observed = []
    def paused(messages):
        seen = next(m for m in messages if getattr(m,'id',None) == 'recoverable-plan')
        assert seen.content == original
        assert seen.tool_calls[0]['id'] == 'check-calc'
        observed.append(seen.content)
        assert interrupt({'kind':'synthetic_resume'}) == 'continue'
        return AIMessage('Fixture done.')
    config = {'configurable': {'thread_id':'history-projection-child'}}
    path = str(ws.store.root / 'history-projection-checkpoint.db')
    for resumed in (False, True):
        current = Workspace(Store(ws.store.root))
        bind_contract(current, current.store.manifest)
        expression = report_expression_profile(current.store)
        interface = review_interface_profile(current.store)
        text_profile = report_prompt_profile(current.store)
        prompt = role_prompt('reviewer', expression_profile=expression,
            interface_profile=interface, prompt_profile=text_profile)
        prompt += '\n' + load_prompt(context_source('reviewer', interface, text_profile))
        driver = Driver(reviewer=[declaration, paused])
        with delegated_task(current,'coordinator',task):
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph = create_agent(driver('reviewer'), system_prompt=prompt,
                    tools=business_tools(current,'reviewer',None,None),
                    middleware=[ReviewPlanning(current), TaskContext(current,'reviewer'),
                        BusinessBoundary(current,'reviewer'), AgentPromptBoundary(current,'reviewer')],
                    checkpointer=saver)
                await graph.ainvoke(Command(resume='continue') if resumed else
                    {'messages':[HumanMessage('Review fixture.')]}, config)
                state = await graph.aget_state(config)
                saved = next(m for m in state.values['messages'] if getattr(m,'id',None) == 'recoverable-plan')
                assert saved.content == original
                assert saved.tool_calls[0]['id'] == 'check-calc'
                assert bool(state.interrupts) is (not resumed)
    assert len(observed) == 2
