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
