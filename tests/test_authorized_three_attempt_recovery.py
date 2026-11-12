"""Actual SDK and native task-boundary checks; all network is replaced or denied."""
import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import model_invocation as invocation
from report_agent.content_store import Actor
from report_agent.deep_models import configured_vision_client
from report_agent.errors import ModelRequestDeadlineExceeded
from report_agent.model_recovery import activate_recovery, recovery_owner, RecoveryBlocked, STATE_KEY
from report_agent.request_budget import RequestBudgetExceeded
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, token_budget
from test_model_recovery import calls
from test_transport_observation import setup_model, use_mock, close, body


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    def denied(*args, **kwargs):
        pytest.fail('No external sockets in recovery verification')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def activate(store):
    return activate_recovery(store, authorization='desktop-600s-fresh-200m',
        extra_per_call=2, extra_per_case=None, extra_token_ceiling=None,
        backoff_seconds=0)


def test_effective_attempt_deadline_is_ten_minutes():
    assert invocation.MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert invocation.model_request_timeout().read == 600


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout', 'rubric_grader', 'text_tool'])
@pytest.mark.parametrize('succeeds', [False, True])
async def test_three_attempts_sdk_owner_and_holds(tmp_path, monkeypatch, role, succeeds):
    store, model = setup_model(tmp_path, monkeypatch, role=role)
    model.root_async_client.max_retries = 0
    activate(store)
    seen = []
    def respond(request):
        seen.append(request)
        assert request.headers.get('x-stainless-retry-count', '0') == '0'
        assert request.extensions['timeout']['read'] == 600
        if not succeeds or len(seen) < 3:
            raise httpx.ReadTimeout('offline timeout', request=request)
        return httpx.Response(200, json=body())
    await use_mock(model, respond)
    budget = TokenBudget(tmp_path/'budget.db', 200_000_000, {'deepseek-v4.1-flash-1017':2_000_000})
    try:
        with token_budget(budget), recovery_owner(store, Actor('actor', role, 'task'), 'model-op'):
            if succeeds:
                assert (await model.ainvoke('one pure inference')).content == 'unchanged result'
                assert (await model.ainvoke('one pure inference')).content == 'unchanged result'
            else:
                with pytest.raises(Exception):
                    await model.ainvoke('one pure inference')
                with pytest.raises(RecoveryBlocked, match='PRIOR_ATTEMPT_UNRESOLVED'):
                    await model.ainvoke('one pure inference')
        assert len(seen) == 3
        states = budget.snapshot()['attempt_states']
        assert states == ({'reserved':2, 'settled':1} if succeeds else {'reserved':3})
        assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == (4_000_000 if succeeds else 6_000_000)
        assert budget.snapshot()['recorded_tokens'] == (10 if succeeds else 0)
        assert store.get(STATE_KEY)['extra_calls'] == 2
        assert len(calls(store)[0]['attempt_history']) == 2
        assert len([e for e in store.events() if e['kind']=='model_invocation_started']) == 3
    finally:
        await close(model)


async def test_new_full_deadline_per_attempt_without_waiting_six_hundred_seconds(tmp_path, monkeypatch):
    store, model = setup_model(tmp_path, monkeypatch, role='coordinator')
    model.root_async_client.max_retries = 0
    activate(store)
    timers, seen = [], []
    def timeout(seconds):
        assert seconds == 600
        timer = asyncio.timeout(None)
        timers.append(timer)
        return timer
    monkeypatch.setattr(invocation, 'asyncio', SimpleNamespace(timeout=timeout, CancelledError=asyncio.CancelledError))
    async def respond(request):
        seen.append(request)
        assert len(timers)==len(seen)
        if len(seen)<3:
            timers[-1].reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'budget.db',200,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            assert (await model.ainvoke('deadline recovery')).content=='unchanged result'
        assert len(seen)==len(timers)==3
        assert [e['data']['outcome'] for e in store.events() if e['kind']=='model_invocation_outcome']==[
            'local_deadline_exceeded','local_deadline_exceeded','returned']
    finally:
        await close(model)


