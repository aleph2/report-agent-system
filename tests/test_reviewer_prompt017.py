"""Effective native prompt/entry/version tests, with no network or private inputs."""
from langchain_core.messages import AIMessage, SystemMessage
from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT

from report_agent import deep_runtime
from report_agent.review import reviewer_prompt, review_delivery
from report_agent.store import digest
from test_deep_runtime import Driver
from test_review_feedback import ws, no_network, save, select, verdict


def _current_scoped_review_protocol(tmp_path):
    """Literal inputs and scripted judgment; no report-quality claim."""
    import json
    from report_agent.bounded_review import ORGANIZER_PROMPT, TOOL_PROMPT, Assessments
    from report_agent.content_store import ContentStore
    from report_agent.task_supervision import ReviewRequirement
    from test_task_supervision import ws as native_fixture
    from test_bounded_review import review_call
    from test_hierarchical_content import seed
    from test_deep_runtime import invoke, observation
    ws = native_fixture.__wrapped__(tmp_path)
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    assigned = review_call(snapshot, refs, reads=[source])
    assigned["args"].pop("supervision_plugin", None)
    observed = {}
    def perform(messages):
        actual = observation(messages, "read_task_assignment")
        assert actual["ok"] is True
        assert actual["assignment"]["review_snapshot_ref"] == snapshot
        assert actual["assignment"] == cs.read({"type": "DelegatedTask", "id": actual["task_id"], "version": 1})["payload"]
        assert [ReviewRequirement.model_validate(r).model_dump() for r in actual["assignment"]["review_requirements"]] == [
            ReviewRequirement.model_validate(r).model_dump() for r in assigned["args"]["review_requirements"]]
        system = "\n".join(m.text for m in messages if isinstance(m, SystemMessage))
        from report_agent.hierarchical_tools import role_prompt
        from report_agent.prompt_sources import role_sources
        assert role_sources('reviewer', 'report-expression-v1', 'review-interfaces-v1') == ['agent-common', 'agent-reviewer']
        expected = role_prompt('reviewer')
        if expected:
            assert system.startswith(expected)
        assert ORGANIZER_PROMPT not in system and GRADER_SYSTEM_PROMPT not in system
        observed["organizer"] = system
        return invoke("perform_assigned_review", operation_id="effective-prompt-check", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[])
    def checker(messages):
        system = "\n".join(m.text for m in messages if isinstance(m, SystemMessage))
        assert TOOL_PROMPT in system
        packet = json.loads(messages[-1].content)
        assert packet["criteria"] == [cs.read(refs["k"])]
        assert packet["commission"]["goal"] == ws.store.manifest["goal"]
        assert packet["evidence"][0]["object"] == cs.read(refs["claim"])
        assert packet["evidence"][1]["object"] == cs.read(source)
        assert packet["output_schema"] == Assessments.model_json_schema()
        observed.update(checker_system=system, packet=packet)
        return AIMessage(content=json.dumps({"items": [{"scope_id": "rule-comparison",
            "checked_requirement_indexes": [0], "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": 0, "locator": "claim", "observation": "Synthetic target observed."},
                {"evidence_index": 1, "locator": "source", "observation": "Synthetic source observed."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed", "result": "Protocol finding.",
                "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["Synthetic comparison"], "unchecked": [], "blocked": [], "basis": "Literal fixture."},
            "reason": "Scripted protocol negative, not engineering validation.", "findings": []}]}))
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[assigned]), AIMessage(content="Scoped finding retained.")],
        reviewer=[invoke("read_task_assignment"), perform, AIMessage(content="Independent checker finding saved.")],
        text_tool=[checker])
    return ws, cs, refs, snapshot, driver, observed


