"""Verify the actual SDK clients and wire timeout, without paid requests."""
import httpx
import asyncio
import pytest

from report_agent.deep_models import configured_model, configured_vision_client
from report_agent.store import Store


@pytest.mark.parametrize('model_name,url', [
    ('glm-5.3', 'https://offline.invalid/v1'),
    ('deepseek-v4.1-flash', 'https://offline.invalid/v1'),
    ('deepseek-flash', 'https://api.deepseek.com'),
])
async def test_timeout_reaches_constructed_chat_clients_and_request(tmp_path, monkeypatch, model_name, url):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    for suffix, value in [('MODEL', model_name), ('BASE_URL', url), ('API_KEY', 'offline-key')]:
        monkeypatch.setenv('REPORT_COORDINATOR_' + suffix, value)
    model = configured_model(Store(tmp_path), 'coordinator')
    seen = []

    async def handle(request):
        seen.append(request.extensions['timeout'])
        return httpx.Response(200, json={
            'id': 'offline', 'object': 'chat.completion', 'created': 1, 'model': model_name,
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'OK'}}],
        })

    model.http_async_client._transport = httpx.MockTransport(handle)
    try:
        for client in [model.root_client, model.root_async_client]:
            assert client.timeout.read == 600
            assert client.timeout.connect == 15
            assert client.timeout.write == client.timeout.pool == 60
            assert client.max_retries == 5
        assert (await model.ainvoke('offline')).content == 'OK'
        assert seen == [{'connect': 15, 'read': 600, 'write': 60, 'pool': 60}]
    finally:
        await model.root_async_client.close()
        model.root_client.close()


async def test_vision_request_uses_ten_minute_read_timeout(monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    for suffix, value in [('MODEL', 'glm-5.3'), ('BASE_URL', 'https://offline.invalid/v1'),
                          ('API_KEY', 'offline-key')]:
        monkeypatch.setenv('REPORT_VISION_' + suffix, value)
    client = configured_vision_client()
    seen = []

    async def handle(request):
        seen.append(request.extensions['timeout'])
        return httpx.Response(200, json={
            'id': 'offline', 'object': 'chat.completion', 'created': 1, 'model': 'offline',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'OK'}}],
        })

    client._client._transport = httpx.MockTransport(handle)
    try:
        assert client.max_retries == 5
        await client.chat.completions.create(model='offline', messages=[{'role': 'user', 'content': 'offline'}])
        assert seen == [{'connect': 15, 'read': 600, 'write': 60, 'pool': 60}]
    finally:
        await client.close()


async def test_chat_deadline_cancels_inflight_sdk_without_later_retry(tmp_path, monkeypatch):
    monkeypatch.setattr('report_agent.deep_models.MODEL_REQUEST_DEADLINE_SECONDS', .02)
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    for suffix, value in [('MODEL', 'glm-5.3'), ('BASE_URL', 'https://offline.invalid/v1'), ('API_KEY', 'offline-key')]:
        monkeypatch.setenv('REPORT_COORDINATOR_' + suffix, value)
    model = configured_model(Store(tmp_path), 'coordinator')
    requests, canceled = [], []

    async def handle(request):
        requests.append(request)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.append(True)
            raise

    model.http_async_client._transport = httpx.MockTransport(handle)
    try:
        with pytest.raises(TimeoutError):
            await model.ainvoke('offline')
        await asyncio.sleep(.01)
        assert len(requests) == 1 and canceled == [True]
    finally:
        await model.root_async_client.close()
        model.root_client.close()


async def test_vision_deadline_is_failed_uncached_observation(tmp_path, monkeypatch):
    from report_agent.vision import observe_source_image
    from test_document_tools import workspace
    monkeypatch.setattr('report_agent.vision.MODEL_REQUEST_DEADLINE_SECONDS', .02)
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    for suffix, value in [('MODEL', 'glm-5.3'), ('BASE_URL', 'https://offline.invalid/v1'), ('API_KEY', 'offline-key')]:
        monkeypatch.setenv('REPORT_VISION_' + suffix, value)
    client = configured_vision_client()
    ws = workspace(tmp_path)
    requests, canceled = [], []

    async def handle(request):
        requests.append(request)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            canceled.append(True)
            raise

    client._client._transport = httpx.MockTransport(handle)
    try:
        result = await observe_source_image(ws, 'original', 'Read visible labels.', client=client)
        assert result['status'] == 'failed'
        assert result['error']['message'] == 'MODEL_REQUEST_TIMEOUT'
        assert ws.store.analysis(result['operation']) is None
        assert len(requests) == 1 and canceled == [True]
        assert [e['kind'] for e in ws.store.events() if e['kind'].startswith('vision_')] == ['vision_request', 'vision_error']
    finally:
        await client.close()


async def test_deadline_also_bounds_sdk_retry_backoff(tmp_path, monkeypatch):
    monkeypatch.setattr('report_agent.deep_models.MODEL_REQUEST_DEADLINE_SECONDS', .03)
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    for suffix, value in [('MODEL', 'glm-5.3'), ('BASE_URL', 'https://offline.invalid/v1'), ('API_KEY', 'offline-key')]:
        monkeypatch.setenv('REPORT_COORDINATOR_' + suffix, value)
    model = configured_model(Store(tmp_path), 'coordinator')
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(503, json={'error': {'message': 'offline'}})

    model.http_async_client._transport = httpx.MockTransport(handle)
    monkeypatch.setattr(model.root_async_client, '_calculate_retry_timeout', lambda *args: 1)
    try:
        with pytest.raises(TimeoutError):
            await model.ainvoke('offline')
        assert len(requests) == 1
    finally:
        await model.root_async_client.close()
        model.root_client.close()
