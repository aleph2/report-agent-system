"""Native fake controls for feedback accounting versus semantic adequacy."""
import json
import os
from pathlib import Path

import pytest
import httpx
from langchain_core.messages import AIMessage, ToolMessage

from duty_probe_optimizer_outcome import (CONDITIONS, MISSING, PREFERENCE, STRATEGY,
    SUSPICION, UNSUPPORTED_CONTROL_ASSERTION, capture_optimizer_outcome)
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws


VARIANTS = ('candidate-and-insufficient', 'both-without-candidate',
            'missing-second-disposition', 'fabricated-candidate-still-accounted')


def optimizer_script(variant, held):
    def first_read(messages):
        prefix = 'Your current assignment (first page; total and continuation are explicit) is: '
        task = messages[-1].content
        assignment, _ = json.JSONDecoder().raw_decode(task.split(prefix, 1)[1])
        held['ids'] = assignment['feedback_ids']
        assert assignment['total'] == 2 and assignment['next_offset'] is None
        return AIMessage(content='', tool_calls=[{
            'name': 'read_learning_feedback', 'id': label + '-' + field, 'type': 'tool_call',
            'args': {'feedback_id': identifier, 'field': field}}
            for label, identifier in zip(('a', 'b'), held['ids'], strict=True)
            for field in ('correction', 'before', 'evidence')])

    def after_read(messages):
        pages = {}
        for label in ('a', 'b'):
            for field in ('correction', 'before', 'evidence'):
                actual = tool_reply(messages, label + '-' + field)
                page = result_value(actual)
                assert actual.status == 'success' and page['next_offset'] is None
                assert page['offset'] == 0 and len(page['text']) == page['total_chars']
                pages[label + '-' + field] = page
        assert pages['a-correction']['text'] == PREFERENCE
        assert pages['b-correction']['text'] == SUSPICION
        assert json.loads(pages['b-evidence']['text']) == [MISSING]
        held['pages'] = pages
        if 'ids' not in held:
            held['ids'] = [pages['a-correction']['feedback_id'], pages['b-correction']['feedback_id']]
        a, b = held['ids']
        insufficient = {'name': 'record_feedback_disposition', 'id': 'handle-b', 'type': 'tool_call', 'args': {
            'feedback_id': b, 'outcome': 'insufficient_evidence',
            'rationale': 'No report version, location or evidence establishes a missing table title.'}}
        if variant == 'both-without-candidate':
            return AIMessage(content='', tool_calls=[{'name': 'record_feedback_disposition', 'id': 'handle-a',
                'type': 'tool_call', 'args': {'feedback_id': a, 'outcome': 'no_change',
                    'rationale': 'The preference remains recorded; defer a reusable candidate until its applicability is evaluated.'}}, insufficient])
        strategy = STRATEGY + (' ' + UNSUPPORTED_CONTROL_ASSERTION if variant == 'fabricated-candidate-still-accounted' else '')
        propose = {'name': 'propose_experience', 'id': 'propose-a', 'type': 'tool_call', 'args': {
            'feedback_ids': [a], 'kind': 'customer_preference', 'title': 'Issues-only workbook preference',
            'strategy': strategy, 'conditions': CONDITIONS,
            'verification': 'Check a later scoped workbook for identified issues versus routine file-inventory rows.'}}
        held['propose_args'] = propose['args']
        # The omission control changes only the B disposition call. The candidate
        # and final completion statement are the same as the normal control.
        return AIMessage(content='', tool_calls=[propose] + ([] if variant == 'missing-second-disposition' else [insufficient]))

    def after_candidate_or_dispositions(messages):
        if variant == 'both-without-candidate':
            for label in ('a', 'b'):
                record = result_value(tool_reply(messages, 'handle-' + label))
                assert record['feedback_id'] == held['ids'][0 if label == 'a' else 1]
                assert record['quality_verified'] is False
            return AIMessage(content='Both items have recorded dispositions; no candidate or validation is claimed.')
        actual = tool_reply(messages, 'propose-a')
        candidate = result_value(actual)
        assert actual.status == 'success'
        for name, value in held['propose_args'].items():
            assert candidate[name] == value
        held['candidate'] = candidate
        if variant != 'missing-second-disposition':
            record = result_value(tool_reply(messages, 'handle-b'))
            assert record['outcome'] == 'insufficient_evidence' and record['quality_verified'] is False
        return action('record_feedback_disposition', 'handle-a', feedback_id=held['ids'][0], outcome='candidate',
            experience_id=candidate['id'], experience_version=candidate['version'],
            rationale='An inactive preference candidate was saved for later validation; no publication or quality approval.')

    def finish(messages):
        record = result_value(tool_reply(messages, 'handle-a'))
        assert record['feedback_id'] == held['ids'][0] and record['quality_verified'] is False
        return AIMessage(content='All assigned feedback is accounted for; the candidate remains inactive and unverified.')

    return [first_read, after_read, after_candidate_or_dispositions, finish]


