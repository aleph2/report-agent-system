"""R1 actual-result consumer controls, including independent oracle calibration."""
from copy import deepcopy
import json
import os
from pathlib import Path
import traceback

import pytest
from langchain_core.messages import AIMessage

from duty_probe_agent_decisions import dump
from duty_probe_reviewer_consumer import capture_reviewer_consumer, FALSE_FINAL
from report_agent import decision_data
from report_agent.content_store import ContentStore
from test_agent_duty_trace_cases import result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


CASES = ('full', 'missing', 'false-all-pass', 'public-limit-loss')


def assert_items(actual, raw, stored, requirements, held):
    def equal(left, right, path):
        if left != right:
            held.setdefault('oracle_failures', []).append({'path': path, 'actual': left, 'expected': right})
        try:
            assert left == right, 'P08_RECORDED_RESULT_FIELD:' + path
        except AssertionError as exc:
            # Passive evidence only; preserve the exact assertion and re-raise.
            held['oracle_failure_traceback'] = {
                'type': type(exc).__name__, 'message': str(exc),
                'formatted': ''.join(traceback.format_exception(exc)),
                'frames': [{'file': frame.filename, 'line': frame.lineno,
                            'function': frame.name, 'expression': frame.line}
                           for frame in traceback.extract_tb(exc.__traceback__)]}
            raise
    equal(len(actual), len(raw), 'items.length')
    for n, (a, r, s, requirement) in enumerate(zip(actual, raw, stored, requirements, strict=True)):
        base = 'items.' + str(n)
        for field in ('target_ref', 'criterion_ref', 'scope_id'):
            equal(a[field], requirement[field], base + '.' + field)
        for field in ('scope_id', 'checked_requirement_indexes', 'execution_state', 'verdict',
                      'coverage', 'reason', 'findings', 'outside_assignment_notes'):
            expected = r.get(field, [] if field == 'outside_assignment_notes' else None)
            equal(a[field], expected, base + '.' + field)
            equal(s[field], expected, 'saved.' + base + '.' + field)
        expected_checks = [{**c, 'remaining': c.get('remaining', '')} for c in r['check_results']]
        equal(a['check_results'], expected_checks, base + '.check_results')
        equal(s['check_results'], expected_checks, 'saved.' + base + '.check_results')
        equal(len(a['observations']), len(r['observations']), base + '.observations.length')
        for i, (observation, original, saved) in enumerate(zip(a['observations'], r['observations'], s['observations'], strict=True)):
            for field in ('locator', 'observation', 'limitations'):
                path = base + '.observations.' + str(i) + '.' + field
                equal(observation[field], original.get(field, ''), path)
                equal(saved[field], original.get(field, ''), 'saved.' + path)
            assert observation['receipt_id'] == saved['receipt_id']
        equal(a, s, base + '.public_saved_identity')


def reviewer_script(ws, case, held):
    def unused(messages):
        raise AssertionError('Original checker setup must occupy step zero')
    def consume(messages):
        message = tool_reply(messages, 'recorded-checker')
        value = result_value(message)
        held['actual_next_reviewer_tool'] = message.model_dump()
        assert message.status == 'success' and value.get('review_ref'), value
        cs = ContentStore(ws.store)
        stored = cs.read(value['review_ref'])
        # Fixture is read only for the independent oracle, never copied into the
        # agent request or its selected output. The fake answer uses actual value.
        fixture = json.loads((held['folder'] / 'fixture.json').read_text('utf-8'))
        assert_items(value['items'], fixture['expected_assessments']['items'], stored['payload']['items'],
                     fixture['task_call']['args']['review_requirements'], held)
        held['consumed_review'] = deepcopy(value)
        if case == 'false-all-pass':
            return AIMessage(content=FALSE_FINAL)
        return AIMessage(content=json.dumps(value, ensure_ascii=False))
    return [unused, consume]


