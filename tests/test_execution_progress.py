"""Opt-in native observed-repetition protection; no semantic/autonomy claims."""
import json
from collections import Counter
from contextlib import asynccontextmanager

import httpx
import pytest
from langchain_core.messages import ToolMessage

from report_agent import deep_runtime
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.errors import ActionRejected
from report_agent.store import encode
from report_agent.task_context import save_observation
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.request_budget import RequestBudget, request_budget
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission
from test_prompt_native_sdk_inputs import completion

CONFIG={'version':1,'window':64,'repeats':3,'after_notice':2}


@asynccontextmanager
async def sdk_case(ws, monkeypatch, *, child=False, alternating=False, unbound=False,
                   capture=True, truncated=False, siblings=False, compact=False, enabled=True):
    native(ws); cs,owner,refs,snap,_=seed(ws)
    manifest=ws.store.manifest; manifest['context_policy']='stateful-tools-v2'
    if enabled: manifest['execution_progress_policy']=CONFIG
    ws.store.set('manifest',manifest)
    if not capture:
        monkeypatch.setattr('report_agent.prompt_provenance.observe_prompt_request',lambda *a,**kw:None)
    summary_calls=[]
    if compact:
        from langchain_core.runnables import RunnableLambda
        from report_agent.working_summary import WorkingSummary
        async def summarize(prompt): summary_calls.append(prompt); return __import__('langchain_core.messages',fromlist=['AIMessage']).AIMessage('Unverified working notes only.')
        monkeypatch.setattr('report_agent.working_summary.working_summary',lambda model,store,role:
            WorkingSummary(model=RunnableLambda(summarize),store=store,role=role,
                trigger=('messages',10),keep=('messages',3),token_counter=lambda messages:len(messages),trim_tokens_to_summarize=None))
    raw_ref,_=save_observation(ws,'coordinator',ToolMessage('Unbound scratch text.',name='read_file',tool_call_id='raw'))
    models,wires,steps={},[],Counter(); target='reviewer' if child else 'coordinator'
    controls={'stop':False,'novel_at':None,'novel_tool_at':None,'bound_after':None,'snapshot_at':None,'timeout_at':None,'max_reads':12}
    def factory(role):
        if role in models:return models[role]
        client=model_async_client(ws.store,role)
        def transport(request):
            body=json.loads(request.content); index=steps[role]; steps[role]+=1; wires.append((role,body))
            if role==target and controls['timeout_at']==index:
                raise httpx.ReadTimeout('Synthetic recovery request entered transport without a response.',request=request)
            tool=None
            if child and role=='coordinator' and index==0: tool=('task',commission(snap,refs))
            elif role==target and not controls['stop'] and index<controls['max_reads']:
                offset=index%2 if alternating else (1 if controls['novel_at']==index else 0)
                active_snapshot=(controls['snapshot_at'][1] if controls['snapshot_at'] and index>=controls['snapshot_at'][0] else snap)
                tool=('read_tool_observation',{'observation_ref':raw_ref,'offset':0,'characters':20}) if unbound and (
                    controls['bound_after'] is None or index<controls['bound_after']) else (
                    'read_content_index',{'snapshot_ref':active_snapshot,'offset':offset,'limit':1})
                if controls['novel_tool_at']==index:tool=('read_source_page',{'source_id':'s','offset':0,'limit':1})
            response=completion(request,'Synthetic partial result; no engineering acceptance.',tool)
            data=json.loads(response.content); data['id']='progress-response-'+role+'-'+str(index)
            if tool:
                calls=data['choices'][0]['message']['tool_calls']; calls[0]['id']+='-'+role+'-'+str(index)
                if siblings and index==0:
                    calls.extend([{**calls[0],'id':calls[0]['id']+'-sibling-'+str(i)} for i in range(2)])
                    controls['stop']=True
            if truncated:data['choices'][0]['finish_reason']='length'
            return httpx.Response(200,json=data)
        client._transport=httpx.MockTransport(transport); client._mounts.clear()
        models[role]=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        yield {'factory':factory,'wires':wires,'steps':steps,'controls':controls,'cs':cs,'refs':refs,'snapshot':snap,'summary_calls':summary_calls,'raw_ref':raw_ref}
    finally:
        for model in models.values():await model.root_async_client.close();model.root_client.close()


def episodes(ws):
    from report_agent.execution_progress import active_episodes
    return active_episodes(ws)


@pytest.mark.parametrize('config',[True,{},{'version':1,'window':True},
    {**CONFIG,'repeats':0},{**CONFIG,'after_notice':0},{**CONFIG,'window':2},{**CONFIG,'extra':'unknown'}])
def test_bad_policy_refuses_before_model_factory(ws,config):
    native(ws)
    manifest=ws.store.manifest;manifest.update(context_policy='stateful-tools-v2',execution_progress_policy=config)
    ws.store.set('manifest',manifest)
    with pytest.raises(ActionRejected,match='PROGRESS_POLICY'):
        deep_runtime.build_agent(ws,lambda role:pytest.fail('model factory called'),None)


