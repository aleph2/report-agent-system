"""Three-feedback SDK Mock: saved dispositions are not worker completion.

The original client, native worker, ToolNode, parser and accounting remain in
use. Provider responses alone are synthetic; no external network or paid calls.
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
from duty_probe_optimizer_three import FINAL
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import digest
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_optimizer_adapter import adapter, no_external_network
from test_duty_optimizer_three import three_optimizer_script
from test_task_supervision import ws


ROOT = Path(__file__).resolve().parents[1]
CASE = 'optimizer-three-feedback'


def source_hashes():
    paths = [Path(__file__), Path(adapter.__file__), ROOT / 'tests/duty_probe_optimizer_three.py',
        ROOT / 'tests/test_duty_optimizer_three.py', ROOT / 'src/report_agent/learning_worker.py',
        ROOT / 'src/report_agent/learning_runtime.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def assert_originals_and_assignment(capture, held):
    assessment, fixture = capture['assessment'], capture['fixture']
    ids = [fixture['feedback'][label]['id'] for label in ('f1', 'f2', 'f3')]
    assert fixture['targets']['f1-row'] != fixture['targets']['f3-block']
    assert fixture['feedback']['f1']['target'] == fixture['targets']['f1-row']
    assert fixture['feedback']['f3']['target'] == fixture['targets']['f3-block']
    assert fixture['feedback']['f2']['target'] == {}
    assert [r['feedback_id'] for r in fixture['queue_before_claim']] == ids
    assert all(r['status'] == 'queued' and r['claim_id'] is None for r in fixture['queue_before_claim'])
    assert len(fixture['feedback_originals']) == 3
    assert len(fixture['candidate_originals']) == len(assessment['candidates']) == 1
    assert assessment['candidates'][0] == fixture['existing_candidate'] == held['candidate']
    assert not assessment['new_candidates']
    # The current worker adds job.candidates only on normal completion. Failed
    # jobs still have the original library; do not invent a completion field.
    assert not assessment['job'].get('candidates')
    assert assessment['candidate_originals_unchanged'] and assessment['feedback_originals_unchanged']
    assert assessment['business_originals_unchanged'] and assessment['source_originals_unchanged']
    assert assessment['active_assignment_after_worker'] is None
    assert assessment['all_candidates_inactive'] and not assessment['active_library']
    assert assessment['job']['quality_verified'] is False
    assert assessment['semantic_status'] == 'not_semantically_assessed'
    assert not assessment['unexpected_feedback_ids']
    assert assessment['candidate_links'] == [{'feedback_id': ids[0],
        'candidate': {'id': held['candidate']['id'], 'version': 1}, 'valid': True}]
    for label, feedback in fixture['feedback'].items():
        assert held['feedback'][label]['id'] == feedback['id']
        for field in ('correction', 'before', 'evidence'):
            page = held['pages'][label + '-' + field]
            assert (page['text'] if field == 'correction' else json.loads(page['text'])) == feedback[field]
            assert page['digest'] == digest(feedback[field])
    for label in ('f1', 'f3'):
        assert json.loads(held['sources'][label]['text']) == fixture['source_originals'][label]
    assert capture['host_existing_candidate_preparation'] and capture['prepared_reads']
    assert not capture['host_completion_actions'] and not capture['host_candidate_publication']
    phases = capture['preparation_phases']
    assert phases[0]['phase'] == 'explicit_fake_read_setup'
    assert phases[0]['assignment']['feedback_ids'] == ids
    calls = phases[0]['action']['tool_calls']
    assert len(calls) == 12
    assert sum(c['name'] == 'read_learning_feedback' for c in calls) == 9
    assert sum(c['name'] == 'read_learning_evidence' for c in calls) == 2
    assert sum(c['name'] == 'read_experience_candidates' for c in calls) == 1
    assert {m['tool_call_id'] for m in phases[1]['native_tool_returns']} == {c['id'] for c in calls}
    assert all(p['phase'] == 'unchanged_consumer_handler' for p in phases[1:])
    assert len(assessment['queue']) == 3
    assert {r['claim_id'] for r in assessment['queue']} == {phases[0]['assignment']['id']}
    assert all(c['boundary'] == 'native_optimizer_decision' for c in capture['native_model_calls'])
    return assessment, ids


@pytest.mark.parametrize('omit_f2,cap', [(False, 4), (False, 1), (True, 4)],
    ids=['all-dispositions-and-final', 'all-dispositions-before-local-refusal', 'same-final-but-f2-unaccounted'])
async def test_optimizer_three_sdk_actual_dispositions_and_host_completion(ws, request, monkeypatch, omit_f2, cap):
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_OPTIMIZER_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    folder = Path(os.environ.get('REPORT_OPTIMIZER_THREE_ADAPTER_OUT', str(ws.store.root / 'captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    initial_hashes = source_hashes()
    dump(folder / 'source-hashes-before.json', initial_hashes)
    held, exchanges, factory_roles = {}, [], []
    script = three_optimizer_script(omit_f2, held)
    model = configured_model(ws.store, 'optimizer')

    async def transport(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        assert len(exchanges) < cap, 'Local refusal must happen before even MockTransport dispatch'
        wire = json.loads(http_request.content)
        # Convert all roles only to select the mock response, never to replace
        # actual application inputs. Wire ToolMessages do not carry status/name;
        # actual native status is checked separately below.
        messages = [_convert_dict_to_message(m) for m in wire['messages']]
        step = sum(isinstance(m, AIMessage) for m in messages)
        try:
            item = script[step]
            answer = item(messages) if callable(item) else item
        except Exception as exc:
            dump(folder / 'mock-oracle-error.json', {'step': step, 'type': type(exc).__name__,
                'message': str(exc), 'traceback': traceback.format_exc(), 'wire': wire})
            raise
        message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'], ensure_ascii=False)}} for c in answer.tool_calls]
        response = {'id': 'optimizer-three-mock-' + str(len(exchanges) + 1), 'object': 'chat.completion',
            'created': 1, 'model': wire['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'step': step, 'wire': wire, 'response': response})
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
    tokens = TokenBudget(ws.store.root / 'mock-three-budget.db', 10000, {'glm-5.3': 1000})
    with request_budget(requests), token_budget(tokens):
        result = await adapter.probe_native_decision(ws, folder, CASE, live=True)
    capture = json.loads((folder / 'capture.json').read_text('utf-8'))
    with sqlite3.connect(tokens.path) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY at,id')]
    dump(folder / 'isolated-budget.json', {'test_only': True, 'rows': rows,
        'request': requests.snapshot(), 'token': tokens.snapshot()})
    dump(folder / 'oracle-observations.json', held)
    dump(folder / 'source-hashes-after.json', source_hashes())
    request.node.user_properties.append(('optimizer_three_adapter_capture', str(folder)))
    count, refused = min(cap, 2), cap == 1
    assert source_hashes() == initial_hashes
    assert factory_roles == ['optimizer'] and not result['observer_errors']
    assert result['mode'] == 'live' and len(result['configured_models']) == 1
    policy = result['configured_models'][0]
    assert policy['role'] == 'optimizer' and policy['model'] == 'glm-5.3'
    assert policy['sdk_max_retries'] == 5 and policy['httpx_connect_retries'] == 0
    assert policy['logical_request_deadline_seconds'] == 600
    assert model.http_async_client.is_closed and model.root_client.is_closed()
    assert len(exchanges) == result['observed_http_responses'] == result['admitted_http_attempts'] == requests.count == count
    assert result['observed_request_hook_entries'] == 2
    assert result['admitted_without_observed_response'] == 0
    assert result['hook_entries_without_admission'] == int(refused)
    assert len(capture['native_model_calls']) == 2
    assert {c['role'] for c in capture['native_model_calls']} == {'optimizer'}
    assert tokens.snapshot()['recorded_tokens'] == 2 * count
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == ({'known_not_sent': 1, 'settled': 1} if refused else {'settled': 2})
    assert len(rows) == 2
    assert {r['response_id'] for r in rows if r['state'] == 'settled'} == {e['response']['id'] for e in exchanges}
    wires = json.loads((folder / 'wire-requests.json').read_text('utf-8'))
    responses = json.loads((folder / 'wire-responses.json').read_text('utf-8'))
    for exchange, wire, response in zip(exchanges, wires[:count], responses, strict=True):
        assert wire['body'] == exchange['wire'] and wire['role'] == response['role'] == 'optimizer'
        assert json.loads(response['body']) == exchange['response'] and response['request_sequence'] == wire['sequence']
    phases = capture['preparation_phases']
    assert len(phases) == 3
    for event, wire in zip(phases[1:], wires, strict=True):
        native_returns = event['native_tool_returns']
        assert all(m['status'] == 'success' for m in native_returns)
        assert {m['tool_call_id']: m['content'] for m in wire['body']['messages'] if m['role'] == 'tool'} == {
            m['tool_call_id']: m['content'] for m in native_returns}
        names = {t['function']['name'] for t in wire['body']['tools']}
        assert {'read_learning_feedback', 'read_learning_evidence', 'read_experience_candidates',
                'propose_experience', 'record_feedback_disposition', 'analyze_learning_material'} <= names
        assert not {'release', 'commit_objects', 'task'} & names
    assessment, ids = assert_originals_and_assignment(capture, held)
    actual_calls = phases[1]['response'][0]['data']['tool_calls']
    assert actual_calls == held['actual_disposition_calls']
    intended = held['intended_disposition_calls']
    assert actual_calls == ([intended[0], intended[2]] if omit_f2 else intended)
    expected_ids = {ids[0], ids[2]} if omit_f2 else set(ids)
    assert set(assessment['dispositions']) == expected_ids
    assert assessment['missing_feedback_ids'] == ([ids[1]] if omit_f2 else [])
    for call in actual_calls:
        args = call['args']
        saved = assessment['dispositions'][args['feedback_id']]
        assert saved['feedback_id'] == args['feedback_id'] and saved['outcome'] == args['outcome']
        assert saved['rationale'] == args['rationale'] and saved['quality_verified'] is False
        assert saved['claim_id'] == phases[0]['assignment']['id']
    assert assessment['dispositions'][ids[0]]['candidate'] == {'id': held['candidate']['id'], 'version': 1}
    if refused:
        assert result['status'] == 'native_execution_incomplete'
        assert capture['raised_error'] == {'type': 'RequestBudgetExceeded', 'message': 'MODEL_REQUEST_BUDGET_REACHED'}
        assert capture['runtime_result'] is None and assessment['job']['state'] == 'failed'
        assert 'response' not in phases[-1] and 'final_text' not in held
        assert all(r['status'] == 'failed' and r['error_type'] == 'RequestBudgetExceeded' for r in assessment['queue'])
        unsent = [r for r in rows if r['state'] == 'known_not_sent']
        assert len(unsent) == 1 and unsent[0]['used'] == 0 and unsent[0]['response_id'] is None
        assert unsent[0]['reason'] == 'Local transport admission rejected before send'
    else:
        assert phases[-1]['response'][-1]['data']['content'] == held['final_text'] == FINAL
        assert not phases[-1]['response'][-1]['data']['tool_calls']
        for label in ('f1', 'f3') if omit_f2 else ('f1', 'f2', 'f3'):
            assert assessment['dispositions'][capture['fixture']['feedback'][label]['id']] == held['public_dispositions'][label]
        if omit_f2:
            assert result['status'] == 'native_execution_incomplete'
            assert capture['raised_error'] == {'type': 'ActionRejected', 'message': 'LEARNING_FEEDBACK_UNACCOUNTED'}
            assert capture['runtime_result'] is None and assessment['job']['state'] == 'failed'
            assert all(r['status'] == 'failed' and r['error_type'] == 'ActionRejected' for r in assessment['queue'])
        else:
            assert result['status'] == 'native_observation_requires_review'
            assert capture['raised_error'] is None and capture['runtime_result']['state'] == 'completed'
            assert capture['runtime_result']['claim'] == phases[0]['assignment']
            assert assessment['job']['state'] == 'completed' and assessment['job']['candidates'] == []
            assert all(r['status'] == 'completed' and r['error_type'] is None for r in assessment['queue'])
    dump(folder / 'finite-oracle.json', {'paid_calls': 0, 'mock_responses': count,
        'local_unsent': int(refused), 'unknown': 0, 'preexisting_inactive_candidates': 1,
        'new_candidates': 0, 'saved_dispositions': len(assessment['dispositions']),
        'worker_state': assessment['job']['state'], 'same_final_text_when_received': FINAL,
        'no_autonomous_strategy_quality_report_change_or_publication_claim': True,
        'prepared_hook_input_is_not_provider_receipt': True})
