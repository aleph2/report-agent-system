"""Exercise registered tools and the actual native ToolMessage, offline only."""
import json
import pytest
from langchain_core.messages import AIMessage
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.errors import ActionForbidden, ActionRejected
from test_bounded_review import Model
from test_deep_runtime import Driver, invoke, observation
from test_hierarchical_content import seed
from test_task_supervision import ws
from test_text_work import tools, writer_call, content


@pytest.mark.parametrize('answer,expected', [(RuntimeError('timeout'), 'reserved'), ('not JSON', 'known_failed')])
async def test_registered_query_finds_unresolved_or_rejected_producer_without_retry(ws, answer, expected):
    cs, _, refs, _, _ = seed(ws)
    model = Model(answer)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        t = tools(ws, 'writer', model)
        with pytest.raises(Exception):
            await t['process_report_content']('attempt', 'Describe evidence', 'ContentNode', [refs['claim']])
        before = ws.store.get('text_work:' + actor.id + ':attempt')
        status = t['get_operation_receipt']('attempt')
        assert status['state'] == 'known_text_attempt'
        assert status['content_operation']['state'] == 'unknown'
        assert status['text_work']['state'] == expected
        assert status['text_work']['request_hash'] == before['request_hash']
        assert status['text_work']['raw_response_received'] is (None if expected == 'reserved' else True)
        assert ws.store.get('text_work:' + actor.id + ':attempt') == before
        with pytest.raises(ActionRejected):
            await t['process_report_content']('attempt', 'Describe evidence', 'ContentNode', [refs['claim']])
        assert len(model.calls) == 1
    with delegated_task(ws, 'coordinator', writer_call('other')):
        assert tools(ws, 'writer', model)['get_operation_receipt']('attempt') == {'state': 'unknown', 'operation_id': 'attempt'}


async def test_completed_text_is_distinct_from_content_commit_and_preserves_owner(ws):
    _, _, refs, _, _ = seed(ws)
    model = Model(json.dumps(content()))
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        t = tools(ws, 'writer', model)
        work = await t['process_report_content']('shared', 'Describe evidence', 'ContentNode', [refs['claim']])
        status = t['get_operation_receipt']('shared')
        assert status['state'] == 'known_text_attempt'
        assert status['text_work']['text_work_id'] == work['text_work_id']
        assert status['text_work']['raw_operation'] == work['operation']
        assert status['content_operation']['state'] == 'unknown'
        assert not status['text_work']['semantic_correctness_verified']
        saved = t['save_text_node']('shared', work['text_work_id'])
        both = t['get_operation_receipt']('shared')
        assert both['state'] == 'known_success'
        assert both['content_operation']['response'] == saved
        assert both['text_work'] == status['text_work']
    with delegated_task(ws, 'coordinator', writer_call('other')):
        with pytest.raises(ActionForbidden, match='owner'):
            tools(ws, 'writer', model)['get_operation_receipt']('shared')


@pytest.mark.parametrize('corruption', ['actor', 'result'])
async def test_owned_key_cannot_disclose_conflicting_stored_owner(ws, corruption):
    _, _, refs, _, _ = seed(ws)
    model = Model(json.dumps(content()))
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        t = tools(ws, 'writer', model)
        await t['process_report_content']('owned', 'Describe evidence', 'ContentNode', [refs['claim']])
        key = 'text_work:' + actor.id + ':owned'
        work = ws.store.get(key)
        if corruption == 'actor':
            work['actor'] = {'id': 'other', 'task_id': 'other', 'role': 'writer'}
        else:
            work['result']['actor_id'] = 'other'
        ws.store.set(key, work)
        with pytest.raises(ActionForbidden, match='owner mismatch'):
            t['get_operation_receipt']('owned')
        assert ws.store.get(key) == work


async def test_native_model_receives_producer_state_and_namespace(ws):
    seen=[]
    def inspect(messages):
        result=observation(messages, 'get_operation_receipt')
        seen.append(result)
        assert result['state'] == 'known_text_attempt'
        assert result['text_work']['state'] == 'completed'
        assert result['content_operation']['state'] == 'unknown'
        return AIMessage(content='Only generation completed; no write or acceptance claimed.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Done.')],
        writer=[invoke('process_report_content',operation_id='native',objective='Describe source',object_type='ContentNode',source_selections=[{'source_id':'s'}]),
                invoke('get_operation_receipt',operation_id='native'),inspect],
        text_tool=[AIMessage(content=json.dumps(content()))])
    result=await run_report(ws, driver)
    assert result['last_error'] is None
    assert len(seen) == 1
    schema=next(s for batch in driver.bindings['writer'] for s in batch if s['name']=='get_operation_receipt')
    assert 'text' in schema['description']
    assert sum(role=='text_tool' for role,_,_ in driver.calls) == 1


async def test_native_truncated_response_exposes_known_cause_without_adoption_or_retry(ws):
    from langchain_core.messages import ToolMessage
    from report_agent.content_store import ContentStore
    def after_failure(messages):
        actual = next(m.content for m in reversed(messages) if isinstance(m, ToolMessage))
        error = json.loads(actual)
        assert error['code'] == 'EVIDENCE_ANALYSIS_INCOMPLETE_OR_INVALID_RESPONSE'
        diagnostic = json.loads(error['message'].split(': ', 1)[1])
        assert diagnostic['finish_reason'] == 'length'
        assert diagnostic['raw_response_received'] is True
        assert len(diagnostic['raw_operation']) == 64
        return invoke('get_operation_receipt', operation_id='bounded')
    def after_query(messages):
        actual=observation(messages,'get_operation_receipt')
        work=actual['text_work']
        assert work['state']=='known_rejected_response'
        assert work['stored_state']=='reserved'
        assert work['raw_response_received'] and not work['adoptable_result']
        assert work['finish_reason']=='length'
        assert work['usage']['output_tokens']==40
        assert len(work['raw_operation'])==64
        return AIMessage(content='Truncated response retained, no adopted result.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Done.')],
        writer=[invoke('process_report_content',operation_id='bounded',objective='Describe source',object_type='ContentNode',source_selections=[{'source_id':'s'}]),after_failure,after_query],
        text_tool=[AIMessage(content='{"payloads": [',response_metadata={'finish_reason':'length'},
                            usage_metadata={'input_tokens':30,'output_tokens':40,'total_tokens':70})])
    result=await run_report(ws,driver)
    assert result['last_error'] is None
    assert ContentStore(ws.store).list_objects('ContentNode') == []
    assert sum(role=='text_tool' for role,_,_ in driver.calls)==1
    with ws.store.connect() as db:
        attempted=[json.loads(v) for k,v in db.execute("SELECT key,value FROM state WHERE key LIKE 'text_work:%'")]
    assert len(attempted)==1 and attempted[0]['state']=='reserved'
