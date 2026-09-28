"""Effective native prompt/entry/version tests, with no network or private inputs."""
from langchain_core.messages import AIMessage, SystemMessage
from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT

from report_agent import deep_runtime
from report_agent.review import reviewer_prompt, review_delivery
from report_agent.store import digest
from test_deep_runtime import Driver
from test_review_feedback import ws, no_network, save, select, verdict


async def test_effective_native_prompt_and_single_review_entry(ws):
    def inspect(messages):
        system = next(m for m in messages if isinstance(m, SystemMessage)).text
        assert reviewer_prompt() in system
        assert GRADER_SYSTEM_PROMPT in system
        assert "# Report review responsibility" in system
        # Capabilities are verified from the bound tool schemas below; the role
        # prompt need not name or prescribe any particular tool.
        return verdict("satisfied")

    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                    rubric_grader=[inspect])
    result = await deep_runtime.run_report(ws, driver)
    assert result["status"] == "reviewed_draft", result
    assert "reviewer" not in driver.created
    grader_tools = {s["name"] for s in driver.bindings["rubric_grader"][-1]}
    assert {"read_result", "read_review_export", "search_sources", "calculate", "analyze_source_image"} <= grader_tools
    assert not {"submit_result", "knowledge_put", "ask_human", "task", "request_correction"} & grader_tools
    task = next(t for t in driver.bindings["coordinator"][-1] if t["name"] == "task")
    assert "reviewer" not in task["description"]
    record = ws.store.get("rubric_reviews")[0]
    assert record["target"]["reviewer_prompt_hash"] == digest(reviewer_prompt())


async def test_old_prompt_acceptance_is_historical_not_current_acceptance(ws, monkeypatch):
    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                    rubric_grader=[verdict("satisfied")])
    await deep_runtime.run_report(ws, driver)
    draft = ws.store.get("delivery")["draft_id"]
    records = ws.store.get("rubric_reviews")
    assert review_delivery(ws, draft)["status"] == "reviewed_draft"
    ws.store.set("active_reviewer_prompt_hash", digest("another role version"))
    assert review_delivery(ws, draft)["status"] == "unreviewed_draft"
    assert ws.store.get("rubric_reviews") == records


async def test_generic_historical_acceptance_does_not_skip_new_native_reviewer(ws):
    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                    rubric_grader=[verdict("satisfied")])
    await deep_runtime.run_report(ws, driver)
    records = ws.store.get("rubric_reviews")
    records[0]["target"].pop("reviewer_prompt_hash")
    ws.store.set("rubric_reviews", records)
    # The completed checkpoint can begin a new native run; its old messages remain.
    driver.scripts["coordinator"].append(AIMessage("Review the selected saved draft."))
    result = await deep_runtime.run_report(ws, driver)
    assert result["status"] == "reviewed_draft", result
    assert len(ws.store.get("rubric_reviews")) == 2
    assert len({r["grading_run_id"] for r in ws.store.get("rubric_reviews")}) == 2
    assert "reviewer_prompt_hash" not in ws.store.get("rubric_reviews")[0]["target"]


async def test_disabled_graph_production_path_uses_saved_results_without_graph(ws, monkeypatch):
    from report_agent import knowledge
    ws.store.set("knowledge_enabled", False)
    ws.store.set("knowledge_project_id", "historical-namespace-never-open")

    def forbidden(*args, **kwargs):
        raise AssertionError("Graph must remain disconnected")

    monkeypatch.setattr(knowledge, "Knowledge", forbidden)
    driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                    rubric_grader=[verdict("satisfied")])
    monkeypatch.setattr(deep_runtime, "configured_model", lambda store, role: driver(role))
    result = await deep_runtime.run_report(ws)
    assert result["status"] == "reviewed_draft", result
    assert result["delivery"]["knowledge"]["status"] == "not_used"
    for bindings in driver.bindings.values():
        for schemas in bindings:
            assert not any(s["name"].startswith("knowledge_") for s in schemas)


def test_disabled_graph_does_not_erase_or_approve_existing_fact_dependencies(ws, monkeypatch):
    from report_agent.knowledge_state import inspect_evidence
    ws.store.set("knowledge_enabled", False)
    monkeypatch.setattr(ws, "collect_fact_ids", lambda ids: ["adopted-fact"])
    result = inspect_evidence(ws, ["draft"])
    assert result["status"] == "unknown"
    assert result["fact_ids"] == ["adopted-fact"]
