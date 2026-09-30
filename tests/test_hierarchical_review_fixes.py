"""Counterexamples from the independent review; offline, isolated project storage."""
from copy import deepcopy
from io import BytesIO
import hashlib

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.content_export import export_snapshot
from report_agent.content_models import Ref
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.knowledge_state import project_state
from report_agent.store import Store
from report_agent.workspace import Workspace
from hierarchical_fixtures import delivery_evidence, unchecked_delivery
from test_deep_runtime import Driver, call, invoke, observation
from test_hierarchical_content import ws, seed, review_item, submission
from test_hierarchical_runtime import grade, select, no_network


async def passed_delivery(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    checks = delivery_evidence(cs, snapshot, export)
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", checks)])
    result = await deep_runtime.run_report(ws, driver)
    assert result["status"] == "reviewed_draft", result
    return cs, actor, refs, snapshot, all_refs, export, checks


async def test_late_defect_invalidates_status_and_native_rerun(ws):
    cs, actor, refs, snapshot, _, export, checks = await passed_delivery(ws)
    reviewer = actor_for("reviewer")
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    cs.submit_review(reviewer, "late-defect", submission(snapshot, refs,
        review_item(refs["claim"], refs["k"], receipt, "not_satisfied", "node")), {})
    assert project_state(ws)["status"] == "changes_required"
    tools = {t.__name__: t for t in content_tools(ws, "coordinator")}
    tools["select_content_delivery"]("retain", Ref.model_validate(snapshot), Ref.model_validate(export), "preserve_unresolved")
    driver = Driver(rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", checks)])
    original = driver.respond
    async def respond(role, messages):
        if role == "coordinator":
            driver.calls.append((role, 0, list(messages)))
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Retain known defect."))])
        return await original(role, messages)
    driver.respond = respond
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert any(role == "rubric_grader" for role, _, _ in driver.calls)
    assert result["status"] == "changes_required"


async def test_new_selection_cannot_inherit_old_pass(ws):
    cs, actor, refs, old, all_refs, _, _ = await passed_delivery(ws)
    new = cs.freeze(actor, "next", refs["root"], all_refs)["result"]["snapshot_ref"]
    export = export_snapshot(cs, actor, "next-export", new)["result"]["export_ref"]
    tools = {t.__name__: t for t in content_tools(ws, "coordinator")}
    tools["select_content_delivery"]("next-selection", Ref.model_validate(new), Ref.model_validate(export))
    state = project_state(ws)
    assert state["status"] == "needs_attention"
    assert state["content_current_review"]["overall_verdict"] is None
    assert not state["content_current_review"]["final_review_current"]
    assert state["content_final_review"]["target"]["snapshot_ref"] == old  # history preserved


async def test_corrected_final_record_cannot_supply_positive_coverage(ws):
    cs, _, refs, snapshot, _, _, checks = await passed_delivery(ws)
    reviewer = actor_for("rubric_grader")
    old = ws.store.get("content_final_review")["review_ref"]
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    replacement = {**submission(snapshot, refs, review_item(snapshot, refs["k"], receipt, "undetermined")),
                   "delivery_checks": checks}
    new = cs.submit_review(reviewer, "corrected", replacement, {})["result"]["review_ref"]
    cs.supersede_review(reviewer, "withdraw-old", old, new, "Prior positive judgment lacks sufficient support.")
    projected = project_state(ws)
    assert projected["status"] == "needs_attention"
    assert projected["content_current_review"]["overall_verdict"] is None
    assert projected["content_current_review"]["final_review_superseded"]


def test_correction_cannot_drop_known_page_defect_or_reuse_old_pages(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    reviewer = actor_for("rubric_grader")
    checks = delivery_evidence(cs, snapshot, export)
    checks[1]["verdict"] = "not_satisfied"
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    data = submission(snapshot, refs, review_item(refs["claim"], refs["k"], receipt, "satisfied", "node"))
    data["target_ref"] = refs["claim"]
    old = cs.submit_review(reviewer, "page-defect", {**data, "delivery_checks": checks}, {})["result"]["review_ref"]
    replacement = cs.submit_review(reviewer, "missing-pages", data, {})["result"]["review_ref"]
    with pytest.raises(ActionRejected, match="DELIVERY_COVERAGE"):
        cs.supersede_review(reviewer, "bad-correction", old, replacement, "Incomplete correction.")
    new = cs.freeze(actor, "next", refs["root"], all_refs)["result"]["snapshot_ref"]
    with pytest.raises(ActionRejected, match="CHANGED_ARTIFACT_REQUIRES_RECHECK"):
        cs.confirm_reuse(reviewer, "bad-reuse", old, new, "Old pages cannot establish new export quality.")


def test_content_correction_does_not_require_unperformed_page_checks(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    reviewer = actor_for("rubric_grader")
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    def record(operation, verdict):
        data = {**submission(snapshot, refs, review_item(snapshot, refs["k"], receipt, verdict)),
                "delivery_checks": unchecked_delivery()}
        return cs.submit_review(reviewer, operation, data, {})["result"]["review_ref"]
    old, new = record("initial", "not_satisfied"), record("corrected", "undetermined")
    assert cs.supersede_review(reviewer, "correction", old, new, "Content finding reconsidered on evidence.")["ok"]
    assert all(c["verdict"] is None and not c["observations"] for c in cs.read(new)["payload"]["delivery_checks"])


async def test_content_pass_with_unperformed_delivery_is_not_final_pass(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), AIMessage(content="Unperformed page review retained.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied")])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "needs_attention"
    assert result["content_final_review"]["overall_verdict"] is None


def test_page_judgment_cannot_use_content_receipt_or_wrong_export(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    reviewer = actor_for("rubric_grader")
    checks = delivery_evidence(cs, snapshot, export)
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    checks[1]["observations"][0]["receipt_id"] = receipt
    data = {**submission(snapshot, refs, review_item(snapshot, refs["k"], receipt, "satisfied")), "delivery_checks": checks}
    with pytest.raises(ActionRejected, match="MATCHING_ACTUAL_OBSERVATION"):
        cs.submit_review(reviewer, "fake-visual", data, {})
    # A completed export check does not replace the mandatory render check.
    from report_agent.content_models import delivery_aggregate
    result = delivery_aggregate({"overall_verdict": "satisfied", "coverage_complete": True}, checks[:1])
    assert result["overall_verdict"] is None
    assert result["missing_delivery_checks"] == ["render"]


def test_task_binding_is_required_and_restored_after_failure(ws):
    cs, _, refs, _, _ = seed(ws)
    tools = {t.__name__: t for t in content_tools(ws, "writer")}
    node = {"client_key": "n", "type": "ContentNode", "payload": cs.read(refs["claim"])["payload"]}
    with pytest.raises(ActionForbidden, match="task binding"):
        tools["commit_objects"]("unbound", [node])
    request = call("task", {"description": "Write assigned chapter", "subagent_type": "writer"}, "first-task")
    with pytest.raises(RuntimeError, match="fixture failure"):
        with delegated_task(ws, "coordinator", request) as (_, first):
            assert tools["content_status"]()["actor"]["task_id"] == first.task_id
            raise RuntimeError("fixture failure")
    with pytest.raises(ActionForbidden, match="task binding"):
        tools["commit_objects"]("leaked", [node])
    with delegated_task(ws, "coordinator", request) as (_, replay):
        assert replay == first  # native checkpoint retry keeps the owner
    bad = call("task", {"description": "Other role", "subagent_type": "reviewer", "resume_content_task_id": first.task_id}, "wrong-role")
    with pytest.raises(ActionForbidden, match="resumption scope"):
        with delegated_task(ws, "coordinator", bad):
            pass


async def test_native_delegation_separates_writers_and_resumes_original_owner(ws):
    cs, _, refs, _, _ = seed(ws)
    created = {}
    payload = cs.read(refs["claim"])["payload"]
    def save_a(messages):
        return invoke("commit_objects", operation_id="a-create", objects=[{"client_key": "a", "type": "ContentNode", "payload": payload}])
    def done_a(messages):
        created["a"] = observation(messages, "commit_objects")["result"]["refs"]["a"]
        return AIMessage(content="A committed.")
    def edit_a(operation):
        return invoke("commit_objects", operation_id=operation, objects=[{"client_key": "a", "type": "ContentNode",
            "previous_ref": created["a"], "payload": {**payload, "body": {"text": "Owned revision"}}}])
    def reject_b(messages):
        assert observation(messages, "commit_objects")["code"] == "FORBIDDEN"
        return AIMessage(content="B cannot overwrite A.")
    def resume(messages):
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer", "description": "Continue A",
            "resume_content_task_id": cs.read(created["a"])["task_id"]}, "resume-a")])
    def revised(messages):
        created["revision"] = observation(messages, "commit_objects")["result"]["refs"]["a"]
        return AIMessage(content="Original producer revised A.")
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer", "description": "Write A"}, "task-a")]),
        AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer", "description": "Write B"}, "task-b")]), resume, AIMessage(content="Finished ownership test.")])
    steps = [save_a, done_a, lambda m: edit_a("b-attempt"), reject_b, lambda m: edit_a("a-resumed"), revised]
    original, count = driver.respond, {"n": 0}
    async def respond(role, messages):
        if role != "writer":
            return await original(role, messages)
        action = steps[count["n"]]
        count["n"] += 1
        return ChatResult(generations=[ChatGeneration(message=action(messages))])
    driver.respond = respond
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert count["n"] == 6
    assert created["revision"]["version"] == 2
    assert cs.read(created["a"])["owner_id"] == cs.read(created["revision"])["owner_id"]
    assert len(cs.list_objects("DelegatedTask")) == 2