@pytest.mark.parametrize('variant', VARIANTS)
async def test_optimizer_native_outcome_controls(ws, request, monkeypatch, variant):
    def denied(*args, **kwargs):
        pytest.fail('Network forbidden for native fake Optimizer controls')
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setattr(httpx.Client, 'send', denied)
    held = {}
    driver = Driver(optimizer=optimizer_script(variant, held))
    folder = Path(os.environ.get('REPORT_OPTIMIZER_OUTCOME_OUT', str(ws.store.root / 'captures'))) / variant
    capture = await capture_optimizer_outcome(ws, folder, driver)
    request.node.user_properties.append(('optimizer_outcome_capture', str(folder)))
    assessment, fixture = capture['assessment'], capture['fixture']
    assert assessment['feedback_originals_unchanged'] and assessment['business_originals_unchanged']
    assert assessment['active_assignment_after_worker'] is None
    assert assessment['all_candidates_inactive'] and not assessment['active_library']
    assert not assessment['unexpected_feedback_ids']
    assert all(row['valid'] for row in assessment['candidate_links'])
    assert assessment['job']['quality_verified'] is False
    assert all(d['quality_verified'] is False for d in assessment['dispositions'].values())
    assert held['ids'] == [fixture['feedback_a']['id'], fixture['feedback_b']['id']]
    for label, feedback in [('a', fixture['feedback_a']), ('b', fixture['feedback_b'])]:
        for field in ('correction', 'before', 'evidence'):
            raw = held['pages'][label + '-' + field]['text']
            assert (raw if field == 'correction' else json.loads(raw)) == feedback[field]
    expected_calls = 3 if variant == 'both-without-candidate' else 4
    assert len(driver.calls) == len(capture['native_model_calls']) == expected_calls
    assert all(c['boundary'] == 'native_optimizer_decision' for c in capture['native_model_calls'])
    names = {s['name'] for s in driver.bindings['optimizer'][-1]}
    assert {'read_learning_feedback', 'read_experience_candidates', 'propose_experience',
            'record_feedback_disposition', 'analyze_learning_material'} <= names
    assert not {'task', 'release', 'commit_objects'} & names
    if variant == 'missing-second-disposition':
        assert capture['raised_error'] == {'type': 'ActionRejected', 'message': 'LEARNING_FEEDBACK_UNACCOUNTED'}
        assert assessment['job']['state'] == 'failed'
        assert assessment['missing_feedback_ids'] == [fixture['feedback_b']['id']]
        assert all(row['status'] == 'failed' for row in assessment['queue'])
    else:
        assert capture['raised_error'] is None and capture['runtime_result']['state'] == 'completed'
        assert assessment['job']['state'] == 'completed' and not assessment['missing_feedback_ids']
        assert all(row['status'] == 'completed' for row in assessment['queue'])
    if variant == 'both-without-candidate':
        assert not assessment['candidates'] and not assessment['job']['candidates']
    else:
        assert len(assessment['candidates']) == 1
        candidate = assessment['candidates'][0]
        assert candidate['id'] == held['candidate']['id'] and candidate['version'] == 1
        assert candidate['customer'] == fixture['customer'] and candidate['project'] == ''
        assert candidate['kind'] == 'customer_preference' and candidate['conditions'] == CONDITIONS
        assert candidate['feedback_ids'] == [fixture['feedback_a']['id']]
        assert assessment['dispositions'][fixture['feedback_a']['id']]['candidate'] == {
            'id': candidate['id'], 'version': candidate['version']}
    if variant == 'fabricated-candidate-still-accounted':
        # Program accounting passes. A separate test observer flags the known
        # false assertion; it does not pretend the program performed fact review.
        assert assessment['semantic_status'] == 'needs_semantic_review'
        assert len(assessment['unsupported_control_assertions']) == 1
        assert assessment['unsupported_control_assertions'][0]['statement'] == UNSUPPORTED_CONTROL_ASSERTION
    else:
        assert assessment['semantic_status'] == 'not_semantically_assessed'
        assert not assessment['unsupported_control_assertions']


