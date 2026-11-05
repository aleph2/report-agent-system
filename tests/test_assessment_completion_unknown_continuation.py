"""One owner-approved fresh inference preserves the exact unknown hold and prior context."""
import json
import hashlib
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from report_agent import assessment_completion as api
from report_agent import model_recovery
from report_agent.store import digest
from report_agent.request_budget import RequestBudgetExceeded
from test_assessment_completion import reserve
from test_assessment_completion_extension import extension, write

HELD = '6e3df9b9-d8b8-459a-86c7-e3adada9a3e1'
FRESH_OPERATION = 'delegate:owner-approved-assessment-completion-fresh-continuation'


@pytest.fixture
def fresh(extension):
    f=extension
    f.held=[HELD,'writer-model',2_000_000,None,'reserved',None,None,'2026-11-05T20:09:00.971753+00:00']
    with f.budget.connect() as db: db.execute('insert into attempts values (?,?,?,?,?,?,?,?)',f.held)
    f.record={'state':'unknown','active':False,'raw':None,'role':'writer','full_input_sha256':'old-full-input',
        'invocation_owner':{'actor':f.prior['writer_actor'],'invocation':{'delegate_operation_id':'delegate:previous'}}}
    with sqlite3.connect(f.case/'state.db') as db:
        db.execute('create table state(key text primary key,value text)')
        db.execute('insert into state values (?,?)',('model_recovery_call:old',json.dumps(f.record)))
    old=deepcopy(f.prior)
    old.update(status='blocked',error_type='RecoveryBlocked',maximum_tokens=20_000_000,
        binding={**f.binding,'extension_authority_sha256':api._sha(f.path),
            'original_baseline_sha256':api._sha(f.evidence/'completion-budget-baseline.json'),
            'prior_launch_sha256':api._sha(f.evidence/'writer-launch.json')})
    old['budget'].update(maximum_tokens=20_000_000,reserved_or_unknown_upper_bounds=2_000_000)
    write(f.folder/'writer-launch.json',old)
    f.folder=f.folder/'fresh-continuation';f.folder.mkdir()
    f.path=f.folder/'owner-approval.json';f.binding['code_sha256']='fresh-code'
    f.authority={'turn_id':'owner-turn','message_id':'fresh-owner-message','owner_answer':'Continue with the 2M hold preserved',
        'maximum_tokens':20_000_000,'held_attempt_id':HELD,'held_tokens':2_000_000,
        'held_row':f.held,'held_row_sha256':digest(f.held),'grant_limit_unchanged':api.GRANT_LIMIT,
        'prior_launch_path':str(f.evidence/'extension-1/writer-launch.json'),
        'prior_launch_sha256':api._sha(f.evidence/'extension-1/writer-launch.json'),
        'original_baseline_path':str(f.evidence/'completion-budget-baseline.json'),
        'original_baseline_sha256':api._sha(f.evidence/'completion-budget-baseline.json'),
        'prior_extension_authority_sha256':api._sha(f.evidence/'extension-1/owner-approval.json'),
        'recovery_state_key':'model_recovery_call:old','recovery_record_sha256':digest(f.record),
        'recovery_full_input_sha256':'old-full-input','blocked_body_sha256':'old-wire','checkpoint_id':'saved-model-checkpoint',
        'code_sha256':'fresh-code'}
    write(f.path,f.authority)
    return f


def check(f):
    return api.require_fresh_continuation(f.case,f.evidence,f.path,f.binding,api.read_finance(f.budget.path))


def guard(f):
    return api.CompletionBudget(lambda:api.read_finance(f.budget.path),f.original,f.original,
        f.budget.model_bounds,writer_model='writer-model',maximum_tokens=20_000_000,preserved_hold=f.held)


def test_exact_hold_is_preserved_and_counted_together_with_current_request(fresh):
    f=fresh;check(f);g=guard(f);before=deepcopy(f.held)
    reserve(f.budget,g)
    assert g.check()==(8_097_818,4_000_000)
    assert g.observation()['remaining_for_new_reservations']==7_902_182
    assert next(row for row in api.read_finance(f.budget.path)['rows'] if row[0]==HELD)==before


@pytest.mark.parametrize('column,value',[(2,1_000_000),(3,0),(4,'unknown'),(5,'response'),(6,'changed'),(7,'changed')])
def test_preserved_hold_cannot_be_altered(fresh,column,value):
    f=fresh;g=guard(f)
    row=deepcopy(f.held);row[column]=value
    with f.budget.connect() as db:
        db.execute('delete from attempts where id=?',(HELD,));db.execute('insert into attempts values (?,?,?,?,?,?,?,?)',row)
    with pytest.raises(RequestBudgetExceeded,match='PRESERVED_HOLD_CHANGED'):g.check()


