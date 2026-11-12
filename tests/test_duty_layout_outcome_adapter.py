"""Actual Layout adapter and configured SDKs; synthetic HTTP, real Office files."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback

import httpx
import pytest
from langchain_core.messages import AIMessage, messages_from_dict
from langchain_openai.chat_models.base import _convert_dict_to_message

from duty_probe_agent_decisions import dump
from report_agent.content_store import ContentStore
from report_agent.deep_models import (
    MODEL_REQUEST_DEADLINE_SECONDS, configured_model, configured_vision_client, connection_retry_count,
)
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import result_value, tool_reply
from test_bounded_deadline import close_model
from test_duty_layout_outcome import (
    VISION_TEXT, contains_exact_final, inspect_layout_word, layout_outcome_script,
)
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_review_consumers_adapter import response_body
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [7, 6], ids=['normal-wire', 'vision-saved-before-local-refusal'])
async def test_layout_actual_adapter_sdk_files_vision_and_budget(ws, request, monkeypatch, cap):
    role_models = {'coordinator': 'deepseek-v4.1-flash-1017', 'writer': 'glm-5.3',
                   'reviewer': 'deepseek-v4.1-flash-1017', 'layout': 'glm-5.3',
                   'text_tool': 'deepseek-v4.1-flash-1017', 'vision': 'deepseek-v4.1-flash-1017'}
    for role, model_name in role_models.items():
        for key, value in {'MODEL': model_name, 'BASE_URL': 'https://offline.invalid/v1',
                           'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_LAYOUT_SDK_OUT', str(ws.store.root / 'sdk-captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    models = {role: configured_model(ws.store, role) for role in role_models if role != 'vision'}
    visual = configured_vision_client()
    requests, responses, exchanges, created, vision_factories, held = [], [], [], [], [], {}
    scripted = layout_outcome_script(folder, 'normal', held)

    def hooks(role):
        async def on_request(http_request):
            number = len(requests) + 1
            http_request.extensions['layout_sdk_sequence'] = number
            requests.append({'sequence': number, 'role': role,
                'body': json.loads(http_request.content), 'origin': 'prepared_before_admission'})
            dump(folder / 'sdk-wire-requests.json', requests)

        async def on_response(response):
            await response.aread()
            responses.append({'request_sequence': response.request.extensions['layout_sdk_sequence'],
                'role': role, 'http_status': response.status_code, 'body': response.text})
            dump(folder / 'sdk-wire-responses.json', responses)
        return on_request, on_response

    async def dispatch(http_request, role):
        try:
            assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
            assert len(exchanges) < cap, 'Refuse locally before MockTransport dispatch'
            wire = json.loads(http_request.content)
            if role == 'vision':
                assert [e['role'] for e in exchanges] == ['layout'] * 5
                assert wire['model'] == role_models['vision'] and not wire.get('tools')
                assert [m['role'] for m in wire['messages']] == ['system', 'user']
                content = wire['messages'][1]['content']
                texts = [b['text'] for b in content if b['type'] == 'text']
                assert texts == ['Describe this physical page only. Preserve unseen-page and acceptance limits.']
                images = [b['image_url'] for b in content if b['type'] == 'image_url']
                assert len(images) == 1 and images[0]['detail'] == 'high'
                prefix, encoded = images[0]['url'].split(',', 1)
                assert prefix == 'data:image/png;base64'
                held['wire_png_sha256'] = hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()
                answer = AIMessage(content=VISION_TEXT)
            else:
                assert role == 'layout', 'Other original configured roles may construct but not call'
                assert wire['model'] == role_models['layout']
                assert 'data:image/' not in json.dumps(wire), 'GLM is text-only; dedicated vision owns image input'
                messages = [_convert_dict_to_message(m) for m in wire['messages']]
                answer = scripted[held.get('turn', 0)](messages)
            raw = response_body(wire, answer, len(exchanges) + 1)
            exchanges.append({'role': role, 'wire': wire, 'response': raw})
            dump(folder / 'mock-exchanges.json', exchanges)
            return httpx.Response(200, json=raw)
        except Exception as exc:
            first_error = folder / 'first-mock-callback-error.json'
            if not first_error.exists():
                dump(first_error, {'role': role, 'type': type(exc).__name__,
                    'message': str(exc), 'traceback': traceback.format_exc()})
            raise

    for role, model in models.items():
        on_request, on_response = hooks(role)
        model.http_async_client.event_hooks['request'].insert(0, on_request)
        model.http_async_client.event_hooks['response'].insert(0, on_response)
        await model.http_async_client._transport.aclose()
        async def model_transport(http_request, selected_role=role):
            return await dispatch(http_request, selected_role)
        model.http_async_client._transport = httpx.MockTransport(model_transport)
        model.http_async_client._mounts = {}
    on_request, on_response = hooks('vision')
    visual._client.event_hooks['request'].insert(0, on_request)
    visual._client.event_hooks['response'].insert(0, on_response)
    await visual._client._transport.aclose()
    async def visual_transport(http_request):
        return await dispatch(http_request, 'vision')
    visual._client._transport = httpx.MockTransport(visual_transport)
    visual._client._mounts = {}

    def original_model(store, role):
        assert store is ws.store
        created.append(role)
        return models[role]

    def original_vision():
        assert not vision_factories, 'No hidden second vision fallback'
        vision_factories.append('vision')
        return visual

    monkeypatch.setattr(adapter, 'configured_model', original_model)
    monkeypatch.setattr(adapter, 'configured_vision_client', original_vision)
    calls = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'layout-mock-budget.db', 20000000,
                         {'glm-5.3': 2000000, 'deepseek-v4.1-flash-1017': 2000000})
    try:
        with request_budget(calls), token_budget(tokens):
            result = await adapter.probe_native_decision(ws, folder, adapter.LAYOUT_OUTCOME_CASE, live=True)
    finally:
        # Also clean test-owned clients if capture/configuration fails early.
        for model in models.values():
            await close_model(model)
        if not visual.is_closed():
            await visual.close()
    capture = json.loads((folder / 'capture.json').read_text())
    adapter_requests = json.loads((folder / 'wire-requests.json').read_text())
    adapter_responses = json.loads((folder / 'wire-responses.json').read_text())
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
         'request': calls.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'independent-observations.json', held)
    request.node.user_properties.append(('layout_sdk_capture', str(folder)))
    refused = cap == 6
    assert set(created) == set(models) and len(created) == len(models)
    assert vision_factories == ['vision']
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert visual.is_closed() and visual._client.is_closed
    assert all(m.max_retries == 5 for m in models.values()) and visual.max_retries == 5
    assert connection_retry_count() == 0 and MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert result['observer_errors'] == capture['observer_errors'] == []
    assert result['initial_parent_and_original_read_choices_are_fake'] is True
    assert {m['role'] for m in result['configured_models']} == set(models)
    assert result['configured_vision_clients'] == [{'sdk_max_retries': 5, 'httpx_connect_retries': 0,
                                                   'logical_request_deadline_seconds': 600}]
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == cap
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == 7
    assert result['hook_entries_without_admission'] == int(refused)
    assert len(requests) == len(adapter_requests) == 7
    assert len(exchanges) == len(responses) == len(adapter_responses) == cap
    assert [e['role'] for e in exchanges] == ['layout'] * 5 + ['vision'] + ([] if refused else ['layout'])
    assert [r['role'] for r in requests] == ['layout'] * 5 + ['vision', 'layout']
    for wire in (r['body'] for r in requests if r['role'] == 'layout'):
        names = {t['function']['name'] for t in wire['tools']}
        assert {'read_context', 'read_layout_capabilities', 'export_content_snapshot',
                'read_content_export', 'render_content_export', 'inspect_rendered_page'} <= names
        assert not names & {'commit_objects', 'freeze_snapshot', 'select_content_delivery',
                           'export_content_workbook', 'submit_review', 'perform_assigned_review',
                           'perform_assigned_artifact_review', 'confirm_review_reuse'}
    assert tokens.snapshot()['recorded_tokens'] == cap * 2
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': cap, 'known_not_sent': 1} if refused else {'settled': cap})
    for own, actual in zip(requests, adapter_requests, strict=True):
        assert own['sequence'] == actual['sequence'] and own['role'] == actual['role']
        assert own['body'] == actual['body']
    for exchange, own, actual in zip(exchanges, responses, adapter_responses, strict=True):
        assert own['role'] == actual['role'] == exchange['role']
        assert own['request_sequence'] == actual['request_sequence']
        assert own['http_status'] == actual['http_status'] == 200
        assert json.loads(own['body']) == json.loads(actual['body']) == exchange['response']
    phases = [e for e in capture['phase_events'] if e['phase'] == 'unchanged_layout_handler']
    layout_requests = [r for r in requests if r['role'] == 'layout']
    assert len(phases) == len(layout_requests) == 6
    for event, wire in zip(phases, layout_requests, strict=True):
        native = {m['data']['tool_call_id']: m['data']['content']
                  for m in event['messages'] if m['type'] == 'tool'}
        assert native == {m['tool_call_id']: m['content']
                          for m in wire['body']['messages'] if m['role'] == 'tool'}
    assert capture['originals_unchanged'] is True and capture['saved_reviews'] == []
    assert len(capture['saved_tasks']) == len(capture['saved_renders']) == 1
    assert len(capture['saved_exports']) == 2
    exported,= [e for e in capture['saved_exports'] if e['payload']['file_ref'].endswith('.docx')]
    companion,= [e for e in capture['saved_exports'] if e['payload']['file_ref'].endswith('.xlsx')]
    task, rendered = capture['saved_tasks'][0], capture['saved_renders'][0]
    assert companion['owner_id']==exported['owner_id']
    assert companion['payload']['snapshot_ref']==exported['payload']['snapshot_ref']
    assert companion['payload']['export_config']['report_export_ref']==exported['ref']
    fixture, cs = capture['fixture'], ContentStore(ws.store)
    actor = 'content:layout:' + task['ref']['id']
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'layout'
    assert task['payload']['goal'] == fixture['task_call']['args']['description']
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    assert task['payload']['layout_snapshot_ref'] == fixture['snapshot_ref']
    for phase in capture['phase_events']:
        assert phase['server_context']['role'] == 'layout'
        assert phase['server_context']['actor_id'] == actor
        assert phase['server_context']['assignment'] == task['payload']
    assert exported['owner_id'] == rendered['owner_id'] == actor
    assert exported['payload']['snapshot_ref'] == rendered['payload']['snapshot_ref'] == fixture['snapshot_ref']
    assert rendered['payload']['export_ref'] == exported['ref']
    assert rendered['payload']['export_digest'] == exported['payload']['file_digest']
    mappings = cs.list_objects('MappingArtifact')
    assert len(mappings) == 2
    mapping,= [m for m in mappings if m['ref']==held['export']['result']['mapping_ref']]
    assert mapping['ref'] == held['export']['result']['mapping_ref']
    assert mapping['owner_id'] == mapping['created_by'] == actor and mapping['task_id'] == task['ref']['id']
    assert mapping['payload']['snapshot_ref'] == fixture['snapshot_ref']
    assert mapping['payload']['export_ref'] == exported['ref']
    assert len(cs.list_objects('DocumentSnapshot')) == 1
    for asset in capture['assets']:
        assert hashlib.sha256((folder / asset['retained_path']).read_bytes()).hexdigest() == asset['sha256']
    word = next(a for a in capture['assets'] if a['file_ref'] == exported['payload']['file_ref'])
    actual_word = inspect_layout_word(folder / word['retained_path'], fixture)
    dump(folder / 'word-oracle.json', actual_word)
    assert actual_word['violations'] == [], actual_word['violations']
    # This native input is prepared in both cases. Only normal's successful
    # final response proves model consumption; cap6 must not be credited for it.
    prepared_vision = result_value(tool_reply(messages_from_dict(phases[-1]['messages']), 'layout-observe'))
    observed = prepared_vision['result']
    assert prepared_vision['ok'] is True and observed['status'] == 'observed'
    assert observed['observation'] == VISION_TEXT and observed['limitations']
    assert observed['source']['render_ref'] == rendered['ref'] and observed['source']['export_ref'] == exported['ref']
    assert observed['source']['page'] == 1 and observed['source']['coverage'] == 'full_page_image'
    assert observed['source']['crop'] is None and not observed['reused']
    assert observed['image_sha256'] == held['wire_png_sha256'] == rendered['payload']['page_assets'][0]['sha256']
    with ws.store.connect() as db:
        receipt = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                             (prepared_vision['receipt_id'],)).fetchone()
        assert receipt and receipt[0] == actor and json.loads(receipt[1]) == observed
    assert VISION_TEXT in json.dumps(requests[-1]['body'])
    parent = [e['actual_child_return'] for e in capture['fake_parent_events'] if e.get('actual_child_return')]
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        error = capture['raised_error'] or capture['runtime']['last_error']
        assert error and 'RequestBudgetExceeded' in str(error)
        assert capture['finals'] == [] and 'final_packet' not in held and 'actual_vision_return' not in held
        assert all(VISION_TEXT not in json.dumps(e['wire']) for e in exchanges if e['role'] == 'layout')
        assert {r['request_sequence'] for r in responses} == set(range(1, 7))
        unsent = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
        # A truthful error return to the parent is legal. No success final is
        # synthesized or required when the original task fails at admission.
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
        assert held['actual_vision_return'] == prepared_vision
        assert capture['finals'] == [json.dumps(held['final_packet'])]
        assert len(parent) == 1 and parent[0]['tool_call_id'] == fixture['task_call']['id']
        assert contains_exact_final(parent[0]['content'], capture['finals'][0])
        assert held['final_packet']['independent_content_review_performed'] is False
        assert held['final_packet']['engineering_accepted'] is False
        assert held['final_packet']['observed_pages'] == [1]
        assert held['final_packet']['unseen_pages'] == list(range(2, len(rendered['payload']['page_assets']) + 1))
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'provider': 'MockTransport',
        'entrypoint': 'actual probe_native_decision Layout branch', 'paid_HTTP': 0,
        'mock_HTTP_received': cap, 'known_local_unsent': int(refused),
        'vision_observation_saved': True, 'vision_consumed_in_received_layout_request': not refused,
        'real_model_or_visual_or_engineering_acceptance': False,
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
