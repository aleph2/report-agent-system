"""Historical reuse/new-material trial; the latter is NOT a feedback test.

Retained for reproducibility. Do not rerun the registered live001 cases.
"""

import asyncio
import json
from pathlib import Path

from report_agent.models import configured_model
from report_agent.runtime import run_task
from report_agent.store import Store


ROOT = Path(__file__).resolve().parents[1]


async def main():
    summaries = []
    for name in ("materials-reuse", "materials-new"):
        store = Store(ROOT / ".runs" / "live001" / name)
        store.initialize(json.loads((ROOT / "examples" / f"{name}.json").read_text()))
        if store.get("live_attempt_registered"):
            raise RuntimeError(f"ALREADY_ATTEMPTED_INSPECT_RECEIPTS: {name}")
        decision = configured_model(store, "decision")
        text = configured_model(store, "text_tool")
        store.set("live_attempt_registered", {"authorized": "user approved two synthetic GLM5.3 scenarios",
                                               "case": name, "model": decision.model})
        status = await run_task(store, decision, text)
        events = store.events()
        requests = [e["data"] for e in events if e["kind"] == "model_request"]
        tools = [e["data"] for e in events if e["kind"] == "tool"]
        summaries.append({"case": name, "status": status,
                          "decision_requests": sum(r["purpose"] == "decision" for r in requests),
                          "text_tool_requests": sum(r["purpose"] == "text_tool" for r in requests),
                          "tool_actions": tools})
        print(json.dumps(summaries[-1], ensure_ascii=False, indent=2), flush=True)
        if status["status"] == "failed":
            break
    return summaries


if __name__ == "__main__":
    asyncio.run(main())
