"""Experiment isolation and evidence capture, not model-quality tests."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import run_stance_diagnostic as probe


def data():
    rubric = json.dumps({"criteria": [{"id": "criterion_12345678", "condition": "Count accurately.",
                         "evidence_expectation": "Source count.", "allowed_limitations": ""}]})
    return {"version": "stance-controls-v1", "cases": [
        {"id": f"{i:012x}", "commission": "Report count.", "source": "Count7.",
         "rubric": rubric, "candidate": "Count7."} for i in range(4)]}


@pytest.mark.parametrize("where", ["root", "case", "criterion"])
def test_reference_labels_rejected(tmp_path, where):
    value = data()
    if where == "criterion":
        rubric = json.loads(value["cases"][0]["rubric"])
        rubric["criteria"][0]["expected"] = "satisfied"
        value["cases"][0]["rubric"] = json.dumps(rubric)
    else:
        (value if where == "root" else value["cases"][0])["expected"] = "satisfied"
    path = tmp_path/"inputs.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        probe.load_inputs(path)


def test_only_stance_line_varies_and_schedule_is_complete():
    cases = data()["cases"]
    messages = [probe.user_message(cases[0], stance) for stance in probe.STANCES]
    assert len({m.split("\n", 1)[1] for m in messages}) == 1
    assert [m.split("\n", 1)[0] for m in messages] == list(probe.STANCES.values())
    order = probe.schedule(cases, 370929)
    assert order == probe.schedule(cases, 370929)
    assert len(order) == 24
    assert len({(c["case_id"], c["repeat"], c["stance"]) for c in order}) == 24
    for case in cases:
        assert sum(c["case_id"] == case["id"] for c in order) == 6
    for position in range(3):
        counts = [sum(row["stance"] == stance for row in order[position::3]) for stance in probe.STANCES]
        assert sorted(counts) == [2, 3, 3]


async def test_public_output_saved_fresh_context_and_replay_rejected(tmp_path):
    case = data()["cases"][0]
    calls = []
    public = {"result": "satisfied", "explanation": "Offline count fixture.",
              "criteria": [{"name": "criterion_12345678", "status": "satisfied", "passed": True,
                            "evidence": [], "explanation": "Count7.", "needed_outcome": "None."}]}
    class Agent:
        async def ainvoke(self, payload):
            calls.append(payload)
            return {"structured_response": public, "opaque_private": "DO_NOT_SAVE"}
    def factory(store, prompt):
        assert prompt == "frozen prompt"
        return Agent(), {"model": "offline"}
    root = tmp_path/"attempt"
    result = await probe.run_one(root, case, "neutral", 0, "frozen prompt", factory)
    assert result["status"] == "completed"
    assert len(calls) == 1 and len(calls[0]["messages"]) == 1
    assert json.loads((root/"output.json").read_text()) == public
    assert "DO_NOT_SAVE" not in (root/"output.json").read_text()
    with pytest.raises(FileExistsError):
        await probe.run_one(root, case, "neutral", 0, "frozen prompt", factory)
    assert len(calls) == 1
