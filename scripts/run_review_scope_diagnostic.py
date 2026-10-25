"""Frozen, supplied-evidence scope comparison; no native acceptance or labels."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re

from deepagents.middleware.rubric import GraderResponse
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage

from report_agent.deep_models import configured_model
from report_agent.review import load_rules, reviewer_prompt
from run_deepagents_trial import load_service_environment
from run_grader_diagnostic import InvocationAudit, run_case, sha, user_message, write_json


EXPERIMENT = {"input_mode": "artifact", "grounded_verdict": True,
              "calibrated_acceptance": True, "compact_table_observations": True}
AVAILABILITY = ("Only the supplied report and source evidence are available. No retrieval or "
                "export-inspection tools are available. raw_geometry_access entries are "
                "provenance metadata, not callable tools in this session.")


def diagnostic_assignment(assignment):
    return AVAILABILITY + "\n\n" + assignment


def diagnostic_message(assignment, source, candidate, rubric):
    return user_message(diagnostic_assignment(assignment), source, candidate, rubric)


def load_inputs(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"system_prompt", "rubric", "source", "cases", "hashes", "experiment"}:
        raise ValueError("UNEXPECTED_INPUT_FIELDS")
    if data["experiment"] != EXPERIMENT or data["system_prompt"] != reviewer_prompt(EXPERIMENT) or data["rubric"] != load_rules():
        raise ValueError("FROZEN_PROMPT_CHANGED")
    if set(data["hashes"]) != {"system_prompt", "rubric", "source"}:
        raise ValueError("UNEXPECTED_HASH_FIELDS")
    for key in data["hashes"]:
        if not isinstance(data[key], str) or not data[key] or sha(data[key]) != data["hashes"][key]:
            raise ValueError("INPUT_HASH_MISMATCH")
    seen = set()
    for case in data["cases"]:
        if set(case) != {"id", "assignment", "candidate", "candidate_sha256", "user_sha256"}:
            raise ValueError("UNEXPECTED_CASE_FIELDS")
        if not re.fullmatch(r"[a-f0-9]{12}", case["id"]) or case["id"] in seen:
            raise ValueError("INVALID_OR_DUPLICATE_CASE_ID")
        if not all(isinstance(case[k], str) and case[k] for k in ("assignment", "candidate")):
            raise ValueError("INCOMPLETE_CASE")
        message = diagnostic_message(case["assignment"], data["source"], case["candidate"], data["rubric"])
        if sha(case["candidate"]) != case["candidate_sha256"] or sha(message) != case["user_sha256"]:
            raise ValueError("INPUT_HASH_MISMATCH")
        seen.add(case["id"])
    if not seen:
        raise ValueError("NO_CASES")
    return data


def bound_factory(prompt):
    """The actual agent and its recorded settings share this validated prompt."""
    def factory(store):
        model = configured_model(store, "grader_diagnostic")
        model.callbacks.append(InvocationAudit(store))
        wire = model._get_request_payload([SystemMessage(prompt), HumanMessage("")])
        settings = {"base_wire_parameters": {k: v for k, v in wire.items() if k != "messages"},
                    "system_sha256": sha(prompt), "max_retries": model.max_retries,
                    "timeout_seconds": {k: getattr(model.request_timeout, k)
                                        for k in ("connect", "read", "write", "pool")},
                    "evidence_tools": [], "response_schema": "GraderResponse",
                    "outer_revision_loop": False}
        agent = create_agent(model=model, system_prompt=prompt, tools=[],
                             response_format=GraderResponse, name="rubric_grader")
        return agent, settings
    return factory


def check_actual_input(folder, data, case, *, required=True):
    events = json.loads((folder / "model-io.json").read_text(encoding="utf-8"))
    requests = [e for e in events if e["kind"] == "deep_model_request"]
    if not requests:
        record = {"request_available": False, "evidence_complete": False}
        write_json(folder / "actual-input-check.json", record)
        if required:
            raise RuntimeError("ACTUAL_INPUT_AUDIT_MISSING")
        return record
    messages = requests[0]["data"]["messages"][0]
    system = next(m["content"] for m in messages if m["type"] == "system")
    human = next(m["content"] for m in messages if m["type"] == "human")
    record = {"request_available": True, "system_sha256": sha(system),
              "user_sha256": sha(human), "system_matches": system == data["system_prompt"],
              "user_matches": sha(human) == case["user_sha256"],
              "system_characters": len(system), "user_characters": len(human)}
    write_json(folder / "actual-input-check.json", record)
    if not record["system_matches"] or not record["user_matches"]:
        raise RuntimeError("ACTUAL_INPUT_DIFFERS_FROM_FREEZE")
    return record


async def main(args):
    data = load_inputs(args.inputs)  # Validate before credentials or paid calls.
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "batch.json", {
        "authorization": args.authorization_note,
        "input_file_sha256": hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
        "input_hashes": data["hashes"], "case_order": [c["id"] for c in data["cases"]],
        "grader_model": args.grader_model, "experiment": data["experiment"],
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    load_service_environment(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = args.grader_model
    factory = bound_factory(data["system_prompt"])
    for case in data["cases"]:
        print(json.dumps({"case": case["id"], "status": "starting"}), flush=True)
        receipt = await run_case({**data, "assignment": diagnostic_assignment(case["assignment"])}, case, args.output, factory)
        check_actual_input(args.output / case["id"], data, case, required=receipt["status"] == "completed")
        print(json.dumps({"case": case["id"], "status": receipt["status"],
                          "result": receipt.get("result"), "responses": receipt["model_responses"],
                          "tokens": sum((u or {}).get("total_tokens", 0) for u in receipt["usage"]),
                          "missing_usage": sum(u is None for u in receipt["usage"])}), flush=True)
        if receipt["status"] == "error":
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorization-note", required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--grader-model", choices=["glm-5.3", "deepseek-v4.1-flash"], default="deepseek-v4.1-flash")
    asyncio.run(main(parser.parse_args()))
