"""Incremental evidence behavior; no simulated result claims model effectiveness."""
import pytest
from pydantic import ValidationError

from report_agent.content_delivery import current_delivery
from report_agent.content_models import ReviewItem, Ref
from report_agent.content_store import ContentStore
from report_agent.content_export import export_snapshot
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.review_status import read_status
from report_agent.knowledge_state import project_state
from report_agent.errors import ActionForbidden, ActionRejected
from test_hierarchical_content import ws, seed, review_item


def current(ws):
    ws.store.set("manifest", {**ws.store.manifest, "review_entrypoint": "delegated-reviewer-v1"})


def save(cs, snap, refs, items, op, export=None):
    return cs.submit_review(actor_for("reviewer"), op, {
        "snapshot_ref": snap, "target_ref": refs["claim"], "scope": "assigned work",
        "criteria_refs": [refs["k"]], "dependency_refs": [], "items": items,
    }, {}, export)["result"]["review_ref"]


def items(cs, snap, refs):
    receipt = cs.read_context(actor_for("reviewer"), snap)["receipt_id"]
    return [dict(review_item(refs[k], refs["k"], receipt), scope_id=k, dependency_refs=[])
            for k in ("claim", "root")]


def test_content_and_snapshot_do_not_require_prior_criteria(ws):
    cs, actor = ContentStore(ws.store), actor_for("coordinator")
    root = cs.commit(actor, "first-content", [{"client_key": "root", "type": "ContentNode", "payload": {
        "kind": "report", "body": {"text": "Draft"}, "qualifiers": {}, "claim_kind": "structure"}}])["result"]["refs"]["root"]
    snap = cs.freeze(actor, "freeze-first", root, [root])["result"]["snapshot_ref"]
    assert cs.read(snap)["payload"]["criteria_refs"] == []


def test_multiple_node_records_are_visible_without_final_or_render_requirements(ws):
    current(ws)
    cs, actor, refs, snap, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
    a, b = items(cs, snap, refs)
    a["verdict"] = b["verdict"] = "satisfied"
    first = save(cs, snap, refs, [a], "a", export)
    second = save(cs, snap, refs, [b], "b")
    ws.store.set("content_delivery", {"snapshot_ref": snap, "export_ref": export})
    evidence = current_delivery(ws.store)
    assert {i["review_ref"]["id"] for i in evidence["items"]} == {first["id"], second["id"]}
    assert evidence["delivery_checks"] == [] and evidence["overall_verdict"] is None
    assert evidence["coverage_complete"] is None and ws.store.get("content_final_review") is None
    tools = {t.__name__: t for t in content_tools(ws, "coordinator")}
    context = tools["read_delivery_review_context"](Ref.model_validate(snap), Ref.model_validate(export))
    assert "obligations" not in context and "delivery_check_kinds" not in context
    ws.store.set("report_status", "completed")
    state = project_state(ws)
    assert state["status"] == state["execution_status"] == "completed"
    assert state["content_current_review"]["overall_verdict"] is None


def test_partial_correction_keeps_other_defect_and_stable_scope_identity(ws):
    current(ws)
    cs, _, refs, snap, _ = seed(ws)
    a, b = items(cs, snap, refs)
    old = save(cs, snap, refs, [a, b], "old")
    corrected = {**a, "scope": "clearer wording", "verdict": "satisfied"}
    new = save(cs, snap, refs, [corrected], "new")
    cs.supersede_review(actor_for("reviewer"), "correct-one", old, new, "Correct one mistaken finding", [0])
    row = read_status(cs, snap, refs["claim"])["objects"][0]
    assert row["scopes"][0]["verdict"] == "satisfied"
    assert any("review_superseded" in h["recheck_reasons"] for h in row["review_history"])
    other = read_status(cs, snap, refs["root"])["objects"][0]
    assert other["scopes"][0]["verdict"] == "not_satisfied"
    with pytest.raises(ActionForbidden):
        cs.supersede_review(actor_for("writer"), "steal", old, new, "No", [0])
    with pytest.raises(ActionRejected, match="COVERAGE"):
        cs.supersede_review(actor_for("reviewer"), "wrong-item", old, new, "No", [1])


def test_selective_reuse_ignores_changed_sibling_but_not_selected_dependencies(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    a, b = items(cs, snap, refs)
    old = save(cs, snap, refs, [a, b], "old")
    revised = cs.commit(actor, "revise-root", [
        {"client_key": "root", "type": "ContentNode", "previous_ref": refs["root"],
         "payload": {**cs.read(refs["root"])["payload"], "body": {"text": "Revised root"}}},
        {"client_key": "edge", "type": "Relation", "previous_ref": refs["edge"],
         "payload": {**cs.read(refs["edge"])["payload"], "subject_ref": {"client_key": "root"}}}
    ])["result"]["refs"]
    new = cs.freeze(actor, "new-snap", revised["root"],
        [r for r in all_refs if r not in [refs["root"], refs["edge"]]] + list(revised.values()))["result"]["snapshot_ref"]
    cs.confirm_reuse(actor_for("reviewer"), "reuse-one", old, new, "Claim and its context still applicable", [0])
    assert read_status(cs, new, refs["claim"])["objects"][0]["scopes"]
    assert not read_status(cs, new, revised["root"])["objects"][0]["scopes"]
    with pytest.raises(ActionRejected, match="CHANGED_REVIEW_INPUT"):
        cs.confirm_reuse(actor_for("reviewer"), "reuse-changed", old, new, "Cannot reuse changed root", [1])


def test_new_mixed_assessments_rejected_and_old_mixed_defect_preserved(ws):
    cs, actor, refs, snap, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
    a = {**items(cs, snap, refs)[0], "assessment_kind": "combined", "artifact_refs": [export]}
    with pytest.raises(ValidationError):
        ReviewItem.model_validate(a)
    other = export_snapshot(cs, actor, "other-export", snap)["result"]["export_ref"]
    assert cs.item_applies(a, snap, other)
    assert not cs.item_applies({**a, "verdict": "satisfied"}, snap, other)


def test_inventory_query_reuses_history_instead_of_reading_per_object_item(ws, monkeypatch):
    cs, _, refs, snap, _ = seed(ws)
    for n in range(12):
        save(cs, snap, refs, items(cs, snap, refs), "batch-" + str(n))
    reads = []
    original = cs.list_objects
    def counted(kind=None):
        reads.append(kind)
        return original(kind)
    monkeypatch.setattr(cs, "list_objects", counted)
    result = read_status(cs, snap, limit=100)
    assert len(result["objects"]) >= 3
    assert len(reads) <= 3  # independent of objects times review-item count
