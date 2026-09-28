"""Offline isolation/integrity tests; mocks make no quality claim."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_grader_diagnostic import load_inputs, run_case, sha, user_message, write_json
from report_agent.review import load_rules, reviewer_prompt


def inputs(candidate):
    data = {"system_prompt": reviewer_prompt(), "rubric": load_rules(),
            "assignment": "Judge the quoted quantity", "source": "Source: 6 units"}
    case = {"id": "0123456789ab", "candidate": candidate, "candidate_sha256": sha(candidate),
            "user_sha256": sha(user_message(data["assignment"], data["source"], candidate, data["rubric"]))}
    return {**data, "cases": [case], "hashes": {k: sha(v) for k, v in data.items()}}


def test_long_input_complete_and_tampering_rejected(tmp_path):
    candidate = "start\n" + "长正文" * 12000 + "\nend"
    data = inputs(candidate)
    path = tmp_path / "inputs.json"
    write_json(path, data)
    loaded = load_inputs(path)
    assert candidate in user_message(loaded["assignment"], loaded["source"], candidate, loaded["rubric"])
    data["cases"][0]["candidate"] += "changed"
    write_json(path, data)
    with pytest.raises(ValueError, match="INPUT_HASH_MISMATCH"):
        load_inputs(path)


def test_reference_fields_rejected(tmp_path):
    data = inputs("6 units")
    data["cases"][0]["expected_target"] = "match"
    path = tmp_path / "inputs.json"
    write_json(path, data)
    with pytest.raises(ValueError, match="UNEXPECTED_CASE_FIELDS"):
        load_inputs(path)


@pytest.mark.asyncio
async def test_fresh_input_public_output_and_no_replay(tmp_path):
    data = inputs("6 units")
    captured = []

    class Agent:
        async def ainvoke(self, value):
            captured.append(value)
            return {"messages": ["private field must not be serialized"],
                    "structured_response": SimpleNamespace(model_dump=lambda **kw: {"result": "satisfied"})}

    result = await run_case(data, data["cases"][0], tmp_path, lambda store: (Agent(), {}))
    assert result["status"] == "completed"
    assert len(captured[0]["messages"]) == 1
    output = tmp_path / data["cases"][0]["id"] / "output.json"
    assert json.loads(output.read_text()) == {"result": "satisfied"}
    with pytest.raises(FileExistsError):
        await run_case(data, data["cases"][0], tmp_path, lambda store: (Agent(), {}))
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_failure_receipt_redacts_provider_text(tmp_path):
    data = inputs("6 units")

    class Agent:
        async def ainvoke(self, value):
            raise RuntimeError("sensitive provider body")

    result = await run_case(data, data["cases"][0], tmp_path, lambda store: (Agent(), {}))
    assert result["status"] == "error"
    assert result["error"]["message"] == "EXECUTION_FAILED"
    assert "sensitive" not in (tmp_path / data["cases"][0]["id"] / "receipt.json").read_text()
