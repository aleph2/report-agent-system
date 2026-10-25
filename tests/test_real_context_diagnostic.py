"""Diagnostic boundaries: oracle exclusion, unchanged evidence and no failed-cell replay."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import run_real_context_diagnostic as diagnostic


def model_inputs():
    rubric = json.dumps({"criteria": [
        {"id": f"criterion_{i:012x}", "condition": "Assess this scoped relation.",
         "evidence_expectation": "Use the supplied original rule.",
         "allowed_limitations": "Only the adopted premise is being evaluated."}
        for i in (1, 2)]})
    return {"version": "context-controls-v1", "cases": [
        {"id": f"{i:012x}", "commission": "Assess only two identified relations.",
         "source": "Complete supplied rule.", "rubric": rubric,
         "candidate": f"Candidate content {i}"} for i in range(1, 5)]}


@pytest.mark.parametrize("target", ["root", "case", "criterion"])
def test_evaluator_labels_are_rejected(tmp_path, target):
    data = model_inputs()
    if target == "criterion":
        rubric = json.loads(data["cases"][0]["rubric"])
        rubric["criteria"][0]["expected"] = "satisfied"
        data["cases"][0]["rubric"] = json.dumps(rubric)
    else:
        (data if target == "root" else data["cases"][0])["expected"] = "satisfied"
    path = tmp_path/"inputs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        diagnostic.load_inputs(path)


def test_common_scope_and_evidence_cannot_silently_vary(tmp_path):
    data = model_inputs()
    data["cases"][3]["commission"] += " Consider all engineering calculations."
    path = tmp_path/"inputs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="ONLY_CANDIDATE_CONTEXT"):
        diagnostic.load_inputs(path)


async def test_resume_preserves_error_and_runs_only_unattempted_cells(tmp_path, monkeypatch):
    data = model_inputs()
    path = tmp_path/"inputs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "frozen_files", lambda p: {
        "inputs": hashlib.sha256(p.read_bytes()).hexdigest()})
    args = SimpleNamespace(inputs=path, output=tmp_path/"runs", seed=380929,
        resume=False, diagnosis_note="", credential_container="unused", authorization_note="offline")
    calls = []

    async def invoke(root, case, stance, repeat, prompt):
        root.mkdir(exist_ok=False)
        assert stance == "neutral"
        calls.append((case["id"], repeat))
        receipt = {"status": "error" if len(calls) == 1 else "completed"}
        diagnostic.write_json(root/"receipt.json", receipt)
        return receipt

    result = await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert result["status"] == "needs_diagnosis" and len(calls) == 1
    failed_path = args.output/f"{calls[0][0]}-{calls[0][1]}"/"receipt.json"
    original = failed_path.read_bytes()
    args.resume = True
    with pytest.raises(ValueError, match="DIAGNOSED_CONTINUATION"):
        await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert len(calls) == 1
    args.diagnosis_note = "Offline schema failure inspected; retain and exclude from semantic scoring."
    result = await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert result["status"] == "completed_with_errors"
    assert len(calls) == len(set(calls)) == 8
    assert failed_path.read_bytes() == original
    assert (args.output/"batch.before-continuation-1.json").exists()
    assert calls == [(r["case_id"], r["repeat"]) for r in result["order"]]
    with pytest.raises(ValueError, match="FROZEN_CONTINUATION_MISMATCH"):
        await diagnostic.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert len(calls) == 8


async def test_changed_input_blocks_resume_before_credentials_or_calls(tmp_path, monkeypatch):
    data = model_inputs()
    path = tmp_path/"inputs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(diagnostic, "frozen_files", lambda p: {
        "inputs": hashlib.sha256(p.read_bytes()).hexdigest()})
    args = SimpleNamespace(inputs=path, output=tmp_path/"runs", seed=380929,
        resume=False, diagnosis_note="", credential_container="unused", authorization_note="offline")
    async def fail(root, *_):
        root.mkdir(exist_ok=False)
        receipt = {"status": "error"}
        diagnostic.write_json(root/"receipt.json", receipt)
        return receipt
    await diagnostic.run_batch(args, invoke=fail, credentials_loader=lambda _: None)
    data["cases"][0]["candidate"] += " Changed after failure."
    path.write_text(json.dumps(data), encoding="utf-8")
    args.resume, args.diagnosis_note = True, "Diagnosed failure."
    def denied(_):
        pytest.fail("Credentials must not load after frozen input changed")
    with pytest.raises(ValueError, match="FROZEN_CONTINUATION_MISMATCH"):
        await diagnostic.run_batch(args, invoke=fail, credentials_loader=denied)
