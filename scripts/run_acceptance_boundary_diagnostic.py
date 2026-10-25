"""Synthetic native-grader controls; labels never enter this process.

This exercises the application's actual criterion storage, pinned export, evidence
tools and grader graph. It does not run an author or the outer revision loop.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from report_agent import review as review_module
from report_agent.acceptance import (AcceptanceCriterionInput, active_criteria,
                                     bind_mode, criteria_rules, save_criteria)
from report_agent.acceptance_review import GraderResponse
from report_agent.deep_models import configured_model, error_data
from report_agent.deep_runtime import BusinessBoundary, business_tools, project_view
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from run_deepagents_trial import load_service_environment
from run_grader_diagnostic import InvocationAudit, sha, write_json


ARMS = {
    "baseline": ("baseline", "baseline"),
    "criteria_only": ("clear_boundary", "baseline"),
    "criteria_and_grader": ("clear_boundary", "candidate"),
}


def load_inputs(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"commission", "scope_instruction", "source_sets", "criteria_sets", "reports"}:
        raise ValueError("MODEL_INPUT_FIELDS_ONLY")
    if set(data["criteria_sets"]) != {"baseline", "clear_boundary"}:
        raise ValueError("PAIRED_CRITERIA_REQUIRED")
    for entries in data["criteria_sets"].values():
        if not entries:
            raise ValueError("EMPTY_CRITERIA")
        for row in entries:
            AcceptanceCriterionInput.model_validate(row)
    for sources in data["source_sets"].values():
        if any(set(source) != {"id", "title", "coverage", "content"} for source in sources):
            raise ValueError("UNEXPECTED_SOURCE_FIELDS")
    seen = set()
    for report in data["reports"]:
        if (set(report) != {"case_id", "title", "source_set", "body"}
                or report["source_set"] not in data["source_sets"]
                or report["case_id"] in seen
                or not report["case_id"].replace("_", "").isalnum()):
            raise ValueError("INVALID_CASE")
        seen.add(report["case_id"])
    if not seen:
        raise ValueError("EMPTY_CASES")
    return data


def prepare_workspace(root, data, case, arm):
    store = Store(root)
    sources = data["source_sets"][case["source_set"]]
    store.initialize({"name": "Synthetic acceptance boundary diagnostic",
                      "goal": data["commission"] + "\n" + data["scope_instruction"],
                      "sources": sources})
    ws = Workspace(store)
    ws.initialize()
    store.set("knowledge_enabled", False)
    bind_mode(ws)
    criteria = save_criteria(ws, actor="coordinator", title="Synthetic diagnostic standards",
                             criteria=data["criteria_sets"][ARMS[arm][0]],
                             source_ids=[s["id"] for s in sources], input_ids=[],
                             reason="Tester-authored equivalent standards for an isolated diagnostic; not model-generated.")
    task = ws.request_task("draft", "Preserve synthetic candidate for diagnosis", [])
    draft = ws.submit(task["id"], actor="writer", title=case["title"], body=case["body"],
                      source_ids=[s["id"] for s in sources], input_ids=[criteria["id"]])
    ws.select_delivery(draft["id"], "")
    return ws


async def run_one(root, data, case, arm, repeat, prompt):
    root.mkdir(parents=True, exist_ok=False)
    receipt = {"case_id": case["case_id"], "arm": arm, "repeat": repeat,
               "started": datetime.now(timezone.utc).isoformat(), "status": "attempted",
               "candidate_sha256": sha(case["body"]), "system_sha256": sha(prompt),
               "synthetic": True, "outer_revision_loop": False}
    write_json(root / "receipt.json", receipt)
    ws = prepare_workspace(root, data, case, arm)
    try:
        model = configured_model(ws.store, "rubric_grader")
        model.callbacks.append(InvocationAudit(ws.store))
        text_model = configured_model(ws.store, "text_tool")
        names = {"project_status", "read_source_page", "search_sources", "inspect_source_page",
                 "analyze_source_image", "calculate", "read_result", "analyze_text",
                 "knowledge_search", "knowledge_read", "knowledge_traverse"}
        tools = [t for t in business_tools(ws, "reviewer", None, text_model) if t.__name__ in names]
        rules = criteria_rules(active_criteria(ws))
        # Construction-only injection: the native target captures the actual arm's
        # prompt hash. No source file/global setting persists across arms.
        with patch.object(review_module, "reviewer_prompt", return_value=prompt):
            review = review_module.native_review(ws, model, tools, rules,
                middleware=[TodoListMiddleware(), BusinessBoundary(ws, "rubric_grader")])
        ids = [c["id"] for c in active_criteria(ws)["criteria"]]
        messages = [HumanMessage(encode(project_view(ws))),
                    AIMessage("The selected saved candidate is a synthetic fixture for assessment.")]
        payload = review._grader_input({"messages": messages, "rubric": rules,
                                       "_rubric_criteria": ids,
                                       "_current_grading_run_id": str(uuid4())}, 0)
        write_json(root / "input.json", {"system_prompt": prompt,
                   "user_message": payload["messages"][0].content, "criteria_ids": ids})
        wire = model._get_request_payload([SystemMessage(prompt), HumanMessage("")])
        write_json(root / "settings.json", {
            "parameters": {k: v for k, v in wire.items() if k != "messages"},
            "tools": [t.name for t in review._tools], "max_retries": model.max_retries,
            "timeout_seconds": {k: getattr(model.request_timeout, k) for k in ("connect", "read", "write", "pool")},
            "versions": {n: version(n) for n in ("deepagents", "langchain-openai", "langgraph")},
            "response_schema": GraderResponse.model_json_schema()})
        result = await review._ensure_grader().ainvoke(payload, {"recursion_limit": 10000})
        public = result["structured_response"].model_dump(mode="json")
        write_json(root / "output.json", public)
        coverage = [c["name"] for c in public["criteria"]] == ids
        receipt.update(status="completed", result=public["result"], exact_criterion_coverage=coverage)
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    receipt["ended"] = datetime.now(timezone.utc).isoformat()
    events = ws.store.events()
    responses = [e["data"] for e in events if e["kind"] == "deep_model_response"]
    receipt.update(model_requests=sum(e["kind"] == "deep_model_request" for e in events),
                   model_responses=len(responses), usage=[e.get("usage") for e in responses])
    write_json(root / "receipt.json", receipt)
    # LocalAudit already omits opaque provider reasoning content and credentials.
    write_json(root / "model-io.json", events)
    return receipt


async def main(args):
    data = load_inputs(args.inputs)
    prompts = {"baseline": args.baseline_prompt.read_text(encoding="utf-8"),
               "candidate": review_module.reviewer_prompt(requirement_acceptance=True)}
    order = []
    arms = list(ARMS)
    for repeat in range(args.repeats):
        for index, case in enumerate(data["reports"]):
            shift = index % len(arms)
            selected = arms[shift:] + arms[:shift]
            if repeat % 2:
                selected.reverse()
            order.extend((case, arm, repeat) for arm in selected)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "batch.json", {
        "authorization": args.authorization_note, "synthetic": True,
        "input_sha256": sha(args.inputs.read_text(encoding="utf-8")),
        "system_prompts": prompts, "arms": ARMS,
        "order": [[c["case_id"], a, r] for c, a, r in order],
        "runner_sha256": sha(Path(__file__).read_text(encoding="utf-8"))})
    load_service_environment(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = "glm-5.3"
    for case, arm, repeat in order:
        name = f"{case['case_id']}-{arm}-{repeat}"
        print(encode({"run": name, "status": "starting"}), flush=True)
        receipt = await run_one(args.output / name, data, case, arm, repeat, prompts[ARMS[arm][1]])
        print(encode({k: v for k, v in receipt.items() if k != "usage"}), flush=True)
        if receipt["status"] == "error":
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-prompt", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=(1, 2), default=2)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", required=True)
    asyncio.run(main(parser.parse_args()))
