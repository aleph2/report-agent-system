"""Offline checks for optional selection and evidence accounting, not model competence."""
import pytest
from pydantic import ValidationError
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.content_models import ReviewItem
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.supervision_plugins import delegated_return, plugin_catalog
from report_agent.task_supervision import reconcile, obligation_coverage
from test_task_supervision import ws, offline, review_call, save_review, global_reviewer_steps
from test_deep_runtime import Driver
from test_hierarchical_content import seed, review_item, submission


def evidence_call(snapshot, refs):
    c = review_call(snapshot, refs)
    c["args"]["supervision_plugin"] = "task-checks-evidence-v2"
    return c


def linked_item(cs, actor, refs, state="completed"):
    receipt = cs.read_context(actor, refs["claim"])["receipt_id"]
    item = review_item(refs["claim"], refs["k"], receipt, "undetermined" if state == "completed" else None)
    item.update(scope_id="rule-comparison", checked_requirement_indexes=[0] if state == "completed" else [])
    item["check_results"] = [{"requirement_index": 0, "execution_state": state,
        "result": "Compared the retrieved adopted class with the source interval; factual selection remains human-pending.",
        "observation_indexes": [0], "remaining": "" if state == "completed" else "Source interval comparison unfinished."}]
    if state != "completed":
        item.update(execution_state="running")
        item["coverage"]["unchecked"] = ["Source interval comparison unfinished."]
    return item


async def test_new_task_without_plugin_invokes_once_and_does_not_follow_up(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    c = review_call(snapshot, refs)
    c["args"].pop("supervision_plugin")
    calls = []
    async def invoke(native):
        calls.append(native)
        return ToolMessage("Checking remains incomplete", tool_call_id=native["id"])
    with delegated_task(ws, "coordinator", c) as (native, actor):
        result = await delegated_return(cs, actor, native, invoke)
        assert len(calls) == 1 and "Task supervision" not in result.content
        assert cs.store.get("content_task_followup:" + actor.task_id) is None
        assert cs.read({"type": "DelegatedTask", "id": actor.task_id, "version": 1})["payload"]["supervision_plugin"] is None
        assert reconcile(cs, actor.task_id)["remaining"]  # Evidence gaps still exist.


async def test_disabled_plugin_does_not_inject_automatic_supervision_notice(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    c = review_call(snapshot, refs); c["args"].pop("supervision_plugin")
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[c]), AIMessage(content="Unfinished work retained.")])
    count = global_reviewer_steps(driver, [AIMessage(content="Source check not completed.")])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None and count["n"] == 1
    assert "Task supervision (execution bookkeeping" not in str(driver.calls[-1][2])


def test_unknown_plugin_and_changed_resumption_are_rejected(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    c = evidence_call(snapshot, refs); c["args"]["supervision_plugin"] = "arbitrary-code"
    with pytest.raises(ActionRejected, match="UNKNOWN_SUPERVISION_PLUGIN"):
        with delegated_task(ws, "coordinator", c): pass
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)) as (_, actor):
        task_id = actor.task_id
    c = review_call(snapshot, refs, "resume"); c["args"]["resume_content_task_id"] = task_id
    with pytest.raises(ActionForbidden, match="changed supervision plugin"):
        with delegated_task(ws, "coordinator", c): pass
    c["args"].pop("supervision_plugin")
    c["id"] = "resume-preserving-selection"
    with delegated_task(ws, "coordinator", c) as (_, actor):
        assert reconcile(cs, actor.task_id)["supervision_plugin"] == "task-checks-evidence-v2"


def test_v2_checkmarks_without_per_check_result_do_not_close_assignment(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)) as (_, actor):
        save_review(cs, actor, snapshot, refs)
        status = reconcile(cs, actor.task_id)
        assert not status["execution_complete"]
        assert status["remaining"][0]["check_accounting_basis"] == "check_evidence_missing"


