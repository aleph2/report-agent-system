"""Configured-SDK calibration for P09/P12 consumers.

MockTransport only; raw initial fixtures and original criteria stay intact.
Execution and actual-trace evidence are recorded separately.
"""
import base64
from copy import deepcopy
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import traceback

import httpx
import pytest
from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, ToolMessage, messages_from_dict
from langchain_openai.chat_models.base import _convert_dict_to_message
from pydantic import ValidationError

from duty_probe_agent_decisions import dump
from duty_probe_coordinator_review_outcome import TRUE_FINAL
from report_agent.content_models import ReviewSubmission
from report_agent.content_store import ContentStore
from report_agent.deep_models import configured_model, configured_vision_client
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.task_supervision import reconcile
from test_agent_duty_artifact_failures import rebind_strings
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_duty_artifact_error_consumer import HONEST, assert_received_output_failure
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_reviewer_consumer import assert_items
from test_task_supervision import ws


P09 = 'coordinator-review-outcome'
P12 = 'artifact-error-consumer'
VISION_MODEL = 'deepseek-v4.1-flash-1017'
QUESTION = ('On this same physical page, transcribe the table header cells and '
            'state any unreadable text. This observation alone cannot complete the review.')
VISUAL_OBSERVATION = ('Synthetic SDK response: the visible headers are Indicator, '
                      'Class, Score. No Note column is visible. This is one page only, '
                      'with no engineering acceptance or completed checker claim.')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def vision_reservations(ws):
    with ws.store.connect() as db:
        return {key: json.loads(raw) for key, raw in db.execute(
            "SELECT key,value FROM state WHERE key LIKE 'vision_attempt:%'")}


