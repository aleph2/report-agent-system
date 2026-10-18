"""Node identity/range/ownership tests. Fake model output is not review quality evidence."""
import json

import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from report_agent.content_models import Ref
from report_agent.content_selection import ContentSelection, content_index, selected_content
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import business_tools
from report_agent.evidence_analysis import analyze_selected_evidence
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from test_evidence_analysis import Model
from test_hierarchical_content import ws, seed, review_item, submission
from test_review_status import save, status
from test_task_supervision import offline


def test_index_pagination_reports_tree_without_claim_body_or_receipt(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    before = cs.list_objects()
    first = content_index(cs, snap, limit=1)
    second = content_index(cs, snap, offset=first["next_offset"], limit=1)
    assert first["total_nodes"] == 2 and second["next_offset"] is None
    rows = first["nodes"] + second["nodes"]
    assert {r["ref"]["id"] for r in rows} == {refs["root"]["id"], refs["claim"]["id"]}
    assert all("body" not in r for r in rows)
    assert "receipt_id" not in first and cs.list_objects() == before
    claim = next(r for r in rows if r["ref"] == refs["claim"])
    assert {x["predicate"] for x in claim["relations"]} == {"contains", "supported_by"}


async def test_selected_node_versions_and_ranges_reach_model_without_other_nodes(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    model = Model()
    before = cs.list_objects()
    sel = [{"ref": refs["claim"], "offset": 4, "limit": 7}]
    result = await analyze_selected_evidence(ws, model, "Compare selected claim.", [], [], snap, sel)
    item = json.loads(model.calls[0][1][1])["evidence"][0]
    assert item["selection"]["ref"] == refs["claim"] and item["snapshot_ref"] == snap
    assert item["body"]["text"] == cs.read(refs["claim"])["payload"]["body"]["text"][4:11]
    assert not item["complete_body_selection"] and item["next_offset"] == 11
    assert item["qualifiers"] == {"condition": "class B"}
    assert len(result["evidence"]) == 1 and cs.list_objects() == before
    again = await analyze_selected_evidence(ws, model, "Compare selected claim.", [], [], snap, sel)
    assert again["reused"] and len(model.calls) == 1
    changed = cs.commit(actor, "revised", [{"client_key": "claim", "type": "ContentNode",
        "previous_ref": refs["claim"], "payload": {**cs.read(refs["claim"])["payload"], "body": {"text": "New text"}}}])["result"]["refs"]["claim"]
    with pytest.raises(ActionRejected, match="OUTSIDE_SNAPSHOT"):
        await analyze_selected_evidence(ws, model, "Compare.", [], [], snap, [{"ref": changed}])
    assert len(model.calls) == 1


def test_table_rows_are_complete_with_headers_and_original_qualifiers(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    table = cs.commit(actor, "table", [{"client_key": "t", "type": "ContentNode", "payload": {
        "kind": "table", "body": {"columns": ["id", "value"], "rows": [[1, 7], [2, 8], [3, 9]]},
        "qualifiers": {"status": "pending human verification"}, "claim_kind": "fact"}},
        {"client_key": "edge", "type": "Relation", "payload": {"subject_ref": refs["root"],
        "predicate": "contains", "object_ref": {"client_key": "t"}, "position": 1,
        "provenance_kind": "adopted_during_generation"}}])["result"]["refs"]
    new = cs.freeze(actor, "table-snapshot", refs["root"], all_refs+list(table.values()))["result"]["snapshot_ref"]
    result = selected_content(ws, new, [{"ref": table["t"], "unit": "rows", "offset": 1, "limit": 1}])[0]
    assert result["body"] == {"columns": ["id", "value"], "rows": [[2, 8]]}
    assert result["total_units"] == 3 and result["next_offset"] == 2
    assert result["qualifiers"]["status"] == "pending human verification"
    with pytest.raises(ActionRejected, match="ROWS_LIMIT"):
        selected_content(ws, new, [{"ref": table["t"], "unit": "rows", "limit": 101}])
    with pytest.raises(ActionRejected, match="TEXT_BODY"):
        selected_content(ws, new, [{"ref": table["t"]}])


async def test_invalid_selections_and_missing_binding_never_call_model(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    model = Model()
    for snapshot, selection, error in [(None, {"ref": refs["claim"]}, ActionRejected),
            (snap, {"ref": {**refs["claim"], "id": "foreign"}}, ActionRejected),
            (snap, {"ref": refs["k"]}, ActionRejected),
            (snap, {"ref": refs["claim"], "offset": True}, ValidationError),
            (snap, {"ref": refs["claim"], "offset": 999}, ActionRejected)]:
        with pytest.raises(error):
            await analyze_selected_evidence(ws, model, "Check.", [], [], snapshot, [selection])
    reviewer_tools = {t.__name__ for t in business_tools(ws, "reviewer", None, model)}
    assert "analyze_evidence" not in reviewer_tools and "perform_assigned_review" in reviewer_tools
    tools = {t.__name__: t for t in business_tools(ws, "writer", None, model)}
    tool = StructuredTool.from_function(coroutine=tools["analyze_evidence"])
    with pytest.raises(ActionForbidden):
        await tool.ainvoke({"question": "Check.", "source_selections": [], "result_selections": [],
            "snapshot_ref": snap, "content_selections": [{"ref": refs["claim"]}]})
    assert not model.calls


async def test_analysis_receipt_uses_current_actor_even_on_cache_hit(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    model = Model()
    reviewer_tools = {t.__name__ for t in business_tools(ws, "reviewer", None, model)}
    assert "analyze_evidence" not in reviewer_tools and "perform_assigned_review" in reviewer_tools
    tools = {t.__name__: t for t in business_tools(ws, "writer", None, model)}
    tool = StructuredTool.from_function(coroutine=tools["analyze_evidence"])
    receipts = []
    owners = []
    original_objects = cs.list_objects()
    for identifier in ("first", "second"):
        with delegated_task(ws, "coordinator", {"id": identifier, "name": "task",
                "args": {"subagent_type": "writer", "description": "Compare selected drafting evidence."}}) as (_, writer):
            result = await tool.ainvoke({"question": "Check.", "source_selections": [], "result_selections": [],
                "snapshot_ref": snap, "content_selections": [{"ref": refs["claim"]}]})
            receipts.append(result["receipt_id"])
            owners.append(writer.id)
            with ws.store.connect() as db:
                row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (receipts[-1],)).fetchone()
            assert row[0] == writer.id
            assert json.loads(row[1]) == {k: v for k, v in result.items() if k != "receipt_id"}
    assert len(model.calls) == 1 and len(set(receipts)) == len(set(owners)) == 2
    assert result["reused"]
    assert not cs.list_objects("ReviewRecord")
    assert all(cs.read(record["ref"]) == record for record in original_objects)


def test_local_review_reuse_survives_sibling_change_but_not_changed_dependency(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    review = save(cs, snap, refs, refs["claim"])
    revision = cs.commit(actor, "root-revision", [
        {"client_key": "root", "type": "ContentNode", "previous_ref": refs["root"],
         "payload": {**cs.read(refs["root"])["payload"], "body": {"text": "New heading"}}},
        {"client_key": "edge", "type": "Relation", "previous_ref": refs["edge"],
         "payload": {**cs.read(refs["edge"])["payload"], "subject_ref": {"client_key": "root"}}}])["result"]["refs"]
    new = cs.freeze(actor, "new-snapshot", revision["root"],
        [r for r in all_refs if r not in (refs["root"], refs["edge"])]+list(revision.values()))["result"]["snapshot_ref"]
    assert not status(cs, new, refs["claim"])["has_current_review"]
    reuse = cs.confirm_reuse(actor_for("reviewer"), "reuse-local", review, new, "Local scope remains valid; parent excluded from this judgment.")
    assert reuse["ok"] and status(cs, new, refs["claim"])["has_current_review"]
    assert not status(cs, new, revision["root"])["has_current_review"]
    whole = save(cs, snap, refs, snap, operation="whole")
    with pytest.raises(ActionRejected, match="CHANGED_REVIEW_INPUT"):
        cs.confirm_reuse(actor_for("reviewer"), "reject-whole", whole, new, "Cannot inherit whole snapshot.")
