"""Synthetic delivery evidence for protocol tests, never model quality evidence."""
from report_agent.content_export import read_export
from report_agent.hierarchical_tools import actor_for


def unchecked_delivery():
    return [{"kind": k, "artifact_refs": [], "execution_state": "not_started", "verdict": None,
        "observations": [], "coverage": {"checked": [], "unchecked": [k], "blocked": [], "basis": "not performed"},
        "reason": "Required delivery check has not run."} for k in ("export", "render")]


def delivery_evidence(cs, snapshot, export, actor=None):
    """Actual DOCX read + explicitly synthetic visual observation and render identity."""
    actor = actor or actor_for("rubric_grader")
    export_receipt = read_export(cs, actor, export)["receipt_id"]
    with cs.store.connect() as db:
        render = cs._insert(db, actor, "RenderArtifact", {"snapshot_ref": snapshot, "export_ref": export,
            "page_assets": [{"page": 1}], "test_fixture": "synthetic render; not quality evidence"})
    page_receipt = cs.observe(actor, {"status": "observed", "observation": "Synthetic visible page fixture.",
        "source": {"render_ref": render, "export_ref": export, "page": 1}})["receipt_id"]
    return [{"kind": k, "artifact_refs": [ref], "execution_state": "completed", "verdict": "satisfied",
        "observations": [{"locator": k, "observation": "Protocol fixture.", "receipt_id": receipt}],
        "coverage": {"checked": [k], "unchecked": [], "blocked": [], "basis": "protocol fixture"},
        "reason": "Synthetic protocol result; not a quality conclusion."}
        for k, ref, receipt in (("export", export, export_receipt), ("render", render, page_receipt))]


async def current_native_export_read_review(tmp_path):
    """Actual saved Word/receipt protocol; scripted export-only judgment, no vision."""
    import hashlib
    import json
    from copy import deepcopy
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.content_export import _bytes
    from test_task_supervision import ws as native_fixture
    from test_hierarchical_content import seed
    from test_deep_runtime import Driver, invoke, call, observation, events
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, snapshot, _ = seed(ws)
    originals = deepcopy(cs.list_objects("ContentNode"))
    seen = {}
    def assign(messages):
        exported = observation(messages, "export_content_snapshot")
        assert exported["ok"], exported
        export = exported["result"]["export_ref"]
        record = cs.read(export)
        assert record["payload"]["snapshot_ref"] == snapshot
        data = _bytes(ws.store, record["payload"]["file_ref"], record["payload"]["file_digest"])
        seen.update(export=export, digest=hashlib.sha256(data).hexdigest())
        assert seen["digest"] == record["payload"]["file_digest"]
        # Narrow task: compare saved Word identity/literal text, not the seeded
        # Criterion's engineering rule or page appearance.
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "reviewer",
            "description": "Check only exact saved Word identity and literal text/structure; no engineering-rule or visual verdict.",
            "review_snapshot_ref": snapshot, "review_requirements": [{"target_ref": refs["claim"],
                "criterion_ref": refs["k"], "scope_id": "saved-export-text", "assessment_kind": "export",
                "artifact_refs": [export], "required_checks": ["Check exact saved Word identity and literal text/structure"]}]},
            "review-saved-export")])
    def read(messages):
        return invoke("read_content_export", export_ref=seen["export"])
    def compare(messages):
        returned = observation(messages, "read_content_export")
        assert returned["ok"], returned
        actual = returned["result"]
        assert actual["export_ref"] == seen["export"] and actual["file_digest"] == seen["digest"]
        assert "For adopted class B use 70." in actual["text"] and actual["structure"]
        assert actual["limitation"] == "Actual OOXML content; not visual observation."
        with ws.store.connect() as db:
            owner, raw = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?",
                (returned["receipt_id"],)).fetchone()
        assert json.loads(raw) == actual
        seen.update(read=deepcopy(actual), receipt=returned["receipt_id"], owner=owner)
        return invoke("perform_assigned_artifact_review", operation_id="compare-saved-word",
            scope_ids=["saved-export-text"], observation_receipts=[returned["receipt_id"]])
    def checker(messages):
        packet = json.loads(messages[-1].content)
        assert packet["snapshot_ref"] == snapshot
        assert packet["evidence"] == [{"receipt_id": seen["receipt"], "actual_observation": seen["read"]}]
        assert packet["requirements"][0]["artifact_refs"] == [seen["export"]]
        assert packet["criteria"] == [cs.read(refs["k"])]
        seen["packet"] = packet
        item = {"target_ref": refs["claim"], "criterion_ref": refs["k"], "scope": "node",
            "scope_id": "saved-export-text", "assessment_kind": "export", "artifact_refs": [seen["export"]],
            "execution_state": "completed", "verdict": "satisfied",
            "observations": [{"receipt_id": seen["receipt"], "locator": "OOXML text and structure",
                "observation": "Actual saved Word text and digest received; no physical-page observation."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": "Synthetic export-identity positive.",
                "observation_indexes": [0], "remaining": ""}],
            "coverage": {"checked": ["Saved Word identity and literal text"], "unchecked": [], "blocked": [],
                "basis": "Actual OOXML read; no rule or visual judgment."},
            "reason": "Scripted export-only protocol positive, not engineering validity.", "findings": []}
        return AIMessage(content=json.dumps({"snapshot_ref": snapshot, "target_ref": refs["claim"],
            "scope": "Exact saved Word export", "criteria_refs": [refs["k"]], "dependency_refs": [seen["export"]],
            "items": [item], "delivery_checks": []}))
    driver = Driver(coordinator=[invoke("export_content_snapshot", operation_id="export-protocol-word", snapshot_ref=snapshot),
        assign, AIMessage(content="Scoped export evidence retained; no whole-report approval.")],
        reviewer=[read, compare, AIMessage(content="Saved independent export-only finding.")], text_tool=[checker])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    records, tasks = cs.list_objects("ReviewRecord"), cs.list_objects("DelegatedTask")
    assert len(records) == len(tasks) == 1
    record = records[0]
    assert record["owner_id"] == seen["owner"] == "content:reviewer:" + tasks[0]["ref"]["id"]
    assert record["task_id"] == tasks[0]["ref"]["id"]
    assert record["payload"]["items"][0]["artifact_refs"] == [seen["export"]]
    assert record["payload"]["items"][0]["observations"][0]["receipt_id"] == seen["receipt"]
    assert record["payload"]["items"][0]["verdict"] == "satisfied"
    assert cs.list_objects("ContentNode") == originals and not cs.list_objects("RenderArtifact")
    assert not ws.store.get("content_final_review")
    reads = [e for e in events(ws, "deep_tool_start") if e["role"] == "reviewer" and e["tool"] == "read_content_export"]
    assert len(reads) == 1
    assert not any(e["role"] == "reviewer" and e["tool"] in {"read_result", "read_context"} for e in events(ws, "deep_tool_start"))
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    schema = next(t for t in driver.bindings["reviewer"][-1] if t["name"] == "read_content_export")
    assert "runtime" not in schema["parameters"]["properties"]
    return ws, driver, seen, result


