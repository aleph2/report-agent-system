"""Offline native grader graph and loop tests; no provider or project data."""
import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from pydantic import Field


spec = importlib.util.spec_from_file_location(
    "trial_native_rubric013", Path(__file__).parents[1] / "scripts" / "trial_native_rubric013.py")
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class ScriptedModel(BaseChatModel):
    replies: list[Any]
    seen: list = Field(default_factory=list, exclude=True)
    bindings: list = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):
        return "offline-rubric-test"

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("Expected asynchronous graph")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        if not self.replies:
            raise AssertionError("Unexpected extra model invocation")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")

    def forbid(*args, **kwargs):
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(httpx.Client, "send", forbid)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)


def verdict(passed, count):
    criteria = [{"name": f"Exact required line {n}", "passed": passed,
                 **({} if passed else {"gap": "Add the required exact line"})}
                for n in range(count)]
    return AIMessage("", tool_calls=[{
        "name": "GraderResponse", "id": f"grade-{passed}", "type": "tool_call",
        "args": {"result": "satisfied" if passed else "needs_revision",
                 "explanation": "Synthetic assessment", "criteria": criteria},
    }])


def rules_file(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({name: case["rubric"] for name, case in trial.CASES.items()}),
                    encoding="utf-8")
    return path


@pytest.mark.parametrize("name", list(trial.CASES))
async def test_native_feedback_revision_and_version_bound_evaluation(tmp_path, name):
    rules = trial.read_rules(rules_file(tmp_path))
    case = trial.CASES[name]
    writer = ScriptedModel(replies=[AIMessage(case["initial"]), AIMessage("\n".join(case["expected"]))])
    grader = ScriptedModel(replies=[verdict(False, len(case["expected"])),
                                   verdict(True, len(case["expected"]))])
    result = await trial.run_case(name, rules[name], writer, grader)
    assert result["success"] is True
    assert result["status"] == "satisfied"
    assert result["private_status_in_invoke_output"] is False
    assert result["native_evaluations_match_callback"] is True
    assert [e["iteration"] for e in result["evaluations"]] == [0, 1]
    assert [e["result"] for e in result["evaluations"]] == ["needs_revision", "satisfied"]
    assert len({e["grading_run_id"] for e in result["evaluations"]}) == 1
    assert result["evaluations"][-1]["candidate_message_id"] == result["final_message_id"]
    assert result["evaluations"][-1]["candidate_sha256"] == result["final_sha256"]
    assert result["evaluations"][0]["candidate_sha256"] != result["final_sha256"]
    assert all(e["rubric_sha256"] == trial.digest(rules[name]) for e in result["evaluations"])
    assert result["evaluations"][0]["callback_keys"] == sorted([
        "grading_run_id", "iteration", "result", "explanation", "criteria", "unverified"])
    feedback = [m for m in writer.seen[1] if m.additional_kwargs.get("lc_source") == "rubric_grader"]
    assert len(feedback) == 1 and feedback[0].name == "rubric_grader"
    for n in range(len(case["expected"])):
        assert f"Exact required line {n}" in feedback[0].text
    assert "Add the required exact line" in feedback[0].text
    assert result["feedback_delivery_and_change_verified"] is True
    assert result["working_model_feedback"][0]["failed_criteria_count"] == len(case["expected"])
    assert result["working_model_feedback"][0]["response_sha256"] == result["final_sha256"]
    assert rules[name] in grader.seen[0][-1].content
    assert len(writer.seen) == len(grader.seen) == 2


@pytest.mark.parametrize("failure", ["grader_error", "max_iterations_reached"])
async def test_terminal_failure_is_not_success(tmp_path, failure):
    rules = trial.read_rules(rules_file(tmp_path))
    case = trial.CASES["checksum"]
    writer = ScriptedModel(replies=[AIMessage(case["initial"])])
    grader = ScriptedModel(replies=[RuntimeError("SYNTHETIC_GRADER_FAILURE")
                                   if failure == "grader_error" else verdict(False, 2)])
    result = await trial.run_case("checksum", rules["checksum"], writer, grader, max_iterations=1)
    assert result["status"] == result["checkpoint_status"] == failure
    assert result["accepted"] is False and result["success"] is False
    assert result["iterations"] == 1
    assert result["feedback_count"] == 0
    assert result["working_model_feedback"] == []
    assert result["feedback_delivery_and_change_verified"] is False
    # Native terminal results keep the last AI candidate; that is not acceptance
    # and no terminal feedback/restart is manufactured by this trial.
    assert result["final_sha256"] == trial.digest(case["initial"])
    assert len(writer.seen) == len(grader.seen) == 1
    assert result["evaluations"][0]["result"] == failure
    assert result["native_evaluations_match_callback"] is True


def test_rules_reject_non_synthetic_input_before_model_use(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"checksum": "unapproved rules"}), encoding="utf-8")
    with pytest.raises(ValueError, match="SYNTHETIC_RULES_MISMATCH"):
        trial.read_rules(path)


def test_metadata_audit_does_not_persist_reasoning_or_double_count_generations():
    records = []
    message = AIMessage("synthetic body", additional_kwargs={"reasoning_content": "private-test-marker"},
                        usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5})
    audit = trial.MetadataAudit("offline", records.append)
    generation = ChatGeneration(message=message)
    audit.on_llm_end(LLMResult(generations=[[generation, generation]]), run_id="synthetic-run")
    assert len(records) == 1
    assert records[0]["generation_count"] == 2
    assert records[0]["usage"]["total_tokens"] == 5
    assert "private-test-marker" not in json.dumps(records)
    assert "synthetic body" not in json.dumps(records)
