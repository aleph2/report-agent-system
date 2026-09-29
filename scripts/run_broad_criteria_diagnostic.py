"""Two fresh broad-criteria judgments with frozen supplied evidence; no oracle."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from run_stance_diagnostic import (CASE_FIELDS, GraderResponse, criterion_ids,
                                  freeze_files, load_service_environment,
                                  reviewer_prompt, run_one, write_json)


def load_inputs(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if (set(data) != {"version", "cases"} or data["version"] != "broad-criteria-controls-v1"
            or not isinstance(data["cases"], list) or len(data["cases"]) != 1):
        raise ValueError("ONE_FROZEN_MODEL_CASE_REQUIRED")
    case = data["cases"][0]
    if (set(case) != CASE_FIELDS or any(not isinstance(v, str) or not v for v in case.values())
            or not re.fullmatch(r"[0-9a-f]{12}", case["id"])):
        raise ValueError("MODEL_INPUT_FIELDS_ONLY")
    if len(criterion_ids(case)) != 6:
        raise ValueError("SIX_ORIGINAL_CRITERIA_REQUIRED")
    return case


def frozen_files(inputs):
    frozen = freeze_files(inputs)
    root = Path(__file__).resolve().parents[1]
    for path in (Path(__file__), root/"scripts/prepare_broad_criteria_diagnostic.py"):
        frozen[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return frozen


async def run_batch(args, *, invoke=run_one, credentials_loader=load_service_environment):
    case = load_inputs(args.inputs)
    frozen = frozen_files(args.inputs)
    prompt = reviewer_prompt(requirement_acceptance=True)
    schema = GraderResponse.model_json_schema()
    order = [{"case_id": case["id"], "repeat": repeat} for repeat in (0, 1)]
    root = args.output
    if args.resume:
        if not args.diagnosis_note:
            raise ValueError("DIAGNOSED_CONTINUATION_REQUIRED")
        batch = json.loads((root/"batch.json").read_text(encoding="utf-8"))
        if (batch["status"] != "needs_diagnosis" or batch["frozen_files"] != frozen
                or batch["system_prompt"] != prompt or batch["response_schema"] != schema
                or batch["order"] != order):
            raise ValueError("FROZEN_CONTINUATION_MISMATCH")
        first = root/f"{case['id']}-0"/"receipt.json"
        if (not first.exists() or (root/f"{case['id']}-1").exists()
                or json.loads(first.read_text(encoding="utf-8"))["status"] != "error"):
            raise ValueError("ONLY_UNATTEMPTED_SECOND_CELL_CAN_CONTINUE")
        backup = root/"batch.before-continuation.json"
        if backup.exists():
            raise ValueError("CONTINUATION_ALREADY_CLAIMED")
        backup.write_bytes((root/"batch.json").read_bytes())
        batch["continuation"] = {"at": datetime.now(timezone.utc).isoformat(),
                                 "diagnosis": args.diagnosis_note}
    else:
        root.mkdir(parents=True, exist_ok=False)
        batch = {"authorization": args.authorization_note, "order": order,
                 "frozen_files": frozen, "system_prompt": prompt, "response_schema": schema,
                 "scope": "Broad original commission/criteria, developer-supplied source pages; no autonomous retrieval or author."}
    batch["status"] = "running"
    write_json(root/"batch.json", batch)
    credentials_loader(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = "glm-5.3"
    for cell in order:
        name = f"{case['id']}-{cell['repeat']}"
        if (root/name).exists():
            continue  # Only the diagnosed, preserved first error is allowed above.
        if frozen_files(args.inputs) != frozen:
            raise RuntimeError("FROZEN_INPUT_OR_RUNTIME_CHANGED")
        print(json.dumps({"run": name, "status": "starting"}), flush=True)
        receipt = await invoke(root/name, case, "neutral", cell["repeat"], prompt)
        print(json.dumps({k: v for k, v in receipt.items() if k != "usage"}, ensure_ascii=False), flush=True)
        if receipt["status"] != "completed":
            batch.update(status="needs_diagnosis" if cell["repeat"] == 0 else "completed_with_errors",
                         stopped_at=name)
            break
    else:
        statuses = [json.loads((root/f"{case['id']}-{i}"/"receipt.json")
                    .read_text(encoding="utf-8"))["status"] for i in (0, 1)]
        batch["status"] = "completed_with_errors" if "error" in statuses else "completed"
    batch.update(ended=datetime.now(timezone.utc).isoformat(),
                 postflight_matches=frozen_files(args.inputs) == frozen)
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