def test_policy_requires_effective_v2_and_old_missing_is_off(ws):
    from report_agent.execution_progress import validate_policy
    native(ws);assert validate_policy(ws) is None
    manifest=ws.store.manifest;manifest.update(context_policy='stateful-tools-v2',execution_progress_policy=CONFIG);ws.store.set('manifest',manifest)
    ws.store.set('context_policy','stateful-tools-v1')
    with pytest.raises(ActionRejected,match='PROGRESS_POLICY_REQUIRES'):
        validate_policy(ws)


@pytest.mark.parametrize('child',[False,True],ids=['co-requested-snapshot','native-reviewer'])
async def test_actual_notice_and_two_distinct_completed_decisions_pause_native_graph(ws,monkeypatch,child):
    async with sdk_case(ws,monkeypatch,child=child) as case:
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')=='needs_attention'
        episode,=episodes(ws)
        assert episode['state']=='degraded' and len(episode['notice_deliveries'])>=2
        assert episode['scope']['role']==('reviewer' if child else 'coordinator')
        assert case['steps'][episode['scope']['role']]==5
        delivered=[body for role,body in case['wires'] if 'notice_id' in encode(body['messages'])]
        assert len(delivered)==2
        assert all(encode(body['messages']).count('notice_id')==1 for body in delivered)
        assert all('Execution observation: the last three' not in encode(body['messages']) for body in delivered)
        count=len(case['wires'])
        await deep_runtime.run_report(ws,case['factory'])
        assert len(case['wires'])==count and ws.store.get('report_status')=='needs_attention'
        assert not case['cs'].list_objects('ReviewRecord')


@pytest.mark.parametrize('kind',['missing-capture','truncated','unbound','off','siblings'])
async def test_unproven_or_single_decision_repetition_does_not_hard_pause(ws,monkeypatch,kind):
    async with sdk_case(ws,monkeypatch,capture=kind!='missing-capture',truncated=kind=='truncated',
                        unbound=kind=='unbound',enabled=kind!='off',siblings=kind=='siblings') as case:
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')!='needs_attention'
        assert not any(e['state']=='degraded' for e in episodes(ws))
        if kind in {'off','siblings'}:
            assert not any('notice_id' in encode(body['messages']) for _,body in case['wires'])


async def test_alternating_warned_pages_survive_summary_and_checkpoint(ws,monkeypatch):
    async with sdk_case(ws,monkeypatch,alternating=True,compact=True) as case:
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')=='needs_attention'
        episode,=episodes(ws)
        assert len(episode['warned_family'])==2 and case['steps']['coordinator']<=9
        assert case['summary_calls']
        before=len(case['wires']); summaries=len(case['summary_calls'])
        await deep_runtime.run_report(ws,case['factory'])
        assert len(case['wires'])==before and len(case['summary_calls'])==summaries


async def test_new_return_breaks_continuation_without_erasing_episode(ws,monkeypatch):
    async with sdk_case(ws,monkeypatch) as case:
        case['controls'].update(novel_at=3,max_reads=5)
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')!='needs_attention'
        records=episodes(ws)
        assert records and all(e['state']!='degraded' for e in records)
        assert any(e['kind']=='execution_progress_new_return' for e in ws.store.events())


async def test_host_recovery_needs_effective_instruction_same_ledger_and_bounded_window(ws,monkeypatch,tmp_path):
    from report_agent.execution_progress import authorize_recovery
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate,release
    ledger=TokenBudget(tmp_path/'original-budget.db',20000,{'glm-5.3':1000})
    old_id=ledger.reserve('glm-5.3')
    with ledger.connect() as db: old_row=db.execute('SELECT * FROM attempts WHERE id=?',(old_id,)).fetchone()
    with token_budget(ledger):
        async with sdk_case(ws,monkeypatch) as case:
            await deep_runtime.run_report(ws,case['factory']); episode,=episodes(ws)
            configure_report(ws.store,'recovery-fixture')
            instruction=candidate(ws,text='New direct fixture instruction: retain the uncertainty and finish this scoped observation.')
            condition={'kind':'effective_instruction','ref':instruction['ref']}
            with request_budget(RequestBudget(2)),pytest.raises(ActionRejected,match='PROGRESS_RECOVERY'):
                authorize_recovery(ws,episode['episode_id'],condition,authorization_basis='Direct test host authority',reason='Actual new instruction.',max_http_attempts=2)
            release(ws,instruction)
            with pytest.raises(ActionRejected,match='PROGRESS_RECOVERY'):
                authorize_recovery(ws,episode['episode_id'],condition,authorization_basis='Direct test host authority',reason='Actual new instruction.',max_http_attempts=2)
            case['controls']['stop']=True
            with request_budget(RequestBudget(2)):
                grant=authorize_recovery(ws,episode['episode_id'],condition,authorization_basis='Direct test host authority',reason='Actual new instruction.',max_http_attempts=2)
                before=len(case['wires']); await deep_runtime.run_report(ws,case['factory'])
                assert 0<len(case['wires'])-before<=2
                with pytest.raises(ActionRejected,match='PROGRESS_RECOVERY'):
                    authorize_recovery(ws,episode['episode_id'],condition,authorization_basis='Direct test host authority',reason='Do not replay grant.',max_http_attempts=2)
    with ledger.connect() as db: assert db.execute('SELECT * FROM attempts WHERE id=?',(old_id,)).fetchone()==old_row


