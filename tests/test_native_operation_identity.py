"""Native injected identity, not model-generated idempotency keys; offline only."""
import json

import pytest
from langchain.tools import tool
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work import content, writer_call


def tools(workspace, role, model):
    from report_agent.deep_runtime import business_tools
    return {getattr(t, 'name', None) or t.__name__: t
            for t in business_tools(workspace, role, None, model)}


def activate(ws):
    ws.store.set('manifest', {**ws.store.manifest,
        'operation_identity_profile': 'native-tool-runtime-v1'})


def graph_for(function, checkpointer=None):
    graph = StateGraph(MessagesState)
    graph.add_node('tools', ToolNode([function], handle_tool_errors=False))
    graph.add_edge(START, 'tools')
    graph.add_edge('tools', END)
    return graph.compile(checkpointer=checkpointer)


async def dispatch(graph, call_id, args):
    result = await graph.ainvoke({'messages': [AIMessage('', tool_calls=[{
        'name': 'process_report_content', 'id': call_id,
        'args': args, 'type': 'tool_call'}])]})
    return json.loads(result['messages'][-1].content)


def test_new_native_schema_hides_technical_identity_but_legacy_keeps_it(ws):
    model = Model(json.dumps(content()))
    with delegated_task(ws, 'coordinator', writer_call()):
        legacy = tool(tools(ws, 'writer', model)['process_report_content'])
        assert 'operation_id' in legacy.tool_call_schema.model_json_schema()['required']
        activate(ws)
        native = tool(tools(ws, 'writer', model)['process_report_content'])
        schema = native.tool_call_schema.model_json_schema()
        assert 'operation_id' not in schema['properties']
        assert 'runtime' not in schema['properties']
        assert {'objective', 'object_type'} <= set(schema['required'])


async def test_native_checkpoint_call_identity_reuses_exact_work_and_rejects_conflict(ws):
    _, _, refs, _, _ = seed(ws)
    activate(ws)
    model = Model(json.dumps(content()))
    args = {'objective': 'Describe the selected rule', 'object_type': 'ContentNode',
            'input_refs': [refs['claim']]}
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        graph = graph_for(tools(ws, 'writer', model)['process_report_content'])
        first = await dispatch(graph, 'persistent-native-call', args)
        replay = await dispatch(graph, 'persistent-native-call', args)
        assert replay['text_work_id'] == first['text_work_id'] and replay['reused']
        assert first['actor_id'] == actor.id and len(model.calls) == 1
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await dispatch(graph, 'persistent-native-call', {**args, 'objective': 'Changed intent'})
        assert len(model.calls) == 1
        independent = await dispatch(graph, 'new-independent-call', args)
        assert independent['operation_id'] != first['operation_id']
        for result in (first, independent):
            state = ws.store.get('text_work:' + actor.id + ':' + result['operation_id'])
            assert state['state'] == 'completed'
            assert tools(ws, 'writer', model)['get_operation_receipt'](result['operation_id'])['state'] == 'known_text_attempt'


async def test_unknown_work_is_not_bypassed_with_a_new_runtime_identity(ws):
    _, _, refs, _, _ = seed(ws)
    activate(ws)
    model = Model(RuntimeError('synthetic unknown response'))
    args = {'objective': 'Describe the selected rule', 'object_type': 'ContentNode',
            'input_refs': [refs['claim']]}
    with delegated_task(ws, 'coordinator', writer_call()):
        graph = graph_for(tools(ws, 'writer', model)['process_report_content'])
        with pytest.raises(RuntimeError, match='synthetic unknown'):
            await dispatch(graph, 'original-call', args)
        with pytest.raises(ActionRejected, match='OUTCOME_UNRESOLVED'):
            await dispatch(graph, 'new-call-not-retry-authority', args)
        assert len(model.calls) == 1


async def test_real_sqlite_checkpoint_replays_saved_call_without_another_producer(ws, tmp_path):
    _, _, refs, _, _ = seed(ws)
    activate(ws)
    model = Model(json.dumps(content()))
    args = {'objective': 'Describe the selected rule', 'object_type': 'ContentNode',
            'input_refs': [refs['claim']]}
    path = str(tmp_path / 'native-identity-checkpoints.db')
    config = {'configurable': {'thread_id': 'identity-reopen'}}
    with delegated_task(ws, 'coordinator', writer_call()):
        function = tools(ws, 'writer', model)['process_report_content']
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = graph_for(function, saver)
            first = await graph.ainvoke({'messages': [AIMessage('', tool_calls=[{
                'id': 'saved-call', 'name': 'process_report_content', 'args': args,
                'type': 'tool_call'}])]}, config)
            checkpoints = [state async for state in graph.aget_state_history(config)]
            pending = next(state for state in checkpoints if state.next == ('tools',))
            assert pending.values['messages'][-1].tool_calls[0]['id'] == 'saved-call'
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            restored = graph_for(function, saver)
            replay = await restored.ainvoke(None, pending.config)
        before = json.loads(first['messages'][-1].content)
        after = json.loads(replay['messages'][-1].content)
        assert after['operation_id'] == before['operation_id']
        assert after['text_work_id'] == before['text_work_id'] and after['reused']
        assert len(model.calls) == 1


