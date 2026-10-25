"""Actual R11 adapter, isolated budgets and SDK transport; no paid requests.

The scripted provider controls only test responses. The native learning worker,
adapter, model binding, ToolNode and accounting hooks remain the real code.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys

import httpx
import pytest
from langchain_core.messages import ToolMessage

from duty_probe_agent_decisions import dump
from duty_probe_optimizer_outcome import CONDITIONS, STRATEGY
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_optimizer_outcome import optimizer_script
from test_task_supervision import ws


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import probe_duty_decisions as adapter


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """MockTransport needs no socket; keep this safe when run outside verify."""
    for name in ('connect', 'connect_ex', 'sendto'):
        original = getattr(socket.socket, name)

        def denied(sock, *args, _original=original, **kwargs):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                pytest.fail('External network forbidden in Optimizer adapter tests')
            return _original(sock, *args, **kwargs)

        monkeypatch.setattr(socket.socket, name, denied)


def artifact_folder(ws, label):
    root = Path(os.environ.get('REPORT_OPTIMIZER_ADAPTER_OUT', str(ws.store.root / 'adapter-captures')))
    folder = root / label
    folder.mkdir(parents=True, exist_ok=True)
    dump(folder / 'test-source-hashes.json', {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in (Path(__file__), Path(adapter.__file__), ROOT / 'tests/duty_probe_optimizer_outcome.py',
                   ROOT / 'tests/test_duty_optimizer_outcome.py')})
    return folder


def read_capture(folder):
    return json.loads((folder / 'capture.json').read_text(encoding='utf-8'))


def assert_preparation_and_originals(capture):
    phases = capture['preparation_phases']
    assert phases[0]['phase'] == 'explicit_fake_read_setup'
    setup = phases[0]['action']['tool_calls']
    assert len(setup) == 6 and all(c['name'] == 'read_learning_feedback' for c in setup)
    expected_ids = {label + '-' + field for label in ('a', 'b') for field in ('correction', 'before', 'evidence')}
    assert {c['id'] for c in setup} == expected_ids
    assert all(p['phase'] == 'unchanged_consumer_handler' for p in phases[1:])
    assert {m['tool_call_id'] for m in phases[1]['native_tool_returns']} == expected_ids
    assert all(m['status'] == 'success' for m in phases[1]['native_tool_returns'])
    assessment = capture['assessment']
    assert assessment['feedback_originals_unchanged'] and assessment['business_originals_unchanged']
    assert assessment['active_assignment_after_worker'] is None
    assert assessment['all_candidates_inactive'] and not assessment['active_library']
    assert not assessment['unexpected_feedback_ids']
    assert all(link['valid'] for link in assessment['candidate_links'])
    assert assessment['job']['quality_verified'] is False
    assert all(d['quality_verified'] is False for d in assessment['dispositions'].values())
    assert assessment['semantic_status'] == 'not_semantically_assessed'
    assert not assessment['unsupported_control_assertions']
    assert all(c['boundary'] == 'native_optimizer_decision' for c in capture['native_model_calls'])
    assert not capture['host_completion_actions'] and not capture['host_candidate_publication']
    return assessment


def assert_saved_candidate_and_dispositions(capture, *, completed):
    assessment = assert_preparation_and_originals(capture)
    fixture = capture['fixture']
    a, b = fixture['feedback_a']['id'], fixture['feedback_b']['id']
    assert len(assessment['candidates']) == 1
    candidate = assessment['candidates'][0]
    assert candidate['version'] == 1 and candidate['kind'] == 'customer_preference'
    assert candidate['customer'] == fixture['customer'] and candidate['project'] == ''
    assert candidate['strategy'] == STRATEGY and candidate['conditions'] == CONDITIONS
    assert candidate['feedback_ids'] == [a]
    assert assessment['dispositions'][b]['outcome'] == 'insufficient_evidence'
    if completed:
        assert capture['raised_error'] is None and capture['runtime_result']['state'] == 'completed'
        assert assessment['job']['state'] == 'completed'
        assert not assessment['missing_feedback_ids']
        assert set(assessment['dispositions']) == {a, b}
        assert assessment['dispositions'][a]['outcome'] == 'candidate'
        assert assessment['dispositions'][a]['candidate'] == {'id': candidate['id'], 'version': candidate['version']}
        assert all(row['status'] == 'completed' for row in assessment['queue'])
    else:
        assert capture['raised_error'] == {'type': 'RequestBudgetExceeded', 'message': 'MODEL_REQUEST_BUDGET_REACHED'}
        assert capture['runtime_result'] is None and assessment['job']['state'] == 'failed'
        assert assessment['missing_feedback_ids'] == [a]
        assert set(assessment['dispositions']) == {b}
        assert all(row['status'] == 'failed' for row in assessment['queue'])


async def test_actual_optimizer_adapter_offline_uses_three_fake_consumers(ws, request, monkeypatch):
    def unexpected_factory(*args, **kwargs):
        pytest.fail('Offline adapter must not construct a configured model client')
    monkeypatch.setattr(adapter, 'configured_model', unexpected_factory)
    folder = artifact_folder(ws, 'offline')
    result = await adapter.probe_native_decision(ws, folder, adapter.OPTIMIZER_CASE, live=False)
    request.node.user_properties.append(('optimizer_adapter_capture', str(folder)))
    capture = read_capture(folder)
    assert result['status'] == 'native_observation_requires_review'
    assert result['mode'] == 'offline_fake_native' and not result['observer_errors']
    assert result['observed_http_requests'] == result['observed_http_responses'] == 0
    assert result['observed_request_hook_entries'] == 0 and not result['configured_models']
    assert len(capture['native_model_calls']) == 3
    assert_saved_candidate_and_dispositions(capture, completed=True)


@pytest.mark.parametrize('cap', [4, 1], ids=['three-responses', 'local-cap-one'])
async def test_actual_optimizer_adapter_configured_sdk_and_shared_budgets(ws, request, monkeypatch, cap):
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_OPTIMIZER_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    model = configured_model(ws.store, 'optimizer')
    held, transport_calls, factory_calls = {}, [], []
    script = optimizer_script('candidate-and-insufficient', held)
    folder = artifact_folder(ws, 'sdk-cap-' + str(cap))

    async def transport(http_request):
        wire = json.loads(http_request.content)
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        # Provider-side decoding chooses the mock answer only. Reconstructed
        # messages never replace application inputs or actual ToolNode outputs.
        messages = [ToolMessage(content=m['content'], tool_call_id=m['tool_call_id'], name=m.get('name', ''))
                    for m in wire['messages'] if m['role'] == 'tool']
        number = len(transport_calls) + 1
        answer = script[number](messages)
        response_message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            response_message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'])}} for c in answer.tool_calls]
        raw_response = {'id': 'optimizer-adapter-mock-' + str(number), 'object': 'chat.completion', 'created': 1,
            'model': wire['model'], 'choices': [{'index': 0,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop', 'message': response_message}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        transport_calls.append({'sequence': number, 'wire': wire, 'response': raw_response})
        dump(folder / 'mock-transport-calls.json', transport_calls)
        return httpx.Response(200, json=raw_response)

    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(transport)
    model.http_async_client._mounts = {}

    def original_model_with_mock_transport(store, role):
        assert store is ws.store and role == 'optimizer'
        factory_calls.append(role)
        return model  # Original configured BaseChatModel; no replacement adapter/model loop.

    monkeypatch.setattr(adapter, 'configured_model', original_model_with_mock_transport)
    requests = RequestBudget(cap)
    # Synthetic response upper bound, solely for this temporary test ledger.
    # This is not the real provider bound or an authorization change.
    tokens = TokenBudget(ws.store.root / 'isolated-mock-token-ledger.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, adapter.OPTIMIZER_CASE, live=True)
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget-observation.json', {'test_only': True, 'ledger_path': str(tokens.path),
         'request': requests.snapshot(), 'token': tokens.snapshot(), 'rows': rows})
    request.node.user_properties.append(('optimizer_adapter_capture', str(folder)))
    capture = read_capture(folder)
    expected_responses = 3 if cap == 4 else 1
    expected_hook_entries = 3 if cap == 4 else 2
    assert factory_calls == ['optimizer']
    assert result['mode'] == 'live' and not result['observer_errors']
    assert result['configured_models'][0]['model'] == 'glm-5.3'
    assert result['configured_models'][0]['sdk_max_retries'] == 5
    assert len(transport_calls) == result['observed_http_responses'] == expected_responses
    assert result['admitted_http_attempts'] == requests.count == expected_responses
    assert result['observed_request_hook_entries'] == expected_hook_entries
    assert result['hook_entries_without_admission'] == (0 if cap == 4 else 1)
    assert result['admitted_without_observed_response'] == 0
    assert len(capture['native_model_calls']) == expected_hook_entries
    assert tokens.snapshot()['recorded_tokens'] == 2 * expected_responses
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': 3} if cap == 4 else {'known_not_sent': 1, 'settled': 1})
    assert len(rows) == expected_hook_entries
    settled = [row for row in rows if row['state'] == 'settled']
    assert [row['response_id'] for row in settled] == ['optimizer-adapter-mock-' + str(i) for i in range(1, expected_responses + 1)]
    if cap == 1:
        unsent = [row for row in rows if row['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
        assert unsent[0]['reason'] == 'Local transport admission rejected before send'
    native_returns = {m['tool_call_id']: m['content'] for m in capture['preparation_phases'][1]['native_tool_returns']}
    assert {m['tool_call_id']: m['content'] for m in transport_calls[0]['wire']['messages'] if m['role'] == 'tool'} == native_returns
    observed_requests = json.loads((folder / 'wire-requests.json').read_text(encoding='utf-8'))
    observed_responses = json.loads((folder / 'wire-responses.json').read_text(encoding='utf-8'))
    for index, entry in enumerate(transport_calls):
        assert observed_requests[index]['body'] == entry['wire']
        assert json.loads(observed_responses[index]['body']) == entry['response']
        names = {tool['function']['name'] for tool in entry['wire']['tools']}
        assert {'read_learning_feedback', 'propose_experience', 'record_feedback_disposition', 'analyze_learning_material'} <= names
        assert not {'release', 'commit_objects', 'task'} & names
    assert result['status'] == ('native_observation_requires_review' if cap == 4 else 'native_execution_incomplete')
    assert_saved_candidate_and_dispositions(capture, completed=cap == 4)
