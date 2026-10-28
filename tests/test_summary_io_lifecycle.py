"""Real summary entry and SDK admission; synthetic history, offline transport.

Admission proof now comes from the production summary boundary. MockTransport
and ledger assertions independently verify actual sends and preserved reserves.
"""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import HumanMessage, AIMessage

from report_agent.errors import ModelRequestDeadlineExceeded
from report_agent.request_budget import RequestBudgetExceeded, RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.working_summary import working_summary, SummaryRepairRequired
from test_bounded_deadline import offline_model, close_model
from test_hierarchical_content import seed
from test_task_supervision import ws


@pytest.fixture(autouse=True)
def record_summary_trace(ws, request):
    yield
    with ws.store.connect() as db:
        rows = db.execute("SELECT key, value FROM state WHERE key LIKE 'summary_policy_failure:%'").fetchall()
    events = [event for event in ws.store.events()
              if event['kind'].startswith(('working_summary_', 'context_summary_'))]
    request.node.user_properties.append(('summary_lifecycle_trace', json.dumps({
        'events': events, 'states': {key: json.loads(value) for key, value in rows}},
        ensure_ascii=False)))


@pytest.mark.parametrize('local_refusal', [True, False], ids=['zero-dispatch', 'dispatched-timeout'])
async def test_summary_preserves_history_and_actual_outcome_classification(ws, monkeypatch, tmp_path, local_refusal):
    seed(ws)
    model = offline_model(ws, monkeypatch)
    if local_refusal:
        monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    sent = []
    deadlines = []
    if not local_refusal:
        from types import SimpleNamespace
        import report_agent.model_invocation as invocation
        def timeout_when_dispatched(delay):
            assert delay == .05
            timer = asyncio.timeout(None)
            deadlines.append(timer)
            return timer
        scenario_asyncio = SimpleNamespace(**vars(asyncio))
        scenario_asyncio.timeout = timeout_when_dispatched
        monkeypatch.setattr(invocation, 'asyncio', scenario_asyncio)

    async def transport(request):
        assert not local_refusal and len(deadlines) == 1
        sent.append(request)
        deadlines[0].reschedule(asyncio.get_running_loop().time() + .05)
        await asyncio.Event().wait()

    model.http_async_client._transport = httpx.MockTransport(transport)
    summary = working_summary(model, ws.store, role='coordinator')
    history = [HumanMessage('Original requirement.'), AIMessage('Unverified hypothesis.'),
               HumanMessage('Retain uncertainty.')]
    before = deepcopy(history)
    tokens = TokenBudget(tmp_path / 'budget.db', 1 if local_refusal else 20000, {'glm-5.3': 10000})
    try:
        with token_budget(tokens):
            with pytest.raises(RequestBudgetExceeded if local_refusal else ModelRequestDeadlineExceeded) as caught:
                await asyncio.wait_for(summary._acreate_summary(history), 30)
            if local_refusal:
                assert str(caught.value) == 'AUTHORIZED_TOKEN_BUDGET_REACHED'
        saved = ws.store.get(summary._failure_key())
        if local_refusal:
            proof = saved['admission_proof']
            assert proof['origin'] == 'logical_request_admission_hook'
            assert proof['admitted_http_attempts'] == 0 and proof['provider_outcome'] == 'not_dispatched'
            assert proof['reason_code'] == 'AUTHORIZED_TOKEN_BUDGET_REACHED'
            assert saved['raw_response_received'] is False and saved['usage'] is None
        assert history == before and len(sent) == (0 if local_refusal else 1)
        assert not any(e['kind'] == 'working_summary_returned' for e in ws.store.events())
        assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == (0 if local_refusal else 10000)
        with pytest.raises(SummaryRepairRequired, match='original_reason='+saved['reason']):
            await summary._acreate_summary(history)
        assert history == before and len(sent) == (0 if local_refusal else 1)
        assert ws.store.get(summary._failure_key()) == saved
        if local_refusal:
            assert saved['reason'] == 'SUMMARY_NOT_DISPATCHED', {
                'failure_record': saved, 'proof': proof, 'dispatched': len(sent)}
        else:
            assert saved['reason'] == 'SUMMARY_OUTCOME_UNKNOWN'
    finally:
        await close_model(model)


async def test_summary_unproven_budget_exception_stays_unknown(ws):
    from langchain_core.runnables import RunnableLambda
    from report_agent.working_summary import WorkingSummary
    calls = []

    async def model(messages):
        calls.append(messages)
        raise RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED')

    summary = WorkingSummary(model=RunnableLambda(model), store=ws.store, role='coordinator',
                             trigger=('messages', 2), keep=('messages', 1),
                             token_counter=lambda messages: len(messages))
    history = [HumanMessage('Keep original request.')]
    with pytest.raises(RequestBudgetExceeded):
        await summary._acreate_summary(history)
    before = ws.store.get(summary._failure_key())
    assert before['reason'] == 'SUMMARY_OUTCOME_UNKNOWN' and 'admission_proof' not in before
    with pytest.raises(SummaryRepairRequired, match='original_reason=SUMMARY_OUTCOME_UNKNOWN'):
        await summary._acreate_summary(history)
    assert len(calls) == 1 and ws.store.get(summary._failure_key()) == before


async def test_summary_budget_refusal_after_first_send_remains_unknown(ws, monkeypatch, tmp_path):
    model = offline_model(ws, monkeypatch)
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    sent = []

    async def transport(request):
        sent.append(request)
        return httpx.Response(500, json={'error': {'message': 'synthetic transport failure'}})

    model.http_async_client._transport = httpx.MockTransport(transport)
    tokens = TokenBudget(tmp_path / 'budget.db', 20000, {'glm-5.3': 10000})
    summary = working_summary(model, ws.store, role='coordinator')
    history = [HumanMessage('Original requirement.')]
    try:
        with token_budget(tokens), request_budget(RequestBudget(1)), pytest.raises(RequestBudgetExceeded):
            await summary._acreate_summary(history)
        saved = ws.store.get(summary._failure_key())
        assert saved['reason'] == 'SUMMARY_OUTCOME_UNKNOWN' and 'admission_proof' not in saved
        with pytest.raises(SummaryRepairRequired):
            await summary._acreate_summary(history)
        assert len(sent) == 1
        assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 10000
        assert tokens.snapshot()['recorded_tokens'] == 0
    finally:
        await close_model(model)
