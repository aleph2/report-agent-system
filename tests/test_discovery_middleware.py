"""Real LangChain graph: discover, bind and execute original tools offline."""
import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
from report_agent.tool_discovery import ToolDiscovery
from test_deep_runtime import Driver, invoke

@pytest.mark.asyncio
async def test_agent_discovers_and_calls_only_registered_tool():
    calls=[]
    def export_report(value:str)->str:
        """Export a synthetic report document."""
        calls.append(value); return "saved"
    def read_source()->str:
        """Read a synthetic source."""
        return "source"
    driver=Driver(coordinator=[invoke("search_tools",query="export_report"),
        invoke("export_report",value="fake"),AIMessage(content="done")])
    model=driver("coordinator")
    agent=create_agent(model=model,tools=[export_report,read_source],
                       middleware=[ToolDiscovery([export_report,read_source])])
    result=await agent.ainvoke({"messages":[HumanMessage(content="Make a fake report.")]})
    bindings=driver.bindings["coordinator"]
    assert "search_tools" in {t["name"] for t in bindings[0]}
    assert "export_report" not in {t["name"] for t in bindings[0]}
    assert "export_report" in {t["name"] for t in bindings[1]}
    assert "read_source" not in {t["name"] for t in bindings[1]}
    assert calls == ["fake"]
    assert any(isinstance(m,ToolMessage) and m.name=="search_tools" for m in result["messages"])


@pytest.mark.asyncio
async def test_discovered_tool_survives_in_memory_checkpoint_reopen():
    from langgraph.checkpoint.memory import MemorySaver
    calls=[]
    def export_report(value:str)->str:
        """Export a synthetic report."""
        calls.append(value);return "saved"
    driver=Driver(coordinator=[invoke("search_tools",query="export_report"),
        AIMessage(content="search complete"),invoke("export_report",value="fake"),
        AIMessage(content="done")])
    saver=MemorySaver()
    def build():
        return create_agent(model=driver("coordinator"),tools=[export_report],
                            middleware=[ToolDiscovery([export_report])],checkpointer=saver)
    config={"configurable":{"thread_id":"fake"}}
    await build().ainvoke({"messages":[HumanMessage(content="Find export.")]},config)
    await build().ainvoke({"messages":[HumanMessage(content="Now export.")]},config)
    assert "export_report" in {x["name"] for x in driver.bindings["coordinator"][2]}
    assert calls==["fake"]


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["agent-search-v1", "agent-search-v2"])
async def test_discovery_is_private_between_parent_and_two_same_role_children(profile):
    from deepagents import create_deep_agent
    from deepagents.middleware._state import private_state_field_names
    from report_agent.tool_discovery import DiscoveryState, DiscoverySelectionState
    assert "_discovered_tools" in private_state_field_names(DiscoveryState if profile == "agent-search-v1" else DiscoverySelectionState)
    def shared_probe()->str:
        """A synthetic shared probe."""
        return "ok"
    driver=Driver(coordinator=[invoke("search_tools",query="shared_probe") if profile == "agent-search-v1" else invoke("select_tools",names=["shared_probe"]),
        invoke("task",subagent_type="writer",description="First fake task"),
        invoke("task",subagent_type="writer",description="Second fake task"),
        AIMessage(content="done")],writer=[AIMessage(content="finished")])
    agent=create_deep_agent(model=driver("coordinator"),tools=[shared_probe],
        middleware=[ToolDiscovery([shared_probe],profile=profile)],subagents=[{"name":"writer",
        "description":"Synthetic writer","system_prompt":"Do the fake task.",
        "model":driver("writer"),"tools":[shared_probe],
        "middleware":[ToolDiscovery([shared_probe],profile=profile)]}])
    await agent.ainvoke({"messages":[HumanMessage(content="Do two tasks.")]})
    child=driver.bindings["writer"]
    assert len(child)==2
    assert all("shared_probe" not in {x["name"] for x in binding} for binding in child)
    assert "shared_probe" in {x["name"] for x in driver.bindings["coordinator"][-1]}


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["agent-search-v1", "agent-search-v2"])
async def test_child_discovery_is_not_returned_to_parent(profile):
    from deepagents import create_deep_agent
    def shared_probe()->str:
        """A synthetic shared probe."""
        return "ok"
    driver=Driver(coordinator=[invoke("task",subagent_type="writer",description="Fake task"),AIMessage(content="done")],
        writer=[invoke("search_tools",query="shared_probe") if profile == "agent-search-v1" else invoke("select_tools",names=["shared_probe"]),AIMessage(content="finished")])
    agent=create_deep_agent(model=driver("coordinator"),tools=[shared_probe],
        middleware=[ToolDiscovery([shared_probe],profile=profile)],subagents=[{"name":"writer",
        "description":"Synthetic writer","system_prompt":"Do the fake task.",
        "model":driver("writer"),"tools":[shared_probe],"middleware":[ToolDiscovery([shared_probe],profile=profile)]}])
    await agent.ainvoke({"messages":[HumanMessage(content="Do the task.")]})
    assert "shared_probe" in {x["name"] for x in driver.bindings["writer"][-1]}
    assert "shared_probe" not in {x["name"] for x in driver.bindings["coordinator"][-1]}