def test_runtime_learning_feedback_is_typed_and_not_a_report_correction(ws,tmp_path):
    from report_agent.learning import LearningLibrary,LearningScope
    library=LearningLibrary(tmp_path/'learning'); scope=LearningScope('fixture-customer',str(ws.store.root))
    event={'episode_id':'fixture-episode','state':'degraded','scope':{'actor_id':'content:coordinator','task_id':'content-task:coordinator','role':'coordinator'},
        'observed_refs':[{'observation_ref':'a'*64,'sha256':'b'*64}], 'notice_deliveries':[{'call_id':'actual-fixture-call'}],
        'outcome':'suspected_repetition_pause_not_semantic_failure'}
    first=library.runtime_observation(scope,event)
    assert first['kind']=='runtime_observation' and 'correction' not in first
    assert library.runtime_observation(scope,event)==first and len(library.queue_status(scope))==1
    assert library.list_versions(scope)==[]


@pytest.mark.parametrize('variant',['valid','missing-capture','wrong-call','missing-notice','length','multiple-response','physical-retry'])
def test_same_call_response_receipt_requires_actual_notice_and_complete_response(ws,variant):
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from report_agent.prompt_provenance import prompt_call,bind_wire_payload,observe_prompt_request,progress_response_fact
    text='Execution feedback: exact fixture notice.'
    part={'source':'execution_progress/repetition','text':text,
        'references':{'episode_id':'actual-episode','notice_id':'actual-notice','family':['signature']}}
    payload={'model':'fixture','messages':[{'role':'system','content':text if variant!='missing-notice' else 'Other guidance.'}]}
    with prompt_call(ws.store,'coordinator',status='exact',offered=payload) as call:
        bind_wire_payload(payload)
        request=httpx.Request('POST','https://fixture.invalid/v1/chat/completions',json=payload)
        if variant!='missing-capture':observe_prompt_request(request,ws.store,'coordinator')
        if variant=='physical-retry':observe_prompt_request(request,ws.store,'coordinator')
        assistant=AIMessage('',id='actual-decision',response_metadata={'finish_reason':'length' if variant=='length' else 'stop'})
        response=SimpleNamespace(result=[assistant,assistant] if variant=='multiple-response' else [assistant])
        progress_response_fact(ws.store,{**call,'call_id':'foreign'} if variant=='wrong-call' else call,response,[part])
    fact=ws.store.get(next(e['data']['capture_key'] for e in reversed(ws.store.events()) if e['kind']=='prompt_response_fact'))
    assert bool(fact['completed'] and fact['notices']) == (variant in {'valid','physical-retry'})
    if variant=='physical-retry':assert len(fact['final_capture_refs'])==1


async def test_native_protection_precedes_summary_model_invocation(ws,monkeypatch):
    from langchain_core.runnables import RunnableLambda
    from langchain_core.messages import AIMessage
    from report_agent.working_summary import WorkingSummary
    from report_agent.task_state_delivery import verified_frame
    invoked=[]
    async def summarize(prompt):invoked.append(prompt);return AIMessage('Notes.')
    monkeypatch.setattr('report_agent.working_summary.working_summary',lambda model,store,role:
        WorkingSummary(model=RunnableLambda(summarize),store=store,role=role,
            # Preserve the original business-message boundary despite added host controls.
            trigger=('tokens',11),keep=('messages',3),
            token_counter=lambda messages: sum(verified_frame(store, m) is None for m in messages),
            trim_tokens_to_summarize=None))
    async with sdk_case(ws,monkeypatch) as case:
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')=='needs_attention' and invoked==[]
        # The summary hook must be due at the real pause, not merely never reached.
        async with deep_runtime.project_agent(ws,case['factory']) as agent:
            paused = await agent.aget_state({'configurable': {'thread_id': 'report'}})
        assert paused.interrupts
        assert sum(verified_frame(ws.store, m) is None for m in paused.values['messages']) >= 11


async def test_arbitrary_native_resume_does_not_release_protection(ws,monkeypatch):
    from langgraph.types import Command
    async with sdk_case(ws,monkeypatch) as case:
        await deep_runtime.run_report(ws,case['factory']); before=len(case['wires'])
        async with deep_runtime.project_agent(ws,case['factory']) as agent:
            config={'configurable':{'thread_id':'report'}}
            await agent.ainvoke(Command(resume=True),config)
            state=await agent.aget_state(config)
        assert state.interrupts and len(case['wires'])==before


