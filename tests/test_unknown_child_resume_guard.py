import asyncio
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from report_agent.store import digest
from report_agent.model_recovery import activate_recovery
from report_agent.supervision_plugins import unknown_child_resume, _resume_original_checkpoint
from test_deliverable_declaration_v4 import case

@pytest.mark.parametrize('mutation', ['none', 'bad_tool', 'missing_attempt', 'wrong_owner', 'raw_received', 'parent_not_reserved', 'wrong_model_call', 'missing_recovery', 'recovery_raw', 'wrong_error', 'wrong_branch', 'missing_message','mixed_owner_string','mixed_operation_string','malformed_text_owner','malformed_text_operation','duplicate_target'])
async def test_unknown_guard_exact_boundaries_and_single_consumption(case, mutation):
    cs, _, actor, _, _ = case
    activate_recovery(cs.store, authorization='synthetic only', version=2)
    call={'id':'delegate-call','args':{'description':'fake'}}
    previous={'task_id':actor.task_id,'native_tool_call_id':call['id'],'request_digest':digest({'actor':actor.__dict__,'call':call}),'state':'reserved'}
    operation='o'*64; child_call='work-call'; model_call='fake-model-call'
    detail={'raw_operation':operation,'model_call':{'call_id':model_call}}
    payload={'code':'EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED','message':'EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED: '+json.dumps(detail)}
    messages=[AIMessage(content='',tool_calls=[{'name':'process_report_content','args':{},'id':child_call,'type':'tool_call'}]), ToolMessage(name='process_report_content',tool_call_id=child_call,content=json.dumps(payload))]
    attempt={'state':'unknown','raw_response_received':False,'operation':operation,'task_id':actor.task_id,'owner':actor.__dict__,'caller_operation_id':'native:process_report_content:'+child_call,'result':{'model_call':{'call_id':model_call}}}
    parent={'state':'reserved','actor':actor.__dict__,'request_hash':'a'*64}
    recovery={'role':'text_tool','state':'unknown','active':False,'invocation_owner':{'operation':{'operation':operation,'actor':actor.__dict__}}}
    if mutation=='bad_tool': messages[-1].name='other'
    if mutation=='wrong_owner': attempt['owner']={'id':'other'}
    if mutation=='raw_received': attempt['raw_response_received']=True
    if mutation=='parent_not_reserved': parent['state']='completed'
    if mutation=='wrong_model_call': attempt['result']['model_call']['call_id']='other'
    if mutation=='recovery_raw': recovery['raw']={'body':'fake'}
    if mutation=='missing_message': messages.pop()
    if mutation!='missing_attempt': cs.store.set('bounded_review_attempt:'+operation,attempt)
    cs.store.set('text_work:'+actor.id+':native:process_report_content:'+child_call,parent)
    if mutation!='missing_recovery': cs.store.set('model_recovery_call:'+('b'*64),recovery)
    if mutation=='malformed_text_owner': cs.store.set('model_recovery_call:'+('0'*64),{'role':'text_tool','invocation_owner':'invalid'})
    if mutation=='malformed_text_operation': cs.store.set('model_recovery_call:'+('0'*64),{'role':'text_tool','invocation_owner':{'operation':'invalid'}})
    if mutation=='duplicate_target': cs.store.set('model_recovery_call:'+('0'*64),recovery)
    if mutation=='mixed_owner_string': cs.store.set('model_recovery_call:'+('0'*64),{'role':'coordinator','invocation_owner':'legacy-owner'})
    if mutation=='mixed_operation_string': cs.store.set('model_recovery_call:'+('0'*64),{'role':'coordinator','invocation_owner':{'operation':'legacy-operation'}})
    checkpoint={'ts':'2026-01-01T00:00:00+00:00','channel_versions':{'a':1},'channel_values':{'branch:to:model':None,'messages':messages}}
    if mutation=='wrong_branch': checkpoint['channel_values']['branch:to:other']=None
    saved=SimpleNamespace(config={'configurable':{'thread_id':'report','checkpoint_ns':'tools:graph-task','checkpoint_id':'child-head'}},metadata={'parents':{'':'root-head'},'lc_agent_name':actor.role},checkpoint=checkpoint,pending_writes=[('node','__error__',"RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')")])
    if mutation=='wrong_error': saved.pending_writes=[('node','__error__',"RuntimeError('other')")]
    class Saver:
        async def aget_tuple(self, config):
            await asyncio.sleep(0)
            return saved
    runtime=SimpleNamespace(config={'configurable':{'thread_id':'report','checkpoint_ns':'tools:graph-task','__pregel_task_id':'graph-task','__pregel_resuming':True,'checkpoint_map':{'':'root-head'},'__pregel_checkpointer':Saver()}})
    identifier='fixture'; path=cs.store.root/'diagnostics'/'private'/(identifier+'.json');path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps({'id':identifier,'at':'2026-01-02T00:00:00+00:00','phase':'native_graph','public_error':{'type':'RequestBudgetExceeded','message':'HOST_TECHNICAL_FAILURE_PENDING'}}).encode();path.write_bytes(raw)
    with unknown_child_resume(cs.store,call_id=call['id'],task_id=actor.task_id,diagnostic_id=identifier,diagnostic_sha256=hashlib.sha256(raw).hexdigest(),checkpoint_id='child-head',parent_checkpoint_id='root-head'):
        result=await asyncio.gather(*[_resume_original_checkpoint(cs,actor,call,deepcopy(previous),runtime) for _ in range(2)])
    assert sorted(result)==([False,True] if mutation in ('none','mixed_owner_string','mixed_operation_string') else [False,False])
