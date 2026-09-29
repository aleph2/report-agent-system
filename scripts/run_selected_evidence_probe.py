"""Fresh autonomous grader-only probe of a saved candidate; no prior verdict/answers."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from report_agent.acceptance import active_criteria, bind_mode, criteria_rules, save_criteria
from report_agent.deep_models import configured_model, error_data
from report_agent.deep_runtime import BusinessBoundary, business_tools, project_view
from report_agent.review import native_review, reviewer_prompt
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from prepare_clean_trial009 import prepare
from run_deepagents_trial import load_service_environment
from run_grader_diagnostic import InvocationAudit, write_json


def prepare_candidate(baseline, destination, draft_id):
    # Only public immutable result records are read; no checkpoint/transcript/review.
    with sqlite3.connect((baseline.resolve() / "state.db").as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        rows = [json.loads(row[0]) for row in db.execute("SELECT data FROM results")]
    original = next(r for r in rows if r["id"] == draft_id and r["kind"] == "draft")
    adopted = [r for r in rows if r["kind"] == "acceptance" and r["id"] in original["input_ids"]]
    if len(adopted) != 1:
        raise ValueError("ONE_ADOPTED_STANDARD_REQUIRED")
    body = json.loads(adopted[0]["body"])
    criteria = [{k: v for k, v in c.items() if k != "id"} for c in body["criteria"]]
    receipt = prepare(baseline, destination)
    workspace = Workspace(Store(destination))
    workspace.store.set("knowledge_enabled", False)
    bind_mode(workspace)
    standard = save_criteria(workspace, actor="coordinator", title=adopted[0]["title"],
                criteria=criteria, source_ids=adopted[0]["source_ids"], input_ids=[],
                reason="Isolated known-candidate grader probe; preserve original criterion definitions.")
    task = workspace.request_task("draft", "Preserve candidate for an isolated review probe", [])
    draft = workspace.submit(task["id"], actor="writer", title=original["title"], body=original["body"],
                source_ids=original["source_ids"], input_ids=[standard["id"]])
    workspace.select_delivery(draft["id"], "")
    current = active_criteria(workspace)
    assert [{k: v for k, v in c.items() if k != "id"} for c in current["criteria"]] == criteria
    assert draft["body"] == original["body"]
    assert workspace.store.manifest["goal"] == body["requirement_basis"]["goal"]
    receipt.update(original_draft_id=original["id"], imported_draft_id=draft["id"],
                   draft_body_sha256=hashlib.sha256(draft["body"].encode()).hexdigest(),
                   original_criteria_id=adopted[0]["id"], imported_criteria_id=standard["id"],
                   criterion_id_mapping=dict(zip([c["id"] for c in body["criteria"]],
                                                 [c["id"] for c in current["criteria"]], strict=True)),
                   criterion_definitions_unchanged=True, imported_prior_verdict=False,
                   imported_author_history=False, outer_revision_loop=False)
    write_json(destination / "candidate-import.json", receipt)
    return workspace


async def main(args):
    workspace = prepare_candidate(args.baseline, args.output, args.draft_id)
    repo = Path(__file__).resolve().parents[1]
    paths = [*sorted((repo / "src/report_agent").rglob("*.py")),
             *sorted((repo / "src/report_agent/rules").glob("*.md")), Path(__file__),
             repo / "scripts/prepare_clean_trial009.py", repo / "pyproject.toml"]
    write_json(args.output / "freeze.json", {"files": {p.relative_to(repo).as_posix():
        hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "role_prompt": reviewer_prompt(requirement_acceptance=True)})
    receipt = {"authorization": args.authorization_note, "started": datetime.now(timezone.utc).isoformat(),
               "status": "attempted", "scope": "Autonomous grader-only known-candidate probe; no author or repair loop."}
    write_json(args.output / "receipt.json", receipt)
    load_service_environment(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = "glm-5.3"
    try:
        model = configured_model(workspace.store, "rubric_grader")
        model.callbacks.append(InvocationAudit(workspace.store))
        text_model = configured_model(workspace.store, "text_tool")
        text_model.callbacks.append(InvocationAudit(workspace.store))
        names = {"project_status", "read_source_page", "search_sources", "inspect_source_page",
                 "analyze_source_image", "calculate", "read_result", "analyze_text", "analyze_evidence"}
        tools = [t for t in business_tools(workspace, "reviewer", None, text_model) if t.__name__ in names]
        rules = criteria_rules(active_criteria(workspace))
        review = native_review(workspace, model, tools, rules,
            middleware=[TodoListMiddleware(), BusinessBoundary(workspace, "rubric_grader")])
        ids = [c["id"] for c in active_criteria(workspace)["criteria"]]
        payload = review._grader_input({"messages": [HumanMessage(encode(project_view(workspace))),
            AIMessage("The selected saved candidate is available for assessment.")],
            "rubric": rules, "_rubric_criteria": ids, "_current_grading_run_id": str(uuid4())}, 0)
        write_json(args.output / "input.json", {"user_message": payload["messages"][0].content,
                                                "criteria_ids": ids})
        result = await review._ensure_grader().ainvoke(payload, {"recursion_limit": 10000})
        public = result["structured_response"].model_dump(mode="json")
        write_json(args.output / "output.json", public)
        receipt.update(status="completed", result=public["result"],
                       exact_criterion_coverage=[c["name"] for c in public["criteria"]] == ids)
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    events = workspace.store.events()
    responses = [e["data"] for e in events if e["kind"] == "deep_model_response"]
    receipt.update(ended=datetime.now(timezone.utc).isoformat(), model_responses=len(responses),
                   usage=[d.get("usage") for d in responses])
    write_json(args.output / "model-io.json", events)
    write_json(args.output / "receipt.json", receipt)
    print(encode({k: v for k, v in receipt.items() if k != "usage"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--authorization-note", required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    asyncio.run(main(parser.parse_args()))
