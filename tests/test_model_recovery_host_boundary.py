"""Offline SDK proof of the fresh host's existing recovery/latch ordering."""
import httpx
import openai
import pytest
from langchain_core.callbacks import BaseCallbackHandler

from report_agent.deep_models import configured_model,error_data
from report_agent.model_recovery import activate_recovery,STATE_KEY
from report_agent.request_budget import RequestBudgetExceeded,request_reservation_observer
from report_agent.store import Store
from report_agent.token_budget import TokenBudget,token_budget
from test_transport_observation import use_mock,close,body


@pytest.mark.parametrize('mode',['disabled','recovers','exhausted'])
async def test_outer_host_latch_only_observes_final_model_failure(tmp_path,monkeypatch,mode):
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    for suffix,value in [('MODEL','deepseek-v4.1-flash'),('BASE_URL','https://fixture.invalid/v1'),
                         ('API_KEY','fixture-only')]:
        monkeypatch.setenv('REPORT_COORDINATOR_'+suffix,value)
    store=Store(tmp_path/'fresh-synthetic')
    if mode!='disabled':activate_recovery(store,authorization='synthetic-fresh-host-policy')
    state={'failed':False,'errors':0};admissions=[];sends=[]
    class Audit(BaseCallbackHandler):
        def on_llm_error(self,error,**kwargs):
            state['failed']=True;state['errors']+=1
    model=configured_model(store,'coordinator')
    def respond(request):
        sends.append(request)
        if mode!='recovers' or len(sends)==1:
            raise httpx.ConnectError('Synthetic TLS connection failure; no real socket',request=request)
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'synthetic-budget.db',300,{'deepseek-v4.1-flash':40})
    def admission():
        snapshot=budget.snapshot();admissions.append({'failed':state['failed'],**snapshot})
        # Same guard as the historical host, without a new recovery exception.
        if state['failed'] or snapshot['attempt_states'].get('unknown',0):
            raise RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')
    try:
        with token_budget(budget),request_reservation_observer(admission):
            if mode=='recovers':
                assert (await model.ainvoke('Synthetic fresh input',config={'callbacks':[Audit()]})).content=='unchanged result'
                assert state=={'failed':False,'errors':0}
            else:
                with pytest.raises(openai.APIConnectionError):
                    await model.ainvoke('Synthetic fresh input',config={'callbacks':[Audit()]})
                assert state=={'failed':True,'errors':1}
                before=budget.snapshot()
                with pytest.raises((RequestBudgetExceeded,openai.APIConnectionError)) as blocked:
                    await model.ainvoke('A different request after the group failed')
                assert error_data(blocked.value)['message']=='HOST_TECHNICAL_FAILURE_PENDING'
                after=budget.snapshot()
                assert after['reserved_or_unknown_upper_bounds']==before['reserved_or_unknown_upper_bounds']
                assert after['attempt_states'].get('known_not_sent')==1
        expected=1 if mode=='disabled' else 2
        assert len(sends)==expected
        # Every physical recovery attempt was admitted before the outer failure callback.
        assert all(not item['failed'] for item in admissions[:expected])
        assert budget.snapshot()['attempt_states']['reserved']==(1 if mode!='exhausted' else 2)
        if mode=='recovers':
            assert budget.snapshot()['attempt_states']['settled']==1
            assert budget.snapshot()['recorded_tokens']==10
        if mode!='disabled':
            assert store.get(STATE_KEY)['extra_calls']==1
            assert store.get(STATE_KEY)['extra_token_bounds']==40
        assert model.root_async_client.max_retries==0
    finally:
        await close(model)
