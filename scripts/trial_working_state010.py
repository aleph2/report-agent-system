"""Explicit, isolated real-agent probes of working-state use; no report recovery."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.calculations import sum_products
from report_agent.deep_models import error_data
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from run_deepagents_trial import load_service_environment


def fixture(changed: bool):
    goal = ("Prepare a short interim draft comparing the weighted costs of batches A and B, "
            "with the adopted inputs, rule and totals. This is synthetic arithmetic, not "
            "an engineering assessment. Do not finalize or obtain a review in this assignment.")
    source = ("Weights: first item 0.6, second item 0.4. Batch A: 10, 20. "
              "Batch B: 30, " + ("45" if changed else "40") + ". Costs are in test units.")
    manifest = {"goal": goal, "sources": [{"id": "synthetic-costs", "title": "Synthetic costs",
                 "coverage": "complete", "content": source}]}
    todos = [{"content": "Confirm the batch totals", "status": "in_progress"},
             {"content": "Save the comparison note", "status": "pending"}]
    messages = [HumanMessage(content=goal + "\nSource synthetic-costs: weights 0.6 and 0.4; "
                             "A: 10,20; B: 30,40. Costs are in test units."),
                AIMessage(content="", tool_calls=[{"name": "write_todos", "args": {"todos": todos},
                           "id": "fixture-todos", "type": "tool_call"}]),
                ToolMessage(content="Updated todo list to " + encode(todos), name="write_todos",
                            tool_call_id="fixture-todos", status="success")]
    for name, terms in (("A", [["10", "0.6"], ["20", "0.4"]]),
                        ("B", [["30", "0.6"], ["40", "0.4"]])):
        identity = "fixture-calculate-" + name
        messages += [AIMessage(content="Calculate batch " + name,
                               tool_calls=[{"name": "calculate", "args": {"terms": terms},
                                            "id": identity, "type": "tool_call"}]),
                     ToolMessage(content=encode(sum_products(terms)), name="calculate",
                                 tool_call_id=identity, status="success")]
    if changed:
        messages.append(HumanMessage(content="Correction from the source owner: batch B's second "
                        "item is 45, not 40. This replaces that earlier value; the current "
                        "synthetic-costs source contains this correction. Everything else is unchanged."))
    return manifest, {"messages": messages, "todos": todos}


def state_view(snapshot):
    return {"next": list(snapshot.next), "todos": snapshot.values.get("todos", []),
            "files": snapshot.values.get("files", {}),
            "messages": [m.model_dump(mode="json") for m in snapshot.values.get("messages", [])]}


async def probe(root: Path, variant: str, changed: bool):
    if root.exists():
        raise RuntimeError("TRIAL_DIRECTORY_EXISTS_NO_AUTOMATIC_REPLAY")
    manifest, payload = fixture(changed)
    store = Store(root)
    store.initialize(manifest)
    workspace = Workspace(store)
    workspace.initialize()
    prompt = deep_runtime.COORDINATOR
    if variant == "baseline":
        prompt = prompt.removesuffix(deep_runtime.WORK_STATE_GUIDANCE)
    store.event("trial_intent", {"variant": variant, "changed_input": changed,
                "synthetic_history": True, "seeded_calculations": sum(
                    isinstance(m, ToolMessage) and m.name == "calculate" for m in payload["messages"]),
                "model": "glm-5.3", "reasoning_effort": "high",
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "production_guard_unchanged": True, "max_outer_rounds": 20})
    config = {"configurable": {"thread_id": "working-state-probe"}, "recursion_limit": 10000}
    error, reason = None, "observation_bound"
    with patch.object(deep_runtime, "COORDINATOR", prompt):
        async with deep_runtime.project_agent(workspace) as agent:
            # Todos are internal state, not part of the graph's public input schema.
            seeded_todos = payload.pop("todos")
            await agent.aupdate_state(config, {"todos": seeded_todos}, as_node="tools")
            if (await agent.aget_state(config)).values.get("todos") != seeded_todos:
                raise RuntimeError("TRIAL_STATE_FIXTURE_NOT_PERSISTED")
            try:
                for _ in range(20):
                    await agent.ainvoke(payload, config, interrupt_after=["tools"])
                    snapshot = await agent.aget_state(config)
                    if any(r["kind"] == "draft" for r in workspace.results()):
                        reason = "draft_saved"
                        break
                    if not snapshot.next or snapshot.interrupts:
                        reason = "agent_end_or_human_interrupt"
                        break
                    payload = None
            except Exception as exc:
                error, reason = error_data(exc), "error"
            before = state_view(await agent.aget_state(config))
        async with deep_runtime.project_agent(workspace) as reopened:
            after = state_view(await reopened.aget_state(config))
    events = store.events()
    calls = [e["data"] for e in events if e["kind"] == "deep_tool_start"]
    result = {"variant": variant, "changed_input": changed, "stop_reason": reason,
              "error": error, "checkpoint_preserved": before == after,
              "model_responses": sum(e["kind"] == "deep_model_response" for e in events),
              "calls": calls, "todos": after["todos"], "files": after["files"],
              "results": workspace.results()}
    (root / "checkpoint-observation.json").write_text(encode(after), encoding="utf-8")
    (root / "probe-result.json").write_text(encode(result), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"files", "calls", "results"}},
                     ensure_ascii=False), flush=True)
    return result


async def main(args):
    load_service_environment(args.credential_container)
    for variant in ("baseline", "candidate"):
        for changed in (False, True):
            await probe(args.root / (variant + ("-changed" if changed else "-reuse")), variant, changed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    asyncio.run(main(parser.parse_args()))
