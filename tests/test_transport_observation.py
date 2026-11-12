import asyncio
import json

import httpx
import openai
import pytest

from report_agent.deep_models import configured_model, model_async_client, model_sync_client
from report_agent.errors import ModelRequestDeadlineExceeded
from report_agent.request_budget import RequestBudgetExceeded
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, token_budget


def phases(store):
    return [e['data'] for e in store.events() if e['kind'] == 'model_http_phase']


def body(model='deepseek-v4.1-flash-1017', usage=None):
    return {'id': 'offline-response', 'object': 'chat.completion', 'created': 1,
            'model': model, 'choices': [{'index': 0, 'finish_reason': 'stop',
             'message': {'role': 'assistant', 'content': 'unchanged result'}}],
            'usage': usage if usage is not None else {'prompt_tokens': 6, 'completion_tokens': 4, 'total_tokens': 10}}


def setup_model(tmp_path, monkeypatch, role='text_tool', endpoint='https://offline.invalid/v1'):
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_REASONING_EFFORT', 'max')
    for suffix, value in [('MODEL', 'deepseek-v4.1-flash-1017'), ('BASE_URL', endpoint), ('API_KEY', 'test-secret')]:
        monkeypatch.setenv('REPORT_' + role.upper() + '_' + suffix, value)
    store = Store(tmp_path / role)
    return store, configured_model(store, role)


async def use_mock(model, responder):
    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(responder)
    model.http_async_client._mounts = {}


async def close(model):
    await model.root_async_client.close()
    model.root_client.close()


@pytest.mark.parametrize('kind', ['model_http_attempt_response', 'model_http_attempt_started',
                                 'model_transport_retry_policy', 'model_http_phase'])
async def test_old_and_new_observer_io_failure_never_resends_received_response(tmp_path, monkeypatch, kind):
    # Exercise the actual SDK retry owner, not just a helper's return value.
    original = Store.event
    def broken(self, event, data):
        if event == kind:
            raise OSError('private synthetic diagnostic failure')
        return original(self, event, data)
    monkeypatch.setattr(Store, 'event', broken)
    store, model = setup_model(tmp_path, monkeypatch)
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=body())
    await use_mock(model, respond)
    monkeypatch.setattr(model.root_async_client, '_calculate_retry_timeout', lambda *args: 0)
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    try:
        with token_budget(budget):
            assert (await model.ainvoke('offline')).content == 'unchanged result'
        assert len(seen) == 1
        assert budget.snapshot()['recorded_tokens'] == 10
        assert budget.snapshot()['attempt_states'] == {'settled': 1}
    finally:
        await close(model)


@pytest.mark.parametrize('failure', ['get', 'set', 'event'])
async def test_strict_wire_observation_io_never_changes_sdk_dispatch(tmp_path, monkeypatch, failure):
    from report_agent.deep_models import strict_wire_audit
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    store = Store(tmp_path / 'store')
    def broken(*args, **kwargs):
        raise OSError('private synthetic observation failure')
    monkeypatch.setattr(store, failure, broken)
    transport = model_async_client(store, 'text_tool', [strict_wire_audit(store, 'text_tool')])
    await transport._transport.aclose()
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=body())
    transport._transport = httpx.MockTransport(respond)
    transport._mounts = {}
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    async with openai.AsyncOpenAI(api_key='synthetic', base_url='https://offline.invalid/v1',
                                 http_client=transport, max_retries=5) as client:
        monkeypatch.setattr(client, '_calculate_retry_timeout', lambda *args: 0)
        with token_budget(budget):
            result = await client.chat.completions.create(model='deepseek-v4.1-flash-1017',
                messages=[{'role': 'user', 'content': 'offline'}])
    assert result.choices[0].message.content == 'unchanged result'
    assert len(seen) == 1 and budget.snapshot()['attempt_states'] == {'settled': 1}


def test_observation_boundary_propagates_cancellation():
    from report_agent.transport_observation import observe_safely
    def cancelled():
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        observe_safely(cancelled)