async def current_native_access_review(ws):
    """Actual one-claim production, scoped independent check and saved Word selection."""
    import json
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent import deep_runtime
    from report_agent.store import Store
    from test_acceptance_runtime import native_access_driver
    from test_deep_runtime import invoke, observation
    # Current interface migration: same real Criterion through generation and
    # independent scoped checking, not the retired automatic whole-report grader.
    import hashlib
    from report_agent.content_store import ContentStore
    from report_agent.content_export import _bytes
    from test_bounded_review import review_call
    cs = ContentStore(ws.store)
    driver, captured, body = native_access_driver(ws)
    producer = driver.scripts["text_tool"][0]
    def freeze_saved(messages):
        page = observation(messages, "read_object_index")
        assert page["total"] == 1 and page["next_offset"] is None
        captured["node"] = page["objects"][0]["ref"]
        inputs = observation(messages, "import_source_versions")["result"]
        captured["source"] = inputs["source_refs"][0]
        return invoke("freeze_snapshot", operation_id="criterion-review-snapshot", root_ref=captured["node"],
            refs=[inputs["requirement_ref"], *inputs["source_refs"], captured["ref"], captured["node"]])
    def export(messages):
        captured["snapshot"] = observation(messages, "freeze_snapshot")["result"]["snapshot_ref"]
        return invoke("export_content_snapshot", operation_id="criterion-review-word", snapshot_ref=captured["snapshot"])
    def delegate(messages):
        captured["export"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
        requested = review_call(captured["snapshot"], {"claim": captured["node"], "k": captured["ref"]},
            id="criterion-consistency-review", reads=[captured["source"]])
        requested["args"].pop("supervision_plugin", None)
        return AIMessage(content="", tool_calls=[requested])
    def read_word(messages):
        return invoke("read_content_export", export_ref=captured["export"])
    def check_content(messages):
        actual = observation(messages, "read_content_export")
        assert actual["ok"] and body["body"]["text"] in actual["result"]["text"]
        exported = cs.read(captured["export"])
        assert exported["payload"]["snapshot_ref"] == captured["snapshot"]
        data = _bytes(ws.store, exported["payload"]["file_ref"], exported["payload"]["file_digest"])
        assert hashlib.sha256(data).hexdigest() == actual["result"]["file_digest"]
        captured["word_receipt"] = actual["receipt_id"]
        return invoke("perform_assigned_review", operation_id="criterion-consistency-check", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[])
    def route_text_tool(messages):
        packet = json.loads(messages[-1].content)
        if "assignment" not in packet:
            return producer(messages)
        assert packet["criteria"] == [cs.read(captured["ref"])]
        assert packet["criteria"][0]["payload"] == captured["payload"]
        assert packet["evidence"][0]["object"] == cs.read(captured["node"])
        assert packet["evidence"][0]["object"]["payload"] == body
        assert packet["evidence"][1]["object"] == cs.read(captured["source"])
        text = "\n".join(m.text for m in messages)
        assert "every criterion you cannot positively confirm should be marked failed" not in text
        captured["checker_observed"] = packet
        return AIMessage(content=json.dumps({"items": [{"scope_id": "rule-comparison",
            "checked_requirement_indexes": [0], "execution_state": "completed", "verdict": "satisfied",
            "observations": [{"evidence_index": 0, "locator": "saved text", "observation": "Daytime access only [s]."},
                {"evidence_index": 1, "locator": "source", "observation": "Daytime access only."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": "Scripted protocol agreement.",
                "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["Exact selected access criterion"], "unchecked": [], "blocked": [], "basis": "Same saved criterion and literal materials."},
            "reason": "Synthetic scoped agreement, not engineering approval.", "findings": []}]}))
    def select(messages):
        returned = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "task")
        assert returned.status == "success" and "Saved scoped criterion comparison." in str(returned.content)
        return invoke("select_content_delivery", operation_id="criterion-review-select", snapshot_ref=captured["snapshot"],
            export_ref=captured["export"], ending_reason="preserve_unresolved")
    def observe_status(messages):
        current = observation(messages, "content_status")["current_review"]
        assert current["items"][0]["criterion_ref"] == captured["ref"]
        assert current["items"][0]["verdict"] == "satisfied"
        assert current["overall_verdict"] is None and not current["final_review_current"]
        return AIMessage(content="Same standard verified across producer and independent scoped checker; no global approval.")
    driver.scripts["coordinator"][3:] = [invoke("read_object_index", object_type="ContentNode"), freeze_saved,
        export, delegate, select, invoke("content_status"), observe_status]
    driver.scripts["reviewer"] = [read_word, check_content, AIMessage(content="Saved scoped criterion comparison.")]
    driver.scripts["text_tool"] = [route_text_tool]
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert captured["producer_observed"] and captured["checker_observed"]
    criteria, nodes, records = cs.list_objects("Criterion"), cs.list_objects("ContentNode"), cs.list_objects("ReviewRecord")
    assert len(criteria) == len(nodes) == len(records) == 1
    assert criteria[0]["ref"] == captured["ref"] and criteria[0]["payload"] == captured["payload"]
    assert nodes[0]["payload"] == body and nodes[0]["ref"] == captured["node"]
    assert records[0]["payload"]["items"][0]["criterion_ref"] == captured["ref"]
    assert records[0]["payload"]["snapshot_ref"] == captured["snapshot"]
    with ws.store.connect() as db:
        owner, observed = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (captured["word_receipt"],)).fetchone()
    assert owner == records[0]["owner_id"]
    assert json.loads(observed)["export_ref"] == captured["export"]
    reopened = ContentStore(Store(ws.store.root))
    assert reopened.read(records[0]["ref"]) == records[0] and reopened.read(captured["ref"]) == criteria[0]
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 2
    assert not any(role == "rubric_grader" for role, _, _ in driver.calls)
    reviewer_tools = {schema["name"] for binding in driver.bindings["reviewer"] for schema in binding}
    assert not reviewer_tools.intersection({"save_acceptance_criteria", "commit_objects", "submit_review", "correct_own_review"})
    assert all(not binding for binding in driver.bindings.get("text_tool", []))
    assert ws.store.manifest["sources"][0]["content"] == "Daytime access only."
    assert not ws.store.get("content_final_review")
    return cs, driver, captured, body, result


async def historical_hierarchical_review(ws, driver):
    """Retained native-rubric-v1 component; not the current production entry point."""
    from inspect import iscoroutinefunction
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.deep_runtime import BusinessBoundary
    from report_agent.hierarchical_review import HierarchicalRubric, reconcile
    from report_agent.hierarchical_tools import content_tools, role_prompt
    from report_agent.knowledge_state import project_state

    ws.store.set("manifest", {**ws.store.manifest, "review_entrypoint": "native-rubric-v1"})
    config = {"configurable": {"thread_id": "historical-hierarchical-component"}}
    path = str(ws.store.root / "checkpoints.db")
    tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
             else StructuredTool.from_function(t) for t in content_tools(ws, "coordinator")]
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"), tools=tools,
            system_prompt=role_prompt("coordinator"), middleware=[BusinessBoundary(ws, "coordinator"),
                HierarchicalRubric(ws, driver("rubric_grader"), content_tools(ws, "rubric_grader"),
                    [BusinessBoundary(ws, "rubric_grader")])], checkpointer=saver)
        await graph.ainvoke({"messages": [HumanMessage(content="Review the selected historical delivery.")],
            "rubric": "Review the exact selected version using hierarchical-review-v1."}, config)
        state = await graph.aget_state(config)
        assert not state.next and not state.interrupts
        assert state.values["_rubric_evaluations"]
        reconcile(ws, state.values)
        result = project_state(ws)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        saved = await saver.aget_tuple(config)
        assert saved.checkpoint["channel_values"]["_rubric_evaluations"] == state.values["_rubric_evaluations"]
    assert project_state(ws) == result
    return result
