"""Real failing Reviewer call: root validation must survive native error formatting."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import ToolNode

from report_agent.errors import ActionRejected
from report_agent.message_fields import validate_message
from report_agent.review_message import ReviewMessage
from report_agent.tool_argument_feedback import compact_native_tool_error
from test_native_task_error_boundary import native_node
from test_task_supervision import offline, ws


@pytest.fixture
def observed_call():
    return json.loads((Path(__file__).parent/'fixtures/reviewer_missing_coverage_state_20261030.json').read_text(encoding='utf8'))


def test_actual_wire_described_the_condition_and_actual_correction_is_valid(observed_call):
    schema = observed_call['actual_schema_excerpt']
    assert 'coverage_state' not in schema['required']
    assert 'Required with non-empty coverage_object_indexes' in schema['properties']['coverage_state']['description']
    original = observed_call['actual_arguments']
    assert original['coverage_object_indexes'] and original['coverage_reason']
    assert 'coverage_state' not in original
    corrected = ReviewMessage.model_validate(observed_call['corrected_actual_arguments'])
    assert corrected.coverage_state == 'assessed'
    assert corrected.assigned_scope_index == original['assigned_scope_index']


def test_internal_validator_already_identifies_the_missing_coverage_group(observed_call):
    with pytest.raises(ActionRejected) as failed:
        validate_message(ReviewMessage, observed_call['actual_arguments'])
    issue, = failed.value.diagnostic['fields']
    assert issue['reason'] == 'COVERAGE_FIELDS_REQUIRED'
    assert issue['related_fields'] == observed_call['expected_repair_diagnostic']['related_fields']


async def test_native_tool_feedback_names_the_missing_coverage_state(observed_call, ws):
    executed = []

    async def must_not_execute(**arguments):
        executed.append(arguments)
        raise AssertionError('Invalid arguments must not reach review storage')

    tool = StructuredTool.from_function(name='submit_review', description='Submit one actual review judgment.',
        coroutine=must_not_execute, args_schema=ReviewMessage)
    args = observed_call['actual_arguments']
    action = {'name':'submit_review', 'id':observed_call['call_id'], 'args':args, 'type':'tool_call'}
    result = await native_node(ToolNode([tool]), {'messages':[AIMessage(content='',tool_calls=[action])]})
    message, = result['messages']
    assert message.status == 'error' and not executed
    assert message.tool_call_id == observed_call['call_id']
    feedback = compact_native_tool_error(message, ws.store, args=args, schema=ReviewMessage)
    public = json.loads(feedback.content)
    repair_diagnostic = json.dumps(public.get('diagnostic'), ensure_ascii=False)
    assert 'COVERAGE_FIELDS_REQUIRED' in repair_diagnostic
    assert 'coverage_state' in repair_diagnostic
    assert 'coverage_object_indexes' in repair_diagnostic
    assert 'coverage_reason' in repair_diagnostic
    assert 'assessment' not in public.get('missing_required_keys', [])
    assert feedback.status == 'error' and not executed