@pytest.mark.parametrize('headers_arrive', [False, True])
@pytest.mark.parametrize('cancel_external', [False, True])
async def test_actual_adapter_stall_phase_and_reservation(tmp_path, monkeypatch, headers_arrive, cancel_external):
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', 0.25)
    store, model = setup_model(tmp_path, monkeypatch)
    entered = asyncio.Event()
    requests = []

    class StalledBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b''

    async def respond(request):
        requests.append(request)
        if headers_arrive:
            return httpx.Response(200, headers={'x-request-id': 'req-123', 'set-cookie': 'secret-cookie'}, stream=StalledBody())
        entered.set()
        await asyncio.Event().wait()

    await use_mock(model, respond)
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    try:
        with token_budget(budget):
            task = asyncio.create_task(model.ainvoke('private synthetic prompt'))
            if cancel_external:
                await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(ModelRequestDeadlineExceeded):
                    await task
        rows = phases(store)
        assert [r['phase'] for r in rows] == ['request_started'] + (['headers_received'] if headers_arrive else [])
        assert len(requests) == 1
        assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == 40
        assert budget.snapshot()['recorded_tokens'] == 0
        assert len({r['attempt_id'] for r in rows}) == 1
        assert all(r['attempt_id'] == r['token_reservation_id'] for r in rows)
        assert all(r['elapsed_seconds'] >= 0 for r in rows)
        encoded = json.dumps(rows)
        assert 'secret-cookie' not in encoded and 'test-secret' not in encoded and 'private synthetic' not in encoded
    finally:
        await close(model)


async def test_complete_response_preserves_result_exact_settlement_and_phase_order(tmp_path, monkeypatch):
    store, model = setup_model(tmp_path, monkeypatch)
    await use_mock(model, lambda r: httpx.Response(200, json=body(), headers={'x-request-id': 'req-ok'}))
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    original = budget.settle
    settled = []

    def counted(*args):
        settled.append(args)
        return original(*args)

    monkeypatch.setattr(budget, 'settle', counted)
    try:
        with token_budget(budget):
            result = await model.ainvoke('offline')
        assert result.content == 'unchanged result'
        rows = phases(store)
        assert [r['phase'] for r in rows] == ['request_started', 'headers_received', 'body_read_completed', 'usage_accounted']
        assert len(settled) == 1 and rows[-1]['recorded_tokens'] == 10
        assert rows[-1]['accounting_state'] == 'settled'
        assert budget.snapshot()['recorded_tokens'] == 10 and budget.snapshot()['reserved_or_unknown_upper_bounds'] == 0
        assert len({r['attempt_id'] for r in rows}) == 1
        assert rows[1]['provider_request_id'] == 'req-ok'
        old = [e for e in store.events() if e['kind'] == 'model_http_attempt_response']
        assert len(old) == 1 and old[0]['sequence'] > [e for e in store.events() if e['kind'] == 'model_http_phase'][-1]['sequence']
    finally:
        await close(model)


async def test_sdk_attempts_have_distinct_budget_ids_same_body_hash(tmp_path, monkeypatch):
    store, model = setup_model(tmp_path, monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503, json={'error': {'message': 'offline'}}, headers={'x-request-id': 'req-fail'}) if len(requests) == 1 else httpx.Response(200, json=body(), headers={'x-request-id': 'req-ok'})

    await use_mock(model, respond)
    monkeypatch.setattr(model.root_async_client, '_calculate_retry_timeout', lambda *args: 0)
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    try:
        with token_budget(budget):
            await model.ainvoke('offline')
        starts = [r for r in phases(store) if r['phase'] == 'request_started']
        assert len(requests) == len(starts) == 2
        assert [r['retry_index'] for r in starts] == [0, 1]
        assert len({r['body_sha256'] for r in starts}) == 1
        assert len({r['attempt_id'] for r in starts}) == 2
        with budget.connect() as db:
            actual_ids = {r[0] for r in db.execute('SELECT id FROM attempts')}
        assert {r['token_reservation_id'] for r in starts} == actual_ids
        accounted = [r for r in phases(store) if r['phase'] == 'usage_accounted']
        assert [(r['accounting_state'], r['recorded_tokens']) for r in accounted] == [('unknown', None), ('settled', 10)]
        assert budget.snapshot()['recorded_tokens'] == 10 and budget.snapshot()['reserved_or_unknown_upper_bounds'] == 40
    finally:
        await close(model)


