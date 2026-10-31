"""Synthetic clean-import and native tool isolation, without real trial writes."""
import asyncio
import hashlib
import importlib.util
from pathlib import Path
import socket

import httpx
from langchain_core.messages import AIMessage, ToolMessage
import pytest

from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.review import load_rules
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def prepare(baseline, destination):
    path = Path(__file__).resolve().parents[1] / "scripts/prepare_clean_trial009.py"
    spec = importlib.util.spec_from_file_location("clean_trial014_importer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare(baseline, destination)


def baseline(root):
    store = Store(root)
    original = root / "sources/input.txt"
    original.parent.mkdir()
    original.write_bytes(b"Synthetic original only.")
    store.initialize({
        "goal": "Compile the synthetic original.", "scope_instruction": "Synthetic scope only.",
        "sources": [{"id": "source", "title": "Synthetic original", "filename": "input.txt",
                     "content": "Frozen extracted original.", "coverage": "complete",
                     "copied_path": "sources/input.txt",
                     "sha256": hashlib.sha256(original.read_bytes()).hexdigest()}],
        "existing_artifacts": [{"title": "OLD_OUTCOME", "body": "OLD_OUTCOME",
                                "source_ids": ["source"]}],
        "feedback": ["OLD_OUTCOME"], "export": {"metadata": {"old": "OLD_OUTCOME"}},
    })
    Catalog(store)
    workspace = Workspace(store)
    workspace.initialize()
    for key in ("report_issues", "feedback", "rubric_reviews", "rubric_targets", "delivery",
                "knowledge_project_id", "agent_summary", "checkpoint_resume"):
        store.set(key, "OLD_OUTCOME")
    store.analysis("old-analysis", {"body": "OLD_OUTCOME"})
    with store.connect() as db:
        db.execute("INSERT INTO work_items VALUES (?, ?, ?)", ("old-task", "old-task-op", encode({"body": "OLD_OUTCOME"})))
        db.execute("INSERT INTO results VALUES (?, ?, ?)", ("old-result", "old-op", encode({"body": "OLD_OUTCOME"})))
    (root / "checkpoints.db").write_bytes(b"OLD_OUTCOME")
    (root / "manual-report.md").write_text("OLD_OUTCOME")
    return store


def test_clean_import_preserves_only_originals_and_frozen_blocks(tmp_path):
    old = baseline(tmp_path / "baseline")
    with old.connect() as db:
        original_state = db.execute("SELECT * FROM state ORDER BY key").fetchall()
    destination = tmp_path / "clean"
    receipt = prepare(old.root, destination)
    fresh = Store(destination)
    with fresh.connect() as db:
        assert {k for (k,) in db.execute("SELECT key FROM state")} == {
            "manifest", "status", "report_status", "clean_import", "acceptance_default"}
        for table in ("results", "artifacts", "analyses", "work_items", "result_replacements", "source_versions"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        blocks = db.execute("SELECT * FROM source_blocks ORDER BY source_id,ordinal").fetchall()
        assert "OLD_OUTCOME" not in encode(db.execute("SELECT * FROM state").fetchall())
    with old.connect() as db:
        assert blocks == db.execute("SELECT * FROM source_blocks ORDER BY source_id,ordinal").fetchall()
        assert original_state == db.execute("SELECT * FROM state ORDER BY key").fetchall()
    assert fresh.get('acceptance_default') == 'requirement-derived-v1'
    assert set(fresh.manifest) == {"goal", "sources", "scope_instruction", "export"}
    assert fresh.manifest["sources"] == old.manifest["sources"]
    assert (destination / "sources/input.txt").read_bytes() == (old.root / "sources/input.txt").read_bytes()
    assert sorted(p.name for p in destination.iterdir()) == ["import-receipt.json", "sources", "state.db"]
    assert [event["kind"] for event in fresh.events()] == ["clean_inputs_imported"]
    assert receipt["source_blocks"] == len(blocks)
    assert all(not value for key, value in receipt.items() if key.startswith("copied_"))
    assert (old.root / "checkpoints.db").read_bytes() == b"OLD_OUTCOME"


@pytest.mark.parametrize("role", ["coordinator", "writer"])
def test_native_effective_tools_cannot_read_host_development_file(tmp_path, role):
    old = baseline(tmp_path / "baseline")
    prepare(old.root, tmp_path / "clean")
    clean = Store(tmp_path / "clean")
    # The historical importer is tested above. Reuse only verified synthetic
    # originals/OCR in a fresh native project, not its retired execution state.
    native = Store(tmp_path / "native")
    for source in clean.manifest["sources"]:
        data = (clean.root / source["copied_path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source["sha256"]
        destination = native.root / source["copied_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    native.initialize({**clean.manifest, "content_contract": "hierarchical-review-v1",
                       "review_entrypoint": "delegated-reviewer-v1"})
    Catalog(native)
    with clean.connect() as db:
        blocks = db.execute("SELECT * FROM source_blocks ORDER BY source_id,ordinal").fetchall()
    with native.connect() as db:
        db.execute("DELETE FROM source_blocks")
        db.executemany("INSERT INTO source_blocks VALUES (?,?,?,?)", blocks)
    workspace = Workspace(native)
    host_file = tmp_path / "developer-only.md"
    host_file.write_text("HOST_DEVELOPMENT_SECRET", encoding="utf-8")
    script = [invoke("read_file", file_path=str(host_file)),
              invoke("write_file", file_path="/scratch.txt", content="VIRTUAL_ONLY"),
              invoke("read_file", file_path="/scratch.txt"),
              AIMessage(content="File isolation observed; no engineering acceptance.")]
    scripts = {role: script}
    if role != "coordinator":
        scripts["coordinator"] = [invoke("task", subagent_type=role, description="Check synthetic file isolation."),
                                  AIMessage(content="Isolation investigation finished.")]
    driver = Driver(**scripts)

    async def exercise():
        result = await deep_runtime.run_report(workspace, driver)
        assert result["last_error"] is None, result

    asyncio.run(exercise())
    observations = [message for called_role, _, messages in driver.calls if called_role == role
                    for message in messages if isinstance(message, ToolMessage) and message.name == "read_file"]
    assert any("not found" in str(message.content).lower() for message in observations)
    assert any("VIRTUAL_ONLY" in str(message.content) for message in observations)
    for called_role, _, messages in driver.calls:
        assert "HOST_DEVELOPMENT_SECRET" not in str(messages)
        assert "OLD_OUTCOME" not in str(messages)
        assert any(m.type == 'system' for m in messages)
        names = {tool["name"] for binding in driver.bindings[called_role] for tool in binding}
        assert {"ls", "read_file", "write_file", "edit_file", "glob", "grep"} <= names
        assert not names & {"execute", "shell", "python", "import_file"}
    assert host_file.read_text() == "HOST_DEVELOPMENT_SECRET"
    assert not (workspace.store.root / "scratch.txt").exists()
    with native.connect() as db:
        assert db.execute("SELECT * FROM source_blocks ORDER BY source_id,ordinal").fetchall() == blocks
    assert (native.root / "sources/input.txt").read_bytes() == (clean.root / "sources/input.txt").read_bytes()
