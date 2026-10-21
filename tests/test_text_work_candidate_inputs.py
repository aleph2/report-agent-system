"""Actual registered/native interfaces with offline services; no semantic claim."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from report_agent import text_work
from report_agent.content_models import ContentNode
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.text_work_candidates import archived_payload_shape
from test_bounded_review import Model
from test_deep_runtime import Driver, invoke, observation
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work import tools, writer_call, content


def select(work, index=0):
    return {'text_work_id': work['text_work_id'], 'output_index': index}


async def draft(ws, refs, actor, model=None):
    return await text_work.produce(ws, actor, model or Model(json.dumps(content())),
        'original', 'Describe selected material', 'ContentNode', [refs['claim']])


async def test_exact_draft_is_tool_input_not_objective_or_business_adoption(ws, monkeypatch):
    cs, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        first = await draft(ws, refs, actor)
        original = deepcopy(ws.store.get('text_work_receipt:'+first['text_work_id']))
        before = cs.list_objects()
        real_authority = text_work.authority
        monkeypatch.setattr(text_work, 'authority', lambda w, a: {**real_authority(w,a), 'goal': 'New authorized revision scope'})
        revised_model = Model(json.dumps(content()))
        revised = await tools(ws,'writer',revised_model)['process_report_content'](
            'revise', 'Check the draft against the selected source and revise as needed.', 'ContentNode',
            source_selections=[{'source_id':'s'}], candidate_selections=[select(first)])
        packet = json.loads(revised_model.calls[0][1][1])
        entry = next(e for e in packet['evidence'] if e['kind']=='text_work_candidate')
        assert entry['payload'] == first['payload']
        assert entry['payload']['qualifiers'] == content()['qualifiers']
        assert entry['payload_digest'] == text_work.digest(content())
        assert 'not source facts' in entry['note']
        assert packet['commission']['goal']=='New authorized revision scope'
        assert 'The supplied rule permits' not in packet['objective']
        assert cs.list_objects() == before
        assert ws.store.get('text_work_receipt:'+first['text_work_id']) == original
        saved=tools(ws,'writer',revised_model)['save_text_node']('save-revised',revised['text_work_id'])
        assert cs.read(saved['result']['refs']['text'])['owner_id']==actor.id
        again=await tools(ws,'writer',revised_model)['process_report_content'](
            'revise', 'Check the draft against the selected source and revise as needed.', 'ContentNode',
            source_selections=[{'source_id':'s'}], candidate_selections=[select(first)])
        assert again['reused'] and len(revised_model.calls)==1


@pytest.mark.parametrize('tamper',['foreign_actor','task','payload','receipt_id','index','reserved','missing_raw','changed_raw','changed_original_input'])
async def test_invalid_candidate_rejected_before_provider(ws,tamper):
    _,_,refs,_,_=seed(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        first=await draft(ws,refs,actor)
        selection=select(first)
        key='text_work_receipt:'+first['text_work_id']
        stored=ws.store.get(key)
        if tamper=='foreign_actor': stored['result']['actor_id']='another-actor'
        elif tamper=='task': stored['result']['task_id']='another-task'
        elif tamper=='payload': stored['result']['payloads'][0]['qualifiers']={}
        elif tamper=='receipt_id': stored['result']['text_work_id']='forged'
        elif tamper=='index': selection['output_index']=1
        elif tamper=='reserved': stored['state']='reserved'
        elif tamper in {'missing_raw','changed_raw','changed_original_input'}:
            with ws.store.connect() as db:
                if tamper=='missing_raw': db.execute('DELETE FROM analyses WHERE operation=?',(first['operation'],))
                elif tamper=='changed_raw':
                    raw=json.loads(db.execute('SELECT data FROM analyses WHERE operation=?',(first['operation'],)).fetchone()[0])
                    raw['analysis']=json.dumps({**content(),'body':{'text':'Changed raw'}})
                    db.execute('UPDATE analyses SET data=? WHERE operation=?',(json.dumps(raw),first['operation']))
                else:
                    row=db.execute("SELECT sequence,data FROM events WHERE kind='evidence_analysis_input'").fetchone()
                    data=json.loads(row[1]);data['input']['objective']='Changed'
                    db.execute('UPDATE events SET data=? WHERE sequence=?',(json.dumps(data),row[0]))
        ws.store.set(key,stored)
        model=Model(json.dumps(content()))
        with pytest.raises((ActionRejected,ActionForbidden)):
            await text_work.produce(ws,actor,model,'bad','Revise','ContentNode',candidate_selections=[selection])
        assert model.calls==[]


async def test_old_invalid_figure_can_be_repair_input_but_not_new_invalid_output(ws,monkeypatch):
    _,_,refs,_,_=seed(ws)
    old={'kind':'figure','body':{'source_id':'s','page':'physical page 1','caption':'Old caption'},
         'qualifiers':{'uncertain':'Original technical limit'},'claim_kind':'fact'}
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        with monkeypatch.context() as patch:
            patch.setattr(text_work,'ContentNode',archived_payload_shape(ContentNode))
            first=await draft(ws,refs,actor,Model(json.dumps(old)))
        unchanged=Model(json.dumps(old))
        with pytest.raises(ActionRejected,match='OUTPUT_CONTRACT_INVALID'):
            await text_work.produce(ws,actor,unchanged,'invalid-new','Revise','ContentNode',
                                   candidate_selections=[select(first)])
        assert len(unchanged.calls)==1
        actual=json.loads(unchanged.calls[0][1][1])
        assert actual['evidence'][0]['payload']==old
        repaired={**old,'body':{**old['body'],'page':1}}
        good=await text_work.produce(ws,actor,Model(json.dumps(repaired)),'valid-new','Use the verified page index',
                                    'ContentNode',candidate_selections=[select(first)])
        assert good['payload']['body']['page']==1


async def test_candidate_ancestor_cannot_hide_related_unknown_or_current_authority(ws):
    _,_,refs,_,_=seed(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        first=await draft(ws,refs,actor)
        second=await text_work.produce(ws,actor,Model(json.dumps(content())),'second','Revise','ContentNode',
                                      candidate_selections=[select(first)])
        with pytest.raises(RuntimeError):
            await text_work.produce(ws,actor,Model(RuntimeError('unknown')),'unknown','Source work','ContentNode',[refs['claim']])
        attempt=Model(json.dumps(content()))
        with pytest.raises(ActionRejected,match='RELATED_OUTCOME_UNRESOLVED'):
            await text_work.produce(ws,actor,attempt,'wrapped','Revise later draft','ContentNode',
                                   candidate_selections=[select(second)])
        assert not attempt.calls


async def test_same_candidate_identity_preserves_unknown_association_without_saved_refs(ws):
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        first=await text_work.produce(ws,actor,Model(json.dumps(content())),'source-only','Draft','ContentNode',
                                      source_selections=[{'source_id':'s'}])
        with pytest.raises(RuntimeError):
            await text_work.produce(ws,actor,Model(RuntimeError('unknown')),'unknown','Revise','ContentNode',
                source_selections=[{'source_id':'s'}],candidate_selections=[select(first)])
        attempt=Model(json.dumps(content()))
        with pytest.raises(ActionRejected,match='RELATED_OUTCOME_UNRESOLVED'):
            await text_work.produce(ws,actor,attempt,'changed-material','Revise','ContentNode',
                                   candidate_selections=[select(first)])
        assert not attempt.calls


async def test_candidate_counts_toward_bound_and_old_receipt_stays_usable(ws,monkeypatch):
    _,_,refs,_,_=seed(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        first=await draft(ws,refs,actor)
        monkeypatch.setattr('report_agent.prepared_material.MAX_EVIDENCE_CHARACTERS',20)
        attempt=Model(json.dumps(content()))
        with pytest.raises(ActionRejected,match='SELECT_SMALLER_LOCATED_EVIDENCE'):
            await text_work.produce(ws,actor,attempt,'too-large','Revise','ContentNode',candidate_selections=[select(first)])
        assert not attempt.calls and ws.store.get('text_work_receipt:'+first['text_work_id'])['state']=='completed'


async def test_native_graph_final_schema_and_actual_revision_input(ws):
    from report_agent.deep_runtime import run_report
    def revise(messages):
        work=observation(messages,'process_report_content')
        return invoke('process_report_content',operation_id='native-revision',objective='Check and revise the selected draft.',
            object_type='ContentNode',candidate_selections=[select(work)],source_selections=[{'source_id':'s'}])
    def save(messages):
        work=observation(messages,'process_report_content')
        return invoke('save_text_node',operation_id='native-save',text_work_id=work['text_work_id'])
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Saved, review pending.')],
        writer=[invoke('process_report_content',operation_id='native-original',objective='Describe selected source.',
            object_type='ContentNode',source_selections=[{'source_id':'s'}]),revise,save,AIMessage(content='Draft saved.')],
        text_tool=[AIMessage(content=json.dumps(content())),AIMessage(content=json.dumps(content()))])
    result=await run_report(ws,driver)
    assert result['last_error'] is None,result
    schema=next(t for t in driver.bindings['writer'][0] if t['name']=='process_report_content')
    assert 'candidate_selections' in schema['parameters']['properties']
    assert 'output_index' in json.dumps(schema) and 'draft' in json.dumps(schema)
    calls=[messages for role,_,messages in driver.calls if role=='text_tool']
    assert len(calls)==2
    packet=json.loads(calls[1][1].content)
    assert any(e['kind']=='text_work_candidate' and e['payload']==content() for e in packet['evidence'])
    assert packet['objective']=='Check and revise the selected draft.'
    assert len(ContentStore(ws.store).list_objects('ContentNode'))==1