def test_episode_http_window_cannot_reset_with_a_new_request_budget(ws,tmp_path):
    from report_agent.execution_progress import reserve_recovery_request
    from report_agent.request_budget import request_reservation_observer,account_request_sync,RequestBudgetExceeded
    key='execution_progress_recovery:synthetic-window'
    ws.store.set(key,{'episode_id':'synthetic','state':'consumed','used':0,'maximum_http_attempts':1})
    request=httpx.Request('POST','https://fixture.invalid/v1/chat/completions',json={'model':'fixture'})
    with request_budget(RequestBudget(1)),request_reservation_observer(lambda:reserve_recovery_request(ws,key)):
        account_request_sync(request)
    assert ws.store.get(key)['used']==1
    with request_budget(RequestBudget(1)),request_reservation_observer(lambda:reserve_recovery_request(ws,key)),pytest.raises(RequestBudgetExceeded):
        account_request_sync(httpx.Request('POST','https://fixture.invalid/v1/chat/completions',json={'model':'fixture'}))
    assert ws.store.get(key)['used']==1


def test_typed_runtime_feedback_reads_via_existing_optimizer_without_dispatch(ws,tmp_path):
    from report_agent.learning import LearningLibrary,LearningScope
    from report_agent.learning_runtime import optimizer_tools
    path=tmp_path/'runtime-learning'
    ws.store.set('learning_config',{'library_path':str(path.resolve()),'customer_id':'runtime-fixture'})
    library=LearningLibrary(path);scope=LearningScope('runtime-fixture',str(ws.store.root))
    event={'episode_id':'observed','state':'degraded','scope':{'actor_id':'content:coordinator','task_id':'co','role':'coordinator'},
        'observed_refs':[],'notice_deliveries':[{'call_id':'delivered'}],'outcome':'suspected_only'}
    item=library.runtime_observation(scope,event)
    read=next(t for t in optimizer_tools(ws) if t.__name__=='read_learning_feedback')
    index=read()['feedback'][0]
    assert index['kind']=='runtime_observation' and 'correction_preview' not in index
    exact=read(item['id'],field='observation')
    assert json.loads(exact['text'])==event and exact['semantic_progress_verified'] is False
    assert library.list_versions(scope)==[] and ws.store.get('learning_job') is None


@pytest.mark.parametrize('variant',['authorized-new','same-bytes-alias','ungranted','changed-version','wrong-target','legacy-child'])
def test_host_material_condition_keeps_original_source_authority(ws,variant):
    from report_agent.catalog import Catalog
    from report_agent.source_use import configure_source_use
    from report_agent.execution_progress import _condition
    from report_agent.content_tasks import delegated_task
    from test_bounded_review import review_call
    cs,owner,refs,snapshot,_=seed(ws)
    extra=Catalog(ws.store).import_file('new-fixture.txt',b'Additional independent fixture evidence.')['source']['id']
    old_scope=None
    if variant=='legacy-child':
        with delegated_task(ws,'coordinator',review_call(snapshot,refs)) as (_,actor):
            from report_agent.execution_progress import _scope
            old_scope=_scope(ws,'reviewer')
    configure_source_use(ws.store,['s',extra],'Direct fixture authorization of exact supplied versions')
    if variant=='changed-version':
        extra=Catalog(ws.store).import_file('changed-fixture.txt',b'Unapproved changed evidence.',replaces_id=extra)['source']['id']
    if variant=='ungranted':
        extra=Catalog(ws.store).import_file('ungranted-fixture.txt',b'Not authorized.')['source']['id']
    source=cs.capture_sources(owner,'condition-material',['s' if variant=='same-bytes-alias' else extra])['result']['source_refs'][0]
    scope=old_scope or {**owner.__dict__,'actor_id':owner.id}
    episode={'scope':scope,'binding':{'snapshot_ref':snapshot,'root_ref':refs['root']}}
    condition={'kind':'authorized_material','ref':source,'target_ref':refs['claim'] if variant=='wrong-target' else refs['root']}
    if variant=='authorized-new':
        actual=_condition(ws,episode,condition)
        assert actual['ref']==source and actual['source_use_ref']
    else:
        with pytest.raises(ActionRejected,match='PROGRESS_RECOVERY|SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            _condition(ws,episode,condition)


async def test_recovery_cap_is_durable_in_actual_sdk_checkpoint_resume(ws,monkeypatch,tmp_path):
    from report_agent.execution_progress import authorize_recovery
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate,release
    ledger=TokenBudget(tmp_path/'recovery-ledger.db',30000,{'glm-5.3':1000})
    with token_budget(ledger):
        async with sdk_case(ws,monkeypatch) as case:
            await deep_runtime.run_report(ws,case['factory']); episode,=episodes(ws)
            configure_report(ws.store,'cap-fixture')
            instruction=candidate(ws,text='New fixture instruction: observe the same scoped work under this explicit changed instruction.')
            release(ws,instruction)
            with request_budget(RequestBudget(5)):
                grant=authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':instruction['ref']},
                    authorization_basis='Direct test authority',reason='Bounded observation only.',max_http_attempts=1)
                before=len(case['wires']); await deep_runtime.run_report(ws,case['factory'])
                assert len(case['wires'])-before==1
                assert ws.store.get(grant['key'])['used']==1
            assert ws.store.get('report_status')=='needs_attention'
            with request_budget(RequestBudget(5)):
                before=len(case['wires']); await deep_runtime.run_report(ws,case['factory'])
                assert len(case['wires'])==before


