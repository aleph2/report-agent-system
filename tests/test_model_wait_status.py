"""Read-only local waiting facts; neither provider liveness nor retry authority."""
import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest

from report_agent.errors import ModelRequestDeadlineExceeded
from report_agent.model_invocation import model_invocation
from report_agent.store import Store
from report_agent.transport_observation import install_http_observer, observe_http_phase


def status(store, **kwargs):
    from report_agent.model_invocation import model_wait_status
    return model_wait_status(store, **kwargs)


async def test_active_call_started_and_actual_timeout_link_without_claiming_provider_liveness(tmp_path):
    store = Store(tmp_path)
    async with model_invocation(store, 'coordinator') as scope:
        started, = [e['data'] for e in store.events() if e['kind'] == 'model_invocation_started']
        assert started['call_id'] == scope.call_id and started['role'] == 'coordinator'
        assert datetime.fromisoformat(started['started_at']).utcoffset().total_seconds() == 0
        assert started['logical_deadline_seconds'] == 600
        request = httpx.Request('POST', 'https://private.invalid', content=b'PRIVATE', extensions={
            'timeout': {'connect': 12, 'read': 37.5, 'write': None, 'pool': 9}})
        install_http_observer(request, store, 'coordinator')
        phase = next(e['data'] for e in store.events() if e['kind'] == 'model_http_phase')
        assert phase['call_id'] == scope.call_id
        assert phase['effective_timeout'] == request.extensions['timeout']
        pending, = status(store)['calls']
        assert pending['latest_known_phase'] == 'request_started'
        assert pending['local_terminal'] is False and pending['provider_unknown'] is True
        observe_http_phase(request, 'headers_received', http_status=200)
        assert status(store)['calls'][0]['latest_known_phase'] == 'headers_received'
        assert status(store)['calls'][0]['provider_unknown'] is True
        observe_http_phase(request, 'body_read_completed')
    terminal, = status(store)['calls']
    assert terminal['local_terminal'] and terminal['local_outcome'] == 'returned'
    assert terminal['provider_unknown'] is False
    assert terminal['elapsed_seconds'] == status(store, now=datetime(2099, 1, 1, tzinfo=timezone.utc))['calls'][0]['elapsed_seconds']
    public = json.dumps(status(store))
    assert 'PRIVATE' not in public and 'private.invalid' not in public


async def test_concurrent_calls_isolate_phase_terminal_and_elapsed(tmp_path):
    store = Store(tmp_path)
    entered = asyncio.Event(); release = asyncio.Event()
    async def waiting():
        async with model_invocation(store, 'writer') as scope:
            entered.set()
            await release.wait()
            return scope.call_id
    task = asyncio.create_task(waiting())
    await entered.wait()
    try:
        async with model_invocation(store, 'reviewer'):
            pass
        rows = status(store)['calls']
        assert len({r['call_id'] for r in rows}) == 2
        assert {r['role']: r['local_terminal'] for r in rows} == {'writer': False, 'reviewer': True}
        assert all(r['provider_unknown'] for r in rows)  # No complete response observed.
    finally:
        release.set(); await task


@pytest.mark.parametrize('bad', [True, False, float('inf'), float('nan'), '600', {'secret': 'PRIVATE'}])
async def test_timeout_capture_allowlist_never_changes_actual_request(tmp_path, bad):
    store = Store(tmp_path)
    values = {'read': bad, 'connect': 15, 'write': None, 'pool': 60, 'headers': 'PRIVATE'}
    async with model_invocation(store, 'reviewer'):
        request = httpx.Request('POST', 'https://private.invalid', content=b'PRIVATE', extensions={'timeout': values})
        install_http_observer(request, store, 'reviewer')
        row = next(e['data'] for e in store.events() if e['kind'] == 'model_http_phase')
        assert row['effective_timeout'] == {'connect': 15, 'write': None, 'pool': 60}
        assert request.extensions['timeout'] is values and values['read'] is bad
        assert 'PRIVATE' not in json.dumps(row)


