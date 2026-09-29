"""Diagnostic isolation and version binding; no model-quality claims."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_acceptance_boundary_diagnostic as diagnostic
from report_agent.acceptance import active_criteria
from report_agent.review import FeedbackRubric, reviewer_prompt
from report_agent.store import Store, digest
from report_agent.workspace import Workspace


def fixture_data():
    criterion = {"condition": "Report the source count accurately.",
                 "requirement_refs": ["commission: count"],
                 "allowed_limitations": "None for the known count."}
    return {"commission": "Report the supplied count.", "scope_instruction": "No new survey.",
            "source_sets": {"common": [{"id": "s", "title": "Inventory",
                              "coverage": "complete", "content": "There are 7 units."}]},
            "criteria_sets": {"baseline": [criterion], "clear_boundary": [criterion]},
            "reports": [{"case_id": "packet_01", "title": "Inventory summary",
                         "source_set": "common", "body": "There are 7 units [s]."}]}


@pytest.mark.parametrize("location", ["root", "case", "source", "criterion"])
def test_evaluator_fields_cannot_enter_inputs(tmp_path, location):
    data = fixture_data()
    target = {"root": data, "case": data["reports"][0],
              "source": data["source_sets"]["common"][0],
              "criterion": data["criteria_sets"]["baseline"][0]}[location]
    target["expected_labels"] = ["satisfied"]
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        diagnostic.load_inputs(path)


def test_preparation_preserves_supplied_standards_sources_and_draft(tmp_path):
    data = fixture_data()
    ws = diagnostic.prepare_workspace(tmp_path, data, data["reports"][0], "criteria_only")
    criteria = active_criteria(ws)
    assert criteria["criteria"][0]["condition"] == data["criteria_sets"]["clear_boundary"][0]["condition"]
    draft = next(r for r in ws.results() if r["kind"] == "draft")
    assert draft["body"] == data["reports"][0]["body"]
    assert draft["input_ids"] == [criteria["id"]]
    assert ws.store.manifest["sources"] == data["source_sets"]["common"]
    assert ws.store.get("knowledge_enabled") is False


async def test_actual_prompt_target_binding_public_receipt_and_no_replay(tmp_path, monkeypatch):
    for key, value in {"REPORT_MODEL": "glm-5.3", "REPORT_BASE_URL": "https://unused.invalid/v1",
                       "REPORT_API_KEY": "offline", "LANGSMITH_TRACING": "false",
                       "LANGCHAIN_TRACING_V2": "false"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("REPORT_GRADER_MODEL", raising=False)
    def denied(*a, **k):
        pytest.fail("Network forbidden")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)
    root = tmp_path / "attempt"
    prompt = "Distinct synthetic baseline prompt."
    original_prompt = reviewer_prompt(requirement_acceptance=True)
    calls = []

    class Agent:
        async def ainvoke(self, payload, config):
            calls.append(payload)
            criteria = active_criteria(Workspace(Store(root)))["criteria"]
            public = {"result": "satisfied", "explanation": "Offline protocol fixture.",
                      "criteria": [{"name": c["id"], "status": "satisfied", "passed": True,
                                    "evidence": [], "explanation": "Offline fixture.",
                                    "needed_outcome": "None."} for c in criteria]}
            return {"private_unexported": "DO_NOT_EXPORT",
                    "structured_response": SimpleNamespace(model_dump=lambda **k: public)}

    def ensure(self):
        assert self._system_prompt == prompt
        return Agent()
    monkeypatch.setattr(FeedbackRubric, "_ensure_grader", ensure)
    data = fixture_data()
    receipt = await diagnostic.run_one(root, data, data["reports"][0], "baseline", 0, prompt)
    assert receipt["status"] == "completed", receipt
    assert receipt["exact_criterion_coverage"]
    targets = Store(root).get("rubric_targets", {})
    assert targets and all(t["reviewer_prompt_hash"] == digest(prompt) for t in targets.values())
    assert reviewer_prompt(requirement_acceptance=True) == original_prompt
    assert "DO_NOT_EXPORT" not in (root / "output.json").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        await diagnostic.run_one(root, data, data["reports"][0], "baseline", 0, prompt)
    assert len(calls) == 1
