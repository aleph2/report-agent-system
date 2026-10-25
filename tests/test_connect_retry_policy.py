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
    client._transport._pool = httpcore.AsyncConnectionPool(retries=2,network_backend=backend)
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
    client._transport._pool=httpcore.AsyncConnectionPool(retries=2,network_backend=backend)
    try:
        with pytest.raises(httpx.ConnectError): await client.post('http://offline.invalid/v1',json={'offline':True})
        assert backend.connections==3 and backend.writes==0
    finally: await client.aclose()


async def test_read_timeout_after_send_is_not_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    client=model_async_client(Store(tmp_path),'writer');backend=Backend(0,read_failure=True)
    client._transport._pool=httpcore.AsyncConnectionPool(retries=2,network_backend=backend)
    try:
        with pytest.raises(httpx.ReadTimeout): await client.post('http://offline.invalid/v1',json={'offline':True})
        assert backend.connections==1 and not backend.delays
        assert b''.join(backend.sent).count(b'POST /v1 HTTP/1.1')==1
    finally: await client.aclose()


async def test_server_error_after_send_is_not_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    client=model_async_client(Store(tmp_path),'writer');backend=Backend(0)
    backend._buffer=[b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n']
    client._transport._pool=httpcore.AsyncConnectionPool(retries=2,network_backend=backend)
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