@pytest.mark.asyncio
async def test_discovery_survives_removed_search_messages_and_rebuilt_graph():
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_core.messages import RemoveMessage
    calls=[]
    def export_report(value:str)->str:
        """Export a synthetic report."""
        calls.append(value);return "saved"
    saver=MemorySaver(); first=Driver(coordinator=[invoke("search_tools",query="export_report"),AIMessage(content="found")])
    def build(driver):
        return create_agent(model=driver("coordinator"),tools=[export_report],
            middleware=[ToolDiscovery([export_report])],checkpointer=saver)
    config={"configurable":{"thread_id":"fake-removal"}}
    graph=build(first);await graph.ainvoke({"messages":[HumanMessage(content="Find export.")]},config)
    state=await graph.aget_state(config)
    remove=[RemoveMessage(id=m.id) for m in state.values["messages"]
            if isinstance(m,ToolMessage) or (isinstance(m,AIMessage) and m.tool_calls)]
    assert len(remove)==2
    await graph.aupdate_state(config,{"messages":remove})
    later=Driver(coordinator=[AIMessage(content="unused"),invoke("export_report",value="fake"),AIMessage(content="done")])
    await build(later).ainvoke({"messages":[HumanMessage(content="Now export.")]},config)
    assert "export_report" in {x["name"] for x in later.bindings["coordinator"][0]}
    assert calls==["fake"]


@pytest.mark.asyncio
async def test_discovered_tool_survives_sqlite_checkpoint_close_and_reopen(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    calls=[]
    def export_report(value:str)->str:
        """Export a synthetic report."""
        calls.append(value);return "saved"
    config={"configurable":{"thread_id":"fake-durable"}}
    def build(driver,saver):
        return create_agent(model=driver("coordinator"),tools=[export_report],
            middleware=[ToolDiscovery([export_report])],checkpointer=saver)
    first=Driver(coordinator=[invoke("search_tools",query="export_report"),AIMessage(content="found")])
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/"checkpoint.db")) as saver:
        await build(first,saver).ainvoke({"messages":[HumanMessage(content="Find export.")]},config)
    later=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="unused"),
        invoke("export_report",value="fake"),AIMessage(content="done")])
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path/"checkpoint.db")) as saver:
        await build(later,saver).ainvoke({"messages":[HumanMessage(content="Now export.")]},config)
    assert "export_report" in {x["name"] for x in later.bindings["coordinator"][0]}
    assert calls==["fake"]


@pytest.mark.asyncio
async def test_changed_registered_schema_is_not_silently_reused():
    from langgraph.checkpoint.memory import MemorySaver
    def first_export(value:str)->str:
        """Export a synthetic report."""
        return value
    def changed_export(value:int)->str:
        """Export a synthetic report."""
        return str(value)
    first_export.__name__=changed_export.__name__="export_report"
    saver=MemorySaver();config={"configurable":{"thread_id":"fake-version"}}
    first=Driver(coordinator=[invoke("search_tools",query="export_report"),AIMessage(content="found")])
    graph=create_agent(model=first("coordinator"),tools=[first_export],
        middleware=[ToolDiscovery([first_export])],checkpointer=saver)
    await graph.ainvoke({"messages":[HumanMessage(content="Find export.")]},config)
    later=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="unused"),AIMessage(content="done")])
    rebuilt=create_agent(model=later("coordinator"),tools=[changed_export],
        middleware=[ToolDiscovery([changed_export])],checkpointer=saver)
    await rebuilt.ainvoke({"messages":[HumanMessage(content="Continue.")]},config)
    names={x["name"] for x in later.bindings["coordinator"][0]}
    assert "search_tools" in names and "export_report" not in names