async def test_effective_native_prompt_and_single_review_entry(tmp_path):
    # Explicit migration: one current Reviewer organizer and one independent
    # checker, rather than the retired automatic rubric grader identity.
    from report_agent.bounded_review import TOOL_PROMPT
    ws, cs, refs, _, driver, observed = _current_scoped_review_protocol(tmp_path)
    originals = cs.list_objects("ContentNode"), cs.list_objects("Criterion")
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    from report_agent.hierarchical_tools import role_prompt
    assert observed['organizer'] == role_prompt('reviewer')
    assert observed['checker_system'] == TOOL_PROMPT
    assert not any(role == "rubric_grader" for role, _, _ in driver.calls)
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    reviewer_tools = {s["name"] for s in driver.bindings["reviewer"][-1]}
    assert {"read_task_assignment", "read_context", "perform_assigned_review", "calculate"} <= reviewer_tools
    assert not {"submit_review", "correct_own_review", "submit_result", "knowledge_put", "ask_human", "task"} & reviewer_tools
    assert all(not binding for binding in driver.bindings.get("text_tool", []))
    records, tasks = cs.list_objects("ReviewRecord"), cs.list_objects("DelegatedTask")
    assert len(records) == len(tasks) == 1
    record = records[0]
    assert record["task_id"] == tasks[0]["ref"]["id"]
    assert record["owner_id"] == "content:reviewer:" + record["task_id"]
    identity = record["payload"]["runtime_identity"]
    assert identity["mode"] == "bounded-review-v1" and identity["prompt_hash"] == digest(TOOL_PROMPT)
    assert identity["request_hash"] == digest({"input": observed["packet"], "model": identity["model"],
        "system": TOOL_PROMPT, "contract": "assigned-review-v6"})
    assert (cs.list_objects("ContentNode"), cs.list_objects("Criterion")) == originals
    assert not ws.store.get("content_final_review")


async def test_old_prompt_acceptance_is_historical_not_current_acceptance(tmp_path, monkeypatch):
    # Explicit dated stored-projection fixture; this does not claim a native
    # runtime execution or global invalidation of current scoped ReviewRecords.
    from test_completed_feedback_recovery import historical_standard_projection_fixture
    ws, historical_draft, _ = historical_standard_projection_fixture(tmp_path, monkeypatch)
    draft = historical_draft["id"]
    records = ws.store.get("rubric_reviews")
    assert review_delivery(ws, draft)["status"] == "reviewed_draft"
    ws.store.set("active_reviewer_prompt_hash", digest("another role version"))
    assert review_delivery(ws, draft)["status"] == "unreviewed_draft"
    assert ws.store.get("rubric_reviews") == records

