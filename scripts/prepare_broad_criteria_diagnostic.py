"""Prepare Task039's original-report/broad-criteria input without model or runtime access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "9c8c1f6128dc"
ORIGINAL_FULL_CASE = "62a14e5d301b"
DRAFT_ID = "b3452830-1325-47a5-92d5-8580f3800eb3"
DRAFT_SHA = "07c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7"
ACCEPTANCE_ID = "77303599-fad3-4468-8e0a-a442436c5e03"
ACCEPTANCE_SHA = "7a197764a53ec3768b4aa939445aea655641a3f4066595a0522d974acfa5a225"
GOAL_SHA = "a0637c7c3e3b2d377cda50d7e29ee424f14753884996c2d12b0ffff258f5cd87"
SOURCE_SHA = "d6a8958de2f95b3f85b247ceef7bd935470905bd773625d7a3c1ba19750e35eb"
INPUT_HASHES = {
    ".analysis/task038/frozen/model-inputs.json": "a196efb76a37c3201ca54e3ead7f0fb265041d881e6ed7d13de29860845544f5",
    ".analysis/task038/frozen/input-receipt.json": "bd69e409f6a2d0358cbbdef82c214affac0afc386b6f1bb3fb9690f90e3a5094",
    ".analysis/task034/probe-results.json": "c339d3be222c9f64d1ad6899d15da4fcb3ca02e14d3af66be30ad78bcfee0ebc",
    ".runs/task034/native-probe/input.json": "620b799ed26ef918bec139227f3265c073ac2c6d245cf21bef129c7bfa0e8426",
    ".runs/task034/native-probe/sources/路堑高边坡施工安全评价指南.pdf": "f063d3f281232a2c7057a8ab832e1e5d0f2262222df72fdf4edbe941b6ac8e98",
}
CRITERION_FIELDS = {"id", "condition", "evidence_expectation", "allowed_limitations",
                    "requirement_refs", "scope"}


def sha(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def checked_inputs(root: Path) -> dict[str, bytes]:
    values = {}
    for name, expected in INPUT_HASHES.items():
        raw = (root / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError(f"FROZEN_INPUT_CHANGED: {name}")
        values[name] = raw
    return values


def build(root: Path = ROOT):
    inputs = checked_inputs(root)
    original_results = json.loads(inputs[".analysis/task034/probe-results.json"])
    draft = [r for r in original_results if r["id"] == DRAFT_ID and r["kind"] == "draft"]
    standards = [r for r in original_results if r["id"] == ACCEPTANCE_ID and r["kind"] == "acceptance"]
    if len(draft) != 1 or len(standards) != 1:
        raise ValueError("ORIGINAL_RESULT_IDENTITY")
    if sha(draft[0]["body"]) != DRAFT_SHA or sha(standards[0]["body"]) != ACCEPTANCE_SHA:
        raise ValueError("ORIGINAL_RESULT_BODY_CHANGED")
    standard = json.loads(standards[0]["body"])
    commission = standard["requirement_basis"]["goal"]
    criteria = standard["criteria"]
    if sha(commission) != GOAL_SHA:
        raise ValueError("ORIGINAL_REQUIREMENT_GOAL_CHANGED")
    if len(criteria) != 6 or any(set(row) != CRITERION_FIELDS for row in criteria):
        raise ValueError("COMPLETE_ORIGINAL_CRITERIA_REQUIRED")

    # Check the saved standard against the actual Task034 initial user input;
    # keep only criteria, not its wrapper, transcript, saved verdict or import note.
    original_input = json.loads(inputs[".runs/task034/native-probe/input.json"])
    rubric_section = original_input["user_message"].split("\n<rubric-", 1)[1]
    rubric_section = rubric_section.split("\n</rubric-", 1)[0].split(">\n", 1)[1]
    actual_rubric = json.loads(rubric_section[rubric_section.index('{"acceptance_identity"'):])
    if actual_rubric["criteria"] != criteria:
        raise ValueError("ACTUAL_CRITERION_DEFINITIONS_DIFFER")
    criterion_ids = [row["id"] for row in criteria]
    if criterion_ids != original_input["criteria_ids"] or len(set(criterion_ids)) != 6:
        raise ValueError("ACTUAL_CRITERION_IDS_DIFFER")

    prior = json.loads(inputs[".analysis/task038/frozen/model-inputs.json"])
    prior_receipt = json.loads(inputs[".analysis/task038/frozen/input-receipt.json"])
    cases = [case for case in prior["cases"] if case["id"] == ORIGINAL_FULL_CASE]
    if prior["version"] != "context-controls-v1" or len(cases) != 1:
        raise ValueError("TASK038_ORIGINAL_FULL_CASE_REQUIRED")
    original_full = cases[0]
    if original_full["candidate"] != draft[0]["body"] or sha(original_full["source"]) != SOURCE_SHA:
        raise ValueError("UNCHANGED_SOURCE_AND_REPORT_REQUIRED")
    if prior_receipt["model_inputs_sha256"] != INPUT_HASHES[".analysis/task038/frozen/model-inputs.json"]:
        raise ValueError("TASK038_RECEIPT_BINDING")

    case = {"id": CASE_ID, "commission": commission, "source": original_full["source"],
            "rubric": json.dumps({"criteria": criteria}, ensure_ascii=False),
            "candidate": original_full["candidate"]}
    model_inputs = {"version": "broad-criteria-controls-v1", "cases": [case]}
    receipt = {
        "version": "broad-criteria-preparation-v1",
        "script_sha256": sha(Path(__file__).read_bytes()),
        "frozen_input_files": INPUT_HASHES,
        "case_id": CASE_ID,
        "field_origins": {
            "id": "Random nonsemantic identifier fixed before model calls.",
            "commission": f".analysis/task034/probe-results.json: result {ACCEPTANCE_ID}, JSON body.requirement_basis.goal; exact string.",
            "source": f".analysis/task038/frozen/model-inputs.json: case {ORIGINAL_FULL_CASE}.source; exact string.",
            "rubric": f".analysis/task034/probe-results.json: result {ACCEPTANCE_ID}, JSON body.criteria; all original fields/values and IDs, checked against actual Task034 input.json.",
            "candidate": f".analysis/task038/frozen/model-inputs.json: case {ORIGINAL_FULL_CASE}.candidate; exact string, equal to Task034 draft body {DRAFT_ID}.",
        },
        "field_sha256": {key: sha(case[key]) for key in ("commission", "source", "rubric", "candidate")},
        "field_characters": {key: len(case[key]) for key in ("commission", "source", "rubric", "candidate")},
        "original_acceptance_id": ACCEPTANCE_ID,
        "original_acceptance_body_sha256": ACCEPTANCE_SHA,
        "original_draft_id": DRAFT_ID,
        "original_draft_body_sha256": DRAFT_SHA,
        "criterion_ids": criterion_ids,
        "criterion_definitions_equal_actual_task034": True,
        "guide_tool_call_id": prior_receipt["guide_tool_call_id"],
        "guide_public_request_sequence": prior_receipt["guide_public_request_sequence"],
        "guide_observation_sha256": prior_receipt["guide_observation_sha256"],
        "guide_blocks": prior_receipt["guide_blocks"],
        "planned_fresh_repetitions": 2,
        "model_inputs_sha256": sha(encoded(model_inputs)),
        "oracle_file": ".ase/verification/039-fixture-oracle.md",
        "excluded_from_model_inputs": ["oracle", "old verdict", "known-error location hints",
                                       "development feedback", "expected outcomes", "Task038 counterfactual"],
        "limits": [
            "Guide physical pages20–22 are supplied directly, not autonomously retrieved.",
            "Original commission and all six broad criteria replace both the narrow Task038 commission and criteria.",
            "Only the original report is used; no whole-report positive control or false-positive-rate estimate.",
            "The oracle has a supported C2 counterexample baseline, not a complete gold verdict for all six criteria.",
            "Other original design/geology/format documents are not added; evaluate claims against actual evidence scope.",
            "No business report repair, native retrieval trajectory, author loop, engineering approval or deployment is tested.",
        ],
    }
    checked_inputs(root)
    return model_inputs, receipt


def main(output: Path):
    model_inputs, receipt = build()
    outputs = {output / "model-inputs.json": encoded(model_inputs),
               output / "input-receipt.json": encoded(receipt)}
    for path, content in outputs.items():
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"REFUSE_DIFFERENT_EXISTING_OUTPUT: {path}")
    output.mkdir(parents=True, exist_ok=True)
    for path, content in outputs.items():
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(content)
    print(json.dumps({"model_inputs": str(output / "model-inputs.json"),
                      "sha256": receipt["model_inputs_sha256"], "cases": 1}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".analysis/task039/frozen")
    main(parser.parse_args().output)