@pytest.mark.asyncio
async def test_explicit_selection_only_exposes_chosen_and_can_replace_it():
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke
    def export_report(value:str)->str:
        """Export a synthetic report."""
        return value
    def read_source()->str:
        """Read a synthetic source."""
        return "source"
    driver=Driver(coordinator=[invoke("search_tools",query="synthetic"),
        invoke("select_tools",names=["export_report"]),
        invoke("export_report",value="fake"),
        invoke("select_tools",names=["read_source"]),
        invoke("read_source"),AIMessage(content="done")])
    agent=create_agent(model=driver("coordinator"),tools=[export_report,read_source],
                       middleware=[ToolDiscovery([export_report,read_source],profile="agent-search-v2")])
    await agent.ainvoke({"messages":[HumanMessage(content="Choose tools freely.")]})
    names=[{x["name"] for x in binding} for binding in driver.bindings["coordinator"]]
    assert "search_tools" in names[0] and "select_tools" in names[0]
    assert "export_report" not in names[0] and "read_source" not in names[0]
    assert "export_report" not in names[1] and "read_source" not in names[1]
    assert "export_report" in names[2] and "read_source" not in names[2]
    assert "export_report" not in names[3]
    assert "read_source" in names[4] and "export_report" not in names[4]
    assert "read_source" not in names[5]


@pytest.mark.asyncio
async def test_v2_selected_schema_persists_and_replaces_after_reopen():
    from langgraph.checkpoint.memory import MemorySaver
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke
    def alpha()->str:
        """A synthetic alpha tool."""
        return "a"
    def beta()->str:
        """A synthetic beta tool."""
        return "b"
    driver=Driver(coordinator=[invoke("select_tools",names=["alpha"]),AIMessage(content="saved"),
        invoke("select_tools",names=["beta"]),AIMessage(content="done")])
    saver=MemorySaver()
    def build():
        return create_agent(model=driver("coordinator"),tools=[alpha,beta],
            middleware=[ToolDiscovery([alpha,beta],profile="agent-search-v2")],checkpointer=saver)
    config={"configurable":{"thread_id":"fake"}}
    await build().ainvoke({"messages":[HumanMessage(content="Pick alpha.")]},config)
    await build().ainvoke({"messages":[HumanMessage(content="Now pick beta.")]},config)
    names=[{x["name"] for x in binding} for binding in driver.bindings["coordinator"]]
    assert "alpha" in names[2] and "beta" not in names[2]
    assert "alpha" not in names[3] and "beta" in names[3]


@pytest.mark.asyncio
async def test_v2_multiple_selected_tools_execute_and_are_cleared_together():
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke,call
    seen=[]
    def alpha()->str:
        """A synthetic alpha tool."""
        seen.append("alpha"); return "a"
    def beta()->str:
        """A synthetic beta tool."""
        seen.append("beta"); return "b"
    both=AIMessage(content="",tool_calls=[call("alpha",{},"a"),call("beta",{},"b")])
    driver=Driver(coordinator=[invoke("select_tools",names=["alpha","beta"]),both,AIMessage(content="done")])
    agent=create_agent(model=driver("coordinator"),tools=[alpha,beta],
        middleware=[ToolDiscovery([alpha,beta],profile="agent-search-v2")])
    await agent.ainvoke({"messages":[HumanMessage(content="Use both.")]})
    names=[{x["name"] for x in binding} for binding in driver.bindings["coordinator"]]
    assert {"alpha","beta"}.issubset(names[1]) and not ({"alpha","beta"}&names[2])
    assert sorted(seen)==["alpha","beta"]


