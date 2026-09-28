"""Explicit GLM trial launcher; credentials stay in subprocess memory, not project data."""
import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path

from report_agent.deep_runtime import run_report, project_agent
from report_agent.exporting import export_docx
from report_agent.store import Store
from report_agent.workspace import Workspace


def load_service_environment(container):
    # Read only three already-authorized service settings; never print Docker output.
    result = subprocess.run(["docker", "inspect", container], capture_output=True, check=True)
    settings = dict(item.split("=", 1) for item in json.loads(result.stdout)[0]["Config"]["Env"] if "=" in item)
    model = settings.get("HIGHWAY_MODEL_NAME", "")
    if model.lower().replace("-", "").replace(".", "") != "glm53":
        raise RuntimeError("SERVICE_IS_NOT_AUTHORIZED_GLM53")
    for target, source in (("REPORT_MODEL", "HIGHWAY_MODEL_NAME"),
                           ("REPORT_BASE_URL", "HIGHWAY_MODEL_BASE_URL"),
                           ("REPORT_API_KEY", "HIGHWAY_MODEL_API_KEY")):
        os.environ[target] = settings[source]
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


async def main(args):
    load_service_environment(args.credential_container)
    if getattr(args, "grader_model", None):
        os.environ["REPORT_GRADER_MODEL"] = args.grader_model
    store = Store(args.project)
    if getattr(args, "review_input_mode", None):
        from report_agent.review_context import configure_context_experiment
        selected = {"input_mode": args.review_input_mode,
                    "grounded_verdict": bool(getattr(args, "grounded_verdict", False))}
        if getattr(args, "calibrated_acceptance", False):
            selected["calibrated_acceptance"] = True
        configure_context_experiment(store, selected)
    if args.manifest:
        with store.run_lock():
            store.initialize(json.loads(args.manifest.read_text(encoding="utf-8")))
            Workspace(store).initialize()
    store.manifest
    if args.inspect:
        async with project_agent(Workspace(store)) as agent:
            state = await agent.aget_state({"configurable": {"thread_id": "report"}}, subgraphs=True)
            def snapshot(value):
                return {"next": value.next, "interrupts": len(value.interrupts),
                        "checkpoint_id": value.config.get("configurable", {}).get("checkpoint_id"),
                        "messages": len(value.values.get("messages", [])),
                        "tasks": [{"name": t.name, "has_error": bool(t.error),
                                   "child": snapshot(t.state) if hasattr(t.state, "values") else None}
                                  for t in value.tasks]}
            print(json.dumps(snapshot(state), ensure_ascii=False, indent=2))
        return
    if store.get("task006_call_intent") and not args.resume:
        raise RuntimeError("ALREADY_ATTEMPTED_INSPECT_CHECKPOINT_AND_RECEIPTS")
    authorization = args.authorization_note or (
        "Task017: user authorized one isolated native review continuation with autonomous revision"
        if store.get("review_import017") else "user approved unlimited project GLM5.3 calls")
    store.set("task006_call_intent", {"authorization": authorization,
                                     "model": os.environ["REPORT_MODEL"],
                                     "grader_model": os.environ.get("REPORT_GRADER_MODEL", os.environ["REPORT_MODEL"]),
                                     "resume": args.resume})
    store.event("trial_attempt_intent", {"model": os.environ["REPORT_MODEL"],
                                        "grader_model": os.environ.get("REPORT_GRADER_MODEL", os.environ["REPORT_MODEL"]),
                                        "resume": args.resume})
    status = await run_report(Workspace(store))
    delivery = status.get("delivery")
    path = None
    if delivery:
        path = store.root / "exports" / (delivery["draft_id"] + ".docx")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(export_docx(Workspace(store), delivery["draft_id"]))
    print(json.dumps({"project": str(store.root), "status": status["status"],
                      "error": status["last_error"], "delivery": delivery,
                      "export": str(path) if path else None,
                      "results": len(status["results"]), "issues": len(status["issues"])}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--inspect", action="store_true", help="Inspect native checkpoints without model invocation")
    parser.add_argument("--serve", action="store_true", help="Serve the workbench without starting a model run")
    parser.add_argument("--port", type=int, default=18140)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", help="Record the existing user authorization for this invocation")
    parser.add_argument("--grader-model", choices=["glm-5.3", "deepseek-v4.1-flash"],
                        help="Grader-only trial override; DeepSeek requires a fresh isolated review fork")
    parser.add_argument("--review-input-mode", choices=["transcript", "artifact"],
                        help="Opt into a context comparison on a fresh isolated review fork")
    parser.add_argument("--grounded-verdict", action="store_true",
                        help="Separate experimental public-grounding instruction (requires input mode)")
    parser.add_argument("--calibrated-acceptance", action="store_true",
                        help="Experimental acceptance-boundary emphasis (requires artifact input and grounding)")
    args = parser.parse_args()
    if args.grounded_verdict and not args.review_input_mode:
        parser.error("--grounded-verdict requires --review-input-mode")
    if args.calibrated_acceptance and (args.review_input_mode != "artifact" or not args.grounded_verdict):
        parser.error("--calibrated-acceptance requires --review-input-mode artifact and --grounded-verdict")
    if args.serve:
        import uvicorn
        from report_agent.webapp import create_app
        load_service_environment(args.credential_container)
        Store(args.project).manifest
        uvicorn.run(create_app(args.project), host="127.0.0.1", port=args.port)
    else:
        asyncio.run(main(args))
