"""Native source reading through the configured SDK with no provider network."""
import json
import os
from pathlib import Path
import sqlite3

import httpx
import pytest
from langchain_openai.chat_models.base import _convert_dict_to_message

from duty_probe_agent_decisions import dump
from duty_probe_source_continuation import GEOLOGY
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_source_continuation import source_consumer_factory
from test_task_supervision import ws


@pytest.mark.parametrize('case, cap', [('literal-hit', 4), ('synonym-no-hit', 4), ('synonym-no-hit', 2)],
                         ids=['hit-wire', 'nohit-wire', 'nohit-tail-prepared-not-sent'])
async def test_source_consumer_sdk_keeps_originals_and_distinguishes_prepared_input(ws, request, monkeypatch, case, cap):
    roles = ('writer', 'text_tool', 'reviewer', 'layout')
    for role in roles:
        for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    label = case + ('-cap-two' if cap == 2 else '-wire')
    folder = Path(os.environ.get('REPORT_SOURCE_ADAPTER_OUT', str(ws.store.root / 'captures'))) / label
    folder.mkdir(parents=True, exist_ok=True)
    held, exchanges, factory_roles = {}, [], []
    script = source_consumer_factory(case, False, held).scripts['writer']
    models = {role: configured_model(ws.store, role) for role in roles}

    async def transport(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert len(exchanges) < cap, 'Local refusal must precede even mock transport'
        wire = json.loads(http_request.content)
        # The test oracle checks catalog identities in the task, as well as
        # tool results. Preserve all native message roles when decoding wire.
        messages = [_convert_dict_to_message(m) for m in wire['messages']]
        try:
            answer = script[len(exchanges) + 1](messages)
        except Exception as exc:
            dump(folder / 'mock-oracle-error.json', {'type': type(exc).__name__, 'message': str(exc)})
            raise
        message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}} for c in answer.tool_calls]
        response = {'id': 'source-consumer-mock-' + str(len(exchanges) + 1), 'object': 'chat.completion',
            'created': 1, 'model': wire['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    async def unexpected_role_transport(http_request):
        pytest.fail('Only Writer may invoke a provider in this calibration')

    for role, model in models.items():
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(transport if role == 'writer' else unexpected_role_transport)
        model.http_async_client._mounts = {}

    def original_configured_model(store, role):
        assert store is ws.store and role in models
        factory_roles.append(role)
        return models[role]

    monkeypatch.setattr(adapter, 'configured_model', original_configured_model)
    requests = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'mock-source-budget.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder,
            'writer-source-hit' if case == 'literal-hit' else 'writer-source-nohit', live=True)
    capture = json.loads((folder / 'capture.json').read_text('utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
         'request': requests.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'oracle-observations.json', held)
    request.node.user_properties.append(('source_adapter_capture', str(folder)))
    assert factory_roles == list(roles) and not result['observer_errors']
    assert all(model.http_async_client.is_closed and model.root_client.is_closed() for model in models.values())
    assert capture['oracle']['source_originals_unchanged']
    assert not capture['oracle']['setup_tail_visible'] and not capture['oracle']['first_consumer_tail_visible']
    assert capture['oracle']['status'] == 'selected_blocks_observed'
    assert capture['oracle']['semantic_status'] == 'needs_semantic_review'
    assert [r['actual_value']['blocks'][0] for r in capture['oracle']['actual_source_reads']] == GEOLOGY
    count = min(cap, 3)
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == len(exchanges) == count
    assert result['observed_request_hook_entries'] == 3
    assert result['hook_entries_without_admission'] == int(cap == 2)
    assert result['admitted_without_observed_response'] == 0
    assert len(capture['native_model_calls']) == 3
    assert {c['role'] for c in capture['native_model_calls']} == {'writer'}
    assert tokens.snapshot()['recorded_tokens'] == 2 * count
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': 2, 'known_not_sent': 1} if cap == 2 else {'settled': 3})
    wires = json.loads((folder / 'wire-requests.json').read_text('utf-8'))
    responses = json.loads((folder / 'wire-responses.json').read_text('utf-8'))
    events = [e for e in capture['phase_events'] if e['phase'] == 'native_writer_handler']
    for event, wire in zip(events, wires, strict=True):
        assert {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'} == {
            m['tool_call_id']: m['content'] for m in event['actual_tool_returns']}
    for exchange, wire, response in zip(exchanges, wires[:count], responses, strict=True):
        assert wire['body'] == exchange['wire']
        assert json.loads(response['body']) == exchange['response']
        assert response['request_sequence'] == wire['sequence']
    observed = result['source_wire_observation']
    assert observed['prepared_complete_input_indexes'] == [2]
    assert observed['response_linked_complete_wire_sequences'] == ([] if cap == 2 else [3])
    assert observed['complete_blocks_in_response_linked_wire'] is (cap != 2)
    if cap == 2:
        assert result['status'] == 'native_execution_incomplete'
        assert capture['raised_error'] or capture['runtime_result']['last_error']
        assert 'task_return' not in capture['parent']
        refused = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(refused) == 1 and refused[0]['used'] == 0 and refused[0]['response_id'] is None
        assert refused[0]['reason'] == 'Local transport admission rejected before send'
        assert GEOLOGY[1]['text'] not in json.dumps(exchanges, ensure_ascii=False)
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime_result']['last_error'] is None
        assert GEOLOGY[1]['text'] in capture['parent']['task_return']['content']
