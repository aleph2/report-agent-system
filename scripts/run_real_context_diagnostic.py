"""Frozen real-evidence context controls; no evaluator labels or business writes."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re

from run_stance_diagnostic import (CASE_FIELDS, GraderResponse, criterion_ids,
                                  freeze_files, load_service_environment,
                                  reviewer_prompt, run_one, write_json)


def load_inputs(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"version", "cases"} or data["version"] != "context-controls-v1":
        raise ValueError("MODEL_INPUT_FIELDS_ONLY")
    if not isinstance(data["cases"], list) or len(data["cases"]) != 4:
        raise ValueError("FOUR_FROZEN_CONDITIONS_REQUIRED")
    seen = set()
    for case in data["cases"]:
        if (set(case) != CASE_FIELDS or any(not isinstance(v, str) or not v for v in case.values())
                or not re.fullmatch(r"[0-9a-f]{12}", case["id"]) or case["id"] in seen):
            raise ValueError("INVALID_MODEL_CASE")
        if len(criterion_ids(case)) != 2:
            raise ValueError("TWO_SEPARATE_PREDICATES_REQUIRED")
        seen.add(case["id"])
    first = data["cases"][0]
    if any(case[key] != first[key] for case in data["cases"]
           for key in ("commission", "source", "rubric")):
        raise ValueError("ONLY_CANDIDATE_CONTEXT_MAY_DIFFER")
    return data


def frozen_files(inputs):
    frozen = freeze_files(inputs)
    root = Path(__file__).resolve().parents[1]
    for path in (Path(__file__), root/"scripts/prepare_real_context_diagnostic.py"):
        frozen[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return frozen


def schedule(cases, seed):
    order = [case["id"] for case in cases]
    random.Random(seed).shuffle(order)
    # Reverse the second block so each condition occupies complementary positions.
    return [{"case_id": case_id, "repeat": repeat}
            for repeat, block in enumerate((order, list(reversed(order)))) for case_id in block]


async def run_batch(args, *, invoke=run_one, credentials_loader=load_service_environment):
    data = load_inputs(args.inputs)
    frozen = frozen_files(args.inputs)
    prompt = reviewer_prompt(requirement_acceptance=True)
    schema = GraderResponse.model_json_schema()
    root = args.output
    if args.resume:
        if not args.diagnosis_note:
            raise ValueError("DIAGNOSED_CONTINUATION_NOTE_REQUIRED")
        batch = json.loads((root/"batch.json").read_text(encoding="utf-8"))
        if (batch["status"] != "needs_diagnosis" or batch["frozen_files"] != frozen
                or batch["system_prompt"] != prompt or batch["response_schema"] != schema):
            raise ValueError("FROZEN_CONTINUATION_MISMATCH")
        if batch["order"] != schedule(data["cases"], batch["seed"]):
            raise ValueError("DECLARED_ORDER_MISMATCH")
        terminal = []
        pending_seen = False
        for cell in batch["order"]:
            name = f"{cell['case_id']}-{cell['repeat']}"
            path = root/name
            if not path.exists():
                pending_seen = True
                continue
            if pending_seen:
                raise ValueError("ATTEMPTS_ARE_NOT_AN_ORDERED_PREFIX")
            receipt = json.loads((path/"receipt.json").read_text(encoding="utf-8"))
            if receipt["status"] not in ("completed", "error"):
                raise ValueError("UNRESOLVED_ATTEMPT_NOT_REPLAYABLE")
            terminal.append(name)
        number = len(batch["continuations"]) + 1
        backup = root/f"batch.before-continuation-{number}.json"
        if backup.exists():
            raise ValueError("CONTINUATION_ALREADY_CLAIMED")
        backup.write_bytes((root/"batch.json").read_bytes())
        batch["continuations"].append({"at": datetime.now(timezone.utc).isoformat(),
            "diagnosis": args.diagnosis_note, "preserved_terminal_cells": terminal})
    else:
        root.mkdir(parents=True, exist_ok=False)
        batch = {"authorization": args.authorization_note, "seed": args.seed,
                 "order": schedule(data["cases"], args.seed), "frozen_files": frozen,
                 "system_prompt": prompt, "response_schema": schema,
                 "scope": "Known-claim rule application, local versus full candidate context; no autonomous discovery, author or retrieval.",
                 "status": "attempted", "continuations": []}
    batch["status"] = "running"
    write_json(root/"batch.json", batch)
    credentials_loader(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = "glm-5.3"
    cases = {case["id"]: case for case in data["cases"]}
    for cell in batch["order"]:
        name = f"{cell['case_id']}-{cell['repeat']}"
        if (root/name).exists():
            continue  # Validated terminal prefix; failed cells are preserved too.
        if frozen_files(args.inputs) != frozen:
            raise RuntimeError("FROZEN_INPUT_OR_RUNTIME_CHANGED")
        print(json.dumps({"run": name, "status": "starting"}), flush=True)
        receipt = await invoke(root/name, cases[cell["case_id"]], "neutral", cell["repeat"], prompt)
        print(json.dumps({k: v for k, v in receipt.items() if k != "usage"}, ensure_ascii=False), flush=True)
        if receipt["status"] != "completed":
            batch.update(status="needs_diagnosis", stopped_at=name)
            break
    else:
        statuses = [json.loads((root/f"{c['case_id']}-{c['repeat']}"/"receipt.json")
                    .read_text(encoding="utf-8"))["status"] for c in batch["order"]]
        batch["status"] = "completed_with_errors" if "error" in statuses else "completed"
    batch.update(ended=datetime.now(timezone.utc).isoformat(),
                 postflight_matches=frozen_files(args.inputs) == frozen)
    write_json(root/"batch.json", batch)
    return batch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=380929)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--diagnosis-note", default="")
    asyncio.run(run_batch(parser.parse_args()))
