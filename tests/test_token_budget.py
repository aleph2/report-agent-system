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



    import asyncio,json
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
    text_url='https://synthetic.invalid/v1'
    vision_url='https://synthetic.maas.aliyuncs.com/v1'
    env.write_text('GLM_NAME=glm-5.3\nGLM_BASE_URL='+text_url+'\nGLM_API_KEY=synthetic\nVISION_NAME=deepseek-v4.1-flash-1017\nVISION_BASE_URL='+vision_url+'\nVISION_API_KEY=synthetic\n')
    hashed=lambda value:sha256(value).hexdigest()
    common=dict(env_sha256=hashed(env.read_bytes()))
    text_proof=dict(common,model='glm-5.3',input_limit=1048576,output_limit=131072,
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
        inputs=[{'path':str(scope),'sha256':hashed(scope.read_bytes())}],
        criteria={'path':str(criteria),'sha256':hashed(criteria.read_bytes())},
        transport={'sdk_retries':0,'connect_retries':0,'vision_thinking':'disabled'},
        invocations=['planning','completion'],record_dir=str(tmp_path/'records'),run_id='production-flow',
        budget={'ledger':str(ledger),'per_run_tokens':4000000,'aggregate_tokens':10000000,
                'preserved_holds':[],'guard_sha256':hashed(b'')})
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
    assert stopped['status']=='unknown_outcome_held' and stopped['budget']['held']==1179648
    assert len(dispatched)==2
    with pytest.raises(ValueError,match='REPORT_ALREADY_LAUNCHED'):
        asyncio.run(run_authority.run_authorized_report(workspace,unknown_path,unknown_pin,env,'only'))
    assert len(dispatched)==2


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
