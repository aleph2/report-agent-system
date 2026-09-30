"""Deterministic version, feedback and export checks. No model-quality claims."""
from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document
from pydantic import ValidationError

from report_agent.content_models import ReviewItem, aggregate
from report_agent.content_store import Actor, ContentStore
from report_agent.content_export import export_snapshot, read_export, render_export
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.store import Store
from report_agent.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Report adopted class B and faithfully check its permitted value.",
        "content_contract": "hierarchical-review-v1",
        "sources": [{"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
    return Workspace(store)


def seed(ws):
    cs, actor = ContentStore(ws.store), actor_for("coordinator")
    inputs = cs.import_inputs(actor, "inputs", ["s"])["result"]
    objects = [
        {"client_key": "k", "type": "Criterion", "payload": {"requirement_refs": [inputs["requirement_ref"]],
            "purpose": "Faithful compilation", "scope": "whole report", "expected_outcome": "Adopted class and value agree.",
            "evidence_expectation": "Compare adopted conditions to original rule.", "allowed_limits": "Unresolved actual class may be conditional."}},
        {"client_key": "root", "type": "ContentNode", "payload": {"kind": "report", "body": {"text": "Report"}, "qualifiers": {}, "claim_kind": "structure"}},
        {"client_key": "claim", "type": "ContentNode", "payload": {"kind": "claim", "body": {"text": "For adopted class B use 70."}, "qualifiers": {"condition": "class B"}, "claim_kind": "inference"}},
        {"client_key": "edge", "type": "Relation", "payload": {"subject_ref": {"client_key": "root"}, "object_ref": {"client_key": "claim"},
            "predicate": "contains", "position": 0, "provenance_kind": "adopted_during_generation"}},
        {"client_key": "evidence", "type": "Evidence", "payload": {"source_refs": inputs["source_refs"], "locator": "s", "excerpt": "Class B permits 75 to 100."}},
        {"client_key": "support", "type": "Relation", "payload": {"subject_ref": {"client_key": "claim"}, "object_ref": {"client_key": "evidence"},
            "predicate": "supported_by", "provenance_kind": "adopted_during_generation"}},
    ]
    refs = cs.commit(actor, "seed", objects)["result"]["refs"]
    all_refs = [inputs["requirement_ref"], *inputs["source_refs"], *refs.values()]
    snapshot = cs.freeze(actor, "snapshot", refs["root"], all_refs)["result"]["snapshot_ref"]
    return cs, actor, refs, snapshot, all_refs


def review_item(target, criterion, receipt=None, verdict="not_satisfied", scope="delivery"):
    return {"target_ref": target, "criterion_ref": criterion, "scope": scope,
        "execution_state": "completed" if receipt else "blocked", "verdict": verdict,
        "observations": [{"locator": "s", "observation": "B allows 75 to 100; 70 lies outside.", "receipt_id": receipt}] if receipt else [],
        "coverage": {"checked": ["rule comparison"] if receipt else [], "unchecked": [], "blocked": [] if receipt else ["source reading"], "basis": "actual observation"},
        "reason": "Given the adopted conditions, the value conflicts with the permitted interval.", "findings": []}


def submission(snapshot, refs, item):
    return {"snapshot_ref": snapshot, "target_ref": snapshot, "scope": "delivery", "criteria_refs": [refs["k"]],
        "dependency_refs": [refs["support"]], "items": [item]}


def test_immutable_versions_cas_and_atomic_batch(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    old = cs.read(refs["claim"])
    update = {"client_key": "claim", "type": "ContentNode", "previous_ref": refs["claim"],
        "payload": {**old["payload"], "body": {"text": "Correction requires a justified in-band selection."}}}
    first = cs.commit(actor, "revision", [update])
    assert cs.commit(actor, "revision", [update]) == first
    assert cs.read(refs["claim"]) == old
    assert first["result"]["refs"]["claim"]["version"] == 2
    with pytest.raises(ActionRejected, match="VERSION_CONFLICT"):
        cs.commit(actor, "stale", [update])
    with pytest.raises(ActionRejected, match="OPERATION_CONFLICT"):
        cs.commit(actor, "revision", [])
    before = len(cs.list_objects())
    with pytest.raises(ActionRejected):
        cs.commit(actor, "rollback", [{"client_key": "new", "type": "ContentNode", "payload": old["payload"]}, update])
    assert len(cs.list_objects()) == before
    assert cs.receipt(actor, "revision")["state"] == "known_success"
    assert cs.receipt(actor, "unknown")["state"] == "unknown"
    assert cs.receipt(actor, "rollback")["state"] == "known_failure"


def test_ownership_and_closed_manifest(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    with pytest.raises(ActionForbidden):
        cs.commit(actor_for("reviewer"), "bad", [{"client_key": "x", "type": "ContentNode", "payload": cs.read(refs["claim"])["payload"]}])
    with pytest.raises(ActionForbidden):
        cs.commit(actor_for("writer"), "other-owner", [{"client_key": "x", "type": "ContentNode", "previous_ref": refs["claim"], "payload": cs.read(refs["claim"])["payload"]}])
    with pytest.raises(ActionRejected, match="INCOMPLETE_REFERENCE_CLOSURE"):
        cs.freeze(actor, "bad-snapshot", refs["root"], [r for r in all_refs if r != refs["evidence"]])
    edge = cs.commit(actor, "cycle-edge", [{"client_key": "cycle", "type": "Relation", "payload": {
        "subject_ref": refs["claim"], "object_ref": refs["root"], "predicate": "contains", "position": 0, "provenance_kind": "adopted_during_generation"}}])["result"]["refs"]["cycle"]
    with pytest.raises(ActionRejected, match="ROOT_HAS_PARENT|CONTAINS_CYCLE"):
        cs.freeze(actor, "cyclic", refs["root"], [*all_refs, edge])


@pytest.mark.parametrize("verdict", ["satisfied", "not_satisfied", "undetermined"])
def test_no_observations_cannot_become_semantic_judgment(ws, verdict):
    _, _, refs, snapshot, _ = seed(ws)
    with pytest.raises(ValidationError, match="ACTUAL_OBSERVATIONS"):
        ReviewItem.model_validate(review_item(snapshot, refs["k"], verdict=verdict))


def test_review_transfer_null_and_current_version(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    reviewer = actor_for("reviewer")
    observed = cs.read_context(reviewer, refs["claim"])
    item = review_item(snapshot, refs["k"], observed["receipt_id"])
    saved = cs.submit_review(reviewer, "review", submission(snapshot, refs, item), {"model": "offline fixture"})
    handoff = cs.handoff(reviewer, "handoff", snapshot, "Confirm justified correction", [], "Criterion not satisfied")
    cs.handoff(actor, "handled", snapshot, "Received for correction", [], "Still not satisfied",
        handling_state="handled", previous_ref=handoff["result"]["handling_ref"])
    assert cs.read(saved["result"]["review_ref"])["payload"]["items"][0]["verdict"] == "not_satisfied"
    requirement = [{"target_ref": snapshot, "criterion_ref": refs["k"], "scope": "delivery"}]
    assert cs.review_summary(snapshot, requirement)["overall_verdict"] == "not_satisfied"
    new_snapshot = cs.freeze(actor, "second-snapshot", refs["root"], all_refs)["result"]["snapshot_ref"]
    assert cs.review_summary(new_snapshot, [{**requirement[0], "target_ref": new_snapshot}])["overall_verdict"] is None
    null = review_item(new_snapshot, refs["k"], verdict=None)
    cs.submit_review(reviewer, "blocked", submission(new_snapshot, refs, null), {})
    assert cs.feedback(actor)["result"]["total"] == 4
    forged = review_item(snapshot, refs["k"], "invented")
    with pytest.raises(ActionRejected, match="OBSERVATION_RECEIPT"):
        cs.submit_review(reviewer, "forged", submission(snapshot, refs, forged), {})


def test_parent_and_partial_coverage_are_not_passes(ws):
    _, _, refs, snapshot, _ = seed(ws)
    required = [{"target_ref": snapshot, "criterion_ref": refs["k"], "scope": "delivery"}]
    child_pass = review_item(refs["claim"], refs["k"], "test", "satisfied", "node")
    assert aggregate([child_pass], required)["overall_verdict"] is None
    defect = review_item(snapshot, refs["k"], "test")
    defect["execution_state"] = "blocked"
    defect["coverage"]["blocked"] = ["remaining pages"]
    assert ReviewItem.model_validate(defect)
    assert aggregate([defect], required) == {"overall_verdict": "not_satisfied", "coverage_complete": False, "missing_obligations": []}


def test_relation_only_change_impacts_parent(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    old = cs.read(refs["support"])
    changed = cs.commit(actor, "change-relation", [{"client_key": "r", "type": "Relation", "previous_ref": refs["support"],
        "payload": {**old["payload"], "predicate": "contradicted_by"}}])["result"]["refs"]["r"]
    new = cs.freeze(actor, "changed-snapshot", refs["root"], [r for r in all_refs if r != refs["support"]] + [changed])["result"]["snapshot_ref"]
    impact = cs.impact(snapshot, new)
    assert refs["root"] in impact["candidate_affected_refs"]
    assert refs["claim"] in impact["candidate_affected_refs"]


def test_export_is_snapshot_bound_and_preserves_conditions(ws, monkeypatch):
    cs, actor, refs, snapshot, _ = seed(ws)
    output = export_snapshot(cs, actor, "export", snapshot)["result"]
    doc = Document(BytesIO((ws.store.root / output["file_ref"]).read_bytes()))
    assert "For adopted class B use 70." in "\n".join(p.text for p in doc.paragraphs)
    assert "condition：class B" in "\n".join(p.text for p in doc.paragraphs)
    read = read_export(cs, actor_for("reviewer"), output["export_ref"])
    assert read["result"]["file_digest"] == output["file_digest"]
    assert cs.read(output["mapping_ref"])["payload"]["snapshot_ref"] == snapshot
    assert "located_at" not in str(cs.read(snapshot))
    # On Linux test missing renderer honestly, without pretending to inspect pages.
    import report_agent.content_export as ce
    monkeypatch.setattr(ce.shutil, "which", lambda _: None)
    monkeypatch.setattr(ce.Path, "exists", lambda _: False)
    result = render_export(cs, actor_for("reviewer"), "render-unavailable", output["export_ref"])
    assert result["result"]["verdict"] is None
    assert result["result"]["execution_state"] == "blocked"


def test_tool_schemas_and_write_permissions(ws):
    from langchain_core.utils.function_calling import convert_to_openai_tool
    for role in ("coordinator", "writer", "reviewer", "rubric_grader"):
        tools = content_tools(ws, role)
        names = {t.__name__ for t in tools}
        for tool in tools:
            assert convert_to_openai_tool(tool)
        if role in {"reviewer", "rubric_grader"}:
            assert not {"commit_objects", "freeze_snapshot", "export_content_snapshot", "select_content_delivery"} & names
        else:
            assert "submit_review" not in names


def test_detached_presentation_is_rejected_and_shared_claim_is_mapped(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    detached = cs.commit(actor, "orphan", [{"client_key": "block", "type": "ContentNode", "payload": {
        "kind": "block", "body": {"text": "Required content must not vanish."}, "qualifiers": {}, "claim_kind": "fact"}}])["result"]["refs"]["block"]
    with pytest.raises(ActionRejected, match="DETACHED_PRESENTATION_NODE"):
        cs.freeze(actor, "orphan-snapshot", refs["root"], [*all_refs, detached])


def test_same_snapshot_defect_requires_explicit_evidenced_review_correction(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    reviewer = actor_for("reviewer")
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    failed = cs.submit_review(reviewer, "failed-review", submission(snapshot, refs, review_item(snapshot, refs["k"], receipt)), {})["result"]["review_ref"]
    passed = cs.submit_review(reviewer, "passed-review", submission(snapshot, refs, review_item(snapshot, refs["k"], receipt, "satisfied")), {})["result"]["review_ref"]
    required = [{"target_ref": snapshot, "criterion_ref": refs["k"], "scope": "delivery"}]
    assert cs.review_summary(snapshot, required)["overall_verdict"] == "not_satisfied"
    cs.supersede_review(reviewer, "correction", failed, passed, "Fixture tests explicit correction, not truth of this evidence.")
    assert cs.review_summary(snapshot, required)["overall_verdict"] == "satisfied"
    with pytest.raises(ActionForbidden):
        cs.supersede_review(actor, "illegal-correction", passed, failed, "Coordinator cannot erase reviewer verdict.")


def test_different_exports_do_not_share_final_acceptance(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    reviewer = actor_for("reviewer")
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    first = export_snapshot(cs, actor, "export-one", snapshot)["result"]["export_ref"]
    second = export_snapshot(cs, actor, "export-two", snapshot)["result"]["export_ref"]
    review = submission(snapshot, refs, review_item(snapshot, refs["k"], receipt))
    review["dependency_refs"].append(first)
    review["items"][0].update(assessment_kind="export", artifact_refs=[first])
    cs.submit_review(reviewer, "export-review", review, {})
    required = [{"target_ref": snapshot, "criterion_ref": refs["k"], "scope": "delivery"}]
    assert cs.review_summary(snapshot, required, first)["overall_verdict"] == "not_satisfied"
    assert cs.review_summary(snapshot, required, second)["overall_verdict"] is None
    with cs.store.connect() as db:
        render_ref = cs._insert(db, reviewer, "RenderArtifact", {"snapshot_ref": snapshot, "export_ref": first})
    render_review = submission(snapshot, refs, review_item(snapshot, refs["k"], receipt))
    render_review["items"][0].update(assessment_kind="render", artifact_refs=[render_ref])
    cs.submit_review(reviewer, "page-review", render_review, {})
    assert cs.review_summary(snapshot, required, second)["overall_verdict"] is None
    content_review = submission(snapshot, refs, review_item(snapshot, refs["k"], receipt))
    content_review["dependency_refs"].append(first)
    cs.submit_review(reviewer, "content-defect", content_review, {})
    assert cs.review_summary(snapshot, required, second)["overall_verdict"] == "not_satisfied"


def test_same_head_concurrency_has_one_winner(ws):
    from concurrent.futures import ThreadPoolExecutor
    cs, actor, refs, _, _ = seed(ws)
    update = {"client_key": "n", "type": "ContentNode", "previous_ref": refs["claim"], "payload": cs.read(refs["claim"])["payload"]}
    def commit(index):
        try:
            return cs.commit(actor, f"concurrent-{index}", [update])["ok"]
        except ActionRejected as exc:
            return str(exc)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(commit, [1, 2]))
    assert results.count(True) == 1
    assert results.count("VERSION_CONFLICT") == 1


def test_reuse_cannot_move_old_pages_to_new_snapshot(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    reviewer = actor_for("reviewer")
    old_export = export_snapshot(cs, actor, "old-export", snapshot)["result"]["export_ref"]
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    item = review_item(refs["claim"], refs["k"], receipt, "satisfied", "node")
    item.update(assessment_kind="export", artifact_refs=[old_export])
    review = submission(snapshot, refs, item)
    review["target_ref"] = refs["claim"]
    saved = cs.submit_review(reviewer, "old-local", review, {})["result"]["review_ref"]
    new_snapshot = cs.freeze(actor, "new-snapshot", refs["root"], all_refs)["result"]["snapshot_ref"]
    with pytest.raises(ActionRejected, match="CHANGED_ARTIFACT_REQUIRES_RECHECK"):
        cs.confirm_reuse(reviewer, "reuse-pages", saved, new_snapshot, "Text unchanged does not prove new pages.")


def test_native_current_response_cannot_accept_an_old_export(ws):
    from report_agent.hierarchical_review import HierarchicalResponse, HierarchicalRubric
    cs, actor, refs, snapshot, _ = seed(ws)
    reviewer = actor_for("rubric_grader")
    first = export_snapshot(cs, actor, "first", snapshot)["result"]["export_ref"]
    second = export_snapshot(cs, actor, "second", snapshot)["result"]["export_ref"]
    receipt = cs.read_context(reviewer, snapshot)["receipt_id"]
    item = review_item(snapshot, refs["k"], receipt, "satisfied")
    item.update(assessment_kind="export", artifact_refs=[first])
    response = HierarchicalResponse(explanation="Wrong-file fixture", review=submission(snapshot, refs, item))
    adapter = object.__new__(HierarchicalRubric)
    adapter.contents = cs
    adapter.target = {"snapshot_ref": snapshot, "export_ref": second}
    with pytest.raises(ValueError, match="REVIEW_ARTIFACT_TARGET_MISMATCH"):
        adapter._build_evaluation(response, "fixture-run", 0)
