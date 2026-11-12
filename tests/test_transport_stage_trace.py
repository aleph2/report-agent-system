"""Metadata-only diagnostics on actual SDK/native localhost and controlled failure paths."""
import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from report_agent.deep_models import model_async_client, model_sync_client, configured_vision_client
from report_agent.errors import ModelRequestDeadlineExceeded
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.transport_observation import observation_scope, observe_model_boundary
from test_transport_observation import setup_model, close, body, use_mock
from test_model_request_timeout import deadline_at_stage


def traces(store):
    return [r['data'] for r in store.events() if r['kind'] == 'model_transport_trace']


@asynccontextmanager
async def local_server(mode):
    release, entered = asyncio.Event(), asyncio.Event()
    tasks, received = set(), []

    async def handle(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            headers = await reader.readuntil(b'\r\n\r\n')
            length = next(int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n')
                          if line.lower().startswith(b'content-length:'))
            received.append(await reader.readexactly(length))
            entered.set()
            payload = json.dumps(body()).encode()
            if mode == 'headers':
                await release.wait()
            else:
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '
                             + str(len(payload)).encode() + b'\r\nConnection: close\r\n\r\n')
                writer.write(payload if mode == 'success' else payload[:1])
                await writer.drain()
                if mode == 'body':
                    await release.wait()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    try:
        yield f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1', entered, received
    finally:
        release.set()
        server.close()
        await server.wait_closed()
        await asyncio.gather(*list(tasks), return_exceptions=True)


@pytest.mark.parametrize('mode,external_cancel', [('success', False), ('headers', False),
                                               ('body', False), ('headers', True), ('body', True)])
async def test_native_localhost_sdk_phases_and_single_flush(tmp_path, monkeypatch, mode, external_cancel):
    # Only the stall cases test deadline expiry; success/cancellation need scheduling headroom.
    deadline = 10.0 if mode == 'success' or external_cancel else .25
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', deadline)
    expire = None if mode == 'success' or external_cancel else deadline_at_stage(monkeypatch, .25)
    async with local_server(mode) as (url, entered, received):
        store, model = setup_model(tmp_path, monkeypatch, endpoint=url)
        model.http_async_client._mounts = {}  # Native direct localhost, no environment proxy.
        body_entered = asyncio.Event()
        if expire or (mode == 'body' and external_cancel):
            # Wait for the *client* to enter body reading, not only server writing.
            hook_index = next(i for i, h in enumerate(model.http_async_client.event_hooks['request']) if h.__name__ == 'observe_start')
            original_hook = model.http_async_client.event_hooks['request'][hook_index]
            async def observe_start(request):
                await original_hook(request)
                previous = request.extensions['trace']
                async def trace(event, info):
                    await previous(event, info)
                    if event == 'http11.receive_response_body.started':
                        body_entered.set()
                    if expire and event == f'http11.receive_response_{mode}.started':
                        await asyncio.wait_for(entered.wait(), 2)
                        expire()
                request.extensions['trace'] = trace
            model.http_async_client.event_hooks['request'][hook_index] = observe_start
        budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
        try:
            with token_budget(budget):
                task = asyncio.create_task(model.ainvoke('synthetic-private-input'))
                if external_cancel:
                    await asyncio.wait_for(entered.wait(), 2)
                    if mode == 'body':
                        await asyncio.wait_for(body_entered.wait(), 2)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                elif mode == 'success':
                    assert (await task).content == 'unchanged result'
                else:
                    with pytest.raises(ModelRequestDeadlineExceeded) as failure:
                        await task
                    assert failure.value.deadline_seconds == .25
            rows = traces(store)
            assert len(received) == len(rows) == 1
            row = rows[0]
            assert row['boundary'] == 'model_call'
            assert row['outcome'] == ('cancelled' if external_cancel else
                                      'returned' if mode == 'success' else 'local_deadline_exceeded')
            names = [e['phase'] for e in row['events']]
            assert 'connection.connect_tcp.complete' in names
            assert 'http11.send_request_body.complete' in names
            assert 'http11.receive_response_headers.started' in names
            if mode == 'success':
                assert 'http11.receive_response_body.complete' in names
                assert row['last_failure_event'] is None
                assert [m['phase'] for m in row['model_markers']] == [
                    'payload_started', 'payload_completed', 'result_parse_started', 'result_parse_completed']
                assert budget.snapshot()['recorded_tokens'] == 10
            else:
                assert row['last_failure_event'] == f'http11.receive_response_{mode}.failed'
                assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == 40
                assert budget.snapshot()['recorded_tokens'] == 0
            wire = json.loads(received[0])
            assert wire['messages'] == [{'content': 'synthetic-private-input', 'role': 'user'}]
            assert wire['stream'] is False
            encoded = json.dumps(rows)
            for secret in ('synthetic-private-input', 'test-secret', '127.0.0.1', 'unchanged result'):
                assert secret not in encoded
        finally:
            await close(model)


