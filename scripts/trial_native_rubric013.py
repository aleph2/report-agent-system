"""Task013 synthetic native Rubric trial; persist metadata, never model reasoning.

The deliberately incomplete first replies test feedback/revision, not autonomy or
engineering review quality. The only revision loop is RubricMiddleware's graph.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.middleware.rubric import RubricMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from report_agent.deep_models import configured_model, error_data


CASES = {
    "checksum": {
        "initial": "checksum=41",
        "expected": ["checksum=42", "status=synthetic"],
        "rubric": (
            "Evaluate only the latest assistant candidate, not earlier candidates. "
            "Criterion 1: its output includes the exact line checksum=42. "
            "Criterion 2: its output includes the exact line status=synthetic."
        ),
    },
    "units": {
        "initial": "mass=3\nvolume=2",
        "expected": ["mass_kg=3", "volume_l=2", "scope=synthetic-only"],
        "rubric": (
            "Evaluate only the latest assistant candidate, not earlier candidates. "
            "Criterion 1: its output includes the exact line mass_kg=3. "
            "Criterion 2: its output includes the exact line volume_l=2. "
            "Criterion 3: its output includes the exact line scope=synthetic-only."
        ),
    },
}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_rules(path):
    rules = json.loads(path.read_text(encoding="utf-8"))
    # This launcher is authorized for these synthetic fixtures, not project data.
    if rules != {name: case["rubric"] for name, case in CASES.items()}:
        raise ValueError("SYNTHETIC_RULES_MISMATCH")
    return rules


class MetadataAudit(BaseCallbackHandler):
    def __init__(self, role, emit):
        self.role, self.emit = role, emit

    def on_llm_end(self, response, *, run_id, **kwargs):
        generations = [generation for batch in response.generations for generation in batch]
        if not generations:
            return
        message = generations[0].message
        reasoning = message.additional_kwargs.get("reasoning_content")
        self.emit({
            "event": "model_response", "role": self.role, "run_id": str(run_id),
            "message_id": message.id, "content_sha256": digest(message.text),
            "reasoning_present": isinstance(reasoning, str),
            "reasoning_length": len(reasoning) if isinstance(reasoning, str) else None,
            # Multiple generations can share one response's usage; record it once.
            "usage": message.usage_metadata, "generation_count": len(generations),
            "tool_call_count": len(message.tool_calls),
        })

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.emit({"event": "model_error", "role": self.role,
                   "run_id": str(run_id), **error_data(error)})


async def run_case(name, rubric, writer, grader, *, max_iterations=3, emit=lambda item: None):
    case = CASES[name]
    rubric_hash = digest(rubric)
    candidates, evaluations = [], []
    binding = {}
    expected_feedback, received_feedback = [], []

    class WorkingModelFeedback(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            if not expected_feedback:
                return
            expected = expected_feedback[-1]
            feedback = [m for batch in messages for m in batch
                        if isinstance(m, HumanMessage)
                        and m.additional_kwargs.get("lc_source") == "rubric_grader"]
            text = feedback[-1].text if feedback else ""
            record = {
                "event": "working_model_feedback", "run_id": str(run_id),
                "iteration": expected["iteration"],
                "prior_candidate_sha256": expected["candidate_sha256"],
                "failed_criteria_count": len(expected["criteria"]),
                "received_exact_criteria_and_gaps": bool(feedback) and bool(expected["criteria"])
                    and all(c["name"] in text and c["gap"].strip() in text for c in expected["criteria"]),
            }
            received_feedback.append(record)
            emit(dict(record))

        def on_llm_end(self, response, *, run_id, **kwargs):
            for record in received_feedback:
                if record["run_id"] == str(run_id):
                    record["response_sha256"] = digest(response.generations[0][0].message.text)

    writer.callbacks = [*(writer.callbacks or []), WorkingModelFeedback()]

    def prepare(messages):
        candidate = next(m for m in reversed(messages) if isinstance(m, AIMessage))
        original = next(m for m in messages if isinstance(m, HumanMessage)
                        and m.additional_kwargs.get("lc_source") != "rubric_grader")
        binding.clear()
        binding.update(candidate_message_id=candidate.id, candidate_sha256=digest(candidate.text),
                       rubric_sha256=rubric_hash)
        if not candidates or candidates[-1] != binding:
            candidates.append(dict(binding))
        # Public native hook: grade exactly this short synthetic candidate.
        return [original, candidate]

    def on_evaluation(evaluation):
        if evaluation["result"] == "needs_revision":
            expected_feedback.append({"iteration": evaluation["iteration"], **binding,
                                      "criteria": [dict(c) for c in evaluation["criteria"] if not c["passed"]]})
        record = {
            "event": "evaluation", **binding,
            "grading_run_id": evaluation["grading_run_id"],
            "iteration": evaluation["iteration"], "result": evaluation["result"],
            "unverified": evaluation["unverified"],
            "callback_keys": sorted(evaluation),
            "criteria_passed": [c["passed"] for c in evaluation["criteria"]],
            "criteria_count": len(evaluation["criteria"]),
        }
        evaluations.append(record)
        emit(record)

    middleware = RubricMiddleware(
        model=grader, max_iterations=max_iterations,
        prepare_messages_for_grader=prepare, on_evaluation=on_evaluation,
    )
    agent = create_deep_agent(
        model=writer, middleware=[middleware], checkpointer=InMemorySaver(),
        system_prompt=(
            "This is a synthetic revision test. Do not use tools or delegate. "
            "Your first reply must be exactly the incomplete seed supplied by the user. "
            "After grader feedback, fix the candidate to satisfy every stated criterion. "
            "Return only the candidate, not private reasoning or commentary."
        ),
    )
    config = {"configurable": {"thread_id": f"rubric013-{name}"}}
    output = await agent.ainvoke({
        "messages": [HumanMessage("First-reply seed:\n" + case["initial"])],
        "rubric": rubric,
    }, config)
    snapshot = await agent.aget_state(config)
    state = snapshot.values
    answers = [m for m in state["messages"] if isinstance(m, AIMessage) and not m.tool_calls]
    final = answers[-1]
    feedback_count = sum(m.additional_kwargs.get("lc_source") == "rubric_grader"
                         for m in state["messages"] if isinstance(m, HumanMessage))
    status = state.get("_rubric_status")
    accepted = status == "satisfied" and bool(evaluations) and not evaluations[-1]["unverified"]
    expected_lines = set(case["expected"]).issubset(final.text.splitlines())
    initial_is_seed = bool(answers) and answers[0].text == case["initial"]
    revised = len(candidates) >= 2 and candidates[0]["candidate_sha256"] != candidates[-1]["candidate_sha256"]
    candidate_hashes = {c["candidate_sha256"] for c in candidates}
    feedback_verified = bool(expected_feedback) and len(received_feedback) == len(expected_feedback) and all(
        record["received_exact_criteria_and_gaps"]
        and record.get("response_sha256") in candidate_hashes
        and record.get("response_sha256") != record["prior_candidate_sha256"]
        for record in received_feedback
    )
    return {
        "case": name, "status": status, "accepted": accepted,
        "iterations": state.get("_rubric_iterations"), "evaluations": evaluations,
        "candidates": candidates, "feedback_count": feedback_count,
        "initial_is_seed": initial_is_seed, "final_expected_lines": expected_lines,
        "revision_observed": revised, "final_sha256": digest(final.text),
        "working_model_feedback": received_feedback,
        "feedback_delivery_and_change_verified": feedback_verified,
        "final_message_id": final.id, "rubric_sha256": rubric_hash,
        "private_status_in_invoke_output": "_rubric_status" in output,
        "checkpoint_status": state.get("_rubric_status"),
        "native_evaluations_match_callback": [e["result"] for e in state.get("_rubric_evaluations", [])]
            == [e["result"] for e in evaluations],
        "success": accepted and expected_lines and initial_is_seed and revised
            and feedback_count > 0 and evaluations[0]["result"] == "needs_revision" and feedback_verified,
    }


async def main(args):
    from run_deepagents_trial import load_service_environment

    # Provider/native exception logs can contain bodies; this trial emits safe metadata instead.
    logging.disable(logging.CRITICAL)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "intent.json").open("x", encoding="utf-8") as stream:
        json.dump({"scope": "Task013 two synthetic native rubric trials", "engineering_data": False,
                   "authorization": "user authorized synthetic GLM validation",
                   "max_grader_iterations_per_case": 3,
                   "note": "native coverage/structured-output and SDK retries may add requests"}, stream)
    rules_path = args.rules or args.output / "synthetic-rules.json"
    if args.rules is None:
        with rules_path.open("x", encoding="utf-8") as stream:
            json.dump({name: case["rubric"] for name, case in CASES.items()}, stream, indent=2)
    rules = read_rules(rules_path)
    load_service_environment(args.credential_container)

    def emit(item):
        with (args.output / "metadata.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=True) + "\n")
        print(json.dumps(item, ensure_ascii=True), flush=True)

    summaries = []
    for name in CASES:
        models = []
        for role in ("writer", "grader"):
            # Replace LocalAudit before invocation: no transcript/response text is persisted.
            model = configured_model(None, f"rubric013_{name}_{role}")
            model.callbacks = [MetadataAudit(f"{name}_{role}", emit)]
            models.append(model)
        try:
            result = await run_case(name, rules[name], *models, emit=emit)
        except Exception as exc:
            result = {"case": name, "success": False, "error": error_data(exc)}
        finally:
            for model in models:
                await model.root_async_client.close()
                model.root_client.close()
        (args.output / f"{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        summaries.append(result)
        emit({"event": "case_finished", "case": name, "success": result["success"],
              "status": result.get("status"), "error": result.get("error")})
    return 0 if all(item["success"] for item in summaries) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".runs/task013/native-rubric"))
    parser.add_argument("--rules", type=Path, help="JSON containing only the approved synthetic rules")
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    arguments = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(arguments)))
    except Exception as exc:
        print(json.dumps({"event": "trial_error", **error_data(exc)}), flush=True)
        raise SystemExit(1) from None
