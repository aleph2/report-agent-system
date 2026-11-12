"""Isolated, inline-evidence judgment diagnostic; never loads reference labels.

This deliberately bypasses transcript excerpting and the outer revision loop.
It is not a production report review or an end-to-end acceptance test.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from deepagents.middleware.rubric import GraderResponse
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage

from report_agent.deep_models import configured_model, error_data
from report_agent.review import load_rules, reviewer_prompt
from report_agent.store import Store
from run_deepagents_trial import load_service_environment


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def user_message(assignment: str, source: str, candidate: str, rubric: str) -> str:
    # Complete strings: no native transcript excerpt limits are applied here.
    return (f"<commission>\n{assignment}\n</commission>\n\n"
            f"<rubric>\n{rubric}\n</rubric>\n\n"
            f"<source_evidence>\n{source}\n</source_evidence>\n\n"
            f"<candidate_report>\n{candidate}\n</candidate_report>")


def load_inputs(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"system_prompt", "rubric", "assignment", "source", "cases", "hashes"}:
        raise ValueError("UNEXPECTED_INPUT_FIELDS")
    if data["system_prompt"] != reviewer_prompt() or data["rubric"] != load_rules():
        raise ValueError("PRODUCTION_PROMPT_CHANGED")
    for key in ("system_prompt", "rubric", "assignment", "source"):
        if sha(data[key]) != data["hashes"][key]:
            raise ValueError("INPUT_HASH_MISMATCH")
    seen = set()
    for case in data["cases"]:
        if set(case) != {"id", "candidate", "candidate_sha256", "user_sha256"}:
            raise ValueError("UNEXPECTED_CASE_FIELDS")
        if not re.fullmatch(r"[a-f0-9]{12}", case["id"]) or case["id"] in seen:
            raise ValueError("INVALID_OR_DUPLICATE_CASE_ID")
        seen.add(case["id"])
        message = user_message(data["assignment"], data["source"], case["candidate"], data["rubric"])
        if sha(case["candidate"]) != case["candidate_sha256"] or sha(message) != case["user_sha256"]:
            raise ValueError("INPUT_HASH_MISMATCH")
    if not seen:
        raise ValueError("NO_CASES")
    return data


class InvocationAudit(BaseCallbackHandler):
    """Record effective invocation options using an explicit credential-free allowlist."""

    def __init__(self, store):
        self.store = store

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        params = kwargs.get("invocation_params", {})
        keys = ("model", "model_name", "stream", "temperature", "top_p", "seed",
                "reasoning_effort", "max_tokens", "max_completion_tokens",
                "parallel_tool_calls", "extra_body", "tools", "tool_choice", "response_format")
        self.store.event("diagnostic_invocation", {
            "run_id": str(run_id), "parameters": {key: params[key] for key in keys if key in params}})


async def run_case(data, case, destination, factory):
    # Exclusive directory claim: attempted calls cannot silently be replayed.
    root = destination / case["id"]
    root.mkdir(parents=True, exist_ok=False)
    store = Store(root)
    message = user_message(data["assignment"], data["source"], case["candidate"], data["rubric"])
    write_json(root / "input.json", {"system_prompt": data["system_prompt"], "user_message": message})
    receipt = {"case_id": case["id"], "started": datetime.now(timezone.utc).isoformat(),
               "system_sha256": sha(data["system_prompt"]), "user_sha256": sha(message),
               "candidate_sha256": case["candidate_sha256"], "status": "attempted"}
    write_json(root / "receipt.json", receipt)
    try:
        agent, settings = factory(store)
        write_json(root / "settings.json", settings)
        result = await agent.ainvoke({"messages": [HumanMessage(content=message)]})
        # Never serialize the complete agent result: it can contain opaque private reasoning.
        public = result["structured_response"].model_dump(mode="json")
        write_json(root / "output.json", public)
        receipt.update(status="completed", result=public["result"])
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    receipt["ended"] = datetime.now(timezone.utc).isoformat()
    events = store.events()
    receipt["model_requests"] = sum(e["kind"] == "deep_model_request" for e in events)
    responses = [e["data"] for e in events if e["kind"] == "deep_model_response"]
    receipt["model_responses"] = len(responses)
    receipt["usage"] = [e["usage"] for e in responses]
    # LocalAudit already removes reasoning_content. Export these recorded events only.
    write_json(root / "model-io.json", events)
    write_json(root / "receipt.json", receipt)
    return receipt


def real_factory(store):
    model = configured_model(store, "grader_diagnostic")
    model.callbacks.append(InvocationAudit(store))
    wire = model._get_request_payload([SystemMessage(content=reviewer_prompt()), HumanMessage(content="")])
    parameters = {key: value for key, value in wire.items() if key != "messages"}
    settings = {"adapter": type(model).__name__, "base_wire_parameters": parameters,
                "max_retries": model.max_retries,
                "timeout_seconds": {key: getattr(model.request_timeout, key)
                                    for key in ("connect", "read", "write", "pool")},
                "unset": [key for key in ("temperature", "top_p", "seed") if key not in wire],
                "versions": {name: version(name) for name in
                             ("deepagents", "langchain", "langchain-openai", "langgraph", "openai")},
                "evidence_tools": [], "response_schema": "GraderResponse",
                "outer_revision_loop": False}
    agent = create_agent(model=model, system_prompt=reviewer_prompt(), tools=[],
                         response_format=GraderResponse, name="rubric_grader")
    return agent, settings


async def main(args):
    # Validate every input before accessing credentials or attempting any call.
    data = load_inputs(args.inputs)
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "batch.json", {
        "authorization": args.authorization_note, "input_sha256": sha(args.inputs.read_text(encoding="utf-8")),
        "case_order": [case["id"] for case in data["cases"]], "input_hashes": data["hashes"],
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    load_service_environment(args.credential_container)
    if getattr(args, "grader_model", None):
        os.environ["REPORT_GRADER_MODEL"] = args.grader_model
    for case in data["cases"]:
        print(json.dumps({"case_id": case["id"], "status": "starting"}), flush=True)
        receipt = await run_case(data, case, destination, real_factory)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        if receipt["status"] == "error":
            # Preserve failure and stop for diagnosis; do not blindly repeat paid calls.
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorization-note", required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--grader-model", choices=["glm-5.3", "deepseek-v4.1-flash-1017"])
    asyncio.run(main(parser.parse_args()))
