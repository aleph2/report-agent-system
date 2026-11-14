import asyncio
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
import openai
from report_agent.token_budget import TokenBudget,token_budget,account_response,account_response_sync
from report_agent.request_budget import RequestBudget,RequestBudgetExceeded,request_budget,account_request,account_request_sync


def test_persistent_atomic_reservations_settle_once_and_keep_unknown(tmp_path,monkeypatch):
    b=TokenBudget(tmp_path/'budget.db',100,{'m':40})
    a=b.reserve('m');c=b.reserve('m')
    with pytest.raises(RequestBudgetExceeded):b.reserve('m')
    b.settle(a,{'total_tokens':10,'prompt_tokens_details':{'cached_tokens':8}})
    b.settle(a,{'total_tokens':10})
    b.settle(c,None)
    reopened=TokenBudget(b.path,100,{'m':40})
    assert reopened.snapshot()['recorded_tokens']==10
    assert reopened.snapshot()['reserved_or_unknown_upper_bounds']==40
    assert reopened.snapshot()['remaining_for_new_reservations']==50
    reopened.reserve('m')
    with pytest.raises(RequestBudgetExceeded):reopened.reserve('m')
    with pytest.raises(ValueError,match='CONFLICT'):TokenBudget(b.path,101,{'m':40})

    from hashlib import sha256
    from report_agent.token_budget import CampaignRunBudget
    campaign=TokenBudget(tmp_path/'production.db',200,{'m':40})
    historical=campaign.reserve('m');campaign.settle(historical,None)
    with campaign.connect() as db:
        holds=[list(r) for r in db.execute("SELECT * FROM attempts WHERE state='unknown' ORDER BY id")]
    options=dict(maximum_tokens=40,aggregate_tokens=200,model_bounds={'m':40},
        authority_sha256='a'*64,preserved_holds=holds,guard_sha256=sha256(b'').hexdigest())
    account=CampaignRunBudget(campaign.path,'same-case',**options)
    paid=account.reserve('m');account.settle(paid,{'total_tokens':40})
    assert account.run_snapshot()=={'maximum_tokens':40,'settled':40,'held':0}
    reopened=CampaignRunBudget(campaign.path,'same-case',**options)
    with pytest.raises(RequestBudgetExceeded,match='REPORT_RUN_TOKEN_LIMIT'):reopened.reserve('m')
    with pytest.raises(RequestBudgetExceeded,match='REPORT_RUN_AUTHORITY_CHANGED'):
        CampaignRunBudget(campaign.path,'same-case',**{**options,'maximum_tokens':80})
    with pytest.raises(RequestBudgetExceeded,match='REPORT_RUN_AUTHORITY_CHANGED'):
        CampaignRunBudget(campaign.path,'same-case',**{**options,'authority_sha256':'b'*64})
    smaller=CampaignRunBudget(campaign.path,'stricter',**{**options,'model_bounds':{'m':30}})
    reserved=smaller.reserve('m')
    assert smaller.run_snapshot()['held']==30
    smaller.settle(reserved,{'total_tokens':5})
    with campaign.connect() as db:
        original_authorization=db.execute('SELECT * FROM authorization').fetchall()
        original_rows=db.execute('SELECT * FROM attempts ORDER BY id').fetchall()
    with pytest.raises(ValueError,match='REPORT_MODEL_BOUND_MISMATCH'):
        CampaignRunBudget(campaign.path,'too-large',**{**options,'model_bounds':{'m':41}})
    with campaign.connect() as db:
        assert db.execute('SELECT * FROM authorization').fetchall()==original_authorization
        assert db.execute('SELECT * FROM attempts ORDER BY id').fetchall()==original_rows
    second=CampaignRunBudget(campaign.path,'second',**options)
    unknown=second.reserve('m');second.settle(unknown,None)
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNRESOLVED_ATTEMPT'):
        CampaignRunBudget(campaign.path,'never-retry',**options)
    with campaign.connect() as db:
        assert list(db.execute('SELECT * FROM attempts WHERE id=?',(historical,)).fetchone())==holds[0]



    import asyncio,json,sqlite3
    from contextlib import closing
    from types import SimpleNamespace
    from report_agent import run_authority,deep_runtime
    from report_agent.store import Store,digest
    from report_agent.workspace import Workspace
    from report_agent.request_budget import account_request
    from report_agent.token_budget import account_response
    case=tmp_path/'authorized-case';store=Store(case)
    store.initialize({'goal':'Synthetic production admission','sources':[{'id':'scope','title':'Scope','content':'Synthetic scope','coverage':'complete'}]})
    workspace=Workspace(store)
    env=tmp_path/'services.env'
    text_url='https://text.synthetic.maas.aliyuncs.com/v1'
    vision_url='https://synthetic.maas.aliyuncs.com/v1'
    env.write_text('GLM_NAME=glm-5.3\nGLM_BASE_URL='+text_url+'\nGLM_API_KEY=synthetic\nVISION_NAME=deepseek-v4.1-flash-1017\nVISION_BASE_URL='+vision_url+'\nVISION_API_KEY=synthetic\n')
    hashed=lambda value:sha256(value).hexdigest()
    common=dict(env_sha256=hashed(env.read_bytes()),endpoint_host_suffix='.maas.aliyuncs.com')
    text_proof=dict(common,model='glm-5.3',input_limit=1048576,output_limit=65536,
        basis='documented_model_ceiling_not_measured_request_fit',
        base_url_sha256=hashed(text_url.encode()),request_url_sha256=hashed((text_url+'/chat/completions').encode()),
        sources=['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3'])
    vision_proof=dict(common,model='deepseek-v4.1-flash-1017',input_limit=1000000,output_limit=8202,
        wire_output_limit=8192,image_max_edge=1024,basis='documented_service_ceiling_not_measured_request_fit',
        base_url_sha256=hashed(vision_url.encode()),request_url_sha256=hashed((vision_url+'/chat/completions').encode()),
        sources=['https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash','https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions'])
    ledger=tmp_path/'authorized-ledger.db';TokenBudget(ledger,10000000,{'glm-5.3':1179648})
    scope=tmp_path/'scope.txt';scope.write_text('Synthetic scope')
    criteria=tmp_path/'criteria.json';criteria.write_text(json.dumps({'criteria':{}}))
    authority=dict(case_path=str(case.resolve()),owner_authority_ref='synthetic-owner',
        confirmers={'owner':{'name':'Owner','acting_for':'owner'}},issue_routes={},
        case_manifest_digest=digest(store.manifest),env_sha256=hashed(env.read_bytes()),
        roles={**dict.fromkeys(['coordinator','writer','reviewer','text_tool','layout'],'glm-5.3'),'vision':'deepseek-v4.1-flash-1017'},
        services={'glm-5.3':{'config_prefix':'GLM_','request_bound_proof':text_proof},
                  'deepseek-v4.1-flash-1017':{'config_prefix':'VISION_','request_bound_proof':vision_proof}},
        candidate_commit='a'*40,candidate_tag='synthetic-candidate',
        graph_limits={'root':100000,'assessment':100000},
        inputs=[{'path':str(scope),'sha256':hashed(scope.read_bytes())}],
        criteria={'path':str(criteria),'sha256':hashed(criteria.read_bytes())},
        transport={'sdk_retries':0,'connect_retries':0,'vision_thinking':'disabled'},
        invocations=['planning','completion'],record_dir=str(tmp_path/'records'),run_id='production-flow',
        budget={'ledger':str(ledger),'per_run_tokens':4000000,'aggregate_tokens':10000000,
                'preserved_holds':[],'guard_sha256':hashed(b'')})
    assert run_authority.graph_config('root')=={'recursion_limit':10000}
    assert run_authority.graph_config('assessment')==run_authority.graph_config('root')
    assert run_authority.graph_config('root',authority)=={'recursion_limit':100000}
    assert run_authority.graph_config('assessment',authority)=={'recursion_limit':100000}
    for invalid_limits in (None, {}, {'root':True,'assessment':1}, {'root':1,'assessment':0},
                           {'root':1,'assessment':1,'extra':1}):
        with pytest.raises(ValueError,match='REPORT_GRAPH_LIMITS_REQUIRED'):
            run_authority.graph_config('root',{**authority,'graph_limits':invalid_limits})
    authority_path=tmp_path/'authority.json';authority_path.write_text(json.dumps(authority));pin=hashed(authority_path.read_bytes())
    monkeypatch.setattr(run_authority.subprocess,'check_output',lambda *a,**k:'a'*40+'\n')
    monkeypatch.setattr(run_authority.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    before=ledger.read_bytes()
    with pytest.raises(ValueError,match='REPORT_AUTHORITY_PIN_REQUIRED'):
        run_authority.preflight(workspace,None,None,env,'planning')
    with pytest.raises(ValueError,match='REPORT_AUTHORITY_PIN_MISMATCH'):
        run_authority.preflight(workspace,authority_path,'0'*64,env,'planning')
    dry=asyncio.run(run_authority.run_authorized_report(workspace,authority_path,pin,env,'planning',dry_run=True))
    assert dry['paid_calls']==0 and ledger.read_bytes()==before and not (tmp_path/'records').exists()
    # Configured bounds may be lower on output, but full input cannot be under-reserved.
    for invalid in ({'input_limit':text_proof['input_limit']-1},
                    {'output_limit':text_proof['input_limit']},
                    {'endpoint_host_suffix':'.untrusted.invalid'},
                    {'env_sha256':'0'*64}, {'sources':['http://synthetic.invalid']}):
        with pytest.raises(ValueError,match='REPORT_REQUEST_PROOF_INVALID'):
            run_authority._service_bound({**text_proof,**invalid},env.read_bytes(),text_proof['model'],text_url)
    with pytest.raises(ValueError,match='REPORT_REQUEST_PROOF_INVALID'):
        run_authority._service_bound({**text_proof,'model':'synthetic-unknown'},env.read_bytes(),'synthetic-unknown',text_url)
    assert ledger.read_bytes()==before
    dispatched=[]
    unknown_mode=False
    async def native(workspace,**kwargs):
        def response(request):
            dispatched.append(request)
            return httpx.Response(200,json={} if unknown_mode else {'id':'synthetic','usage':{'total_tokens':11,'prompt_tokens_details':{'cached_tokens':7}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response),event_hooks={'request':[account_request],'response':[account_response]}) as client:
            await client.post(text_url+'/chat/completions',json={'model':'glm-5.3','stream':False,'max_tokens':1,'messages':[{'role':'user','content':'Synthetic'}]})
        return {'execution_status':'needs_human','status':'needs_human','last_error':None}
    monkeypatch.setattr(deep_runtime,'run_report',native)
    asyncio.run(run_authority.run_authorized_report(workspace,authority_path,pin,env,'planning'))
    result=json.loads((tmp_path/'records/planning/result.json').read_bytes())
    assert len(dispatched)==1 and result['stage_tokens']==11 and result['budget']['held']==0
    with pytest.raises(ValueError,match='REPORT_ALREADY_LAUNCHED'):
        asyncio.run(run_authority.run_authorized_report(workspace,authority_path,pin,env,'planning'))
    with pytest.raises(ValueError,match='REPORT_NATIVE_OWNER_REPLY_REQUIRED'):
        run_authority.preflight(workspace,authority_path,pin,env,'completion')
    assert len(dispatched)==1


    unknown_mode=True
    unknown_authority={**authority,'run_id':'production-unknown','invocations':['only'],
                       'record_dir':str(tmp_path/'unknown-records')}
    unknown_path=tmp_path/'unknown-authority.json';unknown_path.write_text(json.dumps(unknown_authority))
    unknown_pin=hashed(unknown_path.read_bytes())
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNKNOWN_OUTCOME_HELD'):
        asyncio.run(run_authority.run_authorized_report(workspace,unknown_path,unknown_pin,env,'only'))
    stopped=json.loads((tmp_path/'unknown-records/only/result.json').read_bytes())
    assert stopped['status']=='unknown_outcome_held' and stopped['budget']['held']==text_proof['input_limit']+text_proof['output_limit']
    assert len(dispatched)==2
    with pytest.raises(ValueError,match='REPORT_ALREADY_LAUNCHED'):
        asyncio.run(run_authority.run_authorized_report(workspace,unknown_path,unknown_pin,env,'only'))
    assert len(dispatched)==2

    # An explicit new invocation reuses the immutable run binding and real saved head.
    from copy import deepcopy
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import StateGraph, START, END
    def failed_step(state):
        raise RuntimeError('synthetic failed atomic step')
    config={'configurable':{'thread_id':'report'}}
    with SqliteSaver.from_conn_string(str(case/'checkpoints.db')) as saver:
        graph=StateGraph(dict)
        graph.add_node('pending',failed_step)
        graph.add_edge(START,'pending');graph.add_edge('pending',END)
        with pytest.raises(RuntimeError,match='failed atomic'):
            graph.compile(checkpointer=saver).invoke({'committed':'retained'},config)
        head=saver.get_tuple(config).config['configurable']['checkpoint_id']
    with campaign.connect() as db:
        assert list(db.execute('SELECT * FROM attempts WHERE id=?',(historical,)).fetchone())==holds[0]
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)) as db:
        preserved=[list(row) for row in db.execute("SELECT * FROM attempts WHERE state IN ('reserved','unknown') ORDER BY id")]
        original_rows=db.execute('SELECT * FROM attempts ORDER BY id').fetchall()
        original_binding=db.execute('SELECT * FROM report_runs WHERE run_id=?',('production-unknown',)).fetchone()
    continuation=deepcopy(unknown_authority)
    continuation.update(owner_authority_ref='synthetic-continuation-owner',invocations=['only','continue-1'])
    continuation['budget']['preserved_holds']=preserved
    continuation['continuations']={'continue-1':{'prior_invocation':'only',
        'prior_authority':{'path':str(unknown_path),'sha256':unknown_pin},'checkpoint_id':head}}
    continuation_path=tmp_path/'continuation-authority.json'
    def check_continuation(value):
        continuation_path.write_text(json.dumps(value))
        continuation_pin=hashed(continuation_path.read_bytes())
        result=run_authority.preflight(workspace,continuation_path,continuation_pin,env,'continue-1')
        return continuation_pin,result
    invalid=deepcopy(continuation)
    invalid['continuations']['continue-1']['prior_authority']['sha256']='0'*64
    with pytest.raises(ValueError,match='REPORT_CONTINUATION_PIN_MISMATCH'):
        check_continuation(invalid)
    invalid=deepcopy(continuation);invalid['budget']['preserved_holds']=[]
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNRESOLVED_ATTEMPT'):
        check_continuation(invalid)
    invalid=deepcopy(continuation);invalid['budget']['preserved_holds']*=2
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNRESOLVED_ATTEMPT'):
        check_continuation(invalid)
    unrelated=TokenBudget(ledger,10000000,{'glm-5.3':1179648})
    unrelated_id=unrelated.reserve('glm-5.3')
    with unrelated.connect() as db:
        unrelated_hold=list(db.execute('SELECT * FROM attempts WHERE id=?',(unrelated_id,)).fetchone())
    invalid=deepcopy(continuation);invalid['budget']['preserved_holds'].append(unrelated_hold)
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNRESOLVED_ATTEMPT'):
        check_continuation(invalid)
    unrelated.settle(unrelated_id,{'total_tokens':0})
    invalid=deepcopy(continuation);invalid['unreviewed_scope']='changed'
    with pytest.raises(ValueError,match='REPORT_CONTINUATION_SCOPE_MISMATCH'):
        check_continuation(invalid)
    invalid=deepcopy(continuation);invalid['budget']['per_run_tokens']+=1
    with pytest.raises(ValueError,match='REPORT_CONTINUATION_SCOPE_MISMATCH'):
        check_continuation(invalid)
    invalid=deepcopy(continuation);invalid['continuations']['continue-1']['checkpoint_id']='not-the-head'
    with pytest.raises(ValueError,match='REPORT_CONTINUATION_CHECKPOINT_MISMATCH'):
        check_continuation(invalid)
    continuation_pin,admitted=check_continuation(continuation)
    assert admitted[3].pin==unknown_pin and continuation_pin!=unknown_pin
    assert admitted[3].run_snapshot()==stopped['budget']
    # A failed status cannot disguise a new unknown hold from the earlier invocation.
    unknown_result=tmp_path/'unknown-records/only/result.json';unknown_bytes=unknown_result.read_bytes()
    try:
        unknown_result.write_text(json.dumps({**stopped,'status':'failed','error':{'type':'GraphRecursionError'}}))
        with pytest.raises(ValueError,match='REPORT_CONTINUATION_PRIOR_REQUIRED'):
            check_continuation(continuation)
    finally:unknown_result.write_bytes(unknown_bytes)
    unknown_mode=False
    original_native=native
    async def continuing_native(workspace,**kwargs):
        assert kwargs.get('continue_from_checkpoint')==head
        await original_native(workspace,**kwargs)
        return {'execution_status':'failed','status':'failed','last_error':{'type':'GraphRecursionError'}}
    monkeypatch.setattr(deep_runtime,'run_report',continuing_native)
    asyncio.run(run_authority.run_authorized_report(workspace,continuation_path,continuation_pin,env,'continue-1'))
    continued=json.loads((tmp_path/'unknown-records/continue-1/result.json').read_bytes())
    assert continued['authority_sha256']==continuation_pin and continued['status']=='failed' and continued['error']['type']=='GraphRecursionError'
    assert continued['stage_tokens']==11 and continued['budget']['held']==stopped['budget']['held']
    assert len(dispatched)==3
    # Failed-prior admission uses the real saved head and original immutable budget binding.
    failed_continuation=deepcopy(continuation)
    failed_continuation['invocations'].append('continue-2')
    failed_continuation['continuations']['continue-2']={'prior_invocation':'continue-1',
        'prior_authority':{'path':str(continuation_path),'sha256':continuation_pin},'checkpoint_id':head}
    failed_path=tmp_path/'failed-continuation.json';failed_path.write_text(json.dumps(failed_continuation))
    failed_pin=hashed(failed_path.read_bytes())
    result_path=tmp_path/'unknown-records/continue-1/result.json';original_result=result_path.read_bytes()
    try:
        result_path.write_text(json.dumps({**continued,'error':None}))
        with pytest.raises(ValueError,match='REPORT_CONTINUATION_PRIOR_REQUIRED'):
            run_authority.preflight(workspace,failed_path,failed_pin,env,'continue-2')
    finally:result_path.write_bytes(original_result)
    failed_dry=asyncio.run(run_authority.run_authorized_report(workspace,failed_path,failed_pin,env,'continue-2',dry_run=True))
    assert failed_dry['status']=='preflight_passed' and failed_dry['paid_calls']==0 and len(dispatched)==3
    assert not (tmp_path/'unknown-records/continue-2').exists()
    with pytest.raises(ValueError,match='REPORT_ALREADY_LAUNCHED'):
        check_continuation(continuation)
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True)) as db:
        assert db.execute('SELECT * FROM report_runs WHERE run_id=?',('production-unknown',)).fetchone()==original_binding
        current={row[0]:row for row in db.execute('SELECT * FROM attempts')}
        assert all(current[row[0]]==row for row in original_rows)