async def test_recovery_final_response_records_observation_not_semantic_success(ws,monkeypatch,tmp_path):
    from report_agent.execution_progress import authorize_recovery,EPISODES
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate,release
    ledger=TokenBudget(tmp_path/'final-recovery.db',30000,{'glm-5.3':1000})
    with token_budget(ledger):
        async with sdk_case(ws,monkeypatch) as case:
            from report_agent.learning import LearningLibrary,LearningScope
            library_path=tmp_path/'completion-learning'
            ws.store.set('learning_config',{'library_path':str(library_path),'customer_id':'completion-fixture'})
            library=LearningLibrary(library_path);scope=LearningScope('completion-fixture',str(ws.store.root))
            await deep_runtime.run_report(ws,case['factory']); episode,=episodes(ws)
            configure_report(ws.store,'final-fixture')
            instruction=candidate(ws,text='New fixture instruction: preserve uncertainty and return this bounded observation.')
            release(ws,instruction);case['controls']['stop']=True
            with request_budget(RequestBudget(2)):
                authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':instruction['ref']},
                    authorization_basis='Direct test authority',reason='Return-only observation.',max_http_attempts=1)
                await deep_runtime.run_report(ws,case['factory'])
            outcome=ws.store.get(EPISODES+episode['episode_id'])
            assert outcome['state']=='observation_completed'
            assert outcome['outcome']=='completed_response_observed_not_semantic_repair'
            assert not case['cs'].list_objects('ReviewRecord')
            assert len(library.queue_status(scope))==2
            assert not any(e['kind']=='execution_progress_learning_gap' for e in ws.store.events())


async def test_other_actual_return_breaks_warned_family_streak(ws,monkeypatch):
    async with sdk_case(ws,monkeypatch) as case:
        case['controls'].update(novel_tool_at=4,max_reads=6)
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')!='needs_attention'
        assert case['steps']['coordinator']==7
        assert not any(e['state']=='degraded' for e in episodes(ws))


async def test_recovery_first_reread_under_new_instruction_is_not_recurrence(ws,monkeypatch,tmp_path):
    from report_agent.execution_progress import authorize_recovery,EPISODES
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate,release
    ledger=TokenBudget(tmp_path/'legitimate-reread.db',30000,{'glm-5.3':1000})
    with token_budget(ledger):
        async with sdk_case(ws,monkeypatch) as case:
            await deep_runtime.run_report(ws,case['factory']);episode,=episodes(ws)
            configure_report(ws.store,'reread-fixture')
            instruction=candidate(ws,text='New fixture question requires a fresh look at the same original page.')
            release(ws,instruction)
            case['controls'].update(novel_tool_at=6,max_reads=7)
            with request_budget(RequestBudget(5)):
                authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':instruction['ref']},
                    authorization_basis='Direct test authority',reason='Legitimate fresh reread.',max_http_attempts=4)
                await deep_runtime.run_report(ws,case['factory'])
            assert case['steps']['coordinator']==8
            assert ws.store.get(EPISODES+episode['episode_id'])['state']=='observation_completed'


async def test_second_condition_cannot_overwrite_active_recovery_grant(ws,monkeypatch,tmp_path):
    from report_agent.execution_progress import authorize_recovery
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate,release
    ledger=TokenBudget(tmp_path/'active-grant.db',30000,{'glm-5.3':1000})
    with token_budget(ledger):
        async with sdk_case(ws,monkeypatch) as case:
            await deep_runtime.run_report(ws,case['factory']);episode,=episodes(ws)
            configure_report(ws.store,'grant-fixture')
            first=candidate(ws,id='first',topic='first',text='First effective fixture change.')
            second=candidate(ws,id='second',topic='second',text='Second effective fixture change.')
            release(ws,first);release(ws,second)
            with request_budget(RequestBudget(3)):
                grant=authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':first['ref']},
                    authorization_basis='Direct test authority',reason='First grant.',max_http_attempts=1)
                with pytest.raises(ActionRejected,match='PROGRESS_RECOVERY_ACTIVE_GRANT'):
                    authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':second['ref']},
                        authorization_basis='Direct test authority',reason='Must not overwrite.',max_http_attempts=1)
                assert ws.store.get('execution_progress_episode:'+episode['episode_id'])['recovery_key']==grant['key']


