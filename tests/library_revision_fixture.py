"""Explicit current source/revision/whole-question migration of the old library trial."""
from report_agent import report_state
import hashlib
import json
from copy import deepcopy

from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.content_export import _bytes
from report_agent.content_store import ContentStore
from report_agent.review_status import read_status
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, call, invoke, observation


async def current_library_revision_protocol(tmp_path):
    store = Store(tmp_path / "current-library")
    goal = "Compile the complete daytime access report faithfully from the current supplied hours."
    store.initialize({"goal": goal, "content_contract": "hierarchical-review-v1",
        "review_entrypoint": "delegated-reviewer-v1", "review_execution_mode": "bounded-tool-v1",
        "sources": [{"id": "brief", "title": "Commission", "content": goal, "coverage": "complete"}]})
    ws, catalog, cs = Workspace(store), Catalog(store), ContentStore(store)
    texts = ["Daytime access hours: 08:00-17:00. Synthetic fixture only.",
             "Daytime access hours: 09:00-16:00. Synthetic fixture only."]
    source_ids = [catalog.import_file("hours.txt", texts[0].encode())["source"]["id"]]
    seen, phase = {}, 0

    def inputs(messages):
        seen["source"] = observation(messages, "import_source_versions")["result"]["source_refs"][0]
        return seen["source"]

    def standard(messages):
        source = inputs(messages)
        imported = observation(messages, "import_source_versions")["result"]
        seen["requirements"] = imported.get("requirement_refs", [imported["requirement_ref"]])
        return invoke("commit_objects", operation_id="library-stable-criterion", objects=[{
            "client_key": "criterion", "type": "Criterion", "payload": {
                "requirement_refs": seen["requirements"], "purpose": "Faithful complete access summary",
                "scope": "Whole access report and all its substantive bodies",
                "expected_outcome": "Complete daytime access hours match the current independent original hours source.",
                "evidence_expectation": "Read original current hours and all saved report bodies, not a summary of the draft.",
                "allowed_limits": "No engineering approval; unresolved input gaps remain explicit."}}])

    def writer_task(messages):
        seen["criterion"] = observation(messages, "commit_objects")["result"]["refs"]["criterion"]
        return delegate_writer()

    def delegate_writer():
        description = {"phase": phase, "source_id": source_ids[phase], "source_ref": seen["source"],
            "criterion_ref": seen["criterion"], "goal": goal}
        args = {"subagent_type": "writer", "description": encode(description)}
        if phase:
            description["previous"] = seen["initial_refs"]
            args.update(description=encode(description), resume_content_task_id=seen["writer_task"])
        return AIMessage(content="", tool_calls=[call("task", args, f"library-writer-{phase}")])

    def writer_produce(messages):
        # The public native HumanMessage contains this actual invocation's
        # description. No optional managed-context tool is assumed here.
        instruction = json.loads(next(m.content for m in reversed(messages) if m.type == "human"))
        assert instruction["phase"] == phase and instruction["source_ref"] == seen["source"]
        refs = [seen["criterion"], seen["source"]]
        if phase:
            refs.append(seen["initial_refs"]["claim"])
        return invoke("process_report_content", operation_id=f"library-produce-{phase}",
            objective="Compile the complete commissioned daytime hours from the current independent source.",
            object_type="ContentNode", input_refs=refs, source_selections=[{"source_id": source_ids[phase]}])

    def writer_adopt(messages):
        work = observation(messages, "process_report_content")
        objects = [{"client_key": "claim", "type": "ContentNode", "text_work_id": work["text_work_id"]}]
        if not phase:
            objects.insert(0, {"client_key": "root", "type": "ContentNode", "payload": {
                "kind": "report", "body": {"text": "Complete access report"}, "qualifiers": {}, "claim_kind": "structure"}})
            edge = {"subject_ref": {"client_key": "root"}, "object_ref": {"client_key": "claim"},
                "predicate": "contains", "position": 0, "provenance_kind": "adopted_during_generation"}
            objects.append({"client_key": "edge", "type": "Relation", "payload": edge})
        else:
            old = seen["initial_refs"]
            objects[0]["previous_ref"] = old["claim"]
            objects.append({"client_key": "edge", "type": "Relation", "previous_ref": old["edge"],
                "payload": {**cs.read(old["edge"])["payload"], "object_ref": {"client_key": "claim"}}})
        return invoke("commit_objects", operation_id=f"library-adopt-{phase}", objects=objects)

    def writer_finish(messages):
        refs = observation(messages, "commit_objects")["result"]["refs"]
        return AIMessage(content=encode({"saved_refs": refs}))

    def freeze(messages):
        refs = observation(messages, "task")["saved_refs"]
        if not phase:
            seen["initial_refs"] = deepcopy(refs)
        else:
            refs["root"] = seen["initial_refs"]["root"]
        seen["refs"] = refs
        # Independent live source remains an explicit task dependency outside the
        # frozen authored tree, so real source replacement invalidates old reuse.
        return invoke("freeze_snapshot", operation_id=f"library-freeze-{phase}", root_ref=refs["root"],
            refs=[*seen["requirements"], seen["criterion"], *refs.values()])

    def export(messages):
        frozen = observation(messages, "freeze_snapshot")
        assert frozen["ok"], frozen
        seen["snapshot"] = frozen["result"]["snapshot_ref"]
        return invoke("export_content_snapshot", operation_id=f"library-export-{phase}", snapshot_ref=seen["snapshot"])

    def review_task(messages):
        seen["export"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
        refs = seen["refs"]
        args = {"subagent_type": "reviewer", "description": "Judge the whole commissioned access report against the complete current independent hours.",
            "review_snapshot_ref": seen["snapshot"], "review_requirements": [{
                "target_ref": refs["root"], "criterion_ref": seen["criterion"], "scope_id": "whole-library-access",
                "required_checks": ["Entire commissioned daytime access report, all body text and exact current original hours agree"],
                "required_read_refs": [seen["source"]], "material_refs": [refs["claim"]],
                "required_materials": [{"requirement_index": 0, "purpose": "Whole root and independent complete current hours",
                    "refs": [refs["root"], seen["source"]]}],
                "content_check_scopes": [{"requirement_index": 0, "node_ref": refs["root"], "kind": "subtree_bodies"}]}]}
        return AIMessage(content="", tool_calls=[call("task", args, f"library-reviewer-{phase}")])

    def read_word(messages):
        return invoke("read_content_export", export_ref=seen["export"])

    def check(messages):
        actual = observation(messages, "read_content_export")
        assert actual["ok"] and texts[phase] in actual["result"]["text"]
        assert ("08:00-17:00" in actual["result"]["text"]) == (phase == 0)
        payload = cs.read(seen["export"])["payload"]
        assert payload["snapshot_ref"] == seen["snapshot"]
        assert hashlib.sha256(_bytes(store, payload["file_ref"], payload["file_digest"])).hexdigest() == actual["result"]["file_digest"]
        seen["word_receipt"] = actual["receipt_id"]
        return invoke("perform_assigned_review", operation_id=f"library-whole-check-{phase}", scope_ids=["whole-library-access"],
            source_selections=[], content_selections=[{"ref": seen["refs"]["claim"]}])

    def finish_review(messages):
        returned = observation(messages, "perform_assigned_review")
        assert returned["items"][0]["verdict"] == "satisfied", returned
        return AIMessage(content=encode(returned))

    def select(messages):
        return invoke("select_content_delivery", operation_id=f"library-select-{phase}",
            snapshot_ref=seen["snapshot"], export_ref=seen["export"], ending_reason="preserve_unresolved")

    def text_model(messages):
        packet = json.loads(messages[-1].content)
        if "assignment" not in packet:
            blocks = [b["text"] for e in packet["evidence"] if e["kind"] == "source_blocks" for b in e["observation"]["blocks"]]
            assert blocks == [texts[phase]]
            assert any(e.get("object", {}).get("ref") == seen["criterion"] for e in packet["evidence"])
            if phase:
                assert packet["actor"] == seen["writer_actor"]
                assert any(e.get("object", {}).get("ref") == seen["initial_refs"]["claim"] for e in packet["evidence"])
            else:
                seen["writer_actor"] = deepcopy(packet["actor"])
            return AIMessage(content=encode({"kind": "block", "body": {"text": texts[phase] + " [hours]"},
                "qualifiers": {}, "claim_kind": "fact"}))
        assert packet["commission"]["goal"] == goal
        assert packet["criteria"][0]["ref"] == seen["criterion"]
        evidence = packet["evidence"]
        source = next(e["object"] for e in evidence if e.get("object", {}).get("ref") == seen["source"])
        assert source["payload"]["content"] == texts[phase]
        structure = next(e["structure"] for e in evidence if e["kind"] == "snapshot_structure")
        assert structure["inventory_complete"] and not structure["missing_body_extents"]
        assert set(map(encode, structure["body_extents"][0]["required_body_refs"])) == set(map(encode, [seen["refs"]["root"], seen["refs"]["claim"]]))
        child = next(e for e in evidence if e.get("selection", {}).get("ref") == seen["refs"]["claim"])
        assert child["complete_body_selection"] and child["body"]["text"] == texts[phase] + " [hours]"
        observations = [{"evidence_index": i, "locator": f"complete input {i}", "observation": encode(e)}
            for i, e in enumerate(evidence) if e["kind"] in {"saved_object", "content_node_selection", "snapshot_structure"}]
        links = list(range(len(observations)))
        return AIMessage(content=encode({"items": [{"scope_id": "whole-library-access", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "satisfied", "observations": observations,
            "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": "Entire report matches exact current original hours.",
                "observation_indexes": links, "remaining": ""}], "coverage": {"checked": ["Whole commissioned report and all body extent"],
                "unchecked": [], "blocked": [], "basis": "Independent full current hours and exact saved complete tree/body."},
            "reason": "Synthetic whole-question protocol positive, not real engineering approval.", "findings": []}]}))

    def driver(actions, prior_steps=0):
        return Driver(coordinator=[*[None] * prior_steps, *actions],
            writer=[writer_produce, writer_adopt, writer_finish],
            reviewer=[read_word, check, finish_review], text_tool=[text_model])

    first_driver = driver([invoke("import_source_versions", operation_id="library-inputs-0", source_ids=list(source_ids)),
        standard, writer_task, freeze, export, review_task, select, AIMessage(content="Saved complete first access report and whole-question judgment.")])
    assert (await deep_runtime.run_report(ws, first_driver))["last_error"] is None
    initial = deepcopy({k: seen[k] for k in ("initial_refs", "source", "criterion", "snapshot", "export")})
    originals = deepcopy([cs.read(r) for r in [*initial["initial_refs"].values(), initial["source"], initial["criterion"]]])
    old_export = cs.read(initial["export"])["payload"]
    old_word = _bytes(store, old_export["file_ref"], old_export["file_digest"])
    old_review = deepcopy(cs.list_objects("ReviewRecord")[0])
    seen["writer_task"] = cs.read(initial["initial_refs"]["claim"])["task_id"]
    assert read_status(cs, initial["snapshot"], initial["initial_refs"]["root"])["objects"][0]["scopes"][0]["verdict"] == "satisfied"

    phase = 1
    source_ids.append(catalog.import_file("hours.txt", texts[1].encode(), source_ids[0])["source"]["id"])
    stale = read_status(cs, initial["snapshot"], initial["initial_refs"]["root"])["objects"][0]
    assert not stale["has_current_review"] and stale["needs_recheck"]

    def find_owner(messages):
        inputs(messages)
        return invoke("read_context", target_ref=initial["initial_refs"]["claim"])

    def owner_index(messages):
        node = observation(messages, "read_context")["result"]["objects"][0]
        assert node["task_id"] == seen["writer_task"]
        return invoke("read_object_index", object_type="DelegatedTask", current_only=True)

    def owner_read(messages):
        page = observation(messages, "read_object_index")
        owner = next(r["ref"] for r in page["objects"] if r["ref"]["id"] == seen["writer_task"])
        return invoke("read_context", target_ref=owner)

    def resume(messages):
        task = observation(messages, "read_context")["result"]["objects"][0]
        assert task["ref"]["id"] == seen["writer_task"]
        return delegate_writer()

    prior = sum(role == "coordinator" for role, _, _ in first_driver.calls)
    revised_driver = driver([invoke("import_source_versions", operation_id="library-inputs-1", source_ids=[source_ids[1]]),
        find_owner, owner_index, owner_read, resume, freeze, export, review_task, select,
        AIMessage(content="New exact whole report independently checked against replacement hours; old version retained.")], prior)
    assert (await deep_runtime.run_report(ws, revised_driver))["last_error"] is None
    assert cs.read(seen["refs"]["claim"])["previous_ref"] == initial["initial_refs"]["claim"]
    assert cs.read(seen["refs"]["claim"])["owner_id"] == originals[1]["owner_id"]
    assert cs.read(initial["criterion"]) == originals[-1]
    assert [cs.read(r["ref"]) for r in originals] == originals
    assert _bytes(store, old_export["file_ref"], old_export["file_digest"]) == old_word
    assert cs.read(old_review["ref"]) == old_review
    reviews = cs.list_objects("ReviewRecord")
    assert len(reviews) == 2 and reviews[0]["owner_id"] != reviews[1]["owner_id"]
    assert reviews[1]["payload"]["items"][0]["target_ref"] == seen["refs"]["root"]
    assert reviews[1]["payload"]["items"][0]["verdict"] == "satisfied"
    with store.connect() as db:
        owner, actual = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (seen["word_receipt"],)).fetchone()
    assert owner == reviews[1]["owner_id"] and json.loads(actual)["export_ref"] == seen["export"]
    assert len(cs.list_objects("Criterion")) == 1 and len(cs.list_objects("DelegatedTask")) == 3

    unrelated = catalog.import_file("unrelated.txt", b"Synthetic unrelated meeting room inventory.")["source"]["id"]
    before = deepcopy(cs.list_objects()), deepcopy(report_state.selected_delivery(store))
    def retain(messages):
        assert "meeting room" in encode(observation(messages, "read_source_page"))
        return invoke("read_review_status", snapshot_ref=seen["snapshot"], target_ref=seen["refs"]["root"])
    def done(messages):
        assert observation(messages, "read_review_status")["result"]["objects"][0]["scopes"][0]["verdict"] == "satisfied"
        return AIMessage(content="The observed room inventory does not affect commissioned access hours; retain saved report and judgment.")
    fresh = Driver(coordinator=[*[None] * (prior + sum(role == "coordinator" for role, _, _ in revised_driver.calls)),
        invoke("read_source_page", source_id=unrelated, limit=1), retain, done])
    assert (await deep_runtime.run_report(ws, fresh))["last_error"] is None
    assert {role for role, _, _ in fresh.calls} == {"coordinator"}
    assert (cs.list_objects(), report_state.selected_delivery(store)) == before
    assert not report_state.selected_final_review(store)
    return ws


def historical_correction_state_control(tmp_path):
    """Real compatibility transaction; not a renamed native HandlingRecord."""
    store = Store(tmp_path / "historical-correction-state")
    store.initialize({"goal": "Historical material correction state", "sources": [
        {"id": "hours", "title": "Hours", "content": "Daytime access hours.", "coverage": "complete"}]})
    ws = Workspace(store)
    ws.initialize()
    initial = ws.request_task("materials", "Save original historical hours material", [])
    material = ws.submit(initial["id"], actor=initial["owner"], title="Original hours material",
        body="08:00-17:00 [hours].", source_ids=["hours"], input_ids=[])
    old = deepcopy(material)
    correction = ws.request_correction(material["id"], "Use the revised supplied hours.")
    task = ws.request_revision(material["id"], "Explicit original-producer material revision")
    result = ws.submit(task["id"], actor=task["owner"], title="Revised hours material", body="09:00-16:00 [hours].",
        source_ids=["hours"], input_ids=[])
    addressed = next(c for c in store.get("corrections") if c["id"] == correction["id"])
    assert addressed["status"] == "addressed" and addressed["resolved"] is False
    assert result["replaces_id"] == material["id"] and ws.result(material["id"]) == old