def test_parallel_attempts_cannot_overreserve(tmp_path):
    b=TokenBudget(tmp_path/'budget.db',100,{'m':20})
    def claim(_):
        try:b.reserve('m');return 1
        except RequestBudgetExceeded:return 0
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(claim,range(30)))==5
    assert b.snapshot()['reserved_or_unknown_upper_bounds']==100


def test_real_http_hooks_cover_success_and_unknown_without_double_count(tmp_path):
    async def run():
        b=TokenBudget(tmp_path/'budget.db',100,{'m':40});sent=[]
        def respond(req):
            sent.append(req)
            return httpx.Response(200,json={'id':str(len(sent)),'usage':{'total_tokens':10}} if len(sent)==1 else {'id':'missing'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond),event_hooks={'request':[account_request],'response':[account_response]}) as client:
            with token_budget(b),request_budget(RequestBudget(4)):
                await client.post('https://synthetic/chat',json={'model':'m','stream':False})
                await client.post('https://synthetic/chat',json={'model':'m','stream':False})
                assert b.snapshot()['recorded_tokens']==10
                assert b.snapshot()['reserved_or_unknown_upper_bounds']==40
                await client.post('https://synthetic/chat',json={'model':'m','stream':False})
                with pytest.raises(RequestBudgetExceeded):await client.post('https://synthetic/chat',json={'model':'m'})
        assert len(sent)==3
    asyncio.run(run())


