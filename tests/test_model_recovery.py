import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import openai
import pytest

from report_agent.model_recovery import (activate_recovery, canonical_input, recover_model_call,
    RecoveryBlocked, POLICY_KEY, STATE_KEY, PREFIX, _claim, transient)
from report_agent.store import Store, digest
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.errors import ModelRequestDeadlineExceeded
from test_transport_observation import setup_model, use_mock, close, body
from test_task_supervision import ws


def calls(store):
    with store.connect() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT value FROM state WHERE key LIKE ?', (PREFIX+'%',))]


async def active_model(tmp_path, monkeypatch):
    store, model = setup_model(tmp_path, monkeypatch, role='coordinator')
    # Existing setup deliberately defaults SDK to five; active recovery refuses that.
    model.root_async_client.max_retries = 0
    activate_recovery(store, authorization='synthetic-direct-user-policy')
    return store, model


async def test_actual_sdk_timeout_then_success_keeps_first_hold_and_reuses_private_raw(tmp_path, monkeypatch):
    store, model = await active_model(tmp_path, monkeypatch)
    seen = []
    def respond(request):
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ReadTimeout('synthetic', request=request)
        return httpx.Response(200, json=body())
    await use_mock(model, respond)
    budget = TokenBudget(tmp_path/'budget.db', 200, {'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            assert (await model.ainvoke('synthetic input')).content == 'unchanged result'
            # A reopened Store and newly constructed result preserve AIMessage semantics.
            assert (await model.ainvoke('synthetic input')).content == 'unchanged result'
        assert len(seen) == 2
        snap = budget.snapshot()
        assert snap['attempt_states'] == {'reserved':1, 'settled':1}
        assert snap['recorded_tokens'] == 10
        receipt = calls(store)[0]
        assert receipt['extra_calls'] == 1 and receipt['state'] == 'returned'
        assert receipt['attempt_history'][0]['state'] == 'unknown'
        assert store.get(STATE_KEY)['extra_token_bounds'] == 40
        assert 'body_base64' in receipt['raw']
        assert 'body_base64' not in json.dumps(store.events())
    finally:
        await close(model)


async def test_completed_body_timeout_before_sdk_conversion_reparsed_without_new_http(tmp_path, monkeypatch):
    from report_agent.deep_models import GLMChatOpenAI
    store, model = await active_model(tmp_path, monkeypatch)
    original, parse_count, seen = GLMChatOpenAI._create_chat_result, [], []
    def parse(self, *args, **kwargs):
        parse_count.append(1)
        if len(parse_count) == 1:
            raise ModelRequestDeadlineExceeded(600)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(GLMChatOpenAI, '_create_chat_result', parse)
    def respond(request):
        seen.append(request)
        result=body()
        result['choices'][0]['message']['tool_calls']=[{'id':'native-call', 'type':'function',
            'function':{'name':'add','arguments':'{"x":1}'}}]
        return httpx.Response(200,json=result)
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'budget.db',100,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            result=await model.ainvoke('synthetic')
        assert result.tool_calls[0]['id']=='native-call'
        assert len(seen)==1 and len(parse_count)==2
        assert budget.snapshot()['attempt_states']=={'settled':1}
        assert store.get(STATE_KEY)['extra_calls']==0
    finally:
        await close(model)


@pytest.mark.parametrize('mode',['empty','length','invalid_json','bad_utf8','429','500'])
async def test_received_invalid_and_http_status_never_recomputed(tmp_path,monkeypatch,mode):
    store, model=await active_model(tmp_path,monkeypatch)
    seen=[]
    def respond(request):
        seen.append(request)
        if mode in {'429','500'}:
            return httpx.Response(int(mode),json={'error':{'message':'synthetic'}})
        if mode=='invalid_json':return httpx.Response(200,content=b'{invalid')
        if mode=='bad_utf8':return httpx.Response(200,content=b'\xff')
        result=body()
        result['choices'][0]['message']['content']=''
        result['choices'][0]['finish_reason']='length' if mode=='length' else 'stop'
        return httpx.Response(200,json=result)
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'budget.db',100,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            try:await model.ainvoke('synthetic')
            except Exception:pass
        assert len(seen)==1
        assert store.get(STATE_KEY)['extra_calls']==0
    finally:await close(model)


async def test_case_limits_and_restart_fence_without_custom_service_scheduler(tmp_path,monkeypatch):
    store=Store(tmp_path/'case')
    activate_recovery(store,authorization='synthetic')
    budget=TokenBudget(tmp_path/'budget.db',1000,{'m':40})
    seen=[]
    async def fail():
        seen.append(1)
        raise ModelRequestDeadlineExceeded(600)
    async def run(number,role='coordinator',service='first'):
        return await recover_model_call(store=Store(store.root),role=role,profile={'model':'m','endpoint':service},owner={'actor':role},
            payload={'model':'m','messages':[{'role':'user','content':str(number)}]},invoke=fail,parse_raw=lambda x:x)
    with token_budget(budget):
        for i in range(2):
            with pytest.raises(ModelRequestDeadlineExceeded):await run(i)
        assert len(seen)==4
        with pytest.raises(RecoveryBlocked,match='UNRESOLVED'):await run(0)
        # Platform bounded retries share persistent case permission across roles
        # and services, with no second custom cooldown scheduler.
        for i in range(2):
            with pytest.raises(ModelRequestDeadlineExceeded):await run(i+3,'reviewer','first')
        with pytest.raises(ModelRequestDeadlineExceeded):await run(9,'writer','third')
        assert len(seen)==9
        assert Store(store.root).get(STATE_KEY)['extra_calls']==4


def test_atomic_primary_claim_one_owner(tmp_path):
    store=Store(tmp_path)
    policy=activate_recovery(store,authorization='synthetic')
    def claim(_):
        try:return _claim(Store(tmp_path),PREFIX+'same','service',policy,'full')[1]
        except RecoveryBlocked:return 'blocked'
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(claim,range(6)))
    assert results.count(True)==1 and results.count('blocked')==5


def test_canonical_only_known_system_resource_fields_and_preserves_tools():
    from report_agent.model_recovery import _TASK_PREFIX
    original={'messages':[{'role':'system','content':[{'type':'text','text':_TASK_PREFIX+json.dumps({
        'origin':'server_bound_application_state','execution_resources':{'remaining':3},'task':'original'})}]},
        {'role':'user','content':'execution_resources must stay','id':'ephemeral'},
        {'role':'tool','tool_call_id':'keep-id','content':'keep exact'}], 'tools':[{'function':{'name':'keep'}}]}
    result=canonical_input(original)
    assert 'execution_resources' not in result['messages'][0]['content'][0]['text']
    assert result['messages'][1]['content']==original['messages'][1]['content']
    assert result['messages'][2]['tool_call_id']=='keep-id'
    assert result['tools']==original['tools']
    assert 'execution_resources' in original['messages'][0]['content'][0]['text']


async def test_external_cancel_and_disabled_policy_no_extra_attempts(tmp_path):
    store=Store(tmp_path)
    seen=[]
    async def cancel():
        seen.append(1)
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await recover_model_call(store=store,role='coordinator',profile={},payload={},invoke=cancel,parse_raw=lambda x:x)
    assert store.get(STATE_KEY) is None
    activate_recovery(store,authorization='synthetic')
    with pytest.raises(asyncio.CancelledError):
        await recover_model_call(store=store,role='coordinator',profile={},payload={},invoke=cancel,parse_raw=lambda x:x)
    assert len(seen)==2 and store.get(STATE_KEY)['extra_calls']==0


def test_wrapped_capacity_budget_and_status_errors_not_transient():
    from report_agent.request_budget import RequestBudgetExceeded
    for cause in [RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED'),RecoveryBlocked('LOCAL')]:
        outer=openai.APIConnectionError(request=httpx.Request('POST','https://offline.invalid'))
        outer.__cause__=cause
        assert not transient(outer)


async def test_historical_identity_fence_blocks_before_http_and_activation_never_resets(tmp_path):
    store=Store(tmp_path)
    payload={'model':'m','messages':[{'role':'user','content':'original'}]}
    profile={'model':'m'}
    service=digest({'model':profile.get('model'),'endpoint':''})
    identity=digest({'service':service,'role':'coordinator','owner':{'case_root':str(store.root),'actor':'coordinator'},'profile':profile,'input':canonical_input(payload)})
    activate_recovery(store,authorization='synthetic',blocked_calls=[identity])
    async def must_not_run():raise AssertionError('no HTTP allowed')
    with pytest.raises(RecoveryBlocked,match='HISTORICAL'):
        await recover_model_call(store=store,role='coordinator',profile=profile,payload=payload,
            invoke=must_not_run,parse_raw=lambda x:x)
    with pytest.raises(RecoveryBlocked,match='ALREADY_BOUND'):
        activate_recovery(Store(tmp_path),authorization='new ID cannot reset policy')
    assert store.get(STATE_KEY)['extra_calls']==0


async def test_active_policy_refuses_stacked_sdk_retries_before_dispatch(tmp_path,monkeypatch):
    store,model=setup_model(tmp_path,monkeypatch)
    activate_recovery(store,authorization='synthetic')
    try:
        with pytest.raises(RecoveryBlocked,match='SINGLE_RETRY_OWNER'):
            await model.ainvoke('synthetic')
        assert calls(store)==[]
    finally:await close(model)


async def test_vision_real_sdk_uses_same_recovery_and_preserves_unknown_domain_fence(tmp_path,monkeypatch):
    from report_agent.deep_models import configured_vision_client
    from report_agent.vision import _observe
    from report_agent.errors import ActionRejected
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    for suffix,value in [('MODEL','deepseek-v4.1-flash-1017'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','synthetic')]:
        monkeypatch.setenv('REPORT_VISION_'+suffix,value)
    store=Store(tmp_path/'case')
    client=configured_vision_client()
    seen=[]
    def respond(request):
        seen.append(request)
        if len(seen)<2:raise httpx.ReadTimeout('synthetic',request=request)
        return httpx.Response(200,json=body())
    client._client._transport=httpx.MockTransport(respond)
    client._client._mounts={}
    activate_recovery(store,authorization='synthetic')
    budget=TokenBudget(tmp_path/'budget.db',200,{'deepseek-v4.1-flash-1017':40})
    source={'source_id':'synthetic','page':1,'sha256':'a'*64}
    try:
        with token_budget(budget):
            from report_agent.content_store import Actor
            result=await _observe(store,b'synthetic image',source,'read',client,Actor('synthetic-writer','writer','synthetic-task'))
        assert result['status']=='observed' and len(seen)==2
        assert budget.snapshot()['attempt_states']=={'reserved':1,'settled':1}
        assert 'data:image/' not in json.dumps(store.events())
        # A legacy domain reservation still wins before the new wrapper.
        from report_agent.vision_admission import reserve_vision
        reserve_vision(store,'legacy','legacy-material',None)
        with pytest.raises(ActionRejected):reserve_vision(store,'legacy','legacy-material',None)
    finally:await client.close()


async def test_no_trusted_owner_does_not_get_recovery_or_cache(tmp_path):
    store=Store(tmp_path)
    activate_recovery(store,authorization='synthetic')
    seen=[]
    async def fail():
        seen.append(1)
        raise ModelRequestDeadlineExceeded(600)
    with pytest.raises(ModelRequestDeadlineExceeded):
        await recover_model_call(store=store,role='text_tool',profile={'model':'m'},payload={},
            invoke=fail,parse_raw=lambda x:x)
    assert len(seen)==1 and calls(store)==[]


async def test_received_body_keeps_active_owner_until_parser_finishes(tmp_path,monkeypatch):
    from report_agent.model_recovery import capture_response
    store=Store(tmp_path)
    activate_recovery(store,authorization='synthetic')
    entered,release=asyncio.Event(),asyncio.Event()
    payload={'model':'m','messages':[]}
    async def invoke():
        capture_response(httpx.Response(200,json={'synthetic':True},request=httpx.Request('POST','https://offline.invalid')))
        entered.set()
        await release.wait()
        return 'original owner'
    async def run():
        return await recover_model_call(store=store,role='coordinator',profile={'model':'m'},
            payload=payload,invoke=invoke,parse_raw=lambda x:x)
    first=asyncio.create_task(run())
    await entered.wait()
    with pytest.raises(RecoveryBlocked,match='UNRESOLVED'):await run()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):await first
    assert calls(store)[0]['state']=='cancelled'
    assert not calls(store)[0]['active']
    assert await run()=={'synthetic':True}


def test_private_raw_not_in_agent_decision_state_status_or_workspace_results(ws):
    from report_agent.decision_state import state_tool
    marker='PRIVATE_SYNTHETIC_REASONING_97e8'
    ws.store.set(PREFIX+'private',{'raw':{'body_base64':marker}})
    packets=[state_tool(ws,'coordinator')([]),ws.status(),ws.results()]
    assert marker not in json.dumps(packets,default=str)
    assert PREFIX+'private' not in json.dumps(packets,default=str)


async def test_cached_result_marks_historical_usage_not_new_provider_usage(tmp_path,monkeypatch):
    store,model=await active_model(tmp_path,monkeypatch)
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'budget.db',100,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            first=await model.ainvoke('synthetic')
            second=await model.ainvoke('synthetic')
        assert first.usage_metadata['total_tokens']==10
        assert second.usage_metadata is None
        assert second.additional_kwargs['model_recovery_reused'] is True
        assert second.additional_kwargs['historical_usage_metadata']['total_tokens']==10
        assert second.response_metadata['model_recovery_reused'] is True
        assert len(seen)==1 and budget.snapshot()['recorded_tokens']==10
    finally:await close(model)


async def test_legacy_evidence_owner_none_does_not_activate_recovery(tmp_path):
    from report_agent.model_recovery import recovery_owner
    store=Store(tmp_path)
    activate_recovery(store,authorization='synthetic')
    seen=[]
    async def fail():
        seen.append(1)
        raise ModelRequestDeadlineExceeded(600)
    with recovery_owner(store,None,'server-derived-raw-operation'):
        with pytest.raises(ModelRequestDeadlineExceeded):
            await recover_model_call(store=store,role='text_tool',profile={'model':'m'},payload={},
                invoke=fail,parse_raw=lambda x:x)
    assert len(seen)==1 and calls(store)==[]


async def test_legacy_vision_without_actor_has_one_attempt(tmp_path,monkeypatch):
    from report_agent.vision import _observe
    from test_vision import VisionModel
    store=Store(tmp_path)
    activate_recovery(store,authorization='synthetic')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    client=VisionModel(error=httpx.ReadTimeout('synthetic'))
    client.max_retries=0
    result=await _observe(store,b'synthetic',{'source_id':'s'},'read',client)
    assert result['status']=='failed' and len(client.calls)==1 and calls(store)==[]


async def test_deployed_recovery_does_not_reopen_legacy_unknown_with_new_caller_id(tmp_path,monkeypatch,ws):
    from report_agent.evidence_analysis import analyze_evidence_packet
    from report_agent.content_store import Actor
    from report_agent.errors import ActionRejected
    store,model=setup_model(tmp_path,monkeypatch)
    model.root_async_client.max_retries=0
    seen=[]
    def fail(request):
        seen.append(request)
        raise httpx.ReadTimeout('synthetic',request=request)
    await use_mock(model,fail)
    owner=Actor('writer','writer','saved-task')
    try:
        with pytest.raises(ActionRejected,match='OUTCOME_UNRESOLVED'):
            await analyze_evidence_packet(ws,model,{'evidence':'same'},'Read','contract',
                reserve_attempt=True,owner=owner,caller_operation_id='old')
        activate_recovery(ws.store,authorization='synthetic')
        # Actual model still uses the same workspace Store as the domain call.
        model.http_async_client.observation_store=ws.store
        with pytest.raises(ActionRejected,match='PREVIOUS_ATTEMPT_UNRESOLVED'):
            await analyze_evidence_packet(ws,model,{'evidence':'same'},'Read','contract',
                reserve_attempt=True,owner=owner,caller_operation_id='new-id')
        assert len(seen)==1 and calls(ws.store)==[]
    finally:await close(model)


async def test_historical_wire_fence_precedes_new_token_reservation(tmp_path,monkeypatch):
    import hashlib
    from report_agent.deep_models import error_data
    store,model=setup_model(tmp_path,monkeypatch,role='coordinator')
    model.root_async_client.max_retries=0
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'budget.db',100,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            await model.ainvoke('same exact wire')
            activate_recovery(store,authorization='synthetic',blocked_wire_hashes=[hashlib.sha256(seen[0].content).hexdigest()])
            before=budget.snapshot()
            with pytest.raises(RecoveryBlocked) as caught:await model.ainvoke('same exact wire')
        assert error_data(caught.value)['message']=='RECOVERY_HISTORICAL_WIRE_FENCED'
        assert len(seen)==1 and budget.snapshot()==before
        assert store.get(STATE_KEY)['extra_calls']==0
    finally:await close(model)


async def test_native_recovery_block_is_needs_attention_without_resume(ws):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    def blocked(messages):raise RecoveryBlocked('RECOVERY_SERVICE_COOLDOWN')
    driver=Driver(coordinator=[blocked])
    result=await run_report(ws,model_factory=driver)
    assert ws.store.get('report_status')=='needs_attention'
    assert ws.store.get('report_error')['failure_kind']=='model_recovery_blocked'
    assert ws.store.get('report_error')['automatic_resume'] is False
    assert len(driver.calls)==1


async def test_inflight_work_shares_case_permission_without_custom_circuit_scheduler(tmp_path):
    store=Store(tmp_path)
    activate_recovery(store,authorization='synthetic')
    budget=TokenBudget(tmp_path/'budget.db',1000,{'m':40})
    entered,release=asyncio.Event(),asyncio.Event()
    seen=[]
    async def run(number,slow=False):
        async def invoke():
            seen.append(number)
            if slow:
                entered.set();await release.wait()
            raise ModelRequestDeadlineExceeded(600)
        return await recover_model_call(store=store,role='coordinator',profile={'model':'m','endpoint':'same'},
            payload={'model':'m','messages':[{'role':'user','content':str(number)}]},invoke=invoke,parse_raw=lambda x:x)
    with token_budget(budget):
        pending=asyncio.create_task(run('inflight',True))
        await entered.wait()
        for n in (1,2):
            with pytest.raises(ModelRequestDeadlineExceeded):await run(n)
        release.set()
        with pytest.raises(ModelRequestDeadlineExceeded):await pending
    assert seen.count('inflight')==2 and store.get(STATE_KEY)['extra_calls']==3


@pytest.mark.parametrize('failure',['db','broken_json','null','invalid_schema'])
async def test_control_read_failure_is_typed_closed_before_sdk_retry_and_reservation(tmp_path,monkeypatch,failure):
    from contextlib import contextmanager
    from report_agent.deep_models import model_async_client
    from report_agent.model_recovery import load_recovery_policy
    store=Store(tmp_path/'case')
    activate_recovery(store,authorization='synthetic')
    monkeypatch.setenv('REPORT_SDK_RETRIES','5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    transport=model_async_client(store,'text_tool')
    await transport._transport.aclose()
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json=body())
    transport._transport=httpx.MockTransport(respond);transport._mounts={}
    if failure!='db':
        with store.connect() as db:
            db.execute('UPDATE state SET value=? WHERE key=?',({'broken_json':'{','null':'null','invalid_schema':'{}'}[failure],POLICY_KEY))
    original=store.connect;reads=[]
    @contextmanager
    def count_read():
        reads.append(1)
        if failure=='db':raise OSError('synthetic inaccessible control DB')
        with original() as db:yield db
    monkeypatch.setattr(store,'connect',count_read)
    budget=TokenBudget(tmp_path/'budget.db',100,{'deepseek-v4.1-flash-1017':40})
    before=budget.snapshot()
    async with openai.AsyncOpenAI(api_key='synthetic',base_url='https://offline.invalid/v1',http_client=transport,max_retries=5) as client:
        monkeypatch.setattr(client,'_calculate_retry_timeout',lambda *a:0)
        sends=[];original_send=client._send_request
        async def counted_send(*args,**kwargs):
            sends.append(1)
            return await original_send(*args,**kwargs)
        monkeypatch.setattr(client,'_send_request',counted_send)
        with token_budget(budget):
            with pytest.raises(RecoveryBlocked,match='POLICY_READ_FAILED') as error:
                await client.chat.completions.create(model='deepseek-v4.1-flash-1017',messages=[{'role':'user','content':'synthetic'}])
    assert not transient(error.value)
    # One policy read plus a best-effort diagnostic flush can both connect.
    # Count actual SDK sends, not shared storage accesses, to prove no retry.
    assert seen==[] and len(sends)==1 and budget.snapshot()==before


async def test_diagnostic_get_fault_does_not_break_active_recovery_control(tmp_path,monkeypatch):
    store,model=await active_model(tmp_path,monkeypatch)
    seen=[]
    def respond(request):
        seen.append(request)
        if len(seen)==1:raise httpx.ReadTimeout('synthetic',request=request)
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    def broken_get(*a,**k):raise OSError('synthetic diagnostic get sink failure')
    monkeypatch.setattr(store,'get',broken_get)
    budget=TokenBudget(tmp_path/'budget.db',200,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):result=await model.ainvoke('synthetic')
        assert result.content=='unchanged result' and len(seen)==2
        assert budget.snapshot()['attempt_states']=={'reserved':1,'settled':1}
    finally:await close(model)
