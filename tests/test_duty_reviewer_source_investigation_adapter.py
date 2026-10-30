"""Current-source investigation through actual configured SDKs, no network."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback

import httpx
from langchain_core.messages import messages_from_dict
from langchain_openai.chat_models.base import _convert_dict_to_message
import pytest

from duty_probe_agent_decisions import dump
from duty_probe_reviewer_source_investigation import CURRENT_RULE, GOAL, LIMIT, OLD_RULE
from report_agent.content_store import ContentStore
from report_agent.deep_models import configured_model, connection_retry_count, MODEL_REQUEST_DEADLINE_SECONDS
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import digest
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import result_value, tool_reply
from test_bounded_deadline import close_model
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_review_consumers_adapter import response_body
from test_duty_reviewer_source_investigation import CheckerCalibration, investigation_script
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [6, 5], ids=['selected-normal-wire', 'saved-review-before-local-refusal'])
async def test_reviewer_source_actual_sdk_handoff_and_shared_budget(ws, request, monkeypatch, cap):
    roles = {'coordinator': 'deepseek-v4.1-flash', 'writer': 'glm-5.3',
             'reviewer': 'deepseek-v4.1-flash', 'layout': 'glm-5.3', 'text_tool': 'deepseek-v4.1-flash'}
    for role, name in roles.items():
        for key, value in {'MODEL': name, 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    root = Path(os.environ.get('REPORT_REVIEWER_SOURCE_SDK_OUT', str(ws.store.root / 'sdk-captures')))
    folder = root / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    models = {role: configured_model(ws.store, role) for role in roles}
    prepared, received, exchanges, created, held = [], [], [], [], {}
    choose, checker = investigation_script(folder, True, held), CheckerCalibration()

    def hooks(role):
        async def on_request(http_request):
            sequence = len(prepared) + 1
            http_request.extensions['reviewer_source_sequence'] = sequence
            prepared.append({'sequence': sequence, 'role': role, 'body': json.loads(http_request.content),
                             'origin': 'pre_admission_intent_not_dispatch_proof'})
            dump(folder / 'sdk-wire-requests.json', prepared)

        async def on_response(response):
            await response.aread()
            received.append({'request_sequence': response.request.extensions['reviewer_source_sequence'],
                             'role': role, 'body': response.text, 'status': response.status_code})
            dump(folder / 'sdk-wire-responses.json', received)
        return on_request, on_response

    async def dispatch(http_request, role):
        try:
            assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
            assert len(exchanges) < cap, 'Local shared budget must reject before MockTransport'
            assert role in {'reviewer', 'text_tool'}
            wire = json.loads(http_request.content)
            assert wire['model'] == roles[role] and 'data:image/' not in json.dumps(wire)
            if role == 'reviewer':
                answer = choose([_convert_dict_to_message(m) for m in wire['messages']])
            else:
                answer = await checker.ainvoke([(m['role'], m['content']) for m in wire['messages']])
            raw = response_body(wire, answer, len(exchanges) + 1)
            exchanges.append({'role': role, 'wire': wire, 'response': raw})
            dump(folder / 'mock-exchanges.json', exchanges)
            return httpx.Response(200, json=raw)
        except Exception as exc:
            first = folder / 'first-mock-callback-error.json'
            if not first.exists():
                dump(first, {'role': role, 'type': type(exc).__name__, 'message': str(exc),
                             'traceback': traceback.format_exc()})
            raise

    for role, model in models.items():
        on_request, on_response = hooks(role)
        model.http_async_client.event_hooks['request'].insert(0, on_request)
        model.http_async_client.event_hooks['response'].insert(0, on_response)
        await model.http_async_client._transport.aclose()
        async def transport(http_request, selected=role):
            return await dispatch(http_request, selected)
        model.http_async_client._transport = httpx.MockTransport(transport)
        model.http_async_client._mounts = {}

    def original_model(store, role):
        assert store is ws.store
        created.append(role)
        return models[role]

    def no_vision():
        raise AssertionError('No Reviewer source fixture action selects vision or fallback')

    monkeypatch.setattr(adapter, 'configured_model', original_model)
    monkeypatch.setattr(adapter, 'configured_vision_client', no_vision)
    calls = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'reviewer-source-sdk-budget.db', 20000000,
                         {'glm-5.3': 2000000, 'deepseek-v4.1-flash': 2000000})
    try:
        with request_budget(calls), token_budget(tokens):
            result = await adapter.probe_native_decision(ws, folder, adapter.REVIEWER_SOURCE_CASE, live=True)
    finally:
        for model in models.values():
            await close_model(model)
    capture = json.loads((folder / 'capture.json').read_text(encoding='utf-8'))
    actual_requests = json.loads((folder / 'wire-requests.json').read_text(encoding='utf-8'))
    actual_responses = json.loads((folder / 'wire-responses.json').read_text(encoding='utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        attempts = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': attempts,
                                          'request': calls.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'scripted-choices.json', held)
    dump(folder / 'checker-mock-inputs.json', checker.calls)
    request.node.user_properties.append(('reviewer_source_sdk_capture', str(folder)))
    refused = cap == 5
    assert set(created) == set(roles) and len(created) == len(roles)
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert all(m.max_retries == 5 for m in models.values())
    assert connection_retry_count() == 0 and MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert result['observer_errors'] == []
    assert result['host_completes_model_work'] is False
    assert result['initial_parent_and_catalog_transition_are_fake'] is True
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == cap
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == len(prepared) == len(actual_requests) == 6
    assert result['hook_entries_without_admission'] == int(refused)
    expected_roles = ['reviewer'] * 4 + ['text_tool', 'reviewer']
    assert [r['role'] for r in prepared] == expected_roles
    assert [r['role'] for r in received] == [r['role'] for r in exchanges] == expected_roles[:cap]
    assert len(received) == len(actual_responses) == len(exchanges) == cap
    assert tokens.snapshot()['recorded_tokens'] == cap * 2
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': 5, 'known_not_sent': 1} if refused else {'settled': 6})
    for own, actual in zip(prepared, actual_requests, strict=True):
        assert own['sequence'] == actual['sequence'] and own['role'] == actual['role']
        assert own['body'] == actual['body']
    for own, actual, exchange in zip(received, actual_responses, exchanges, strict=True):
        assert own['request_sequence'] == actual['request_sequence']
        assert own['role'] == actual['role'] == exchange['role']
        assert own['status'] == actual['http_status'] == 200
        assert json.loads(own['body']) == json.loads(actual['body']) == exchange['response']
    reviewer_requests = [r for r in prepared if r['role'] == 'reviewer']
    assert len(capture['phase_events']) == len(reviewer_requests) == 5
    for phase, wire in zip(capture['phase_events'], reviewer_requests, strict=True):
        native = {m['data']['tool_call_id']: m['data']['content'] for m in phase['messages'] if m['type'] == 'tool'}
        assert native == {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'}
    cs, fixture = ContentStore(ws.store), capture['fixture']
    task, = cs.list_objects('DelegatedTask')
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['goal'] == GOAL and task['payload']['role'] == 'reviewer'
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    actor = 'content:reviewer:' + task['ref']['id']
    for phase in capture['phase_events']:
        assert phase['server_context']['role'] == 'reviewer' and phase['server_context']['actor_id'] == actor
        assert phase['server_context']['assignment'] == task['payload']
    assert capture['originals_unchanged'] and not capture['host_completion_actions']
    original_read = result_value(tool_reply(messages_from_dict(capture['phase_events'][1]['messages']),
                                           'investigation-current-original'))
    page = fixture['catalog_transition']['current_source_page']
    assert {k: original_read[k] for k in page} == page
    assert digest(page) == fixture['catalog_transition']['current_page_digest']
    assert len(checker.calls) == len(capture['checker_calls']) == 1
    packet = json.loads(checker.calls[0][-1][1])
    assert json.loads(capture['checker_calls'][0]['input'][-1][1]) == packet
    source, = [e for e in packet['evidence'] if e['kind'] == 'source_blocks']
    assert {k: source['observation'][k] for k in page} == page
    assert CURRENT_RULE in json.dumps(packet['evidence']) and OLD_RULE not in json.dumps(packet['evidence'])
    assert packet['task_id'] == task['ref']['id']
    assert packet['assignment']['review_snapshot_ref'] == fixture['snapshot_ref']
    assert packet['criteria'][0]['ref'] == fixture['refs']['criterion']
    review, = capture['saved_reviews']
    assert review['owner_id'] == actor
    item, = review['payload']['items']
    assert item['target_ref'] == fixture['refs']['claim']
    assert item['execution_state'] == 'completed' and item['verdict'] == 'not_satisfied'
    dependencies = [cs.read(r) for r in review['payload']['dependency_refs'] if r['type'] == 'SourceArtifact']
    assert dependencies and all(r['payload'] == fixture['current_source_payload'] for r in dependencies)
    perform = result_value(tool_reply([_convert_dict_to_message(m) for m in prepared[-1]['body']['messages']],
                                     'investigation-perform'))
    assert perform['review_ref'] == review['ref'] and perform['items'] == review['payload']['items']
    assert capture['task_status'][0]['execution_complete'] is True
    assert not (folder / 'first-mock-callback-error.json').exists()
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        assert 'MODEL_REQUEST_BUDGET_REACHED' in json.dumps(capture['raised_error']) + json.dumps(capture['runtime'])
        assert held['turn'] == 4 and 'final_messages' not in held
        assert 'actual_child_return' not in capture['fake_parent_events'][-1]
        assert not capture['phase_events'][-1].get('response')
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        assert held['turn'] == 5
        final = json.loads(capture['fake_parent_events'][-1]['actual_child_return']['content'])
        assert final == {'limitation': LIMIT, 'scoped_result': perform}
