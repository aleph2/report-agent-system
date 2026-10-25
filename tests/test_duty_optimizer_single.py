"""Single-feedback learning outcome calibrations, fake decisions and local SDK."""
import json
import os
from pathlib import Path
import socket

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from duty_probe_agent_decisions import dump
from duty_probe_optimizer_outcome import CONDITIONS, PREFERENCE, STRATEGY, UNSUPPORTED_CONTROL_ASSERTION
from duty_probe_optimizer_single import capture_optimizer_single
from report_agent.deep_models import configured_model
from report_agent.store import digest
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_deadline import close_model
from test_deep_runtime import Driver
from test_task_supervision import ws


VARIANTS = ('candidate', 'no-change', 'missing-disposition', 'fabricated-strategy')


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    for name in ('connect', 'connect_ex', 'sendto'):
        original = getattr(socket.socket, name)
        def denied(sock, *args, _original=original, **kwargs):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                pytest.fail('External network forbidden in single-feedback tests')
            return _original(sock, *args, **kwargs)
        monkeypatch.setattr(socket.socket, name, denied)


def single_optimizer_script(variant, held):
    def unused_preparation(messages):
        raise AssertionError('The explicit five-read setup must occupy native step zero')

    def after_reads(messages):
        pages = {}
        for field in ('correction', 'before', 'evidence'):
            raw = tool_reply(messages, 'a-' + field)
            pages[field] = result_value(raw)
            assert raw.status == 'success' and pages[field]['next_offset'] is None
            assert pages[field]['offset'] == 0 and len(pages[field]['text']) == pages[field]['total_chars']
        assert pages['correction']['text'] == PREFERENCE
        evidence = json.loads(pages['evidence']['text'])
        held['feedback_id'] = pages['correction']['feedback_id']
        assert {p['feedback_id'] for p in pages.values()} == {held['feedback_id']}
        source_raw = tool_reply(messages, 'a-source')
        source = result_value(source_raw)
        assert source_raw.status == 'success' and source['next_offset'] is None
        assert source['ref'] == evidence[0]['source_ref']
        assert json.loads(source['text'])['ref'] == source['ref']
        assert json.loads(source['text'])['payload']['content'] == PREFERENCE
        assert source['digest'] == digest(json.loads(source['text']))
        index_raw = tool_reply(messages, 'candidate-index')
        index = result_value(index_raw)
        assert index_raw.status == 'success' and index['items'] == []
        assert index['total'] == 0 and index['next_offset'] is None
        held['pages'], held['source'], held['candidate_index'] = pages, source, index
        if variant == 'no-change':
            return action('record_feedback_disposition', 'dispose-a', feedback_id=held['feedback_id'],
                outcome='no_change', rationale='The explicit preference remains applicable and unchanged. This isolated handling introduces no additional reusable candidate or report edits.')
        strategy = STRATEGY + (' ' + UNSUPPORTED_CONTROL_ASSERTION if variant == 'fabricated-strategy' else '')
        held['propose_args'] = {'feedback_ids': [held['feedback_id']], 'kind': 'customer_preference',
            'title': 'Issues-only workbook preference', 'strategy': strategy, 'conditions': CONDITIONS,
            'verification': 'Check a later scoped workbook for identified issues versus routine file-inventory rows.'}
        return action('propose_experience', 'propose-a', **held['propose_args'])

    def after_candidate(messages):
        if variant == 'no-change':
            value = result_value(tool_reply(messages, 'dispose-a'))
            assert value['outcome'] == 'no_change' and value['quality_verified'] is False
            return AIMessage(content='Assigned feedback has a recorded no-change disposition. The original requirement remains applicable; no candidate, report edit or quality approval is claimed.')
        raw = tool_reply(messages, 'propose-a')
        candidate = result_value(raw)
        assert raw.status == 'success'
        for key, value in held['propose_args'].items():
            assert candidate[key] == value
        held['candidate'] = candidate
        if variant == 'missing-disposition':
            # Only the required disposition is omitted. The exact same final
            # completion claim as the normal case must not close accounting.
            return AIMessage(content=final_text())
        return action('record_feedback_disposition', 'dispose-a', feedback_id=held['feedback_id'], outcome='candidate',
            experience_id=candidate['id'], experience_version=candidate['version'],
            rationale='An inactive candidate is saved for later validation; no publication or quality approval.')

    def final_text():
        return 'Assigned feedback is accounted for; the candidate remains inactive and unverified.'

    def finish(messages):
        raw = tool_reply(messages, 'dispose-a')
        value = result_value(raw)
        assert raw.status == 'success' and value['feedback_id'] == held['feedback_id']
        assert value['quality_verified'] is False
        return AIMessage(content=final_text())

    return [unused_preparation, after_reads, after_candidate, finish]


