"""Actual comparison adapter and configured SDKs; local synthetic responses only."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback

from docx import Document
import httpx
from langchain_core.messages import AIMessage, messages_from_dict
from langchain_openai.chat_models.base import _convert_dict_to_message
import pytest

from duty_probe_agent_decisions import dump
from duty_probe_layout_comparison_outcome import (
    BODY, FOOTNOTE, LIMIT, QUESTION, STANDARD, measure_prepared_page,
)
from report_agent.content_store import ContentStore
from report_agent.deep_models import (
    MODEL_REQUEST_DEADLINE_SECONDS, configured_model, configured_vision_client, connection_retry_count,
)
from report_agent.layout_revision import status as revision_status
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import result_value, tool_reply
from test_bounded_deadline import close_model
from test_duty_layout_comparison_outcome import (
    VISION_TEXT, assert_current_page_identity, comparison_script,
)
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_review_consumers_adapter import response_body
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [6, 5], ids=['normal-wire', 'current-saved-before-local-refusal'])
async def test_layout_comparison_actual_sdk_handoffs_files_and_shared_budget(ws, request, monkeypatch, cap):
    ws.store.set('layout_revision_limit', 1)
    roles = {'coordinator': 'deepseek-v4.1-flash', 'writer': 'glm-5.3',
             'reviewer': 'deepseek-v4.1-flash', 'layout': 'glm-5.3',
             'text_tool': 'deepseek-v4.1-flash', 'vision': 'deepseek-v4.1-flash'}
    for role, model in roles.items():
        for key, value in {'MODEL': model, 'BASE_URL': 'https://offline.invalid/v1',
                           'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    root = Path(os.environ.get('REPORT_LAYOUT_COMPARISON_SDK_OUT', str(ws.store.root / 'sdk-captures')))
    folder = root / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    models = {role: configured_model(ws.store, role) for role in roles if role != 'vision'}
    prepared, received, exchanges, created, visuals, replaced_transports, held = [], [], [], [], [], [], {}
    choose = comparison_script(folder, False, held)

    def hooks(role):
        async def on_request(http_request):
            sequence = len(prepared) + 1
            http_request.extensions['comparison_sdk_sequence'] = sequence
            prepared.append({'sequence': sequence, 'role': role, 'body': json.loads(http_request.content),
                             'origin': 'pre_admission_intent_not_dispatch_proof'})
            dump(folder / 'sdk-wire-requests.json', prepared)

        async def on_response(response):
            await response.aread()
            received.append({'request_sequence': response.request.extensions['comparison_sdk_sequence'],
                             'role': role, 'status': response.status_code, 'body': response.text})
            dump(folder / 'sdk-wire-responses.json', received)
        return on_request, on_response

    async def dispatch(http_request, role):
        try:
            assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
            assert len(exchanges) < cap, 'Shared budget must refuse before MockTransport'
            wire = json.loads(http_request.content)
            assert wire['model'] == roles[role]
            if role == 'vision':
                assert len(exchanges) in {2, 4}
                assert not wire.get('tools') and [m['role'] for m in wire['messages']] == ['system', 'user']
                text, image = wire['messages'][1]['content']
                assert text == {'type': 'text', 'text': QUESTION}
                assert image['type'] == 'image_url' and image['image_url']['detail'] == 'high'
                prefix, encoded = image['image_url']['url'].split(',', 1)
                assert prefix == 'data:image/png;base64'
                held.setdefault('vision_wire_images', []).append(
                    hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest())
                answer = AIMessage(content=VISION_TEXT)
            else:
                assert role == 'layout' and 'data:image/' not in json.dumps(wire)
                answer = choose([_convert_dict_to_message(m) for m in wire['messages']])
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

    def attach(role, client):
        on_request, on_response = hooks(role)
        client.event_hooks['request'].insert(0, on_request)
        client.event_hooks['response'].insert(0, on_response)
        replaced_transports.extend([client._transport, *[t for t in client._mounts.values() if t is not None]])
        async def transport(http_request):
            return await dispatch(http_request, role)
        client._transport, client._mounts = httpx.MockTransport(transport), {}

    for role, model in models.items():
        attach(role, model.http_async_client)

    def original_model(store, role):
        assert store is ws.store
        created.append(role)
        return models[role]

    def fresh_vision():
        # Each actual inspection owns its own SDK client and closes it. The
        # replaced, unused default transports are also closed below.
        client = configured_vision_client()
        visuals.append(client)
        attach('vision', client._client)
        return client

    monkeypatch.setattr(adapter, 'configured_model', original_model)
    monkeypatch.setattr(adapter, 'configured_vision_client', fresh_vision)
    calls = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'comparison-sdk-budget.db', 20000000,
                         {'glm-5.3': 2000000, 'deepseek-v4.1-flash': 2000000})
    try:
        with request_budget(calls), token_budget(tokens):
            result = await adapter.probe_native_decision(ws, folder, adapter.LAYOUT_COMPARISON_CASE, live=True)
    finally:
        for model in models.values():
            await close_model(model)
        for client in visuals:
            if not client.is_closed():
                await client.close()
        for transport in {id(t): t for t in replaced_transports}.values():
            await transport.aclose()
    capture = json.loads((folder / 'capture.json').read_text(encoding='utf-8'))
    actual_requests = json.loads((folder / 'wire-requests.json').read_text(encoding='utf-8'))
    actual_responses = json.loads((folder / 'wire-responses.json').read_text(encoding='utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        attempts = [dict(row) for row in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': attempts,
                                          'request': calls.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'scripted-choices.json', held)
    refused = cap == 5
    assert set(created) == set(models) and len(created) == len(models)
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert len(visuals) == 2 and len({id(v) for v in visuals}) == 2
    assert all(v.is_closed() and v._client.is_closed and v.max_retries == 5 for v in visuals)
    assert all(m.max_retries == 5 for m in models.values())
    assert connection_retry_count() == 0 and MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert result['configured_vision_clients'] == [
        {'sdk_max_retries': 5, 'httpx_connect_retries': 0, 'logical_request_deadline_seconds': 600}] * 2
    assert result['observer_errors'] == capture['observer_errors'] == []
    assert result['initial_parent_and_pair_preparation_are_fake'] and not result['host_completes_model_work']
    assert not capture['host_completion_actions'] and capture['originals_unchanged']
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == cap
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == len(prepared) == len(actual_requests) == 6
    assert result['hook_entries_without_admission'] == int(refused)
    expected_roles = ['layout', 'layout', 'vision', 'layout', 'vision', 'layout']
    assert [r['role'] for r in prepared] == expected_roles
    assert [e['role'] for e in exchanges] == [r['role'] for r in received] == expected_roles[:cap]
    assert len(exchanges) == len(received) == len(actual_responses) == cap
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
    phases = [p for p in capture['phase_events'] if p['phase'] == 'unchanged_layout_handler']
    layout_requests = [r for r in prepared if r['role'] == 'layout']
    assert len(phases) == len(layout_requests) == 4
    for phase, wire in zip(phases, layout_requests, strict=True):
        native = {m['data']['tool_call_id']: m['data']['content'] for m in phase['messages'] if m['type'] == 'tool'}
        assert native == {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'}
        names = {t['function']['name'] for t in wire['body']['tools']}
        assert {'read_context', 'read_layout_capabilities', 'inspect_rendered_page'} <= names
        assert not names & {'commit_objects', 'freeze_snapshot', 'select_content_delivery', 'submit_review'}
        assert 'data:image/' not in json.dumps(wire)
    fixture, cs = capture['fixture'], ContentStore(ws.store)
    pair = fixture['prepared_pair']
    task, = cs.list_objects('DelegatedTask')
    actor = 'content:layout:' + task['ref']['id']
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'layout' and task['payload']['goal'] == fixture['task_call']['args']['description']
    assert task['payload']['layout_snapshot_ref'] == fixture['snapshot_ref']
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    for phase in capture['phase_events']:
        assert phase['server_context']['role'] == 'layout' and phase['server_context']['actor_id'] == actor
        assert phase['server_context']['assignment'] == task['payload']
    assert len(cs.list_objects('DocumentSnapshot')) == 1 and cs.list_objects('ReviewRecord') == []
    assert len(cs.list_objects('ExportArtifact')) == len(cs.list_objects('RenderArtifact')) == len(cs.list_objects('MappingArtifact')) == 2
    assert cs.read(fixture['inputs']['source_refs'][1])['payload']['content'] == STANDARD
    assert cs.read(fixture['inputs']['source_refs'][0])['payload']['content'] == 'Class B permits 75 to 100.'
    assert cs.read(fixture['refs']['claim'])['payload'] == {'kind': 'claim', 'body': {'text': 'For adopted class B use 70.'},
        'qualifiers': {'condition': 'class B'}, 'claim_kind': 'inference'}
    with ws.store.connect() as db:
        budget = revision_status(db)
    assert budget['max_revisions'] == budget['revisions_used'] == 1
    for label, size, prep_index in [('before', 11, '0'), ('after', 12, '2')]:
        export, render = cs.read(pair[label]['export_ref']), cs.read(pair[label]['render_ref'])
        mapping = cs.read(capture['preparation_receipts'][prep_index]['result']['mapping_ref'])
        for obj in [export, render, mapping]:
            assert obj['owner_id'] == obj['created_by'] == actor and obj['task_id'] == task['ref']['id']
            assert obj['payload']['snapshot_ref'] == fixture['snapshot_ref']
        assert render['payload']['export_ref'] == mapping['payload']['export_ref'] == export['ref']
        assert render['payload']['export_digest'] == export['payload']['file_digest']
        assert measure_prepared_page(ws, export['ref'], render['ref'], size) == pair[label]
        word = Document(ws.store.root / export['payload']['file_ref'])
        texts = ['Synthetic local comparison', 'For adopted class B use 70.', BODY, FOOTNOTE]
        for text in texts:
            assert text in '\n'.join(p.text for p in word.paragraphs)
        assert [[c.text for c in row.cells] for row in word.tables[0].rows] == [fixture['expected_table']['columns'], *fixture['expected_table']['rows']]
        assert 'condition：class B' in '\n'.join(p.text for p in word.paragraphs)
        for text in [*texts, *fixture['expected_table']['columns'], *(c for row in fixture['expected_table']['rows'] for c in row)]:
            assert ' '.join(text.split()) in ' '.join(pair[label]['pdf_text'].split())
    assert held['vision_wire_images'] == [pair['before']['image']['sha256'], pair['after']['image']['sha256']]
    assert held['vision_wire_images'][0] != held['vision_wire_images'][1]
    for asset in capture['assets']:
        assert hashlib.sha256((folder / asset['retained_path']).read_bytes()).hexdigest() == asset['sha256']
    observations = []
    for label, call_id, phase_index, response_index in [('before', 'comparison-before', 2, 2), ('after', 'comparison-after', 3, 4)]:
        envelope = result_value(tool_reply(messages_from_dict(phases[phase_index]['messages']), call_id))
        observation = envelope['result']
        row, = [r for r in capture['native_observation_rows'] if r['id'] == envelope['receipt_id']]
        with ws.store.connect() as db:
            actual_row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (envelope['receipt_id'],)).fetchone()
        assert actual_row == (actor, row['data']) and json.loads(row['data']) == observation
        assert row['actor_id'] == actor and observation['status'] == 'observed' and not observation['reused']
        assert observation['observation'] == VISION_TEXT
        assert observation['limitations'] == ['Model observation is not a confirmed fact or engineering approval.',
            'Coverage is only the supplied page/region; no whole-document OCR claim.', 'Original sources and existing OCR are unchanged.']
        assert observation['response_id'] == exchanges[response_index]['response']['id']
        assert observation['source']['render_ref'] == pair[label]['render_ref']
        assert observation['source']['export_ref'] == pair[label]['export_ref']
        assert observation['source']['page'] == 1 and observation['source']['coverage'] == 'full_page_image'
        assert observation['source']['crop'] is None and observation['image_sha256'] == pair[label]['image']['sha256']
        observations.append(envelope)
    assert_current_page_identity(pair, [o['result'] for o in observations])
    assert held['before'] == observations[0]
    assert not (folder / 'first-mock-callback-error.json').exists()
    parent = [p['actual_child_return'] for p in capture['fake_parent_events'] if 'actual_child_return' in p]
    dump(folder / 'full-native-vision-handoffs.json', {'observations': observations,
        'parent_returns': parent, 'current_observation_received_by_successful_layout_response': not refused})
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        assert 'MODEL_REQUEST_BUDGET_REACHED' in json.dumps(capture['raised_error']) + json.dumps(capture['runtime'])
        assert held['turn'] == 3 and 'after' not in held and 'final_packet' not in held
        assert not phases[-1].get('response')
        unsent, = [a for a in attempts if a['state'] == 'known_not_sent']
        assert unsent['used'] == 0 and unsent['response_id'] is None
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        assert held['turn'] == 4 and held['after'] == observations[1]
        assert len(parent) == 1 and json.loads(parent[0]['content']) == held['final_packet']
        assert held['final_packet']['scope'] == LIMIT and not held['final_packet']['engineering_accepted']
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'provider': 'MockTransport',
        'entrypoint': 'actual probe_native_decision comparison branch', 'paid_HTTP': 0,
        'mock_HTTP_received': cap, 'local_unsent': int(refused), 'saved_current_vision': True,
        'current_vision_successfully_consumed': not refused, 'real_model_acceptance': False})
