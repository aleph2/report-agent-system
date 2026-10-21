"""Sibling lifecycle regressions through real SDK hooks, with no network.

Retained NFR-05 reproduction and recovery/compatibility counterexamples.
"""
import asyncio
import json

import httpx
import pytest

from report_agent.artifact_review import bounded_artifact_review_tool
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.request_budget import RequestBudgetExceeded
from report_agent.token_budget import TokenBudget, token_budget
from test_artifact_review import setup, visual
from test_bounded_deadline import offline_model, close_model
from test_task_supervision import ws


@pytest.fixture(autouse=True)
def record_artifact_trace(ws, request):
    yield
    with ws.store.connect() as db:
        rows = db.execute("SELECT key, value FROM state WHERE key LIKE 'artifact_text_work:%' "
                          "OR key LIKE 'bounded_review_attempt:%'").fetchall()
    events = [event for event in ws.store.events() if event['kind'] in {
        'bounded_operation_not_dispatched', 'evidence_analysis_unresolved',
        'evidence_analysis_reused', 'evidence_analysis_rejected_response',
        'evidence_analysis_completed'}]
    request.node.user_properties.append(('artifact_lifecycle_trace', json.dumps({
        'events': events, 'states': {key: json.loads(value) for key, value in rows}},
        ensure_ascii=False)))