async def test_no_unapproved_case_retry_subquota_and_budget_still_blocks(tmp_path,monkeypatch):
    store,model=setup_model(tmp_path,monkeypatch,role='coordinator')
    model.root_async_client.max_retries=0
    policy=activate(store)
    assert policy['extra_per_case'] is policy['extra_token_ceiling'] is None
    seen=[]
    def respond(request):
        seen.append(request)
        if len(seen)%3:
            raise httpx.ReadTimeout('offline',request=request)
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/'budget.db',200_000_000,{'deepseek-v4.1-flash-1017':2_000_000})
    try:
        with token_budget(budget):
            for i in range(5):
                await model.ainvoke('distinct input '+str(i))
        assert len(seen)==15 and store.get(STATE_KEY)['extra_calls']==10
        assert store.get(STATE_KEY)['extra_token_bounds']==20_000_000
        assert budget.snapshot()['reserved_or_unknown_upper_bounds']==20_000_000
        near=TokenBudget(tmp_path/'near.db',200_000_000,{'deepseek-v4.1-flash-1017':2_000_000,'prior':198_000_000})
        prior=near.reserve('prior')
        near.settle(prior,{'total_tokens':198_000_000})
        with token_budget(near),pytest.raises(RequestBudgetExceeded):
            await model.ainvoke('budget near boundary')
        assert near.snapshot()['recorded_tokens']==198_000_000
        assert near.snapshot()['reserved_or_unknown_upper_bounds']==2_000_000
        assert len(seen)==16
    finally:
        await close(model)


@pytest.mark.parametrize('succeeds',[False,True])
async def test_vision_three_attempts_with_same_persistent_owner(tmp_path,monkeypatch,succeeds):
    from report_agent.vision import _observe
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    for suffix,value in [('MODEL','deepseek-v4.1-flash-1017'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','offline')]:
        monkeypatch.setenv('REPORT_VISION_'+suffix,value)
    store=Store(tmp_path/'vision');activate(store);client=configured_vision_client();seen=[]
    def respond(request):
        seen.append(request)
        assert request.extensions['timeout']['read']==600
        if not succeeds or len(seen)<3:
            raise httpx.ReadTimeout('offline',request=request)
        return httpx.Response(200,json=body())
    client._client._transport=httpx.MockTransport(respond);client._client._mounts={}
    budget=TokenBudget(tmp_path/'budget.db',200,{'deepseek-v4.1-flash-1017':40})
    try:
        with token_budget(budget):
            result=await _observe(store,b'fake-image',{'source_id':'s','page':1,'sha256':'a'*64},
                'observe',client,Actor('writer','writer','task'))
        assert result['status']==('observed' if succeeds else 'failed')
        assert len(seen)==3 and store.get(STATE_KEY)['extra_calls']==2
        assert budget.snapshot()['attempt_states']==({'reserved':2,'settled':1} if succeeds else {'reserved':3})
    finally:
        await client.close()


async def test_sync_client_rejects_active_async_recovery_profile_before_send(tmp_path,monkeypatch):
    store,model=setup_model(tmp_path,monkeypatch,role='coordinator');activate(store)
    try:
        with pytest.raises(Exception,match='RECOVERY_ASYNC_ENTRYPOINT_REQUIRED'):
            model.invoke('must not use a sync path with this profile')
    finally:
        await close(model)


async def test_delegated_local_deadline_returns_to_co_and_another_task_runs(tmp_path):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver,call,observation
    from test_task_supervision import ws
    workspace=ws.__wrapped__(tmp_path/'native')
    seen=[]
    def fail(messages):
        seen.append(1)
        if len(seen)==1:
            raise ModelRequestDeadlineExceeded(600)
        return AIMessage(content='Alternate task returned.')
    def next_action(messages):
        value=observation(messages,'task')
        assert value['code']=='DELEGATED_EXECUTION_FAILED'
        assert value['error']['message']=='MODEL_REQUEST_TIMEOUT'
        return AIMessage(content='',tool_calls=[call('task',{'subagent_type':'writer','description':'Independent alternate task.'},'alternate')])
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[call('task',{
        'subagent_type':'writer','description':'First task that fails.'},'first')]),next_action,
        AIMessage(content='Two observations retained. No engineering acceptance.')],
        writer=[fail])
    result=await run_report(workspace,driver)
    assert result['last_error'] is None
    assert len([e for e in workspace.store.events() if e['kind']=='content_delegation_failed'])==1
    assert len(seen)==2


async def test_root_deadline_is_attention_with_checkpoint_not_host_restart(tmp_path):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    from test_task_supervision import ws
    workspace=ws.__wrapped__(tmp_path/'root');seen=[]
    def fail(messages):
        seen.append(1)
        raise ModelRequestDeadlineExceeded(600)
    result=await run_report(workspace,Driver(coordinator=[fail]))
    assert workspace.store.get('report_status')=='needs_attention'
    assert result['last_error']['failure_kind']=='model_request_timeout'
    assert (workspace.store.root/'checkpoints.db').exists()
    assert len(seen)==1
