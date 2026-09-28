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


@pytest.fixture
async def completed(tmp_path):
    store = Store(tmp_path / "baseline")
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
    result = await deep_runtime.run_report(workspace, driver)
    assert result["status"] == "reviewed_draft", result
    async with deep_runtime.project_agent(workspace, driver, rules=deep_runtime.load_rules()) as agent:
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
    rejected = [e["data"] for e in baseline.store.events() if e["kind"] == "deep_tool_rejected"]
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
    result = await deep_runtime.run_report(workspace, driver)
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
