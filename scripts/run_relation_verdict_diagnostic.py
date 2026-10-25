"""Run a frozen Task042 pair; preserve errors and require diagnosed suffix continuation."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from langchain_core.messages import HumanMessage

from prepare_relation_verdict_diagnostic import (ROOT, assignment, build, checked_files,
    model_message, sha, suffix)
from run_stance_diagnostic import (CASE_FIELDS, GraderResponse, Store, criterion_ids,
    error_data, load_service_environment, real_factory, reviewer_prompt, write_json)


def load_inputs(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if (set(data) != {"version", "cases"} or data["version"] != "relation-verdict-controls-v1"
            or not isinstance(data["cases"], list) or len(data["cases"]) != 2):
        raise ValueError("TWO_FROZEN_MODEL_CASES_REQUIRED")
    seen = set()
    for case in data["cases"]:
        if (set(case) != CASE_FIELDS or any(not isinstance(v, str) or not v for v in case.values())
                or not re.fullmatch(r"[0-9a-f]{12}", case["id"]) or case["id"] in seen
                or len(criterion_ids(case)) != 6):
            raise ValueError("MODEL_INPUT_FIELDS_ONLY")
        seen.add(case["id"])
    if any(data["cases"][0][key] != data["cases"][1][key] for key in CASE_FIELDS - {"id"}):
        raise ValueError("IDENTICAL_MATERIALS_REQUIRED")
    receipt = json.loads(path.with_name("input-receipt.json").read_text(encoding="utf-8"))
    fixed = receipt["assignment"]
    if (fixed != assignment(fixed["seed"]) or receipt["augmentation"] != suffix(fixed)
            or seen != set(fixed["case_order"]) or receipt["model_inputs_sha256"] != sha(path.read_bytes())):
        raise ValueError("FROZEN_ASSIGNMENT_OR_INPUT_MISMATCH")
    # Reconstruct from the immutable public provenance, not from labels or prior answers.
    expected_data, expected_receipt = build(fixed["seed"])
    if data != expected_data or receipt != expected_receipt:
        raise ValueError("FROZEN_PREPARATION_MISMATCH")
    return data, receipt


def frozen_files(inputs, preparation):
    files = {**preparation["runtime_files"], **preparation["frozen_input_files"]}
    checked_files(ROOT, files)
    files.update({str(inputs.resolve()): sha(inputs.read_bytes()),
                  str(inputs.with_name("input-receipt.json").resolve()):
                  sha(inputs.with_name("input-receipt.json").read_bytes())})
    return files


async def run_one(root, case, message, prompt, factory=real_factory):
    """Same adapter/schema/audit as037; accept the exact predeclared message suffix."""
    root.mkdir(parents=True, exist_ok=False)
    store = Store(root)
    receipt = {"case_id": case["id"], "started": datetime.now(timezone.utc).isoformat(),
               "status": "attempted", "system_sha256": sha(prompt), "user_sha256": sha(message),
               "scope": "Fresh inline judgment; no retrieval tools, author or outer revision loop."}
    write_json(root/"input.json", {"system": prompt, "user": message})
    write_json(root/"receipt.json", receipt)
    try:
        agent, settings = factory(store, prompt)
        write_json(root/"settings.json", settings)
        result = await agent.ainvoke({"messages": [HumanMessage(message)]})
        # Do not serialize the full agent state or inspect private reasoning.
        public = GraderResponse.model_validate(result["structured_response"]).model_dump(mode="json")
        write_json(root/"output.json", public)
        if [row["name"] for row in public["criteria"]] != criterion_ids(case):
            raise ValueError("CRITERION_COVERAGE_MISMATCH")
        receipt.update(status="completed", result=public["result"], exact_criterion_coverage=True)
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    events = store.events()  # LocalAudit's public, reasoning-stripped observations.
    responses = [event["data"] for event in events if event["kind"] == "deep_model_response"]
    receipt.update(ended=datetime.now(timezone.utc).isoformat(),
                   model_requests=sum(event["kind"] == "deep_model_request" for event in events),
                   model_responses=len(responses), usage=[row.get("usage") for row in responses])
    write_json(root/"model-io.json", events)
    write_json(root/"receipt.json", receipt)
    return receipt


async def run_batch(args, *, invoke=run_one, credentials_loader=load_service_environment):
    data, preparation = load_inputs(args.inputs)  # No oracle file argument or read path.
    frozen = frozen_files(args.inputs, preparation)
    prompt = reviewer_prompt(requirement_acceptance=True)
    schema = GraderResponse.model_json_schema()
    order = preparation["assignment"]["case_order"]
    root = args.output.resolve()
    if args.resume:
        if not args.diagnosis_note.strip():
            raise ValueError("DIAGNOSED_CONTINUATION_REQUIRED")
        batch = json.loads((root/"batch.json").read_text(encoding="utf-8"))
        if (batch["status"] != "needs_diagnosis" or batch["frozen_files"] != frozen
                or batch["system_prompt"] != prompt or batch["response_schema"] != schema
                or batch["order"] != order):
            raise ValueError("FROZEN_CONTINUATION_MISMATCH")
        first = root/order[0]/"receipt.json"
        if (not first.exists() or (root/order[1]).exists()
                or json.loads(first.read_text(encoding="utf-8"))["status"] != "error"):
            raise ValueError("ONLY_UNATTEMPTED_SUFFIX_CAN_CONTINUE")
        # Claim once; retain the failed cell and original batch byte-for-byte.
        with (root/"batch.before-continuation.json").open("xb") as stream:
            stream.write((root/"batch.json").read_bytes())
        batch["continuation"] = {"at": datetime.now(timezone.utc).isoformat(),
                                 "diagnosis": args.diagnosis_note,
                                 "authorization": args.authorization_note}
    else:
        root.mkdir(parents=True, exist_ok=False)
        batch = {"authorization": args.authorization_note, "order": order,
                 "frozen_files": frozen, "system_prompt": prompt, "response_schema": schema,
                 "intended_model": "glm-5.3", "reasoning_effort": "high",
                 "runtime_versions": preparation.get("runtime_versions", {}),
                 "assignment": preparation["assignment"],
                 "scope": "Task040 materials supplied inline; not native replay, autonomous retrieval or a causal effect estimate."}
    batch["status"] = "running"
    write_json(root/"batch.json", batch)
    cases = {case["id"]: case for case in data["cases"]}
    try:
        credentials_loader(args.credential_container)
        os.environ["REPORT_GRADER_MODEL"] = "glm-5.3"
        for index, identifier in enumerate(order):
            if args.resume and index == 0:
                continue  # Only the diagnosed first error is permitted above.
            if frozen_files(args.inputs, preparation) != frozen:
                raise ValueError("FROZEN_INPUT_OR_RUNTIME_CHANGED")
            print(json.dumps({"case_id": identifier, "status": "starting"}), flush=True)
            receipt = await invoke(root/identifier, cases[identifier],
                model_message(cases[identifier], preparation["assignment"]), prompt)
            print(json.dumps({k: v for k, v in receipt.items() if k != "usage"}, ensure_ascii=False), flush=True)
            if receipt["status"] != "completed":
                batch.update(status="needs_diagnosis", stopped_at=identifier)
                break
        else:
            statuses = [json.loads((root/identifier/"receipt.json").read_text(encoding="utf-8"))["status"]
                        for identifier in order]
            batch["status"] = "completed_with_errors" if "error" in statuses else "completed"
    except Exception as exc:
        batch.update(status="needs_diagnosis", execution_error=error_data(exc))
    try:
        batch["postflight_matches"] = frozen_files(args.inputs, preparation) == frozen
    except (OSError, ValueError):
        batch["postflight_matches"] = False
    if not batch["postflight_matches"]:
        batch["status"] = "needs_diagnosis"
    batch["ended"] = datetime.now(timezone.utc).isoformat()
    write_json(root/"batch.json", batch)
    return batch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--diagnosis-note", default="")
    asyncio.run(run_batch(parser.parse_args()))