async def test_generic_historical_acceptance_does_not_skip_new_native_reviewer(ws):
    # Explicit retained historical middleware with a real persistent checkpoint.
    # A new human invocation triggers the native terminal-run reset; no claim
    # that missing prompt identity itself triggers current production regrading.
    import hashlib
    from copy import deepcopy
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review, reconcile_review
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    task = ws.request_task("draft", "Dated historical prompt identity fixture", [])
    draft = ws.submit(task["id"], actor="writer", title="Synthetic report", body="Daytime access only [s].",
        source_ids=["s"], input_ids=[])
    ws.select_delivery(draft["id"], "")
    originals = deepcopy(ws.results()), deepcopy(ws.tasks()), deepcopy(ws.store.manifest["sources"])
    commits = deepcopy([e for e in ws.store.events() if e["kind"] == "result_committed"])
    rules = deep_runtime.load_rules()
    ws.store.set("active_rubric_hash", digest(rules))
    ws.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
    path = str(ws.store.root / "historical-prompt-identity.db")
    config = {"configurable": {"thread_id": "historical-prompt-identity"}}
    driver = Driver(coordinator=[AIMessage(content="Review the selected historical report once.")],
        rubric_grader=[verdict("satisfied")])
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"),
            middleware=[native_review(ws, driver("rubric_grader"), [], rules)], checkpointer=saver)
        await graph.ainvoke({"messages": [HumanMessage(content="Assess the saved historical draft.")], "rubric": rules}, config)
        first = await graph.aget_state(config)
        assert not first.next and not first.interrupts and first.values["_rubric_status"] == "satisfied"
        reconcile_review(ws, first.values)
    assert review_delivery(ws, draft["id"])["status"] == "reviewed_draft"
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1
    # Preserve the exact original historical-record mutation.
    records[0]["target"].pop("reviewer_prompt_hash")
    ws.store.set("rubric_reviews", records)
    generic_record = deepcopy(records[0])
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(coordinator=[AIMessage(content="Unused old step"), AIMessage(content="Explicitly review the same historical draft again.")],
        rubric_grader=[verdict("satisfied")])
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=fresh("coordinator"),
            middleware=[native_review(reopened, fresh("rubric_grader"), [], rules)], checkpointer=saver)
        stored = await graph.aget_state(config)
        assert stored.values["_rubric_evaluations"] == first.values["_rubric_evaluations"]
        await graph.ainvoke({"messages": [HumanMessage(content="New explicit assessment of the selected saved draft.")],
            "rubric": rules}, config)
        final = await graph.aget_state(config)
        assert not final.next and not final.interrupts and final.values["_rubric_status"] == "satisfied"
        reconcile_review(reopened, final.values)
    reviews = reopened.store.get("rubric_reviews")
    assert len(reviews) == 2 and len({r["grading_run_id"] for r in reviews}) == 2
    assert reviews[0] == generic_record and "reviewer_prompt_hash" not in reviews[0]["target"]
    assert reviews[1]["target"]["reviewer_prompt_hash"] == digest(reviewer_prompt())
    assert [r["iteration"] for r in reviews] == [0, 0]
    for r in reviews:
        assert r["target"]["draft_id"] == draft["id"]
        assert r["target"]["draft_body_sha256"] == hashlib.sha256(draft["body"].encode()).hexdigest()
        assert r["target"]["preview_version"] == reviews[0]["target"]["preview_version"]
        assert r["target"]["docx_sha256"] == reviews[0]["target"]["docx_sha256"]
    assert review_delivery(reopened, draft["id"])["status"] == "reviewed_draft"
    assert [r for r, _, _ in driver.calls] == ["coordinator", "rubric_grader"]
    assert [r for r, _, _ in fresh.calls] == ["coordinator", "rubric_grader"]
    assert fresh.calls[0][:2] == ("coordinator", 1)
    reconcile_review(reopened, final.values)
    assert reopened.store.get("rubric_reviews") == reviews
    assert (reopened.results(), reopened.tasks(), reopened.store.manifest["sources"]) == originals
    assert [e for e in reopened.store.events() if e["kind"] == "result_committed"] == commits


async def test_disabled_graph_production_path_uses_saved_results_without_graph(tmp_path, monkeypatch):
    from report_agent import knowledge
    ws, cs, _, _, driver, observed = _current_scoped_review_protocol(tmp_path)
    ws.store.set("knowledge_enabled", False)
    ws.store.set("knowledge_project_id", "historical-namespace-never-open")
    def forbidden(*args, **kwargs):
        raise AssertionError("Graph must remain disconnected")
    monkeypatch.setattr(knowledge, "Knowledge", forbidden)
    configured = []
    def fake_configured(store, role):
        assert store.root == ws.store.root
        configured.append(role)
        return driver(role)
    monkeypatch.setattr(deep_runtime, "configured_model", fake_configured)
    # Real default factory selection path, with fake services; not a live-provider test.
    result = await deep_runtime.run_report(ws)
    assert result["last_error"] is None, result
    assert "coordinator" in configured and "reviewer" in configured and "text_tool" in configured
    assert observed["packet"] and len(cs.list_objects("ReviewRecord")) == 1
    assert ws.store.get("knowledge_project_id") == "historical-namespace-never-open"
    for bindings in driver.bindings.values():
        for schemas in bindings:
            assert not any(s["name"].startswith("knowledge_") for s in schemas)
    assert not ws.store.get("content_final_review")


def test_disabled_graph_does_not_erase_or_approve_existing_fact_dependencies(ws, monkeypatch):
    from report_agent.knowledge_state import inspect_evidence
    ws.store.set("knowledge_enabled", False)
    monkeypatch.setattr(ws, "collect_fact_ids", lambda ids: ["adopted-fact"])
    result = inspect_evidence(ws, ["draft"])
    assert result["status"] == "unknown"
    assert result["fact_ids"] == ["adopted-fact"]
