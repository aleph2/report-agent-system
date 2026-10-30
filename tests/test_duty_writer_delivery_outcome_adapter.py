"""Actual Writer probe adapter/configured SDKs, synthetic HTTP and real files."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import traceback

from docx import Document
import httpx
from langchain_core.messages import messages_from_dict
from langchain_openai.chat_models.base import _convert_dict_to_message
from openpyxl import load_workbook
import pytest

from duty_probe_agent_decisions import dump, ref_key
from duty_probe_writer_delivery_outcome import BODY_B, BOOK_NOTE, FOOTNOTE, GOAL, REPORT_TABLE, UNKNOWN, UNREVIEWED
from report_agent.content_store import ContentStore
from report_agent.deep_models import MODEL_REQUEST_DEADLINE_SECONDS, configured_model, connection_retry_count
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import result_value, tool_reply
from test_bounded_deadline import close_model
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_review_consumers_adapter import response_body
from test_duty_writer_delivery_outcome import current_version_violations, delivery_script, exact_final_inside
from test_task_supervision import ws


@pytest.mark.parametrize('cap', [5, 3], ids=['normal-wire', 'pair-saved-before-local-refusal'])
async def test_writer_pair_actual_adapter_sdk_and_local_budget(ws, request, monkeypatch, cap):
    role_models = {'coordinator': 'deepseek-v4.1-flash', 'writer': 'glm-5.3',
        'reviewer': 'deepseek-v4.1-flash', 'layout': 'glm-5.3', 'text_tool': 'deepseek-v4.1-flash'}
    for role, name in role_models.items():
        for suffix, value in {'MODEL': name, 'BASE_URL': 'https://offline.invalid/v1',
                              'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + suffix, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_WRITER_DELIVERY_SDK_OUT', str(ws.store.root / 'sdk-captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    models = {role: configured_model(ws.store, role) for role in role_models}
    requests, responses, exchanges, created, held = [], [], [], [], {}
    scripted = delivery_script(folder, 'current', held)

    def hooks(role):
        async def on_request(http_request):
            sequence = len(requests) + 1
            http_request.extensions['writer_delivery_sdk_sequence'] = sequence
            requests.append({'sequence': sequence, 'role': role,
                'body': json.loads(http_request.content), 'origin': 'prepared_before_admission'})
            dump(folder / 'sdk-wire-requests.json', requests)

        async def on_response(response):
            await response.aread()
            responses.append({'request_sequence': response.request.extensions['writer_delivery_sdk_sequence'],
                'role': role, 'http_status': response.status_code, 'body': response.text})
            dump(folder / 'sdk-wire-responses.json', responses)
        return on_request, on_response

    async def dispatch(http_request, role):
        try:
            assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
            assert len(exchanges) < cap, 'Native transport budget must refuse before MockTransport'
            assert role == 'writer', 'Only the selected Writer may call its configured client'
            wire = json.loads(http_request.content)
            assert wire['model'] == role_models['writer']
            assert 'data:image/' not in json.dumps(wire)
            messages = [_convert_dict_to_message(m) for m in wire['messages']]
            answer = scripted[held.get('turn', 0)](messages)
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

    def unselected_vision():
        raise AssertionError('This fake Writer script contains no vision action or fallback')

    monkeypatch.setattr(adapter, 'configured_model', original_model)
    monkeypatch.setattr(adapter, 'configured_vision_client', unselected_vision)
    calls = RequestBudget(cap)
    tokens = TokenBudget(ws.store.root / 'writer-delivery-sdk-budget.db', 20000000,
                         {'glm-5.3': 2000000, 'deepseek-v4.1-flash': 2000000})
    try:
        with request_budget(calls), token_budget(tokens):
            result = await adapter.probe_native_decision(ws, folder, adapter.WRITER_DELIVERY_CASE, live=True)
    finally:
        for model in models.values():
            await close_model(model)
    capture = json.loads((folder / 'capture.json').read_text())
    adapter_requests = json.loads((folder / 'wire-requests.json').read_text())
    adapter_responses = json.loads((folder / 'wire-responses.json').read_text())
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        attempts = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': attempts,
         'request': calls.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'independent-observations.json', held)
    request.node.user_properties.append(('writer_delivery_sdk_capture', str(folder)))
    refused = cap == 3
    prepared_count = 4 if refused else 5
    assert set(created) == set(models) and len(created) == len(models)
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert all(m.max_retries == 5 for m in models.values())
    assert connection_retry_count() == 0 and MODEL_REQUEST_DEADLINE_SECONDS == 600
    assert result['observer_errors'] == capture['observer_errors'] == []
    assert result['initial_parent_and_original_read_choices_are_fake'] is True
    assert {m['role'] for m in result['configured_models']} == set(models)
    assert result.get('configured_vision_clients', []) == []
    assert result['admitted_http_attempts'] == result['observed_http_responses'] == cap
    assert result['admitted_without_observed_response'] == 0
    assert result['observed_request_hook_entries'] == prepared_count
    assert result['hook_entries_without_admission'] == int(refused)
    assert len(requests) == len(adapter_requests) == prepared_count
    assert len(exchanges) == len(responses) == len(adapter_responses) == cap
    assert [r['role'] for r in requests] == ['writer'] * prepared_count
    assert tokens.snapshot()['recorded_tokens'] == cap * 2
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'settled': cap, 'known_not_sent': 1} if refused else {'settled': cap})
    for own, actual in zip(requests, adapter_requests, strict=True):
        assert own['sequence'] == actual['sequence'] and own['role'] == actual['role']
        assert own['body'] == actual['body']
        names = {t['function']['name'] for t in own['body']['tools']}
        assert {'read_context', 'freeze_snapshot', 'derive_snapshot', 'export_content_snapshot',
                'export_content_workbook', 'read_content_export'} <= names
        assert not names & {'select_content_delivery', 'record_execution_decision', 'submit_review',
                            'perform_assigned_review', 'perform_assigned_artifact_review', 'confirm_review_reuse'}
    for exchange, own, actual in zip(exchanges, responses, adapter_responses, strict=True):
        assert own['role'] == actual['role'] == exchange['role']
        assert own['request_sequence'] == actual['request_sequence']
        assert own['http_status'] == actual['http_status'] == 200
        assert json.loads(own['body']) == json.loads(actual['body']) == exchange['response']
    phases = [p for p in capture['phase_events'] if p['phase'] == 'unchanged_writer_handler']
    assert len(phases) == len(requests) == prepared_count
    for phase, wire in zip(phases, requests, strict=True):
        native_tools = {m['data']['tool_call_id']: m['data']['content']
                        for m in phase['messages'] if m['type'] == 'tool'}
        assert native_tools == {m['tool_call_id']: m['content']
                                for m in wire['body']['messages'] if m['role'] == 'tool'}
    cs, fixture = ContentStore(ws.store), capture['fixture']
    tasks = cs.list_objects('DelegatedTask')
    assert len(tasks) == 1
    task = tasks[0]
    actor = 'content:writer:' + task['ref']['id']
    assert fixture['writer_actor']['id'] == actor
    assert task['payload']['role'] == 'writer' and task['payload']['goal'] == GOAL
    assert task['payload']['delegated_by'] == task['owner_id'] == 'content:coordinator'
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    for phase in capture['phase_events']:
        assert phase['server_context']['actor_id'] == actor
        assert phase['server_context']['role'] == 'writer'
        assert phase['server_context']['assignment'] == task['payload']
    first_messages = [_convert_dict_to_message(m) for m in requests[0]['body']['messages']]
    originals_read = [o for o in fixture['originals'] if o['ref']['type'] != 'DelegatedTask']
    for index, original in enumerate(originals_read):
        delivered = result_value(tool_reply(first_messages, 'delivery-original-' + str(index)))
        assert delivered['ok'] is True
        assert delivered['result']['target_ref'] == original['ref']
        assert delivered['result']['objects'] == [original]
        assert delivered['result']['loaded_refs'] == [original['ref']]
        assert delivered['result']['next_offset'] is None
        assert delivered['result']['unreturned_refs'] == []
    assert capture['originals_unchanged'] is True
    assert capture['saved_reviews'] == capture['saved_renders'] == []
    assert len(capture['saved_snapshots']) == 1 and len(capture['saved_exports']) == 2
    assert len(capture['saved_mappings']) == 2
    snapshot = capture['saved_snapshots'][0]
    word = next(o for o in capture['saved_exports'] if o['payload']['file_ref'].endswith('.docx'))
    book = next(o for o in capture['saved_exports'] if o['payload']['file_ref'].endswith('.xlsx'))
    assert snapshot['ref'] == word['payload']['snapshot_ref'] == book['payload']['snapshot_ref']
    assert book['payload']['export_config']['report_export_ref'] == word['ref']
    assert {ref_key(r) for r in snapshot['payload']['workbook_refs']} == {
        ref_key(fixture['bundles']['current']['issues']), ref_key(fixture['bundles']['current']['note'])}
    for obj in [snapshot, word, book, *capture['saved_mappings']]:
        assert obj['owner_id'] == obj['created_by'] == actor and obj['task_id'] == task['ref']['id']
    for mapping in capture['saved_mappings']:
        assert mapping['payload']['snapshot_ref'] == snapshot['ref']
        assert mapping['payload']['export_ref'] in [word['ref'], book['ref']]
    assert len(capture['assets']) == 2
    for obj in [word, book]:
        asset = next(a for a in capture['assets'] if a['file_ref'] == obj['payload']['file_ref'])
        assert hashlib.sha256((folder / asset['retained_path']).read_bytes()).hexdigest() == asset['sha256'] == obj['payload']['file_digest']
    doc = Document(ws.store.root / word['payload']['file_ref'])
    word_text = '\n'.join(p.text for p in doc.paragraphs)
    assert BODY_B in word_text and FOOTNOTE in word_text and UNKNOWN in word_text and UNREVIEWED in word_text
    assert BOOK_NOTE not in word_text and 'Issue: actual weathering class remains unresolved.' not in word_text
    assert len(doc.tables) == 1
    assert [[c.text for c in row.cells] for row in doc.tables[0].rows] == [REPORT_TABLE['columns'], *REPORT_TABLE['rows']]
    workbook = load_workbook(BytesIO((ws.store.root / book['payload']['file_ref']).read_bytes()), data_only=False)
    try:
        assert workbook.sheetnames == ['Issues']
        matrix = [list(row) for row in workbook.active.values]
        assert matrix == [['Revision', 'Object', 'Issue', 'Evidence status'],
            ['B', 'Site S', 'Issue: actual weathering class remains unresolved.', 'Original source requires verification'],
            ['Note', BOOK_NOTE, None, None], ['status', UNREVIEWED, None, None]]
    finally:
        workbook.close()
    assert current_version_violations(snapshot, fixture, word_text, matrix) == []
    # The XLSX tool return exists in prepared request4 in both controls. Only
    # the normal case has a successful response linked to that request.
    book_return = result_value(tool_reply(messages_from_dict(phases[3]['messages']), 'delivery-book'))
    assert book_return['ok'] is True and book_return['result']['export_ref'] == book['ref']
    assert not any(r['type'] in {'DocumentSnapshot', 'ExportArtifact'} for r in (o['ref'] for o in fixture['originals']))
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        assert result['runtime_result']['last_error']['type'] == 'RequestBudgetExceeded'
        assert capture['finals'] == [] and 'final' not in held
        assert 'word_read' not in held and 'book_read' not in held
        assert not any(c['function']['name'] == 'read_content_export'
                       for exchange in exchanges for c in exchange['response']['choices'][0]['message'].get('tool_calls', []))
        not_sent = next(a for a in attempts if a['state'] == 'known_not_sent')
        assert not_sent['used'] == 0 and not not_sent['response_id']
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert result['runtime_result']['last_error'] is None
        assert capture['finals'] == [json.dumps(held['final'])]
        for name, obj in [('word', word), ('book', book)]:
            read = held[name + '_read']
            assert read['result']['export_ref'] == obj['ref']
            assert read['result']['file_digest'] == obj['payload']['file_digest']
            assert read['receipt_id'] in json.dumps(requests[-1]['body'])
            with ws.store.connect() as db:
                row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (read['receipt_id'],)).fetchone()
            assert row[0] == actor and json.loads(row[1]) == read['result']
        parent = [p['actual_child_return'] for p in capture['fake_parent_events'] if p.get('actual_child_return')]
        assert len(parent) == 1 and exact_final_inside(parent[0]['content'], capture['finals'][0])
        assert held['final']['snapshot_ref'] == snapshot['ref']
        assert held['final']['export_ref'] == word['ref'] and held['final']['workbook_export_ref'] == book['ref']
        assert held['final']['engineering_accepted'] is False and held['final']['independent_review_performed'] is False
    dump(folder / 'sdk-oracle.json', {'adapter_entry_called': True, 'actual_paid_HTTP': 0,
        'prepared': prepared_count, 'received': cap, 'known_local_unsent': int(refused),
        'pair_exists': True, 'XLSX_receipt_successfully_consumed': not refused,
        'readbacks_and_final_completed': not refused, 'semantic_or_engineering_acceptance': False})
