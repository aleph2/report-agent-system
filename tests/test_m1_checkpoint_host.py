"""Owner checkpoints wait/resume in one host budget without fresh report launches."""
import asyncio
from pathlib import Path
import runpy

import pytest

from report_agent import request_budget, token_budget as budgets
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_pilot_m1_preparation import ROOT, host_case, put_json


def helper(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    host = runpy.run_path(str(ROOT / 'scripts/report_host.py'), run_name='checkpoint_helper_test')
    return host['run_with_owner_checkpoint']


@pytest.fixture
def waiting_workspace(tmp_path):
    store = Store(tmp_path / 'case')
    store.initialize({'goal': 'Synthetic checkpoint', 'sources': [
        {'id': 'scope', 'title': 'Scope', 'content': 'Confirm before writing.', 'coverage': 'complete'}]})
    return Workspace(store)


def pending(ws, description):
    issue = ws.issue('requirement', description, ['scope'])
    ws.store.set('report_status', 'needs_human')
    ws.store.set('native_interrupts', [{'id': 'interrupt-' + issue['id'],
                                      'value': {'issue_id': issue['id']}}])
    return issue


async def test_no_owner_reply_keeps_waiting_without_more_runner_calls(waiting_workspace, monkeypatch):
    run = helper(monkeypatch)
    ws = waiting_workspace
    calls, sleeps = [], []

    async def runner(workspace):
        calls.append(workspace)
        pending(workspace, 'Confirm current plan')
        return {'status': 'needs_human'}

    async def tick(seconds):
        sleeps.append(seconds)
        assert calls == [ws]
        if len(sleeps) == 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', tick)
    with pytest.raises(asyncio.CancelledError):
        await run(ws, runner)
    assert calls == [ws] and len(sleeps) == 3
    assert ws.store.get('report_status') == 'needs_human'


async def test_owner_replies_and_corrections_resume_same_workspace_budget_and_unknown_rows(waiting_workspace, monkeypatch, tmp_path):
    run = helper(monkeypatch)
    ws = waiting_workspace
    budget = budgets.TokenBudget(tmp_path / 'ledger.db', 1000, {'offline': 100})
    budget.settle(budget.reserve('offline'), {'total_tokens': 7})
    budget.settle(budget.reserve('offline'), None)
    original = budget.snapshot()
    calls, sleeps, issues = [], [], []
    observer = lambda: None

    async def runner(workspace):
        assert workspace is ws and budgets._active.get() is budget
        assert any(item[0] is observer for item in request_budget._reservation_observer.get())
        assert budget.snapshot() == original
        calls.append(workspace)
        if len(calls) < 3:
            issues.append(pending(ws, 'Confirm plan version ' + str(len(calls))))
            return {'status': 'needs_human'}
        ws.store.set('report_status', 'completed')
        return {'status': 'completed', 'same_host': True}

    async def tick(seconds):
        sleeps.append(seconds)
        assert len(calls) == len(sleeps)
        assert budgets._active.get() is budget
        # First response requests corrections; a later distinct checkpoint needs its own answer.
        ws.decide_issue(issues[-1]['id'], 'Correct the plan' if len(sleeps) == 1 else 'Approve corrected plan', resolved=True)

    monkeypatch.setattr(asyncio, 'sleep', tick)
    with budgets.token_budget(budget), request_budget.request_reservation_observer(observer):
        result = await run(ws, runner)
    assert result == {'status': 'completed', 'same_host': True}
    assert len(calls) == 3 and len(sleeps) == 2
    assert budget.snapshot() == original
    assert len({issue['id'] for issue in issues}) == 2


async def test_unidentified_interrupt_returns_attention_without_spinning_or_resuming(waiting_workspace, monkeypatch):
    run = helper(monkeypatch)
    ws = waiting_workspace
    calls = []

    async def runner(workspace):
        calls.append(workspace)
        ws.store.set('report_status', 'needs_human')
        ws.store.set('native_interrupts', [{'id': 'unknown', 'value': {'kind': 'other_attention'}}])
        return {'status': 'needs_human'}

    async def forbidden(*args):
        pytest.fail('An unidentified interrupt must not become an endless owner wait')

    monkeypatch.setattr(asyncio, 'sleep', forbidden)
    result = await run(ws, runner)
    assert len(calls) == 1 and result['status'] == 'needs_attention'


async def test_all_pending_issues_need_operator_answers_before_resume(waiting_workspace, monkeypatch):
    run = helper(monkeypatch)
    ws = waiting_workspace
    first, second = pending(ws, 'First question'), pending(ws, 'Second question')
    ws.decide_issue(first['id'], 'Approved', resolved=True)
    calls, sleeps = [], []

    async def runner(workspace):
        calls.append(workspace)
        if len(calls) == 1:
            ws.store.set('report_status', 'needs_human')
            ws.store.set('native_interrupts', [{'id': issue['id'], 'value': {'issue_id': issue['id']}}
                                               for issue in (first, second)])
            return {'status': 'needs_human'}
        ws.store.set('report_status', 'completed')
        return {'status': 'completed'}

    async def tick(seconds):
        sleeps.append(seconds)
        assert len(calls) == 1
        ws.decide_issue(second['id'], 'Approved separately', resolved=True)

    monkeypatch.setattr(asyncio, 'sleep', tick)
    assert (await run(ws, runner))['status'] == 'completed'
    assert len(calls) == 2 and len(sleeps) == 1


async def test_actual_host_invokes_checkpoint_helper_inside_existing_budget_context(tmp_path, monkeypatch):
    from report_agent import model_config, deep_runtime
    state = host_case(tmp_path, monkeypatch)
    state['prepare']()
    prepared = state['load'](state['HERE'] / 'prepared.json')
    put_json(state['HERE'] / 'neo-approval.json', {'approved': True,
        'host_sha256': prepared['host_sha256'], 'prepared_sha256': state['sha'](state['HERE'] / 'prepared.json')})
    monkeypatch.setitem(state, 'LOCK', tmp_path / 'host.lock')
    monkeypatch.setitem(state, 'ROLE_MODELS', {})
    monkeypatch.setattr(model_config, 'load_mixed_services', lambda *args: None)
    monkeypatch.setattr(model_config, 'role_service', lambda role: ('offline', 'https://fixture.invalid', 'offline'))
    monkeypatch.setattr(model_config, 'bind_role_services', lambda store: None)
    seen = []

    class BoundaryReached(Exception):
        pass

    async def checkpoint(workspace, runner):
        active = budgets._active.get()
        assert active is not None and active.path == state['LEDGER']
        assert request_budget._reservation_observer.get()
        assert runner is deep_runtime.run_report
        assert workspace.store.root == state['CASE']
        seen.append(True)
        raise BoundaryReached()

    async def forbidden(*args, **kwargs):
        pytest.fail('Actual host must use the checkpoint helper, not invoke a report directly')

    monkeypatch.setattr(deep_runtime, 'run_report', forbidden)
    monkeypatch.setitem(state, 'run_with_owner_checkpoint', checkpoint)
    with pytest.raises(BoundaryReached):
        await state['run']()
    assert seen == [True]
