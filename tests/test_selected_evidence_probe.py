"""Public candidate import isolation; no paid call or legacy implementation use."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_selected_evidence_probe as probe
from report_agent.acceptance import active_criteria, bind_mode, save_criteria
from report_agent.store import Store
from report_agent.workspace import Workspace


def test_import_preserves_definitions_and_body_but_excludes_verdict_and_history(tmp_path, monkeypatch):
    baseline, destination = tmp_path / "baseline", tmp_path / "probe"
    store = Store(baseline)
    manifest = {"goal": "Compile the count.", "sources": [{"id": "s", "title": "Count",
                                "content": "Count: 7.", "coverage": "complete"}]}
    store.initialize(manifest)
    ws = Workspace(store)
    ws.initialize()
    bind_mode(ws)
    standard = save_criteria(ws, actor="coordinator", title="Count standard", criteria=[{
        "condition": "Report the known count accurately.", "requirement_refs": ["commission"]}],
        source_ids=["s"], input_ids=[], reason="Fixture standard.")
    task = ws.request_task("draft", "Compile", [])
    draft = ws.submit(task["id"], actor="writer", title="Count", body="Count: 7.",
                      source_ids=["s"], input_ids=[standard["id"]])
    ws.select_delivery(draft["id"], "")
    store.set("rubric_reviews", [{"explanation": "DO_NOT_IMPORT_VERDICT"}])
    store.event("deep_model_response", {"content": "DO_NOT_IMPORT_HISTORY"})
    original = ws.results()

    def clean_inputs_only(source, target):
        assert source == baseline
        if target.exists():
            raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
        target.mkdir()
        target_store = Store(target)
        target_store.initialize(manifest)
        Workspace(target_store).initialize()
        return {"copied_results": False, "copied_reviews": False}

    monkeypatch.setattr(probe, "prepare", clean_inputs_only)
    imported = probe.prepare_candidate(baseline, destination, draft["id"])
    assert len(imported.results()) == 2
    new_draft = next(r for r in imported.results() if r["kind"] == "draft")
    assert new_draft["body"] == draft["body"] and new_draft["id"] != draft["id"]
    assert new_draft["input_ids"] == [active_criteria(imported)["id"]]
    receipt = json.loads((destination / "candidate-import.json").read_text())
    assert receipt["criterion_definitions_unchanged"]
    assert not receipt["imported_prior_verdict"] and not receipt["imported_author_history"]
    assert imported.store.get("rubric_reviews") is None
    assert "DO_NOT_IMPORT" not in str(imported.store.events())
    assert ws.results() == original
    with pytest.raises(ValueError, match="NEW_ISOLATED"):
        probe.prepare_candidate(baseline, destination, draft["id"])
