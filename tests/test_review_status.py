"""Version-scoped review inventory; synthetic verdicts test contracts, not quality."""
import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.content_export import export_snapshot
from report_agent.content_models import Ref
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.review_status import read_status
from test_deep_runtime import Driver, invoke, observation
from test_hierarchical_content import ws, seed, review_item, submission
from test_hierarchical_runtime import grade, select, no_network
from hierarchical_fixtures import delivery_evidence


def save(cs, snapshot, refs, target, operation="review", verdict="satisfied", scope="whole node", extra=None):
    reviewer = actor_for("reviewer")
    receipt = cs.read_context(reviewer, target)["receipt_id"]
    data = submission(snapshot, refs, review_item(target, refs["k"], receipt, verdict, scope))
    data.update(target_ref=target, **(extra or {}))
    return cs.submit_review(reviewer, operation, data, {})["result"]["review_ref"]


def status(cs, snapshot, target, **kw):
    return read_status(cs, snapshot, target, **kw)["objects"][0]


def test_unreviewed_inventory_paginates_without_writes(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    before = cs.list_objects()
    page = read_status(cs, snapshot, limit=2)
    rest = read_status(cs, snapshot, offset=page["next_offset"], limit=2)
    assert page["total"] == 4  # snapshot, requirement and two nodes
    assert len(page["returned_refs"]) == 2 and page["unreturned_count"] == 2
    assert rest["next_offset"] is None
    assert {r["type"] for r in page["returned_refs"] + rest["returned_refs"]} == {"DocumentSnapshot", "Requirement", "ContentNode"}
    for row in page["objects"] + rest["objects"]:
        assert row["execution_state"] == "not_started"
        assert row["overall_verdict"] is None
        assert not row["has_review_history"] and not row["has_current_review"]
    assert cs.list_objects() == before
    assert read_status(cs, snapshot, offset=100)["objects"] == []
    with pytest.raises(ActionRejected, match="INVALID_PAGE"):
        read_status(cs, snapshot, limit=101)


def test_scoped_and_whole_node_judgments_preserved_without_parent_pass(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    save(cs, snapshot, refs, refs["claim"], scope="whole node")
    child = status(cs, snapshot, refs["claim"])
    assert child["execution_state"] == "completed"
    assert child["scopes"][0]["scope"] == "whole node"
    assert child["scopes"][0]["verdict"] == "satisfied"
    assert child["overall_verdict"] is None  # no blanket all-criteria conclusion invented
    for parent in [refs["root"], snapshot]:
        row = status(cs, snapshot, parent)
        assert not row["has_current_review"] and row["overall_verdict"] is None
    save(cs, snapshot, refs, refs["root"], operation="parent", scope="composition and completeness")
    assert status(cs, snapshot, refs["root"])["scopes"][0]["scope"] == "composition and completeness"


def test_known_defect_survives_later_pass_and_handling_until_explicit_correction(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    old = save(cs, snapshot, refs, refs["claim"], verdict="not_satisfied")
    new = save(cs, snapshot, refs, refs["claim"], operation="later-pass")
    first = cs.handoff(actor_for("reviewer"), "handoff", refs["claim"], "Resolve finding", [], "Unaccepted")
    cs.handoff(actor, "handled", refs["claim"], "Received", [], "Verdict unchanged",
               handling_state="handled", previous_ref=first["result"]["handling_ref"])
    row = status(cs, snapshot, refs["claim"])
    assert row["scopes"][0]["verdict"] == "not_satisfied"
    assert len(row["scopes"][0]["review_refs"]) == 2
    assert [r["is_latest_in_chain"] for r in row["handling_records"]] == [False, True]
    cs.supersede_review(actor_for("reviewer"), "correct", old, new, "Reviewer explicitly withdraws the prior mistaken finding.")
    row = status(cs, snapshot, refs["claim"])
    assert row["scopes"][0]["verdict"] == "satisfied"
    assert len(row["review_history"]) == 2 and not row["needs_recheck"]
    assert "review_superseded" in row["review_history"][0]["recheck_reasons"]


def test_old_snapshot_needs_explicit_reuse_and_unchanged_target_is_not_never_reviewed(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    review = save(cs, snapshot, refs, refs["claim"])
    new = cs.freeze(actor, "next", refs["root"], all_refs)["result"]["snapshot_ref"]
    row = status(cs, new, refs["claim"])
    assert row["has_review_history"] and not row["has_current_review"]
    assert row["execution_state"] == "not_started" and row["needs_recheck"]
    reuse = cs.confirm_reuse(actor_for("reviewer"), "reuse", review, new, "Relevance and unchanged dependencies checked.")
    row = status(cs, new, refs["claim"])
    assert row["scopes"][0]["verdict"] == "satisfied" and not row["needs_recheck"]
    assert row["scopes"][0]["judgment"]["reuse_refs"] == [reuse["result"]["reuse_ref"]]


def test_known_defect_does_not_hide_latest_blocked_execution(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    old = save(cs, snapshot, refs, refs["claim"], verdict="not_satisfied")
    data = submission(snapshot, refs, review_item(refs["claim"], refs["k"], verdict=None, scope="whole node"))
    cs.submit_review(actor_for("reviewer"), "blocked-recheck", data, {})
    row = status(cs, snapshot, refs["claim"])
    assert row["execution_state"] == "blocked"
    scope = row["scopes"][0]
    assert scope["verdict"] == "not_satisfied"
    assert scope["judgment"]["review_ref"] == old
    assert scope["judgment"]["execution_state"] == "completed"
    assert scope["latest_execution"]["execution_state"] == "blocked"
    assert scope["latest_execution"]["coverage"]["blocked"] == ["source reading"]


def test_changed_target_retains_old_judgment_only_as_history(ws):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    save(cs, snapshot, refs, refs["root"])
    revision = cs.commit(actor, "revise", [
        {"client_key": "root", "type": "ContentNode", "previous_ref": refs["root"],
         "payload": {**cs.read(refs["root"])["payload"], "body": {"text": "Revised report"}}},
        {"client_key": "edge", "type": "Relation", "previous_ref": refs["edge"],
         "payload": {**cs.read(refs["edge"])["payload"], "subject_ref": {"client_key": "root"}}},
    ])["result"]["refs"]
    new = cs.freeze(actor, "revised", revision["root"],
        [r for r in all_refs if r not in [refs["root"], refs["edge"]]] + list(revision.values()))["result"]["snapshot_ref"]
    row = status(cs, new, revision["root"])
    assert not row["scopes"] and row["needs_recheck"]
    assert "target_version_changed" in row["review_history"][0]["recheck_reasons"]
    assert row["review_history"][0]["verdict"] == "satisfied"
    with pytest.raises(ActionRejected, match="OUTSIDE_SNAPSHOT"):
        status(cs, new, refs["root"])


@pytest.mark.parametrize("verdict", ["satisfied", "not_satisfied", "undetermined"])
def test_independent_source_change_invalidates_positive_applicability_but_keeps_defect(ws, verdict):
    cs, actor, refs, snapshot, all_refs = seed(ws)
    cat = Catalog(ws.store)
    sid = cat.import_file("independent.txt", b"Independent evidence.")["source"]["id"]
    source = cs.capture_sources(actor_for("reviewer"), "capture", [sid])["result"]["source_refs"][0]
    review = save(cs, snapshot, refs, refs["claim"], verdict=verdict, extra={"dependency_refs": [source]})
    new = cs.freeze(actor, "next", refs["root"], all_refs)["result"]["snapshot_ref"]
    cs.confirm_reuse(actor_for("reviewer"), "reuse", review, new, "Unchanged sources examined.")
    cat.import_file("independent.txt", b"Changed independent evidence.", sid)
    row = status(cs, new, refs["claim"])
    assert row["needs_recheck"] and row["review_history"][0]["changed_source_refs"] == [source]
    assert bool(row["scopes"]) == (verdict == "not_satisfied")
    assert row["review_history"][0]["verdict"] == verdict


def test_artifact_reviews_are_bound_to_exact_export_and_render(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    old = export_snapshot(cs, actor, "old-export", snapshot)["result"]["export_ref"]
    new = export_snapshot(cs, actor, "new-export", snapshot)["result"]["export_ref"]
    checks = delivery_evidence(cs, snapshot, old, actor_for("reviewer"))
    save(cs, snapshot, refs, snapshot, extra={"delivery_checks": checks})
    tools = {t.__name__: t for t in content_tools(ws, "coordinator")}
    tools["select_content_delivery"]("select-new", Ref.model_validate(snapshot), Ref.model_validate(new))
    old_row = status(cs, snapshot, old)
    assert {s["assessment_kind"] for s in old_row["scopes"]} == {"export", "render"}
    assert not status(cs, snapshot, new)["has_review_history"]
    render = checks[1]["artifact_refs"][0]
    assert status(cs, snapshot, render)["scopes"][0]["assessment_kind"] == "render"
    current_snapshot = status(cs, snapshot, snapshot)
    assert len(current_snapshot["scopes"]) == 1  # content only, not old file checks
    assert current_snapshot["needs_recheck"]
    assert read_status(cs, snapshot, export_ref=old)["export_ref"] == old
    assert ws.store.get("content_delivery")["export_ref"] == new


def test_status_has_no_observation_receipt_and_enforces_delegated_binding(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    tools = {t.__name__: t for t in content_tools(ws, "coordinator")}
    with ws.store.connect() as db:
        before = db.execute("SELECT count(*) FROM content_observations").fetchone()[0]
    response = tools["read_review_status"](Ref.model_validate(snapshot))
    assert response["ok"] and "receipt_id" not in response
    with ws.store.connect() as db:
        assert db.execute("SELECT count(*) FROM content_observations").fetchone()[0] == before
    for role in ["reviewer", "writer"]:
        tool = next(t for t in content_tools(ws, role) if t.__name__ == "read_review_status")
        with pytest.raises(ActionForbidden, match="task binding"):
            tool(Ref.model_validate(snapshot))


async def test_native_grader_reads_inventory_then_submits_its_own_judgment(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    def inspect_inventory(messages):
        result = observation(messages, "read_review_status")["result"]
        assert any(r["execution_state"] == "not_started" for r in result["objects"])
        return invoke("read_context", target_ref=snapshot)
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected.")],
        rubric_grader=[invoke("read_review_status", snapshot_ref=snapshot), inspect_inventory,
                       grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft"
    current = status(cs, snapshot, snapshot)
    assert current["overall_verdict"] == "satisfied"
    assert current["delivery_review"]["final_review_current"]
    other_export = export_snapshot(cs, actor, "other-export", snapshot)["result"]["export_ref"]
    assert status(cs, snapshot, snapshot, export_ref=other_export)["overall_verdict"] is None
    assert ws.store.get("content_delivery")["export_ref"] == export