async def test_optimizer_prepared_reads_use_real_tools_and_configured_sdk_without_network(ws, request, monkeypatch):
    """Three provider-shaped fake consumer responses after six native reads."""
    from duty_probe_agent_decisions import dump
    from report_agent.deep_models import configured_model
    from test_bounded_deadline import close_model
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_OPTIMIZER_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    model = configured_model(ws.store, 'optimizer')
    held, wires = {}, []
    scripts = optimizer_script('candidate-and-insufficient', held)

    async def transport(request):
        wire = json.loads(request.content)
        wires.append(wire)
        # Decode the actual SDK request only to choose the mock provider answer.
        # These reconstructed objects never become application/model input.
        messages = [ToolMessage(content=m['content'], tool_call_id=m['tool_call_id'], name=m.get('name', ''))
                    for m in wire['messages'] if m['role'] == 'tool']
        response = scripts[len(wires)](messages)
        message = {'role': 'assistant', 'content': response.content}
        if response.tool_calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {
                'name': c['name'], 'arguments': json.dumps(c['args'])}} for c in response.tool_calls]
        return httpx.Response(200, json={'id': 'offline-optimizer', 'object': 'chat.completion', 'created': 1,
            'model': wire['model'], 'choices': [{'index': 0, 'finish_reason': 'tool_calls' if response.tool_calls else 'stop',
            'message': message}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(transport)
    model.http_async_client._mounts = {}
    folder = Path(os.environ.get('REPORT_OPTIMIZER_OUTCOME_OUT', str(ws.store.root / 'captures'))) / 'sdk-prepared-reads'
    try:
        capture = await capture_optimizer_outcome(ws, folder, lambda role: model, prepared_reads=True)
    finally:
        await close_model(model)
        folder.mkdir(parents=True, exist_ok=True)
        dump(folder / 'sdk-wire.json', wires)
    request.node.user_properties.append(('optimizer_prepared_sdk_capture', str(folder)))
    assessment = capture['assessment']
    assert capture['raised_error'] is None and capture['runtime_result']['state'] == 'completed'
    assert assessment['feedback_originals_unchanged'] and assessment['business_originals_unchanged']
    assert not assessment['missing_feedback_ids'] and not assessment['unexpected_feedback_ids']
    assert assessment['all_candidates_inactive'] and not assessment['active_library']
    assert len(assessment['candidates']) == 1 and all(v['valid'] for v in assessment['candidate_links'])
    assert assessment['job']['quality_verified'] is False
    assert all(v['quality_verified'] is False for v in assessment['dispositions'].values())
    assert len(wires) == len(capture['native_model_calls']) == 3
    phases = capture['preparation_phases']
    assert phases[0]['phase'] == 'explicit_fake_read_setup'
    assert len(phases[0]['action']['tool_calls']) == 6
    assert all(p['phase'] == 'unchanged_consumer_handler' for p in phases[1:])
    assert len(phases[1]['native_tool_returns']) == 6
    assert {m['tool_call_id'] for m in wires[0]['messages'] if m['role'] == 'tool'} == {
        label + '-' + field for label in ('a', 'b') for field in ('correction', 'before', 'evidence')}
    actual_tool_messages = {m['tool_call_id']: m['content'] for m in phases[1]['native_tool_returns']}
    assert {m['tool_call_id']: m['content'] for m in wires[0]['messages'] if m['role'] == 'tool'} == actual_tool_messages
    for wire in wires:
        names = {tool['function']['name'] for tool in wire['tools']}
        assert {'read_learning_feedback', 'analyze_learning_material', 'propose_experience',
                'record_feedback_disposition'} <= names
        assert not {'release', 'commit_objects', 'task'} & names
    assert assessment['semantic_status'] == 'not_semantically_assessed'
