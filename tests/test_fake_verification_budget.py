"""Synthetic transport and actual SQLite transactions, with no service or real ledger."""
from concurrent.futures import ThreadPoolExecutor
import threading

import httpx
import pytest

from report_agent.fake_verification_budget import FakeVerificationBudget, fake_verification_budget
from report_agent.request_budget import RequestBudgetExceeded, account_request_sync
from report_agent.token_budget import account_response_sync

MODEL = 'synthetic'
BOUND = 1_179_648


@pytest.fixture
def grant(tmp_path):
    FakeVerificationBudget.initialize(tmp_path, {MODEL: BOUND})
    return tmp_path


def dispatch(grant, run, respond):
    with fake_verification_budget(grant, run):
        with httpx.Client(transport=httpx.MockTransport(respond), event_hooks={
            'request': [account_request_sync], 'response': [account_response_sync],
        }) as client:
            return client.post('https://synthetic.invalid/v1/test', json={'model': MODEL})


def spent(grant, run, usage):
    return dispatch(grant, run, lambda _: httpx.Response(200, json={'usage': {'total_tokens': usage}}))


def must_not_send(_):
    pytest.fail('local refusal reached transport')


def test_run_and_campaign_caps_survive_reopening_and_exact_boundary(grant):
    for run in ('one', 'two'):
        for usage in (BOUND, BOUND, 3_700_000 - 3 * BOUND, BOUND):
            spent(grant, run, usage)
        assert FakeVerificationBudget(grant, run).run_snapshot()['settled'] == 3_700_000
        with pytest.raises(RequestBudgetExceeded, match='FAKE_RUN_TOKEN_LIMIT'):
            dispatch(grant, run, must_not_send)
    for usage in (BOUND, 2_600_000 - 2 * BOUND, BOUND):
        spent(grant, 'three', usage)
    assert FakeVerificationBudget(grant, 'three').snapshot()['recorded_tokens'] == 10_000_000
    with pytest.raises(RequestBudgetExceeded, match='AUTHORIZED_TOKEN_BUDGET_REACHED'):
        dispatch(grant, 'four', must_not_send)


def test_single_request_across_concurrent_run_owners(grant):
    entered = threading.Event()
    release = threading.Event()

    def waiting(_):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json={'usage': {'total_tokens': 2}})

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(dispatch, grant, 'a', waiting)
        try:
            assert entered.wait(5)
            with pytest.raises(RequestBudgetExceeded, match='FAKE_REQUEST_PENDING'):
                dispatch(grant, 'b', must_not_send)
        finally:
            release.set()
        pending.result()
    spent(grant, 'b', 3)
    assert FakeVerificationBudget(grant, 'b').snapshot()['recorded_tokens'] == 5


@pytest.mark.parametrize('no_response', [False, True])
def test_unresolved_outcome_blocks_future_runs_and_preserves_hold(grant, no_response):
    def fail(_):
        if no_response:
            raise httpx.ReadError('synthetic interruption')
        return httpx.Response(200, json={})

    if no_response:
        with pytest.raises(httpx.ReadError):
            dispatch(grant, 'first', fail)
    else:
        dispatch(grant, 'first', fail)
    with pytest.raises(RequestBudgetExceeded, match='FAKE_REQUEST_PENDING'):
        dispatch(grant, 'second', must_not_send)
    snap = FakeVerificationBudget(grant, 'first').run_snapshot()
    assert snap == {'maximum_tokens': 3_700_000, 'settled': 0, 'held': BOUND}


def test_missing_or_already_initialized_grant_is_never_reset(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        FakeVerificationBudget(tmp_path, 'run')
    assert not list(tmp_path.iterdir())
    FakeVerificationBudget.initialize(tmp_path, {MODEL: BOUND})
    spent(tmp_path, 'run', 1000)
    with pytest.raises(FileExistsError):
        FakeVerificationBudget.initialize(tmp_path, {MODEL: BOUND})
    assert FakeVerificationBudget(tmp_path, 'run').run_snapshot()['settled'] == 1000

@pytest.mark.asyncio
async def test_configured_writer_and_vision_sdk_use_the_same_fake_grant(tmp_path, monkeypatch):
    from report_agent.deep_models import configured_model, configured_vision_client
    from report_agent.store import Store
    from test_connect_retry_policy import AsyncTLSBackend, close_model

    # Use production clients and admission hooks, replacing the TCP backend only.
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '2')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    monkeypatch.setenv('REPORT_REASONING_EFFORT', 'high')
    models = {'writer': 'glm-5.3', 'vision': 'deepseek-v4.1-flash-1017'}
    for role, model_id in models.items():
        for suffix, value in {'MODEL': model_id, 'BASE_URL': 'https://offline.invalid/v1',
                              'API_KEY': 'synthetic'}.items():
            monkeypatch.setenv(f'REPORT_{role.upper()}_{suffix}', value)
    pool = tmp_path / 'campaign'
    FakeVerificationBudget.initialize(pool, {model_id: 2_000_000 for model_id in models.values()})
    writer = configured_model(Store(tmp_path / 'workspace'), 'writer')
    vision = configured_vision_client()
    writer_wire, vision_wire = AsyncTLSBackend(), AsyncTLSBackend()
    writer.http_async_client._transport._pool._network_backend = writer_wire
    vision._client._transport._pool._network_backend = vision_wire
    try:
        with fake_verification_budget(pool, 'same') as budget:
            await writer.ainvoke('synthetic scan test')
            await vision.chat.completions.create(model=models['vision'],
                messages=[{'role': 'user', 'content': 'synthetic page'}], max_tokens=50)
            assert budget.run_snapshot()['settled'] == 20
        assert writer_wire.connections == vision_wire.connections == 1
    finally:
        await close_model(writer)
        await vision.close()