@pytest.mark.parametrize('mode',['cap','persistence'])
async def test_local_recovery_refusal_preserves_exact_zero_send_and_old_financial_row(tmp_path,monkeypatch,mode):
    from test_model_recovery import active_model,calls
    from test_transport_observation import use_mock,close,body
    from report_agent.request_budget import request_reservation_observer,RequestBudgetExceeded
    import sqlite3
    store,model=await active_model(tmp_path,monkeypatch)
    seen=[]
    await use_mock(model,lambda request:seen.append(request) or httpx.Response(200,json=body()))
    ledger=TokenBudget(tmp_path/'local-cap.db',200,{'deepseek-v4.1-flash':40})
    old=ledger.reserve('deepseek-v4.1-flash')
    with ledger.connect() as db:before=db.execute('SELECT * FROM attempts WHERE id=?',(old,)).fetchone()
    def refuse():
        if mode=='persistence':raise sqlite3.OperationalError('synthetic durable write unavailable')
        raise RequestBudgetExceeded('RECOVERY_OBSERVATION_HTTP_LIMIT')
    try:
        with token_budget(ledger),request_budget(RequestBudget(2)),request_reservation_observer(refuse):
            with pytest.raises(RequestBudgetExceeded):await model.ainvoke('local cap fixture')
        assert seen==[]
        receipt,=calls(store)
        assert receipt['state']=='local_admission_blocked'
        assert receipt['provider_outcome']=='not_dispatched'
        assert receipt['admission_proof']['admitted_http_attempts']==0
        assert receipt['extra_calls']==0
        with ledger.connect() as db:assert db.execute('SELECT * FROM attempts WHERE id=?',(old,)).fetchone()==before
    finally:await close(model)


@pytest.mark.parametrize('variant',['unbound-to-bound','snapshot-change'])
async def test_new_binding_gets_its_own_feedback_without_unlocking_protection(ws,monkeypatch,variant):
    async with sdk_case(ws,monkeypatch,unbound=variant=='unbound-to-bound') as case:
        if variant=='unbound-to-bound':
            case['controls']['bound_after']=3
            expected=case['snapshot']
        else:
            original=case['cs'].read(case['snapshot'])['payload']
            from report_agent.hierarchical_tools import actor_for
            expected=case['cs'].freeze(actor_for('coordinator'),'second-snapshot',original['root_ref'],original['refs'])['result']['snapshot_ref']
            case['controls']['snapshot_at']=(3,expected)
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')=='needs_attention'
        episode,=episodes(ws)
        assert episode['state']=='degraded' and episode['binding']['snapshot_ref']==expected
        assert case['steps']['coordinator']==8
        assert len([e for e in ws.store.events() if e['kind']=='execution_progress_observed'])==2


async def test_notice_preview_keeps_real_recovery_navigation_and_exact_warned_subset(ws,monkeypatch):
    from types import SimpleNamespace
    from langchain_core.messages import SystemMessage
    from report_agent.execution_progress import ExecutionProgress,EPISODES
    native(ws);cs,owner,refs,snapshot,_=seed(ws)
    manifest=ws.store.manifest;manifest.update(context_policy='stateful-tools-v2',execution_progress_policy=CONFIG);ws.store.set('manifest',manifest)
    middleware=ExecutionProgress(ws,'coordinator');key,control=middleware.control()
    monkeypatch.setattr('report_agent.prompt_sources.load_prompt',
        lambda name: pytest.fail('Runtime observations must not load additional prompt files'))
    family=[str(i).zfill(64) for i in range(20)]
    binding={'scope_kind':'requested_snapshot_scope','snapshot_ref':snapshot,'root_ref':refs['root'],
        'instruction_digest':None,'source_use_ref':None,'criterion_refs':[refs['k']]*100}
    episode={'episode_id':'large-binding','state':'observing','scope':control['scope'],'binding':binding,
        'binding_digest':'b'*64,'family':family,'observed_refs':[{'index':9,'observation_ref':'a'*64,'sha256':'b'*64,'tool':'read_content_index','call_id':'c'}]}
    control['episode_id']=episode['episode_id'];middleware.save(key,control,episode)
    request=SimpleNamespace(system_message=SystemMessage('Existing unchanged role.'),messages=[])
    request.override=lambda **kw:SimpleNamespace(**{**request.__dict__,**kw})
    seen=[]
    async def handler(actual):seen.append(actual);return SimpleNamespace(result=[])
    await middleware.awrap_model_call(request,handler)
    contribution=seen[0].system_message.additional_kwargs['report_system_contributions'][-1]
    packet=json.loads(contribution['text'])
    assert 'notice_id' in packet
    assert 'files' not in contribution
    assert len(encode(packet))<=4096 and packet['family']==family[:8]
    assert contribution['references']['family']==packet['family']
    assert packet['binding']['partial'] and packet['binding']['criterion_count']==100
    assert packet['recovery']['binding']['arguments']['snapshot_ref']==snapshot
    assert packet['recovery']['observations']=={'tool':'read_summary_observations','arguments':{'offset':9,'limit':3}}


