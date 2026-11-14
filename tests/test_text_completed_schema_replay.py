"""Exact received output survives a schema repair at a pending tools boundary."""
import json
from copy import deepcopy
import pytest
from report_agent.content_models import ContentNode
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.store import encode
from test_text_work import tools, writer_call, content
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


async def test_native_pending_tool_checkpoint_reuses_completed_result_after_schema_repair(ws, monkeypatch):
    from langgraph.types import interrupt
    from langchain_core.messages import AIMessage
    from report_agent import text_work
    from report_agent.deep_runtime import run_report
    from report_agent.content_store import ContentStore
    from test_deep_runtime import Driver, invoke, observation, snapshot
    issue=ws.issue('requirement','Synthetic completed-schema checkpoint?',[])
    def save_work(messages):
        work = observation(messages, 'process_report_content')
        return invoke('save_text_node', operation_id='adopt-resumed', text_work_id=work['text_work_id'])
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]), AIMessage(content='Task returned.')],
        writer=[invoke('process_report_content', operation_id='pending-native', objective='Describe the selected rule',
            object_type='ContentNode', source_selections=[{'source_id': 's'}]), save_work,
            AIMessage(content='Saved the exact received payload.')],
        text_tool=[AIMessage(content=json.dumps(content()))])
    original_produce, current_schema = text_work.produce, ContentNode.model_json_schema
    async def stop_after_saved(*args, **kwargs):
        result=await original_produce(*args, **kwargs)
        answer=interrupt({'issue_id':issue['id'],'kind':'synthetic_test_checkpoint'})
        assert answer=='Adopt the exact completed payload.'
        return result
    def old_schema(*args, **kwargs):
        result = deepcopy(current_schema(*args, **kwargs))
        result.pop('allOf', None)
        return result
    monkeypatch.setattr(text_work,'produce',stop_after_saved)
    with monkeypatch.context() as patch:
        patch.setattr(ContentNode,'model_json_schema',old_schema)
        stopped=await run_report(ws,driver)
        assert stopped['status']=='needs_human' and stopped['last_error'] is None
        pending=await snapshot(ws,driver)
        assert pending.interrupts[0].value['issue_id']==issue['id']
    assert not ContentStore(ws.store).list_objects('ContentNode')
    ws.decide_issue(issue['id'],'Adopt the exact completed payload.')
    result = await run_report(ws, driver)
    assert result['last_error'] is None
    nodes = ContentStore(ws.store).list_objects('ContentNode')
    assert len(nodes) == 1 and nodes[0]['payload'] == content()
    assert sum(role == 'text_tool' for role, _, _ in driver.calls) == 1
    assert any(e['kind'] == 'text_work_completed_schema_reused' for e in ws.store.events())


async def original_without_conditions(ws, monkeypatch):
    _, _, refs, _, _ = seed(ws)
    current = ContentNode.model_json_schema
    def old_schema(*args, **kwargs):
        value = deepcopy(current(*args, **kwargs))
        value.pop('allOf', None)
        return value
    model = Model(json.dumps(content()))
    args = ('one', 'Describe the supplied rule', 'ContentNode', [refs['claim']])
    with monkeypatch.context() as patch:
        patch.setattr(ContentNode, 'model_json_schema', old_schema)
        work = await tools(ws, 'writer', model)['process_report_content'](*args)
    return model, args, work


async def test_completed_same_call_reuses_exact_receipt_after_schema_repair(ws, monkeypatch):
    with delegated_task(ws, 'coordinator', writer_call()):
        model, args, work = await original_without_conditions(ws, monkeypatch)
        repeated = await tools(ws, 'writer', model)['process_report_content'](*args)
        assert repeated == {**work, 'reused': True}
        assert len(model.calls) == 1
        assert ws.store.events()[-1]['kind'] == 'text_work_completed_schema_reused'


@pytest.mark.parametrize('change', ['objective', 'count', 'authority', 'source', 'missing_archive', 'missing_receipt', 'corrupt_payload', 'unknown'])
async def test_schema_replay_never_bypasses_changed_intent_or_unproven_outcome(ws, monkeypatch, change):
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        model, args, work = await original_without_conditions(ws, monkeypatch)
        kwargs = {}
        if change == 'objective': args = (args[0], 'Different objective', *args[2:])
        if change == 'count': kwargs['output_count'] = 2
        if change == 'authority':
            manifest = ws.store.manifest
            manifest['goal'] += ' Changed authority.'
            ws.store.set('manifest', manifest)
        if change == 'source': args = (*args[:3], [], [{'source_id': 's'}])
        with ws.store.connect() as db:
            if change == 'missing_archive':
                db.execute("DELETE FROM events WHERE kind='evidence_analysis_input'")
            if change == 'missing_receipt':
                db.execute('DELETE FROM state WHERE key=?', ('text_work_receipt:' + work['text_work_id'],))
            if change in {'corrupt_payload', 'unknown'}:
                key = 'text_work:' + actor.id + ':one'
                stored = json.loads(db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()[0])
                if change == 'unknown': stored['state'] = 'reserved'
                else: stored['result']['payloads'][0]['body']['text'] = 'Changed text'
                db.execute('UPDATE state SET value=? WHERE key=?', (encode(stored), key))
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await tools(ws, 'writer', model)['process_report_content'](*args, **kwargs)
        assert len(model.calls) == 1
