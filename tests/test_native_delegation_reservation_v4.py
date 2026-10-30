"""Registration reuse must never silently pay for the native child again."""
import pytest
from langchain_core.messages import ToolMessage

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.supervision_plugins import delegated_return
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call


async def test_native_reentry_with_same_intent_is_unresolved_not_another_invoke(case):
    cs, _, criteria, _ = prepared(case)
    call = review_call(criteria[:1])
    invoked = []
    async def actual(native):
        invoked.append(native)
        return ToolMessage('Original native result.', tool_call_id=call['id'])
    for index in range(2):
        with delegated_task(Workspace(cs.store), 'coordinator', call) as (native, actor):
            if index == 0:
                result = await delegated_return(cs, actor, native, actual)
                assert result.content == 'Original native result.'
            else:
                with pytest.raises(ActionRejected, match='NATIVE_DELEGATION_OUTCOME_UNRESOLVED'):
                    await delegated_return(cs, actor, native, actual)
    assert len(invoked) == 1


async def test_failed_native_attempt_retains_reservation_and_does_not_retry(case):
    cs, _, criteria, _ = prepared(case)
    call = review_call(criteria[:1])
    invoked = []
    async def interrupted(native):
        invoked.append(native)
        raise TimeoutError('Synthetic lost response.')
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (native, actor):
        with pytest.raises(TimeoutError):
            await delegated_return(cs, actor, native, interrupted)
        with pytest.raises(ActionRejected, match='NATIVE_DELEGATION_OUTCOME_UNRESOLVED'):
            await delegated_return(cs, actor, native, interrupted)
    assert len(invoked) == 1


async def test_audit_write_failure_after_native_return_preserves_original_result(case, monkeypatch):
    cs, _, criteria, _ = prepared(case)
    call = review_call(criteria[:1])
    original = ToolMessage('Preserved original.', tool_call_id=call['id'])
    async def actual(native):
        monkeypatch.setattr(cs.store, 'set', lambda *a, **k: (_ for _ in ()).throw(OSError('Synthetic audit failure')))
        return original
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (native, actor):
        assert await delegated_return(cs, actor, native, actual) is original