def test_local_http_cap_rejection_releases_known_unsent_tokens(tmp_path):
    async def run():
        b=TokenBudget(tmp_path/'budget.db',100,{'m':40})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'usage':{'total_tokens':10}})),event_hooks={'request':[account_request],'response':[account_response]}) as client:
            with token_budget(b),request_budget(RequestBudget(1)):
                await client.post('https://synthetic/chat',json={'model':'m'})
                with pytest.raises(RequestBudgetExceeded):await client.post('https://synthetic/chat',json={'model':'m'})
        assert b.snapshot()['reserved_or_unknown_upper_bounds']==0
        assert b.snapshot()['attempt_states']['known_not_sent']==1
    asyncio.run(run())


def test_unverified_model_and_bound_violation_block_future_dispatch(tmp_path):
    b=TokenBudget(tmp_path/'budget.db',100,{'m':40})
    with pytest.raises(RequestBudgetExceeded,match='NOT_VERIFIED'):b.reserve('unverified')
    a=b.reserve('m');b.settle(a,{'total_tokens':41})
    with pytest.raises(RequestBudgetExceeded,match='VIOLATION'):b.reserve('m')
    assert b.snapshot()['recorded_tokens']==41


def test_sync_invocations_share_the_same_persistent_budget(tmp_path):
    b=TokenBudget(tmp_path/'budget.db',100,{'m':40})
    with token_budget(b),request_budget(RequestBudget(1)):
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'usage':{'total_tokens':20}})),event_hooks={'request':[account_request_sync],'response':[account_response_sync]}) as client:
            client.post('https://synthetic/chat',json={'model':'m'})
            with pytest.raises(RequestBudgetExceeded):client.post('https://synthetic/chat',json={'model':'m'})
    assert b.snapshot()['recorded_tokens']==20
    assert b.snapshot()['reserved_or_unknown_upper_bounds']==0


