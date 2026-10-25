"""Small known-control comparison of analysis entrypoints, without a grader/author."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from report_agent.deep_models import configured_model, error_data
from report_agent.deep_runtime import business_tools
from report_agent.evidence_analysis import selected_evidence, model_identity, ANALYSIS_PROMPT
from report_agent.store import encode
from run_acceptance_boundary_diagnostic import load_inputs, prepare_workspace
from run_deepagents_trial import load_service_environment
from run_grader_diagnostic import write_json, sha, InvocationAudit


def request_for(workspace, data, case):
    draft = next(r for r in workspace.results() if r["kind"] == "draft")
    question = ("Assess the selected report's factual relationships and conclusions against "
                "the supplied source evidence and commission. Identify supported claims, "
                "material contradictions and unresolved relationships, with precise evidence "
                "and limits. Do not invent additional requirements.\nCommission:\n" +
                data["commission"] + "\n" + data["scope_instruction"])
    return {"question": question,
            "source_selections": [{"source_id": s["id"], "offset": 0, "limit": 50}
                                  for s in data["source_sets"][case["source_set"]]],
            "result_selections": [{"result_id": draft["id"], "offset": 0,
                                   "characters": len(draft["body"])}]}


def legacy_arguments(workspace, request):
    # The old source-only entrypoint can receive additional material inside purpose.
    # Supply the identical remaining sources/result as explicitly labelled evidence.
    # This compares real interfaces, not identical system-prompt/serialization bytes.
    selected = selected_evidence(workspace, request["source_selections"], request["result_selections"])
    primary = request["source_selections"][0]
    return {**primary, "purpose": encode({"question": request["question"],
             "additional_selected_evidence": selected[1:]})}


async def run_arm(workspace, root, arm, request):
    root.mkdir(parents=True, exist_ok=False)
    receipt = {"arm": arm, "status": "attempted", "started": datetime.now(timezone.utc).isoformat(),
               "outer_grader": False, "author": False, "known_synthetic_controls": True}
    write_json(root / "receipt.json", receipt)
    before = len(workspace.store.events())
    try:
        model = configured_model(workspace.store, "text_tool")
        model.callbacks.append(InvocationAudit(workspace.store))
        available = {tool.__name__: tool for tool in business_tools(workspace, "reviewer", None, model)}
        name = "analyze_text" if arm == "legacy" else "analyze_evidence"
        arguments = legacy_arguments(workspace, request) if arm == "legacy" else request
        write_json(root / "input.json", {"tool": name, "arguments": arguments})
        write_json(root / "settings.json", model_identity(model))
        result = await available[name](**arguments)
        write_json(root / "output.json", result)
        receipt.update(status="completed", operation=result.get("operation"), reused=result["reused"])
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    events = workspace.store.events()[before:]
    responses = [e["data"] for e in events if e["kind"] == "deep_model_response"]
    receipt.update(ended=datetime.now(timezone.utc).isoformat(),
                   model_requests=sum(e["kind"] == "deep_model_request" for e in events),
                   model_responses=len(responses), usage=[e.get("usage") for e in responses])
    write_json(root / "model-io.json", events)  # LocalAudit excludes provider private reasoning.
    write_json(root / "receipt.json", receipt)
    return receipt


async def main(args):
    data = load_inputs(args.inputs)  # strict model-visible allowlist, no oracle file.
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "batch.json", {"authorization": args.authorization_note,
        "input_sha256": sha(args.inputs.read_text(encoding="utf-8")),
        "runner_sha256": sha(Path(__file__).read_text(encoding="utf-8")),
        "analysis_prompt": ANALYSIS_PROMPT, "repeats": 1,
        "scope": "Known synthetic interface sanity comparison; not generalization or autonomous use."})
    load_service_environment(args.credential_container)
    for index, case in enumerate(data["reports"]):
        root = args.output / case["case_id"]
        workspace = prepare_workspace(root, data, case, "criteria_and_grader")
        request = request_for(workspace, data, case)
        write_json(root / "selections.json", request)
        for arm in (["legacy", "selected"] if index % 2 == 0 else ["selected", "legacy"]):
            print(encode({"case": case["case_id"], "arm": arm, "status": "starting"}), flush=True)
            receipt = await run_arm(workspace, root / arm, arm, request)
            print(encode({"case": case["case_id"], **{k: v for k, v in receipt.items() if k != "usage"}}), flush=True)
            if receipt["status"] != "completed":
                return  # diagnose first; no blind paid replay.


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", required=True)
    asyncio.run(main(parser.parse_args()))
