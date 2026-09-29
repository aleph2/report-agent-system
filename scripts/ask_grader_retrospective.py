"""One explicit post-hoc audit question; no artifact edits, tools or private reasoning."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from report_agent.deep_models import configured_model, error_data
from report_agent.evidence_analysis import model_identity
from report_agent.store import Store
from run_deepagents_trial import load_service_environment
from run_grader_diagnostic import InvocationAudit, write_json


async def main(args):
    inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    if set(inputs) != {"system", "user"}:
        raise ValueError("EXPLICIT_PUBLIC_MESSAGES_REQUIRED")
    args.output.mkdir(parents=True, exist_ok=False)
    store = Store(args.output)
    receipt = {"authorization": args.authorization_note, "status": "attempted",
               "started": datetime.now(timezone.utc).isoformat(), "post_hoc_counterevidence_supplied": True}
    write_json(args.output / "input.json", inputs)
    write_json(args.output / "receipt.json", receipt)
    load_service_environment(args.credential_container)
    os.environ["REPORT_GRADER_MODEL"] = "glm-5.3"
    try:
        model = configured_model(store, "grader_diagnostic")
        model.callbacks.append(InvocationAudit(store))
        write_json(args.output / "settings.json", model_identity(model))
        response = await model.ainvoke([("system", inputs["system"]), ("user", inputs["user"])])
        write_json(args.output / "output.json", {"content": response.content,
            "returned_model": response.response_metadata.get("model_name"),
            "tool_calls": response.tool_calls})
        receipt["status"] = "completed"
    except Exception as exc:
        receipt.update(status="error", error=error_data(exc))
    events = store.events()
    responses = [e["data"] for e in events if e["kind"] == "deep_model_response"]
    receipt.update(ended=datetime.now(timezone.utc).isoformat(), responses=len(responses),
                   usage=[e.get("usage") for e in responses])
    write_json(args.output / "model-io.json", events)
    write_json(args.output / "receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    parser.add_argument("--authorization-note", required=True)
    asyncio.run(main(parser.parse_args()))
