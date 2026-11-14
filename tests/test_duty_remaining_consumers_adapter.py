"""Configured SDK fidelity and local refusals for two native consumer fixtures."""
import json
import os
from pathlib import Path
import sqlite3

import httpx
import pytest
from langchain_openai.chat_models.base import _convert_dict_to_message

from duty_probe_agent_decisions import dump
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_coordinator_requirements import coordinator_requirements_script
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_writer_revision_consumer import revision_consumer_factory
from test_task_supervision import ws


@pytest.mark.parametrize('case,cap', [('coordinator-requirements', 4), ('coordinator-requirements', 1),
                                    ('writer-revision-consumer', 4), ('writer-revision-consumer', 2)],
                         ids=['requirements-wire', 'requirements-commit-before-refusal',
                              'revision-wire', 'revision-saved-before-refusal'])
async def test_native_remaining_consumer_sdk_fidelity_and_saved_state(ws, request, monkeypatch, case, cap):
    revision = case == 'writer-revision-consumer'
    active_role = 'writer' if revision else 'coordinator'
    roles = ('writer', 'reviewer', 'layout') if revision else ('writer', 'text_tool', 'reviewer', 'layout', 'coordinator')
    for role in roles:
        for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_REMAINING_ADAPTER_OUT', str(ws.store.root / 'captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    held, exchanges, factory_roles = {}, [], []
    script = revision_consumer_factory(True, held).scripts['writer'] if revision else coordinator_requirements_script(ws, 'complete', held)
    start = 3 if revision else 1
    models = {role: configured_model(ws.store, role) for role in roles}

    async def transport(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert len(exchanges) < cap, 'Local budget refusal must precede mock dispatch'
        wire = json.loads(http_request.content)
        messages = [_convert_dict_to_message(m) for m in wire['messages']]
        try:
            answer = script[start + len(exchanges)](messages)
        except Exception as exc:
            dump(folder / 'mock-oracle-error.json', {'type': type(exc).__name__, 'message': str(exc)})
            raise
        message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}} for c in answer.tool_calls]
        response = {'id': 'remaining-consumer-mock-' + str(len(exchanges) + 1), 'object': 'chat.completion',
            'created': 1, 'model': wire['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    async def unexpected_role_transport(http_request):
        pytest.fail('Only the selected consumer may invoke a provider in this fixture')

    for role, model in models.items():
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(transport if role == active_role else unexpected_role_transport)
        model.http_async_client._mounts = {}

    def original_configured_model(store, role):
        assert store is ws.store and role in models
        factory_roles.append(role)
        return models[role]

    monkeypatch.setattr(adapter, 'configured_model', original_configured_model)
    requests = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'mock-remaining-budget.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, case, live=True)
    capture = json.loads((folder / 'capture.json').read_text('utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
         'request': requests.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'oracle-observations.json', held)
    request.node.user_properties.append(('remaining_adapter_capture', str(folder)))
    # Managed context may construct Coordinator first for its summary service;
    # the verified contract is the exact role set and one client per role.
    assert set(factory_roles) == set(roles) and len(factory_roles) == len(roles)
    assert [m['role'] for m in result['configured_models']] == factory_roles
    assert not result['observer_errors']
    assert all(model.http_async_client.is_closed and model.root_client.is_closed() for model in models.values())
    count = min(cap, 3)
    refused = cap < 3
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == len(exchanges) == count
    assert result['hook_entries_without_admission'] == int(refused)
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == count + int(refused)
    assert tokens.snapshot()['recorded_tokens'] == 2 * count
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': count, 'known_not_sent': 1} if refused else {'settled': count})
    assert len(capture['native_model_calls']) == count + int(refused)
    assert {c['role'] for c in capture['native_model_calls']} == {active_role}
    wires = json.loads((folder / 'wire-requests.json').read_text('utf-8'))
    responses = json.loads((folder / 'wire-responses.json').read_text('utf-8'))
    phase = 'native_writer_handler' if revision else 'unchanged_coordinator_handler'
    events = [e for e in capture['phase_events'] if e['phase'] == phase]
    for event, wire in zip(events, wires, strict=True):
        assert {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'} == {
            m['tool_call_id']: m['content'] for m in event['actual_tool_returns' if revision else 'native_tool_returns']}
    for exchange, wire, response in zip(exchanges, wires[:count], responses, strict=True):
        assert wire['body'] == exchange['wire']
        assert json.loads(response['body']) == exchange['response']
        assert response['request_sequence'] == wire['sequence']
    if revision:
        oracle = capture['oracle']
        assert result['fixture_producer_calls'] == 2 and result['later_text_calls'] == 0
        assert result['historic_producer_usage_is_not_new_usage']
        assert oracle['original_v1_unchanged'] and oracle['source_originals_unchanged']
        assert oracle['status'] == 'exact_revision_saved'
        saved = oracle['current_node']
        assert saved['payload'] == capture['fixture']['expected_payload']
        assert saved['previous_ref'] == capture['host_diagnostic_held']['target']
        for key in ('body', 'kind', 'claim_kind'):
            assert saved['payload'][key] == capture['fixture']['initial_payload'][key]
        assert oracle['semantic_status'] == 'needs_semantic_review'
    else:
        assert capture['originals_unchanged']
        assert len(capture['criteria']) == len(capture['new_objects']) == 1
        assert capture['criteria'][0]['payload'] == held['submitted']
        assert capture['tasks'] == capture['handoffs'] == capture['issues'] == []
    if refused:
        if revision:
            assert result['status'] == 'native_observation_requires_review'
            assert capture['raised_error'] is None and capture.get('runtime_result',capture.get('runtime'))['last_error'] is None
            task_failure=json.loads(capture['parent']['task_return']["content"])
            task_failure=task_failure.get('metadata',task_failure)
            assert task_failure['ok'] is False and task_failure['code']=='DELEGATED_EXECUTION_FAILED'
            assert task_failure['error']['type']=='RequestBudgetExceeded'
            assert task_failure['error']['message']=='MODEL_REQUEST_BUDGET_REACHED'
        else:
            assert result['status']=='native_execution_incomplete'
            assert capture['raised_error'] or capture.get('runtime_result',capture.get('runtime'))['last_error']
            assert 'task_return' not in capture.get('parent',{})
        if not revision:
            assert capture['finals'] == []
        unsent = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
        assert unsent[0]['reason'] == 'Local transport admission rejected before send'
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture.get('runtime_result', capture.get('runtime'))['last_error'] is None
        if revision:
            assert held['adopted_ref']['id'] in capture['parent']['task_return']['content']
        else:
            assert capture['finals'] and held['actual_readback'] == capture['criteria'][0]
