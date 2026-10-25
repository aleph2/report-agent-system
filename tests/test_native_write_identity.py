"""Native SDK schema and ToolNode identity with real atomic ContentStore writes."""
import json

import httpx
import pytest
from deepagents import create_deep_agent
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.content_tasks import delegated_task
from report_agent.content_store import ContentStore
from report_agent.deep_models import GLMChatOpenAI
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.text_work import guarded_tools
from test_bounded_review import Model
from test_native_operation_identity import activate, graph_for
from test_prompt_native_sdk_inputs import completion
from test_task_supervision import ws
from test_text_work import writer_call


ATOMIC_CASES = [
    ('coordinator', 'import_source_versions'), ('rubric_grader', 'capture_review_sources'),
    ('writer', 'commit_objects'), ('writer', 'save_text_node'),
    ('coordinator', 'freeze_snapshot'), ('coordinator', 'derive_snapshot'),
    ('rubric_grader', 'submit_review'), ('coordinator', 'record_handoff'),
    ('rubric_grader', 'confirm_review_reuse'), ('rubric_grader', 'correct_own_review'),
    ('coordinator', 'export_content_snapshot'), ('coordinator', 'export_content_workbook'),
    ('coordinator', 'request_layout_capability'), ('coordinator', 'select_content_delivery'),
    ('coordinator', 'record_execution_decision')]


def native_tools(workspace, role):
    from report_agent.native_operation_tools import native_write_tools
    functions = guarded_tools(workspace, role, Model('unused'), content_tools(workspace, role))
    return {getattr(t, 'name', None) or t.__name__: t
            for t in native_write_tools(workspace, role, functions)}


def heading(title='Selected report'):
    return {'objects': [{'client_key': 'heading', 'type': 'ContentNode', 'payload': {
        'kind': 'report', 'claim_kind': 'structure', 'body': {'text': title}, 'qualifiers': {}}}]}


async def dispatch(function, call_id, args):
    result = await graph_for(function).ainvoke({'messages': [AIMessage('', tool_calls=[{
        'name': getattr(function, 'name', None) or function.__name__,
        'id': call_id, 'type': 'tool_call', 'args': args}])]})
    return json.loads(result['messages'][-1].content)


async def test_commit_native_actual_sdk_hides_id_and_preserves_discriminated_object_contract(ws):
    activate(ws)
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, '', ('commit_objects', heading()))
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture', base_url='https://fixture.invalid/v1',
        http_async_client=client, use_responses_api=False, disable_streaming=True, max_retries=0)
    try:
        with delegated_task(ws, 'coordinator', writer_call()):
            function = native_tools(ws, 'writer')['commit_objects']
            response = await model.bind_tools([function]).ainvoke([HumanMessage('Save the selected heading.')])
            schema = wires[0]['tools'][0]['function']['parameters']
            assert 'operation_id' not in schema['properties']
            objects = schema['properties']['objects']['items']
            assert objects['discriminator']['propertyName'] == 'type'
            assert len(objects['oneOf']) == 4
            result = await graph_for(function).ainvoke({'messages': [response]})
            saved = json.loads(result['messages'][-1].content)
            assert saved['ok'] and saved['receipt_id'].startswith('native:')
            assert saved['operation_id'] == saved['receipt_id']
            assert len(ContentStore(ws.store).list_objects('ContentNode')) == 1
    finally:
        await model.root_async_client.close(); model.root_client.close()


async def test_commit_native_actor_namespace_replay_conflict_and_forgery(ws):
    activate(ws)
    receipts = []
    for delegation in ('writer-one', 'writer-two'):
        with delegated_task(ws, 'coordinator', writer_call(delegation)) as (_, actor):
            function = native_tools(ws, 'writer')['commit_objects']
            first = await dispatch(function, 'same-persistent-call', {**heading(), 'operation_id': 'forged'})
            replay = await dispatch(function, 'same-persistent-call', heading())
            assert first == replay
            assert 'forged' not in first['receipt_id']
            receipts.append(first['receipt_id'])
            assert ContentStore(ws.store).receipt(actor, first['receipt_id'])['state'] == 'known_success'
            with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
                await dispatch(function, 'same-persistent-call', heading('Changed heading'))
    assert receipts[0] != receipts[1]
    assert len(ContentStore(ws.store).list_objects('ContentNode')) == 2


