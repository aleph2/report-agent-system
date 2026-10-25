"""The authorized synthetic feedback case; no replays of live001."""

import asyncio
import json
from pathlib import Path

from report_agent.models import configured_model
from report_agent.runtime import run_task
from report_agent.store import Store


ROOT = Path(__file__).resolve().parents[1]


async def main():
    store = Store(ROOT / ".runs" / "live002" / "materials-feedback")
    manifest = json.loads((ROOT / "examples" / "materials-reuse.json").read_text())
    manifest["existing_artifacts"][0]["body"] = (
        "Pedestrians use the east footpath while the west footpath is closed [access]."
    )
    store.initialize(manifest)
    if store.get("live_attempt_registered"):
        raise RuntimeError("ALREADY_ATTEMPTED_INSPECT_RECEIPTS")
    decision = configured_model(store, "decision")
    text = configured_model(store, "text_tool")
    store.set("live_attempt_registered", {
        "authorized": "user approved synthetic feedback-driven further analysis",
        "case": "materials-feedback", "model": decision.model,
    })
    original = store.artifacts()[0]
    store.select_result(original["id"])
    store.add_feedback(
        "The existing materials note omits when the arrangement applies and its limits. "
        "Please examine the supplied sources and supplement it with supported timing, "
        "the maintenance-week applicability and what can or cannot be said about night-time access. "
        "Retain supported existing content; do not invent arrangements."
    )
    result = await run_task(store, decision, text)
    events = store.events()
    requests = [e["data"] for e in events if e["kind"] == "model_request"]
    summary = {
        "case": "materials-feedback", "status": result,
        "original_unchanged": store.artifacts()[0] == original,
        "decision_requests": sum(r["purpose"] == "decision" for r in requests),
        "text_tool_requests": sum(r["purpose"] == "text_tool" for r in requests),
        "tool_actions": [e["data"] for e in events if e["kind"] == "tool"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["status"] == "draft_ready" and not result["last_error"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
