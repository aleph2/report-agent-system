"""Actual Reviewer SDK boundary with recorded checker data and isolated budgets."""
import json
import os
from pathlib import Path
import sqlite3

import httpx
import pytest
from langchain_core.messages import ToolMessage

from duty_probe_agent_decisions import dump
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_reviewer_consumer import reviewer_script
from test_task_supervision import ws


@pytest.mark.parametrize('case, exhausted', [('full', False), ('missing', False), ('missing', True)],
                         ids=['full-wire', 'missing-wire', 'missing-zero-dispatch'])
async def test_reviewer_consumer_sdk_preserves_actual_result_and_local_refusal(ws, request, monkeypatch, case, exhausted):
    for role in ('WRITER', 'REVIEWER', 'LAYOUT'):
        for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    label = case + ('-zero-dispatch' if exhausted else '-wire')
    folder = Path(os.environ.get('REPORT_REVIEWER_ADAPTER_OUT', str(ws.store.root / 'captures'))) / label
    folder.mkdir(parents=True, exist_ok=True)
    held, exchanges, factory_roles = {'folder': folder}, [], []
    script = reviewer_script(ws, case, held)
    models = {role: configured_model(ws.store, role) for role in ('writer', 'reviewer', 'layout')}

    async def transport(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert not exhausted, 'Exhausted local budget must not reach even mock transport'
        wire = json.loads(http_request.content)
        messages = [ToolMessage(content=m['content'], tool_call_id=m['tool_call_id'], name=m.get('name', ''))
                    for m in wire['messages'] if m['role'] == 'tool']
        # Decode only to choose the mock response; never replace native inputs.
        answer = script[1](messages)
        assert not answer.tool_calls
        response = {'id': 'reviewer-consumer-mock', 'object': 'chat.completion', 'created': 1,
            'model': wire['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': answer.content},
                                                'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    async def unexpected_role_transport(http_request):
        pytest.fail('Only the Reviewer consumer may invoke a provider in this fixture')

    for role, model in models.items():
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(transport if role == 'reviewer' else unexpected_role_transport)
        model.http_async_client._mounts = {}

    def original_configured_model(store, role):
        assert store is ws.store and role in models
        factory_roles.append(role)
        return models[role]

    monkeypatch.setattr(adapter, 'configured_model', original_configured_model)
    requests = RequestBudget(1 if exhausted else 4)
    if exhausted:
        requests.reserve()  # Pre-consumed test host budget, not a provider call.
    tokens = TokenBudget(ws.store.root / 'mock-reviewer-budget.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, 'reviewer-consumer-' + case, live=True)
    capture = json.loads((folder / 'capture.json').read_text('utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
         'request': requests.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'oracle-observations.json', held)
    request.node.user_properties.append(('reviewer_adapter_capture', str(folder)))
    assert factory_roles == ['writer', 'reviewer', 'layout'] and not result['observer_errors']
    assert all(model.http_async_client.is_closed and model.root_client.is_closed() for model in models.values())
    assert result['fixture_producer_calls'] == 1 and result['later_checker_calls'] == 0
    assert result['historic_producer_usage_is_not_new_usage']
    assert len(capture['checker_calls']) == 1 and len(capture['saved_reviews']) == 1
    assert capture['originals_unchanged'] and not capture['host_completion_actions']
    assert capture['saved_task_status'][0]['execution_complete'] is (case == 'full')
    assert bool(capture['saved_task_status'][0]['remaining']) is (case == 'missing')
    assert not capture['saved_task_status'][0]['semantic_coverage_verified']
    count = 0 if exhausted else 1
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == len(exchanges) == count
    assert result['observed_request_hook_entries'] == 1
    assert result['hook_entries_without_admission'] == int(exhausted)
    assert result['admitted_without_observed_response'] == 0
    assert len(capture['native_model_calls']) == 1
    assert capture['native_model_calls'][0]['role'] == 'reviewer'
    assert tokens.snapshot()['recorded_tokens'] == 2 * count
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'known_not_sent': 1} if exhausted else {'settled': 1})
    actual_returns = {m['tool_call_id']: m['content'] for m in capture['phase_events'][1]['native_tool_returns']}
    assert set(actual_returns) == {'recorded-checker'}
    observed_requests = json.loads((folder / 'wire-requests.json').read_text('utf-8'))
    observed_responses = json.loads((folder / 'wire-responses.json').read_text('utf-8'))
    wire = observed_requests[0]['body']
    assert {m['tool_call_id']: m['content'] for m in wire['messages'] if m['role'] == 'tool'} == actual_returns
    if exhausted:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        task_failure=json.loads(capture['parent']['task_return']["content"])
        task_failure=task_failure.get('metadata',task_failure)
        assert task_failure['ok'] is False and task_failure['code']=='DELEGATED_EXECUTION_FAILED'
        assert task_failure['error']['type']=='RequestBudgetExceeded'
        assert task_failure['error']['message']=='MODEL_REQUEST_BUDGET_REACHED'
        assert not capture['consumer_finals'] and not observed_responses
        assert len(rows) == 1 and rows[0]['used'] == 0 and rows[0]['response_id'] is None
        assert rows[0]['reason'] == 'Local transport admission rejected before send'
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        assert not held.get('oracle_failures')
        assert wire == exchanges[0]['wire']
        assert json.loads(observed_responses[0]['body']) == exchanges[0]['response']
        parent = capture['parent']['supervision']['result']['tasks'][0]
        assert parent['requirements'] == capture['saved_task_status'][0]['requirements']
        assert parent['remaining'] == capture['saved_task_status'][0]['remaining']
        assert parent['execution_complete'] is (case == 'full')
        if case == 'missing':
            assert len(capture['parent']['pages']) == 2
        assert capture['semantic_status'] == 'not_semantically_assessed'