@pytest.mark.parametrize('role,name', ATOMIC_CASES)
def test_all_atomic_write_schemas_preserve_every_business_field(ws, role, name):
    from report_agent.native_operation_tools import native_write_tools
    functions = guarded_tools(ws, role, Model('unused'), content_tools(ws, role))
    original = next(f for f in functions if f.__name__ == name)
    activate(ws)
    native = next(f for f in native_write_tools(ws, role, functions)
                  if (getattr(f, 'name', None) or f.__name__) == name)
    expected = convert_to_openai_tool(tool(original))
    parameters = expected['function']['parameters']
    parameters['properties'].pop('operation_id')
    parameters['required'].remove('operation_id')
    assert convert_to_openai_tool(native) == expected


@pytest.mark.parametrize('role,name', [('writer', 'commit_objects'), ('coordinator', 'freeze_snapshot')])
async def test_actual_deepagents_registration_to_sdk_matches_original_except_identity(ws, role, name):
    from report_agent.native_operation_tools import native_write_tools
    functions = guarded_tools(ws, role, Model('unused'), content_tools(ws, role))
    original = next(f for f in functions if f.__name__ == name)
    activate(ws)
    adapted = native_write_tools(ws, role, [original])[0]
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, 'No tool execution requested.')
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture', base_url='https://fixture.invalid/v1',
        http_async_client=client, use_responses_api=False, disable_streaming=True, max_retries=0)
    try:
        for function in (original, adapted):
            graph = create_deep_agent(model=model, tools=[function], system_prompt='Fixture schema comparison.')
            await graph.ainvoke({'messages': [HumanMessage('Inspect the available tool.') ]})
        before, after = [next(t for t in wire['tools'] if t['function']['name'] == name) for wire in wires]
        parameters = before['function']['parameters']
        parameters['properties'].pop('operation_id')
        parameters['required'].remove('operation_id')
        assert after == before
    finally:
        await model.root_async_client.close(); model.root_client.close()


@pytest.mark.parametrize('role,name', ATOMIC_CASES)
def test_atomic_identity_namespaces_and_trusted_copy_preserve_raw_call(ws, role, name):
    from report_agent.operation_identity import write_id, effective_call
    activate(ws)
    raw = {'name': name, 'id': 'persisted-call', 'args': {'operation_id': 'forged', 'unchanged': [1]}}
    first = effective_call(ws.store, raw, actor_id='actor-one')
    assert first['args']['operation_id'] == write_id('actor-one', name, 'persisted-call')
    assert first['args']['operation_id'] != write_id('actor-two', name, 'persisted-call')
    assert first['args']['operation_id'] != write_id('actor-one', name, 'other-call')
    assert raw['args']['operation_id'] == 'forged' and first['args']['unchanged'] == [1]
    with pytest.raises(ActionRejected, match='NATIVE_TOOL_CALL_ID_REQUIRED'):
        write_id('actor-one', name, '')


def test_legacy_returns_original_tools_and_receipt_query_never_injects(ws):
    from report_agent.native_operation_tools import native_write_tools
    from report_agent.operation_identity import effective_call
    functions = guarded_tools(ws, 'coordinator', Model('unused'), content_tools(ws, 'coordinator'))
    assert native_write_tools(ws, 'coordinator', functions) is functions
    activate(ws)
    adapted = native_write_tools(ws, 'coordinator', functions)
    query = next(f for f in functions if f.__name__ == 'get_operation_receipt')
    assert any(f is query for f in adapted)
    assert 'operation_id' in convert_to_openai_tool(query)['function']['parameters']['required']
    call = {'name': 'get_operation_receipt', 'id': 'query', 'args': {'operation_id': 'selected-existing-id'}}
    assert effective_call(ws.store, call) is call
    with pytest.raises(ActionRejected, match='UNKNOWN_OPERATION_IDENTITY_PROFILE'):
        ws.store.set('manifest', {**ws.store.manifest, 'operation_identity_profile': 'unrecognized'})
        native_write_tools(ws, 'coordinator', functions)


async def test_atomic_known_failure_queries_same_trusted_id_without_stored_return_mutation(ws):
    from report_agent.operation_identity import effective_call
    activate(ws)
    args = heading()
    args['objects'][0]['previous_ref'] = {'type': 'ContentNode', 'id': 'missing', 'version': 1}
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        functions = native_tools(ws, 'writer')
        call = {'name': 'commit_objects', 'id': 'invalid-write', 'args': args}
        trusted = effective_call(ws.store, call, actor.id)
        with pytest.raises(ActionRejected):
            await dispatch(functions['commit_objects'], call['id'], args)
        query = await dispatch(functions['get_operation_receipt'], 'receipt-read',
                               {'operation_id': trusted['args']['operation_id']})
        assert query['state'] == 'known_failure'
        assert query['response']['receipt_id'] == trusted['args']['operation_id']
        assert 'operation_id' not in query['response']
        assert not ContentStore(ws.store).list_objects('ContentNode')
