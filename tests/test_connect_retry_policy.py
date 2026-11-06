"""Use HTTPX/httpcore's real retry loop with offline network streams."""
import json
import httpcore
import httpx
import pytest
from httpcore._backends.mock import AsyncMockBackend, AsyncMockStream
from report_agent.deep_models import model_async_client, connection_retry_count, configured_model, configured_vision_client
from report_agent.store import Store


class Backend(AsyncMockBackend):
    def __init__(self, failures, failure_type=httpcore.ConnectError, read_failure=False):
        super().__init__([b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK'])
        self.failures, self.failure_type, self.read_failure = failures, failure_type, read_failure
        self.connections, self.writes, self.delays = 0, 0, []
        self.sent = []

    async def connect_tcp(self, **kwargs):
        self.connections += 1
        if self.connections <= self.failures:
            raise self.failure_type('offline connection failure')
        owner = self
        class Stream(AsyncMockStream):
            async def write(self, buffer, timeout=None):
                owner.writes += 1
                owner.sent.append(buffer)
                await super().write(buffer, timeout)
            async def read(self, max_bytes, timeout=None):
                if owner.read_failure: raise httpcore.ReadTimeout('offline read timeout')
                return await super().read(max_bytes, timeout)
        return Stream(list(self._buffer))

    async def sleep(self, seconds):
        self.delays.append(seconds)


@pytest.mark.parametrize('failure_type',[httpcore.ConnectError,httpcore.ConnectTimeout])
async def test_two_pre_send_failures_then_one_http_request(tmp_path, monkeypatch, failure_type):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    store = Store(tmp_path)
    client = model_async_client(store,'reviewer')
    backend = Backend(2,failure_type)
    client._transport._pool._network_backend = backend
    try:
        response = await client.post('http://offline.invalid/v1',json={'offline':True})
        assert response.text=='OK' and backend.connections==3
        assert b''.join(backend.sent).count(b'POST /v1 HTTP/1.1')==1
        assert b''.join(backend.sent).count(b'{"offline":true}')==1
        assert len(backend.delays)==2
        with store.connect() as db:
            events=[json.loads(d) for d, in db.execute("select data from events where kind='model_connection_retry_trace'")]
        assert sum(e['event']=='connection.connect_tcp.failed' for e in events)==2
        assert sum(e['event']=='connection.retry.started' for e in events)==2
    finally: await client.aclose()


async def test_connection_retry_exhaustion_sends_no_http_body(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    client=model_async_client(Store(tmp_path),'writer');backend=Backend(3)
    client._transport._pool._network_backend=backend
    try:
        with pytest.raises(httpx.ConnectError): await client.post('http://offline.invalid/v1',json={'offline':True})
        assert backend.connections==3 and backend.writes==0
    finally: await client.aclose()


async def test_read_timeout_after_send_is_not_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    client=model_async_client(Store(tmp_path),'writer');backend=Backend(0,read_failure=True)
    client._transport._pool._network_backend=backend
    try:
        with pytest.raises(httpx.ReadTimeout): await client.post('http://offline.invalid/v1',json={'offline':True})
        assert backend.connections==1 and not backend.delays
        assert b''.join(backend.sent).count(b'POST /v1 HTTP/1.1')==1
    finally: await client.aclose()


async def test_server_error_after_send_is_not_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    client=model_async_client(Store(tmp_path),'writer');backend=Backend(0)
    backend._buffer=[b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n']
    client._transport._pool._network_backend=backend
    try:
        response=await client.post('http://offline.invalid/v1',json={'offline':True})
        assert response.status_code==503 and backend.connections==1 and not backend.delays
        assert b''.join(backend.sent).count(b'POST /v1 HTTP/1.1')==1
    finally: await client.aclose()


@pytest.mark.parametrize('value',['-1','3','true','2.0'])
def test_invalid_retry_count_is_rejected(monkeypatch,value):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES',value)
    with pytest.raises(RuntimeError,match='MODEL_CONNECT_RETRIES_INVALID'): connection_retry_count()


async def test_chat_and_vision_enable_only_transport_connect_retries(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    for suffix,value in [('MODEL','glm-5.3'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','offline-key')]:
        monkeypatch.setenv('REPORT_'+suffix,value)
        for role in ['COORDINATOR','VISION']: monkeypatch.setenv('REPORT_'+role+'_'+suffix,value)
    model=configured_model(Store(tmp_path),'coordinator')
    vision=configured_vision_client()
    try:
        assert model.root_async_client.max_retries==model.root_client.max_retries==vision.max_retries==0
        assert model.http_async_client._transport._pool._retries==2
        assert model.http_client._transport._pool._retries==2
        assert vision._client._transport._pool._retries==2
    finally:
        await model.root_async_client.close();model.root_client.close();await vision.close()


# These backends replace only the network boundary of the actual factory pool.
import ssl
import openai
from hashlib import sha256
from httpcore._backends.mock import MockBackend, MockStream
from langchain_core.callbacks import BaseCallbackHandler
from report_agent.deep_models import model_sync_client
from report_agent.assessment_completion import read_finance
from report_agent.probe_budget import ProbeBudget
from report_agent.token_budget import TokenBudget, RequestBound, token_budget, request_token_bound
from report_agent.request_budget import RequestBudgetExceeded, request_reservation_observer

MODEL='glm-5.3'
URL='https://offline.invalid/v1/chat/completions'
FULL_BOUND=RequestBound(MODEL,sha256(URL.encode()).hexdigest(),1_048_576,131_072,'a'*64)


def http_response(status=200):
    body=({'id':'offline','object':'chat.completion','created':1,'model':MODEL,
        'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'offline success'}}],
        'usage':{'prompt_tokens':6,'completion_tokens':4,'total_tokens':10}}
        if status==200 else {'error':{'message':'synthetic server error','type':'server_error'}})
    raw=json.dumps(body).encode()
    return b'HTTP/1.1 '+str(status).encode()+b' Offline\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw)).encode()+b'\r\n\r\n'+raw


class TLSFacts:
    def __init__(self,failures=0,failure=None,status=200):
        self.failures,self.failure=failures,failure
        self.response=http_response(status)
        self.connections=0;self.tls_attempts=0;self.sent=[];self.delays=[]

    def tls(self,ssl_context,server_hostname):
        self.tls_attempts+=1
        assert ssl_context.verify_mode==ssl.CERT_REQUIRED and ssl_context.check_hostname
        assert server_hostname=='offline.invalid'
        if self.tls_attempts<=self.failures:
            raise httpcore.ConnectError('synthetic TLS handshake failure')

    def write(self,buffer):
        self.sent.append(buffer)
        if self.failure=='write' and buffer and not buffer.startswith(b'POST '):
            raise httpcore.WriteError('synthetic body write failure')

    def read(self):
        if self.failure=='read':
            raise httpcore.ReadTimeout('synthetic response read timeout')
        if self.failure=='write':
            raise httpcore.ReadError('synthetic stream broken after body write failure')


class AsyncTLSBackend(AsyncMockBackend,TLSFacts):
    def __init__(self,**kwargs):
        TLSFacts.__init__(self,**kwargs)

    async def connect_tcp(self,**kwargs):
        self.connections+=1;owner=self
        class Stream(AsyncMockStream):
            async def start_tls(self,ssl_context,server_hostname=None,timeout=None):
                owner.tls(ssl_context,server_hostname)
                return self
            async def write(self,buffer,timeout=None):
                owner.write(buffer)
                await super().write(buffer,timeout)
            async def read(self,max_bytes,timeout=None):
                owner.read()
                return await super().read(max_bytes,timeout)
        return Stream([self.response])

    async def sleep(self,seconds):
        self.delays.append(seconds)


class SyncTLSBackend(MockBackend,TLSFacts):
    def __init__(self,**kwargs):
        TLSFacts.__init__(self,**kwargs)

    def connect_tcp(self,**kwargs):
        self.connections+=1;owner=self
        class Stream(MockStream):
            def start_tls(self,ssl_context,server_hostname=None,timeout=None):
                owner.tls(ssl_context,server_hostname)
                return self
            def write(self,buffer,timeout=None):
                owner.write(buffer)
                super().write(buffer,timeout)
            def read(self,max_bytes,timeout=None):
                owner.read()
                return super().read(max_bytes,timeout)
        return Stream([self.response])

    def sleep(self,seconds):
        self.delays.append(seconds)


class Turns(BaseCallbackHandler):
    def __init__(self):self.count=0
    def on_chat_model_start(self,*args,**kwargs):self.count+=1


def configured_tls_case(tmp_path,monkeypatch,asynchronous,*,failures=0,failure=None,status=200,cap=2_200_000):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_REASONING_EFFORT','high')
    for suffix,value in [('MODEL',MODEL),('BASE_URL','https://offline.invalid/v1'),('API_KEY','synthetic')]:
        monkeypatch.setenv('REPORT_WRITER_'+suffix,value)
    store=Store(tmp_path/'runtime')
    model=configured_model(store,'writer')
    client=model.http_async_client if asynchronous else model.http_client
    pool=client._transport._pool
    assert pool._keepalive_expiry==60.0
    assert pool._max_connections==100 and pool._max_keepalive_connections==20 and pool._retries==2
    backend=(AsyncTLSBackend if asynchronous else SyncTLSBackend)(failures=failures,failure=failure,status=status)
    pool._network_backend=backend
    assert client._transport._pool is pool
    budgets=TokenBudget(tmp_path/'tokens.db',20_000_000,{MODEL:2_000_000})
    original=read_finance(budgets.path);hold_id=budgets.reserve(MODEL)
    baseline=read_finance(budgets.path);hold=next(row for row in baseline['rows'] if row[0]==hold_id)
    guard=ProbeBudget(lambda:read_finance(budgets.path),original,baseline,
                      maximum_tokens=cap,preserved_hold=hold,writer_model=MODEL)
    return model,client,backend,budgets,baseline,hold,guard


async def close_model(model):
    await model.root_async_client.close();model.root_client.close()


@pytest.mark.parametrize('retries',[0,2])
async def test_actual_configured_sync_and_async_pools_keep_native_limits_and_ssl(tmp_path,monkeypatch,retries):
    from report_agent import deep_models
    monkeypatch.setenv('REPORT_CONNECT_RETRIES',str(retries));monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_REASONING_EFFORT','high')
    for suffix,value in [('MODEL',MODEL),('BASE_URL','https://offline.invalid/v1'),('API_KEY','synthetic')]:
        monkeypatch.setenv('REPORT_WRITER_'+suffix,value)
    model=configured_model(Store(tmp_path),'writer')
    try:
        assert deep_models.MODEL_KEEPALIVE_EXPIRY_SECONDS==60.0
        for client in (model.http_async_client,model.http_client):
            pool=client._transport._pool
            assert pool._keepalive_expiry==60.0
            assert pool._max_connections==100 and pool._max_keepalive_connections==20
            assert pool._retries==retries
            assert pool._ssl_context.verify_mode==ssl.CERT_REQUIRED
            assert pool._ssl_context.check_hostname
        assert model.root_async_client.max_retries==model.root_client.max_retries==0
    finally:
        await close_model(model)


async def test_zero_connect_retries_preserve_existing_async_environment_proxy_route(monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0');monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('HTTPS_PROXY','http://synthetic-proxy.invalid:3128')
    monkeypatch.setenv('HTTP_PROXY','http://synthetic-proxy.invalid:3128')
    monkeypatch.setenv('NO_PROXY','')
    monkeypatch.delenv('ALL_PROXY',raising=False)
    asynchronous=model_async_client();synchronous=model_sync_client()
    try:
        route=asynchronous._transport_for_url(httpx.URL('https://routed.invalid/v1'))
        assert route is not asynchronous._transport
        assert isinstance(route._pool,httpcore.AsyncHTTPProxy)
        assert route._pool._keepalive_expiry==60.0
        assert synchronous._transport_for_url(httpx.URL('https://routed.invalid/v1')) is synchronous._transport
    finally:
        await asynchronous.aclose();synchronous.close()


@pytest.mark.parametrize('asynchronous',[True,False],ids=['async','sync'])
@pytest.mark.parametrize('failures',[1,2])
async def test_native_tls_failures_then_one_sdk_post_one_finance_row_and_one_turn(tmp_path,monkeypatch,asynchronous,failures):
    model,client,backend,budget,baseline,hold,guard=configured_tls_case(tmp_path,monkeypatch,asynchronous,failures=failures)
    bodies=[];turns=Turns()
    if asynchronous:
        async def capture(request):bodies.append(request.content)
    else:
        def capture(request):bodies.append(request.content)
    client.event_hooks['request'].append(capture)
    try:
        with token_budget(budget),request_token_bound(FULL_BOUND),request_reservation_observer(guard.check):
            if asynchronous: result=await model.ainvoke('synthetic TLS retry',config={'callbacks':[turns]})
            else: result=model.invoke('synthetic TLS retry',config={'callbacks':[turns]})
        assert result.content=='offline success' and turns.count==1
        assert backend.connections==backend.tls_attempts==failures+1 and len(backend.delays)==failures
        assert len(bodies)==1
        sent=b''.join(backend.sent)
        assert sent.count(b'POST /v1/chat/completions HTTP/1.1')==1
        assert sent.count(bodies[0])==1
        now=read_finance(budget.path);old_ids={r[0] for r in baseline['rows']}
        added=[r for r in now['rows'] if r[0] not in old_ids]
        assert len(added)==1 and added[0][2:5]==[1_179_648,10,'settled']
        assert hold in now['rows'] and now['auth']==baseline['auth']
        assert guard.check()==(10,0)
    finally:
        await close_model(model)


@pytest.mark.parametrize('asynchronous',[True,False],ids=['async','sync'])
async def test_native_tls_retry_exhaustion_stops_at_three_handshakes_without_http(tmp_path,monkeypatch,asynchronous):
    model,_,backend,budget,baseline,hold,guard=configured_tls_case(tmp_path,monkeypatch,asynchronous,failures=3)
    turns=Turns()
    try:
        with token_budget(budget),request_token_bound(FULL_BOUND),request_reservation_observer(guard.check):
            with pytest.raises(openai.APIConnectionError):
                if asynchronous:await model.ainvoke('synthetic TLS exhaustion',config={'callbacks':[turns]})
                else:model.invoke('synthetic TLS exhaustion',config={'callbacks':[turns]})
        assert backend.connections==backend.tls_attempts==3 and len(backend.delays)==2
        assert not backend.sent and turns.count==1
        now=read_finance(budget.path);old_ids={r[0] for r in baseline['rows']}
        added=[r for r in now['rows'] if r[0] not in old_ids]
        assert len(added)==1 and added[0][2:5]==[1_179_648,None,'reserved']
        assert hold in now['rows'] and now['auth']==baseline['auth']
    finally:await close_model(model)


@pytest.mark.parametrize('asynchronous',[True,False],ids=['async','sync'])
@pytest.mark.parametrize('failure,status',[('read',200),('write',200),(None,500)])
async def test_post_send_read_write_or_http_500_never_retries(tmp_path,monkeypatch,asynchronous,failure,status):
    model,_,backend,budget,baseline,hold,guard=configured_tls_case(tmp_path,monkeypatch,asynchronous,failure=failure,status=status)
    turns=Turns()
    try:
        with token_budget(budget),request_token_bound(FULL_BOUND),request_reservation_observer(guard.check):
            with pytest.raises(openai.InternalServerError if status==500 else openai.APIConnectionError):
                if asynchronous:await model.ainvoke('synthetic after-send failure',config={'callbacks':[turns]})
                else:model.invoke('synthetic after-send failure',config={'callbacks':[turns]})
        assert turns.count==1 and backend.connections==backend.tls_attempts==1 and not backend.delays
        assert b''.join(backend.sent).count(b'POST /v1/chat/completions HTTP/1.1')==1
        now=read_finance(budget.path);old_ids={r[0] for r in baseline['rows']}
        added=[r for r in now['rows'] if r[0] not in old_ids]
        assert len(added)==1 and added[0][2]==1_179_648 and added[0][4] in ('reserved','unknown')
        assert hold in now['rows']
    finally:await close_model(model)


@pytest.mark.parametrize('asynchronous',[True,False],ids=['async','sync'])
async def test_stage_cap_rejects_before_tls_and_preserves_old_hold(tmp_path,monkeypatch,asynchronous):
    model,_,backend,budget,baseline,hold,guard=configured_tls_case(tmp_path,monkeypatch,asynchronous,cap=1_179_647)
    try:
        with token_budget(budget),request_token_bound(FULL_BOUND),request_reservation_observer(guard.check):
            with pytest.raises(RequestBudgetExceeded,match='PROBE_TOKEN_LIMIT'):
                if asynchronous:await model.ainvoke('synthetic cap refusal')
                else:model.invoke('synthetic cap refusal')
        assert backend.connections==backend.tls_attempts==0 and not backend.sent
        now=read_finance(budget.path);old_ids={r[0] for r in baseline['rows']}
        added=[r for r in now['rows'] if r[0] not in old_ids]
        assert len(added)==1 and added[0][3:5]==[0,'known_not_sent']
        assert hold in now['rows']
    finally:await close_model(model)
