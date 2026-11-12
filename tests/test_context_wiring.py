"""C1 native checkpoint continuation and existing prompt-capture trace join."""
import json

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents import create_agent

from report_agent.content_store import Actor, ContentStore
from report_agent.hierarchical_tools import role_prompt
from report_agent.prompt_provenance import AgentPromptBoundary
from report_agent.tool_trace import ToolTrace, capture_tools
from test_deep_runtime import Driver, invoke
from test_task_supervision import ws, offline


async def test_trace_rows_join_real_boundary_prompt_capture(ws, tmp_path):
    def read_synthetic_state():
        """Return one fixed synthetic value."""
        return "synthetic state"
    driver=Driver(coordinator=[invoke("read_synthetic_state"), AIMessage("完成。")])
    path=tmp_path/"trace.jsonl"
    with capture_tools(ToolTrace(ws,"synthetic-c1",path,Actor("coordinator","coordinator","synthetic-task"))):
        graph=create_agent(driver("coordinator"),[read_synthetic_state],
            system_prompt=role_prompt("coordinator"),middleware=[AgentPromptBoundary(ws,"coordinator")])
        await graph.ainvoke({"messages":[HumanMessage("Read the synthetic value.")]})
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    captures={e["data"]["call_id"] for e in ws.store.events() if e["kind"]=="prompt_model_input"}
    models=[r for r in rows if r["kind"]=="model_started"]
    tools=[r for r in rows if r["kind"]=="tool_outcome"]
    assert len(models)==2 and len(tools)==1
    assert all(r["prompt_call_id"] in captures for r in models+tools)
    assert tools[0]["prompt_call_id"]==models[0]["prompt_call_id"]
    assert tools[0]["native_call_id"]=="read_synthetic_state"


async def test_c1_checkpoint_waits_then_reopens_after_saved_owner_reply(tmp_path):
    from test_fake_draft_flow import checkpoint
    from report_agent.fake_draft_flow import plan
    from report_agent.commission_plan import reply
    from report_agent import plan_authority
    ws,paused,planner,_=await checkpoint(tmp_path)
    count=len(planner.calls)
    for _ in range(2):
        assert (await plan(ws,planner))["status"]=="needs_human"
        assert len(planner.calls)==count
    cs=ContentStore(ws.store)
    ref=plan_authority.plan_ref(ws.store)
    issue=next(i for i in paused["issues"] if not i.get("resolved"))
    reply(ws,issue["id"],dict(plan_ref=ref,requirements_ref=cs.read(ref)["payload"]["requirements_ref"],
        approved=True,corrections="",reductions=[dict(object_id="C",reason="界外对象按委托范围排除。")]))
    planner.scripts["coordinator"].append(AIMessage("计划及页面表已确认，本阶段结束。"))
    result=await plan(ws,planner)
    assert not result.get("last_error"),result
    assert len(planner.calls)==count+1
    assert all(role=="coordinator" for role,_,_ in planner.calls)