def test_budget_error_kind_is_preserved_without_exposing_arbitrary_text():
    from report_agent.deep_models import error_data
    assert error_data(RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED'))['message']=='AUTHORIZED_TOKEN_BUDGET_REACHED'
    assert error_data(RequestBudgetExceeded('https://private.invalid/secret'))['message']=='MODEL_REQUEST_BUDGET_REACHED'


def test_malformed_json_shapes_and_inconsistent_usage_keep_reservation_without_retry(tmp_path):
    async def run():
        b=TokenBudget(tmp_path/'budget.db',300,{'m':40});sent=[]
        bodies=[[],{'usage':[]},{'usage':{'total_tokens':0,'prompt_tokens':10,'completion_tokens':5}},
                {'usage':{'total_tokens':10,'prompt_tokens':10,'completion_tokens':5}}]
        def respond(req):
            sent.append(req)
            return httpx.Response(200,json=bodies[len(sent)-1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond),event_hooks={'request':[account_request],'response':[account_response]}) as client:
            with token_budget(b):
                for _ in bodies:await client.post('https://synthetic/chat',json={'model':'m'})
        assert len(sent)==4 and b.snapshot()['attempt_states']=={'unknown':4}
        assert b.snapshot()['recorded_tokens']==0
        assert b.snapshot()['reserved_or_unknown_upper_bounds']==160
    asyncio.run(run())


def test_sdk_does_not_resend_received_response_after_local_settlement_failure(tmp_path,monkeypatch):
    async def run():
        b=TokenBudget(tmp_path/'budget.db',100,{'m':40});sent=[]
        def respond(req):
            sent.append(req)
            return httpx.Response(200,json={'id':'r','object':'chat.completion','created':0,'model':'m',
              'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'Saved response'}}],
              'usage':{'total_tokens':10,'prompt_tokens':8,'completion_tokens':2}})
        def failed(*args,**kwargs):raise OSError('Synthetic local disk failure')
        monkeypatch.setattr(b,'settle',failed)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond),event_hooks={'request':[account_request],'response':[account_response]}) as http:
            client=openai.AsyncOpenAI(api_key='synthetic',base_url='https://synthetic',http_client=http,max_retries=5)
            with token_budget(b):
                with pytest.raises(RequestBudgetExceeded,match='TOKEN_LEDGER_SETTLEMENT_FAILED'):
                    await client.chat.completions.create(model='m',messages=[{'role':'user','content':'Test'}])
            await client.close()
        assert len(sent)==1
        assert b.snapshot()['reserved_or_unknown_upper_bounds']==40
    asyncio.run(run())