@pytest.mark.parametrize("kind", ["figure", "markdown"])
def test_all_image_paths_require_snapshot_source_membership(tmp_path, kind):
    from pypdf import PdfWriter
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    pdf.write(buffer)
    data = buffer.getvalue()
    root = tmp_path / kind
    (root / "sources").mkdir(parents=True)
    (root / "sources" / "image.pdf").write_bytes(data)
    store = Store(root)
    store.initialize({"goal": "Use versioned images.", "content_contract": "hierarchical-review-v1", "sources": [
        {"id": "s", "title": "Rule", "content": "75 to 100.", "coverage": "complete"},
        {"id": "fig", "title": "Image", "content": "Image.", "coverage": "complete", "copied_path": "sources/image.pdf", "sha256": hashlib.sha256(data).hexdigest()}]})
    cs, actor, refs, _, all_refs = seed(Workspace(store))
    body = {"source_id": "fig", "caption": "Figure", "page": 1} if kind == "figure" else {"text": "![Figure](source-page://fig/1)"}
    added = cs.commit(actor, "image", [{"client_key": "image", "type": "ContentNode", "payload": {
        "kind": "figure" if kind == "figure" else "block", "body": body, "qualifiers": {}, "claim_kind": "fact"}},
        {"client_key": "edge", "type": "Relation", "payload": {"subject_ref": refs["root"], "object_ref": {"client_key": "image"},
        "predicate": "contains", "position": 1, "provenance_kind": "adopted_during_generation"}}])["result"]["refs"]
    missing = cs.freeze(actor, "missing", refs["root"], all_refs + list(added.values()))["result"]["snapshot_ref"]
    with pytest.raises(ActionRejected, match="IMAGE_SOURCE_OUTSIDE_SNAPSHOT"):
        export_snapshot(cs, actor, "missing-export", missing)
    image_ref = cs.capture_sources(actor, "capture", ["fig"])["result"]["source_refs"]
    complete = cs.freeze(actor, "complete", refs["root"], all_refs + list(added.values()) + image_ref)["result"]["snapshot_ref"]
    assert export_snapshot(cs, actor, "complete-export", complete)["ok"]