@pytest.mark.parametrize('sync', [False, True])
async def test_direct_send_fallback_and_existing_native_callback(tmp_path, monkeypatch, sync):
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    store = Store(tmp_path)
    seen = []
    if sync:
        client = model_sync_client(store, 'text_tool')
        def previous(event, info):
            seen.append(event)
        def respond(request):
            request.extensions['trace']('connection.start_tls.started', {'host': 'PRIVATE'})
            return httpx.Response(200, json=body())
        client._transport.close()
        client._transport = httpx.MockTransport(respond)
        with client:
            client.send(client.build_request('POST', 'https://offline.invalid', json={'model': 'offline'},
                                            extensions={'trace': previous}))
    else:
        client = model_async_client(store, 'text_tool')
        async def previous(event, info):
            seen.append(event)
        async def respond(request):
            await request.extensions['trace']('connection.start_tls.started', {'host': 'PRIVATE'})
            return httpx.Response(200, json=body())
        await client._transport.aclose()
        client._transport = httpx.MockTransport(respond)
        client._mounts = {}
        async with client:
            await client.send(client.build_request('POST', 'https://offline.invalid', json={'model': 'offline'},
                                                   extensions={'trace': previous}))
    assert seen == ['connection.start_tls.started']
    assert len(traces(store)) == 1
    assert traces(store)[0]['boundary'] == 'httpx_send'
    assert traces(store)[0]['last_native_event'] == seen[0]
    assert 'PRIVATE' not in json.dumps(traces(store))


@pytest.mark.parametrize('failure', [ValueError('PRIVATE'), asyncio.CancelledError()])
async def test_existing_callback_failure_is_preserved_not_suppressed(tmp_path, monkeypatch, failure):
    store, model = setup_model(tmp_path, monkeypatch)
    async def previous(event, info):
        raise failure
    async def prepare(request):
        request.extensions['trace'] = previous
    model.http_async_client.event_hooks['request'].insert(1, prepare)
    async def respond(request):
        await request.extensions['trace']('http11.send_request_body.started', {})
        return httpx.Response(200, json=body())
    await use_mock(model, respond)
    try:
        with pytest.raises(type(failure)) as caught:
            # Check the HTTPX boundary itself; the SDK/LC may wrap ordinary
            # callback exceptions using their existing retry/error policies.
            await model.http_async_client.post('https://offline.invalid/v1/chat/completions', json={'model': 'deepseek-v4.1-flash-1017'})
        assert caught.value is failure
        assert len(traces(store)) == 1
        assert 'PRIVATE' not in json.dumps(traces(store))
    finally:
        await close(model)


async def test_new_observation_failures_do_not_alter_result_or_settlement(tmp_path, monkeypatch):
    store, model = setup_model(tmp_path, monkeypatch)
    calls = []
    def respond(request):
        calls.append(True)
        return httpx.Response(200, json=body())
    await use_mock(model, respond)
    original = store.event
    def broken(kind, data):
        if kind == 'model_transport_trace':
            raise OSError('PRIVATE')
        return original(kind, data)
    monkeypatch.setattr(store, 'event', broken)
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    try:
        with token_budget(budget):
            assert (await model.ainvoke('offline')).content == 'unchanged result'
        assert calls == [True]
        assert budget.snapshot()['attempt_states'] == {'settled': 1}
        assert budget.snapshot()['recorded_tokens'] == 10
    finally:
        await close(model)