@pytest.mark.parametrize('failure', ['missing_usage', 'bad_usage', 'settlement', 'observer'])
async def test_diagnostic_or_accounting_edge_does_not_retry(tmp_path, monkeypatch, failure, caplog):
    store, model = setup_model(tmp_path, monkeypatch)
    requests = []
    payload = body()
    if failure == 'missing_usage':
        payload.pop('usage')
    if failure == 'bad_usage':
        payload['usage'] = {'total_tokens': 0, 'prompt_tokens': 2, 'completion_tokens': 1}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    await use_mock(model, respond)
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    if failure == 'settlement':
        def fail(*args):
            raise OSError('synthetic ledger issue')
        monkeypatch.setattr(budget, 'settle', fail)
    if failure == 'observer':
        original = store.event
        def event(kind, data):
            if kind == 'model_http_phase':
                raise OSError('synthetic private observation issue')
            return original(kind, data)
        monkeypatch.setattr(store, 'event', event)
    try:
        with token_budget(budget):
            if failure == 'settlement':
                with pytest.raises(RequestBudgetExceeded, match='TOKEN_LEDGER_SETTLEMENT_FAILED'):
                    await model.ainvoke('offline')
            else:
                assert (await model.ainvoke('offline')).content == 'unchanged result'
        assert len(requests) == 1
        assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == (0 if failure == 'observer' else 40)
        rows = phases(store)
        if failure in {'missing_usage', 'bad_usage'}:
            assert rows[-1]['accounting_state'] == 'unknown' and rows[-1]['recorded_tokens'] is None
        if failure == 'settlement':
            assert rows[-1]['phase'] == 'body_read_completed'
        if failure == 'observer':
            assert budget.snapshot()['recorded_tokens'] == 10
            assert 'OSError' in caplog.text and 'synthetic private' not in caplog.text
    finally:
        await close(model)


@pytest.mark.parametrize('sync', [False, True])
async def test_without_budget_and_without_sdk_retries_still_observes(tmp_path, monkeypatch, sync):
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    store = Store(tmp_path)
    if sync:
        client = model_sync_client(store, 'text_tool')
        client._transport.close()
        client._transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body()))
        client._mounts = {}
        with client:
            response = client.post('https://offline.invalid/v1', json={'model': 'offline'})
    else:
        client = model_async_client(store, 'text_tool')
        await client._transport.aclose()
        client._transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body()))
        client._mounts = {}
        async with client:
            response = await client.post('https://offline.invalid/v1', json={'model': 'offline'})
    assert response.json()['id'] == 'offline-response'
    rows = phases(store)
    assert [r['phase'] for r in rows] == ['request_started', 'headers_received', 'body_read_completed']
    assert len({r['attempt_id'] for r in rows}) == 1
    assert all(r['token_reservation_id'] is None for r in rows)


@pytest.mark.parametrize('stall', [False, True])
def test_sync_budget_and_body_stall(tmp_path, monkeypatch, stall):
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    store = Store(tmp_path / 'store')
    client = model_sync_client(store, 'text_tool')

    class FailingBody(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadTimeout('offline body timeout')
            yield b''

    client._transport.close()
    client._transport = httpx.MockTransport(lambda r: httpx.Response(200, stream=FailingBody()) if stall else httpx.Response(200, json=body()))
    client._mounts = {}
    budget = TokenBudget(tmp_path / 'budget.db', 100, {'deepseek-v4.1-flash-1017': 40})
    with client, token_budget(budget):
        if stall:
            with pytest.raises(httpx.ReadTimeout):
                client.post('https://offline.invalid/v1', json={'model': 'deepseek-v4.1-flash-1017'})
        else:
            assert client.post('https://offline.invalid/v1', json={'model': 'deepseek-v4.1-flash-1017'}).json()['id'] == 'offline-response'
    assert [r['phase'] for r in phases(store)] == ['request_started', 'headers_received'] + ([] if stall else ['body_read_completed', 'usage_accounted'])
    assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == (40 if stall else 0)
