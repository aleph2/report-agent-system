"""Original configured SDK/ToolNode I/O with public HTTPX transport injection.

Mock responses do not establish real-model choices. The original SDK, request
hooks, shared budget, output parser and client close paths remain in use.
"""
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
from duty_probe_writer_analysis_outcome import FIELD, QUESTION, RULE
from report_agent.deep_models import configured_model, connection_retry_count, MODEL_REQUEST_DEADLINE_SECONDS
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import digest
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import result_value, tool_reply
from test_bounded_deadline import close_model
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_review_consumers_adapter import response_body
from test_duty_writer_analysis_outcome import analysis_finding, writer_analysis_script
from test_duty_writer_delivery_outcome import exact_final_inside
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [3, 2], ids=['complete-consumption', 'analysis-saved-next-request-refused'])
async def test_writer_analysis_actual_sdk_selected_packet_and_budget(ws, request, monkeypatch, cap):
    roles = {'coordinator': 'deepseek-v4.1-flash', 'writer': 'glm-5.3',
             'reviewer': 'deepseek-v4.1-flash', 'layout': 'glm-5.3', 'text_tool': 'deepseek-v4.1-flash'}
    for role, name in roles.items():
        for key, value in {'MODEL': name, 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    root = Path(os.environ.get('DUTY_ANALYSIS_SDK_EVIDENCE', str(ws.store.root / 'sdk-captures')))
    folder = root / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    prepared, received, exchanges, clients, created, held = [], [], [], [], [], {}
    finding, writer_turn = analysis_finding(True), 0
    writer_script = writer_analysis_script(True, finding, held)

    async def dispatch(http_request):
        nonlocal writer_turn
        role = http_request.extensions['writer_analysis_role']
        try:
            assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
            assert len(exchanges) < cap, 'Shared native budget must reject before MockTransport'
            assert role in {'writer', 'text_tool'}
            wire = json.loads(http_request.content)
            assert wire['model'] == roles[role] and 'data:image/' not in json.dumps(wire)
            if role == 'writer':
                assert wire.get('tools')
                writer_turn += 1
                assert writer_turn in {1, 2}, 'Unexpected extra scripted Writer request'
                answer = writer_script[writer_turn]([_convert_dict_to_message(m) for m in wire['messages']])
            else:
                assert not wire.get('tools')
                packet = json.loads(wire['messages'][1]['content'])
                assert packet['question'] == QUESTION
                assert [e['selection'] for e in packet['evidence']] == [
                    {'source_id': s, 'offset': 0, 'limit': 1} for s in ['analysis-field', 'analysis-rule']]
                fixture = json.loads((folder / 'fixture.json').read_text(encoding='utf-8'))
                for entry in packet['evidence']:
                    source_id, page = entry['selection']['source_id'], entry['observation']
                    original = fixture['source_pages'][source_id]
                    assert {key: page[key] for key in original} == original
                    assert entry['observation_sha256'] == digest(page)
                from langchain_core.messages import AIMessage
                answer = AIMessage(content=finding)
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

    from report_agent import transport_observation
    original_async_client = transport_observation.ObservedAsyncClient

    class OfflineClient(original_async_client):
        def __init__(self, *args, **kwargs):
            if any(kwargs.get(key) is not None for key in ('transport', 'mounts', 'proxy')):
                raise AssertionError('SDK fixture cannot replace a configured transport/mount/proxy policy')
            super().__init__(*args, **{**kwargs, 'transport': httpx.MockTransport(dispatch), 'trust_env': False})
            clients.append(self)

    monkeypatch.setattr(transport_observation, 'ObservedAsyncClient', OfflineClient)
    models = {role: configured_model(ws.store, role) for role in roles}
    for role, model in models.items():
        async def on_request(http_request, selected=role):
            sequence = len(prepared) + 1
            http_request.extensions.update(writer_analysis_sequence=sequence, writer_analysis_role=selected)
            prepared.append({'sequence': sequence, 'role': selected, 'body': json.loads(http_request.content),
                             'origin': 'prepared_before_local_admission_not_dispatch'})
            dump(folder / 'sdk-wire-requests.json', prepared)

        async def on_response(response, selected=role):
            await response.aread()
            received.append({'request_sequence': response.request.extensions['writer_analysis_sequence'],
                             'role': selected, 'body': response.text, 'status': response.status_code})
            dump(folder / 'sdk-wire-responses.json', received)
        model.http_async_client.event_hooks['request'].insert(0, on_request)
        model.http_async_client.event_hooks['response'].insert(0, on_response)

    def original_model(store, role):
        assert store is ws.store
        created.append(role)
        return models[role]

    def no_vision():
        raise AssertionError('No image inspection or alternate provider in this comparison fixture')

    monkeypatch.setattr(adapter, 'configured_model', original_model)
    monkeypatch.setattr(adapter, 'configured_vision_client', no_vision)
    calls = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'writer-analysis-sdk-budget.db', 20000000,
                        {'glm-5.3': 2000000, 'deepseek-v4.1-flash': 2000000})
    try:
        with request_budget(calls), token_budget(tokens):
            result = await adapter.probe_native_decision(ws, folder, adapter.WRITER_ANALYSIS_CASE, live=True)
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
    dump(folder / 'scripted-consumption.json', held)
    refused = cap == 2
    assert set(created) == set(roles) and len(created) == len(roles)
    assert len(clients) == len(models) and all(c.is_closed for c in clients)
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert all(m.max_retries == 5 for m in models.values())
    assert connection_retry_count() == 0 and MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert result['observer_errors'] == [] and result['host_completes_model_work'] is False
    assert result['initial_parent_and_source_read_choices_are_fake'] is True
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == cap
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == len(prepared) == len(actual_requests) == 3
    assert result['hook_entries_without_admission'] == int(refused)
    expected_roles = ['writer', 'text_tool', 'writer']
    assert [r['role'] for r in prepared] == expected_roles
    assert [r['role'] for r in received] == [r['role'] for r in exchanges] == expected_roles[:cap]
    assert len(received) == len(actual_responses) == len(exchanges) == cap
    assert tokens.snapshot()['recorded_tokens'] == cap * 2
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': 2, 'known_not_sent': 1} if refused else {'settled': 3})
    for own, actual in zip(prepared, actual_requests, strict=True):
        assert (own['sequence'], own['role'], own['body']) == (actual['sequence'], actual['role'], actual['body'])
    for own, actual, exchange in zip(received, actual_responses, exchanges, strict=True):
        assert own['request_sequence'] == actual['request_sequence']
        assert own['role'] == actual['role'] == exchange['role']
        assert own['status'] == actual['http_status'] == 200
        assert json.loads(own['body']) == json.loads(actual['body']) == exchange['response']
    phases = [e for e in capture['phase_events'] if e['phase'] == 'unchanged_writer_handler']
    writer_requests = [r for r in prepared if r['role'] == 'writer']
    assert len(phases) == len(writer_requests) == 2
    for phase, wire in zip(phases, writer_requests, strict=True):
        native = [(m['data']['tool_call_id'], m['data']['content']) for m in phase['messages'] if m['type'] == 'tool']
        assert native == [(m['tool_call_id'], m['content']) for m in wire['body']['messages'] if m['role'] == 'tool']
    packet = json.loads(exchanges[1]['wire']['messages'][1]['content'])
    analysis = result_value(tool_reply(messages_from_dict(phases[-1]['messages']), 'writer-analysis-call'))
    assert analysis['analysis'] == finding and analysis['evidence'] == packet['evidence']
    assert analysis['scope_note'].startswith('A bounded model observation')
    assert FIELD in json.dumps(packet) and RULE in json.dumps(packet)
    assert capture['originals_unchanged'] and capture['source_rows_unchanged'] and capture['catalog_sources_unchanged']
    assert not capture['host_completed_consumer_actions']
    task, = [o for o in capture['content_objects'] if o['ref']['type'] == 'DelegatedTask']
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'writer'
    assert task['payload']['goal'] == capture['fixture']['task_call']['args']['description']
    for phase in capture['phase_events']:
        assert phase['server_context']['actor_id'] == 'content:writer:' + task['ref']['id']
        assert phase['server_context']['assignment'] == task['payload']
    assert not (folder / 'first-mock-callback-error.json').exists()
    parents = [e['actual_child_return'] for e in capture['fake_parent_events'] if 'actual_child_return' in e]
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        assert 'MODEL_REQUEST_BUDGET_REACHED' in json.dumps(capture['raised_error']) + json.dumps(capture['runtime'])
        assert writer_turn == 1 and 'analysis_message' not in held
        assert not phases[-1].get('response')
        assert not any(exact_final_inside(p['content'], finding) for p in parents)
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        assert writer_turn == 2 and len(parents) == 1
        assert parents[0]['tool_call_id'] == 'writer-analysis-task'
        assert exact_final_inside(parents[0]['content'], finding)
