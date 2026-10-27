"""Real SDK/adapter timeout reaches native tool observation; no external network."""
import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.content_store import ContentStore
from report_agent.deep_models import configured_model
from report_agent.deep_runtime import run_report
from report_agent.errors import ModelRequestDeadlineExceeded
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.request_budget import RequestBudgetExceeded
from report_agent.token_budget import TokenBudget, token_budget
from test_deep_runtime import Driver, invoke, observation
from test_task_supervision import ws
from test_text_work import writer_call


def offline_model(ws, monkeypatch):
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', .05)
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    for suffix, value in [('MODEL', 'glm-5.3'), ('BASE_URL', 'https://offline.invalid/v1'),
                          ('API_KEY', 'offline-key')]:
        monkeypatch.setenv('REPORT_TEXT_TOOL_' + suffix, value)
    return configured_model(ws.store, 'text_tool')


async def close_model(model):
    await model.root_async_client.close()
    model.root_client.close()


@pytest.mark.parametrize('new_id', [False, True])
async def test_native_bounded_sdk_deadline_is_unknown_observation_with_reserved_budget(ws, monkeypatch, tmp_path, new_id):
    model = offline_model(ws, monkeypatch)
    dispatched, cancelled = [], []
    from types import SimpleNamespace
    import report_agent.model_invocation as invocation
    deadlines = []
    def timeout_when_dispatched(delay):
        assert delay == .05
        timer = asyncio.timeout(None)
        deadlines.append(timer)
        return timer
    scenario_asyncio = SimpleNamespace(**vars(asyncio))
    scenario_asyncio.timeout = timeout_when_dispatched
    # Stage this in-flight fault after preparation without patching global asyncio.
    monkeypatch.setattr(invocation, 'asyncio', scenario_asyncio)
    async def handle(request):
        dispatched.append(request)
        assert len(deadlines) == 1
        deadlines[0].reschedule(asyncio.get_running_loop().time() + .05)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    model.http_async_client._transport = httpx.MockTransport(handle)
    tokens = TokenBudget(tmp_path / 'budget.db', 20000, {'glm-5.3': 10000})
    def after_failure(messages):
        result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
        assert result['code'] == 'EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED'
        detail = json.loads(result['message'].split(': ', 1)[1])
        assert detail['provider_outcome'] == 'unknown'
        assert detail['raw_response_received'] is False and detail['usage'] is None
        assert detail['deadline_seconds'] == .05
        assert detail['local_elapsed_seconds'] > 0
        return invoke('get_operation_receipt', operation_id='timeout')
    def after_query(messages):
        result = observation(messages, 'get_operation_receipt')
        attempt = result['text_work']
        assert result['content_operation']['state'] == 'unknown'
        assert attempt['state'] == 'outcome_unresolved' and attempt['stored_state'] == 'reserved'
        assert not attempt['raw_response_received'] and not attempt['adoptable_result']
        assert attempt['usage'] is None and attempt['provider_outcome'] == 'unknown'
        return invoke('process_report_content', operation_id='shortened-retry' if new_id else 'timeout',
                      objective='Describe source concisely' if new_id else 'Describe source',
                      object_type='ContentNode', source_selections=[{'source_id': 's'}])
    def after_replay(messages):
        result = json.loads(next(m.content for m in reversed(messages) if isinstance(m, ToolMessage)))
        assert result['code'] == ('TEXT_WORK_SAME_EVIDENCE_OUTCOME_UNRESOLVED' if new_id else 'TEXT_WORK_OUTCOME_UNRESOLVED')
        return AIMessage(content='No result was adopted; original unknown attempt retained.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]), AIMessage(content='Done.')],
                    writer=[invoke('process_report_content', operation_id='timeout', objective='Describe source',
                                   object_type='ContentNode', source_selections=[{'source_id': 's'}]),
                            after_failure, after_query, after_replay])
    try:
        with token_budget(tokens):
            result = await asyncio.wait_for(run_report(ws,
                model_factory=lambda role: model if role == 'text_tool' else driver(role)), 30)
        assert result['last_error'] is None
        assert len(dispatched) == 1 and cancelled == [True]
        assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 10000
        assert tokens.snapshot()['recorded_tokens'] == 0
        assert ContentStore(ws.store).list_objects('ContentNode') == []
        attempts = [e for e in ws.store.events() if e['kind'] == 'evidence_analysis_unresolved']
        assert len(attempts) == 1
        assert ws.store.analysis(attempts[0]['data']['operation']) is None
        receipt = ws.store.get('bounded_review_attempt:' + attempts[0]['data']['operation'])
        assert receipt['state'] == 'unknown' and receipt['raw_response_received'] is False
        assert receipt['result']['usage'] is None
    finally:
        await close_model(model)


