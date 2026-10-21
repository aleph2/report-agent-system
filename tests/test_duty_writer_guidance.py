"""P14 tests: native Writer guidance applicability, three fake outputs."""
from copy import deepcopy
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from duty_probe_agent_decisions import dump
from duty_probe_writer_guidance import (
    APPLICABLE_TASK, ASSIGNMENT_BASE, CONDITIONS, FALSE_FINAL, INAPPLICABLE_TASK, NO_USE_FINAL,
    SOURCE, STRATEGY, TARGET, TITLE, TRUE_FINAL, USE_REASON, capture_writer_guidance,
)
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def writer_guidance_script(variant, held):
    def unused(messages):
        raise AssertionError('Fake setup must occupy the initial read/search step')
    def after_reads(messages):
        source_message, target_message = tool_reply(messages, 'p14-source'), tool_reply(messages, 'p14-target')
        source, target = result_value(source_message), result_value(target_message)
        assert source_message.status == target_message.status == 'success'
        assert source['ok'] is True and target['ok'] is True
        assert len(source['result']['objects']) == len(target['result']['objects']) == 1
        source_object, target_object = source['result']['objects'][0], target['result']['objects'][0]
        assert source_object['payload']['content'] == SOURCE
        assert target_object['payload'] == TARGET
        guidance_message = tool_reply(messages, 'p14-search')
        guidance = result_value(guidance_message)
        assert guidance_message.status == 'success' and len(guidance['items']) == 1
        item = guidance['items'][0]
        assert item['active'] is True and item['version'] == 1 and item['kind'] == 'general_skill'
        assert item['title'] == TITLE and item['strategy'] == STRATEGY and item['conditions'] == CONDITIONS
        held['actual_source'], held['actual_target'], held['actual_search'] = source_object, target_object, deepcopy(guidance)
        # Current task difference is explicit native assignment text. Full input
        # is retained for Neo; this fake branch is not an autonomous judgment.
        task_line = INAPPLICABLE_TASK if variant == 'inapplicable' else APPLICABLE_TASK
        assert any(task_line in str(m.content) for m in messages)
        if variant == 'inapplicable':
            return AIMessage(content=NO_USE_FINAL)
        held['use_arguments'] = {'experience_id': item['id'], 'version': item['version'],
                                 'target_ref': target_object['ref'], 'reason': USE_REASON}
        return action('record_experience_use', 'p14-use', **held['use_arguments'])
    def after_use(messages):
        message = tool_reply(messages, 'p14-use')
        value = result_value(message)
        assert message.status == 'success'
        assert value['experience'] == {k:v for k,v in held['actual_search']['items'][0].items() if k != 'active'}
        assert value['limitation'] == 'Declared use is not evidence of correct application or quality improvement.'
        held['actual_use_receipt'] = message.model_dump()
        # Same applicability, arguments and actual use receipt. Only final text
        # differs in the known method-as-fact counterexample.
        return AIMessage(content=FALSE_FINAL if variant == 'false-fact-claim' else TRUE_FINAL)
    return [unused, after_reads, after_use]


@pytest.mark.parametrize('variant', ['applicable', 'inapplicable', 'false-fact-claim'])
async def test_native_writer_guidance_applicability_and_method_not_fact(ws, tmp_path, variant):
    folder = Path(os.environ.get('REPORT_WRITER_GUIDANCE_OUT', tmp_path / 'evidence')) / variant
    held = {}
    driver = Driver(writer=writer_guidance_script(variant, held))
    capture = await capture_writer_guidance(ws, variant, folder, driver)
    dump(folder / 'independent-observations.json', held)
    assert capture['raised_error'] is None and capture['runtime']['last_error'] is None, capture['raised_error'] or capture['runtime']
    assert capture['originals_unchanged'] is True
    fixture = capture['fixture']
    assert fixture['original_task']['payload']['goal'] == ASSIGNMENT_BASE
    assert APPLICABLE_TASK not in fixture['original_task']['payload']['goal']
    assert INAPPLICABLE_TASK not in fixture['original_task']['payload']['goal']
    assert capture['guidance_versions'] == fixture['guidance_versions']
    assert capture['feedback'] == fixture['feedback_originals']
    assert capture['saved_objects'] == fixture['originals']
    assert held['actual_target']['owner_id'] == fixture['writer_actor']['id']
    assert held['actual_target']['ref'] == fixture['target_ref']
    assert len(capture['declared_uses']) == (0 if variant == 'inapplicable' else 1)
    assert len(driver.calls) == len(capture['native_model_calls']) == (1 if variant == 'inapplicable' else 2)
    assert all(role == 'writer' for role, _, _ in driver.calls)
    if variant != 'inapplicable':
        use = capture['declared_uses'][0]
        assert use == {'customer': fixture['customer'], 'project': fixture['project'],
            'id': fixture['guidance']['id'], 'version': 1, 'target': fixture['target_ref'],
            'reason': USE_REASON, 'actor': fixture['writer_actor']['id']}
    expected_final = {'applicable': TRUE_FINAL, 'inapplicable': NO_USE_FINAL, 'false-fact-claim': FALSE_FINAL}[variant]
    assert capture['finals'] == [expected_final]
    assert expected_final in str(capture['parent']['actual_task_return']['content'])
    semantic = 'needs_semantic_review' if capture['finals'] == [FALSE_FINAL] else 'not_semantically_assessed'
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'known_fixture_semantic_status': semantic,
        'fake_consumer_calls': len(driver.calls), 'paid_calls': 0,
        'normal_pair_difference': 'Current task only: risk scoring versus verbatim transcription. Source/guidance/target/customer stay logically identical in fresh workspaces.',
        'counterexample_difference': 'Same applicable task and actual use arguments/receipt, only final method-as-fact assertion changes.',
        'no_new_applicability_guard': True, 'no_autonomous_strategy_or_output_quality_claim': True,
        'later_model_routes_not_exercised': 'No independent text tool or extra child is selected by these three fake scripts.'})
