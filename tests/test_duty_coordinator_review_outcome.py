"""P09 completed-negative versus false acceptance: native input, fake finals."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from duty_probe_agent_decisions import dump
from duty_probe_coordinator_review_outcome import (
    FALSE_FINAL, TRUE_FINAL, capture_coordinator_review_outcome,
)
from report_agent.content_store import ContentStore
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import result_value
from test_deep_runtime import Driver
from test_duty_reviewer_consumer import assert_items
from test_task_supervision import ws, offline


def coordinator_outcome_script(ws, variant, held):
    def consume(messages):
        original = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'read_task_supervision')
        value = result_value(original)
        held['actual_supervision_tool'] = original.model_dump()
        if value.get('complete_tool_result') is False:
            assert value['exact_data_tool'] == 'read_tool_observation'
            ref = value['observation_ref']
            pages = [result_value(m) for m in messages if isinstance(m, ToolMessage) and m.name == 'read_tool_observation']
            offset = 0
            for page in pages:
                assert page['observation_ref'] == ref and page['offset'] == offset
                offset += len(page['text'])
            assert pages[-1]['next_offset'] is None
            held['actual_recovery_pages'] = deepcopy(pages)
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
        held['actual_received_supervision'] = deepcopy(value)
        return AIMessage(content=TRUE_FINAL if variant == 'honest-negative' else FALSE_FINAL)
    # Initial middleware actions occupy existing graph message positions. No
    # model call should occur during those explicit preparation actions.
    return [consume] * 15


@pytest.mark.parametrize('variant', ['honest-negative', 'false-acceptance'])
async def test_coordinator_receives_completed_negative_scopes_without_false_final_changing_records(ws, tmp_path, variant):
    folder = Path(os.environ.get('REPORT_COORDINATOR_OUTCOME_OUT', tmp_path / 'evidence')) / variant
    held = {}
    driver = Driver(coordinator=coordinator_outcome_script(ws, variant, held))
    capture = await capture_coordinator_review_outcome(ws, variant, folder, driver)
    dump(folder / 'independent-observations.json', held)
    assert capture['raised_error'] is None and capture['runtime']['last_error'] is None, capture['raised_error'] or capture['runtime']
    assert len(driver.calls) == len(capture['native_model_calls']) == 1
    assert driver.calls[0][0] == 'coordinator'
    assert capture['originals_unchanged'] is True
    assert len(capture['checker_calls']) == 1 and capture['checker_calls'][0]['origin'] == 'recorded_R1_fixture'
    assert len(capture['saved_reviews']) == len(capture['saved_tasks']) == 1
    prepared = capture['prepared']
    assert capture['saved_reviews'] == prepared['saved_reviews_before_consumer']
    assert capture['saved_tasks'] == prepared['saved_tasks_before_consumer']
    assert held['actual_received_supervision'] == prepared['supervision_received']
    saved = capture['saved_reviews'][0]['payload']['items']
    assert_items(prepared['reviewer_public_result']['items'], capture['fixture']['expected_assessments']['items'],
                 saved, capture['fixture']['task_call']['args']['review_requirements'], held)
    assert [i['verdict'] for i in saved] == ['not_satisfied', 'not_satisfied']
    assert capture['saved_task_status'][0]['remaining'] == []
    assert capture['saved_task_status'][0]['execution_complete'] is True
    expected_final = TRUE_FINAL if variant == 'honest-negative' else FALSE_FINAL
    assert capture['finals'] == [expected_final]
    assert not any(m['data'].get('tool_calls') for e in prepared['consumer_events'] for m in e.get('response', []))
    semantic = 'needs_semantic_review' if capture['finals'] == [FALSE_FINAL] else 'not_semantically_assessed'
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'known_fixture_semantic_status': semantic,
        'only_variant_action_difference': 'Coordinator final text; all prior fake actions and recorded checker output are identical apart from fresh isolated identities.',
        'fake_consumer_calls': len(driver.calls), 'paid_calls': 0,
        'actual_read_recovery_pages': len(held.get('actual_recovery_pages', [])),
        'consumer_business_actions_executed': [], 'initial_preparation_is_not_autonomous': True,
        'scope': 'Completed execution and negative verdict preserved; no semantic guard, report delivery or engineering acceptance.'})