def test_sync_sdk_does_not_resend_after_settlement_failure(tmp_path,monkeypatch):
    b=TokenBudget(tmp_path/'budget.db',100,{'m':40});sent=[]
    def respond(req):
        sent.append(req)
        return httpx.Response(200,json={'usage':{'total_tokens':10}})
    def failed(*args,**kwargs):raise OSError('Synthetic ledger failure')
    monkeypatch.setattr(b,'settle',failed)
    with httpx.Client(transport=httpx.MockTransport(respond),event_hooks={'request':[account_request_sync],'response':[account_response_sync]}) as http:
        client=openai.OpenAI(api_key='synthetic',base_url='https://synthetic',http_client=http,max_retries=5)
        with token_budget(b),pytest.raises(RequestBudgetExceeded,match='TOKEN_LEDGER_SETTLEMENT_FAILED'):
            client.chat.completions.create(model='m',messages=[{'role':'user','content':'Test'}])
        client.close()
    assert len(sent)==1 and b.snapshot()['reserved_or_unknown_upper_bounds']==40


def _legacy_production_campaign(tmp_path, count):
    import hashlib
    from report_agent.token_budget import _LEGACY_CAMPAIGN_RUN_TRIGGER
    campaign=TokenBudget(tmp_path/'production-campaign.db',500,{'m':40})
    for _ in range(count):campaign.reserve('m')
    with campaign.connect() as db:
        holds=[list(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]
        db.execute('CREATE TABLE fake_flow_runs (run_id TEXT PRIMARY KEY, maximum INTEGER NOT NULL, authority TEXT NOT NULL)')
        db.execute('CREATE TABLE fake_run_attempts (attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL)')
        db.execute('CREATE TABLE fake_comparison_requests (request_id TEXT PRIMARY KEY, held_id TEXT NOT NULL, run_id TEXT NOT NULL)')
        db.execute('CREATE TABLE fake_continuations (previous_id TEXT NOT NULL, retry_id TEXT PRIMARY KEY, run_id TEXT NOT NULL)')
        db.execute(_LEGACY_CAMPAIGN_RUN_TRIGGER)
        old_guard=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='fake_reservation'").fetchone()[0]
    return campaign,holds,hashlib.sha256(old_guard.encode()).hexdigest()


def test_production_campaign_preserves_two_holds_and_migrates_atomically(tmp_path,monkeypatch):
    import sqlite3
    import report_agent.token_budget as budgets
    campaign,holds,old_pin=_legacy_production_campaign(tmp_path,2)
    before=campaign.path.read_bytes()
    # A denied DDL operation must roll back the new table as well as the guard.
    connect=sqlite3.connect
    def deny_guard_change(*args,**kwargs):
        db=connect(*args,**kwargs)
        db.set_authorizer(lambda action,*_:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_DROP_TRIGGER else sqlite3.SQLITE_OK)
        return db
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3,'connect',deny_guard_change)
        with pytest.raises(sqlite3.DatabaseError):
            budgets.CampaignRunBudget.migrate_hold_guard(campaign.path,
                previous_guard_sha256=old_pin,new_guard_sha256=budgets.CAMPAIGN_HOLD_GUARD_SHA256)
    assert campaign.path.read_bytes()==before
    with pytest.raises(ValueError,match='REPORT_CAMPAIGN_GUARD_PIN_MISMATCH'):
        budgets.CampaignRunBudget.migrate_hold_guard(campaign.path,
            previous_guard_sha256='0'*64,new_guard_sha256=budgets.CAMPAIGN_HOLD_GUARD_SHA256)
    migrated=budgets.CampaignRunBudget.migrate_hold_guard(campaign.path,
        previous_guard_sha256=old_pin,new_guard_sha256=budgets.CAMPAIGN_HOLD_GUARD_SHA256)
    assert migrated['applied'] and migrated['attempts_unchanged']
    assert not budgets.CampaignRunBudget.migrate_hold_guard(campaign.path,
        previous_guard_sha256=old_pin,new_guard_sha256=migrated['guard_sha256'])['applied']
    options=dict(maximum_tokens=40,aggregate_tokens=500,model_bounds={'m':40},
        authority_sha256='a'*64,preserved_holds=holds,guard_sha256=migrated['guard_sha256'])
    budget=budgets.CampaignRunBudget(campaign.path,'fresh',**options)
    request=budget.reserve('m')
    with campaign.connect() as db:
        assert [list(r) for r in db.execute('SELECT * FROM attempts WHERE id<>? ORDER BY id',(request,))]==holds
        assert db.execute('SELECT request_id,held_id,run_id FROM report_hold_exemptions ORDER BY held_id').fetchall()==[(request,h[0],'fresh') for h in holds]
        assert not db.execute('SELECT * FROM fake_continuations').fetchall()
        assert not db.execute('SELECT * FROM fake_comparison_requests').fetchall()
    assert budget.run_snapshot()=={'maximum_tokens':40,'settled':0,'held':40}
    budget.settle(request,{'total_tokens':10})
    assert budget.run_snapshot()=={'maximum_tokens':40,'settled':10,'held':0}
    with pytest.raises(RequestBudgetExceeded,match='REPORT_RUN_TOKEN_LIMIT'):budget.reserve('m')
    with campaign.connect() as db:
        assert [list(r) for r in db.execute('SELECT * FROM attempts WHERE id<>? ORDER BY id',(request,))]==holds


