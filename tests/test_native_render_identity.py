"""Native render identities and unresolved local external-work protection; no Office."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent.content_export import render_export
from report_agent.content_store import ContentStore, Actor
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from test_hierarchical_content import ws
from test_native_operation_identity import activate, graph_for, tools
from test_render_transaction import export_fixture, pdf_bytes
from test_prompt_native_sdk_inputs import completion


def render_tool(ws):
    from test_bounded_review import Model
    return tools(ws, 'coordinator', Model('unused'))['render_content_export']


def operation_row(contents, operation_id):
    with contents.store.connect() as db:
        return db.execute('SELECT * FROM content_operations WHERE operation_id=?', (operation_id,)).fetchone()


async def dispatch(function, call_id, export_ref):
    result = await graph_for(function).ainvoke({'messages': [AIMessage('', tool_calls=[{
        'name': 'render_content_export', 'id': call_id, 'type': 'tool_call',
        'args': {'export_ref': export_ref}}])]})
    return json.loads(result['messages'][-1].content)


def test_native_render_schema_hides_id_and_legacy_keeps_it(ws):
    before = tool(render_tool(ws)).tool_call_schema.model_json_schema()
    assert 'operation_id' in before['required']
    activate(ws)
    function = render_tool(ws)
    after = (function if hasattr(function, 'tool_call_schema') else tool(function)).tool_call_schema.model_json_schema()
    assert 'operation_id' not in after['properties']
    assert set(after['required']) == {'export_ref'}
    assert after['properties']['export_ref'] == before['properties']['export_ref']


async def test_native_render_actual_sdk_schema_has_only_business_input(ws):
    from report_agent.deep_models import GLMChatOpenAI
    activate(ws)
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, 'Schema inspection only; do not render.')
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only', base_url='https://fixture.invalid/v1',
        http_async_client=client, use_responses_api=False, disable_streaming=True, max_retries=0)
    try:
        await model.bind_tools([render_tool(ws)]).ainvoke([HumanMessage('Inspect the tool schema only.')])
        schema = wires[0]['tools'][0]['function']['parameters']
        assert set(schema['properties']) == {'export_ref'}
        assert schema['required'] == ['export_ref']
    finally:
        await model.root_async_client.close()
        model.root_client.close()


def test_unknown_export_cannot_be_executed_by_a_new_native_operation(ws, monkeypatch):
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('synthetic renderer interruption')
        return None, {'code': 'fixture blocked'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with pytest.raises(RuntimeError, match='synthetic renderer'):
        render_export(contents, actor, 'original-unknown', ref)
    original = operation_row(contents, 'original-unknown')
    with pytest.raises(ActionRejected, match='RENDER_EXPORT_OUTCOME_UNRESOLVED'):
        render_export(contents, actor, 'new-call-not-retry-authority', ref)
    assert calls == [1]
    assert operation_row(contents, 'original-unknown') == original
    assert contents.receipt(actor, 'original-unknown')['state'] == 'outcome_unresolved'
    blocked = contents.receipt(actor, 'new-call-not-retry-authority')
    assert blocked['state'] == 'known_failure'
    assert 'original-unknown' in blocked['response']['message']
    with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
        render_export(contents, actor, 'original-unknown', ref)
    assert operation_row(contents, 'original-unknown') == original


def test_same_export_concurrent_native_operations_execute_only_once(ws, monkeypatch):
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    entered, release = Event(), Event()
    calls = []
    def convert(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return pdf_bytes(), {'engine': 'fixture-only'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(render_export, contents, actor, 'first-reserved', ref)
        try:
            assert entered.wait(5)
            second = pool.submit(render_export, contents, actor, 'second-new-call', ref)
            with pytest.raises(ActionRejected, match='RENDER_EXPORT_OUTCOME_UNRESOLVED'):
                second.result(timeout=2)
            assert contents.receipt(actor, 'first-reserved')['state'] == 'outcome_unresolved'
        finally:
            release.set()
        assert running.result(timeout=5)['ok']
    assert calls == [1]
    assert contents.receipt(actor, 'second-new-call')['state'] == 'known_failure'


@pytest.mark.parametrize('different', ['export', 'actor'])
def test_render_association_is_exact_export_and_same_actor_only(ws, monkeypatch, different):
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('synthetic interrupted converter')
        return None, {'code': 'fixture unavailable'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with pytest.raises(RuntimeError):
        render_export(contents, actor, 'old', ref)
    other_ref = export_fixture(contents, actor) if different == 'export' else ref
    other_actor = Actor('another-owner', 'layout', 'another-task') if different == 'actor' else actor
    assert render_export(contents, other_actor, 'distinct', other_ref)['result']['execution_state'] == 'blocked'
    assert len(calls) == 2


@pytest.mark.parametrize('initialized', [True, False], ids=['legacy-manifest', 'legacy-direct-no-manifest'])
def test_legacy_direct_render_contract_is_not_migrated(ws, monkeypatch, initialized):
    if not initialized:
        with ws.store.connect() as db:
            db.execute("DELETE FROM state WHERE key='manifest'")
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('historical unknown fixture')
        return None, {'code': 'fixture unavailable'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with pytest.raises(RuntimeError):
        render_export(contents, actor, 'old', ref)
    original = operation_row(contents, 'old')
    assert render_export(contents, actor, 'another-legacy-intent', ref)['result']['execution_state'] == 'blocked'
    assert operation_row(contents, 'old') == original and len(calls) == 2


async def test_native_sqlite_checkpoint_reuses_completed_render_without_external_execution(ws, monkeypatch, tmp_path):
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        return pdf_bytes(), {'engine': 'fixture-only'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    function = render_tool(ws)
    path, config = str(tmp_path / 'render-checkpoint.db'), {'configurable': {'thread_id': 'render'}}
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = graph_for(function, saver)
        first = await graph.ainvoke({'messages': [AIMessage('', tool_calls=[{
            'name': 'render_content_export', 'id': 'persisted-render-call', 'type': 'tool_call',
            'args': {'export_ref': ref}}])]}, config)
        history = [state async for state in graph.aget_state_history(config)]
        pending = next(state for state in history if state.next == ('tools',))
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        replay = await graph_for(function, saver).ainvoke(None, pending.config)
    before, after = [json.loads(value['messages'][-1].content) for value in (first, replay)]
    assert before == after and before['operation_id'] == before['receipt_id']
    assert before['operation_id'].startswith('native:render_content_export:')
    assert calls == [1]


async def test_native_same_call_and_new_call_keep_unresolved_render_without_rerender(ws, monkeypatch):
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        raise RuntimeError('synthetic unknown renderer')
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    function = render_tool(ws)
    with pytest.raises(RuntimeError, match='synthetic unknown renderer'):
        await dispatch(function, 'persisted-render-call', ref)
    with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
        await dispatch(function, 'persisted-render-call', ref)
    with pytest.raises(ActionRejected, match='RENDER_EXPORT_OUTCOME_UNRESOLVED'):
        await dispatch(function, 'other-render-call', ref)
    assert calls == [1]


async def test_native_sqlite_unknown_checkpoint_reopens_without_render_retry(ws, monkeypatch, tmp_path):
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        raise RuntimeError('synthetic unknown renderer')
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    function = render_tool(ws)
    path = str(tmp_path / 'unknown-render-checkpoint.db')
    config = {'configurable': {'thread_id': 'unknown-render'}}
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = graph_for(function, saver)
        with pytest.raises(RuntimeError, match='synthetic unknown renderer'):
            await graph.ainvoke({'messages': [AIMessage('', tool_calls=[{
                'name': 'render_content_export', 'id': 'unknown-persisted-call', 'type': 'tool_call',
                'args': {'export_ref': ref}}])]}, config)
        pending = await graph.aget_state(config)
        assert pending.next == ('tools',)
        assert pending.values['messages'][-1].tool_calls[0]['id'] == 'unknown-persisted-call'
    with contents.store.connect() as db:
        original = db.execute('SELECT * FROM content_operations').fetchall()
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
            await graph_for(function, saver).ainvoke(None, pending.config)
    with contents.store.connect() as db:
        assert db.execute('SELECT * FROM content_operations').fetchall() == original
    assert calls == [1] and not contents.list_objects('RenderArtifact')


async def test_boundary_error_receipt_uses_the_render_runtime_identity(ws, monkeypatch):
    from report_agent import deep_runtime
    from test_bounded_review import Model
    from test_deep_runtime import Driver, call, observation
    from test_reviewer_native_profile import native
    native(ws)
    activate(ws)
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    ref = export_fixture(contents, actor, '.txt')
    monkeypatch.setattr('report_agent.office_render.convert_pdf', lambda *args: pytest.fail('prepare must reject'))
    observed = {}
    def inspect_error(messages):
        error = observation(messages, 'render_content_export')
        assert error['code'] == 'RENDER_FORMAT_UNSUPPORTED'
        assert error['receipt_id'].startswith('native:render_content_export:')
        observed['identity'] = error['receipt_id']
        return AIMessage('', tool_calls=[call('get_operation_receipt', {'operation_id': error['receipt_id']}, 'receipt')])
    def inspect_receipt(messages):
        receipt = observation(messages, 'get_operation_receipt')
        assert receipt['state'] == 'known_failure'
        assert receipt['response']['receipt_id'] == observed['identity']
        return AIMessage('Known local rejection retained; no retry.')
    driver = Driver(coordinator=[AIMessage('', tool_calls=[call('render_content_export', {'export_ref': ref}, 'invalid-render')]),
                                 inspect_error, inspect_receipt])
    result = await deep_runtime.run_report(ws, lambda role: Model('unused') if role == 'text_tool' else driver(role))
    assert result['last_error'] is None, result
