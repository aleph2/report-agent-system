import asyncio
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
import openai
from report_agent.token_budget import TokenBudget,token_budget,account_response,account_response_sync
from report_agent.request_budget import RequestBudget,RequestBudgetExceeded,request_budget,account_request,account_request_sync


def test_persistent_atomic_reservations_settle_once_and_keep_unknown(tmp_path):
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
