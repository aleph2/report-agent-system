"""Persistent mechanical replay safety, distinct from a semantic progress judge."""
import pytest

from repetition_fixtures import known_write_repetition_case
from test_deep_runtime import snapshot
from test_task_supervision import offline


@pytest.mark.parametrize("reference", [False, True])
async def test_managed_context_persistent_known_write_keeps_original_failure_contract(tmp_path, monkeypatch, reference):
    from report_agent.content_store import ContentStore
    actual_commits = []
    commit = ContentStore.commit
    def count_handler(self, actor, operation, *args, **kwargs):
        if operation == "same-structural-plan":
            actual_commits.append(operation)
        return commit(self, actor, operation, *args, **kwargs)
    monkeypatch.setattr(ContentStore, "commit", count_handler)
    ws, cs, driver, seen, result = await known_write_repetition_case(tmp_path, managed=True, reference=reference)
    assert result["status"] == "failed"
    assert result["last_error"]["message"] == "REPEATED_ACTION_WITHOUT_STATE_PROGRESS"
    assert seen["advisory_observed"]
    assert len(cs.list_objects("ContentNode")) == len(cs.list_objects("DelegatedTask")) == 1
    assert len([r for r in driver.calls if r[0] == "writer"]) == 5
    assert len(actual_commits) == 4  # The chosen post-notice replay never enters its handler.
    assert (await snapshot(ws, driver)).next


@pytest.mark.parametrize("managed", [False, True])
async def test_three_known_receipts_then_productive_work_has_no_call_quota(tmp_path, managed):
    _, cs, driver, seen, result = await known_write_repetition_case(tmp_path, managed=managed, progress=True, reference=managed)
    assert result["last_error"] is None, result
    assert seen["advisory_observed"]
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert len(cs.list_objects("ContentNode")) == 9
    assert len([r for r in driver.calls if r[0] == "writer"]) > 8


async def test_valid_replay_with_invalid_new_sibling_preserves_native_correction_feedback(tmp_path):
    ws, cs, _, seen, result = await known_write_repetition_case(tmp_path, managed=True, reference=True, mixed_invalid=True)
    assert result["last_error"] is None, result
    assert seen["advisory_observed"] and seen["invalid_feedback_observed"]
    assert len(cs.list_objects("ContentNode")) == len(cs.list_objects("DelegatedTask")) == 1
    assert not any(e["kind"] == "known_write_repetition_stopped" for e in ws.store.events())