async def test_bounded_ring_and_concurrent_scope_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    store = Store(tmp_path)
    client = model_async_client()  # Active model/vision scope supplies sink and role.
    async def respond(request):
        for _ in range(90):
            await request.extensions['trace']('http11.send_request_body.started', {'headers': 'PRIVATE'})
        await request.extensions['trace']('unrecognized.PRIVATE.started', {})
        await asyncio.sleep(0)
        return httpx.Response(200, json=body())
    await client._transport.aclose()
    client._transport = httpx.MockTransport(respond)
    client._mounts = {}
    async def call(role):
        with observation_scope(store, role):
            for _ in range(90):
                observe_model_boundary('payload_started')
            await client.post('https://offline.invalid', json={'model': 'offline'})
    async with client:
        await asyncio.gather(call('writer'), call('reviewer'))
    rows = traces(store)
    assert len(rows) == 2 and {r['role'] for r in rows} == {'writer', 'reviewer'}
    assert len({r['attempt_id'] for r in rows}) == 2
    for row in rows:
        assert len(row['events']) == len(row['model_markers']) == 64
        assert row['dropped_events'] == 29 and row['dropped_model_markers'] == 26
        assert row['buffer_truncated'] is True
        assert row['last_native_event'] == 'http11.send_request_body.started'
    assert 'PRIVATE' not in json.dumps(rows)


@pytest.mark.parametrize('reuse_request', [False, True])
async def test_scope_request_limit_reports_omission(tmp_path, monkeypatch, reuse_request):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    store = Store(tmp_path)
    client = model_async_client(store, 'text_tool')
    external = []
    async def previous(event, info):
        external.append(event)
    async def respond(request):
        await request.extensions['trace']('http11.send_request_body.complete', {})
        return httpx.Response(200, json=body())
    await client._transport.aclose()
    client._transport = httpx.MockTransport(respond)
    client._mounts = {}
    def new_request():
        return client.build_request('POST', 'https://offline.invalid', json={'model': 'offline'},
                                    extensions={'trace': previous})
    reused = new_request()
    with observation_scope(store, 'text_tool'):
        async with client:
            for _ in range(18):
                await client.send(reused if reuse_request else new_request())
    assert len(traces(store)) == 16
    assert len(external) == 18
    assert all(r['dropped_requests'] == 2 and r['buffer_truncated'] for r in traces(store))
    assert all(sum(e['phase'] == 'http11.send_request_body.complete' for e in r['events']) == 1
               for r in traces(store))


async def test_nested_model_failure_has_own_outcome_and_no_request_summary(tmp_path):
    outer, inner = Store(tmp_path / 'outer'), Store(tmp_path / 'inner')
    with observation_scope(outer, 'coordinator'):
        try:
            with observation_scope(inner, 'reviewer'):
                observe_model_boundary('payload_started')
                raise ValueError('PRIVATE')
        except ValueError:
            pass
        observe_model_boundary('payload_completed')
    one = [r['data'] for r in outer.events() if r['kind'] == 'model_transport_call']
    two = [r['data'] for r in inner.events() if r['kind'] == 'model_transport_call']
    assert len(one) == len(two) == 1
    assert one[0]['outcome'] == 'returned' and two[0]['outcome'] == 'failed'
    assert one[0]['call_id'] != two[0]['call_id']
    assert two[0]['request_count'] == 0 and two[0]['no_http_observed'] is True
    assert [m['phase'] for m in one[0]['model_markers']] == ['payload_completed']
    assert 'PRIVATE' not in json.dumps(two)


@pytest.mark.parametrize('retries', ['0', '1'])
async def test_same_public_request_does_not_chain_old_observers(tmp_path, monkeypatch, retries):
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', retries)
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    store = Store(tmp_path)
    client = model_async_client(store, 'reviewer')
    called = []
    async def previous(event, info):
        called.append(event)
    async def respond(request):
        await request.extensions['trace']('connection.connect_tcp.complete', {})
        return httpx.Response(200, json=body())
    await client._transport.aclose()
    client._transport = httpx.MockTransport(respond)
    client._mounts = {}
    request = client.build_request('POST', 'https://offline.invalid', json={'model': 'offline'},
                                   extensions={'trace': previous})
    async with client:
        for _ in range(5):
            await client.send(request)
    rows = traces(store)
    assert len(rows) == len(called) == 5
    assert len({r['call_id'] for r in rows}) == 5
    assert all(sum(e['phase'] == 'connection.connect_tcp.complete' for e in r['events']) == 1 for r in rows)
    assert all(r['dropped_events'] == 0 for r in rows)


@pytest.mark.parametrize('phase', ['connection.connect_tcp', 'connection.start_tls',
                                  'http11.send_request_body'])