@pytest.mark.parametrize('case', CASES)
async def test_recorded_two_scope_result_reaches_native_reviewer_and_parent(ws, request, monkeypatch, case):
    folder = Path(os.environ.get('REPORT_REVIEWER_CONSUMER_OUT', str(ws.store.root / 'captures'))) / case
    held = {'folder': folder}
    driver = Driver(reviewer=reviewer_script(ws, case, held))
    original_public = decision_data.public_value
    def public(tool, value):
        shown, complete = original_public(tool, value)
        if case == 'public-limit-loss' and tool == 'perform_assigned_review' and isinstance(shown, dict) and shown.get('items'):
            held['public_before_fault'] = deepcopy(shown)
            shown = deepcopy(shown)
            shown['items'][1]['observations'][0]['limitations'] = ''
            held['public_after_fault'] = deepcopy(shown)
        return shown, complete
    monkeypatch.setattr(decision_data, 'public_value', public)
    try:
        capture = await capture_reviewer_consumer(ws, case, folder, driver)
    finally:
        folder.mkdir(parents=True, exist_ok=True)
        dump(folder / 'oracle-observations.json', held)
    request.node.user_properties.append(('reviewer_consumer_capture', str(folder)))
    assert len(capture['checker_calls']) == 1 and capture['checker_calls'][0]['origin'] == 'recorded_R1_fixture'
    assert len(capture['saved_reviews']) == 1 and capture['originals_unchanged']
    assert len(driver.calls) == 1 and driver.calls[0][0] == 'reviewer'
    assert len(capture['native_model_calls']) == 1
    assert all(o['ref']['type'] not in ('ExportArtifact',) for o in ContentStore(ws.store).list_objects())
    if case == 'public-limit-loss':
        assert held['oracle_failures'] == [{'path': 'items.1.observations.0.limitations', 'actual': '',
            'expected': capture['fixture']['expected_assessments']['items'][1]['observations'][0]['limitations']}]
        assert capture['runtime']['last_error'] is None and capture['raised_error'] is None
        failure=json.loads(capture['parent']['task_return']['content'])
        failure=failure.get('metadata',failure)
        assert failure['ok'] is False and failure['code']=='DELEGATED_EXECUTION_FAILED'
        assert failure['error']=={'type':'AssertionError','http_status':None,'message':'EXECUTION_FAILED'}
        actual_call=capture['parent']['task_return']['tool_call_id']
        from report_agent.hierarchical_tools import actor_for
        receipt=ContentStore(ws.store).receipt(actor_for('coordinator'),'delegate:'+actual_call)
        assert receipt['state']=='known_success' and receipt['response']['result']['task_ref']['id']==capture['saved_reviews'][0]['task_id']
        assert held['oracle_failure_traceback']['type'] == 'AssertionError'
        assert held['oracle_failure_traceback']['message'].startswith(
            'P08_RECORDED_RESULT_FIELD:items.1.observations.0.limitations')
        assert held['oracle_failure_traceback']['frames'][-1]['function'] == 'equal'
        assert 'assert left == right' in held['oracle_failure_traceback']['frames'][-1]['expression']
        stored = capture['saved_reviews'][0]['payload']['items'][1]['observations'][0]['limitations']
        assert stored == held['oracle_failures'][0]['expected']
        assert stored in json.dumps(held['public_before_fault'])
        return
    assert capture['raised_error'] is None and capture['runtime']['last_error'] is None
    assert not held.get('oracle_failures')
    status = capture['saved_task_status'][0]
    assert status['execution_complete'] is (case == 'full')
    assert bool(status['remaining']) is (case != 'full')
    assert status['semantic_coverage_verified'] is False
    parent = capture['parent']['supervision']['result']['tasks'][0]
    assert parent['requirements'] == status['requirements'] and parent['remaining'] == status['remaining']
    assert parent['execution_complete'] == status['execution_complete']
    if case == 'false-all-pass':
        assert capture['consumer_finals'] == [FALSE_FINAL]
        assert capture['semantic_status'] == 'needs_semantic_review'
        assert FALSE_FINAL in str(capture['parent']['task_return']['content'])
        assert parent['remaining'], 'False free text must not erase the real incomplete saved scope'
    else:
        returned = json.dumps(capture['parent']['task_return'], ensure_ascii=False)
        for item in held['consumed_review']['items']:
            for field in ('reason',):
                assert item[field] in returned
            for observation in item['observations']:
                assert observation['limitations'] in returned
        assert capture['semantic_status'] == 'not_semantically_assessed'
