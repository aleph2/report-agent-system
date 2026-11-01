"""Provider counters are observations, never a second bill or stop authority."""
from copy import deepcopy
import json
import socket

import httpx
import pytest

from report_agent.deep_models import model_async_client, model_sync_client
from report_agent.prompt_provenance import bind_wire_payload, prompt_call
from report_agent.token_budget import TokenBudget, token_budget
from test_task_supervision import ws


@pytest.fixture(autouse=True)
def no_external_socket(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    def denied(*args, **kwargs):
        pytest.fail('Observation tests use MockTransport, never external sockets.')
    monkeypatch.setattr(socket.socket, 'connect', denied)


@pytest.mark.parametrize('purpose', ['coordinator', 'tool_selector:coordinator'])
@pytest.mark.parametrize('asynchronous', [True, False], ids=['async', 'sync'])
@pytest.mark.parametrize('cache,expected,source', [
    ({'prompt_tokens_details': {'cached_tokens': 3}}, 3, 'prompt_tokens_details.cached_tokens'),
    ({'prompt_cache_hit_tokens': 3, 'prompt_cache_miss_tokens': 5}, 3, 'prompt_cache_hit_tokens'),
    ({'prompt_tokens_details': {'cached_tokens': 0}}, 0, 'prompt_tokens_details.cached_tokens'),
    ({}, None, None),
    ({'prompt_tokens_details': {'cached_tokens': True}}, None, None),
    ({'prompt_tokens_details': {'cached_tokens': '3'}}, None, None),
    ({'prompt_tokens_details': {'cached_tokens': -1}}, None, None),
    ({'prompt_tokens_details': ['not-a-count-dictionary']}, None, None),
    ({'prompt_cache_hit_tokens': False}, None, None),
    ({'prompt_cache_hit_tokens': '3'}, None, None),
    ({'prompt_cache_hit_tokens': -1}, None, None),
])
async def test_real_http_usage_hook_preserves_cache_source_and_counts_cost_once(ws, tmp_path, purpose, asynchronous, cache, expected, source):
    usage = {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10, **cache,
             'private_provider_metadata': 'PRIVATE_USAGE_CANARY', 'unapproved_counter': 987,
             'completion_tokens_details': {'unapproved_detail': 123}}
    before_usage = deepcopy(usage)
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'fixture-model': 50})
    old_id = budget.reserve('fixture-model')
    with budget.connect() as db:
        old_row = db.execute('SELECT * FROM attempts WHERE id=?', (old_id,)).fetchone()
    payload = {'model': 'fixture-model', 'stream': False, 'messages': [
        {'role': 'user', 'content': 'Synthetic observation only.'}]}
    requests = []
    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={'id': 'fixture-response', 'usage': usage,
            'choices': [{'message': {'content': 'PRIVATE_PROVIDER_BODY_CANARY'}}]})
    if asynchronous:
        async with model_async_client(ws.store, 'coordinator') as client:
            old = client._transport
            client._transport = httpx.MockTransport(transport)
            await old.aclose()
            client._mounts.clear()
            with token_budget(budget), prompt_call(ws.store, purpose, status='exact', offered=payload) as call:
                bind_wire_payload(payload)
                response = await client.post('https://offline.invalid/v1/chat/completions', json=payload)
                assert response.status_code == 200 and response.json()['usage'] == usage
    else:
        with model_sync_client(ws.store, 'coordinator') as client:
            old = client._transport
            client._transport = httpx.MockTransport(transport)
            old.close()
            client._mounts.clear()
            with token_budget(budget), prompt_call(ws.store, purpose, status='exact', offered=payload) as call:
                bind_wire_payload(payload)
                response = client.post('https://offline.invalid/v1/chat/completions', json=payload)
                assert response.status_code == 200 and response.json()['usage'] == usage
    event, = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_provider_usage']
    assert event['role'] == 'coordinator' and event['purpose'] == purpose
    assert event['call_id'] == call['call_id']
    assert event['attempt_id'] == requests[0].extensions['report_token_budget'][1]
    assert event['cached_tokens'] == expected and event['cached_tokens_source'] == source
    expected_usage = {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}
    if source == 'prompt_tokens_details.cached_tokens':
        expected_usage['prompt_tokens_details'] = {'cached_tokens': expected}
    elif source == 'prompt_cache_hit_tokens':
        expected_usage.update(prompt_cache_hit_tokens=expected, prompt_cache_miss_tokens=5)
    assert event['usage'] == expected_usage
    assert 'PRIVATE_USAGE_CANARY' not in json.dumps(event)
    assert 'PRIVATE_PROVIDER_BODY_CANARY' not in json.dumps(event)
    assert 'stop' not in event and 'replay' not in event
    actual = budget.snapshot()
    assert actual['recorded_tokens'] == 10
    assert actual['reserved_or_unknown_upper_bounds'] == 50
    with budget.connect() as db:
        assert db.execute('SELECT * FROM attempts WHERE id=?', (old_id,)).fetchone() == old_row
        new_row = db.execute('SELECT state,used FROM attempts WHERE id=?', (event['attempt_id'],)).fetchone()
    assert new_row == ('settled', 10)
    assert usage == before_usage and len(requests) == 1


