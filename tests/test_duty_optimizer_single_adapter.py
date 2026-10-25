"""Single-feedback adapter under real SDK hooks and isolated mock budgets."""
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
from test_duty_optimizer_single import assert_single_outcome, single_optimizer_script
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [4, 1], ids=['three-responses', 'local-cap-one'])
async def test_single_adapter_sdk_budget_and_unchanged_delivery(ws, request, monkeypatch, cap):
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_OPTIMIZER_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    model = configured_model(ws.store, 'optimizer')
    held, exchanges, factory_roles = {}, [], []
    script = single_optimizer_script('candidate', held)
    folder = Path(os.environ.get('REPORT_SINGLE_ADAPTER_OUT', str(ws.store.root / 'captures'))) / str(cap)
    folder.mkdir(parents=True, exist_ok=True)

    async def transport(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        wire = json.loads(http_request.content)
        messages = [ToolMessage(content=m['content'], tool_call_id=m['tool_call_id'], name=m.get('name', ''))
                    for m in wire['messages'] if m['role'] == 'tool']
        number = len(exchanges) + 1
        answer = script[number](messages)
        message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'])}} for c in answer.tool_calls]
        response = {'id': 'single-adapter-' + str(number), 'object': 'chat.completion', 'created': 1,
            'model': wire['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(transport)
    model.http_async_client._mounts = {}

    def configured_original(store, role):
        assert store is ws.store and role == 'optimizer'
        factory_roles.append(role)
        return model
    monkeypatch.setattr(adapter, 'configured_model', configured_original)
    requests = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'mock-single-budget.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, adapter.SINGLE_OPTIMIZER_CASE, live=True)
    capture = json.loads((folder / 'capture.json').read_text())
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
         'request': requests.snapshot(), 'token': tokens.snapshot()})
    request.node.user_properties.append(('single_adapter_capture', str(folder)))
    count = 3 if cap == 4 else 1
    hooks = 3 if cap == 4 else 2
    assert factory_roles == ['optimizer'] and not result['observer_errors']
    assert len(exchanges) == result['observed_http_responses'] == requests.count == count
    assert result['observed_request_hook_entries'] == hooks
    assert result['admitted_without_observed_response'] == 0
    assert result['hook_entries_without_admission'] == (0 if cap == 4 else 1)
    assert len(capture['native_model_calls']) == hooks
    assert tokens.snapshot()['recorded_tokens'] == 2 * count
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': 3} if cap == 4 else {'known_not_sent': 1, 'settled': 1})
    returned = {m['tool_call_id']: m['content'] for m in capture['preparation_phases'][1]['native_tool_returns']}
    assert set(returned) == {'a-correction', 'a-before', 'a-evidence', 'a-source', 'candidate-index'}
    assert {m['tool_call_id']: m['content'] for m in exchanges[0]['wire']['messages'] if m['role'] == 'tool'} == returned
    observed_requests = json.loads((folder / 'wire-requests.json').read_text())
    observed_responses = json.loads((folder / 'wire-responses.json').read_text())
    for i, exchange in enumerate(exchanges):
        assert observed_requests[i]['body'] == exchange['wire']
        assert json.loads(observed_responses[i]['body']) == exchange['response']
    if cap == 4:
        assert result['status'] == 'native_observation_requires_review'
        assert_single_outcome(capture, held, 'candidate')
    else:
        assert result['status'] == 'native_execution_incomplete'
        assert capture['raised_error'] == {'type': 'RequestBudgetExceeded', 'message': 'MODEL_REQUEST_BUDGET_REACHED'}
        a = capture['assessment']
        assert a['job']['state'] == 'failed' and len(a['candidates']) == 1
        assert a['missing_feedback_ids'] == [capture['fixture']['feedback']['id']]
        assert not a['dispositions'] and not a['active_library'] and a['all_candidates_inactive']
        assert a['feedback_originals_unchanged'] and a['business_originals_unchanged']
        assert not capture['host_completion_actions'] and not capture['host_candidate_publication']
        unsent = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
        assert unsent[0]['reason'] == 'Local transport admission rejected before send'
