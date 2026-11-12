"""Frozen synthetic hold-out comparison using the application's native grader.

No expected labels are loaded. This is grader judgment/tool evidence, not an author
revision trial or professional acceptance. Real report continuation uses the normal
run_deepagents_trial entry point on isolated pre-review forks.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from report_agent.deep_models import configured_model, error_data
from report_agent.deep_runtime import business_tools, BusinessBoundary, project_view
from report_agent.review import native_review, load_rules, reviewer_prompt
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from run_deepagents_trial import load_service_environment
from run_grader_diagnostic import InvocationAudit, sha, write_json


ARMS = {
    "transcript": {"input_mode": "transcript", "grounded_verdict": False},
    "artifact": {"input_mode": "artifact", "grounded_verdict": False},
    "artifact_grounded": {"input_mode": "artifact", "grounded_verdict": True},
    "artifact_grounded_calibrated": {"input_mode": "artifact", "grounded_verdict": True,
                                      "calibrated_acceptance": True},
}


def load_cases(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"synthetic", "cases"} or data["synthetic"] is not True:
        raise ValueError("SYNTHETIC_CASE_SET_REQUIRED")
    seen = set()
    for case in data["cases"]:
        if set(case) != {"id", "assignment", "sources", "report", "author_history", "human_feedback"}:
            raise ValueError("UNEXPECTED_CASE_FIELDS")
        if not re.fullmatch(r"[a-f0-9]{12}", case["id"]) or case["id"] in seen:
            raise ValueError("INVALID_OR_DUPLICATE_CASE_ID")
        if not all(isinstance(case[k], str) and case[k] for k in ("assignment", "report", "author_history")):
            raise ValueError("INCOMPLETE_SYNTHETIC_CASE")
        if any(set(s) != {"id", "title", "content"} for s in case["sources"]):
            raise ValueError("UNEXPECTED_SOURCE_FIELDS")
        # Nonempty real feedback needs a faithful application issue representation;
        # do not quietly flatten it into an author message in this small runner.
        if case["human_feedback"]:
            raise ValueError("SYNTHETIC_FEEDBACK_REQUIRES_APPLICATION_ISSUE_MAPPING")
        seen.add(case["id"])
    if not seen:
        raise ValueError("NO_CASES")
    return data


def prepare_workspace(root, case, arm):
    store = Store(root)
    store.initialize({"name": "Synthetic review comparison", "goal": case["assignment"],
                      "sources": [{**source, "coverage": "complete"} for source in case["sources"]]})
    ws = Workspace(store)
    ws.initialize()
    task = ws.request_task("draft", "Preserve the supplied synthetic candidate", [])
    result = ws.submit(task["id"], actor="writer", title="Synthetic candidate report",
                       body=case["report"], source_ids=[s["id"] for s in case["sources"]], input_ids=[])
    ws.select_delivery(result["id"], "")
    store.set("knowledge_enabled", False)
    store.set("review_context_experiment", ARMS[arm])
    # Direct nested-grader diagnostic, not a fabricated imported runtime fork.
    return ws


async def run_one(root, case, arm, repeat):
    root.mkdir(parents=True, exist_ok=False)
    receipt = {"case_id": case["id"], "arm": arm, "repeat": repeat,
               "started": datetime.now(timezone.utc).isoformat(), "status": "attempted",
               "candidate_sha256": sha(case["report"]), "synthetic": True,
               "outer_revision_loop": False}
    write_json(root / "receipt.json", receipt)
    ws = prepare_workspace(root, case, arm)
    try:
        model = configured_model(ws.store, "rubric_grader")
        model.callbacks.append(InvocationAudit(ws.store))
        names = {"project_status", "read_source_page", "search_sources", "inspect_source_page",
                 "analyze_source_image", "calculate", "read_result"}
        tools = [tool for tool in business_tools(ws, "reviewer", None, None) if tool.__name__ in names]
        review = native_review(ws, model, tools, load_rules(), middleware=[BusinessBoundary(ws, "rubric_grader")])
        messages = [HumanMessage(encode(project_view(ws))), AIMessage(case["author_history"])]
        payload = review._grader_input({"messages": messages, "rubric": load_rules(),
                                       "_current_grading_run_id": str(uuid4())}, 0)
        prompt = reviewer_prompt(ARMS[arm])
        write_json(root / "input.json", {"system_prompt": prompt, "user_message": payload["messages"][0].content})
        wire = model._get_request_payload([SystemMessage(prompt), HumanMessage("")])
        write_json(root / "settings.json", {"parameters": {k: v for k, v in wire.items() if k != "messages"},
                   "tools": [tool.name for tool in review._tools], "experiment": ARMS[arm],
                   "system_sha256": sha(prompt), "rubric_sha256": sha(load_rules()),
                   "response_schema": "GraderResponse"})
        result = await review._ensure_grader().ainvoke(payload, {"recursion_limit": 10000})
        public = result["structured_response"].model_dump(mode="json")
        write_json(root / "output.json", public)
        receipt.update(status="completed", result=public["result"])
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    receipt["ended"] = datetime.now(timezone.utc).isoformat()
    events = ws.store.events()
    responses = [e["data"] for e in events if e["kind"] == "deep_model_response"]
    receipt.update(model_requests=sum(e["kind"] == "deep_model_request" for e in events),
                   model_responses=len(responses), usage=[e["usage"] for e in responses])
    write_json(root / "model-io.json", events)
    write_json(root / "receipt.json", receipt)
    return receipt


async def main(args):
    data = load_cases(args.inputs)
    order = []
    for repeat in range(args.repeats):
        for index, case in enumerate(data["cases"]):
            arms = args.arms if (index + repeat) % 2 == 0 else list(reversed(args.arms))
            order.extend((case, arm, repeat) for arm in arms)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "batch.json", {"authorization": args.authorization_note,
        "input_sha256": sha(args.inputs.read_text(encoding="utf-8")),
        "input_file_sha256": sha256(args.inputs.read_bytes()).hexdigest(),
        "system_prompts": {arm: reviewer_prompt(ARMS[arm]) for arm in args.arms},
        "rubric": load_rules(), "order": [[c["id"], a, r] for c, a, r in order],
        "runner_sha256": sha(Path(__file__).read_text(encoding="utf-8"))})
    load_service_environment(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = args.grader_model
    for case, arm, repeat in order:
        name = f"{case['id']}-{arm}-{repeat}"
        print(encode({"run": name, "status": "starting"}), flush=True)
        receipt = await run_one(args.output / name, case, arm, repeat)
        print(encode(receipt), flush=True)
        if receipt["status"] == "error":
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", choices=list(ARMS), required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    parser.add_argument("--grader-model", choices=["glm-5.3", "deepseek-v4.1-flash-1017"], default="deepseek-v4.1-flash-1017")
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", required=True)
    asyncio.run(main(parser.parse_args()))