def response_body(wire, answer, sequence):
    message = {'role': 'assistant', 'content': answer.content}
    if answer.tool_calls:
        message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
            'name': c['name'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}}
            for c in answer.tool_calls]
    return {'id': 'review-consumer-mock-' + str(sequence), 'object': 'chat.completion',
        'created': 1, 'model': wire['model'], 'choices': [{'index': 0, 'message': message,
            'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}


def wire_tool_results(messages, tool_name):
    """Associate actual provider replies with preceding assistant calls.

    The provider protocol omits native ToolMessage.name/status. Do not synthesize
    them or use their decoder defaults as evidence of native execution status.
    """
    names, replies = {}, []
    for message in messages:
        if isinstance(message, AIMessage):
            names.update({call['id']: call['name'] for call in message.tool_calls})
        elif isinstance(message, ToolMessage) and names.get(message.tool_call_id) == tool_name:
            replies.append(message)
    return replies


async def run_sdk(ws, request, monkeypatch, case, *, zero_remaining=False, followup_vision=False):
    """Existing native helper/adapter only; this function does not drive an agent loop."""
    assert not followup_vision or case == P12 and not zero_remaining
    if case == P12:
        import duty_probe_artifact_error_consumer as artifact_fixture
        monkeypatch.setattr(artifact_fixture, 'capture_artifact_error_consumer',
            partial(artifact_fixture.capture_artifact_error_consumer,
                    fixture_variant='current_contract_duplicate'))
    active_role = 'coordinator' if case == P09 else 'reviewer'
    roles = ('writer', 'reviewer', 'layout', 'coordinator') if case == P09 else ('writer', 'reviewer', 'layout')
    for role in (*roles, 'text_tool', 'vision'):
        values = {'MODEL': VISION_MODEL if role == 'vision' else 'glm-5.3',
                  'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}
        for key, value in values.items():
            monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_REVIEW_CONSUMERS_ADAPTER_OUT',
        str(ws.store.root / 'captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    held, exchanges, factory_roles, vision_factory_calls = {}, [], [], []
    models = {role: configured_model(ws.store, role) for role in roles}
    # Only the extra-vision test creates a later vision client. The helper's
    # initial fake vision remains untouched; unexpected later services fail.
    vision = configured_vision_client() if followup_vision else None
    def normal(messages):
        if case == P09:
            original = tool_reply(messages, 'p09-supervision')
            assert original in wire_tool_results(messages, 'read_task_supervision')
            value = result_value(original)
            held['actual_supervision_wire_message'] = original.model_dump()
            if value.get('complete_tool_result') is False:
                assert value['exact_data_tool'] == 'read_tool_observation'
                pages = [result_value(m) for m in wire_tool_results(messages, 'read_tool_observation')]
                offset = 0
                for page in pages:
                    assert page['observation_ref'] == value['observation_ref'] and page['offset'] == offset
                    offset += len(page['text'])
                assert pages and pages[-1]['next_offset'] is None
                held['actual_recovery_pages'] = pages
                value = json.loads(''.join(p['text'] for p in pages))
            assert value['ok'] is True and len(value['result']['tasks']) == 1
            actual = value['result']['tasks'][0]
            expected = reconcile(ContentStore(ws.store), actual['task_id'])
            for field in ('requirements', 'remaining', 'execution_complete', 'semantic_coverage_verified'):
                assert actual[field] == expected[field], 'P09_NEXT_COORDINATOR_FIELD:' + field
            assert actual['execution_complete'] is True and actual['remaining'] == []
            assert actual['semantic_coverage_verified'] is False
            assert [r['requirement']['scope_id'] for r in actual['requirements']] == ['rule-comparison', 'second-comparison']
            assert [r['state'] for r in actual['requirements']] == ['completed', 'completed']
            assert [r['verdict'] for r in actual['requirements']] == ['not_satisfied', 'not_satisfied']
            held['actual_received_supervision'] = value
            return AIMessage(content=TRUE_FINAL)
        actual = tool_reply(messages, 'compare')
        assert actual in wire_tool_results(messages, 'perform_assigned_artifact_review')
        public = result_value(actual)
        held['public_error'], held['public_wire_message'] = public, actual.model_dump()
        held['output_failure'] = assert_received_output_failure(public)
        return AIMessage(content=HONEST)

    def reviewer_answer(messages):
        role_requests = sum(e['role'] == active_role for e in exchanges)
        if not followup_vision:
            assert role_requests == 0, 'Unexpected additional consumer request'
            return normal(messages)
        if role_requests == 0:
            normal(messages)  # Exact public JSON error, without native-only metadata.
            original = result_value(tool_reply(messages, 'page'))
            assert original['ok'] and original['result']['status'] == 'observed'
            assert QUESTION != original['result']['question']
            held['old_vision_from_native_input'] = original
            held['vision_reservations_before'] = vision_reservations(ws)
            held['selected_followup_args'] = {'render_ref': original['result']['source']['render_ref'],
                'page': original['result']['source']['page'], 'question': QUESTION}
            return action('inspect_rendered_page', 'consumer-followup-page', **held['selected_followup_args'])
        assert role_requests == 1, 'No retry or final substitution after the second Reviewer request'
        actual = tool_reply(messages, 'consumer-followup-page')
        assert actual in wire_tool_results(messages, 'inspect_rendered_page')
        public = result_value(actual)
        assert public['ok'], public
        assert public['result']['status'] == 'observed' and public['result']['question'] == QUESTION
        assert public['result']['observation'] == VISUAL_OBSERVATION
        assert not public['result']['reused']
        held['new_vision_wire_message'] = actual.model_dump()
        held['new_vision_public'] = public
        return AIMessage(content=HONEST)

    async def dispatch_body(http_request, role):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert not zero_remaining, 'Local refusal must precede MockTransport dispatch'
        wire = json.loads(http_request.content)
        # Decode every provider role. This is response-selection observation,
        # never a replacement for the application's actual request messages.
        messages = [_convert_dict_to_message(m) for m in wire['messages']]
        held.setdefault('decoded_role_sequences', []).append([m['role'] for m in wire['messages']])
        if role == 'vision':
            assert followup_vision and [e['role'] for e in exchanges] == ['reviewer']
            assert wire['model'] == VISION_MODEL and not wire.get('tools')
            assert [m['role'] for m in wire['messages']] == ['system', 'user']
            content = wire['messages'][-1]['content']
            assert [v['text'] for v in content if v['type'] == 'text'] == [QUESTION]
            images = [v['image_url'] for v in content if v['type'] == 'image_url']
            assert len(images) == 1 and images[0]['detail'] == 'high'
            prefix, encoded = images[0]['url'].split(',', 1)
            assert prefix == 'data:image/png;base64'
            held['wire_png_sha256'] = hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()
            answer = AIMessage(content=VISUAL_OBSERVATION)
        else:
            assert role == active_role, 'Only the selected native consumer may call a model in this fixture'
            if followup_vision and any(e['role'] == 'reviewer' for e in exchanges):
                assert [e['role'] for e in exchanges] == ['reviewer', 'vision']
            answer = reviewer_answer(messages)
        raw = response_body(wire, answer, len(exchanges) + 1)
        exchanges.append({'role': role, 'wire': wire, 'response': raw})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=raw)

    async def dispatch(http_request, role):
        try:
            return await dispatch_body(http_request, role)
        except Exception as exc:
            if 'first_mock_callback_error' not in held:
                error = {'role': role, 'type': type(exc).__name__, 'message': str(exc),
                    'traceback': traceback.format_exc(), 'request_body': http_request.content.decode('utf-8')}
                held['first_mock_callback_error'] = error
                dump(folder / 'first-mock-callback-error.json', error)
            raise  # Preserve original exception and production SDK retry policy.

    for role, model in models.items():
        async def model_transport(http_request, role=role):
            return await dispatch(http_request, role)
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(model_transport)
        model.http_async_client._mounts = {}
    if vision is not None:
        async def vision_transport(http_request):
            return await dispatch(http_request, 'vision')
        await vision._client._transport.aclose()
        vision._client._transport = httpx.MockTransport(vision_transport)
        vision._client._mounts = {}

    def original_model(store, role):
        assert store is ws.store and role in models
        factory_roles.append(role)
        return models[role]

    def original_vision():
        assert followup_vision and vision is not None, 'No unexpected live/fake visual fallback'
        assert not vision_factory_calls, 'No automatic second later-vision client'
        vision_factory_calls.append('vision')
        return vision

    monkeypatch.setattr(adapter, 'configured_model', original_model)
    # Planned Main-owned symbol: strict setattr intentionally fails if not wired.
    monkeypatch.setattr(adapter, 'configured_vision_client', original_vision)
    requests = RequestBudget(1 if zero_remaining else 4)
    if zero_remaining:
        # RequestBudget(0) is invalid by the current contract. Preoccupy its
        # only admission explicitly; these tests assert adapter delta, not total.
        requests.reserve()
    before = requests.snapshot()
    tokens = TokenBudget(ws.store.root / 'mock-review-consumers-budget.db', 10000,
                         {'glm-5.3': 1000, VISION_MODEL: 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, case, live=True)
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    capture = read_json(folder / 'capture.json')
    wires, responses = read_json(folder / 'wire-requests.json'), read_json(folder / 'wire-responses.json')
    dump(folder / 'isolated-budget.json', {'test_only': True, 'before': before,
        'request': requests.snapshot(), 'token': tokens.snapshot(), 'rows': rows,
        'zero_remaining_is_explicit_preoccupied_capacity': zero_remaining})
    dump(folder / 'oracle-observations.json', held)
    request.node.user_properties.append(('review_consumer_adapter', str(folder)))

    expected = 0 if zero_remaining else 3 if followup_vision else 1
    expected_roles = [] if zero_remaining else ['reviewer', 'vision', 'reviewer'] if followup_vision else [active_role]
    assert [e['role'] for e in exchanges] == expected_roles
    assert set(factory_roles) == set(roles) and len(factory_roles) == len(roles)
    assert {m['role'] for m in result['configured_models']} == set(roles)
    assert all(m['sdk_max_retries'] == 5 and m['httpx_connect_retries'] == 0 and
               m['logical_request_deadline_seconds'] == 600 for m in result['configured_models'])
    assert all(m.http_async_client.is_closed and m.root_client.is_closed() for m in models.values())
    assert vision_factory_calls == (['vision'] if followup_vision else [])
    if vision is not None:
        assert vision.max_retries == 5 and vision.is_closed() and vision._client.is_closed
    assert result['mode'] == 'live' and not result['observer_errors']
    assert result['admitted_http_attempts'] == result['observed_http_requests'] == expected
    assert result['count_origin'] == 'request_budget_reserved_delta'
    assert result['observed_http_requests_not_dispatch_proof'] is True
    assert requests.count - before['reserved_http_attempts'] == expected
    assert result['observed_http_responses'] == len(exchanges) == len(responses) == expected
    assert result['observed_request_hook_entries'] == len(wires) == expected + int(zero_remaining)
    assert result['hook_entries_without_admission'] == int(zero_remaining)
    assert result['admitted_without_observed_response'] == 0
    assert tokens.snapshot()['recorded_tokens'] == 2 * expected
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    states = {'known_not_sent': 1} if zero_remaining else {'settled': expected}
    assert tokens.snapshot()['attempt_states'] == states
    assert len(rows) == expected + int(zero_remaining)
    if zero_remaining:
        assert rows[0]['state'] == 'known_not_sent' and rows[0]['used'] == 0 and rows[0]['response_id'] is None
        assert rows[0]['reason'] == 'Local transport admission rejected before send'
        assert before['remaining_http_attempts'] == 0
    else:
        assert {r['response_id'] for r in rows} == {e['response']['id'] for e in exchanges}
        assert all(r['state'] == 'settled' and r['used'] == 2 for r in rows)
    for exchange, observed, response in zip(exchanges, wires[:expected], responses, strict=True):
        assert observed['role'] == response['role'] == exchange['role']
        assert observed['body'] == exchange['wire']
        assert json.loads(response['body']) == exchange['response']
        assert response['request_sequence'] == observed['sequence']
    # These observers contain body/model/schema, never request headers/keys.
    assert all('headers' not in w and 'api_key' not in w for w in [*wires, *responses])
    assert 'synthetic-key' not in json.dumps([wires, responses], ensure_ascii=False)
    consumer_wires = [w for w in wires if w['role'] == active_role]
    if case == P09:
        events = capture['prepared']['consumer_events']
        assert all(e['phase'] == 'unchanged_coordinator_handler' for e in events)
        actual_returns = [[m.model_dump() for m in messages_from_dict(e['messages']) if m.type == 'tool'] for e in events]
    else:
        events = [e for e in capture['phase_events'] if e['phase'] == 'native_reviewer_handler']
        actual_returns = [e['actual_tool_returns'] for e in events]
    assert len(capture['native_model_calls']) == len(consumer_wires) == (2 if followup_vision else 1)
    assert {c['role'] for c in capture['native_model_calls']} == {active_role}
    for native, observed in zip(actual_returns, consumer_wires, strict=True):
        assert {m['tool_call_id']: m['content'] for m in native} == {
            m['tool_call_id']: m['content'] for m in observed['body']['messages'] if m['role'] == 'tool'}
    for wire in consumer_wires:
        names = {t['function']['name'] for t in wire['body']['tools']}
        assert ({'task', 'read_task_supervision'} if case == P09 else
                {'perform_assigned_artifact_review', 'inspect_rendered_page'}) <= names
    if zero_remaining:
        if case==P12:
            assert result['status'] == 'native_observation_requires_review'
            assert capture['raised_error'] is None and capture.get('runtime_result',capture.get('runtime'))['last_error'] is None
            task_failure=json.loads(capture['parent']['task_return']["content"])
            task_failure=task_failure.get('metadata',task_failure)
            assert task_failure['ok'] is False and task_failure['code']=='DELEGATED_EXECUTION_FAILED'
            assert task_failure['error']['type']=='RequestBudgetExceeded'
            assert task_failure['error']['message']=='MODEL_REQUEST_BUDGET_REACHED'
        else:
            assert result['status']=='native_execution_incomplete'
            assert capture['raised_error'] or (capture.get('runtime_result',capture.get('runtime')) or {}).get('last_error')
            assert 'MODEL_REQUEST_BUDGET_REACHED' in json.dumps([result,capture['raised_error']],ensure_ascii=False)
    else:
        assert result['status'] == 'native_observation_requires_review'
        assert capture['raised_error'] is None
        assert capture.get('runtime_result', capture.get('runtime'))['last_error'] is None
    return {'result': result, 'capture': capture, 'held': held, 'folder': folder,
            'wires': wires, 'exchanges': exchanges, 'rows': rows}


def assert_completed_negative(bundle, *, refused):
    capture, held = bundle['capture'], bundle['held']
    assert capture['originals_unchanged'] and not capture['host_completion_actions']
    assert len(capture['checker_calls']) == 1 and capture['checker_calls'][0]['origin'] == 'recorded_R1_fixture'
    prepared = capture['prepared']
    native = next(m['data'] for m in prepared['consumer_events'][0]['messages']
                  if m['type'] == 'tool' and m['data']['tool_call_id'] == 'p09-supervision')
    assert native['name'] == 'read_task_supervision' and native['status'] == 'success'
    assert len(capture['saved_reviews']) == len(capture['saved_tasks']) == 1
    assert capture['saved_reviews'] == prepared['saved_reviews_before_consumer']
    assert capture['saved_tasks'] == prepared['saved_tasks_before_consumer']
    saved = capture['saved_reviews'][0]['payload']['items']
    assert_items(prepared['reviewer_public_result']['items'], capture['fixture']['expected_assessments']['items'],
                 saved, capture['fixture']['task_call']['args']['review_requirements'], held)
    assert [i['verdict'] for i in saved] == ['not_satisfied', 'not_satisfied']
    status = capture['saved_task_status'][0]
    assert status['execution_complete'] is True and status['remaining'] == []
    assert status['semantic_coverage_verified'] is False
    assert capture['semantic_status'] == 'not_semantically_assessed'
    assert capture['finals'] == ([] if refused else [TRUE_FINAL])
    if not refused:
        assert held['actual_received_supervision'] == prepared['supervision_received']
        assert native['content'] == held['actual_supervision_wire_message']['content']
        assert native['tool_call_id'] == held['actual_supervision_wire_message']['tool_call_id']


def assert_original_checker_rejection(bundle, *, refused, new_vision=False):
    capture, held = bundle['capture'], bundle['held']
    diagnostic, oracle = capture['host_diagnostic_held'], capture['oracle']
    first_error = ToolMessage.model_validate(diagnostic['first_consumer_error'])
    error_value = result_value(first_error)
    assert first_error.name == 'perform_assigned_artifact_review'
    assert first_error.status == 'error' and error_value['ok'] is False
    output_failure = assert_received_output_failure(error_value)
    assert capture['fixture_variant'] == diagnostic['fixture_variant'] == 'current_contract_duplicate'
    assert capture['fixture_preparation_actions'] == 4
    assert capture['fixture_vision_calls'] == 1 and capture['fixture_vision_closed']
    assert capture['vision_routes'] == ([{'origin': 'recorded_vision_fixture'}, {'origin': 'consumer_factory'}]
                                       if new_vision else [{'origin': 'recorded_vision_fixture'}])
    assert len(capture['text_service_calls']) == 1 and capture['text_service_calls'][0]['origin'] == 'recorded_R3_fixture'
    first_wire = next(w for w in bundle['wires'] if w['role'] == 'reviewer')['body']
    schema = next(t['function']['parameters'] for t in first_wire['tools']
                  if t['function']['name'] == 'perform_assigned_artifact_review')
    Draft202012Validator(schema).validate(diagnostic['actual_caller_args'])
    assert diagnostic['actual_caller_args']['observation_receipts'] == diagnostic['receipts']
    packet = diagnostic['checker_packet']
    assert packet['requirements'][0]['required_checks'] == capture['fixture']['original_packet']['requirements'][0]['required_checks']
    assert len(packet['requirements'][0]['required_checks']) == 2
    assert [e['receipt_id'] for e in packet['evidence']] == diagnostic['receipts']
    assert packet['task_id'] == diagnostic['actor']['task_id']
    changes = []
    replay = diagnostic['checker_output']
    original_rebound = rebind_strings(capture['fixture']['original_output'], diagnostic['identity_map'], changes)
    assert original_rebound == diagnostic['original_rebound_output']
    restored = deepcopy(replay)
    restored['items'][0]['artifact_refs'] = diagnostic['compatibility_projection']['before']
    assert restored == original_rebound
    assert diagnostic['compatibility_projection']['path'] == '$.items[0].artifact_refs'
    assert replay['items'][0]['artifact_refs'] == packet['requirements'][0]['artifact_refs']
    assert changes == diagnostic['identity_rebindings']
    assert [c['requirement_index'] for c in replay['items'][0]['check_results']] == [0, 0]
    Draft202012Validator(packet['output_schema']).validate(replay)
    with pytest.raises(ValidationError, match='DUPLICATE_CHECK_RESULT'):
        ReviewSubmission.model_validate(replay)
    assert json.loads(capture['text_service_calls'][0]['raw_response']['content']) == replay
    before, after = diagnostic['state_before_consumer'], oracle['analysis_state_after']
    raw = [v for v in before['analyses'].values() if 'analysis' in v]
    assert len(raw) == 1 and json.loads(raw[0]['analysis']) == replay
    assert output_failure['raw_operation'] == raw[0]['operation']
    for section in ('analyses', 'reservations'):
        assert {k: after[section][k] for k in before[section]} == before[section]
    if not new_vision:
        assert after == before
    assert diagnostic['review_records_before_consumer'] == oracle['review_records'] == []
    assert oracle['original_objects_unchanged'] and oracle['recorded_checker_has_duplicate_indexes']
    assert oracle['status'] == 'no_saved_review_incomplete' and oracle['semantic_status'] == 'needs_semantic_review'
    old, current = diagnostic['status_before_consumer'], oracle['current_status']
    assert not old['execution_complete'] and not current['execution_complete']
    assert len(old['remaining']) == len(current['remaining']) == 1
    assert current['remaining'] == old['remaining']
    assert not capture['host_completion_actions']
    if refused:
        assert capture['parent']['task_return']['status']=='error'
    else:
        assert error_value == held['public_error']
        assert first_error.content == held['public_wire_message']['content']
        assert first_error.tool_call_id == held['public_wire_message']['tool_call_id']
        assert capture['parent']['task_return']['content'] == HONEST
        supervision = capture['parent']['supervision']
        assert supervision['ok'] is True
        task = next(t for t in supervision['result']['tasks'] if t['task_id'] == diagnostic['actor']['task_id'])
        assert not task['execution_complete'] and task['remaining'] == current['remaining']
        assert task['semantic_coverage_verified'] is False


async def test_p09_configured_sdk_completed_negative_consumer(ws, request, monkeypatch):
    bundle = await run_sdk(ws, request, monkeypatch, P09)
    assert_completed_negative(bundle, refused=False)


async def test_p09_zero_remaining_refuses_before_transport(ws, request, monkeypatch):
    bundle = await run_sdk(ws, request, monkeypatch, P09, zero_remaining=True)
    assert_completed_negative(bundle, refused=True)


async def test_p12_configured_sdk_rejected_checker_honest_final(ws, request, monkeypatch):
    bundle = await run_sdk(ws, request, monkeypatch, P12)
    assert_original_checker_rejection(bundle, refused=False)


async def test_p12_zero_remaining_refuses_before_transport(ws, request, monkeypatch):
    bundle = await run_sdk(ws, request, monkeypatch, P12, zero_remaining=True)
    assert_original_checker_rejection(bundle, refused=True)


async def test_p12_native_followup_vision_shares_three_mock_http_and_budget(ws, request, monkeypatch):
    bundle = await run_sdk(ws, request, monkeypatch, P12, followup_vision=True)
    assert_original_checker_rejection(bundle, refused=False, new_vision=True)
    capture, held = bundle['capture'], bundle['held']
    prepared = read_json(bundle['folder'] / 'visual-preparation.json')
    diagnostic, public = capture['host_diagnostic_held'], held['new_vision_public']
    result = public['result']
    last_event = [e for e in capture['phase_events'] if e['phase'] == 'native_reviewer_handler'][-1]
    native = next(m for m in last_event['actual_tool_returns'] if m['tool_call_id'] == 'consumer-followup-page')
    assert native['name'] == 'inspect_rendered_page' and native['status'] == 'success'
    assert native['content'] == held['new_vision_wire_message']['content']
    assert native['tool_call_id'] == held['new_vision_wire_message']['tool_call_id']
    original = held['old_vision_from_native_input']
    assert result['question'] == QUESTION and QUESTION != prepared['question']
    assert result['actor'] == diagnostic['actor']
    assert result['source'] == original['result']['source']
    assert result['source']['render_ref'] == prepared['render_ref']
    assert result['source']['export_ref'] == prepared['export_ref']
    assert result['source']['page'] == 1 and result['source']['crop'] is None
    assert result['source']['coverage'] == 'full_page_image'
    asset = prepared['render_record']['payload']['page_assets'][0]
    assert result['image_sha256'] == held['wire_png_sha256'] == asset['sha256']
    assert hashlib.sha256((ws.store.root / asset['asset_ref']).read_bytes()).hexdigest() == asset['sha256']
    assert result['model_requested'] == result['model_returned'] == VISION_MODEL
    assert result['response_id'] == bundle['exchanges'][1]['response']['id']
    assert result['observation'] == VISUAL_OBSERVATION and result['limitations']
    assert result['operation'] != original['result']['operation']
    assert public['receipt_id'] not in diagnostic['receipts']
    with ws.store.connect() as db:
        row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (public['receipt_id'],)).fetchone()
    assert row is not None and row[0] == diagnostic['actor']['id'] and json.loads(row[1]) == result
    before = diagnostic['state_before_consumer']['analyses']
    after = capture['oracle']['analysis_state_after']['analyses']
    assert set(after) - set(before) == {result['operation']}
    assert after[result['operation']] == result
    old_reservations, new_reservations = held['vision_reservations_before'], vision_reservations(ws)
    assert {k: new_reservations[k] for k in old_reservations} == old_reservations
    key = 'vision_attempt:' + result['operation']
    assert set(new_reservations) - set(old_reservations) == {key}
    assert new_reservations[key]['state'] == 'completed'
    assert new_reservations[key]['actor'] == diagnostic['actor']
    assert new_reservations[key]['result'] == result
    dump(bundle['folder'] / 'new-vision-binding.json', {'observation': public,
        'old_reservations': old_reservations, 'all_reservations_after': new_reservations,
        'checker_not_retried': True, 'review_still_incomplete': True,
        'mock_http_roles': [e['role'] for e in bundle['exchanges']],
        'limits': 'Native scripted recovery choice and real configured SDK mechanics only; no autonomous choice, paid call or engineering acceptance.'})