def test_independent_source_can_be_captured_and_reviewed_without_author_mutation(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    catalog = Catalog(ws.store)
    sid = catalog.import_file("counterevidence.txt", b"Independent rule evidence.")["source"]["id"]
    original = cs.read(snapshot)
    requirement_count = len(cs.list_objects("Requirement"))
    request = call("task", {"description": "Independently investigate", "subagent_type": "reviewer"}, "review-extra")
    with delegated_task(ws, "coordinator", request) as (_, reviewer):
        tools = {t.__name__: t for t in content_tools(ws, "reviewer")}
        source = tools["capture_review_sources"]("capture-extra", [sid])["result"]["source_refs"][0]
        receipt = tools["read_context"](Ref.model_validate(source))["receipt_id"]
        data = submission(snapshot, refs, review_item(refs["claim"], refs["k"], receipt, "not_satisfied", "node"))
        data.update(target_ref=refs["claim"], dependency_refs=[refs["support"], source])
        review = cs.submit_review(reviewer, "independent-review", data, {})["result"]["review_ref"]
        assert source in cs.read(review)["payload"]["dependency_refs"]
        new = cs.freeze(actor, "next-snapshot", refs["root"], all_refs)["result"]["snapshot_ref"]
        assert cs.confirm_reuse(reviewer, "valid-reuse", review, new, "Checked unchanged adopted evidence.")["ok"]
        catalog.import_file("counterevidence.txt", b"Revised independent evidence.", sid)
        with pytest.raises(ActionRejected, match="CHANGED_REVIEW_SOURCE"):
            cs.confirm_reuse(reviewer, "stale-reuse", review, new, "Source replaced; recheck required.")
        assert cs.changed_review_sources(cs.read(review)["payload"]) == [source]
        bad = deepcopy(data)
        bad["target_ref"] = source
        with pytest.raises(ActionRejected, match="REVIEW_TARGET_OUTSIDE_SNAPSHOT"):
            cs.submit_review(reviewer, "bad-target", bad, {})
    assert cs.read(snapshot) == original
    assert len(cs.list_objects("Requirement")) == requirement_count


@pytest.mark.parametrize("verdict", ["satisfied", "not_satisfied"])
def test_existing_reuse_loses_positive_applicability_when_source_changes(ws, verdict):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    cat = Catalog(ws.store)
    sid = cat.import_file("independent.txt", b"Independent evidence.")["source"]["id"]
    reviewer = actor_for("reviewer")
    source = cs.capture_sources(reviewer, "capture", [sid])["result"]["source_refs"][0]
    receipt = cs.read_context(reviewer, source)["receipt_id"]
    data = submission(snapshot, refs, review_item(refs["claim"], refs["k"], receipt, verdict, "node"))
    data.update(target_ref=refs["claim"], dependency_refs=[source])
    review = cs.submit_review(reviewer, "review", data, {})["result"]["review_ref"]
    new = cs.freeze(actor, "new", refs["root"], all_refs)["result"]["snapshot_ref"]
    cs.confirm_reuse(reviewer, "reuse", review, new, "Unchanged evidence, explicit applicability checked.")
    required = [{"target_ref": refs["claim"], "criterion_ref": refs["k"], "scope": "node"}]
    assert cs.review_summary(new, required)["overall_verdict"] == verdict
    cat.import_file("independent.txt", b"Changed independent evidence.", sid)
    summary = cs.review_summary(new, required)
    assert summary["overall_verdict"] == ("not_satisfied" if verdict == "not_satisfied" else None)
    assert summary["needs_recheck"][0]["review_ref"] == review
    assert cs.read(review)["payload"]["items"][0]["verdict"] == verdict
