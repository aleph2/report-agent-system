"""Inventory real compiled graphs and final fake-model bindings in temporary stores."""
import asyncio
import json
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path

from measure import ROOT, Observe, save

sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]


async def inventory():
    import deepagents.graph as graph_module
    import deepagents.middleware.subagents as subagent_module
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import AIMessage
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from report_agent.deep_runtime import build_agent
    from report_agent.learning_runtime import build_optimizer
    from report_agent.knowledge import Knowledge
    from test_task_supervision import ws as fixture
    from test_bounded_review import review_call
    from test_hierarchical_content import seed
    from report_agent.content_tasks import delegated_task
    from test_decision_data import activate
    from test_deep_runtime import Driver, ScriptedChat

    out = ROOT / ".analysis/round0-coverage-20261018"
    out.mkdir(parents=True, exist_ok=True)
    guard = Observe(out)
    guard.guard_network()
    records, graphs, errors = [], [], []
    originals = []
    profile = None
    class BindingCaptured(BaseException):
        """Normal probe stop: schemas captured before any model generation."""
    original_bind = ScriptedChat.bind_tools
    def capture_bind(model, tools, **kwargs):
        original_bind(model, tools, **kwargs)
        raise BindingCaptured()
    ScriptedChat.bind_tools = capture_bind
    for module in (graph_module, subagent_module):
        original = module.create_agent
        originals.append((module, original))
        def capture(*args, _original=original, **kwargs):
            agent = _original(*args, **kwargs)
            model = args[0] if args else kwargs["model"]
            role = getattr(model, "role", kwargs.get("name", "unknown"))
            node = agent.get_graph().nodes.get("tools")
            tools = getattr(node.data, "tools_by_name", {}) if node else {}
            records.append({"profile": profile, "role": role,
                "registration_stage": "compiled_native_toolnode",
                "tools": [convert_to_openai_tool(t)["function"] for t in tools.values()]})
            graphs.append((role, agent))
            return agent
        module.create_agent = capture
    try:
        for managed in (False, True):
            for knowledge in (False, True):
                profile = f"report:managed={managed}:knowledge={knowledge}"
                with tempfile.TemporaryDirectory(prefix="round0-inventory-") as tmp:
                    ws = fixture.__wrapped__(Path(tmp))
                    ws.store.set("knowledge_enabled", knowledge)
                    if managed:
                        activate(ws)
                    _, _, refs, snapshot, _ = seed(ws)
                    driver = Driver(**{r: [AIMessage(content="Synthetic binding inspection only.")]
                                       for r in ("coordinator", "writer", "reviewer", "layout", "text_tool")})
                    graphs.clear()
                    build_agent(ws, driver, InMemorySaver(),
                                knowledge=Knowledge("round0", embedding=False) if knowledge else None)
                    seen = set()
                    for role, agent in list(graphs):
                        if (role, id(agent)) in seen:
                            continue
                        seen.add((role, id(agent)))
                        try:
                            call = {"id": "inventory-" + role, "args": {"subagent_type": role, "description": "Synthetic schema inspection"}}
                            if role == "layout":
                                call["args"]["layout_snapshot_ref"] = snapshot
                            if role == "reviewer":
                                call = review_call(snapshot, refs, id="inventory-reviewer")
                            context = delegated_task(ws, "coordinator", call) if role in {"writer", "reviewer", "layout"} else nullcontext()
                            with context:
                                await agent.ainvoke({"messages": [{"role": "user", "content": "Observe available interfaces; no tool calls."}]},
                                                    config={"configurable": {"thread_id": role}, "recursion_limit": 5})
                        except BindingCaptured:
                            pass
                        except Exception as exc:
                            errors.append({"profile": profile, "role": role, "error": type(exc).__name__, "detail": str(exc)[:500]})
                    for role, batches in driver.bindings.items():
                        records.append({"profile": profile, "role": role,
                            "registration_stage": "final_scripted_model_bind_tools", "tools": batches[-1]})
        for experiment in (False, True):
            profile = f"optimizer:experiment={experiment}"
            with tempfile.TemporaryDirectory(prefix="round0-learning-inventory-") as tmp:
                ws = fixture.__wrapped__(Path(tmp) / "project")
                ws.store.set("learning_config", {"library_path": str(Path(tmp) / "library"), "customer_id": "synthetic"})
                driver = Driver(optimizer=[AIMessage(content="Synthetic binding inspection only.")])
                agent = build_optimizer(ws, driver("optimizer"), experiment_runner=(lambda *a: None) if experiment else None,
                                        text_model=driver("text_tool"))
                try:
                    await agent.ainvoke({"messages": [{"role": "user", "content": "Observe available interfaces; no tool calls."}]})
                except BindingCaptured:
                    pass
                records.append({"profile": profile, "role": "optimizer",
                    "registration_stage": "final_scripted_model_bind_tools", "tools": driver.bindings["optimizer"][-1]})
    finally:
        ScriptedChat.bind_tools = original_bind
        for module, original in originals:
            module.create_agent = original
        guard.finish()
    save(out / "interface-inventory.json", {"scope": "Four declared report configurations and two optimizer capability configurations; no claim of all possible configurations or host API coverage.",
        "profiles": records, "errors": errors, "denied_connections": guard.denied_connections,
        "actual_provider_calls": 0, "business_tool_calls": 0})
    print(json.dumps({"records": len(records), "errors": errors, "path": str(out / "interface-inventory.json")}))


if __name__ == "__main__":
    asyncio.run(inventory())
