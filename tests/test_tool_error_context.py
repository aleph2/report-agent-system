"""Error context is compact; original argument/evidence state is not rewritten."""
import json
from langchain_core.messages import ToolMessage
from report_agent.store import Store
from report_agent.tool_argument_feedback import compact_native_tool_error


def test_native_schema_error_retains_diagnostic_and_does_not_repeat_review_body(tmp_path):
    store = Store(tmp_path)
    rejected_body = 'real scoped finding ' * 5000
    original = ToolMessage(content="Error invoking tool 'submit_artifact_review' with kwargs "
        + rejected_body + " with error:\\n review.items.0.check_results.0: COMPLETED_CHECK_REQUIRES_LINKED_OBSERVATIONS_AND_NO_REMAINING_WORK",
        tool_call_id='call', name='submit_artifact_review', status='error')
    result = compact_native_tool_error(original, store)
    value = json.loads(result.content)
    assert 'COMPLETED_CHECK_REQUIRES_LINKED_OBSERVATIONS_AND_NO_REMAINING_WORK' in value['diagnostic']
    assert rejected_body not in result.content and len(result.content) < 1000
    assert result.tool_call_id == original.tool_call_id and result.status == 'error'
    assert rejected_body in original.content
    assert store.events()[-1]['data']['native_error'] == original.content


def test_source_observations_and_action_rejections_are_not_compacted(tmp_path):
    store = Store(tmp_path)
    for status, content in [('success', 'real observation ' * 5000),
                            ('error', '{"code":"SOURCE_CONFLICT","message":"actual conflict"}')]:
        original = ToolMessage(content=content, tool_call_id='call', status=status)
        assert compact_native_tool_error(original, store) is original
    assert not store.events()
