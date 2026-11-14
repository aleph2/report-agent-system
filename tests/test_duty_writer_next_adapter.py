"""SDK Mock fidelity for P14 guidance and P06 two-candidate consumers.

The real adapter, configured clients, native graph, tools and isolated budgets
run unchanged. Only provider responses are scripted; no external requests.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback

import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_openai.chat_models.base import _convert_dict_to_message

from duty_probe_agent_decisions import dump
from duty_probe_writer_guidance import (
    APPLICABLE_TASK, ASSIGNMENT_BASE, INAPPLICABLE_TASK, NO_USE_FINAL,
    SOURCE, TARGET, TRUE_FINAL, USE_REASON,
)
from duty_probe_writer_multi_consumer import GUIDE, SITE_B
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import digest
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_writer_guidance import writer_guidance_script
from test_duty_writer_multi_consumer import fake_batch, multi_consumer_factory
from test_task_supervision import ws


ROOT = Path(__file__).resolve().parents[1]
# deep_runtime.build_agent constructs these subagent services and text_tool;
# both helpers supply their own explicitly fake Coordinator. Order is not a contract.
CONFIGURED_ROLES = {'writer', 'text_tool', 'reviewer', 'layout'}


def original_source_hashes():
    paths = [Path(__file__), Path(adapter.__file__),
        ROOT / 'tests/duty_probe_writer_guidance.py', ROOT / 'tests/test_duty_writer_guidance.py',
        ROOT / 'tests/duty_probe_writer_multi_consumer.py', ROOT / 'tests/test_duty_writer_multi_consumer.py',
        ROOT / 'src/report_agent/deep_runtime.py', ROOT / 'src/report_agent/deep_models.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def native_tools(event, multi):
    messages = event['actual_tool_returns'] if multi else [m['data'] for m in event['messages'] if m['type'] == 'tool']
    return {m['tool_call_id']: m['content'] for m in messages}


def assert_guidance_state(capture, held, variant, refused):
    fixture = capture['fixture']
    assert capture['originals_unchanged'] and capture['saved_objects'] == fixture['originals']
    assert capture['guidance_versions'] == fixture['guidance_versions']
    assert capture['feedback'] == fixture['feedback_originals']
    assert not capture['host_completed_consumer_actions']
    assert capture['semantic_status'] == 'not_semantically_assessed'
    assert fixture['original_task']['payload']['goal'] == ASSIGNMENT_BASE
    assert APPLICABLE_TASK not in fixture['original_task']['payload']['goal']
    assert INAPPLICABLE_TASK not in fixture['original_task']['payload']['goal']
    assert held['actual_source']['payload']['content'] == SOURCE
    assert held['actual_target']['payload'] == TARGET
    assert held['actual_target']['ref'] == fixture['target_ref']
    assert held['actual_target']['owner_id'] == fixture['writer_actor']['id']
    expected_uses = [] if variant == 'inapplicable' else [{
        'customer': fixture['customer'], 'project': fixture['project'],
        'id': fixture['guidance']['id'], 'version': 1, 'target': fixture['target_ref'],
        'reason': USE_REASON, 'actor': fixture['writer_actor']['id']}]
    assert capture['declared_uses'] == expected_uses
    expected_final = NO_USE_FINAL if variant == 'inapplicable' else TRUE_FINAL
    assert capture['finals'] == ([] if refused else [expected_final])
    if not refused:
        assert expected_final in capture['parent']['actual_task_return']['content']


def assert_multi_state(capture, held, refused):
    oracle = capture['oracle']
    expected = fake_batch()
    public = capture['host_diagnostic_held']['first_public_value']
    receipt = oracle['initial_receipt']
    packet = held['producer_packet']
    assert receipt['state'] == 'completed'
    assert receipt['result']['payloads'] == expected['payloads']
    assert receipt['result']['generation_notes'] == expected['generation_notes']
    assert receipt['result']['text_work_id'] == public['text_work_id'] == oracle['initial_receipt_id']
    assert receipt['result']['actor_id'] == public['actor_id'] == packet['actor']['id']
    assert receipt['result']['task_id'] == public['task_id'] == packet['actor']['task_id']
    assert public['state'] == 'completed' and public['semantic_correctness_verified'] is False
    assert public['outputs']['total'] == 2 and public['outputs']['complete']
    assert public['generation_notes'] == expected['generation_notes']
    assert len(public['outputs']['entries']) == 2
    for i, entry in enumerate(public['outputs']['entries']):
        assert entry['index'] == i and entry['body_deferred'] and 'body' not in entry
        assert entry['original_path'] == ['payloads', i]
        assert entry['payload_digest'] == digest(expected['payloads'][i])
        for key in ('kind', 'claim_kind', 'qualifiers'):
            assert entry[key] == expected['payloads'][i][key]
    materials = [e['object'] for e in packet['evidence'] if e['kind'] == 'saved_object']
    assert [o['payload']['content'] for o in materials] == [GUIDE, SITE_B]
    source_originals = [o for o in capture['fixture']['originals'] if o['ref']['type'] == 'SourceArtifact']
    assert materials == source_originals
    assert expected['payloads'][0]['body']['columns'] == capture['fixture']['table_columns']
    assert expected['payloads'][0]['body']['rows'] == capture['fixture']['table_rows']
    assert expected['payloads'][0]['body']['footnote'] == capture['fixture']['original_footnote']
    assert oracle['originals_unchanged'] and oracle['initial_receipt_unchanged'] and oracle['no_review_or_export']
    assert not capture['initial_producer_is_recorded_fixture'] and not capture['host_completion_actions']
    assert oracle['semantic_status'] == 'needs_semantic_review'
    assert oracle['other_successful_content_actions'] == []
    assert oracle['adopted_indexes'] == ([] if refused else [0, 1])
    assert oracle['unadopted_indexes'] == ([0, 1] if refused else [])
    assert len(oracle['all_content_nodes']) == len(oracle['adoptions']) == (0 if refused else 2)
    assert oracle['status'] == ('initial_batch_not_adopted' if refused else 'exact_initial_batch_adopted')
    if not refused:
        assert len(held['pages']) == 1
        assert held['recovered']['payloads'] == expected['payloads']
        for item in oracle['adoptions']:
            index, node = item['index'], item['saved_node']
            assert item['exact'] and item['text_work_id'] == public['text_work_id']
            assert node['payload'] == expected['payloads'][index]
            assert node['owner_id'] == public['actor_id'] and node['task_id'] == public['task_id']
            assert node['ref'] == held['adopted_refs']['candidate-' + str(index)]
        parent = json.loads(capture['parent']['task_return']['content'])
        assert parent['adopted_refs'] == held['adopted_refs'] and parent['unadopted_indexes'] == []
        assert parent['technical_limit'] == SITE_B


@pytest.mark.parametrize('case,cap', [
    ('writer-guidance-applicable', 4), ('writer-guidance-inapplicable', 4),
    ('writer-guidance-applicable', 1), ('writer-multi-consumer', 4), ('writer-multi-consumer', 1),
], ids=['guidance-use-and-final', 'guidance-not-applicable', 'guidance-use-before-local-refusal',
        'multi-two-index-adoption', 'multi-producer-before-local-refusal'])
async def test_writer_next_adapter_sdk_wire_and_shared_budget(ws, request, monkeypatch, case, cap):
    multi = case == 'writer-multi-consumer'
    variant = 'inapplicable' if case.endswith('-inapplicable') else 'applicable'
    expected_count = 4 if multi else (1 if variant == 'inapplicable' else 2)
    refused = cap < expected_count
    count = min(cap, expected_count)
    for role in CONFIGURED_ROLES:
        for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_WRITER_NEXT_ADAPTER_OUT', str(ws.store.root / 'captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    initial_hashes = original_source_hashes()
    dump(folder / 'source-hashes-before.json', initial_hashes)
    held, exchanges, factory_roles = {}, [], []
    scripts = (multi_consumer_factory(True, held).scripts if multi else
               {'writer': writer_guidance_script(variant, held)})
    models = {role: configured_model(ws.store, role) for role in CONFIGURED_ROLES}

    async def transport(role, http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert len(exchanges) < cap, 'Refusal must precede even MockTransport dispatch'
        assert role in scripts, 'Only the selected producer/consumer may make requests'
        wire = json.loads(http_request.content)
        # Full standard SDK conversion is solely for choosing the fake response.
        # It never replaces a native message, role prompt, tool or parsed result.
        messages = [_convert_dict_to_message(m) for m in wire['messages']]
        step = sum(isinstance(m, AIMessage) for m in messages)
        try:
            item = scripts[role][step]
            answer = item(messages) if callable(item) else item
        except Exception as exc:
            dump(folder / 'mock-oracle-error.json', {'role': role, 'step': step,
                'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc(), 'wire': wire})
            raise
        message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}} for c in answer.tool_calls]
        response = {'id': 'writer-next-mock-' + str(len(exchanges) + 1), 'object': 'chat.completion',
            'created': 1, 'model': wire['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'role': role, 'step': step, 'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    for role, model in models.items():
        await model.http_async_client._transport.aclose()
        async def send(http_request, _role=role):
            return await transport(_role, http_request)
        model.http_async_client._transport = httpx.MockTransport(send)
        model.http_async_client._mounts = {}

    def original_configured_model(store, role):
        assert store is ws.store and role in models
        factory_roles.append(role)
        return models[role]

    monkeypatch.setattr(adapter, 'configured_model', original_configured_model)
    requests = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'isolated-writer-next-budget.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, case, live=True)
    capture = json.loads((folder / 'capture.json').read_text('utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
        'request': requests.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'oracle-observations.json', held)
    dump(folder / 'source-hashes-after.json', original_source_hashes())
    request.node.user_properties.append(('writer_next_adapter_capture', str(folder)))
    assert original_source_hashes() == initial_hashes
    assert set(factory_roles) == CONFIGURED_ROLES and len(factory_roles) == len(CONFIGURED_ROLES)
    assert [m['role'] for m in result['configured_models']] == factory_roles
    for policy in result['configured_models']:
        assert policy['model'] == 'glm-5.3' and policy['sdk_max_retries'] == 5
        assert policy['httpx_connect_retries'] == 0 and policy['logical_request_deadline_seconds'] == 600
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert result['mode'] == 'live' and not result['observer_errors']
    assert result['observed_http_responses'] == result['admitted_http_attempts'] == requests.count == len(exchanges) == count
    assert result['observed_request_hook_entries'] == count + int(refused)
    assert result['hook_entries_without_admission'] == int(refused)
    assert result['admitted_without_observed_response'] == 0
    assert len(capture['native_model_calls']) == count + int(refused)
    assert tokens.snapshot()['recorded_tokens'] == 2 * count
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': count, 'known_not_sent': 1} if refused else {'settled': count})
    assert len(rows) == count + int(refused)
    assert {r['response_id'] for r in rows if r['state'] == 'settled'} == {e['response']['id'] for e in exchanges}
    wires = json.loads((folder / 'wire-requests.json').read_text('utf-8'))
    responses = json.loads((folder / 'wire-responses.json').read_text('utf-8'))
    for exchange, wire, response in zip(exchanges, wires[:count], responses, strict=True):
        assert wire['body'] == exchange['wire'] and wire['role'] == exchange['role']
        assert json.loads(response['body']) == exchange['response'] and response['role'] == exchange['role']
        assert response['request_sequence'] == wire['sequence']
    phases = [p for p in capture['phase_events'] if p['phase'] == ('native_writer_handler' if multi else 'unchanged_writer_handler')]
    writer_wires = [w for w in wires if w['role'] == 'writer']
    for event, wire in zip(phases, writer_wires, strict=True):
        assert {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'} == native_tools(event, multi)
        names = {t['function']['name'] for t in wire['body']['tools']}
        assert {'read_tool_observation', 'commit_objects', 'process_report_content'} <= names
        if multi:
            assert 'record_experience_use' not in names
        else:
            assert 'record_experience_use' in names
    if multi:
        assert [e['role'] for e in exchanges] == ['text_tool'] + ['writer'] * (count - 1)
        assert json.loads(exchanges[0]['wire']['messages'][-1]['content']) == held['producer_packet']
        assert_multi_state(capture, held, refused)
    else:
        assert {e['role'] for e in exchanges} == {'writer'}
        assert_guidance_state(capture, held, variant, refused)
    runtime = capture.get('runtime_result', capture.get('runtime'))
    if refused:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and runtime['last_error'] is None
        task_failure=json.loads(capture['parent']['task_return' if multi else 'actual_task_return']["content"])
        task_failure=task_failure.get('metadata',task_failure)
        assert task_failure['ok'] is False and task_failure['code']=='DELEGATED_EXECUTION_FAILED'
        assert task_failure['error']['type']=='RequestBudgetExceeded'
        assert task_failure['error']['message']=='MODEL_REQUEST_BUDGET_REACHED'
        unsent = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
        assert unsent[0]['reason'] == 'Local transport admission rejected before send'
        assert wires[-1]['role'] == 'writer' and len(responses) == count
        if multi:
            assert all(e['role'] != 'writer' for e in exchanges)
        else:
            assert len(exchanges) == 1
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and runtime['last_error'] is None
    dump(folder / 'test-interpretation.json', {'paid_calls': 0, 'mock_responses': count,
        'local_unsent_requests': int(refused), 'unknown_outcomes': 0,
        'prepared_input_is_not_provider_receipt': True,
        'scope': 'SDK/native I/O, saved exact outputs and budget containment; not autonomous semantic quality.',
        'visible_footnote_defect_not_closed': True})
