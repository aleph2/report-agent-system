"""Actual DeepAgents execution with offline scripted models, not quality evidence."""
from report_agent import report_state
import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_export import export_snapshot
from report_agent.content_models import Ref
from report_agent.hierarchical_tools import content_tools
from test_deep_runtime import Driver, call, invoke, observation
from test_hierarchical_content import ws, seed, review_item, submission
from hierarchical_fixtures import delivery_evidence, unchecked_delivery


def select(snapshot, export):
    return invoke("select_content_delivery", operation_id="select:" + snapshot["id"], snapshot_ref=snapshot, export_ref=export)


def grade(snapshot, refs, verdict, checks=None):
    def action(messages):
        receipt = observation(messages, "read_context")["receipt_id"]
        item = review_item(snapshot, refs["k"], receipt, verdict)
        return AIMessage(content="", tool_calls=[call("HierarchicalResponse", {"explanation": "Offline protocol fixture.", "review": {**submission(snapshot, refs, item), "delivery_checks": checks if checks is not None else unchecked_delivery()}})])
    return action


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    def denied(*a, **k):
        pytest.fail("Network forbidden for synthetic protocol tests")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


async def test_native_final_pass_and_effective_permissions(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected for review.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
    from hierarchical_fixtures import historical_hierarchical_review
    result = await historical_hierarchical_review(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    assert result["content_final_review"]["overall_verdict"] == "satisfied"
    names = {t["name"] for t in driver.bindings["rubric_grader"][0]}
    assert {"read_context", "read_feedback", "observe_evidence"} <= names
    assert not {"submit_result", "commit_objects", "select_content_delivery", "task", "write_file"} & names
    prompt = str(next(messages[0].content for role, _, messages in driver.calls if role == "coordinator"))
    assert "save_acceptance_criteria" not in prompt
    assert "own the requirement" not in prompt or "criteria" in prompt


async def test_unexecuted_null_does_not_trigger_author_repair(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    answer = AIMessage(content="", tool_calls=[call("HierarchicalResponse", {
        "explanation": "Reading was blocked; no semantic conclusion.",
        "review": {**submission(snapshot, refs, review_item(snapshot, refs["k"], verdict=None)), "delivery_checks": unchecked_delivery()}})])
    driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), AIMessage(content="Unexecuted review retained; no approval.")], rubric_grader=[answer])
    from hierarchical_fixtures import historical_hierarchical_review
    result = await historical_hierarchical_review(ws, driver)
    assert result["last_error"] is None, result
    assert result["content_final_review"]["overall_verdict"] is None
    assert result["status"] == "needs_attention"
    assert len([r for r in cs.list_objects("ContentNode")]) == 2
    assert "needs_revision" not in json.dumps(result["content_final_review"])

    # A fresh invocation of the same snapshot must re-open investigation, while
    # checkpoint continuation is handled without starting a new run.
    assert [step for role, step, _ in driver.calls if role == "coordinator"] == [0, 1, 2]
    new_driver = Driver(coordinator=[None] * 3 +
        [AIMessage(content="Retry investigation after source recovery.")],
        rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
    # Fresh Human invocation reopens the actual saved graph; prior AI turns retain their indexes.
    retried = await historical_hierarchical_review(ws, new_driver)
    assert [step for role, step, _ in new_driver.calls if role == "coordinator"] == [3]
    assert retried["last_error"] is None, retried
    assert retried["content_final_review"]["overall_verdict"] == "satisfied", retried
    assert len(cs.list_objects("ReviewRecord")) == 2


async def test_feedback_revision_recheck_runs_through_native_graph(tmp_path):
    """Current native review/revision chain; fake judgments do not prove quality."""
    from copy import deepcopy
    from io import BytesIO
    from docx import Document
    from langchain_core.messages import ToolMessage
    from report_agent.store import digest
    from report_agent.content_store import ContentStore
    from report_agent.content_export import _bytes
    from report_agent.content_delivery import current_delivery
    from test_task_supervision import ws as native_ws
    from test_decision_data import activate
    from test_agent_duty_trace_cases import result_value
    ws = native_ws.__wrapped__(tmp_path)
    activate(ws)
    cs, seen = ContentStore(ws.store), {}
    initial = {"kind": "block", "body": {"text": "For adopted class B use 70."},
               "qualifiers": {}, "claim_kind": "fact"}
    revised = {**initial, "body": {"text": "Under class B, permitted range is 75 to 100; final selection unresolved."}}
    sources_before = deepcopy(ws.store.manifest["sources"])

    def received(messages, name, identity=None):
        return result_value(next(m for m in reversed(messages) if isinstance(m, ToolMessage)
            and m.name == name and (identity is None or m.tool_call_id == identity)))

    def delegated(identity, **args):
        action = invoke("task", **args)
        action.tool_calls[0]["id"] = identity
        return action

    def initial_refs(messages):
        return received(messages, "task", "writer-create")["saved_refs"]

    def criterion(messages):
        return received(messages, "commit_objects")["result"]["refs"]["criterion"]

    def inputs(messages):
        return received(messages, "import_source_versions")["result"]

    def standard(messages):
        return invoke("commit_objects", operation_id="criterion", objects=[{
            "client_key": "criterion", "type": "Criterion", "payload": {
                "requirement_refs": [inputs(messages)["requirement_ref"]],
                "purpose": "Compare the adopted class B value with the original interval.",
                "scope": "Class B value", "expected_outcome": "Use the permitted interval and disclose unresolved selection.",
                "evidence_expectation": "Complete adopted claim and original class B rule.",
                "allowed_limits": "The final value may remain explicitly unresolved."}}])

    def delegate_writer(messages):
        seen["source_ref"] = deepcopy(inputs(messages)["source_refs"][0])
        return delegated("writer-create", subagent_type="writer", description=json.dumps({
            "action": "initial", "criterion_ref": criterion(messages),
            "source_ref": inputs(messages)["source_refs"][0]}))

    def freeze(messages):
        saved = initial_refs(messages)
        return invoke("freeze_snapshot", operation_id="snapshot1", root_ref=saved["root"],
            refs=[*saved.values(), criterion(messages), inputs(messages)["requirement_ref"],
                  *inputs(messages)["source_refs"]])

    def current_snapshot(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage)
                       and m.name in {"freeze_snapshot", "derive_snapshot"})
        return result_value(message)["result"]["snapshot_ref"]

    def word(messages):
        snap = current_snapshot(messages)
        return invoke("export_content_snapshot", operation_id="word:" + snap["id"], snapshot_ref=snap)

    def choose(messages):
        result = received(messages, "export_content_snapshot")["result"]
        export = result["export_ref"]
        obj = cs.read(export)
        data = _bytes(ws.store, obj["payload"]["file_ref"], obj["payload"]["file_digest"])
        seen.setdefault("exports", []).append((deepcopy(obj), data))
        return select(current_snapshot(messages), export)

    def review_task(messages):
        new = any(isinstance(m, ToolMessage) and m.name == "derive_snapshot" for m in messages)
        saved = received(messages, "task", "writer-revise")["saved_refs"] if new else initial_refs(messages)
        source = inputs(messages)["source_refs"][0]
        return delegated("review-second" if new else "review-first", subagent_type="reviewer",
            description="Compare this exact claim with the original class B rule; preserve unresolved final choice.",
            review_snapshot_ref=current_snapshot(messages), review_requirements=[{
                "target_ref": saved["claim"], "criterion_ref": criterion(messages),
                "scope_id": "rule-comparison", "required_checks": ["rule comparison"],
                "required_materials": [{"requirement_index": 0,
                    "purpose": "Compare complete claim with original permitted interval.",
                    "refs": [saved["claim"], source]}]}])

    def read_reviewed_node(messages):
        records = received(messages, "read_feedback")["result"]["records"]
        assert len(records) == 1 and records[0]["payload"]["items"][0]["verdict"] == "not_satisfied"
        seen["first_review"] = deepcopy(records[0])
        return invoke("read_context", target_ref=records[0]["payload"]["items"][0]["target_ref"])

    def task_index(messages):
        node = received(messages, "read_context")["result"]["objects"][0]
        seen["old_public_node"] = deepcopy(node)
        return invoke("read_object_index", object_type="DelegatedTask", current_only=True)

    def read_owner_task(messages):
        page = received(messages, "read_object_index")
        task_ref = next(obj["ref"] for obj in page["objects"]
                        if obj["ref"]["id"] == seen["old_public_node"]["task_id"])
        return invoke("read_context", target_ref=task_ref)

    def resume_writer(messages):
        task = received(messages, "read_context")["result"]["objects"][0]
        node, saved = seen["old_public_node"], initial_refs(messages)
        assert task["ref"]["id"] == node["task_id"]
        return delegated("writer-revise", subagent_type="writer", resume_content_task_id=task["ref"]["id"],
            description=json.dumps({"action": "revise", "target_ref": node["ref"],
                "edge_ref": saved["edge"], "root_ref": saved["root"],
                "review_ref": seen["first_review"]["ref"], "criterion_ref": criterion(messages),
                "source_ref": inputs(messages)["source_refs"][0]}))

    def derive(messages):
        old, new = initial_refs(messages), received(messages, "task", "writer-revise")["saved_refs"]
        base = received(messages, "freeze_snapshot")["result"]["snapshot_ref"]
        return invoke("derive_snapshot", operation_id="snapshot2", base_snapshot_ref=base,
            additional_refs=[], replacements=[{"previous_ref": old[k], "new_ref": new[k]} for k in ("claim", "edge")])

    def parent_finish(messages):
        records = received(messages, "read_feedback")["result"]["records"]
        assert [r["payload"]["items"][0]["verdict"] for r in records] == ["not_satisfied", "undetermined"]
        assert records[1]["payload"]["snapshot_ref"] == current_snapshot(messages)
        seen["public_reviews"] = deepcopy(records)
        return AIMessage(content="The class B interval is corrected; final selection remains unresolved. No whole-report approval.")

    def instruction(messages):
        value = received(messages, "read_decision_state")["value"]
        return json.loads(value["description"])

    def writer_first_read(messages):
        data = instruction(messages)
        return invoke("read_context", target_ref=data["criterion_ref"]) if data["action"] == "initial" else invoke("read_feedback")

    def writer_produce_or_read(messages):
        data = instruction(messages)
        if data["action"] == "revise":
            records = received(messages, "read_feedback")["result"]["records"]
            assert len(records) == 1 and records[0]["ref"] == data["review_ref"]
            return invoke("read_context", target_ref=data["target_ref"])
        selected = received(messages, "read_context")["result"]["objects"][0]
        assert selected["ref"] == data["criterion_ref"]
        return invoke("process_report_content", operation_id="produce-initial", object_type="ContentNode",
            objective=json.dumps({"intent": "initial", "criterion_ref": selected["ref"]}),
            input_refs=[selected["ref"], data["source_ref"]], source_selections=[{"source_id": "s"}])

    def writer_adopt_or_read_edge(messages):
        data = instruction(messages)
        if data["action"] == "revise":
            node = received(messages, "read_context")["result"]["objects"][0]
            assert node == seen["old_public_node"]
            return invoke("read_context", target_ref=data["edge_ref"])
        work = received(messages, "process_report_content")
        seen["first_work_id"] = work["text_work_id"]
        seen["old_receipt"] = deepcopy(ws.store.get("text_work_receipt:" + work["text_work_id"]))
        return invoke("commit_objects", operation_id="adopt-initial", objects=[
            {"client_key": "root", "type": "ContentNode", "payload": {"kind": "report",
                "body": {"text": "Synthetic class B report"}, "qualifiers": {}, "claim_kind": "structure"}},
            {"client_key": "claim", "type": "ContentNode", "text_work_id": work["text_work_id"]},
            {"client_key": "edge", "type": "Relation", "payload": {"subject_ref": {"client_key": "root"},
                "object_ref": {"client_key": "claim"}, "predicate": "contains", "position": 0,
                "provenance_kind": "adopted_during_generation"}}])

    def writer_finish_or_revise(messages):
        if instruction(messages)["action"] == "initial":
            return AIMessage(content=json.dumps({"saved_refs": received(messages, "commit_objects")["result"]["refs"]}))
        data = instruction(messages)
        records = received(messages, "read_feedback")["result"]["records"]
        selected = next(r for r in records if r["ref"] == data["review_ref"])
        edge = received(messages, "read_context")["result"]["objects"][0]
        assert edge["ref"] == data["edge_ref"] and edge["payload"]["object_ref"] == data["target_ref"]
        return invoke("process_report_content", operation_id="produce-revision", object_type="ContentNode",
            objective=json.dumps({"intent": "revise-established-conflict", "selected_review": selected}),
            input_refs=[data["target_ref"], data["source_ref"], data["criterion_ref"]], source_selections=[{"source_id": "s"}])

    def adopt_revision(messages):
        data = instruction(messages)
        edge = received(messages, "read_context")["result"]["objects"][0]
        work = received(messages, "process_report_content")
        return invoke("commit_objects", operation_id="adopt-revision", objects=[
            {"client_key": "claim", "type": "ContentNode", "previous_ref": data["target_ref"], "text_work_id": work["text_work_id"]},
            {"client_key": "edge", "type": "Relation", "previous_ref": edge["ref"],
                "payload": {**edge["payload"], "object_ref": {"client_key": "claim"}}}])

    def return_revision(messages):
        return AIMessage(content=json.dumps({"saved_refs": received(messages, "commit_objects")["result"]["refs"]}))

    packets = []
    def independent_work(messages):
        packet = json.loads(messages[-1].content)
        packets.append(deepcopy(packet))
        if "objective" in packet:
            objective = json.loads(packet["objective"])
            objects = [e["object"] for e in packet["evidence"] if e["kind"] == "saved_object"]
            source = next(o for o in objects if o["ref"]["type"] == "SourceArtifact")
            assert source["ref"] == seen["source_ref"]
            original = cs.read(source["ref"])["payload"]
            assert source["payload"] == {k: v for k, v in original.items() if k != "content"}
            assert source["payload"]["source_id"] == "s" and original["content"] == "Class B permits 75 to 100."
            assert source["content_digest"] == digest(original["content"])
            assert source["content_supplied"] == "located selections only"
            selections = [e for e in packet["evidence"] if e["kind"] == "source_blocks"]
            assert len(selections) == 1 and selections[0]["selection"]["source_id"] == "s"
            actual = selections[0]["observation"]
            assert [b["text"] for b in actual["blocks"]] == [original["content"]]
            assert actual["total_blocks"] == len(actual["blocks"]) == 1 and actual["next_offset"] is None
            assert next(o for o in objects if o["ref"]["type"] == "Criterion")["payload"]["scope"] == "Class B value"
            if objective["intent"] == "initial":
                seen["producer_actor"] = deepcopy(packet["actor"])
                return AIMessage(content=json.dumps(initial))
            assert objective == {"intent": "revise-established-conflict", "selected_review": seen["first_review"]}
            assert next(o for o in objects if o["ref"]["type"] == "ContentNode") == seen["old_public_node"]
            assert packet["actor"] == seen["producer_actor"]
            return AIMessage(content=json.dumps(revised))
        assigned = packet["assignment"]["review_requirements"][0]
        target = next((i, e["object"]) for i, e in enumerate(packet["evidence"])
                      if e.get("object", {}).get("ref") == assigned["target_ref"])
        source = next((i, e["object"]) for i, e in enumerate(packet["evidence"])
                      if e.get("object", {}).get("ref", {}).get("type") == "SourceArtifact")
        assert source[1]["payload"]["content"] == "Class B permits 75 to 100."
        assert packet["criteria"][0]["ref"] == assigned["criterion_ref"]
        is_initial = target[1]["ref"]["version"] == 1
        assert target[1]["payload"] == (initial if is_initial else revised)
        reason = "70 is outside 75 to 100." if is_initial else "Permitted interval corrected; final selection remains unresolved."
        return AIMessage(content=json.dumps({"items": [{"scope_id": "rule-comparison",
            "checked_requirement_indexes": [0], "execution_state": "completed",
            "verdict": "not_satisfied" if is_initial else "undetermined",
            "observations": [{"evidence_index": target[0], "locator": "complete claim", "observation": target[1]["payload"]["body"]["text"]},
                {"evidence_index": source[0], "locator": "original rule", "observation": source[1]["payload"]["content"]}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": reason,
                "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["rule comparison"], "unchecked": [], "blocked": [], "basis": "Exact claim, criterion and original rule."},
            "reason": reason, "outside_assignment_notes": [] if is_initial else ["Confirm final selection."], "findings": []}]}))

    def return_review(messages):
        return AIMessage(content=json.dumps(received(messages, "perform_assigned_review")))

    driver = Driver(coordinator=[invoke("import_source_versions", operation_id="inputs", source_ids=["s"]),
        standard, delegate_writer, freeze, word, choose, review_task, invoke("read_feedback"),
        read_reviewed_node, task_index, read_owner_task, resume_writer, derive, word, choose,
        review_task, invoke("read_feedback"), parent_finish],
        writer=[invoke("read_decision_state", path=["current_invocation"]), writer_first_read,
            writer_produce_or_read, writer_adopt_or_read_edge, writer_finish_or_revise, adopt_revision, return_revision],
        reviewer=[invoke("perform_assigned_review", operation_id="compare", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[]), return_review], text_tool=[independent_work])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    reviews = cs.list_objects("ReviewRecord")
    assert reviews == seen["public_reviews"] and len(reviews) == 2
    assert reviews[0] == seen["first_review"]
    old = seen["old_public_node"]
    new = cs.read(reviews[1]["payload"]["items"][0]["target_ref"])
    assert cs.read(old["ref"]) == old and old["payload"] == initial
    assert new["payload"] == revised and new["previous_ref"] == old["ref"]
    assert new["owner_id"] == old["owner_id"] and new["task_id"] == old["task_id"]
    assert old["task_id"] == seen["producer_actor"]["task_id"]
    assert len(cs.list_objects("DelegatedTask")) == 3  # One Writer, two independent Reviewers.
    assert reviews[0]["payload"]["snapshot_ref"] != reviews[1]["payload"]["snapshot_ref"]
    assert len(packets) == 4 and sum("objective" in p for p in packets) == 2
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 4
    assert "rubric_grader" not in driver.created
    assert ws.store.get("text_work_receipt:" + seen["first_work_id"]) == seen["old_receipt"]
    assert ws.store.manifest["sources"] == sources_before
    assert len(seen["exports"]) == 2
    for (export, data), expected in zip(seen["exports"], (initial, revised)):
        assert _bytes(ws.store, export["payload"]["file_ref"], export["payload"]["file_digest"]) == data
        assert expected["body"]["text"] in "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    assert seen["exports"][0][0]["payload"]["snapshot_ref"] == reviews[0]["payload"]["snapshot_ref"]
    assert seen["exports"][1][0]["payload"]["snapshot_ref"] == reviews[1]["payload"]["snapshot_ref"]
    assert report_state.selected_delivery(ws.store)["export_ref"] == seen["exports"][1][0]["ref"]
    assert current_delivery(ws.store)["overall_verdict"] != "satisfied"

async def test_local_review_returns_feedback_without_finishing_or_revising(tmp_path):
    from copy import deepcopy
    from langchain_core.messages import ToolMessage
    from report_agent.content_delivery import current_delivery
    from report_agent.content_export import _bytes
    from test_agent_duty_trace_cases import result_value
    from test_bounded_review import review_call
    from test_decision_data import activate
    from test_task_supervision import ws as native_ws

    ws = native_ws.__wrapped__(tmp_path)
    activate(ws)
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    saved_export = cs.read(export)
    original_word = _bytes(ws.store, saved_export["payload"]["file_ref"], saved_export["payload"]["file_digest"])
    original_nodes = deepcopy(cs.list_objects("ContentNode"))
    original_relations = deepcopy(cs.list_objects("Relation"))
    original_sources = deepcopy(ws.store.manifest["sources"])
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    source_object = deepcopy(cs.read(source))
    packets, returned_feedback = [], []

    def checker(messages):
        packet = json.loads(messages[-1].content)
        packets.append(deepcopy(packet))
        assigned = packet["assignment"]["review_requirements"][0]
        assert assigned["target_ref"] == refs["claim"]
        assert assigned["criterion_ref"] == refs["k"]
        indexes = [next(i for i, e in enumerate(packet["evidence"])
                        if e.get("object", {}).get("ref") == ref) for ref in (refs["claim"], source)]
        assert [packet["evidence"][i]["object"] for i in indexes] == [next(o for o in original_nodes if o["ref"] == refs["claim"]), source_object]
        return AIMessage(content=json.dumps({"items": [{
            "scope_id": "rule-comparison", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": indexes[0], "locator": "claim", "observation": "For adopted class B use 70."},
                             {"evidence_index": indexes[1], "locator": "rule", "observation": "Class B permits 75 to 100."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "70 is outside the original permitted interval.", "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["rule comparison"], "unchecked": [], "blocked": [], "basis": "Exact assigned claim and rule."},
            "reason": "Known local defect remains unresolved.", "findings": []}]}))

    def preserve_feedback(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_feedback")
        records = result_value(message)["result"]["records"]
        assert len(records) == 1
        record = records[0]
        assert record["payload"]["items"][0]["verdict"] == "not_satisfied"
        returned_feedback.append(deepcopy(record))
        return invoke("select_content_delivery", operation_id="stop-with-known-defect",
            snapshot_ref=snapshot, export_ref=export, ending_reason="preserve_unresolved")

    def finish(messages):
        assert returned_feedback
        return AIMessage(content="The local defect remains unresolved; no correction or whole-report approval.")

    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[review_call(snapshot, refs, reads=[source])]),
        invoke("read_feedback"), preserve_feedback, finish],
        reviewer=[invoke("perform_assigned_review", operation_id="local-defect", scope_ids=["rule-comparison"],
                         source_selections=[], content_selections=[]), AIMessage(content="Saved local finding returned unchanged.")],
        text_tool=[checker])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    reviews = cs.list_objects("ReviewRecord")
    assert reviews == returned_feedback and len(reviews) == 1
    review = reviews[0]
    assert review["payload"]["runtime_identity"]["mode"] == "bounded-review-v1"
    task = cs.read({"type": "DelegatedTask", "id": review["task_id"], "version": 1})
    assert task["payload"]["role"] == "reviewer"
    assert review["owner_id"] == "content:reviewer:" + task["ref"]["id"]
    assert len(packets) == 1 and sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    assert "rubric_grader" not in driver.created
    assert not {"writer", "rubric_grader"} & {role for role, _, _ in driver.calls}
    assert [t["payload"]["role"] for t in cs.list_objects("DelegatedTask")] == ["reviewer"]
    assert result["execution_status"] == "completed"
    delivery = current_delivery(ws.store)
    assert len(delivery["confirmed_violations"]) == 1
    assert delivery["confirmed_violations"][0]["review_ref"] == review["ref"]
    assert delivery["overall_verdict"] != "satisfied" and not delivery["final_review_current"]
    assert cs.list_objects("ContentNode") == original_nodes
    assert cs.list_objects("Relation") == original_relations
    assert ws.store.manifest["sources"] == original_sources and cs.read(source) == source_object
    assert cs.read(export) == saved_export
    assert _bytes(ws.store, saved_export["payload"]["file_ref"], saved_export["payload"]["file_digest"]) == original_word
