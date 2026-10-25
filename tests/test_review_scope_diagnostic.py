"""Diagnostic integrity only; these tests do not assess model quality."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_review_scope_diagnostic as scope
from run_grader_diagnostic import sha, user_message, write_json
from report_agent.review import load_rules, reviewer_prompt


def fixture():
    data = {"experiment": scope.EXPERIMENT, "system_prompt": reviewer_prompt(scope.EXPERIMENT),
            "rubric": load_rules(), "source": "Original evidence"}
    candidate = "Complete report " * 4000
    case = {"id": "a123456789bc", "assignment": "Assess this defined scope", "candidate": candidate,
            "candidate_sha256": sha(candidate)}
    case["user_sha256"] = sha(scope.diagnostic_message(case["assignment"], data["source"], candidate, data["rubric"]))
    return {**data, "cases": [case], "hashes": {k: sha(data[k]) for k in ("system_prompt", "rubric", "source")}}


def test_frozen_scope_and_evidence_cannot_be_changed_or_labeled(tmp_path):
    data = fixture()
    path = tmp_path / "inputs.json"
    write_json(path, data)
    assert scope.load_inputs(path) == data
    for field in ("assignment", "candidate"):
        changed = copy.deepcopy(data)
        changed["cases"][0][field] += "tampered"
        write_json(path, changed)
        with pytest.raises(ValueError, match="INPUT_HASH_MISMATCH"):
            scope.load_inputs(path)
    labeled = copy.deepcopy(data)
    labeled["cases"][0]["expected_target"] = "match"
    write_json(path, labeled)
    with pytest.raises(ValueError, match="UNEXPECTED_CASE_FIELDS"):
        scope.load_inputs(path)


def test_factory_uses_validated_candidate_not_default_system(monkeypatch):
    prompt = reviewer_prompt(scope.EXPERIMENT)
    assert prompt != reviewer_prompt()
    payload_messages, agents = [], []
    model = SimpleNamespace(callbacks=[], max_retries=2,
                            request_timeout=SimpleNamespace(connect=15, read=1800, write=60, pool=60))
    def payload(messages):
        payload_messages.append(messages)
        return {"model": "test", "messages": [], "max_tokens": 65536}
    model._get_request_payload = payload
    monkeypatch.setattr(scope, "configured_model", lambda store, role: model)
    def agent(**kwargs):
        agents.append(kwargs)
        return object()
    monkeypatch.setattr(scope, "create_agent", agent)
    _, settings = scope.bound_factory(prompt)(object())
    assert agents[0]["system_prompt"] == prompt == payload_messages[0][0].content
    assert agents[0]["tools"] == []
    assert settings["system_sha256"] == sha(prompt)


def test_actual_request_guard_detects_default_prompt_and_truncation(tmp_path):
    data = fixture()
    case = data["cases"][0]
    human = scope.diagnostic_message(case["assignment"], data["source"], case["candidate"], data["rubric"])
    for system, text, valid in ((data["system_prompt"], human, True),
                                (reviewer_prompt(), human, False),
                                (data["system_prompt"], human[:4000], False)):
        write_json(tmp_path / "model-io.json", [{"kind": "deep_model_request", "data": {
            "messages": [[{"type": "system", "content": system}, {"type": "human", "content": text}]]}}])
        if valid:
            checked = scope.check_actual_input(tmp_path, data, case)
            assert checked["user_matches"] and checked["system_matches"]
        else:
            with pytest.raises(RuntimeError, match="ACTUAL_INPUT_DIFFERS_FROM_FREEZE"):
                scope.check_actual_input(tmp_path, data, case)


def test_missing_audit_is_recorded_and_cannot_be_verified(tmp_path):
    data = fixture()
    write_json(tmp_path / "model-io.json", [])
    with pytest.raises(RuntimeError, match="ACTUAL_INPUT_AUDIT_MISSING"):
        scope.check_actual_input(tmp_path, data, data["cases"][0])
    assert json.loads((tmp_path / "actual-input-check.json").read_text())["request_available"] is False
    assert scope.check_actual_input(tmp_path, data, data["cases"][0], required=False)["evidence_complete"] is False