@pytest.mark.parametrize('state',['reserved','unknown'])
def test_every_other_unresolved_attempt_still_blocks_another_request(fresh,state):
    f=fresh;g=guard(f);new=f.budget.reserve('writer-model')
    if state=='unknown':f.budget.settle(new,None)
    with pytest.raises(RequestBudgetExceeded,match='UNRESOLVED_ATTEMPT'):reserve(f.budget,g)
    assert next(row for row in api.read_finance(f.budget.path)['rows'] if row[0]==HELD)==f.held


def test_preserved_hold_is_never_subtracted_from_twenty_million_cap(fresh):
    f=fresh;g=guard(f)
    for _ in range(5):f.budget.settle(f.budget.reserve('writer-model'),{'total_tokens':1_800_000})
    assert g.check()==(17_097_818,2_000_000)
    with pytest.raises(RequestBudgetExceeded,match='TOKEN_LIMIT'):reserve(f.budget,g)
    assert next(row for row in api.read_finance(f.budget.path)['rows'] if row[0]==HELD)==f.held


@pytest.mark.parametrize('fault',['source','authority','hold','recovery','extra_pending','duplicate'])
def test_fresh_authority_is_one_shot_and_fully_pinned(fresh,fault):
    f=fresh
    if fault=='source':f.binding['source_db_sha256']='changed'
    elif fault=='authority':f.authority['owner_answer']='ordinary plan approval';write(f.path,f.authority)
    elif fault=='hold':f.authority['held_row'][2]=0;write(f.path,f.authority)
    elif fault=='recovery':
        with sqlite3.connect(f.case/'state.db') as db:db.execute('update state set value=?',(json.dumps({**f.record,'active':True}),))
    elif fault=='extra_pending':f.budget.reserve('writer-model')
    else:api.claim_launch(f.folder/'writer-launch.json',{'status':'unknown'})
    with pytest.raises((ValueError,FileExistsError,RequestBudgetExceeded)):check(f)


def test_prior_launches_and_original_baseline_are_unchanged_by_preflight(fresh):
    f=fresh
    paths=[f.evidence/'writer-launch.json',f.evidence/'extension-1/writer-launch.json',f.evidence/'completion-budget-baseline.json']
    before=[p.read_bytes() for p in paths];a,original,prior=check(f)
    assert original['baseline']==f.original and prior['writer_actor']['task_id']=='same'
    assert [p.read_bytes() for p in paths]==before


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['wire','input','key','missing','role','marker','system','ok'])
async def test_old_logical_or_wire_identity_is_refused_before_financial_reservation(fresh,monkeypatch,fault):
    from report_agent.token_budget import token_budget
    from report_agent.request_budget import account_request
    f=fresh;notice=api.fresh_continuation_notice(f.authority)
    body={'model':'writer-model','messages':[{'role':'user','content':notice if fault!='marker' else 'not authority'}]}
    if fault=='system':body['messages'][0]['role']='system'
    request=httpx.Request('POST','https://example.invalid/chat/completions',json=body)
    record={'role':'writer','full_input_sha256':'fresh-full-input','invocation_owner':{
        'actor':f.prior['writer_actor'],'invocation':{'delegate_operation_id':FRESH_OPERATION}}}
    if fault=='wire':f.authority['blocked_body_sha256']=hashlib.sha256(request.content).hexdigest()
    if fault=='input':record['full_input_sha256']=f.authority['recovery_full_input_sha256']
    if fault=='role':record['role']='coordinator'
    if fault=='marker':request=httpx.Request('POST','https://example.invalid/chat/completions',json={**body,'arbitrary_marker':notice})
    monkeypatch.setattr(model_recovery,'_load_call',lambda store,key:record)
    monkeypatch.setattr(model_recovery,'load_recovery_policy',lambda store:None)
    active=None if fault=='missing' else (SimpleNamespace(root=f.case),
        f.authority['recovery_state_key'] if fault=='key' else 'model_recovery_call:fresh','owner',0)
    token=model_recovery._ACTIVE.set(active)
    before=api.read_finance(f.budget.path)
    try:
        hook=api.fresh_request_guard(f.case,f.authority,f.prior['writer_actor'])
        with token_budget(f.budget):
            if fault in ('ok','system'):await hook(request);await account_request(request)
            else:
                with pytest.raises(model_recovery.RecoveryBlocked):await hook(request);await account_request(request)
    finally:model_recovery._ACTIVE.reset(token)
    after=api.read_finance(f.budget.path)
    assert len(after['rows'])-len(before['rows'])==(1 if fault in ('ok','system') else 0)
    assert next(row for row in after['rows'] if row[0]==HELD)==f.held


