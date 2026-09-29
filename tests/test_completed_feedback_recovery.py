"""Synthetic offline completed-state recovery; no real report or semantic-model claims."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import sys

import httpx
from langchain_core.messages import AIMessage, HumanMessage
import pytest

from report_agent import deep_runtime
from report_agent.acceptance import active_criteria, criteria_rules
from report_agent.catalog import Catalog
from report_agent.knowledge_state import project_state
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_acceptance_runtime import save_standards, save_draft, select, verdict
from test_deep_runtime import Driver, invoke


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("prepare_review_trial017", SCRIPTS / "prepare_review_trial017.py")
primitives = importlib.util.module_from_spec(spec)
sys.modules.setdefault("prepare_review_trial017", primitives)
spec.loader.exec_module(primitives)
spec = importlib.util.spec_from_file_location("completed_recovery", SCRIPTS / "prepare_completed_feedback_recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("REPORT_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("NETWORK_OR_CONFIGURED_MODEL_FORBIDDEN")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(deep_runtime, "configured_model", forbidden)


@pytest.fixture
async def completed(tmp_path):
    store = Store(tmp_path / "baseline")
    source = store.root / "sources/access.txt"
    source.parent.mkdir()
    source.write_bytes(b"Daytime access only.")
    store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
        "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
        "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
    store.set("knowledge_enabled", False)
    Catalog(store)
    workspace = Workspace(store)
    driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                 select, AIMessage(content="Saved synthetic draft.")],
                    rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
    result = await deep_runtime.run_report(workspace, driver)
    assert result["status"] == "reviewed_draft", result
    draft = next(r for r in workspace.results() if r["kind"] == "draft")
    feedback = tmp_path / "feedback.txt"
    feedback.write_text("The source says daytime only; assess the report's unrestricted-access claim and its consequences.",
                        encoding="utf-8")
    (store.root / "trial-freeze.json").write_text('{"fixture":"completed synthetic trial"}', encoding="utf-8")
    return workspace, draft, feedback


def arguments(completed, destination):
    workspace, draft, feedback = completed
    return (workspace.store.root, destination, feedback, draft["id"],
            hashlib.sha256(draft["body"].encode()).hexdigest())


async def test_completed_copy_receives_feedback_and_normal_new_run_revises_with_fresh_review(completed, tmp_path):
    baseline, original, feedback = completed
    original_tree = recovery.tree_hashes(baseline.store.root)
    original_results = baseline.results()
    original_reviews = baseline.store.get("rubric_reviews")
    destination = tmp_path / "recovery"
    receipt = await recovery.prepare(*arguments(completed, destination))
    assert recovery.tree_hashes(baseline.store.root) == original_tree
    workspace = Workspace(Store(destination))
    assert workspace.results() == original_results
    assert workspace.store.get("rubric_reviews") == original_reviews
    assert workspace.store.get("checkpoint_resume") is False
    assert workspace.store.get("feedback") is None
    assert receipt["state_keys_changed"] == ["corrections"]
    assert receipt["review_projection_before"] == "reviewed_draft"
    assert receipt["review_projection_after"] == "needs_attention"
    assert receipt["checkpoint"]["next"] == [] and receipt["checkpoint"]["interrupt_count"] == 0
    assert receipt["model_calls"] == 0
    assert recovery.file_hash(destination / "checkpoints.db") == receipt["copied_checkpoint_sha256"]
    assert (destination / "trial-freeze.json").read_bytes() == (baseline.store.root / "trial-freeze.json").read_bytes()
    assert project_state(workspace)["status"] == "needs_attention"
    description = workspace.store.get("corrections")[0]["description"]
    assert description == recovery.PREFIX + feedback.read_text()
    for change in receipt["path_changes"]:
        assert Path(change["new"]).is_relative_to(destination)
        assert Path(change["new"]).is_file()
    received, graded = [], []

    def inspect_new_call(messages):
        newest = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        current = json.loads(newest.content)
        assert any(c["description"] == description and c["result_id"] == original["id"]
                   for c in current["corrections"])
        received.append(True)
        return invoke("read_source_page", source_id="s")

    def grade(messages):
        text = str([m.content for m in messages])
        assert description in text or "read_review_context" in text
        graded.append(True)
        return verdict(workspace, ["satisfied"])

    # Retained synthetic history has four coordinator AI messages. Test the new
    # invocation and immutable replacement, not any required business-tool plan.
    driver = Driver(coordinator=[None] * 4 + [inspect_new_call,
                    save_draft(workspace, "Daytime access only [s].", original["id"]), select,
                    AIMessage(content="Saved corrected synthetic report.")], rubric_grader=[grade])
    result = await deep_runtime.run_report(workspace, driver)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    assert driver.calls[0][0] == "coordinator" and received and graded
    new_reviews = workspace.store.get("rubric_reviews")
    assert new_reviews[:-1] == original_reviews
    assert new_reviews[-1]["grading_run_id"] != original_reviews[-1]["grading_run_id"]
    assert new_reviews[-1]["iteration"] == 0
    replacement = workspace.result(result["delivery"]["draft_id"])
    assert replacement["id"] != original["id"] and replacement["replaces_id"] == original["id"]
    assert replacement["body"] == "Daytime access only [s]."
    assert new_reviews[-1]["target"]["draft_id"] == replacement["id"]
    assert workspace.result(original["id"]) == original
    assert [r for r in workspace.results() if r["kind"] == "acceptance"] == [
        r for r in original_results if r["kind"] == "acceptance"]
    assert workspace.store.get("corrections")[0]["status"] == "addressed"
    assert recovery.tree_hashes(baseline.store.root) == original_tree


@pytest.mark.parametrize("mutation,error", [
    ("hash", "DRAFT_BODY_HASH_MISMATCH"),
    ("target", "EXACT_SELECTED_DRAFT_REQUIRED"),
    ("source", "SOURCE_HASH_MISMATCH"),
    ("foreign_source_path", "SOURCE_PATH_NOT_PROJECT_BOUND"),
    ("graph", "REQUIREMENT_ACCEPTANCE_WITHOUT_GRAPH_REQUIRED"),
    ("resume", "COMPLETED_SUCCESSFUL_BASELINE_REQUIRED"),
    ("interrupt", "COMPLETED_SUCCESSFUL_BASELINE_REQUIRED"),
    ("error", "COMPLETED_SUCCESSFUL_BASELINE_REQUIRED"),
    ("standard", "EXACT_HISTORICAL_SATISFIED_REVIEW_REQUIRED"),
    ("preview", "PREVIEW_PATH_NOT_BASELINE_BOUND"),
])
async def test_refuses_unsafe_preparation_without_changing_baseline(completed, tmp_path, mutation, error):
    workspace, draft, feedback = completed
    args = list(arguments(completed, tmp_path / "refused"))
    if mutation == "hash":
        args[-1] = "0" * 64
    elif mutation == "target":
        args[-2] = "different-draft"
    elif mutation == "source":
        (workspace.store.root / "sources/access.txt").write_text("Changed.")
    elif mutation == "foreign_source_path":
        manifest = workspace.store.manifest
        manifest["sources"][0]["copied_path"] = "../outside.txt"
        workspace.store.set("manifest", manifest)
    elif mutation == "graph":
        draft["fact_ids"] = ["unavailable-graph-fact"]
        with workspace.store.connect() as db:
            db.execute("UPDATE results SET data=? WHERE id=?", (encode(draft), draft["id"]))
    elif mutation in {"resume", "interrupt", "error"}:
        key, value = {"resume": ("checkpoint_resume", True), "interrupt": ("native_interrupts", [{"id": "pending"}]),
                      "error": ("report_error", {"type": "Unresolved"})}[mutation]
        workspace.store.set(key, value)
    elif mutation == "standard":
        record = next(r for r in workspace.results() if r["kind"] == "acceptance")
        body = json.loads(record["body"])
        body["criteria"][0]["condition"] = "Different standard."
        record["body"] = encode(body)
        with workspace.store.connect() as db:
            db.execute("UPDATE results SET data=? WHERE id=?", (encode(record), record["id"]))
    else:
        path = next((workspace.store.root / "previews").glob("*/summary.json"))
        data = json.loads(path.read_text())
        data["docx"]["path"] = str(tmp_path / "foreign/report.docx")
        path.write_text(encode(data))
    before = recovery.tree_hashes(workspace.store.root)
    with pytest.raises(ValueError, match=error):
        await recovery.prepare(*args)
    assert recovery.tree_hashes(workspace.store.root) == before


async def test_native_pending_checkpoint_is_refused_even_when_public_flags_say_complete(completed, tmp_path):
    workspace, _, _ = completed
    async with deep_runtime.project_agent(workspace, lambda role: recovery.NoCallModel(),
                                         rules=criteria_rules(active_criteria(workspace))) as agent:
        await agent.aupdate_state({"configurable": {"thread_id": "report"}}, {},
                                  as_node="TodoListMiddleware.after_model")
    before = recovery.tree_hashes(workspace.store.root)
    target = tmp_path / "pending"
    with pytest.raises(ValueError, match="TERMINAL_CHECKPOINT_REQUIRED"):
        await recovery.prepare(*arguments(completed, target))
    assert recovery.tree_hashes(workspace.store.root) == before
    assert (target / "feedback-recovery-incomplete.json").is_file()
    assert not (target / "feedback-recovery-receipt.json").exists()


async def test_existing_nested_live_and_symlink_destinations_are_refused(completed, tmp_path):
    import fcntl

    workspace, _, _ = completed
    existing = tmp_path / "existing"
    existing.mkdir()
    for destination in (existing, workspace.store.root, workspace.store.root / "child", tmp_path):
        with pytest.raises(ValueError, match="NEW_ISOLATED_DESTINATION_REQUIRED"):
            await recovery.prepare(*arguments(completed, destination))
    parent = tmp_path / "link"
    parent.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match="SYMLINK_OR_JUNCTION_NOT_ALLOWED"):
        await recovery.prepare(*arguments(completed, parent / "new"))
    with (workspace.store.root / "run.lock").open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="BASELINE_ALREADY_RUNNING"):
            await recovery.prepare(*arguments(completed, tmp_path / "live"))


def test_backup_reads_committed_wal_without_creating_baseline_sidecars(tmp_path):
    baseline = tmp_path / "wal"
    baseline.mkdir()
    source = baseline / "state.db"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('committed in WAL')")
        db.commit()
        before = recovery.tree_hashes(baseline)
        recovery.backup(source, tmp_path / "copied.db")
        with sqlite3.connect(tmp_path / "copied.db") as copied:
            assert copied.execute("SELECT value FROM evidence").fetchone()[0] == "committed in WAL"
        assert recovery.tree_hashes(baseline) == before
