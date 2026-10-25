"""Import mechanics only; not a report-quality or model-autonomy test."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

from report_agent.catalog import Catalog
from report_agent.store import Store
from report_agent.workspace import Workspace

spec = importlib.util.spec_from_file_location("trial007", Path(__file__).parents[1] / "scripts/prepare_revision_trial007.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


@pytest.fixture
def baseline(tmp_path):
    root = tmp_path / "baseline"
    path = root / "sources" / "source.txt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"Frozen source")
    store = Store(root)
    store.initialize({"goal": "Synthetic report", "scope_instruction": {"text": "Reader scope"}, "sources": [{"id": "s", "title": "Source",
        "content": "Frozen source", "coverage": "complete", "copied_path": "sources/source.txt",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]})
    Catalog(store)
    with store.connect() as db:
        db.execute("UPDATE source_blocks SET locator='physical page 8'")
    ws = Workspace(store)
    ws.initialize()
    ws._seed("draft", "Old draft", "Candidate, not authority", ["s"])
    store.set("report_status", "reviewed_draft")
    store.set("selected_draft", ws.results()[0]["id"])
    (root / "checkpoints.db").write_bytes(b"Must not copy")
    feedback = tmp_path / "feedback.md"
    feedback.write_text("Check the draft against source", encoding="utf-8")
    return root, ws.results()[0]["id"], feedback


def test_isolated_copy_reuses_text_not_approval(baseline, tmp_path):
    root, draft_id, feedback = baseline
    original_hash = trial.file_hash(root / "state.db")
    dest = tmp_path / "revision"
    receipt = trial.prepare(root, dest, draft_id, feedback, {})
    new = Store(dest)
    assert new.get("report_status") == "ready"
    assert new.get("selected_draft") is None
    assert new.manifest["export"]["metadata"]["scope"] == "Reader scope"
    assert not (dest / "checkpoints.db").exists()
    results = Workspace(new).results()
    assert len(results) == 1 and results[0]["kind"] == "draft"
    assert results[0]["id"] != draft_id
    assert receipt["imported_draft_id"] == results[0]["id"]
    assert Catalog(new).read("s")["blocks"][0]["locator"] == "physical page 8"
    assert trial.file_hash(root / "state.db") == original_hash
    assert (dest / "sources/source.txt").read_bytes() == b"Frozen source"
    with pytest.raises(ValueError, match="NEW_ISOLATED"):
        trial.prepare(root, dest, draft_id, feedback, {})


def test_tampered_source_rejected_before_import(baseline, tmp_path):
    root, draft_id, feedback = baseline
    (root / "sources/source.txt").write_bytes(b"Changed")
    dest = tmp_path / "revision"
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        trial.prepare(root, dest, draft_id, feedback, {})
    assert not dest.exists()


def test_nested_destination_cannot_modify_baseline(baseline):
    root, draft_id, feedback = baseline
    with pytest.raises(ValueError, match="NEW_ISOLATED"):
        trial.prepare(root, root / "revision", draft_id, feedback, {})


def test_imported_draft_keeps_old_source_when_revised_after_source_change(baseline, tmp_path):
    root, draft_id, feedback = baseline
    original_hash = trial.file_hash(root / "state.db")
    dest = tmp_path / "revision"
    receipt = trial.prepare(root, dest, draft_id, feedback, {})
    ws = Workspace(Store(dest))
    imported = ws.result(receipt["imported_draft_id"])
    replacement = Catalog(ws.store).import_file("new-source.txt", b"New version", replaces_id="s")
    task = ws.request_revision(imported["id"], "Compare the original source version")
    revised = ws.submit(task["id"], actor="writer", title="Source comparison",
                        body="Historical evidence retained for review.", source_ids=["s"], input_ids=[])
    assert revised["source_ids"] == ["s"]
    assert revised["input_changes"]["source_replacements"] == {"s": replacement["source"]["id"]}
    assert ws.result(imported["id"]) == imported
    assert Catalog(ws.store).read("s")["blocks"][0]["locator"] == "physical page 8"
    assert (dest / "sources/source.txt").read_bytes() == b"Frozen source"
    assert ws.delivery(revised["id"])["status"] == "unreviewed_draft"
    assert trial.file_hash(root / "state.db") == original_hash
