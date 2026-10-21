"""Single-condition regressions at the final result-delivery boundary."""
import json

import pytest
from langchain_core.messages import ToolMessage

from report_agent.decision_data import deliver_controls
from report_agent.errors import ActionRejected
from report_agent.task_context import TaskContext
from test_decision_data import activate
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('mutation', ['tool', 'status'])
def test_final_result_cannot_change_tool_or_promote_transport_status(ws, mutation):
    seed(ws)
    activate(ws)
    message = TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        content=json.dumps({'ok': False, 'code': 'SYNTHETIC_REJECTED', 'retryable': False}),
        name='analyze_source_image', tool_call_id='original', status='error'))
    # One variable changes; owner, digest, call ID and saved data remain fixed.
    changed = message.model_copy(update={'name': 'analyze_evidence'} if mutation == 'tool'
                                 else {'status': 'success'})
    with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_OWNER_OR_CALL_MISMATCH'):
        deliver_controls(ws, 'coordinator', changed)
    assert deliver_controls(ws, 'coordinator', message).status == 'error'
