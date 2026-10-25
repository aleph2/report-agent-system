"""Legacy history stays cheap; production validates the explicit new release."""
import pytest

from report_agent import deep_runtime
from report_agent.errors import ActionRejected
from report_agent.task_context import TaskContext
from test_focused_context import activate
from test_task_supervision import ws, offline


@pytest.mark.parametrize('projection', ['focused-v1', 'unrecognized'])
def test_native_projection_rejects_explicit_legacy_state_before_model_factory(ws, projection):
    activate(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'context_projection': projection})
    ws.store.set('context_policy', 'stateful-tools-v1')
    def forbidden(role):
        pytest.fail('Invalid production projection must be rejected before constructing models')
    with pytest.raises(ActionRejected, match='CONTEXT_PROJECTION_REQUIRES_EXPLICIT_V2_PROFILE'):
        deep_runtime.build_agent(ws, forbidden, None)
    assert ws.store.get('context_projection_binding') is None


def test_existing_focused_binding_cannot_use_legacy_fast_path_to_downgrade(ws):
    activate(ws)
    middleware = TaskContext(ws, 'coordinator')
    assert middleware.focused and ws.store.get('context_projection_binding') == 'focused-v1'
    ws.store.set('context_policy', 'stateful-tools-v1')
    with pytest.raises(ActionRejected, match='CONTEXT_PROJECTION_REQUIRES_EXPLICIT_V2_PROFILE'):
        TaskContext(ws, 'coordinator')
    assert middleware.focused  # Existing instances do not silently change policy.
    assert ws.store.get('context_projection_binding') == 'focused-v1'
