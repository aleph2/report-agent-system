"""Current whole-root protocol evidence; scripted checks do not prove model quality."""
from report_agent import report_state
import json
import hashlib
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, call, invoke, observation, snapshot
from test_task_supervision import offline


@pytest.mark.parametrize("case", ["complete", "missing_b", "body_not_supplied"])
async def test_independent_whole_requirement_checks_actual_root_and_all_bodies(tmp_path, case):
    # Scope is commissioned before production, independently of what Writer saves.
    goal = "Compile the whole access report: A daytime restriction AND B authorized escort."
    source_text = "Required A: Daytime access only. Required B: Authorized escort required."
    store = Store(tmp_path)
    store.initialize({"goal": goal, "scope_instruction": "Both A and B are required in the whole report.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "review_execution_mode": "bounded-tool-v1", "sources": [{"id": "s", "title": "Independent access scope",
            "content": source_text, "coverage": "complete"}]})
    ws, seen = Workspace(store), {}
    cs = ContentStore(store)
    bodies = [{"kind": "report", "body": {"text": "Access report"}, "claim_kind": "structure", "qualifiers": {}},
              {"kind": "block", "body": {"text": "Daytime access only [s]."}, "claim_kind": "fact", "qualifiers": {}}]
    if case != "missing_b":
        bodies.append({"kind": "block", "body": {"text": "Authorized escort required [s]."},
                       "claim_kind": "fact", "qualifiers": {}})

    def criterion(messages):
        seen["inputs"] = observation(messages, "import_source_versions")["result"]
        return invoke("commit_objects", operation_id="whole-criterion", objects=[{
            "client_key": "criterion", "type": "Criterion", "payload": {
                "requirement_refs": [seen["inputs"]["requirement_ref"]], "purpose": "Complete commissioned access report",
                "scope": "Whole report, including all contains-linked bodies",
                "expected_outcome": "Both A daytime access and B authorized escort agree with the independent original scope.",
                "evidence_expectation": "Compare independent original scope with every saved report body and its topology.",
                "allowed_limits": "Missing checker input is a limitation, never a confirmed report omission or approval."}}])

    def writer_task(messages):
        seen["criterion"] = observation(messages, "commit_objects")["result"]["refs"]["criterion"]
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer",
            "description": "Compile the entire A+B access report using " + encode(seen["criterion"])}, "whole-writer-task")])

    def produce(messages):
        return invoke("process_report_content", operation_id="whole-produce", object_type="ContentNode",
            objective="Compile the complete commissioned A+B access report with a report root and substantive blocks.",
            input_refs=[seen["criterion"]], source_selections=[{"source_id": "s"}], output_count=len(bodies))

    def adopt(messages):
        work = observation(messages, "process_report_content")
        objects = [{"client_key": f"node{i}", "type": "ContentNode", "text_work_id": work["text_work_id"],
                    "text_work_index": i} for i in range(len(bodies))]
        objects += [{"client_key": f"edge{i}", "type": "Relation", "payload": {
            "subject_ref": {"client_key": "node0"}, "object_ref": {"client_key": f"node{i}"},
            "predicate": "contains", "position": i - 1, "provenance_kind": "adopted_during_generation"}}
            for i in range(1, len(bodies))]
        return invoke("commit_objects", operation_id="whole-adopt", objects=objects)

    def freeze(messages):
        page = observation(messages, "read_object_index")
        assert page["next_offset"] is None
        seen["nodes"] = [r for r in cs.list_objects("ContentNode")]
        assert sorted(encode(r["payload"]) for r in seen["nodes"]) == sorted(map(encode, bodies))
        seen["root"] = next(r["ref"] for r in seen["nodes"] if r["payload"]["kind"] == "report")
        seen["children"] = [r["ref"] for r in seen["nodes"] if r["ref"] != seen["root"]]
        refs = [r["ref"] for r in cs.list_objects() if r["ref"]["type"] in {
            "Requirement", "SourceArtifact", "Criterion", "ContentNode", "Relation", "Evidence"}]
        assert {encode(r) for r in refs} <= {encode(r["ref"]) for r in page["objects"]}
        return invoke("freeze_snapshot", operation_id="whole-freeze", root_ref=seen["root"], refs=refs)

    def export(messages):
        frozen = observation(messages, "freeze_snapshot")
        assert frozen["ok"], frozen
        seen["snapshot"] = frozen["result"]["snapshot_ref"]
        return invoke("export_content_snapshot", operation_id="whole-export", snapshot_ref=seen["snapshot"])

    def review_task(messages):
        seen["export"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
        source = seen["inputs"]["source_refs"][0]
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "reviewer",
            "description": "Independently judge the WHOLE commissioned A+B report, not just its introduction.",
            "review_snapshot_ref": seen["snapshot"], "review_requirements": [{
                "target_ref": seen["root"], "criterion_ref": seen["criterion"], "scope_id": "whole-access-report",
                "required_checks": ["Entire commissioned A+B access report and internal contains-linked coverage agree with independent scope"],
                "required_read_refs": [source], "material_refs": seen["children"],
                "required_materials": [{"requirement_index": 0, "purpose": "Root and independent complete scope", "refs": [seen["root"], source]}],
                "content_check_scopes": [{"requirement_index": 0, "node_ref": seen["root"], "kind": "subtree_bodies"}]}]}, "whole-reviewer-task")])

    def read_word(messages):
        return invoke("read_content_export", export_ref=seen["export"])

    def check(messages):
        read = observation(messages, "read_content_export")
        assert read["ok"]
        for body in bodies:
            assert body["body"]["text"] in read["result"]["text"]
        assert ("Authorized escort required [s]." in read["result"]["text"]) == (case != "missing_b")
        from report_agent.content_export import _bytes
        exported = cs.read(seen["export"])["payload"]
        assert exported["snapshot_ref"] == seen["snapshot"]
        assert hashlib.sha256(_bytes(store, exported["file_ref"], exported["file_digest"])).hexdigest() == read["result"]["file_digest"]
        seen["word_receipt"] = read["receipt_id"]
        return invoke("perform_assigned_review", operation_id="whole-check", scope_ids=["whole-access-report"],
            source_selections=[], content_selections=[] if case == "body_not_supplied" else [{"ref": r} for r in seen["children"]])

    def text_model(messages):
        packet = json.loads(messages[-1].content)
        if "assignment" not in packet:
            assert goal in encode(packet)
            assert source_text in encode(packet)
            seen["producer_packet"] = packet
            return AIMessage(content=json.dumps(bodies))
        assert case != "body_not_supplied", "Missing required body must not enter the checker."
        seen["checker_packet"] = packet
        assert packet["commission"]["goal"] == goal
        requirement = packet["assignment"]["review_requirements"][0]
        assert requirement["target_ref"] == seen["root"]
        assert requirement["content_check_scopes"][0]["kind"] == "subtree_bodies"
        evidence = packet["evidence"]
        structure_index = next(i for i, e in enumerate(evidence) if e["kind"] == "snapshot_structure")
        structure = evidence[structure_index]["structure"]
        assert structure["inventory_complete"] and not structure["missing_body_extents"]
        assert set(map(encode, structure["body_extents"][0]["required_body_refs"])) == set(map(encode, [seen["root"], *seen["children"]]))
        assert source_text in encode(evidence)
        actual_bodies = {}
        for entry in evidence:
            if entry["kind"] == "saved_object" and entry["object"]["ref"]["type"] == "ContentNode":
                actual_bodies[encode(entry["object"]["ref"])] = entry["object"]["payload"]["body"]
            elif entry["kind"] == "content_node_selection":
                assert entry["complete_body_selection"] and entry["next_offset"] is None
                actual_bodies[encode(entry["selection"]["ref"])] = entry["body"]
        assert actual_bodies == {encode(n["ref"]): n["payload"]["body"] for n in seen["nodes"]}
        assert (any("Authorized escort required [s]." in encode(b) for b in actual_bodies.values())) == (case != "missing_b")
        observations = []
        for i, entry in enumerate(evidence):
            if entry["kind"] == "saved_object" or entry["kind"] == "content_node_selection":
                observations.append({"evidence_index": i, "locator": f"full input {i}", "observation": encode(entry)})
        observations.append({"evidence_index": structure_index, "locator": "complete frozen contains tree", "observation": encode(structure)})
        links = list(range(len(observations)))
        findings = [] if case == "complete" else [{"finding_type": "confirmed_defect", "locator_state": "absent",
            "description": "Independent required B authorized escort is absent from this complete saved report.",
            "impact": "The whole commissioned report is incomplete.", "needed_outcome": "Restore the required escort content.",
            "requirement_index": 0, "observation_indexes": links, "basis_kind": "snapshot_structure"}]
        return AIMessage(content=json.dumps({"items": [{"scope_id": "whole-access-report", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "satisfied" if case == "complete" else "not_satisfied",
            "observations": observations, "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "Whole A+B report agrees." if case == "complete" else "B is absent against independent scope.",
                "observation_indexes": links, "remaining": ""}],
            "coverage": {"checked": ["Entire A+B obligation, all root/subtree bodies, and exact independent scope"],
                "unchecked": [], "blocked": [], "basis": "Complete supplied bodies and independently commissioned A+B scope."},
            "reason": "Synthetic whole-report protocol judgment, not model-quality or engineering acceptance.", "findings": findings}]}))

    def finish_review(messages):
        seen["returned"] = observation(messages, "perform_assigned_review")
        return AIMessage(content="Whole-report result retained with its actual scope and limits.")

    def select(messages):
        return invoke("select_content_delivery", operation_id="whole-select", snapshot_ref=seen["snapshot"],
            export_ref=seen["export"], ending_reason="preserve_unresolved")

    driver = Driver(coordinator=[invoke("import_source_versions", operation_id="whole-inputs", source_ids=["s"]),
        criterion, writer_task, invoke("read_object_index", limit=20), freeze, export, review_task, select,
        AIMessage(content="Selected exact Word; whole question result is retained, without a global approval claim.")],
        writer=[produce, adopt, AIMessage(content="Saved owned report tree.")],
        reviewer=[read_word, check, finish_review], text_tool=[text_model])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    records = cs.list_objects("ReviewRecord")
    if case == "body_not_supplied":
        assert seen["returned"]["code"] == "REVIEW_REQUIRED_BODIES_NOT_SUPPLIED"
        assert seen["returned"]["model_called"] is False and not records
        assert "checker_packet" not in seen
    else:
        assert len(records) == 1
        record = records[0]
        item = record["payload"]["items"][0]
        assert record["payload"]["snapshot_ref"] == seen["snapshot"]
        assert item["target_ref"] == seen["root"] and item["criterion_ref"] == seen["criterion"]
        assert item["scope_id"] == "whole-access-report" and item["execution_state"] == "completed"
        assert item["verdict"] == ("satisfied" if case == "complete" else "not_satisfied")
        assert bool(item["findings"]) == (case == "missing_b")
        assert record["owner_id"].startswith("content:reviewer:")
        with store.connect() as db:
            owner, observed = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (seen["word_receipt"],)).fetchone()
        assert owner == record["owner_id"] and json.loads(observed)["export_ref"] == seen["export"]
        assert all(n["owner_id"].startswith("content:writer:") and n["owner_id"] != record["owner_id"] for n in seen["nodes"])
        saved = deepcopy(record)
        assert ContentStore(Store(store.root)).read(record["ref"]) == saved
    delivery = report_state.selected_delivery(store)
    assert delivery["snapshot_ref"] == seen["snapshot"] and delivery["export_ref"] == seen["export"]
    assert cs.read(seen["export"])["payload"]["snapshot_ref"] == seen["snapshot"]
    assert not report_state.selected_final_review(store)  # Whole assigned question is distinct from global final approval.
    final = await snapshot(ws, driver)
    assert not final.next and not final.interrupts
    assert not any(role == "rubric_grader" for role, _, _ in driver.calls)