@pytest.mark.parametrize('error',["RecoveryBlocked('RECOVERY_PRIOR_ATTEMPT_UNRESOLVED')","ReadTimeout('unknown')"])
def test_prior_model_checkpoint_error_must_match_fresh_authority(error):
    state=SimpleNamespace(next=('model',),tasks=(SimpleNamespace(name='model',id='saved-task',error=error),),
        config={'configurable':{'thread_id':'bounded-assessment-completion','checkpoint_id':'saved-model-checkpoint'}})
    if error.startswith('RecoveryBlocked'):
        assert api.require_continuation_checkpoint(state,fresh_authority={'checkpoint_id':'saved-model-checkpoint'})['next']==['model']
    else:
        with pytest.raises(ValueError):api.require_continuation_checkpoint(state,fresh_authority={'checkpoint_id':'saved-model-checkpoint'})


@pytest.mark.asyncio
async def test_native_summary_prefix_changes_only_with_genuine_authority_notice(tmp_path,monkeypatch):
    from langchain_core.messages import AIMessage,HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    import deepagents.graph
    from deepagents.middleware.summarization import SummarizationMiddleware
    from report_agent.content_tasks import delegated_task
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver
    from functools import wraps
    from inspect import signature
    stock=deepagents.graph.create_summarization_middleware
    @wraps(stock)
    def forced(model,backend,**kwargs):
        defaults=stock(model,backend,**kwargs)
        return SummarizationMiddleware(model=model,backend=backend,trigger=('messages',3),keep=('messages',1),
            summary_prompt=kwargs.get('summary_prompt',signature(stock).parameters['summary_prompt'].default))
    monkeypatch.setattr(deepagents.graph,'create_summarization_middleware',forced)
    outputs=[]
    authority={'message_id':'fresh-owner','held_attempt_id':HELD,'held_row':[HELD,'writer-model'],
        'recovery_state_key':'model_recovery_call:old','recovery_full_input_sha256':'old-full','blocked_body_sha256':'old-wire'}
    notice=api.fresh_continuation_notice(authority)
    for suffix in ['',notice]:
        store=Store(tmp_path/('fresh' if suffix else 'old'))
        store.initialize({'goal':'Synthetic context continuation','content_contract':'hierarchical-review-v1',
            'review_interface_profile':'review-interfaces-v4','assembly_contract':'system-assembler-v1',
            'review_entrypoint':'delegated-reviewer-v1','review_execution_mode':'native-reviewer-v2',
            'delegation_prompt_profile':'separate-description-v1','operation_identity_profile':'native-tool-runtime-v1',
            'report_expression_profile':'reader-expression-v2','report_prompt_profile':'concise-v1',
            'sources':[{'id':'source','title':'Synthetic','content':'saved evidence','coverage':'complete'}]})
        ws=Workspace(store);ContentStore(store)
        driver=Driver(writer=[AIMessage(content='Synthetic retained context')])
        with delegated_task(ws,'coordinator',{'name':'task','id':api.FRESH_OPERATION,'args':{
                'subagent_type':'writer','description':'Continue only the same authorized task.'}}) as (_,actor):
            agent=api.build_writer_agent(ws,driver('writer'),[],lambda:False,InMemorySaver(),continuation_notice=suffix or None)
            await agent.ainvoke({'messages':[HumanMessage(content='Prior evidence '+str(i)) for i in range(4)]+
                [HumanMessage(content=notice)]},{'configurable':{'thread_id':'same-checkpoint'}})
            if suffix:
                await agent.ainvoke({'messages':[HumanMessage(content='Continue the approved work.')]},
                    {'configurable':{'thread_id':'same-checkpoint'}})
                actual=driver.calls[-1][2]
                assert any(m.type=='system' and notice in str(m.content) for m in actual)
                assert not any(m.type=='human' and notice in str(m.content) for m in actual)
                record={'role':'writer','full_input_sha256':'fresh-full','invocation_owner':{
                    'actor':actor.__dict__,'invocation':{'delegate_operation_id':FRESH_OPERATION}}}
                monkeypatch.setattr(model_recovery,'_load_call',lambda store,key:record)
                token=model_recovery._ACTIVE.set((store,'model_recovery_call:fresh','owner',0))
                try:
                    payload={'model':'writer-model','messages':[{'role':{'system':'system','human':'user','ai':'assistant'}[m.type],
                        'content':m.content} for m in actual]}
                    await api.fresh_request_guard(store.root,authority,actor.__dict__)(
                        httpx.Request('POST','https://example.invalid/chat/completions',json=payload))
                finally:model_recovery._ACTIVE.reset(token)
                with store.connect() as db:
                    statuses=[json.loads(row[0])['status'] for row in db.execute(
                        "select data from events where kind='prompt_model_input'")]
                assert statuses and set(statuses)=={'exact'}
        summary_inputs=[str(messages[0].content) for _,_,messages in driver.calls if len(messages)==1]
        assert summary_inputs
        outputs.append(summary_inputs[0])
    assert notice not in outputs[0]  # Newest owner message is outside the summarized older partition.
    assert notice in outputs[1]
    assert outputs[0]!=outputs[1]
