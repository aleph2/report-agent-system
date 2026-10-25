"""Offline provenance, controlled-message and attempted-call isolation checks."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import prepare_relation_verdict_diagnostic as prep
import run_relation_verdict_diagnostic as probe


def criteria():
    return [{"id": f"criterion_{i:012x}", "condition": "Compile the supplied values.",
             "scope": "Supplied inventory", "evidence_expectation": "Locate the source value.",
             "allowed_limitations": "", "requirement_refs": ["Commission"]} for i in range(6)]


def synthetic_inputs(tmp_path, monkeypatch):
    fixed = prep.assignment(4271)
    fields = {"commission": "Compile inventory.", "source": "Count7.", "candidate": "Count7.",
              "rubric": json.dumps({"criteria": criteria()})}
    data = {"version": "relation-verdict-controls-v1", "cases": [
        {"id": fixed["arm_case_ids"][arm], **fields} for arm in ("A", "B")]}
    receipt = {"assignment": fixed, "augmentation": prep.suffix(fixed),
               "model_inputs_sha256": prep.sha(prep.encoded(data)),
               "runtime_files": {}, "frozen_input_files": {}}
    path = tmp_path/"model-inputs.json"
    path.write_bytes(prep.encoded(data))
    path.with_name("input-receipt.json").write_bytes(prep.encoded(receipt))
    original_data, original_receipt = copy.deepcopy(data), copy.deepcopy(receipt)
    monkeypatch.setattr(probe, "build", lambda seed: (copy.deepcopy(original_data), copy.deepcopy(original_receipt)))
    return path, data, receipt


def source_pair():
    content = json.dumps({"source_id": "source-one", "page": 19, "native_text": "Raw text\n7.",
                          "frozen_text_blocks": [{"text": "Raw text\n7."}],
                          "limitations": ["Original limitation"]}, ensure_ascii=False)
    records, events = [], []
    for index in range(2):  # Duplicate source content must still be retained.
        records.append({"sequence": 400 + index*4, "role": "rubric_grader", "tool": "inspect_source_page",
                        "arguments": {"source_id": "source-one", "page": 19},
                        "tool_call_id": f"call-{index}", "received_in_request": 402+index*4,
                        "tool_message_status": "success", "observation_sha256": prep.sha(content),
                        "observation": json.loads(content)})
        events.append({"sequence": 402+index*4, "kind": "deep_model_request", "data": {
            "role": "rubric_grader", "messages": [[{"type": "tool", "tool_call_id": f"call-{index}",
                                                         "status": "success", "content": content}]]}})
    records.append({"sequence": 410, "tool": "calculate", "observation": "Not source evidence"})
    records.append({"sequence": 300, "tool": "read_source_page", "observation": "Earlier author evidence"})
    return records, events


def test_actual_callback_content_checked_and_repetitions_preserved():
    records, events = source_pair()
    selected = prep.verified_observations(records, events)
    assert selected == records[:2] and len(selected) == 2
    assert json.loads(json.dumps(selected, ensure_ascii=False)) == records[:2]
    events[0]["data"]["messages"][0][0]["content"] += " "
    with pytest.raises(ValueError, match="CALLBACK_CONTENT"):
        prep.verified_observations(records, events)


@pytest.mark.parametrize("change", ["role", "status", "content"])
def test_nonreceived_failed_or_changed_observation_refused(change):
    records, events = source_pair()
    if change == "role":
        records[0]["role"] = "coordinator"
    elif change == "status":
        records[0]["tool_message_status"] = "error"
    else:
        records[0]["observation"]["page"] = 20
    with pytest.raises(ValueError):
        prep.verified_observations(records, events)


def test_original_scope_and_complete_criteria_must_equal_first_actual_request(monkeypatch):
    standard = {"criteria": criteria(), "basis_hash": "basis", "requirement_basis": {"goal": "Compile inventory."}}
    body = json.dumps(standard)
    monkeypatch.setattr(prep, "ACCEPTANCE_SHA", prep.sha(body))
    monkeypatch.setattr(prep, "DRAFT_SHA", prep.sha("Count7."))
    active = {"id": prep.ACCEPTANCE_ID, "kind": "acceptance", "body": body}
    results = [active, {"id": prep.DRAFT_ID, "kind": "draft", "body": "Count7."}]
    actual = {"acceptance_identity": {"criteria_id": prep.ACCEPTANCE_ID,
               "body_hash": prep.ACCEPTANCE_SHA, "basis_hash": "basis"}, "criteria": criteria()}
    def request():
        return {"sequence": 353, "role": "rubric_grader", "messages": [[{"type": "human",
            "content": "\n<rubric-abc>\nOriginal instructions\n" + json.dumps(actual) + "\n</rubric-abc>"}]]}
    records, events = source_pair()
    fields, selected = prep.extract_materials(results, {**active, "current": True}, request(), records, events)
    assert json.loads(fields["rubric"])["criteria"] == criteria()
    assert selected == records[:2] and fields["commission"] == "Compile inventory."
    actual["criteria"][0]["allowed_limitations"] = "Any result allowed."
    with pytest.raises(ValueError, match="DEFINITIONS_DIFFER"):
        prep.extract_materials(results, active, request(), records, events)


@pytest.mark.parametrize("where", ["root", "case", "criterion"])
def test_oracle_fields_rejected_before_runtime(tmp_path, monkeypatch, where):
    path, data, _ = synthetic_inputs(tmp_path, monkeypatch)
    if where == "criterion":
        rubric = json.loads(data["cases"][0]["rubric"])
        rubric["criteria"][0]["expected"] = "not_satisfied"
        data["cases"][0]["rubric"] = json.dumps(rubric)
    else:
        (data if where == "root" else data["cases"][0])["expected"] = "not_satisfied"
    path.write_bytes(prep.encoded(data))
    with pytest.raises(ValueError):
        probe.load_inputs(path)


def test_pair_is_identical_except_exact_suffix_and_order_persists(tmp_path, monkeypatch):
    path, data, receipt = synthetic_inputs(tmp_path, monkeypatch)
    loaded, frozen = probe.load_inputs(path)
    fixed = frozen["assignment"]
    assert fixed == prep.assignment(fixed["seed"])
    a, b = [prep.model_message(case, fixed) for case in loaded["cases"]]
    assert b == a + prep.suffix(fixed)
    for excluded in ("expected", "arm_case_ids", "case_order", "seed", "known error", "corrected"):
        assert excluded not in b
    assert all(case["id"] not in b for case in data["cases"])
    assert probe.load_inputs(path) == (loaded, frozen)
    data["cases"][1]["source"] += " Extra evidence"
    path.write_bytes(prep.encoded(data))
    with pytest.raises(ValueError, match="IDENTICAL"):
        probe.load_inputs(path)


def test_preparation_never_overwrites_even_identical_output(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(prep, "build", lambda seed: (calls.append(seed) or {"data": 1}, {"seed": seed}))
    output = tmp_path/"frozen"
    prep.prepare(output, 42)
    original = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(FileExistsError, match="EXISTING"):
        prep.prepare(output, 42)
    assert calls == [42] and original == {p.name: p.read_bytes() for p in output.iterdir()}


def test_receipt_cannot_change_augmentation_or_random_order(tmp_path, monkeypatch):
    path, _, receipt = synthetic_inputs(tmp_path, monkeypatch)
    receipt["augmentation"] += " Expected result: reject."
    path.with_name("input-receipt.json").write_bytes(prep.encoded(receipt))
    with pytest.raises(ValueError, match="ASSIGNMENT"):
        probe.load_inputs(path)


async def test_suffix_reaches_actual_model_message_and_public_audit(tmp_path, monkeypatch):
    _, data, receipt = synthetic_inputs(tmp_path, monkeypatch)
    case = data["cases"][1]
    message = prep.model_message(case, receipt["assignment"])
    seen = []
    public = {"result": "satisfied", "explanation": "Offline fixture only.", "criteria": [
        {"name": row["id"], "passed": True, "status": "satisfied", "evidence": [],
         "explanation": "Source count7.", "needed_outcome": "None."} for row in criteria()]}
    class Agent:
        async def ainvoke(self, payload):
            seen.append(payload)
            return {"structured_response": public, "opaque_private": "DO_NOT_SERIALIZE"}
    def factory(store, prompt):
        store.event("deep_model_request", {"role": "grader_diagnostic", "messages": [[{"type": "human", "content": message}]]})
        store.event("deep_model_response", {"usage": {"total_tokens": 11}, "content": "Public response"})
        return Agent(), {"model": "offline"}
    root = tmp_path/"cell"
    result = await probe.run_one(root, case, message, "prompt", factory=factory)
    assert result["status"] == "completed" and result["usage"] == [{"total_tokens": 11}]
    assert len(seen) == 1 and len(seen[0]["messages"]) == 1
    assert seen[0]["messages"][0].content == json.loads((root/"input.json").read_text())["user"] == message
    assert "DO_NOT_SERIALIZE" not in (root/"output.json").read_text()
    assert json.loads((root/"model-io.json").read_text())[0]["data"]["messages"][0][0]["content"] == message
    with pytest.raises(FileExistsError):
        await probe.run_one(root, case, message, "prompt", factory=factory)
    assert len(seen) == 1


async def test_protocol_error_preserves_usage_and_unmodified_invalid_output(tmp_path, monkeypatch):
    _, data, receipt = synthetic_inputs(tmp_path, monkeypatch)
    case = data["cases"][0]
    # Schema-valid but missing five required IDs must remain a failed attempt.
    public = {"result": "satisfied", "explanation": "Offline malformed coverage.", "criteria": [{
        "name": criteria()[0]["id"], "passed": True, "status": "satisfied", "evidence": [],
        "explanation": "One criterion only.", "needed_outcome": "None."}]}
    class Agent:
        async def ainvoke(self, payload):
            return {"structured_response": public}
    def factory(store, prompt):
        store.event("deep_model_response", {"usage": {"total_tokens": 17}, "content": "Public incomplete response"})
        return Agent(), {"model": "offline"}
    root = tmp_path/"failure"
    result = await probe.run_one(root, case, prep.model_message(case, receipt["assignment"]), "prompt", factory)
    assert result["status"] == "error" and result["usage"] == [{"total_tokens": 17}]
    assert "CRITERION_COVERAGE_MISMATCH" in json.dumps(result)
    assert json.loads((root/"output.json").read_text()) == public


async def test_failed_attempt_retained_and_only_frozen_diagnosed_suffix_runs(tmp_path, monkeypatch):
    path, data, receipt = synthetic_inputs(tmp_path, monkeypatch)
    runtime = tmp_path/"runtime.txt"
    runtime.write_text("v1")
    monkeypatch.setattr(probe, "frozen_files", lambda p, _: {"inputs": prep.sha(p.read_bytes()),
        "receipt": prep.sha(p.with_name("input-receipt.json").read_bytes()), "runtime": prep.sha(runtime.read_bytes())})
    args = SimpleNamespace(inputs=path, output=tmp_path/"batch", resume=False, diagnosis_note="",
                           credential_container="unused", authorization_note="offline")
    order = receipt["assignment"]["case_order"]
    calls = []
    async def invoke(root, case, message, prompt):
        root.mkdir(exist_ok=False)
        calls.append(case["id"])
        item = {"status": "error" if len(calls) == 1 else "completed", "usage": [13]}
        probe.write_json(root/"input.json", {"user": message})
        probe.write_json(root/"receipt.json", item)
        return item
    def no_credentials(_):
        pytest.fail("Preflight must reject before credentials.")
    initial = await probe.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    failed_root = args.output/order[0]
    original = {p.name: p.read_bytes() for p in failed_root.iterdir()}
    assert initial["status"] == "needs_diagnosis" and calls == order[:1]
    assert not (args.output/order[1]).exists()
    with pytest.raises(FileExistsError):
        await probe.run_batch(args, invoke=invoke, credentials_loader=no_credentials)
    args.resume = True
    with pytest.raises(ValueError, match="DIAGNOSED"):
        await probe.run_batch(args, invoke=invoke, credentials_loader=no_credentials)
    args.diagnosis_note = "Main reviewed the protocol error; preserve it and attempt untouched suffix."
    runtime.write_text("v2")
    with pytest.raises(ValueError, match="FROZEN"):
        await probe.run_batch(args, invoke=invoke, credentials_loader=no_credentials)
    runtime.write_text("v1")
    result = await probe.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert result["status"] == "completed_with_errors" and calls == order
    assert original == {p.name: p.read_bytes() for p in failed_root.iterdir()}
    assert json.loads((args.output/"batch.before-continuation.json").read_text())["status"] == "needs_diagnosis"
    with pytest.raises(ValueError, match="FROZEN"):
        await probe.run_batch(args, invoke=invoke, credentials_loader=no_credentials)


async def test_unexpected_batch_error_preserved_without_automatic_retry(tmp_path, monkeypatch):
    path, _, _ = synthetic_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(probe, "frozen_files", lambda *_: {"frozen": "yes"})
    args = SimpleNamespace(inputs=path, output=tmp_path/"batch", resume=False, diagnosis_note="",
                           credential_container="unused", authorization_note="offline")
    calls = []
    async def invoke(*_):
        calls.append(1)
        raise RuntimeError("Synthetic transport boundary failure")
    result = await probe.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
    assert result["status"] == "needs_diagnosis" and "execution_error" in result and calls == [1]
    args.resume, args.diagnosis_note = True, "Unknown write outcome cannot be replayed."
    with pytest.raises(ValueError, match="UNATTEMPTED_SUFFIX"):
        await probe.run_batch(args, invoke=invoke, credentials_loader=lambda _: None)
