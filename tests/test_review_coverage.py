from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from fastapi.testclient import TestClient

from report_agent import deep_runtime
from report_agent.content_export import export_snapshot
from report_agent.content_models import ReviewSubmission, Ref
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.review_coverage import inventory, apply_coverage, validate_accounting
from report_agent.webapp import create_app
from test_hierarchical_content import ws, seed, review_item, submission
from test_hierarchical_runtime import no_network, select
from test_deep_runtime import Driver, call, invoke, observation
from hierarchical_fixtures import delivery_evidence


def covered_seed(ws):
    cs, actor, refs, old, all_refs = seed(ws)
    ws.store.set("manifest", {**ws.store.manifest, "coverage_contract": "object-coverage-v1"})
    snap = cs.freeze(actor, "covered", refs["root"], all_refs)["result"]["snapshot_ref"]
    return cs, actor, refs, snap, old


def review_data(cs, refs, snap):
    receipt = cs.read_context(actor_for("rubric_grader"), snap)["receipt_id"]
    data = submission(snap, refs, review_item(snap, refs["k"], receipt, "satisfied"))
    data["coverage_accounting"] = [{"target_refs": inventory(cs.read(snap)), "state": "assessed",
                                    "item_indexes": [0], "reason": "Grouped whole-document examination."}]
    return ReviewSubmission.model_validate(data).model_dump()


def test_new_contract_is_frozen_and_old_records_keep_original_semantics(ws):
    cs, _, refs, snap, old = covered_seed(ws)
    summary = {"overall_verdict": "satisfied", "coverage_complete": True}
    missing = apply_coverage(summary, cs.read(snap), None)
    assert missing["overall_verdict"] is None and not missing["coverage_complete"]
    assert missing["object_coverage"]["expected_count"] == 3
    assert apply_coverage(summary, cs.read(old), None)["overall_verdict"] == "satisfied"
    ws.store.set("manifest", {**ws.store.manifest, "coverage_contract": None})
    assert apply_coverage(summary, cs.read(snap), None)["overall_verdict"] is None


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
        assert result["overall_verdict"] == (verdict if complete or verdict == "not_satisfied" else None)


@pytest.mark.parametrize("fault,code", [("index", "INDEX_INVALID"), ("duplicate", "DUPLICATE"),
    ("outside", "OUTSIDE_SNAPSHOT"), ("no_evidence", "OBSERVED_JUDGMENT"), ("cancel_requirement", "CANCEL_REQUIREMENT")])
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
    elif fault == "no_evidence":
        entry["item_indexes"] = []
    else:
        entry["state"] = "not_applicable"
    with pytest.raises(ActionRejected, match=code):
        cs.submit_review(actor_for("rubric_grader"), "bad", data, {})


@pytest.mark.parametrize("account", [True, False])
async def test_native_whole_report_pass_requires_new_object_accounting(ws, account):
    cs, actor, refs, snap, _ = covered_seed(ws)
    export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
    checks = delivery_evidence(cs, snap, export)
    def grade(messages):
        data = review_data(cs, refs, snap)
        data["items"][0]["observations"][0]["receipt_id"] = observation(messages, "read_context")["receipt_id"]
        data["delivery_checks"] = checks
        if not account:
            data["coverage_accounting"] = []
        return AIMessage(content="", tool_calls=[call("HierarchicalResponse", {"explanation": "Protocol fixture.", "review": data})])
    driver = Driver(coordinator=[select(snap, export), AIMessage(content="Selected."), AIMessage(content="Actual limitations retained.")],
                    rubric_grader=[invoke("read_context", target_ref=snap), grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == ("reviewed_draft" if account else "needs_attention")
    final = result["content_final_review"]
    assert final["object_coverage"]["complete"] == account
    assert final["overall_verdict"] == ("satisfied" if account else None)
    packet = next(e["data"]["packet"] for e in ws.store.events() if e["kind"] == "content_native_review_input")
    assert len(packet["object_coverage"]["expected_refs"]) == 3


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