@pytest.mark.parametrize('refused_locally', [True, False], ids=['zero-dispatch', 'dispatched-timeout'])
async def test_artifact_replay_preserves_actual_dispatch_classification(ws, monkeypatch, tmp_path, refused_locally):
    cs, refs, snap, export, render, source, requested = setup(ws, pages=1)
    model = offline_model(ws, monkeypatch)
    if refused_locally:
        monkeypatch.setattr('report_agent.deep_models.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    sent = []

    async def transport(request):
        sent.append(request)
        await asyncio.Event().wait()

    model.http_async_client._transport = httpx.MockTransport(transport)
    budget = TokenBudget(tmp_path / 'budget.db', 1 if refused_locally else 20000,
                         {'glm-5.3': 10000})
    try:
        with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
            receipt = visual(cs, reviewer, render, export, source, 1)
            tool = bounded_artifact_review_tool(ws, model)
            with token_budget(budget):
                with pytest.raises(RequestBudgetExceeded if refused_locally else ActionRejected) as first:
                    await tool('original', ['rule-comparison'], [receipt])
            event = next(e['data'] for e in ws.store.events() if e['kind'] == 'evidence_analysis_input')
            raw = ws.store.get('bounded_review_attempt:' + event['operation'])
            parent = ws.store.get('artifact_text_work:' + reviewer.id + ':original')
            assert len(sent) == (0 if refused_locally else 1)
            assert raw['state'] == ('not_dispatched' if refused_locally else 'unknown')
            assert raw['raw_response_received'] is False
            assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == (0 if refused_locally else 10000)
            if not refused_locally:
                assert str(first.value).startswith('EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED')
                assert raw['result']['usage'] is None
            if refused_locally:
                proof = next(e['data']['proof'] for e in ws.store.events()
                             if e['kind'] == 'bounded_operation_not_dispatched')
                assert proof['admitted_http_attempts'] == 0
                assert proof['reason_code'] == 'AUTHORIZED_TOKEN_BUDGET_REACHED'
                assert parent['state'] == 'not_dispatched'
                assert parent['admission_proof'] == raw['admission_proof'] == proof
                assert len(raw['linked_reservation_keys']) == 2
            with pytest.raises(ActionRejected) as replay:
                await tool('original', ['rule-comparison'], [receipt])
            assert len(sent) == (0 if refused_locally else 1)
            assert not cs.list_objects('ReviewRecord')
            assert ws.store.get('artifact_text_work:' + reviewer.id + ':original') == parent
            # Known refusal must never be labelled an unknown provider outcome.
            expected = 'NOT_DISPATCHED' if refused_locally else 'OUTCOME_UNRESOLVED'
            assert expected in str(replay.value), json.dumps({
                'actual_error': str(replay.value), 'raw': raw, 'outer': parent,
                'dispatched': len(sent), 'budget': budget.snapshot()}, ensure_ascii=False)
            if refused_locally:
                detail = json.loads(str(replay.value).split(': ', 1)[1])
                assert detail['raw_response_received'] is False and detail['usage'] is None
                # Another ID must not enable this caller to rearm the same raw request.
                with pytest.raises(ActionRejected, match='^EVIDENCE_ANALYSIS_NOT_DISPATCHED'):
                    await tool('another-id', ['rule-comparison'], [receipt])
                with pytest.raises(ActionRejected, match='^ARTIFACT_TEXT_WORK_NOT_DISPATCHED'):
                    await tool('another-id', ['rule-comparison'], [receipt])
                blocked = ws.store.get('artifact_text_work:' + reviewer.id + ':another-id')
                assert blocked['result'] == {'proof_origin': 'prior_raw_receipt',
                    'raw_operation': event['operation'], 'new_provider_attempt': False}
                assert ws.store.get('bounded_review_attempt:' + event['operation']) == raw
                assert ws.store.get('artifact_text_work:' + reviewer.id + ':original') == parent
                assert not sent
    finally:
        await close_model(model)


@pytest.mark.parametrize('legacy', [False, True])
async def test_artifact_unproven_budget_exception_is_not_promoted_to_unsent(ws, legacy):
    from test_bounded_review import Model
    cs, refs, snap, export, render, source, requested = setup(ws, pages=1)
    model = Model(RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED'))
    with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
        receipt = visual(cs, reviewer, render, export, source, 1)
        tool = bounded_artifact_review_tool(ws, model)
        with pytest.raises(RequestBudgetExceeded):
            await tool('unproven', ['rule-comparison'], [receipt])
        key = 'artifact_text_work:' + reviewer.id + ':unproven'
        prior = ws.store.get(key)
        if legacy:
            prior = {'request_hash': prior['request_hash']}
            ws.store.set(key, prior)
        with pytest.raises(ActionRejected, match='^ARTIFACT_TEXT_WORK_OUTCOME_UNRESOLVED'):
            await tool('unproven', ['rule-comparison'], [receipt])
        with pytest.raises(ActionRejected, match='^OPERATION_CONFLICT'):
            await tool('unproven', ['rule-comparison'], [receipt, receipt])
        assert len(model.calls) == 1 and ws.store.get(key) == prior
        assert not cs.list_objects('ReviewRecord')
        assert not any(e['kind'] == 'bounded_operation_not_dispatched' for e in ws.store.events())


async def test_artifact_cancelled_dispatch_is_preserved_without_replay(ws, monkeypatch, tmp_path):
    cs, refs, snap, export, render, source, requested = setup(ws, pages=1)
    model = offline_model(ws, monkeypatch)
    monkeypatch.setattr('report_agent.deep_models.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    sent = []
    dispatched = asyncio.Event()

    async def transport(request):
        sent.append(request)
        dispatched.set()
        await asyncio.Event().wait()

    model.http_async_client._transport = httpx.MockTransport(transport)
    budget = TokenBudget(tmp_path / 'budget.db', 20000, {'glm-5.3': 10000})
    try:
        with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
            receipt = visual(cs, reviewer, render, export, source, 1)
            tool = bounded_artifact_review_tool(ws, model)
            with token_budget(budget):
                work = asyncio.create_task(tool('cancelled', ['rule-comparison'], [receipt]))
                await dispatched.wait()
                work.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await work
            with pytest.raises(ActionRejected, match='^ARTIFACT_TEXT_WORK_OUTCOME_UNRESOLVED'):
                await tool('cancelled', ['rule-comparison'], [receipt])
            assert len(sent) == 1 and not cs.list_objects('ReviewRecord')
            assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == 10000
            assert not any(e['kind'] == 'bounded_operation_not_dispatched' for e in ws.store.events())
    finally:
        await close_model(model)
