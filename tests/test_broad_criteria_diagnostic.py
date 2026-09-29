"""Preserve paid failures and reject evaluator leakage before accessing credentials."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import run_broad_criteria_diagnostic as diagnostic


def inputs(tmp_path):
    data = {"version": "broad-criteria-controls-v1", "cases": [{
        "id": "012345abcdef", "commission": "Original commission", "source": "Source pages",
        "candidate": "Original full report", "rubric": json.dumps({"criteria": [
            {"id": f"criterion_{i:012x}", "condition": "Original condition",
             "evidence_expectation": "Grounded evidence", "allowed_limitations": ""}
            for i in range(6)]})}]}
    path = tmp_path/"inputs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


@pytest.mark.parametrize("target", ["root", "case", "criterion"])
def test_oracle_cannot_enter_model_inputs(tmp_path, target):
    path, data = inputs(tmp_path)
    if target == "criterion":
        rubric = json.loads(data["cases"][0]["rubric"])
        rubric["criteria"][1]["expected"] = "not_satisfied"
        data["cases"][0]["rubric"] = json.dumps(rubric)
    else:
        (data if target == "root" else data["cases"][0])["expected"] = "not_satisfied"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        diagnostic.load_inputs(path)


async def test_failure_retained_and_changed_input_cannot_resume(tmp_path, monkeypatch):
    path, data = inputs(tmp_path)
    monkeypatch.setattr(diagnostic, "frozen_files", lambda p: {"input": hashlib.sha256(p.read_bytes()).hexdigest()})
    args = SimpleNamespace(inputs=path, output=tmp_path/"run", resume=False,
        diagnosis_note="", credential_container="unused", authorization_note="offline")
    calls = []
    async def invoke(root, case, stance, repeat, prompt):
        root.mkdir(exist_ok=False)
        calls.append(repeat)
        receipt = {"status": "error" if repeat == 0 else "completed"}
        diagnostic.write_json(root/"receipt.json", receipt)
        return receipt
    await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    failed = args.output/"012345abcdef-0/receipt.json"
    original = failed.read_bytes()
    args.resume = True
    with pytest.raises(ValueError, match="DIAGNOSED"):
        await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    args.diagnosis_note = "Inspected invalid response; retain failure."
    frozen_input = path.read_bytes()
    data["cases"][0]["candidate"] += " changed"
    path.write_text(json.dumps(data), encoding="utf-8")
    def denied(_):
        pytest.fail("No credentials after frozen-input mismatch")
    with pytest.raises(ValueError, match="FROZEN"):
        await diagnostic.run_batch(args, invoke=invoke, credentials_loader=denied)
    path.write_bytes(frozen_input)
    result = await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert result["status"] == "completed_with_errors"
    assert calls == [0, 1] and failed.read_bytes() == original
    with pytest.raises(ValueError, match="FROZEN"):
        await diagnostic.run_batch(args, invoke=invoke, credentials_loader=denied)