async def test_controlled_stage_stalls_record_exact_last_native_phase(tmp_path, monkeypatch, phase):
    # Controlled callback signals, not claims of real TCP/TLS failure reproduction.
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', .05)
    store, model = setup_model(tmp_path, monkeypatch)
    expire = deadline_at_stage(monkeypatch, .05)
    async def respond(request):
        trace = request.extensions['trace']
        await trace(phase + '.started', {'headers': 'PRIVATE'})
        expire()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as error:
            await trace(phase + '.failed', {'exception': error})
            raise
    await use_mock(model, respond)
    try:
        with pytest.raises(ModelRequestDeadlineExceeded):
            await model.ainvoke('offline')
        row, = traces(store)
        assert row['last_native_event'] == row['last_failure_event'] == phase + '.failed'
        assert row['outcome'] == 'local_deadline_exceeded'
        assert row['events'][-1]['exception_type'] == 'CancelledError'
        assert 'PRIVATE' not in json.dumps(row)
    finally:
        await close(model)


async def test_native_diagnostic_callback_fault_is_best_effort(tmp_path, monkeypatch):
    from report_agent import transport_observation as observation
    store, model = setup_model(tmp_path, monkeypatch)
    def broken(*args):
        raise ValueError('PRIVATE')
    monkeypatch.setattr(observation._RequestTrace, 'native', broken)
    async def respond(request):
        await request.extensions['trace']('connection.connect_tcp.started', {})
        return httpx.Response(200, json=body())
    await use_mock(model, respond)
    try:
        assert (await model.ainvoke('offline')).content == 'unchanged result'
        row, = traces(store)
        assert row['last_native_event'] is None
    finally:
        await close(model)


async def test_direct_vision_timeout_classifies_at_model_boundary(tmp_path, monkeypatch):
    from report_agent.vision import observe_source_image
    from test_document_tools import workspace
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', .05)
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    for suffix, value in [('MODEL', 'glm-5.3'), ('BASE_URL', 'https://offline.invalid/v1'),
                          ('API_KEY', 'synthetic-secret')]:
        monkeypatch.setenv('REPORT_VISION_' + suffix, value)
    client = configured_vision_client()
    ws = workspace(tmp_path)
    expire = deadline_at_stage(monkeypatch, .05)
    async def respond(request):
        expire()
        await asyncio.Event().wait()
    await client._client._transport.aclose()
    client._client._transport = httpx.MockTransport(respond)
    client._client._mounts = {}
    try:
        result = await observe_source_image(ws, 'original', 'synthetic-private-question', client=client)
        assert result['status'] == 'failed'
        row, = traces(ws.store)
        assert row['boundary'] == 'model_call' and row['outcome'] == 'local_deadline_exceeded'
        assert row['exception_type'] == 'ModelRequestDeadlineExceeded'
        assert row['last_native_event'] is None  # MockTransport has no native events.
        assert 'synthetic-private-question' not in json.dumps(row)
    finally:
        await client.close()


async def test_actual_adapter_payload_failure_emits_zero_http_summary(tmp_path, monkeypatch):
    from langchain_openai import ChatOpenAI
    store, model = setup_model(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise ValueError('PRIVATE')
    monkeypatch.setattr(ChatOpenAI, '_get_request_payload', fail)
    try:
        with pytest.raises(ValueError):
            await model.ainvoke('offline')
        rows = [r['data'] for r in store.events() if r['kind'] == 'model_transport_call']
        row, = rows
        assert row['boundary'] == 'model_call' and row['outcome'] == 'failed'
        assert row['request_count'] == 0 and row['no_http_observed'] is True
        assert [m['phase'] for m in row['model_markers']] == ['payload_started']
        assert 'PRIVATE' not in json.dumps(row)
    finally:
        await close(model)


async def test_sdk_physical_attempts_link_to_one_logical_call(tmp_path, monkeypatch):
    store, model = setup_model(tmp_path, monkeypatch)
    seen = []
    def respond(request):
        seen.append(request)
        return (httpx.Response(503, json={'error': {'message': 'offline'}}) if len(seen) == 1
                else httpx.Response(200, json=body()))
    await use_mock(model, respond)
    monkeypatch.setattr(model.root_async_client, '_calculate_retry_timeout', lambda *args: 0)
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    try:
        with token_budget(budget):
            assert (await model.ainvoke('offline')).content == 'unchanged result'
        rows = traces(store)
        assert len(rows) == len(seen) == 2
        assert len({r['call_id'] for r in rows}) == 1
        assert len({r['attempt_id'] for r in rows}) == 2
        assert [r['request_index'] for r in rows] == [0, 1]
        assert [r['retry_index'] for r in rows] == [0, 1]
        assert budget.snapshot()['attempt_states'] == {'unknown': 1, 'settled': 1}
    finally:
        await close(model)
