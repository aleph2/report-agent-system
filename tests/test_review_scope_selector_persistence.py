"""Selectors use existing native transactions and guards; no provider requests."""
from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.operation_identity import write_id
from report_agent.review_scope_selectors import expand_submission
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_deliverable_recovery_v4 import resolve
from test_native_operation_identity import graph_for
from test_native_write_identity import native_tools,dispatch
from test_review_binding_v4 import prepared,review_call,task_record
from test_review_scope_selectors import CONTRACT,IDENTITY,wire_submission
from test_reviewer_native_profile import candidate


@pytest.mark.parametrize('kind',['export','render'])
def test_selector_preserves_actual_non_content_assessment_kind(case,kind):
    cs,output,criteria,_=prepared(case)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    snapshot=resolve(cs,case[1],'bind-artifact',{'kind':'deliverable','operation_id':'published'})
    with cs.store.connect() as db:
        exported=cs._insert(db,case[1],'ExportArtifact',{'snapshot_ref':snapshot,'file_ref':'synthetic.docx'})
        artifact=(cs._insert(db,case[1],'RenderArtifact',{'snapshot_ref':snapshot,'export_ref':exported,
            'page_assets':[{'asset_ref':'synthetic.png','sha256':'synthetic'}]}) if kind=='render' else exported)
    request=review_call(criteria[:1],scope={'kind':'mapped','items':[{'criterion_ref':criteria[0],
        'target_ref':output['refs']['a'],'assessment_kind':kind,'artifact_refs':[artifact]}]})
    request['args']['review']['deliverable']={'kind':'snapshot','snapshot_ref':snapshot}
    with delegated_task(Workspace(cs.store),'coordinator',request) as (_,actor):
        before=task_record(cs,actor)
        expanded=expand_submission(cs,actor,wire_submission())
        assert expanded['items'][0]['assessment_kind']==kind
        assert expanded['items'][0]['scope_id']==before['payload']['review_requirements'][0]['scope_id']
        assert 'artifact_refs' not in expanded['items'][0]  # Evidence selection is still the model's responsibility.
        assert task_record(cs,actor)==before and not cs.list_objects('ReviewRecord')


async def test_selector_save_receipt_survives_child_store_and_checkpoint_reopen(case,tmp_path):
    cs,output,criteria,_=prepared(case);ws=Workspace(cs.store)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    request=review_call(criteria[:1],identity='persist-selector')
    checkpoint=str(tmp_path/'selector-checkpoint.db')
    config={'configurable':{'thread_id':'synthetic-selector-checkpoint'}}
    with delegated_task(ws,'coordinator',request) as (_,actor):
        task=task_record(cs,actor)['payload']
        receipt=cs.read_context(actor,output['refs']['a-body'])['receipt_id']
        value=candidate(task['review_snapshot_ref'],{'root':output['refs']['a'],'k':criteria[0],
            'support':output['refs']['support']},[receipt],verdict='satisfied')
        item=value['items'][0]
        for field in IDENTITY:item.pop(field,None)
        item['assigned_scope_index']=0
        function=native_tools(ws,'reviewer')['submit_review']
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            graph=graph_for(function,saver)
            result=await graph.ainvoke({'messages':[AIMessage('',tool_calls=[{
                'name':'submit_review','id':'saved-selector-call','type':'tool_call','args':{'review':value}}])]},config)
            first=json.loads(result['messages'][-1].content)
            history=[state async for state in graph.aget_state_history(config)]
            pending=next(state for state in history if state.next==('tools',))
        operation=write_id(actor.id,'submit_review','saved-selector-call')
        saved_receipt=cs.receipt(actor,operation)
        original=deepcopy(cs.list_objects('ReviewRecord'))
        assert len(original)==1 and saved_receipt['state']=='known_success'
        child_id=actor.task_id
    reopened=Workspace(Store(ws.store.root))
    resume=review_call(criteria[:1],identity='reopen-selector')
    resume['args']['resume_content_task_id']=child_id
    with delegated_task(reopened,'coordinator',resume) as (_,recovered):
        assert recovered==actor
        function=native_tools(reopened,'reviewer')['submit_review']
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            replay=await graph_for(function,saver).ainvoke(None,pending.config)
        assert json.loads(replay['messages'][-1].content)==first
        contents=ContentStore(reopened.store)
        assert contents.list_objects('ReviewRecord')==original
        assert contents.receipt(recovered,operation)==saved_receipt
        changed=deepcopy(value);changed['items'][0]['reason']='Different semantic claim, same native call.'
        with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
            await dispatch(function,'saved-selector-call',{'review':changed})
        assert contents.list_objects('ReviewRecord')==original


@pytest.mark.parametrize('failure',['foreign-receipt','missing-check'])
def test_selector_does_not_bypass_canonical_review_guards(case,failure):
    cs,output,criteria,_=prepared(case);ws=Workspace(cs.store)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    with delegated_task(ws,'coordinator',review_call(criteria[:1],identity='receipt-owner')) as (_,first):
        foreign=cs.read_context(first,output['refs']['a-body'])['receipt_id']
    with delegated_task(ws,'coordinator',review_call(criteria[:1],identity='guarded-selector')) as (_,actor):
        task=task_record(cs,actor)['payload']
        receipt=(foreign if failure=='foreign-receipt' else cs.read_context(actor,output['refs']['a-body'])['receipt_id'])
        value=candidate(task['review_snapshot_ref'],{'root':output['refs']['a'],'k':criteria[0],
            'support':output['refs']['support']},[receipt],
            verdict=None if failure=='foreign-receipt' else 'satisfied',
            state='running' if failure=='foreign-receipt' else 'completed')
        for field in IDENTITY:value['items'][0].pop(field,None)
        value['items'][0]['assigned_scope_index']=0
        if failure=='missing-check':
            value['items'][0]['check_results']=[]
            value['items'][0]['checked_requirement_indexes']=[]
        expanded=expand_submission(cs,actor,value)
        code=('^OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER$' if failure=='foreign-receipt'
              else 'COMPLETED_REVIEW_REQUIRES_EVERY_ASSIGNED_CHECK')
        with pytest.raises(ActionRejected,match=code):
            cs.submit_review(actor,'guarded-save',expanded,{})
        assert not cs.list_objects('ReviewRecord')
