"""Retained business projection rules; frame serialization is retired under C1."""
import json
from copy import deepcopy
import pytest
from report_agent.decision_state import compact_context
from report_agent.task_context import exact_task_context
from report_agent.content_tasks import delegated_task
from test_task_supervision import ws, offline


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
def test_authority_projection_preserves_long_goal_scope_and_original_assignment(role):
    goal = '委托目标及条件。' * 300 + 'GOAL_TAIL'
    scope = '适用范围与排除条件。' * 250 + 'SCOPE_TAIL'
    assigned = '原始委派约束。' * 300 + 'ASSIGNMENT_TAIL'
    original = {'role': role, 'goal': goal, 'scope_instruction': {'origin': 'operator', 'text': scope},
                'assignment': {'goal': assigned, 'review_requirements': []},
                'current_invocation': {'description': 'Short correction, not replacement of original goal.'},
                'operator_feedback': [{'id': str(i), 'origin': 'operator',
                    'message': '保留条件。' * 1300 + f'FEEDBACK_{i}'} for i in range(22)]}
    before = deepcopy(original)
    actual = compact_context(original)
    assert actual['goal'] == goal
    assert actual['scope_instruction'] == original['scope_instruction']
    assert actual['assignment']['goal'] == assigned
    assert actual['current_invocation'] == original['current_invocation']
    assert actual['operator_feedback'] == original['operator_feedback']
    assert original == before


async def test_resumed_writer_keeps_original_goal_and_current_correction_separately(ws):
    ws.store.set('manifest', {**ws.store.manifest, 'review_interface_profile': 'review-interfaces-v4',
        'review_execution_mode': 'native-reviewer-v2', 'delegation_prompt_profile': 'separate-description-v1',
        'operation_identity_profile': 'native-tool-runtime-v1'})
    original = 'Original commissioned constraint. ' * 110 + 'ORIGINAL_TAIL'
    with delegated_task(ws, 'coordinator', {'id': 'writer-original', 'args': {
            'subagent_type': 'writer', 'description': original}}) as (_, actor):
        task_id = actor.task_id
    with delegated_task(ws, 'coordinator', {'id': 'writer-resume', 'args': {
            'subagent_type': 'writer', 'description': 'Correct only the selected item.',
            'resume_content_task_id': task_id}}):
        exact = exact_task_context(ws, 'writer')
        actual = compact_context(exact)
        assert actual['assignment']['goal'] == original
        assert actual['current_invocation'] == exact['current_invocation']
        assert 'Correct only the selected item.' in json.dumps(actual['current_invocation'])