def test_linked_result_preserves_human_pending_and_separates_outside_task_notes(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)) as (_, actor):
        item = linked_item(cs, actor, refs)
        item["outside_assignment_notes"] = ["Rendered-page review belongs to a later delivery task."]
        cs.submit_review(actor, "linked", submission(snapshot, refs, item), {})
        status = reconcile(cs, actor.task_id)
        assert status["execution_complete"] and status["semantic_coverage_verified"] is False
        assert status["requirements"][0]["verdict"] == "undetermined"
        assert status["requirements"][0]["outside_assignment_notes"]


def test_partial_result_cannot_hide_behind_checked_index(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)) as (_, actor):
        item = linked_item(cs, actor, refs, "partial")
        item["checked_requirement_indexes"] = [0]
        with pytest.raises(ValidationError, match="CHECK_DECLARATION_CONFLICTS"):
            ReviewItem.model_validate(item)
        item["checked_requirement_indexes"] = []
        cs.submit_review(actor, "partial", submission(snapshot, refs, item), {})
        assert not reconcile(cs, actor.task_id)["execution_complete"]


def test_missing_and_out_of_range_check_results_do_not_close_assignment(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    c = evidence_call(snapshot, refs)
    c["args"]["review_requirements"][0]["required_checks"] += ["Check qualifications"]
    with delegated_task(ws, "coordinator", c) as (_, actor):
        item = linked_item(cs, actor, refs)
        cs.submit_review(actor, "one", submission(snapshot, refs, item), {})
        assert reconcile(cs, actor.task_id)["remaining"][0]["missing_checks"] == ["Check qualifications"]
        item["check_results"][0]["requirement_index"] = 7; item["checked_requirement_indexes"] = [7]
        cs.submit_review(actor, "wrong-index", submission(snapshot, refs, item), {})
        assert reconcile(cs, actor.task_id)["remaining"][0]["check_accounting_basis"] == "invalid_check_result_indexes"


def test_failed_or_foreign_observation_cannot_support_completed_check(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)) as (_, actor):
        item = linked_item(cs, actor, refs)
        failed = cs.observe(actor, {"status": "failed"})["receipt_id"]
        item["observations"].append({"locator": "failed lookup", "observation": "Read failed", "receipt_id": failed})
        item["check_results"][0]["observation_indexes"] = [1]
        with pytest.raises(ActionRejected, match="SUCCESSFUL_OBSERVATION"):
            cs.submit_review(actor, "failed", submission(snapshot, refs, item), {})
        foreign = cs.read_context(actor_for("coordinator"), refs["claim"])["receipt_id"]
        item["observations"][1]["receipt_id"] = foreign
        with pytest.raises(ActionRejected, match="NOT_FROM_THIS_REVIEWER"):
            cs.submit_review(actor, "foreign", submission(snapshot, refs, item), {})


async def test_v2_plugin_completes_only_one_followup_with_real_linked_result(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    count = 0
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)) as (native, actor):
        async def invoke(call):
            nonlocal count
            count += 1
            item = linked_item(cs, actor, refs, "partial" if count == 1 else "completed")
            cs.submit_review(actor, "check-" + str(count), submission(snapshot, refs, item), {})
            return ToolMessage("Actual result retained", tool_call_id=call["id"])
        await delegated_return(cs, actor, native, invoke)
        assert count == 2
        assert reconcile(cs, actor.task_id)["execution_complete"]
        assert cs.store.get("content_task_followup:" + actor.task_id)["state"] == "returned"


def test_plugin_catalog_and_obligation_inventory_are_optional_coordinator_tools(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    assert plugin_catalog()["default"] is None
    tools = {t.__name__ for t in content_tools(ws, "coordinator")}
    assert {"list_supervision_plugins", "read_review_obligation_coverage"} <= tools
    assert "list_supervision_plugins" not in {t.__name__ for t in content_tools(ws, "reviewer")}
    before = obligation_coverage(cs, snapshot)
    assert refs["k"] in before["criteria_without_assignment"]
    with delegated_task(ws, "coordinator", evidence_call(snapshot, refs)):
        after = obligation_coverage(cs, snapshot)
        assert refs["k"] not in after["criteria_without_assignment"]
        assert after["semantic_coverage_verified"] is False
