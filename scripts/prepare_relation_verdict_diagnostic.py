"""Freeze Task042 public materials and one reproducible randomized pair; no model calls."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import random
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]
PREFIX = ".analysis/task040/"
DRAFT_ID = "49a0fd72-0228-4d09-86d5-a5193a5a0018"
DRAFT_SHA = "0acf099ed36fd270774f18e42dfc55ea38abb111f1da42590b0f2beead2681f4"
ACCEPTANCE_ID = "95f221a2-b318-4158-b1f8-235aa71c6273"
ACCEPTANCE_SHA = "e4a789d64947060be81a313a01a27fc6e7c84c3110058b15b86773e47465e013"
INPUT_HASHES = {
    PREFIX + "action-observations.json": "7d590b12a78cec3774662f08c9c5186d428c146b7efb116c6c7b554cadcfaceb",
    PREFIX + "actual/results.json": "4b53ed03827d22f1a47f90f5c41b5c292b6e73fe01c637feaa62f5273a0548ad",
    PREFIX + "actual/active-criteria.json": "bbf29588dd8dd84775cc13b601dfeeedb056513b788e5e48d259d3135a43cd5b",
    PREFIX + "actual/first-request-rubric_grader.json": "aa890cb0b3ff0ee54ccfa7074a6dc7cb9309fcfa91f86c57461803a83f5c3ae8",
    PREFIX + "actual/model-io.json": "462b995bf00b14f4b23e48a0fe583a575c6cc9265d4ccc22647c3dd2d2697fa5",
    PREFIX + "actual/state.json": "1405a2f253f31378818e746dce83edda92a3030d29fec28b743a2a9926462588",
    PREFIX + f"actual/draft-{DRAFT_ID}.md": DRAFT_SHA,
    PREFIX + f"actual/acceptance-{ACCEPTANCE_ID}.md": ACCEPTANCE_SHA,
    PREFIX + "freeze.json": "ef8a768ca41dea233ae410fb1ea72bc285a49d04b290784506e18fa744e90e21",
}
SOURCE_TOOLS = {"read_source_page", "inspect_source_page", "search_sources"}
CRITERION_FIELDS = {"id", "condition", "scope", "evidence_expectation",
                    "allowed_limitations", "requirement_refs"}
RELATION_REQUEST = (
    "For each referenced item listed below, use the existing evidence.observation fields "
    "to state the report's adopted premise, the relevant source content, and what, if anything, "
    "the supplied evidence establishes about their relationship, while assessing every "
    "unchanged criterion within its stated scope."
)
TARGETS = {
    "x21": "Work point ① X21 (§4.3, Table 4-1, X21 row)",
    "r31": "R31 values (§4.2(1) and the X31 rows in Tables 4-1–4-6)",
    "height": "The proposed slope height of work point ① (§4.3(1) and Table 4-1, X11 row)",
}


def sha(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def assignment(seed):
    # This seed randomizes only the frozen experimental assignment, never the model.
    rng = random.Random(seed)
    mapping = {arm: f"{rng.getrandbits(48):012x}" for arm in ("A", "B")}
    targets = list(TARGETS)
    rng.shuffle(targets)
    arms = ["A", "B"]
    rng.shuffle(arms)
    return {"seed": seed, "arm_case_ids": mapping, "target_order": targets,
            "case_order": [mapping[arm] for arm in arms]}


def suffix(fixed):
    return "\n\n" + RELATION_REQUEST + "\n" + "\n".join(
        f"- {TARGETS[key]}" for key in fixed["target_order"])


def model_message(case, fixed):
    from run_stance_diagnostic import user_message
    base = user_message(case, "neutral")
    return base + (suffix(fixed) if case["id"] == fixed["arm_case_ids"]["B"] else "")


def checked_files(root, expected, *, read=False):
    values = {}
    for name, digest in expected.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("PROVENANCE_PATH_OUTSIDE_REPOSITORY")
        if read:
            raw = path.read_bytes()
            actual = sha(raw)
            values[name] = raw
        else:
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise ValueError(f"FROZEN_INPUT_CHANGED: {name}")
    return values


def verified_observations(observations, public_events):
    selected = [row for row in observations
                if row["sequence"] >= 353 and row["tool"] in SOURCE_TOOLS]
    if not selected or len({row["tool_call_id"] for row in selected}) != len(selected):
        raise ValueError("SOURCE_OBSERVATION_IDENTITY")
    requests = {event["sequence"]: event["data"] for event in public_events
                if event["kind"] == "deep_model_request"}
    for row in selected:
        if (row["role"] != "rubric_grader" or row["tool_message_status"] != "success"
                or not isinstance(row["observation"], dict)
                or row["observation"].get("accepted") is False):
            raise ValueError("SUCCESSFUL_GRADER_SOURCE_REQUIRED")
        request = requests[row["received_in_request"]]
        messages = [msg for batch in request["messages"] for msg in batch
                    if msg.get("type") == "tool" and msg.get("tool_call_id") == row["tool_call_id"]]
        if request["role"] != "rubric_grader" or len(messages) != 1:
            raise ValueError("ACTUAL_SOURCE_RECEIPT_MISSING")
        message = messages[0]
        if (message.get("status") != "success" or sha(message["content"]) != row["observation_sha256"]
                or json.loads(message["content"]) != row["observation"]):
            raise ValueError("SOURCE_CALLBACK_CONTENT_MISMATCH")
    # Retain all original records, return structure, strings, order and repetitions.
    return selected


def extract_materials(results, active, first_request, observations, public_events):
    drafts = [row for row in results if row["id"] == DRAFT_ID and row["kind"] == "draft"]
    standards = [row for row in results if row["id"] == ACCEPTANCE_ID and row["kind"] == "acceptance"]
    if (len(drafts) != 1 or len(standards) != 1
            or any(active.get(key) != standards[0].get(key) for key in ("id", "kind", "body"))
            or sha(drafts[0]["body"]) != DRAFT_SHA or sha(active["body"]) != ACCEPTANCE_SHA):
        raise ValueError("ORIGINAL_RESULT_IDENTITY_OR_BODY")
    standard = json.loads(active["body"])
    criteria = standard["criteria"]
    if len(criteria) != 6 or any(set(row) != CRITERION_FIELDS for row in criteria):
        raise ValueError("SIX_COMPLETE_ORIGINAL_CRITERIA_REQUIRED")
    if first_request["sequence"] != 353 or first_request["role"] != "rubric_grader":
        raise ValueError("ACTUAL_FIRST_GRADER_REQUEST_REQUIRED")
    human = [msg for batch in first_request["messages"] for msg in batch if msg["type"] == "human"]
    if len(human) != 1:
        raise ValueError("ACTUAL_RUBRIC_SECTION_REQUIRED")
    match = re.search(r"\n<rubric-([^>]+)>\n(.*?)\n</rubric-\1>", human[0]["content"], re.S)
    actual = json.loads(match[2][match[2].index('{"acceptance_identity"'):]) if match else {}
    if (actual.get("criteria") != criteria or actual.get("acceptance_identity") != {
            "criteria_id": ACCEPTANCE_ID, "body_hash": ACCEPTANCE_SHA, "basis_hash": standard["basis_hash"]}):
        raise ValueError("ACTUAL_CRITERION_DEFINITIONS_DIFFER")
    selected = verified_observations(observations, public_events)
    return {"commission": standard["requirement_basis"]["goal"],
            "source": json.dumps(selected, ensure_ascii=False),
            "rubric": json.dumps({"criteria": criteria}, ensure_ascii=False),
            "candidate": drafts[0]["body"]}, selected


def runtime_files(root=ROOT):
    paths = list((root/"src/report_agent").rglob("*.py"))
    paths += list((root/"src/report_agent/rules").glob("*.md"))
    paths += [root/"pyproject.toml"] + [root/"scripts"/name for name in (
        "prepare_relation_verdict_diagnostic.py", "run_relation_verdict_diagnostic.py",
        "run_stance_diagnostic.py", "run_grader_diagnostic.py", "run_deepagents_trial.py")]
    return {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in sorted(set(paths))}


def build(seed, root=ROOT):
    raw = checked_files(root, INPUT_HASHES, read=True)
    get = lambda name: json.loads(raw[PREFIX + name])
    fields, selected = extract_materials(get("actual/results.json"), get("actual/active-criteria.json"),
        get("actual/first-request-rubric_grader.json"), get("action-observations.json"), get("actual/model-io.json"))
    if len(selected) != 15 or fields["candidate"].encode("utf-8") != raw[PREFIX+f"actual/draft-{DRAFT_ID}.md"]:
        raise ValueError("COMPLETE_TASK040_MATERIALS_REQUIRED")
    source_files = {".runs/task040/feedback-recovery/" + name: digest
                    for name, digest in get("freeze.json")["baseline_files_sha256"].items()
                    if name.startswith("sources/")}
    checked_files(root, source_files)
    fixed = assignment(seed)
    cases = [{"id": fixed["arm_case_ids"][arm], **fields} for arm in ("A", "B")]
    data = {"version": "relation-verdict-controls-v1", "cases": cases}
    receipt = {
        "version": "relation-verdict-preparation-v1", "assignment": fixed,
        "augmentation": suffix(fixed), "model_inputs_sha256": sha(encoded(data)),
        "frozen_input_files": {**INPUT_HASHES, **source_files}, "runtime_files": runtime_files(root),
        "runtime_versions": {name: version(name) for name in
                             ("deepagents", "langchain", "langchain-openai", "langgraph", "openai")},
        "field_sha256": {key: sha(value) for key, value in fields.items()},
        "field_characters": {key: len(value) for key, value in fields.items()},
        "message_sha256": {case["id"]: sha(model_message(case, fixed)) for case in cases},
        "message_characters": {case["id"]: len(model_message(case, fixed)) for case in cases},
        "original_draft_id": DRAFT_ID, "original_draft_body_sha256": DRAFT_SHA,
        "original_acceptance_id": ACCEPTANCE_ID, "original_acceptance_body_sha256": ACCEPTANCE_SHA,
        "criteria_equal_actual_first_request": True,
        "source_sequences": [row["sequence"] for row in selected],
        "source_callback_hashes": {row["tool_call_id"]: row["observation_sha256"] for row in selected},
        "field_origins": {
            "commission": "Original acceptance body.requirement_basis.goal; exact string.",
            "rubric": "Original acceptance body.criteria; all six fields/values, checked against Task040 request353.",
            "candidate": "Task040 replacement draft body; exact complete string including its own revision notes.",
            "source": "All15 successful source-tool records after353 from action-observations, checked against the actual received public tool content; ordered JSON serialization only, no deduplication, summary or truncation.",
        },
        "limits": ["Fresh inline judgment, not exact Task040 replay or autonomous retrieval.",
                   "Source image references remain text; no images are newly retrieved or attached.",
                   "Original source files are hashed for provenance only; only the selected observations reach the model.",
                   "One attempt per arm; no stable effect, causal mechanism, native success or whole-report gold claim.",
                   "Oracle, arm mapping, historical verdicts and development feedback are not serialized into model messages."],
    }
    checked_files(root, receipt["frozen_input_files"])
    return data, receipt


def prepare(output, seed=None):
    if output.exists():
        raise FileExistsError("REFUSE_EXISTING_PREPARATION")
    data, receipt = build(secrets.randbits(64) if seed is None else seed)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("model-inputs.json", data), ("input-receipt.json", receipt)):
        with (output/name).open("xb") as stream:
            stream.write(encoded(value))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/".analysis/task042/frozen")
    parser.add_argument("--seed", type=int, help="Reconstruct a recorded assignment; never a model seed.")
    args = parser.parse_args()
    receipt = prepare(args.output, args.seed)
    print(json.dumps({"input_sha256": receipt["model_inputs_sha256"],
                      "message_characters": receipt["message_characters"],
                      "order": receipt["assignment"]["case_order"]}))