async def test_missing_provider_usage_stays_unknown_and_keeps_reservation(ws, tmp_path):
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'fixture-model': 50})
    payload = {'model': 'fixture-model', 'stream': False, 'messages': [{'role': 'user', 'content': 'Fixture.'}]}
    async with model_async_client(ws.store, 'coordinator') as client:
        client._transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'id': 'unknown-usage'}))
        client._mounts.clear()
        with token_budget(budget), prompt_call(ws.store, 'coordinator', status='exact', offered=payload):
            bind_wire_payload(payload)
            await client.post('https://offline.invalid/v1/chat/completions', json=payload)
    event, = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_provider_usage']
    assert event['usage'] is None
    assert event['cached_tokens'] is None and event['cached_tokens_source'] is None
    assert budget.snapshot()['recorded_tokens'] == 0
    assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == 50
    assert budget.snapshot()['attempt_states']['unknown'] == 1


def observation(tokens, *, role='writer', purpose='writer', task_id='task-one', phase='draft',
                rejection='', saved=()):
    return {'role': role, 'purpose': purpose, 'task_id': task_id, 'phase': phase,
            'tokens': tokens, 'rejection_signature': rejection, 'saved_record_refs': list(saved)}


def signals(records, window=3):
    from report_agent import execution_progress
    return execution_progress.progress_signals(records, window=window)


def test_progress_signals_are_observations_not_a_two_times_stop_policy():
    records = [observation(n, rejection='same-rejection') for n in (10, 21, 50)]
    before = deepcopy(records)
    result = signals(records)
    assert {r['kind'] for r in result} == {'increasing_tokens', 'repeated_rejection', 'no_new_saved_records'}
    assert all(r == {'kind': r['kind'], 'role': 'writer', 'purpose': 'writer',
                     'task_id': 'task-one', 'phase': 'draft', 'window': 3} for r in result)
    assert records == before  # Includes >2x growth; no hidden cancellation, quota or mutation.


@pytest.mark.parametrize('field', ['role', 'purpose', 'task_id', 'phase'])
def test_progress_comparisons_never_mix_different_responsibilities_or_phases(field):
    records = [observation(n, rejection='same-rejection') for n in (10, 20, 40)]
    records[1][field] = 'other'
    assert signals(records) == []


@pytest.mark.parametrize('field', ['role', 'purpose', 'task_id', 'phase'])
def test_unknown_comparison_identity_is_not_treated_as_an_equivalent_window(field):
    records = [observation(n) for n in (10, 20, 40)]
    for record in records:
        del record[field]
    assert signals(records) == []


def test_missing_tokens_or_saved_record_observations_are_not_zero_or_no_progress():
    records = [observation(n) for n in (10, 20, 40)]
    records[1]['tokens'] = None
    del records[1]['saved_record_refs']
    assert signals(records) == []


def test_a_new_saved_version_is_progress_even_when_object_id_stays_the_same():
    first = {'type': 'ContentNode', 'id': 'same-node', 'version': 1}
    second = {**first, 'version': 2}
    records = [observation(10, saved=[first]), observation(9, saved=[first]), observation(8, saved=[second])]
    assert signals(records) == []


def test_recent_group_window_is_explicit_and_does_not_compare_old_episodes():
    records = [observation(n, rejection='earlier-error' if i < 3 else '')
               for i, n in enumerate((1, 2, 3, 30, 20, 10))]
    records[-1]['saved_record_refs'] = ['new-record']
    assert signals(records, window=3) == []
    assert signals(records[:2], window=3) == []


def test_progress_window_has_no_implicit_default():
    from report_agent import execution_progress
    with pytest.raises(TypeError):
        execution_progress.progress_signals([])
