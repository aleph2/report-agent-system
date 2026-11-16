from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from report_agent.content_export import export_snapshot
from report_agent.content_models import ReviewSubmission, Ref
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.review_coverage import inventory, apply_coverage, validate_accounting
from report_agent.webapp import create_app
from test_hierarchical_content import ws, seed, review_item, submission
from test_hierarchical_runtime import no_network


def covered_seed(ws):
    cs, actor, refs, old, all_refs = seed(ws)
    snap = cs.freeze(actor, "covered", refs["root"], all_refs)["result"]["snapshot_ref"]
    return cs, actor, refs, snap, old


def review_data(cs, refs, snap):
    receipt = cs.read_context(actor_for("rubric_grader"), snap)["receipt_id"]
    data = submission(snap, refs, review_item(snap, refs["k"], receipt, "satisfied"))
    data["coverage_accounting"] = [{"target_refs": inventory(cs.read(snap)), "state": "assessed",
                                    "item_indexes": [0], "reason": "Grouped whole-document examination."}]
    return ReviewSubmission.model_validate(data).model_dump()


@pytest.mark.parametrize("state,complete", [("assessed", True), ("partial", False), ("not_assessed", False)])
def test_grouped_accounting_respects_gaps_and_preserves_n_and_u(ws, state, complete):
    cs, _, refs, snap, _ = covered_seed(ws)
    data = review_data(cs, refs, snap)
    data["coverage_accounting"][0]["state"] = state
    validate_accounting(cs.read(snap), data)
    for verdict in ["satisfied", "not_satisfied", "undetermined"]:
        data["items"][0]["verdict"] = verdict
        result = apply_coverage({"overall_verdict": verdict, "coverage_complete": True}, cs.read(snap), data)
        assert result["object_coverage"]["complete"] == complete


@pytest.mark.parametrize("fault,code", [("index", "INDEX_INVALID"), ("duplicate", "DUPLICATE"),
    ("outside", "OUTSIDE_SNAPSHOT"), ("cancel_requirement", "CANCEL_REQUIREMENT")])
def test_bad_accounting_is_rejected_on_persistent_submission(ws, fault, code):
    cs, _, refs, snap, _ = covered_seed(ws)
    data = review_data(cs, refs, snap)
    entry = data["coverage_accounting"][0]
    if fault == "index":
        entry["item_indexes"] = [5]
    elif fault == "duplicate":
        data["coverage_accounting"].append(deepcopy(entry))
    elif fault == "outside":
        entry["target_refs"] = [refs["k"]]
    else:
        entry["state"] = "not_applicable"
    with pytest.raises(ActionRejected, match=code):
        cs.submit_review(actor_for("rubric_grader"), "bad", data, {})


def test_deployed_content_routes_are_read_only_and_paginate(ws):
    cs, actor, _, snap, _ = covered_seed(ws)
    export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
    tool = next(t for t in content_tools(ws, "coordinator") if t.__name__ == "select_content_delivery")
    tool("select", Ref.model_validate(snap), Ref.model_validate(export))
    before = cs.list_objects()
    with TestClient(create_app(ws.store.root)) as client:
        response = client.get("/api/content/review-status?limit=2")
        assert response.status_code == 200 and response.json()["next_offset"] == 2
        assert client.get("/api/content/review-status?limit=101").status_code == 400
        assert client.get("/api/content/delivery").content.startswith(b"PK")
    assert cs.list_objects() == before