def test_production_campaign_refuses_unlisted_or_changed_pending_hold(tmp_path):
    import report_agent.token_budget as budgets
    campaign,holds,old_pin=_legacy_production_campaign(tmp_path,3)
    migrated=budgets.CampaignRunBudget.migrate_hold_guard(campaign.path,
        previous_guard_sha256=old_pin,new_guard_sha256=budgets.CAMPAIGN_HOLD_GUARD_SHA256)
    options=dict(maximum_tokens=40,aggregate_tokens=500,model_bounds={'m':40},
        authority_sha256='a'*64,preserved_holds=holds[:2],guard_sha256=migrated['guard_sha256'])
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNRESOLVED_ATTEMPT'):
        budgets.CampaignRunBudget(campaign.path,'unlisted',**options)
    campaign.before_send_cancelled(holds[2][0])
    budget=budgets.CampaignRunBudget(campaign.path,'changed',**options)
    with campaign.connect() as db:
        db.execute('UPDATE attempts SET reason=? WHERE id=?',('Synthetic unexpected hold change',holds[0][0]))
        before=db.execute('SELECT * FROM attempts ORDER BY id').fetchall()
    with pytest.raises(RequestBudgetExceeded,match='REPORT_UNRESOLVED_ATTEMPT'):budget.reserve('m')
    with campaign.connect() as db:assert db.execute('SELECT * FROM attempts ORDER BY id').fetchall()==before
