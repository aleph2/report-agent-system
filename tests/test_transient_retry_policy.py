"""Offline checks exercise the real SDK retry loop, no custom retry executor."""
import json
import httpx
import openai
import pytest
from report_agent.deep_models import configured_model, configured_vision_client, sdk_retry_count
from report_agent.store import Store

@pytest.fixture
def enabled(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0');monkeypatch.setenv('REPORT_SDK_RETRIES','5')
    for suffix,value in [('MODEL','glm-5.3'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','offline-key')]:
        monkeypatch.setenv('REPORT_'+suffix,value)
        for role in ['COORDINATOR','VISION']:monkeypatch.setenv('REPORT_'+role+'_'+suffix,value)
    return Store(tmp_path)

@pytest.mark.parametrize('failure',[429,500,503,408,409,'read','connect'])
async def test_transient_failure_retries_same_request_only(enabled,monkeypatch,failure):
    model=configured_model(enabled,'coordinator');requests=[]
    async def handle(request):
        requests.append(request.content)
        if len(requests)==1:
            if failure=='read':raise httpx.ReadTimeout('offline',request=request)
            if failure=='connect':raise httpx.ConnectError('offline',request=request)
            return httpx.Response(failure,json={'error':{'message':'offline'}},headers={'retry-after':'0.001'})
        return httpx.Response(200,json={'id':'offline','object':'chat.completion','created':1,'model':'glm-5.3','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'OK'}}],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}})
    model.http_async_client._transport=httpx.MockTransport(handle)
    monkeypatch.setattr(model.root_async_client,'_calculate_retry_timeout',lambda *args:0)
    try:
        assert (await model.ainvoke('offline')).content=='OK'
        assert len(requests)==2 and requests[0]==requests[1]
        starts=[e['data'] for e in enabled.events() if e['kind']=='model_http_attempt_started']
        assert [e['retry_index'] for e in starts]==[0,1]
        assert len({e['body_sha256'] for e in starts})==1
    finally:await model.root_async_client.close();model.root_client.close()

@pytest.mark.parametrize('failure',[400,401,403,404,422])
async def test_permanent_error_not_retried_even_with_provider_override(enabled,monkeypatch,failure):
    model=configured_model(enabled,'coordinator');requests=[]
    async def handle(request):
        requests.append(request)
        return httpx.Response(failure,json={'error':{'message':'offline'}},headers={'x-should-retry':'true'})
    model.http_async_client._transport=httpx.MockTransport(handle)
    monkeypatch.setattr(model.root_async_client,'_calculate_retry_timeout',lambda *args:0)
    try:
        with pytest.raises(openai.APIStatusError):await model.ainvoke('offline')
        assert len(requests)==1
    finally:await model.root_async_client.close();model.root_client.close()

async def test_five_retries_exhaust_then_error(enabled,monkeypatch):
    model=configured_model(enabled,'coordinator');requests=[]
    async def handle(request):
        requests.append(request.content);return httpx.Response(503,json={'error':{'message':'offline'}})
    model.http_async_client._transport=httpx.MockTransport(handle)
    monkeypatch.setattr(model.root_async_client,'_calculate_retry_timeout',lambda *args:0)
    try:
        with pytest.raises(openai.APIStatusError):await model.ainvoke('offline')
        assert len(requests)==6 and len(set(requests))==1
    finally:await model.root_async_client.close();model.root_client.close()

async def test_chat_and_vision_bound_at_construction(enabled):
    model=configured_model(enabled,'coordinator');vision=configured_vision_client()
    try:
        assert model.max_retries==model.root_async_client.max_retries==model.root_client.max_retries==vision.max_retries==5
        assert model.http_async_client._transport._pool._retries==0
    finally:await model.root_async_client.close();model.root_client.close();await vision.close()

def test_retry_layers_do_not_multiply(monkeypatch):
    monkeypatch.setenv('REPORT_SDK_RETRIES','5');monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    with pytest.raises(RuntimeError,match='MODEL_RETRY_LAYERS_MUST_NOT_STACK'):sdk_retry_count()
