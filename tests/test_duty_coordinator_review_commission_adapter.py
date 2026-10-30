"""C5 original SDK/native tools with synthetic HTTP responses; no provider."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai.chat_models.base import _convert_dict_to_message

from duty_probe_agent_decisions import dump
from duty_probe_coordinator_review_commission import (
    CHILD_FINAL, PARENT_FINAL,
)
from report_agent.deep_models import MODEL_REQUEST_DEADLINE_SECONDS, configured_model, connection_retry_count
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import action, result_value
from test_bounded_deadline import close_model
from test_duty_coordinator_review_commission import missing_commission_targets
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_review_consumers_adapter import response_body, wire_tool_results
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [3, 1], ids=['normal-wire', 'task-saved-before-local-refusal'])
async def test_c5_configured_sdk_preserves_assignment_and_partial_saved_state(ws, request, monkeypatch, cap):
    role_models = {'coordinator': 'deepseek-v4.1-flash', 'writer': 'glm-5.3',
                   'reviewer': 'deepseek-v4.1-flash', 'layout': 'glm-5.3',
                   'text_tool': 'deepseek-v4.1-flash'}
    for role, model_name in role_models.items():
        for key, value in {'MODEL': model_name, 'BASE_URL': 'https://offline.invalid/v1',
                           'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    # This finite SDK transport slice does not claim provider strict acceptance.
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_C5_SDK_OUT', str(ws.store.root / 'sdk-captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    models = {role: configured_model(ws.store, role) for role in role_models}
    requests, responses, exchanges, created, held = [], [], [], [], {}

    async def request_hook(http_request):
        sequence = len(requests) + 1
        http_request.extensions['c5_sdk_sequence'] = sequence
        requests.append({'sequence': sequence, 'body': json.loads(http_request.content),
                         'origin': 'pre_admission_intent_not_dispatch_proof'})
        dump(folder / 'sdk-wire-requests.json', requests)

    async def response_hook(response):
        await response.aread()
        responses.append({'request_sequence': response.request.extensions['c5_sdk_sequence'],
                          'http_status': response.status_code, 'body': response.text})
        dump(folder / 'sdk-wire-responses.json', responses)

    async def transport(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert len(exchanges) < cap
        wire = json.loads(http_request.content)
        messages = [_convert_dict_to_message(m) for m in wire['messages']]
        turn = len(exchanges)
        if turn == 0:
            fixture = json.loads((folder / 'fixture.json').read_text())
            call = deepcopy(fixture['task_call'])
            call['id'] = 'c5-sdk-review-task'
            held['fake_model_task_choice'] = deepcopy(call)
            answer = AIMessage(content='', tool_calls=[call])
        elif turn == 1:
            child_return = wire_tool_results(messages, 'task')[-1]
            assert child_return.tool_call_id == 'c5-sdk-review-task'
            assert CHILD_FINAL in str(child_return.content)
            held['actual_child_return_wire'] = child_return.model_dump()
            answer = action('read_task_supervision', 'c5-sdk-supervision')
        else:
            supervision = wire_tool_results(messages, 'read_task_supervision')[-1]
            assert supervision.tool_call_id == 'c5-sdk-supervision'
            value = result_value(supervision)
            # The nine-original-read fixture has a small inline task status.
            # Advertised paging remains a separate, explicitly unobserved path.
            assert value['ok'] is True and len(value['result']['tasks']) == 1
            held['actual_supervision_wire'] = deepcopy(value)
            answer = AIMessage(content=PARENT_FINAL)
        response = response_body(wire, answer, turn + 1)
        exchanges.append({'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    async def unexpected_role(http_request):
        pytest.fail('Only the Coordinator provider is selected; Reviewer is an explicit fake child')

    for role, model in models.items():
        # Observe the prepared request before the unchanged accounting hook can
        # refuse it. Only responses, Mock exchanges and ledger states show send.
        model.http_async_client.event_hooks['request'].insert(0, request_hook)
        model.http_async_client.event_hooks['response'].append(response_hook)
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(transport if role == 'coordinator' else unexpected_role)
        model.http_async_client._mounts = {}

    def factory(role):
        created.append(role)
        return models[role]

    def original_configured_model(store, role):
        assert store is ws.store
        return factory(role)

    monkeypatch.setattr(adapter, 'configured_model', original_configured_model)
    calls = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'c5-mock-budget.db', 10000000,
                         {'glm-5.3': 2000000, 'deepseek-v4.1-flash': 2000000})
    try:
        with request_budget(calls), token_budget(tokens):
            result = await adapter.probe_native_decision(ws, folder, 'coordinator-review-commission', live=True)
            capture = json.loads((folder / 'capture.json').read_text())
    finally:
        for model in models.values():
            await close_model(model)
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
         'request': calls.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'independent-observations.json', held)
    request.node.user_properties.append(('c5_sdk_capture', str(folder)))
    assert set(created) == set(role_models) and len(created) == len(role_models)
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert all(m.max_retries == 5 for m in models.values())
    assert connection_retry_count() == 0 and MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert result['observer_errors'] == []
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == cap
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == cap + int(cap == 1)
    assert result['hook_entries_without_admission'] == int(cap == 1)
    assert result['generated_actions_executed'] is True
    assert result['initial_original_reads_and_reviewer_are_fake'] is True
    assert {m['role'] for m in result['configured_models']} == set(role_models)
    assert capture['observer_errors'] == [] and capture['originals_unchanged'] is True
    assert len(exchanges) == len(responses) == calls.snapshot()['reserved_http_attempts'] == cap
    refused = cap == 1
    assert len(requests) == len(capture['native_model_calls']) == cap + int(refused)
    assert tokens.snapshot()['recorded_tokens'] == cap * 2
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': cap, 'known_not_sent': 1} if refused else {'settled': cap})
    events = [e for e in capture['phase_events'] if e['phase'] == 'unchanged_coordinator_handler']
    for event, wire in zip(events, requests, strict=True):
        native = {m['data']['tool_call_id']: m['data']['content']
                  for m in event['messages'] if m['type'] == 'tool'}
        assert native == {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'}
    for exchange, wire, response in zip(exchanges, requests[:cap], responses, strict=True):
        assert wire['body'] == exchange['wire']
        assert response['request_sequence'] == wire['sequence']
        assert json.loads(response['body']) == exchange['response']
        assert wire['body']['model'] == models['coordinator'].model_name
    assert len(capture['saved_tasks']) == 1 and capture['saved_reviews'] == []
    task = capture['saved_tasks'][0]
    assert missing_commission_targets(capture['fixture'], capture['saved_tasks']) == []
    for before, saved in zip(held['fake_model_task_choice']['args']['review_requirements'],
                             task['payload']['review_requirements'], strict=True):
        assert all(saved[key] == value for key, value in before.items())
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'reviewer' and task['payload']['supervision_plugin'] is None
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    assert all(e['server_context']['actor_id'] == 'content:reviewer:' + task['ref']['id'] and
               e['server_context']['assignment'] == task['payload'] for e in capture['fake_child_events'])
    assert len([e for e in capture['fake_child_events'] if e.get('received_assignment')]) == 1
    status = capture['saved_task_status'][0]
    assert status['execution_complete'] is False and len(status['remaining']) == 2
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        error = capture['raised_error'] or capture['runtime']['last_error']
        assert error and 'RequestBudgetExceeded' in str(error)
        assert capture['finals'] == [] and 'actual_supervision_wire' not in held
        assert CHILD_FINAL in str(requests[1]['body']['messages'])
        assert CHILD_FINAL not in str(requests[0]['body']['messages'])
        assert {r['request_sequence'] for r in responses} == {1}
        unsent = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        assert capture['finals'] == [PARENT_FINAL]
        assert held['actual_supervision_wire']['result']['tasks'][0] == {
            'task_ref': task['ref'], 'goal': task['payload']['goal'], **status, 'followup': None}
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'provider': 'MockTransport',
        'entrypoint': 'actual probe_native_decision C5 branch',
        'paid_HTTP': 0, 'mock_HTTP_received': cap, 'known_local_unsent': int(refused),
        'real_model_or_semantic_acceptance': False, 'default_plugin_only': True,
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