async def test_first_sent_attempt_then_local_cap_refusal_remains_unknown(tmp_path,monkeypatch):
    from test_model_recovery import active_model,calls
    from test_transport_observation import use_mock,close
    from report_agent.request_budget import request_reservation_observer,RequestBudgetExceeded
    store,model=await active_model(tmp_path,monkeypatch)
    sent=[];reserved=[]
    def transport(request):
        sent.append(request)
        raise httpx.ReadTimeout('Synthetic first request already entered transport.',request=request)
    def reserve():
        if reserved:raise RequestBudgetExceeded('RECOVERY_OBSERVATION_HTTP_LIMIT')
        reserved.append(True)
    await use_mock(model,transport)
    ledger=TokenBudget(tmp_path/'sent-then-local.db',200,{'deepseek-v4.1-flash':40})
    try:
        with token_budget(ledger),request_budget(RequestBudget(3)),request_reservation_observer(reserve):
            with pytest.raises(RequestBudgetExceeded):await model.ainvoke('Sent fixture then refused extra.')
        receipt,=calls(store)
        assert len(sent)==1 and receipt['extra_calls']==1
        assert receipt['state']=='unknown' and 'admission_proof' not in receipt
        assert receipt['attempt_history'][0]['state']=='unknown'
        assert ledger.snapshot()['attempt_states']['reserved']==1
    finally:await close(model)


def test_new_source_id_with_same_file_bytes_is_not_a_recovery_condition(ws):
    from report_agent.catalog import Catalog
    from report_agent.source_use import configure_source_use
    from report_agent.execution_progress import _condition
    cs,owner,refs,snapshot,all_refs=seed(ws)
    first=Catalog(ws.store).import_file('first-copy.txt',b'Identical supplied fixture file.')['source']['id']
    duplicate=Catalog(ws.store).import_file('second-copy.txt',b'Identical supplied fixture file.')['source']['id']
    configure_source_use(ws.store,['s',first,duplicate],'Direct fixture authorization of these exact files')
    original=cs.capture_sources(owner,'first-file',[first])['result']['source_refs'][0]
    alias=cs.capture_sources(owner,'second-file',[duplicate])['result']['source_refs'][0]
    containing=cs.freeze(owner,'with-first-file',refs['root'],[*all_refs,original])['result']['snapshot_ref']
    episode={'scope':{**owner.__dict__,'actor_id':owner.id},'binding':{'snapshot_ref':containing,'root_ref':refs['root']}}
    with pytest.raises(ActionRejected,match='PROGRESS_RECOVERY_UNCHANGED_MATERIAL'):
        _condition(ws,episode,{'kind':'authorized_material','ref':alias,'target_ref':refs['root']})


async def test_post_response_optional_policy_read_failure_is_diagnostic_only(ws,monkeypatch):
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage,SystemMessage
    from report_agent.prompt_provenance import AgentPromptBoundary
    from report_agent.prompt_sources import load_prompt
    from report_agent.store import Store
    real_get=Store.get;returned=[]
    def read(self,key,default=None):
        if self is ws.store and key=='manifest' and returned:raise OSError('Synthetic optional diagnostic read failed.')
        return real_get(self,key,default)
    monkeypatch.setattr(Store,'get',read)
    response=SimpleNamespace(result=[AIMessage('Actual fixture completed response.')])
    async def handler(request):returned.append(True);return response
    request=SimpleNamespace(system_message=SystemMessage(load_prompt('experience-optimizer')),messages=[],tools=[])
    assert await AgentPromptBoundary(ws,'experience_optimizer',source='experience-optimizer').awrap_model_call(request,handler) is response
    assert returned==[True]


async def test_foreign_observation_rejection_does_not_crash_repetition_diagnostics(ws,monkeypatch):
    async with sdk_case(ws,monkeypatch,unbound=True) as case:
        saved=ws.store.get('tool_observation:'+case['raw_ref']);saved['owner']='another-private-task'
        ws.store.set('tool_observation:'+case['raw_ref'],saved)
        case['controls']['max_reads']=4
        await deep_runtime.run_report(ws,case['factory'])
        assert ws.store.get('report_status')!='failed' and case['steps']['coordinator']==5
        assert any(e['kind']=='execution_progress_observation_gap' for e in ws.store.events())


@pytest.mark.parametrize('delivered',[True,False])
def test_recovery_condition_receipt_requires_exact_final_wire(ws,delivered):
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from report_agent.prompt_provenance import prompt_call,bind_wire_payload,observe_prompt_request,progress_response_fact
    text='Host changed condition exact fixture reference.'
    contribution={'source':'execution_progress/recovery_condition','text':text,
        'references':{'episode_id':'fixture','condition_digest':'c'*64}}
    payload={'model':'fixture','messages':[{'role':'system','content':text if delivered else 'Other unchanged role.'}]}
    with prompt_call(ws.store,'coordinator',status='exact',offered=payload) as call:
        bind_wire_payload(payload)
        observe_prompt_request(httpx.Request('POST','https://fixture.invalid/v1/chat/completions',json=payload),ws.store,'coordinator')
        progress_response_fact(ws.store,call,SimpleNamespace(result=[AIMessage('Fixture response.',id='response',response_metadata={'finish_reason':'stop'})]),[contribution])
    fact=ws.store.get(next(e['data']['capture_key'] for e in reversed(ws.store.events()) if e['kind']=='prompt_response_fact'))
    assert len(fact['recovery_conditions'])==(1 if delivered else 0)
    if delivered:assert fact['recovery_conditions'][0]['condition_digest']=='c'*64