@pytest.mark.asyncio
async def test_v2_concurrent_selections_return_error_and_can_be_corrected():
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke,call
    def alpha()->str:
        """A synthetic alpha tool."""
        return "a"
    def beta()->str:
        """A synthetic beta tool."""
        return "b"
    collision=AIMessage(content="",tool_calls=[call("select_tools",{"names":["alpha"]},"a"),call("select_tools",{"names":["beta"]},"b")])
    driver=Driver(coordinator=[collision,invoke("select_tools",names=["alpha"]),invoke("alpha"),AIMessage(content="done")])
    agent=create_agent(model=driver("coordinator"),tools=[alpha,beta],middleware=[ToolDiscovery([alpha,beta],profile="agent-search-v2")])
    result=await agent.ainvoke({"messages":[HumanMessage(content="Choose.")]})
    errors=[m for m in result["messages"] if isinstance(m,ToolMessage) and m.name=="select_tools" and m.status=="error"]
    assert len(errors)==2 and all("CONCURRENT_TOOL_SELECTION" in str(m.content) for m in errors)
    assert any(isinstance(m,ToolMessage) and m.name=="alpha" and m.content=="a" for m in result["messages"])


@pytest.mark.asyncio
async def test_v2_selection_parallel_with_business_call_is_rejected_but_business_executes():
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke,call
    seen=[]
    def alpha()->str:
        """A synthetic alpha tool."""
        seen.append("alpha");return "a"
    def beta()->str:
        """A synthetic beta tool."""
        return "b"
    mixed=AIMessage(content="",tool_calls=[call("select_tools",{"names":["beta"]},"select"),call("alpha",{},"alpha")])
    driver=Driver(coordinator=[invoke("select_tools",names=["alpha"]),mixed,AIMessage(content="done")])
    agent=create_agent(model=driver("coordinator"),tools=[alpha,beta],middleware=[ToolDiscovery([alpha,beta],profile="agent-search-v2")])
    result=await agent.ainvoke({"messages":[HumanMessage(content="Use alpha.")]})
    errors=[m for m in result["messages"] if isinstance(m,ToolMessage) and m.name=="select_tools" and m.status=="error"]
    assert len(errors)==1 and "CONCURRENT_TOOL_SELECTION" in str(errors[0].content)
    assert seen==["alpha"]
    last={t["name"] for t in driver.bindings["coordinator"][-1]}
    assert "alpha" not in last and "beta" not in last


@pytest.mark.asyncio
async def test_v2_pending_call_executes_once_after_reopen_without_schema():
    from langgraph.checkpoint.memory import MemorySaver
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke
    seen=[]
    def alpha()->str:
        """A synthetic alpha tool."""
        seen.append("alpha");return "a"
    driver=Driver(coordinator=[invoke("select_tools",names=["alpha"]),invoke("alpha"),AIMessage(content="done")])
    saver=MemorySaver()
    def build(interrupt):
        return create_agent(model=driver("coordinator"),tools=[alpha],middleware=[ToolDiscovery([alpha],profile="agent-search-v2")],checkpointer=saver,interrupt_before=["tools"] if interrupt else None)
    config={"configurable":{"thread_id":"pending"}}
    agent=build(True)
    await agent.ainvoke({"messages":[HumanMessage(content="Use alpha.")]},config)
    await agent.ainvoke(None,config)
    state=await agent.aget_state(config)
    assert seen==[] and state.next and not state.values.get("_discovered_tools")
    await build(False).ainvoke(None,config)
    assert seen==["alpha"]
    assert "alpha" not in {x["name"] for x in driver.bindings["coordinator"][-1]}


@pytest.mark.asyncio
async def test_v2_pending_call_survives_sqlite_saver_close_reopen(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from report_agent.tool_discovery import ToolDiscovery
    from test_deep_runtime import Driver,invoke
    seen=[]
    def alpha()->str:
        """A synthetic alpha tool."""
        seen.append("alpha");return "a"
    driver=Driver(coordinator=[invoke("select_tools",names=["alpha"]),invoke("alpha"),AIMessage(content="done")])
    config={"configurable":{"thread_id":"pending-sqlite"}}
    def build(saver,interrupt):
        return create_agent(model=driver("coordinator"),tools=[alpha],middleware=[ToolDiscovery([alpha],profile="agent-search-v2")],checkpointer=saver,interrupt_before=["tools"] if interrupt else None)
    path=str(tmp_path/"checkpoints.db")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        agent=build(saver,True)
        await agent.ainvoke({"messages":[HumanMessage(content="Use alpha.")]},config)
        await agent.ainvoke(None,config)
        state=await agent.aget_state(config)
        assert seen==[] and state.next and not state.values.get("_discovered_tools")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        await build(saver,False).ainvoke(None,config)
    assert seen==["alpha"]
    assert "alpha" not in {x["name"] for x in driver.bindings["coordinator"][-1]}