async def test_inflight_timeout_scenario_survives_cold_sdk_preparation(ws, monkeypatch, tmp_path):
    import time
    from report_agent.deep_models import GLMChatOpenAI
    original = GLMChatOpenAI._get_request_payload
    def slow_payload(self, *args, **kwargs):
        time.sleep(.15)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(GLMChatOpenAI, '_get_request_payload', slow_payload)
    await test_native_bounded_sdk_deadline_is_unknown_observation_with_reserved_budget(
        ws, monkeypatch, tmp_path, False)


async def test_real_deadline_bounds_sdk_preparation_before_http_send(ws, monkeypatch):
    model = offline_model(ws, monkeypatch)
    dispatched = []
    async def prepare(request):
        await asyncio.Event().wait()
    async def transport(request):
        dispatched.append(request)
        raise AssertionError('SDK preparation must remain inside the real total deadline')
    monkeypatch.setattr(model.root_async_client, '_prepare_request', prepare)
    model.http_async_client._transport = httpx.MockTransport(transport)
    try:
        with pytest.raises(ModelRequestDeadlineExceeded):
            await asyncio.wait_for(model.ainvoke('Synthetic pre-HTTP wait.'), 30)
        assert dispatched == []
    finally:
        await close_model(model)


async def test_decision_model_deadline_still_raises_dedicated_timeout(ws, monkeypatch):
    model = offline_model(ws, monkeypatch)
    async def handle(request):
        await asyncio.Event().wait()
    model.http_async_client._transport = httpx.MockTransport(handle)
    try:
        with pytest.raises(ModelRequestDeadlineExceeded) as caught:
            await model.ainvoke('offline decision')
        assert caught.value.deadline_seconds == .05
    finally:
        await close_model(model)


async def test_outer_cancellation_is_not_a_local_deadline(ws, monkeypatch):
    model = offline_model(ws, monkeypatch)
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    dispatched = asyncio.Event()
    async def handle(request):
        dispatched.set()
        await asyncio.Event().wait()
    model.http_async_client._transport = httpx.MockTransport(handle)
    try:
        work = asyncio.create_task(analyze_evidence_packet(ws, model, {'evidence': []}, 'offline', 'offline', reserve_attempt=True))
        await dispatched.wait()
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
        assert not any(e['kind'] == 'evidence_analysis_unresolved' for e in ws.store.events())
    finally:
        await close_model(model)


@pytest.mark.parametrize('failure', [TimeoutError('unrelated'), RequestBudgetExceeded('MODEL_REQUEST_BUDGET_REACHED')])
async def test_unrelated_timeout_and_budget_failure_are_not_reclassified(ws, monkeypatch, failure):
    from langchain_openai import ChatOpenAI
    model = offline_model(ws, monkeypatch)
    async def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(ChatOpenAI, '_agenerate', fail)
    try:
        with pytest.raises(type(failure)) as caught:
            await analyze_evidence_packet(ws, model, {'evidence': []}, 'offline', 'offline', reserve_attempt=True)
        assert caught.value is failure
        assert not any(e['kind'] == 'evidence_analysis_unresolved' for e in ws.store.events())
    finally:
        await close_model(model)
