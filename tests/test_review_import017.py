"""Offline native checkpoint fork, feedback loop and baseline-isolation checks."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3

import httpx
from langchain_core.messages import AIMessage
import pytest

from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke, observation
from test_review_feedback import select, verdict


spec = importlib.util.spec_from_file_location("review_import017",
    Path(__file__).resolve().parents[1] / "scripts/prepare_review_trial017.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("REPORT_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def save(body, replaces=""):
    return invoke("submit_result", kind="draft", title="Synthetic report", body=body,
                  source_ids=["s"], input_ids=[], replaces_id=replaces)


EARLY_IMPORT_MUTATIONS = {"feedback", "decision", "graph", "source", "error"}


def historical_import_public_fixture(tmp_path, monkeypatch):
    """Static old import format; not an executable pending native checkpoint."""
    from test_completed_feedback_recovery import historical_public_state_fixture
    workspace,draft,_ = historical_public_state_fixture(tmp_path,monkeypatch)
    store = workspace.store
    source = store.root / "sources/access.txt"
    source.rename(store.root / "sources/input.txt")
    manifest = store.manifest
    manifest["sources"][0]["copied_path"] = "sources/input.txt"
    store.set("manifest",manifest)
    store.set("acceptance_mode","legacy")
    def forbidden(*args,**kwargs):
        pytest.fail("IMPORT_PREVALIDATION_MUST_NOT_REACH_BACKUP_OR_GRAPH")
    monkeypatch.setattr(importer,"project_agent",forbidden)
    monkeypatch.setattr(importer,"backup",forbidden)
    return workspace,"not-an-executable-native-checkpoint"


def test_historical_import_public_control_does_not_claim_checkpoint_validity(tmp_path,monkeypatch):
    workspace,_ = historical_import_public_fixture(tmp_path,monkeypatch)
    before = hashes(workspace.store.root)
    _,results,blocks,sources,draft,_ = importer.inspect_baseline(workspace.store.root)
    assert results == workspace.results() and draft["id"] == workspace.store.get("delivery")["draft_id"]
    assert blocks and sources == workspace.store.manifest["sources"]
    assert hashes(workspace.store.root) == before


@pytest.fixture
async def completed(tmp_path,request,monkeypatch):
    mutation = getattr(getattr(request.node,"callspec",None),"params",{}).get("mutation")
    if mutation in EARLY_IMPORT_MUTATIONS or mutation == "post_commit":
        return historical_import_public_fixture(tmp_path,monkeypatch)

    monkeypatch.setattr(importer, "project_agent", _historical_import_agent)
    store = Store(tmp_path / "baseline")
    store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
    source = store.root / "sources/input.txt"
    source.parent.mkdir()
    source.write_bytes(b"Daytime access only.")
    store.initialize({"goal": "Compile synthetic access report.", "sources": [{
        "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
        "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
    Catalog(store)
    workspace = Workspace(store)
    workspace.initialize()
    driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                    rubric_grader=[invoke("read_review_export", limit=101),
                                   invoke("read_review_export", limit=30), verdict("satisfied")])
    result = await _historical_import_run(workspace, driver)
    assert result["status"] == "reviewed_draft", result
    async with _historical_import_agent(workspace, driver, rules=deep_runtime.load_rules()) as agent:
        checkpoints = [state async for state in agent.aget_state_history({"configurable": {"thread_id": "report"}})]
    pending = next(s for s in checkpoints if s.next == (importer.REVIEW_NODE,))
    # Inherited binding must not survive, even though this draft adopted no facts.
    store.set("knowledge_project_id", "historical-graph")
    store.set("task006_call_intent", {"model": "historical-test", "resume": False})
    (store.root / "manual-feedback.txt").write_text("MUST_NOT_IMPORT", encoding="utf-8")
    return workspace, pending.config["configurable"]["checkpoint_id"]


def hashes(root):
    return {str(path.relative_to(root)): importer.file_hash(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


async def test_fork_runs_grader_first_and_native_revision_without_touching_baseline(completed, tmp_path):
    baseline, checkpoint = completed
    before = hashes(baseline.store.root)
    # Explicit diagnostic representation migration: actual native ToolMessage/checkpoint, not duplicate DB logs.
    from test_deep_runtime import events
    rejected = events(baseline, "deep_tool_rejected")
    assert len(rejected) == 1 and rejected[0]["message"] == "PREVIEW_INVALID_RANGE"
    original_results = baseline.results()
    destination = tmp_path / "review"
    receipt = await importer.prepare(baseline.store.root, destination, checkpoint)
    assert hashes(baseline.store.root) == before
    assert receipt["model_calls"] == 0 and receipt["new_ocr"] is False
    assert receipt["graph_copied"] is False and receipt["graph_dependencies"] == 0
    assert receipt["grading_run_id"] != receipt["baseline_grading_run_id"]
    assert receipt["next"] == [importer.REVIEW_NODE]
    assert not (destination / "manual-feedback.txt").exists()
    workspace = Workspace(Store(destination))
    assert workspace.results() == original_results
    assert workspace.store.get("knowledge_enabled") is False
    assert workspace.store.get("knowledge_project_id") is None
    assert workspace.store.get("task006_call_intent") is None
    assert workspace.store.get("rubric_targets") is None
    assert workspace.store.get("rubric_reviews") is None
    assert workspace.store.get("agent_summary") is None
    assert workspace.store.get("checkpoint_resume") is True
    assert workspace.store.events()[-1]["sequence"] == receipt["historical_event_end"] + 1
    grades = []

    def grade(messages):
        grades.append(messages)
        return verdict("needs_revision", "Include the source's daytime restriction.") if len(grades) == 1 else verdict("satisfied")

    def revise(messages):
        assert "Include the source's daytime restriction." in str([m.content for m in messages])
        return save("Daytime access only [s].", original_results[0]["id"])

    driver = Driver(coordinator=[None, None, None, revise, select, AIMessage(content="Revised draft.")],
                    rubric_grader=[grade])
    result = await _historical_import_run(workspace, driver)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    assert driver.calls[0][0] == "rubric_grader"
    assert len(grades) == 2
    reviews = workspace.store.get("rubric_reviews")
    assert [r["result"] for r in reviews] == ["needs_revision", "satisfied"]
    assert {r["grading_run_id"] for r in reviews} == {receipt["grading_run_id"]}
    assert {r["target"]["reviewer_prompt_hash"] for r in reviews} == {receipt["reviewer_prompt_hash"]}
    assert reviews[0]["target"]["draft_id"] == original_results[0]["id"]
    assert reviews[1]["target"]["draft_id"] != original_results[0]["id"]
    assert len(workspace.results()) == 2
    assert hashes(baseline.store.root) == before
    assert all(not any(t["name"].startswith("knowledge_") for t in tools)
               for bindings in driver.bindings.values() for tools in bindings)


@pytest.mark.parametrize("mutation,error", [
    ("feedback", "HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED"),
    ("decision", "HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED"),
    ("graph", "GRAPH_DEPENDENT_RESULTS"),
    ("source", "BASELINE_SOURCE_HASH_MISMATCH"),
    ("error", "BASELINE_HAS_UNRESOLVED_EXECUTION_STATE"),
    ("post_commit", "BUSINESS_OR_ERROR_EVENT_AFTER_REVIEW_BOUNDARY"),
])
async def test_refuses_unsafe_imports_without_baseline_changes(completed, tmp_path, mutation, error):
    workspace, checkpoint = completed
    if mutation == "post_commit":
        # Explicit migration: actual historical event-audit predicate, not a
        # claim that the retired pending-checkpoint import graph can execute.
        state, _, _, _, draft, _ = importer.inspect_baseline(workspace.store.root)
        run_id = "dated-static-event-boundary"
        target = {"draft_id": draft["id"],
            "draft_body_sha256": hashlib.sha256(draft["body"].encode()).hexdigest()}
        workspace.store.set("rubric_targets", {run_id + ":0": target})
        workspace.store.event("rubric_review_started", {"key": run_id + ":0",
            "fixture_only": True, "executed": False})
        state, _, _, _, draft, _ = importer.inspect_baseline(workspace.store.root)
        clean = hashes(workspace.store.root)
        boundary = importer.review_event_boundary(workspace.store.root, run_id, state, draft)
        assert isinstance(boundary, int) and boundary >= 0
        assert hashes(workspace.store.root) == clean
        workspace.store.event("result_committed", {"id": "later-write"})
        before = hashes(workspace.store.root)
        with pytest.raises(ValueError, match=error):
            importer.review_event_boundary(workspace.store.root, run_id, state, draft)
        assert hashes(workspace.store.root) == before
        assert not (tmp_path / "review").exists()
        return
    if mutation == "feedback":
        workspace.store.set("feedback", [{"origin": "operator", "message": "Manual answer"}])
    elif mutation == "decision":
        workspace.store.event("human_decision", {"decision": "Manual answer"})
    elif mutation == "graph":
        result = workspace.results()[0]
        result["fact_ids"] = ["external-fact"]
        with workspace.store.connect() as db:
            db.execute("UPDATE results SET data=? WHERE id=?", (encode(result), result["id"]))
    elif mutation == "source":
        (workspace.store.root / "sources/input.txt").write_text("Changed")
    elif mutation == "error":
        workspace.store.set("report_error", {"type": "Unknown"})
    else:
        workspace.store.event("result_committed", {"id": "later-write"})
    before = hashes(workspace.store.root)
    with pytest.raises(ValueError, match=error):
        await importer.prepare(workspace.store.root, tmp_path / "review", checkpoint)
    assert hashes(workspace.store.root) == before
    if mutation in EARLY_IMPORT_MUTATIONS:
        assert not (tmp_path / "review").exists()


async def test_refuses_existing_destination_invalid_checkpoint_and_live_baseline(completed, tmp_path):
    import fcntl

    workspace, checkpoint = completed
    existing = tmp_path / "existing"
    existing.mkdir()
    for target in (existing, workspace.store.root / "nested", workspace.store.root):
        with pytest.raises(ValueError, match="NEW_ISOLATED_DESTINATION_REQUIRED"):
            await importer.prepare(workspace.store.root, target, checkpoint)
    with (workspace.store.root / "run.lock").open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="BASELINE_ALREADY_RUNNING"):
            await importer.prepare(workspace.store.root, tmp_path / "live", checkpoint)
    before = hashes(workspace.store.root)
    with pytest.raises(ValueError, match="PRISTINE_PENDING_NATIVE_REVIEW_CHECKPOINT_REQUIRED"):
        await importer.prepare(workspace.store.root, tmp_path / "invalid", "not-a-checkpoint")
    assert hashes(workspace.store.root) == before


def test_sqlite_snapshot_preserves_committed_wal_without_original_sidecar_writes(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    source = root / "state.db"
    db = sqlite3.connect(source)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('committed in WAL')")
        db.commit()
        assert source.with_name("state.db-wal").stat().st_size > 0
        before = hashes(root)
        target = tmp_path / "copied.db"
        importer.backup(source, target)
        with sqlite3.connect(target) as copied:
            assert copied.execute("SELECT value FROM evidence").fetchone()[0] == "committed in WAL"
        assert hashes(root) == before
    finally:
        db.close()


from contextlib import asynccontextmanager


@asynccontextmanager
async def _historical_import_agent(workspace, model_factory, *, rules=""):
    """Read-only construction of the real historical import topology, not current admission."""
    from inspect import iscoroutinefunction
    from langchain.agents import create_agent
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review
    tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
             else StructuredTool.from_function(t)
             for t in deep_runtime.business_tools(workspace, "coordinator", None, None)]
    middleware = native_review(workspace, model_factory("rubric_grader"), [], rules,
        middleware=[deep_runtime.BusinessBoundary(workspace, "rubric_grader")])
    async with AsyncSqliteSaver.from_conn_string(str(workspace.store.root / "checkpoints.db")) as saver:
        graph = create_agent(model=model_factory("coordinator"), tools=tools,
            system_prompt=deep_runtime.COORDINATOR,
            middleware=[TodoListMiddleware(), deep_runtime.BusinessBoundary(workspace, "coordinator"), middleware],
            checkpointer=saver, name="report_coordinator")
        graph.report_review_middleware = middleware
        yield graph


async def _historical_import_run(workspace, driver):
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command
    from report_agent.review import reconcile_review, reviewer_prompt
    from report_agent.knowledge_state import project_state
    from report_agent.store import digest
    with workspace.store.run_lock():
        workspace.initialize()
        rules = deep_runtime.load_rules()
        workspace.store.set("active_rubric_hash", digest(rules))
        workspace.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
        config = {"configurable": {"thread_id": "report"}}
        async with _historical_import_agent(workspace, driver, rules=rules) as graph:
            before = await graph.aget_state(config)
            payload = Command(update={"rubric": rules}) if before.next else {
                "messages": [HumanMessage(content=encode(deep_runtime.project_view(workspace)))], "rubric": rules}
            await graph.ainvoke(payload, config)
            state = await graph.aget_state(config)
            assert not state.next and not state.interrupts
            reconcile_review(workspace, state.values)
            workspace.store.set("checkpoint_resume", bool(state.next))
            workspace.store.set("native_interrupts", [{"id": i.id, "value": i.value} for i in state.interrupts])
            return project_state(workspace)