async def test_caller_cannot_override_injected_identity_and_foreign_actor_cannot_query_it(ws):
    _, _, refs, _, _ = seed(ws)
    activate(ws)
    model = Model(json.dumps(content()))
    with delegated_task(ws, 'coordinator', writer_call('owner')):
        graph = graph_for(tools(ws, 'writer', model)['process_report_content'])
        work = await dispatch(graph, 'trusted-call', {
            'objective': 'Describe selected material', 'object_type': 'ContentNode',
            'input_refs': [refs['claim']], 'operation_id': 'forged',
            'runtime': {'tool_call_id': 'forged'}})
        assert work['operation_id'] == 'native:process_report_content:trusted-call'
        own = tools(ws, 'writer', model)['get_operation_receipt'](work['operation_id'])
        assert own['text_work']['text_work_id'] == work['text_work_id']
    with delegated_task(ws, 'coordinator', writer_call('other')):
        foreign = tools(ws, 'writer', model)['get_operation_receipt'](work['operation_id'])
        assert foreign['state'] == 'unknown'
        assert 'text_work' not in foreign and not foreign.get('model_attempts')


async def test_native_direct_call_without_runtime_is_rejected_before_production(ws):
    activate(ws)
    model = Model(json.dumps(content()))
    with delegated_task(ws, 'coordinator', writer_call()):
        with pytest.raises(ActionRejected, match='NATIVE_TOOL_CALL_ID_REQUIRED'):
            await tools(ws, 'writer', model)['process_report_content'](
                objective='Describe material', object_type='ContentNode')
        assert not model.calls


async def test_native_boundary_unknown_interrupt_and_exact_host_resume_share_identity(ws, tmp_path):
    from report_agent import deep_runtime
    from report_agent.errors import ModelRequestDeadlineExceeded
    from test_deep_runtime import Driver, call, invoke, snapshot
    from test_text_unknown_interrupt import grant

    _, _, refs, _, _ = seed(ws)
    activate(ws)
    service = Model(ModelRequestDeadlineExceeded(1800))
    driver = Driver(coordinator=[
        invoke('task', subagent_type='writer', description='Inspect selected material.'),
        AIMessage('Child returned, no engineering acceptance.')], writer=[
        AIMessage('', tool_calls=[call('process_report_content', {
            'objective': 'Assess selected material', 'object_type': 'ContentNode',
            'input_refs': [refs['claim']]}, 'unknown-call')]),
        AIMessage('', tool_calls=[call('process_report_content', {
            'objective': 'Assess newly supplied evidence', 'object_type': 'ContentNode',
            'input_refs': [refs['claim'], refs['evidence']]}, 'related-call')]),
        AIMessage('Candidate received; still requires review.')])
    factory = lambda role: service if role == 'text_tool' else driver(role)
    await deep_runtime.run_report(ws, factory)
    pending = await snapshot(ws, factory)
    assert pending.interrupts
    event = pending.interrupts[0].value
    assert event['operation_id'] == 'native:process_report_content:related-call'
    assert event['tool_call_id'] == 'related-call' and not event['producer_invoked']
    offered = next(t for t in driver.bindings['writer'][0] if t['name'] == 'process_report_content')
    assert 'operation_id' not in offered['parameters']['properties']
    assert 'runtime' not in offered['parameters']['properties']
    count = len(driver.calls)
    await deep_runtime.run_report(ws, factory)
    assert len(driver.calls) == count and len(service.calls) == 1
    grant(ws, event, tmp_path)
    service.response = json.dumps(content())
    await deep_runtime.run_report(ws, factory)
    final = await snapshot(ws, factory)
    assert not final.interrupts and not final.next and len(service.calls) == 2
    actor_id = event['actor']['id']
    assert ws.store.get('text_work:' + actor_id + ':native:process_report_content:unknown-call')['state'] == 'reserved'
    assert ws.store.get('text_work:' + actor_id + ':' + event['operation_id'])['state'] == 'completed'


async def test_built_graph_identity_survives_store_profile_change_and_error_is_queryable(ws, tmp_path):
    from langchain_core.messages import HumanMessage
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, call, observation

    seed(ws)
    activate(ws)
    identity = 'native:process_report_content:forbidden-call'
    def inspect_error(messages):
        result = observation(messages, 'process_report_content')
        assert result['receipt_id'] == identity and result['code'] == 'FORBIDDEN'
        return AIMessage('', tool_calls=[call('get_operation_receipt', {
            'operation_id': identity}, 'query-error')])
    def inspect_query(messages):
        result = observation(messages, 'get_operation_receipt')
        # Rejection happened before any producer operation; no receipt is invented.
        assert result['state'] == 'unknown' and 'text_work' not in result
        return AIMessage('Forbidden attempt was not dispatched.')
    driver = Driver(coordinator=[AIMessage('', tool_calls=[call('process_report_content', {
        'objective': 'Coordinator cannot author this', 'object_type': 'ContentNode',
        'source_selections': [{'source_id': 's'}]}, 'forbidden-call')]), inspect_error, inspect_query])
    producer = Model(json.dumps(content()))
    factory = lambda role: producer if role == 'text_tool' else driver(role)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'two-graphs.db')) as saver:
        native = deep_runtime.build_agent(ws, factory, saver)
        ws.store.set('manifest', {**ws.store.manifest,
            'operation_identity_profile': 'caller-operation-v1'})
        legacy = deep_runtime.build_agent(ws, factory, saver)
        assert native.config['metadata']['report_operation_identity_profile'] == 'native-tool-runtime-v1'
        assert legacy.config['metadata']['report_operation_identity_profile'] == 'caller-operation-v1'
        await native.ainvoke({'messages': [HumanMessage('Inspect identity rejection.')]},
            {'configurable': {'thread_id': 'built-native'}})
    assert not producer.calls
