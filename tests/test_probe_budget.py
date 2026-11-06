"""Offline request-bound and per-slope probe admission contracts."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import httpx
import pytest

from report_agent.token_budget import (
    RequestBound, TokenBudget, account_response, account_response_sync,
    current_model_token_bound, request_token_bound, token_budget,
)
from report_agent.probe_budget import ProbeBudget
from report_agent.request_budget import (
    RequestBudgetExceeded, account_request, account_request_sync,
    current_budget_observation, request_reservation_observer,
)

MODEL = 'glm-5.3'
URL = 'https://synthetic.invalid/v1/chat/completions'
BOUND = RequestBound(MODEL, sha256(URL.encode()).hexdigest(), 200_000, 100_000, 'a' * 64)


def finance(budget):
    with budget.connect() as db:
        return {'auth': list(db.execute('SELECT maximum,bounds FROM authorization').fetchone()),
                'rows': [list(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]}


def setup_probe(tmp_path, *, prior=0):
    budget = TokenBudget(tmp_path / 'tokens.db', 100_000_000, {MODEL: 2_000_000})
    original = finance(budget)
    hold_id = budget.reserve(MODEL)
    hold = next(r for r in finance(budget)['rows'] if r[0] == hold_id)
    if prior:
        identity = budget.reserve(MODEL)
        budget.settle(identity, {'total_tokens': prior})
    stage = finance(budget)
    guard = ProbeBudget(lambda: finance(budget), original, stage,
                        preserved_hold=hold, writer_model=MODEL)
    return budget, original, stage, hold, guard


def payload(**changes):
    return {'model': MODEL, 'max_tokens': 100_000, 'n': 1, 'stream': False,
            'messages': [{'role': 'user', 'content': 'synthetic'}], **changes}


def send(budget, guard, body=None, *, url=URL, usage=10, bound=BOUND):
    sent = []
    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={'usage': {'total_tokens': usage}} if usage is not None else {})
    with token_budget(budget), request_token_bound(bound), request_reservation_observer(guard.check, observation=guard.observation):
        with httpx.Client(transport=httpx.MockTransport(respond),
                          event_hooks={'request': [account_request_sync], 'response': [account_response_sync]}) as client:
            try:
                client.post(url, json=payload() if body is None else body)
            except RequestBudgetExceeded:
                assert not sent, 'Local guard rejection must never reach transport'
                raise
    return sent


def test_exact_cap_is_allowed_and_one_more_request_is_cancelled_without_dispatch(tmp_path):
    b, original, stage, hold, guard = setup_probe(tmp_path)
    for _ in range(4):
        send(b, guard, usage=300_000)
    assert len(send(b, guard, usage=300_000)) == 1
    assert guard.check() == (1_500_000, 0)
    before = finance(b)
    with pytest.raises(RequestBudgetExceeded, match='PROBE_TOKEN_LIMIT'):
        send(b, guard)
    after = finance(b)
    added = [r for r in after['rows'] if r[0] not in {r[0] for r in before['rows']}]
    assert len(added) == 1 and added[0][3:5] == [0, 'known_not_sent']
    assert next(r for r in after['rows'] if r[0] == hold[0]) == hold
    assert after['auth'] == original['auth'] == stage['auth']
    assert b.model_bounds == {MODEL: 2_000_000}
    assert guard.observation()['remaining_for_new_reservations'] == 0


@pytest.mark.parametrize('body,url', [
    (payload(model='other'), URL),
    (payload(), URL + '?different=1'),
    (payload(max_tokens=100_001), URL),
    (payload(max_tokens=0), URL),
    (payload(max_tokens=True), URL),
    (payload(max_completion_tokens=100_001), URL),
    ({k:v for k,v in payload().items() if k != 'max_tokens'}, URL),
    (payload(n=2), URL),
    (payload(n=True), URL),
    (payload(stream=True), URL),
    (payload(messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://synthetic.invalid/image'}}]}]), URL),
    (payload(messages=[{'role':'user','content':[{'type':'input_audio','input_audio':{'data':'test'}}]}]), URL),
    (payload(messages=[{'role':'user','content':'text', 'image_url':'https://synthetic.invalid/image'}]), URL),
])
def test_wrong_wire_bound_rejected_before_finance_or_transport(tmp_path, body, url):
    b, _, stage, _, guard = setup_probe(tmp_path)
    with pytest.raises(RequestBudgetExceeded):
        send(b, guard, body, url=url)
    assert finance(b) == stage


def test_unknown_is_retained_and_blocks_further_http(tmp_path):
    b, _, _, hold, guard = setup_probe(tmp_path)
    send(b, guard, usage=None)
    before = finance(b)
    unknown = next(r for r in before['rows'] if r[4] == 'unknown')
    with pytest.raises(RequestBudgetExceeded, match='UNRESOLVED'):
        send(b, guard)
    now = finance(b)
    assert next(r for r in now['rows'] if r[0] == unknown[0]) == unknown
    assert next(r for r in now['rows'] if r[0] == hold[0]) == hold
    assert sum(r[4] == 'known_not_sent' for r in now['rows']) == 1


def test_scoped_recovery_bound_and_nested_observers_preserve_outer_limit(tmp_path):
    b, _, _, _, guard = setup_probe(tmp_path)
    with token_budget(b):
        assert current_model_token_bound(MODEL) == 2_000_000
        with request_token_bound(BOUND), request_reservation_observer(guard.check, observation=guard.observation):
            assert current_model_token_bound(MODEL) == 300_000
            with request_token_bound(BOUND), request_reservation_observer(lambda: None):
                assert current_model_token_bound(MODEL) == 300_000
                view = current_budget_observation()['host_run_limits'][0]
                assert view['maximum_tokens'] == 1_500_000
                assert view['model_reservation_bounds'] == {MODEL: 300_000}
                assert view['status'] == 'observed'
            with pytest.raises(RequestBudgetExceeded):
                with request_token_bound(replace(BOUND, input_limit=200_001)):
                    pass
            identity = b.reserve(MODEL)
            assert next(r for r in finance(b)['rows'] if r[0] == identity)[2] == 2_000_000
            b.before_send_cancelled(identity)
        assert current_model_token_bound(MODEL) == 2_000_000
    assert current_model_token_bound(MODEL) is None


def test_async_dispatch_uses_same_verified_bound(tmp_path):
    b, _, _, _, guard = setup_probe(tmp_path)
    async def run():
        sent = []
        def respond(request):
            sent.append(request)
            return httpx.Response(200, json={'usage': {'total_tokens': 20}})
        with token_budget(b), request_token_bound(BOUND), request_reservation_observer(guard.check):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond),
                    event_hooks={'request':[account_request], 'response':[account_response]}) as client:
                await client.post(URL, json=payload(max_completion_tokens=50_000))
        assert len(sent) == 1
    asyncio.run(run())
    assert guard.check() == (20, 0)


def test_overall_twenty_million_cap_counts_preserved_hold(tmp_path):
    b, original, stage, hold, guard = setup_probe(tmp_path)
    # Prior cost already in the overall scope, outside this slope's stage.
    for _ in range(9):
        identity = b.reserve(MODEL)
        b.settle(identity, {'total_tokens': 2_000_000})
    stage = finance(b)
    guard = ProbeBudget(lambda: finance(b), original, stage, preserved_hold=hold, writer_model=MODEL)
    with pytest.raises(RequestBudgetExceeded, match='OVERALL'):
        send(b, guard)
    now = finance(b)
    assert all(r in now['rows'] for r in stage['rows'])
    assert sum(r[4] == 'known_not_sent' for r in now['rows']) == 1
    assert guard.check() == (0, 0)


@pytest.mark.parametrize('mutation', ['auth', 'hold', 'old', 'other_model', 'violation'])
def test_guard_rejects_baseline_or_finance_drift(tmp_path, mutation):
    b, original, stage, hold, guard = setup_probe(tmp_path)
    now = deepcopy(stage)
    if mutation == 'auth':
        now['auth'][0] += 1
    elif mutation in ('hold', 'old'):
        now['rows'][0][4] = 'known_not_sent'
    else:
        now['rows'].append(['new', 'other' if mutation == 'other_model' else MODEL, 300_000,
                            300_001 if mutation == 'violation' else 0,
                            'bound_violation' if mutation == 'violation' else 'settled', None, None, 'test'])
    guard.finance = lambda: now
    with pytest.raises(RequestBudgetExceeded):
        guard.check()


@pytest.mark.parametrize('changes', [
    {'input_limit': 0}, {'output_limit': True}, {'request_url_sha256': 'bad'},
    {'proof_sha256': ''}, {'model': ''},
])
def test_bound_requires_explicit_immutable_proof_fields(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(BOUND, **changes)


def test_scoped_bound_cannot_exceed_registered_authoritative_bound(tmp_path):
    b, _, stage, _, guard = setup_probe(tmp_path)
    with pytest.raises(RequestBudgetExceeded):
        send(b, guard, bound=replace(BOUND, input_limit=2_000_000))
    assert finance(b) == stage



def test_documented_ceiling_accepts_existing_output_without_prompt_estimates(tmp_path):
    b, _, _, _, guard = setup_probe(tmp_path)
    bound = replace(BOUND, input_limit=1_048_576, output_limit=131_072)
    assert len(send(b, guard, payload(max_tokens=65_536), bound=bound)) == 1
    assert next(r for r in finance(b)['rows'] if r[4] == 'settled')[2] == 1_179_648


def test_scoped_override_requires_financial_budget_before_any_http(tmp_path):
    request = httpx.Request('POST', URL, json=payload())
    with request_token_bound(BOUND), pytest.raises(RequestBudgetExceeded, match='AUTHORITATIVE'):
        account_request_sync(request)
    assert 'report_token_budget' not in request.extensions


def test_second_pending_request_is_cancelled_but_first_hold_remains(tmp_path):
    b, _, _, _, guard = setup_probe(tmp_path)
    request = httpx.Request('POST', URL, json=payload())
    with token_budget(b), request_token_bound(BOUND), request_reservation_observer(guard.check):
        account_request_sync(request)
        first = request.extensions['report_token_budget'][1]
        with pytest.raises(RequestBudgetExceeded, match='UNRESOLVED'):
            account_request_sync(httpx.Request('POST', URL, json=payload()))
    now = finance(b)
    assert next(r for r in now['rows'] if r[0] == first)[4] == 'reserved'
    assert sum(r[4] == 'known_not_sent' for r in now['rows']) == 1


def test_actual_recovery_accounts_scoped_bound_and_cannot_escape_probe_guard(tmp_path):
    from report_agent.model_recovery import activate_recovery, recover_model_call, STATE_KEY
    from report_agent.store import Store
    b, _, _, hold, guard = setup_probe(tmp_path)
    store = Store(tmp_path / 'case')
    activate_recovery(store, authorization='synthetic', extra_token_ceiling=BOUND.total, backoff_seconds=0)
    sent = []
    def respond(request):
        sent.append(request)
        raise httpx.ReadTimeout('synthetic timeout', request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond),
                event_hooks={'request':[account_request], 'response':[account_response]}) as client:
            async def invoke():
                with request_reservation_observer(lambda: None):
                    return await client.post(URL, json=payload())
            with token_budget(b), request_token_bound(BOUND), request_reservation_observer(guard.check):
                with pytest.raises(RequestBudgetExceeded, match='UNRESOLVED'):
                    await recover_model_call(store=store, role='writer', owner='synthetic-owner',
                        profile={'model':MODEL, 'endpoint':URL}, payload=payload(),
                        invoke=invoke, parse_raw=lambda raw:raw)
    asyncio.run(run())
    assert len(sent) == 1
    assert store.get(STATE_KEY)['extra_token_bounds'] == BOUND.total
    now = finance(b)
    assert next(r for r in now['rows'] if r[0] == hold[0]) == hold
    assert sum(r[4] == 'known_not_sent' for r in now['rows']) == 1
    assert sorted(r[2] for r in now['rows'] if r[4] == 'reserved') == [BOUND.total, 2_000_000]