def test_recent_event_projection_is_bounded_partial_and_read_only(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.event('model_invocation_started', {'call_id': 'one', 'role': 'coordinator',
        'started_at': '2026-10-24T00:00:00+00:00', 'logical_deadline_seconds': 1800})
    store.event('model_http_phase', {'call_id': 'one', 'role': 'coordinator', 'phase': 'headers_received'})
    calls = []
    original = store.events
    def bounded(limit=None):
        calls.append(limit)
        return original(limit)
    monkeypatch.setattr(store, 'events', bounded)
    report = status(store, now=datetime(2026, 10, 24, 0, 0, 20, tzinfo=timezone.utc), limit=1)
    assert calls == [1] and report['coverage'] == 'partial'
    assert report['calls'][0]['started_at'] is None
    assert report['calls'][0]['elapsed_seconds'] is None
    assert report['calls'][0]['provider_unknown'] is True
    assert len(original()) == 2


def test_missing_outcome_past_deadline_remains_local_uncertainty_and_read_failure_is_safe(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.event('model_invocation_started', {'call_id': 'orphan', 'role': 'coordinator',
        'started_at': '2026-10-24T00:00:00+00:00', 'logical_deadline_seconds': 1800})
    report = status(store, now=datetime(2026, 10, 25, tzinfo=timezone.utc))
    row, = report['calls']
    assert row['elapsed_seconds'] == 86400
    assert row['provider_unknown'] and not row['local_terminal'] and row['local_outcome'] is None
    def unavailable(limit=None):
        raise OSError('PRIVATE read failure')
    monkeypatch.setattr(store, 'events', unavailable)
    report = status(store)
    assert report['coverage'] == 'unavailable' and report['calls'] == []
    assert 'PRIVATE' not in json.dumps(report)


def test_recent_call_projection_is_small_and_marks_omitted_history(tmp_path):
    store = Store(tmp_path)
    for index in range(25):
        store.event('model_invocation_started', {'call_id': str(index), 'role': 'coordinator',
            'started_at': '2026-10-24T00:00:00+00:00', 'logical_deadline_seconds': 1800})
    # An older call observed again belongs to the latest visible set.
    store.event('model_http_phase', {'call_id': '0', 'phase': 'headers_received'})
    before = store.events()
    report = status(store)
    assert report['call_limit'] == 16 and report['observed_call_count'] == 25
    assert report['truncated'] and report['coverage'] == 'partial'
    assert len(report['calls']) == 16
    assert [row['call_id'] for row in report['calls']] == [str(i) for i in range(10, 25)] + ['0']
    assert store.events() == before


async def test_diagnostic_write_failure_preserves_original_exception(tmp_path, monkeypatch):
    store = Store(tmp_path)
    def broken(*args):
        raise OSError('PRIVATE')
    monkeypatch.setattr(store, 'event', broken)
    original = ValueError('actual failure')
    with pytest.raises(ValueError) as caught:
        async with model_invocation(store, 'coordinator'):
            raise original
    assert caught.value is original


async def test_local_logical_deadline_is_terminal_unknown_and_no_later_dispatch(tmp_path, monkeypatch):
    from test_transport_observation import setup_model, use_mock, close
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', .03)
    store, model = setup_model(tmp_path, monkeypatch)
    posts = []
    deadlines = []
    real_timeout = asyncio.timeout
    def controlled_timeout(seconds):
        deadline = real_timeout(None if seconds == .03 else seconds)
        if seconds == .03:
            deadlines.append(deadline)
        return deadline
    monkeypatch.setattr(asyncio, 'timeout', controlled_timeout)
    async def blocked(request):
        posts.append(True)
        assert len(deadlines) == 1
        # Exercise the sent-without-response branch, independent of SDK startup load.
        deadlines[0].reschedule(asyncio.get_running_loop().time() + .03)
        await asyncio.Event().wait()
    await use_mock(model, blocked)
    try:
        with pytest.raises(ModelRequestDeadlineExceeded):
            await asyncio.wait_for(model.ainvoke('synthetic input'), timeout=10)
        row, = status(store)['calls']
        assert row['local_outcome'] == 'local_deadline_exceeded' and row['local_terminal']
        assert row['provider_unknown'] is True
        assert len(posts) == 1
        await asyncio.sleep(.05)
        assert len(posts) == 1
    finally:
        await close(model)
