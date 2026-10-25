"""Offline protocol checks; no claim about a model's engineering judgments."""
import json
import httpx
import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.task_supervision import reconcile, reserve_followup, task_status
from test_deep_runtime import Driver, call, invoke, observation
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_hierarchical_content import seed, review_item, submission


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Report adopted class B and check its permitted value.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "sources": [{"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
    return Workspace(store)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    def denied(*a, **k):
        pytest.fail("Network forbidden")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


def requirement(refs, reads=()):
    return {"target_ref": refs["claim"], "criterion_ref": refs["k"], "scope_id": "rule-comparison",
            "required_checks": ["rule comparison"], "required_read_refs": list(reads)}


def review_call(snapshot, refs, id="review-task", reads=()):
    return call("task", {"subagent_type": "reviewer", "description": "Compare adopted value with the original rule.",
        "review_snapshot_ref": snapshot, "review_requirements": [requirement(refs, reads)],
        "supervision_plugin": "task-checks-v1"}, id)


def save_review(cs, reviewer, snapshot, refs, *, checked=True, verdict="undetermined", operation="review"):
    receipt = cs.read_context(reviewer, refs["claim"])["receipt_id"]
    item = review_item(refs["claim"], refs["k"], receipt, verdict)
    item["scope_id"] = "rule-comparison"
    if not checked:
        item.update(execution_state="running", verdict=None)
        item["coverage"] = {"checked": [], "unchecked": ["rule comparison"], "blocked": [], "basis": "Not yet compared."}
    return cs.submit_review(reviewer, operation, submission(snapshot, refs, item), {})


def test_missing_partial_and_completed_human_pending_are_distinct(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["state"] == "missing"
        save_review(cs, reviewer, snapshot, refs, checked=False)
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["state"] == "incomplete"
        save_review(cs, reviewer, snapshot, refs, operation="completed", verdict="undetermined")
        status = reconcile(cs, reviewer.task_id)
        assert status["execution_complete"] and not status["remaining"]
        assert status["requirements"][0]["verdict"] == "undetermined"
        assert status["semantic_coverage_verified"] is False
        # A new partial disclosure remains visible even after a previous completed item.
        save_review(cs, reviewer, snapshot, refs, checked=False, operation="later-partial")
        assert reconcile(cs, reviewer.task_id)["remaining"]


def test_required_source_read_is_actual_returned_body_not_manifest_metadata(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        save_review(cs, reviewer, snapshot, refs, verdict="satisfied")
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["missing_read_refs"] == [source]
        receipt = cs.read_context(reviewer, source)["receipt_id"]
        item = review_item(refs["claim"], refs["k"], receipt, "satisfied")
        item["scope_id"] = "rule-comparison"
        cs.submit_review(reviewer, "actual-source", submission(snapshot, refs, item), {})
        assert reconcile(cs, reviewer.task_id)["execution_complete"]


def test_task_read_pool_and_different_check_wording_close_actual_scope(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        cs.read_context(reviewer, source)  # Actual task read, not copied into this item's citations.
        receipt = cs.read_context(reviewer, refs["claim"])["receipt_id"]
        item = review_item(refs["claim"], refs["k"], receipt)
        item.update(scope_id="rule-comparison")
        item["coverage"]["checked"] = ["Compared the adopted class and allowed interval."]
        cs.submit_review(reviewer, "different-wording", submission(snapshot, refs, item), {})
        assert reconcile(cs, reviewer.task_id)["execution_complete"]


def test_later_foreign_failed_partial_and_wrong_version_reads_do_not_retroactively_close(ws):
    from report_agent.hierarchical_tools import actor_for
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    cs.read_context(actor_for("coordinator"), source)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        wrong = cs.read(source)
        wrong["ref"] = {**source, "version": 2}
        cs.observe(reviewer, {"objects": [wrong]})
        cs.observe(reviewer, {"objects": [cs.read(source)], "status": "failed"})
        cs.observe(reviewer, {"selections": [{"selection": {"ref": source}, "complete_body_selection": False}]})
        save_review(cs, reviewer, snapshot, refs)
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["missing_read_refs"] == [source]
        cs.read_context(reviewer, source)
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["missing_read_refs"] == [source]
        save_review(cs, reviewer, snapshot, refs, operation="new-assessment")
        assert reconcile(cs, reviewer.task_id)["execution_complete"]


def test_multiple_required_actions_need_explicit_performed_indexes(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    call_data = review_call(snapshot, refs)
    call_data["args"]["review_requirements"][0]["required_checks"] = ["compare rule", "check qualifications"]
    with delegated_task(ws, "coordinator", call_data) as (_, reviewer):
        receipt = cs.read_context(reviewer, refs["claim"])["receipt_id"]
        item = review_item(refs["claim"], refs["k"], receipt)
        item.update(scope_id="rule-comparison", checked_requirement_indexes=[0])
        cs.submit_review(reviewer, "one-action", submission(snapshot, refs, item), {})
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["missing_checks"] == ["check qualifications"]
        item["checked_requirement_indexes"] = [0, 1]
        cs.submit_review(reviewer, "both-actions", submission(snapshot, refs, item), {})
        assert reconcile(cs, reviewer.task_id)["execution_complete"]


def test_reused_scope_id_with_different_checks_does_not_reuse_old_completion(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        save_review(cs, reviewer, snapshot, refs)
    changed = review_call(snapshot, refs, "new-task")
    changed["args"]["review_requirements"][0]["required_checks"] = ["A newly requested different comparison"]
    with delegated_task(ws, "coordinator", changed) as (_, reviewer):
        assert not reconcile(cs, reviewer.task_id)["execution_complete"]


@pytest.mark.parametrize("old_kind,new_kind,new_node,expected_reuse", [
    ("local_body", "local_body", "root", True),
    ("subtree_bodies", "subtree_bodies", "root", True),
    ("local_body", "subtree_bodies", "root", False),
    ("subtree_bodies", "local_body", "root", False),
    ("local_body", "local_body", "claim", False),
    ("local_body", None, "root", False),
    (None, "local_body", "root", False),
])
def test_saved_completion_reuse_requires_same_content_body_extent(
        ws, old_kind, new_kind, new_node, expected_reuse):
    cs, _, refs, snapshot, _ = seed(ws)

    def extent_task(task_id, kind, node):
        requested = review_call(snapshot, refs, task_id)
        req = requested["args"]["review_requirements"][0]
        req.update(target_ref=refs["root"], material_refs=[refs["claim"]])
        if kind is not None:
            req["content_check_scopes"] = [{"requirement_index": 0,
                "node_ref": refs[node], "kind": kind}]
        return requested

    with delegated_task(ws, "coordinator", extent_task("original", old_kind, "root")) as (_, first):
        root_receipt = cs.read_context(first, refs["root"])["receipt_id"]
        cs.read_context(first, refs["claim"])
        item = review_item(refs["root"], refs["k"], root_receipt, "undetermined")
        item["scope_id"] = "rule-comparison"
        cs.submit_review(first, "body-extent-review", submission(snapshot, refs, item), {})
        assert reconcile(cs, first.task_id)["execution_complete"]
    saved = cs.list_objects("ReviewRecord")

    with delegated_task(ws, "coordinator", extent_task("next", new_kind, new_node)) as (_, next_actor):
        outcome = reconcile(cs, next_actor.task_id)
        assert outcome["execution_complete"] is expected_reuse
        if not expected_reuse:
            assert outcome["remaining"][0]["state"] == "missing"
    assert cs.list_objects("ReviewRecord") == saved


@pytest.mark.parametrize("new_extent", [None, "local_body", "subtree_bodies"])
def test_legacy_contractless_review_cannot_close_new_explicit_body_extent(ws, new_extent):
    from report_agent.hierarchical_tools import actor_for
    cs, _, refs, snapshot, _ = seed(ws)
    old_actor = actor_for("reviewer")
    root_receipt = cs.read_context(old_actor, refs["root"])["receipt_id"]
    item = review_item(refs["root"], refs["k"], root_receipt, "undetermined")
    item["scope_id"] = "rule-comparison"
    cs.submit_review(old_actor, "legacy-root-check", submission(snapshot, refs, item), {})
    saved = cs.list_objects("ReviewRecord")
    assert not cs.list_objects("DelegatedTask")

    requested = review_call(snapshot, refs, "new-body-contract")
    req = requested["args"]["review_requirements"][0]
    req.update(target_ref=refs["root"], material_refs=[refs["claim"]])
    if new_extent is not None:
        req["content_check_scopes"] = [{"requirement_index": 0,
            "node_ref": refs["root"], "kind": new_extent}]
    with delegated_task(ws, "coordinator", requested) as (_, new_actor):
        outcome = reconcile(cs, new_actor.task_id)
        assert outcome["execution_complete"] is (new_extent is None)
        if new_extent is not None:
            assert outcome["remaining"][0]["state"] == "missing"
    assert cs.list_objects("ReviewRecord") == saved


def test_foreign_version_scope_and_superseded_items_do_not_close_task(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        receipt = cs.read_context(reviewer, refs["claim"])["receipt_id"]
        wrong = review_item(refs["claim"], refs["k"], receipt)
        wrong["scope_id"] = "different-scope"
        cs.submit_review(reviewer, "different", submission(snapshot, refs, wrong), {})
        assert reconcile(cs, reviewer.task_id)["remaining"][0]["state"] == "missing"
        assert reserve_followup(cs, reviewer, "call-a") is True
        assert reserve_followup(cs, reviewer, "call-a") is False
        assert reserve_followup(cs, reviewer, "call-b") is False
    assert task_status(cs)["total"] == 1


def test_resuming_task_cannot_narrow_its_requirements(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        task_id = reviewer.task_id
    changed = review_call(snapshot, refs, "narrowed")
    changed["args"]["resume_content_task_id"] = task_id
    changed["args"]["review_requirements"][0]["required_checks"] = ["just read"]
    with pytest.raises(ActionForbidden, match="changed review assignment"):
        with delegated_task(ws, "coordinator", changed):
            pass
    assert len(cs.list_objects("DelegatedTask")) == 1


def test_writer_owns_body_coordinator_can_freeze_without_acquiring_it(ws):
    cs, coordinator, refs, snapshot, _ = seed(ws)
    tools = {t.__name__: t for t in content_tools(ws, "coordinator")}
    assert "save_text_node" not in tools
    node = {"client_key": "root", "type": "ContentNode", "payload": cs.read(refs["root"])["payload"]}
    with pytest.raises(ActionForbidden, match="authorship"):
        tools["commit_objects"]("bad-body", [node])
    with delegated_task(ws, "coordinator", call("task", {"subagent_type": "writer", "description": "Write report"}, "writer-task")) as (_, writer):
        root = cs.commit(writer, "writer-body", [node])["result"]["refs"]["root"]
    new_snapshot = cs.freeze(coordinator, "assembly", root, [root])["result"]["snapshot_ref"]
    assert cs.read(root)["owner_id"] == writer.id
    assert cs.read(new_snapshot)["owner_id"] == coordinator.id


def global_reviewer_steps(driver, steps):
    original, count = driver.respond, {"n": 0}
    async def respond(role, messages):
        if role != "reviewer":
            return await original(role, messages)
        i = count["n"]
        count["n"] += 1
        driver.calls.append((role, i, list(messages)))
        action = steps[i]
        return ChatResult(generations=[ChatGeneration(message=action(messages) if callable(action) else action)])
    driver.respond = respond
    return count


@pytest.mark.parametrize("completed_on_followup", [True, False])
async def test_native_supervisor_follows_up_once_and_preserves_remaining(ws, completed_on_followup):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    assigned = review_call(snapshot, refs, reads=[source])
    assigned["args"]["review_requirements"][0]["required_materials"] = [{
        "requirement_index": 0, "purpose": "Compare actual claim and original rule", "refs": [refs["claim"], source]}]

    def checker(messages):
        # Independent bounded text tool receives the saved assignment and actual
        # material; the reviewer organizer no longer authors submit_review data.
        packet = json.loads(messages[-1].content)
        assert packet["assignment"]["review_requirements"][0]["scope_id"] == "rule-comparison"
        assert packet["evidence"][0]["object"]["ref"] == refs["claim"]
        assert packet["evidence"][1]["object"]["ref"] == source
        return AIMessage(content=json.dumps({"items": [{
            "scope_id": "rule-comparison", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "undetermined",
            "observations": [{"evidence_index": 0, "locator": "claim", "observation": "Adopted B uses 70."},
                             {"evidence_index": 1, "locator": "source", "observation": "B permits 75 to 100."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "70 is outside the stated interval; human selection remains.",
                "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["Compared original interval and adopted value."],
                "unchecked": [], "blocked": [], "basis": "Actual claim and original rule."},
            "reason": "Comparison performed; engineering selection remains human-owned.", "findings": []}]}))

    steps = [AIMessage(content="Some checking remains undone.")]
    steps += ([invoke("perform_assigned_review", operation_id="completion", scope_ids=["rule-comparison"],
                      source_selections=[], content_selections=[]), AIMessage(content="Comparison completed; human selection remains.")]
              if completed_on_followup else [AIMessage(content="Source still unavailable; no saved assessment.")])
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[assigned]),
        AIMessage(content="Keep actual result and remaining limitations.")],
        text_tool=[checker] if completed_on_followup else [])
    count = global_reviewer_steps(driver, steps)
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    status = task_status(cs)["tasks"][0]
    assert status["execution_complete"] is completed_on_followup
    assert status["followup"]["state"] == "returned"
    assert count["n"] == (3 if completed_on_followup else 2)
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == int(completed_on_followup)
    reviews = cs.list_objects("ReviewRecord")
    assert len(reviews) == int(completed_on_followup)
    if completed_on_followup:
        assert reviews[0]["payload"]["runtime_identity"]["mode"] == "bounded-review-v1"
        assert reviews[0]["payload"]["items"][0]["verdict"] == "undetermined"
    assert all("submit_review" not in {tool["name"] for tool in binding}
               and "perform_assigned_review" in {tool["name"] for tool in binding}
               for binding in driver.bindings["reviewer"])
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert "Task supervision" in str(driver.calls[-1][2])
    assert next(e for e in ws.store.events() if e["kind"] == "content_delegation_returned")["data"]["native_invocations"] == 2


@pytest.mark.parametrize("layout_first", [True, False])
async def test_same_model_batch_cannot_prequeue_layout_in_either_order(ws, layout_first):
    cs, _, refs, snapshot, _ = seed(ws)
    layout = call("task", {"subagent_type": "layout", "description": "Layout after review", "layout_snapshot_ref": snapshot}, "layout-call")
    review = review_call(snapshot, refs)
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[layout, review] if layout_first else [review, layout]),
        AIMessage(content="Assess return before a new layout request.")])
    global_reviewer_steps(driver, [AIMessage(content="Incomplete."), AIMessage(content="Still incomplete.")])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert not any(role == "layout" for role, _, _ in driver.calls)
    assert "REVIEW_RESULT_DECISION_REQUIRED" in str(driver.calls[-1][2])


async def test_pending_layout_is_blocked_and_ending_keeps_gaps(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[review_call(snapshot, refs)]),
        invoke("task", subagent_type="layout", description="Format", layout_snapshot_ref=snapshot),
        invoke("record_execution_decision", operation_id="end", decision="handoff", reason="Required source check remains unavailable.", evidence=[], unresolved=[]),
        AIMessage(content="Unfinished checking retained.")])
    global_reviewer_steps(driver, [AIMessage(content="Incomplete."), AIMessage(content="Still incomplete.")])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert not any(role == "layout" for role, _, _ in driver.calls)
    assert "REVIEW_WORK_INCOMPLETE" in str(driver.calls[-1][2])
    assert ws.store.get("content_execution_decision")["task_supervision_remaining"]


async def test_uncertain_followup_is_not_reexecuted_on_checkpoint_replay(ws):
    from report_agent.task_supervision import supervised_return
    cs, _, refs, snapshot, _ = seed(ws)
    count = {"n": 0}
    async def failed_followup(call):
        count["n"] += 1
        if count["n"] == 2:
            raise httpx.ReadTimeout("Offline unknown return")
        from langchain_core.messages import ToolMessage
        return ToolMessage("Incomplete", tool_call_id=call["id"])
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (native, reviewer):
        with pytest.raises(httpx.ReadTimeout):
            await supervised_return(cs, reviewer, native, failed_followup)
        replay = await supervised_return(cs, reviewer, native, failed_followup)
        assert "execution_replayed" in replay.content
        assert count["n"] == 2
        with pytest.raises(ActionRejected, match="EXHAUSTED"):
            await supervised_return(cs, reviewer, {**native, "id": "another-call"}, failed_followup)
        assert count["n"] == 2


def test_unrelated_snapshot_layout_and_snapshot_disclosure_are_not_misclassified(ws):
    from report_agent.task_supervision import batch_needs_review_decision
    cs, actor, refs, snapshot, all_refs = seed(ws)
    other = cs.freeze(actor, "independent-snapshot", refs["root"], all_refs)["result"]["snapshot_ref"]
    review = review_call(snapshot, refs)
    layout = call("task", {"subagent_type": "layout", "layout_snapshot_ref": other}, "independent-layout")
    assert not batch_needs_review_decision([AIMessage(content="", tool_calls=[review, layout])], layout)
    with delegated_task(ws, "coordinator", review) as (_, reviewer):
        disclosure = review_item(snapshot, refs["k"], verdict=None)
        disclosure["scope_id"] = "coverage-disclosure"
        cs.submit_review(reviewer, "null-disclosure", submission(snapshot, refs, disclosure), {})
        assert len(cs.list_objects("ReviewRecord")) == 1  # Allowed, but no node check closed.
        assert reconcile(cs, reviewer.task_id)["remaining"]


def test_real_completed_defect_does_not_become_pass_or_repeat_check(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        save_review(cs, reviewer, snapshot, refs, verdict="not_satisfied")
        status = reconcile(cs, reviewer.task_id)
        assert status["execution_complete"]
        assert status["requirements"][0]["verdict"] == "not_satisfied"
        assert ws.store.get("content_task_followup:" + reviewer.task_id) is None


async def test_native_followup_preserves_initial_scratch_file_state(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    def check_followup_read(messages):
        assert "initial-review-notes" in str(messages)
        return AIMessage(content="Scratch note retained; source comparison still incomplete.")
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[review_call(snapshot, refs)]),
        invoke("read_file", file_path="/review-notes.txt"), AIMessage(content="Working note preserved.")])
    global_reviewer_steps(driver, [invoke("write_file", file_path="/review-notes.txt", content="initial-review-notes"),
        AIMessage(content="Original comparison not completed."), invoke("read_file", file_path="/review-notes.txt"), check_followup_read])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert "initial-review-notes" in str(driver.calls[-1][2])
    assert task_status(cs)["tasks"][0]["remaining"]


async def test_completed_unchanged_evidence_reuses_without_another_invocation(ws):
    from report_agent.task_supervision import supervised_return
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, first):
        save_review(cs, first, snapshot, refs)
    async def forbidden_call(call):
        pytest.fail("Applicable completed scope must be reused")
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, "reuse-task")) as (native, reviewer):
        result = await supervised_return(cs, reviewer, native, forbidden_call)
        assert "reused_existing_evidence" in result.content
        assert "undetermined" in result.content
        assert ws.store.get("content_task_followup:" + reviewer.task_id) is None


def test_new_required_material_cannot_reuse_an_old_completed_scope(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, first):
        save_review(cs, first, snapshot, refs, verdict="satisfied")
    changed = review_call(snapshot, refs, "new-material-task")
    changed["args"]["review_requirements"][0]["required_materials"] = [{
        "requirement_index": 0, "purpose": "Original rule excerpt", "refs": [refs["evidence"]]}]
    with delegated_task(ws, "coordinator", changed) as (_, reviewer):
        assert reconcile(cs, reviewer.task_id)["remaining"]


def test_legacy_assignment_normalization_does_not_add_empty_material_fields(ws):
    from report_agent.content_tasks import normalize_review_requirements
    cs, _, refs, snapshot, _ = seed(ws)
    value = normalize_review_requirements([requirement(refs)])[0]
    assert "required_materials" not in value and "material_refs" not in value and "source_ranges" not in value