def test_actor_received_material_outside_snapshot_is_not_new_condition(ws):
    from report_agent.catalog import Catalog
    from report_agent.source_use import configure_source_use
    from report_agent.execution_progress import _condition
    from report_agent.source_materials import issue,block_material
    from report_agent.summary_recovery import capture
    from langchain_core.messages import AIMessage
    native(ws);manifest=ws.store.manifest;manifest['context_policy']='stateful-tools-v2';ws.store.set('manifest',manifest)
    cs,owner,refs,snapshot,_=seed(ws)
    extra=Catalog(ws.store).import_file('already-received.txt',b'Authorized material already returned to this task.')['source']['id']
    configure_source_use(ws.store,['s',extra],'Direct fixture authority')
    page=Catalog(ws.store).read(extra,0,10);text=json.dumps(page,ensure_ascii=False)
    receipt=issue(ws,owner,'read_source_page',text,block_material(page))
    ai=AIMessage('',id='actual-source-decision',tool_calls=[{'id':'source-call','name':'read_source_page','args':{'source_id':extra,'offset':0,'limit':10}}],response_metadata={'finish_reason':'tool_calls'})
    message=ToolMessage(text,name='read_source_page',tool_call_id='source-call',artifact={'source_material':receipt})
    capture(ws,'coordinator',[ai,message])
    alias=cs.capture_sources(owner,'received-source-alias',[extra])['result']['source_refs'][0]
    episode={'scope':{**owner.__dict__,'actor_id':owner.id},'binding':{'snapshot_ref':snapshot,'root_ref':refs['root']}}
    with pytest.raises(ActionRejected,match='PROGRESS_RECOVERY_UNCHANGED_MATERIAL'):
        _condition(ws,episode,{'kind':'authorized_material','ref':alias,'target_ref':refs['root']})


@pytest.mark.parametrize('boundary',['known-zero-send','missing-proof','already-sent'])
async def test_root_model_limit_resume_requires_persisted_whole_logical_zero_send(ws,monkeypatch,tmp_path,boundary):
    from types import SimpleNamespace
    from report_agent.execution_progress import authorize_recovery,EPISODES
    from report_agent.model_recovery import activate_recovery
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate,release
    ledger=TokenBudget(tmp_path/'exact-root-resume.db',60000,{'glm-5.3':1000})
    old_id=ledger.reserve('glm-5.3')
    with ledger.connect() as db:old=db.execute('SELECT * FROM attempts WHERE id=?',(old_id,)).fetchone()
    with token_budget(ledger):
        async with sdk_case(ws,monkeypatch) as case:
            activate_recovery(ws.store,authorization='Direct synthetic fixture recovery authority')
            await deep_runtime.run_report(ws,case['factory']);episode,=episodes(ws)
            configure_report(ws.store,'exact-boundary')
            first=candidate(ws,id='first-boundary',topic='first-boundary',text='First changed fixture condition.')
            release(ws,first)
            if boundary=='already-sent':case['controls']['timeout_at']=5
            with request_budget(RequestBudget(10)):
                authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':first['ref']},
                    authorization_basis='Direct fixture host authority',reason='First bounded observation.',max_http_attempts=1)
                await deep_runtime.run_report(ws,case['factory'])
            limited=ws.store.get(EPISODES+episode['episode_id'])
            assert limited['state']=='observation_limit'
            if boundary!='already-sent':
                assert limited['resume_boundary']['kind']=='root_model_zero_send'
                assert limited['resume_boundary']['node']=='model'
            else:assert not limited.get('resume_boundary')
            if boundary=='missing-proof':
                limited['resume_boundary']=None;ws.store.set(EPISODES+episode['episode_id'],limited)
            second=candidate(ws,id='second-boundary',topic='second-boundary',text='Second independently effective fixture condition.')
            release(ws,second);case['controls']['stop']=True
            with request_budget(RequestBudget(10)):
                authorize_recovery(ws,episode['episode_id'],{'kind':'effective_instruction','ref':second['ref']},
                    authorization_basis='Direct fixture host authority',reason='Resume only exact safe model boundary.',max_http_attempts=2)
                from report_agent.execution_progress import limited_model_resume_keys
                assert limited_model_resume_keys(ws,SimpleNamespace(next=('tools',))) is None
                before=len(case['wires']);await deep_runtime.run_report(ws,case['factory'])
                assert len(case['wires'])-before==(1 if boundary=='known-zero-send' else 0)
            if boundary=='known-zero-send':
                assert ws.store.get(EPISODES+episode['episode_id'])['state']=='observation_completed'
            else:assert ws.store.get('report_status')=='needs_attention'
    with ledger.connect() as db:assert db.execute('SELECT * FROM attempts WHERE id=?',(old_id,)).fetchone()==old