def assert_single_outcome(capture, held, variant):
    assessment, fixture = capture['assessment'], capture['fixture']
    feedback_id = fixture['feedback']['id']
    assert fixture['feedback_originals'] == [fixture['feedback']]
    assert held['feedback_id'] == feedback_id
    for field, page in held['pages'].items():
        assert (page['text'] if field == 'correction' else json.loads(page['text'])) == fixture['feedback'][field]
        assert page['digest'] == digest(fixture['feedback'][field])
    assert json.loads(held['source']['text']) == fixture['source_original']
    assert assessment['feedback_originals_unchanged'] and assessment['business_originals_unchanged']
    assert assessment['active_assignment_after_worker'] is None
    assert assessment['all_candidates_inactive'] and not assessment['active_library']
    assert assessment['job']['quality_verified'] is False
    assert not assessment['unexpected_feedback_ids']
    assert all(d['quality_verified'] is False for d in assessment['dispositions'].values())
    assert all(link['valid'] for link in assessment['candidate_links'])
    if variant == 'missing-disposition':
        assert capture['raised_error'] == {'type': 'ActionRejected', 'message': 'LEARNING_FEEDBACK_UNACCOUNTED'}
        assert assessment['job']['state'] == 'failed'
        assert assessment['missing_feedback_ids'] == [feedback_id] and not assessment['dispositions']
        assert all(row['status'] == 'failed' for row in assessment['queue'])
    else:
        assert capture['raised_error'] is None and capture['runtime_result']['state'] == 'completed'
        assert assessment['job']['state'] == 'completed' and not assessment['missing_feedback_ids']
        assert set(assessment['dispositions']) == {feedback_id}
        assert all(row['status'] == 'completed' for row in assessment['queue'])
    if variant == 'no-change':
        assert not assessment['candidates'] and not assessment['job']['candidates']
        assert assessment['dispositions'][feedback_id]['outcome'] == 'no_change'
    else:
        assert len(assessment['candidates']) == 1
        candidate = assessment['candidates'][0]
        assert candidate['id'] == held['candidate']['id'] and candidate['version'] == 1
        assert candidate['customer'] == fixture['customer'] and candidate['project'] == ''
        assert candidate['conditions'] == CONDITIONS and candidate['feedback_ids'] == [feedback_id]
        if variant != 'missing-disposition':
            assert assessment['dispositions'][feedback_id]['candidate'] == {'id': candidate['id'], 'version': 1}
    if variant == 'fabricated-strategy':
        assert assessment['semantic_status'] == 'needs_semantic_review'
        assert len(assessment['unsupported_control_assertions']) == 1
        assert assessment['unsupported_control_assertions'][0]['origin'] == 'candidate.strategy'
    else:
        assert assessment['semantic_status'] == 'not_semantically_assessed'
        assert not assessment['unsupported_control_assertions']
    phases = capture['preparation_phases']
    assert phases[0]['phase'] == 'explicit_fake_read_setup' and len(phases[0]['action']['tool_calls']) == 5
    assert len(phases[1]['native_tool_returns']) == 5
    assert all(p['phase'] == 'unchanged_consumer_handler' for p in phases[1:])
    assert all(c['boundary'] == 'native_optimizer_decision' for c in capture['native_model_calls'])
    assert len(capture['native_model_calls']) == (2 if variant in ('no-change', 'missing-disposition') else 3)


@pytest.mark.parametrize('variant', VARIANTS)
async def test_single_feedback_native_outcome_controls(ws, request, variant):
    held = {}
    driver = Driver(optimizer=single_optimizer_script(variant, held))
    folder = Path(os.environ.get('REPORT_OPTIMIZER_SINGLE_OUT', str(ws.store.root / 'captures'))) / variant
    capture = await capture_optimizer_single(ws, folder, driver)
    request.node.user_properties.append(('single_feedback_capture', str(folder)))
    assert_single_outcome(capture, held, variant)
    assert len(driver.calls) == len(capture['native_model_calls'])
    names = {s['name'] for s in driver.bindings['optimizer'][-1]}
    assert {'read_learning_feedback', 'read_learning_evidence', 'read_experience_candidates',
            'propose_experience', 'record_feedback_disposition', 'analyze_learning_material'} <= names
    assert not {'task', 'release', 'commit_objects'} & names


async def test_single_feedback_configured_sdk_preserves_actual_prepared_read_messages(ws, request, monkeypatch):
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_OPTIMIZER_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    model = configured_model(ws.store, 'optimizer')
    held, wires, raw_responses = {}, [], []
    script = single_optimizer_script('candidate', held)
    async def transport(request):
        wire = json.loads(request.content)
        wires.append(wire)
        # Decode solely to select a fake provider answer, never to construct or
        # replace actual application/model input messages.
        actual_tools = [ToolMessage(content=m['content'], tool_call_id=m['tool_call_id'], name=m.get('name', ''))
                        for m in wire['messages'] if m['role'] == 'tool']
        answer = script[len(wires)](actual_tools)
        message = {'role': 'assistant', 'content': answer.content}
        if answer.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'])}} for c in answer.tool_calls]
        response = {'id': 'offline-single-' + str(len(wires)), 'object': 'chat.completion', 'created': 1,
            'model': wire['model'], 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if answer.tool_calls else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        raw_responses.append(response)
        return httpx.Response(200, json=response)
    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(transport)
    model.http_async_client._mounts = {}
    folder = Path(os.environ.get('REPORT_OPTIMIZER_SINGLE_OUT', str(ws.store.root / 'captures'))) / 'sdk-prepared-reads'
    try:
        capture = await capture_optimizer_single(ws, folder, lambda role: model)
    finally:
        await close_model(model)
        folder.mkdir(parents=True, exist_ok=True)
        dump(folder / 'sdk-wire.json', wires)
        dump(folder / 'sdk-responses.json', raw_responses)
    request.node.user_properties.append(('single_feedback_capture', str(folder)))
    assert_single_outcome(capture, held, 'candidate')
    assert len(wires) == len(raw_responses) == 3
    actual_returns = {m['tool_call_id']: m['content'] for m in capture['preparation_phases'][1]['native_tool_returns']}
    assert {m['tool_call_id']: m['content'] for m in wires[0]['messages'] if m['role'] == 'tool'} == actual_returns
    assert set(actual_returns) == {'a-correction', 'a-before', 'a-evidence', 'a-source', 'candidate-index'}
    for wire in wires:
        names = {t['function']['name'] for t in wire['tools']}
        assert {'read_learning_feedback', 'read_learning_evidence', 'analyze_learning_material',
                'propose_experience', 'record_feedback_disposition'} <= names
        assert not {'task', 'release', 'commit_objects'} & names
