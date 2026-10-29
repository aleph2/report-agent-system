import hashlib,json
import httpx,pytest
from langchain_core.messages import HumanMessage,ToolMessage
from report_agent.deep_models import configured_model
from report_agent.deep_runtime import run_report,project_agent
from report_agent.model_recovery import activate_recovery,recovery_owner
from report_agent.request_budget import RequestBudgetExceeded,request_reservation_observer,enforce_host_admission
from report_agent.store import Store
from report_agent.token_budget import TokenBudget,token_budget
from report_agent.workspace import Workspace
from test_deep_runtime import Driver
from test_transport_observation import use_mock,close,body
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared,review_call

@pytest.mark.asyncio
async def test_v4_reviewer_500_root_new_facts_same_task_and_old_requests_fenced(case,tmp_path,monkeypatch):
    cs,_,criteria,_=prepared(case);store=cs.store
    from report_agent.source_use import configure_source_use
    authority=configure_source_use(store,['s'],'Synthetic explicit permission')
    store.set('manifest',{**store.manifest,'context_policy':'stateful-tools-v2','history_projection_profile':'exact-history-v1',
        'review_plan_contract':'optional-v1','context_projection':'review-materials-v2','tool_discovery_profile':'agent-search-v2',
        'content_input_profile':'relation-endpoints-v2','report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1','review_submission_contract':'task-scope-selectors-v1',
        'execution_progress_policy':{'version':1,'window':64,'repeats':3,'after_notice':2}})
    activate_recovery(store,authorization='synthetic only',version=2)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','0');monkeypatch.setenv('REPORT_REASONING_EFFORT','high')
    for role in ('COORDINATOR','REVIEWER','TEXT_TOOL'):
        for suffix,value in [('MODEL','deepseek-v4.1-flash'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','fake')]:monkeypatch.setenv('REPORT_'+role+'_'+suffix,value)
    co=configured_model(store,'coordinator');reviewer=configured_model(store,'reviewer');text=configured_model(store,'text_tool')
    for m in (co,reviewer,text):m.root_async_client.max_retries=0;m.root_client.max_retries=0
    ledger=TokenBudget(tmp_path/'synthetic-budget.db',50000000,{'deepseek-v4.1-flash':2000000,'seed':15000000})
    prior_used=ledger.reserve('seed');ledger.settle(prior_used,{'total_tokens':11111748})
    prior_held=ledger.reserve('deepseek-v4.1-flash')
    baseline=ledger.snapshot()
    current_used=ledger.reserve('seed');ledger.settle(current_used,{'total_tokens':10105865})
    old_text=[]
    def text_timeout(request):old_text.append(request.content);raise httpx.ReadTimeout('synthetic unknown',request=request)
    await use_mock(text,text_timeout)
    writer=case[2]
    co_sent=[];old_co=[];reviewer_sent=[]
    args=review_call(criteria)['args']
    reviewer_resume_task={}
    def completion(request):
        payload=json.loads(request.content);co_sent.append(payload)
        result=body()
        if len(co_sent)==1:
            result['choices'][0]['finish_reason']='tool_calls';result['choices'][0]['message']={'role':'assistant','content':'','tool_calls':[{'id':'review-first','type':'function','function':{'name':'task','arguments':json.dumps(args)}}]}
        elif len(co_sent)==2:
            result['choices'][0]['finish_reason']='tool_calls';result['choices'][0]['message']={'role':'assistant','content':'','tool_calls':[{'id':'review-next','type':'function','function':{'name':'task','arguments':json.dumps({'subagent_type':'reviewer','description':'Continue the prior scoped review.','resume_content_task_id':reviewer_resume_task['id']})}}]}
        return httpx.Response(200,json=result)
    await use_mock(co,completion)
    def review_response(request):
        reviewer_sent.append(request.content)
        return httpx.Response(500,json={'error':{'message':'synthetic unavailable'}}) if len(reviewer_sent)==1 else httpx.Response(200,json=body())
    await use_mock(reviewer,review_response)
    async def old_co_fence(request):
        if len(co_sent)==1:
            old_co.append(request.content);raise RequestBudgetExceeded('HOST_RESUME_PROOF_REQUIRED')
    co.http_async_client.event_hooks['request'].insert(0,old_co_fence)
    driver=Driver(writer=[],layout=[])
    factory=lambda role: co if role=='coordinator' else reviewer if role=='reviewer' else text if role=='text_tool' else driver(role)
    from report_agent.deep_runtime import build_agent
    from langgraph.checkpoint.memory import InMemorySaver
    build_agent(Workspace(store),factory,InMemorySaver())
    try:
        with token_budget(ledger),recovery_owner(store,writer,'synthetic-text-operation'),pytest.raises(Exception):await text.ainvoke('synthetic old text')
        with token_budget(ledger):failed=await run_report(Workspace(store),model_factory=factory)
        assert failed['last_error'] is not None and len(old_text)==1 and len(co_sent)==1 and len(old_co)==1 and len(reviewer_sent)==1
        snapshot=ledger.snapshot();assert snapshot['reserved_or_unknown_upper_bounds']-baseline['reserved_or_unknown_upper_bounds']==4000000
        assert snapshot['recorded_tokens']-baseline['recorded_tokens']==10105875
        assert 36888252-((snapshot['recorded_tokens']-baseline['recorded_tokens'])+(snapshot['reserved_or_unknown_upper_bounds']-baseline['reserved_or_unknown_upper_bounds']))==22782377
        with store.read_only() as db:
            old_records={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'model_recovery_call:%'") if json.loads(v).get('state') in ('unknown','response_received','local_admission_blocked')}
        assert any(v.get('role')=='text_tool' and v.get('state')=='unknown' for v in old_records.values())
        assert any(v.get('role')=='coordinator' and v.get('state')=='unknown' for v in old_records.values())
        assert any(v.get('role')=='reviewer' and v.get('state')=='response_received' and v.get('raw',{}).get('status')==500 for v in old_records.values())
        tasks=[x for x in cs.list_objects('DelegatedTask') if x['payload']['role']=='reviewer'];assert len(tasks)==1
        task=tasks[0];reviewer_resume_task['id']=task['ref']['id']; task_copy=cs.read(task['ref']); snapshot_ref=task['payload']['review_snapshot_ref']; snapshot_copy=cs.read(snapshot_ref)
        task_binding=store.get('source_use_task_binding:'+task['ref']['id']);assert task_binding==authority
        before_objects=cs.list_objects();co.http_async_client.event_hooks['request'].remove(old_co_fence)
        import importlib.util
        spec=importlib.util.spec_from_file_location('resume_host_guards',str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'resume_host_guards.py'));assert hashlib.sha256(__import__('pathlib').Path(spec.origin).read_bytes()).hexdigest() == '43516f41f8ce6ed106b6eed273fae1616f4fbae256b6302ddda070a70b241d21'
        guards=importlib.util.module_from_spec(spec);spec.loader.exec_module(guards)
        async def block_old(request):
            for prior in (old_text[0],old_co[0],reviewer_sent[0]):guards.guard_unknown_wire(request,hashlib.sha256(prior).hexdigest(),guards.canonical_wire_sha256(prior))
        co.http_async_client.event_hooks['request'].insert(0,block_old);reviewer.http_async_client.event_hooks['request'].insert(0,block_old);text.http_async_client.event_hooks['request'].insert(0,block_old)
        admissions=[]
        def admission():
            current=ledger.snapshot();admissions.append((current['recorded_tokens'],current['reserved_or_unknown_upper_bounds']))
            enforce_host_admission(used_plus_held=(current['recorded_tokens']-baseline['recorded_tokens'])+(current['reserved_or_unknown_upper_bounds']-baseline['reserved_or_unknown_upper_bounds']),limit=36888252,unknown=False,failed=False)
        async with project_agent(Workspace(Store(store.root)),model_factory=factory) as agent:
            config={'configurable':{'thread_id':'report'}};before=await agent.aget_state(config)
            assert before.next==('model',)
            assert any(isinstance(m,ToolMessage) and 'DELEGATED_EXECUTION_FAILED' in str(m.content) and 'MODEL_SERVICE_UNAVAILABLE' in str(m.content) for m in before.values['messages'])
            message=HumanMessage(id='synthetic-recovery',name='host_recovery_observation',content='[系统恢复通知：由宿主生成，并非用户指令]'+json.dumps({'task_id':task['ref']['id'],'reviewer_response':'http_500_usage_unknown','native_task':'failed','permissions':'unchanged'}))
            changed=await agent.aupdate_state(before.config,{'messages':[message]},as_node='WorkingSummary.before_model')
            after=await agent.aget_state(changed);assert after.next==('model',)
            with token_budget(ledger),request_reservation_observer(admission):await agent.ainvoke(None,changed)
        assert len(co_sent)==3 and len(reviewer_sent)==2 and len(old_text)==1 and len(old_co)==1
        before_fences=ledger.snapshot()
        for client,payload in ((text.http_async_client,old_text[0]),(co.http_async_client,old_co[0]),(reviewer.http_async_client,reviewer_sent[0])):
            with token_budget(ledger),request_reservation_observer(admission),pytest.raises(RequestBudgetExceeded,match='HOST_PRIOR_UNKNOWN_WIRE_FENCED'):
                await client.post('https://offline.invalid/v1/chat/completions',content=payload)
        assert len(co_sent)==3 and len(reviewer_sent)==2 and len(old_text)==1 and ledger.snapshot()==before_fences
        assert any('系统恢复通知' in json.dumps(msg,ensure_ascii=False) for msg in co_sent[1]['messages'])
        assert cs.read(task['ref'])==task_copy and cs.read(snapshot_ref)==snapshot_copy
        assert store.get('source_use_authority_binding')==authority and store.get('source_use_task_binding:'+task['ref']['id'])==task_binding
        assert all(cs.read(item['ref'])==item for item in before_objects)
        assert len([x for x in cs.list_objects('DelegatedTask') if x['payload']['role']=='reviewer'])==1
        assert {k:store.get(k) for k in old_records}==old_records
        assert ledger.snapshot()['reserved_or_unknown_upper_bounds']-baseline['reserved_or_unknown_upper_bounds']==4000000 and admissions
        with ledger.connect() as db:
            assert db.execute('select state,reserved from attempts where id=?',(prior_held,)).fetchone()==('reserved',2000000)
            assert db.execute('select state,used from attempts where id=?',(prior_used,)).fetchone()==('settled',11111748)
        assert not cs.list_objects('ReviewRecord')
    finally:
        for model in (co,reviewer,text):await close(model)
