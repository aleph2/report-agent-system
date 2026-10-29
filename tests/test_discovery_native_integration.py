"""Opt-in search integrates with the actual native agent and release binding."""
import pytest
from langchain_core.messages import AIMessage
from report_agent.deep_runtime import run_report
from report_agent.workspace import Workspace
from test_deep_runtime import Driver,invoke
from test_deliverable_declaration_v4 import case

@pytest.mark.asyncio
async def test_coordinator_discovers_original_tool_in_native_runtime(case):
    cs,*_=case;ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    driver=Driver(coordinator=[invoke("search_tools",query="project_status"),
        invoke("project_status"),AIMessage(content="done")])
    result=await run_report(ws,driver)
    assert result["last_error"] is None
    bindings=driver.bindings["coordinator"]
    assert "search_tools" in {x["name"] for x in bindings[0]}
    assert "project_status" not in {x["name"] for x in bindings[0]}
    assert "project_status" in {x["name"] for x in bindings[1]}
    assert "read_source_page" not in {x["name"] for x in bindings[1]}


def test_opt_in_discovery_profile_is_bound_and_cannot_be_removed(case):
    from report_agent.tool_discovery import bind_profile
    from report_agent.errors import ActionRejected
    cs,*_=case
    bind_profile(cs.store,None)
    assert cs.store.get("tool_discovery_binding") is None
    bind_profile(cs.store,"agent-search-v1")
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_PROFILE_MISMATCH"):
        bind_profile(cs.store,None)

def test_legacy_checkpoint_cannot_silently_enable_discovery(case):
    from report_agent.tool_discovery import bind_profile
    from report_agent.errors import ActionRejected
    cs,*_=case
    (cs.store.root/"checkpoints.db").touch()
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_REQUIRES_FRESH_CASE"):
        bind_profile(cs.store,"agent-search-v1")


def test_direct_builder_rejects_profile_removal_after_binding(case):
    from langgraph.checkpoint.memory import MemorySaver
    from report_agent.deep_runtime import build_agent
    from report_agent.errors import ActionRejected
    cs,*_=case;ws=Workspace(cs.store)
    base=cs.store.manifest
    cs.store.set("manifest",{**base,"tool_discovery_profile":"agent-search-v1"})
    build_agent(ws,Driver(coordinator=[]),MemorySaver())
    cs.store.set("manifest",base)
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_PROFILE_MISMATCH"):
        build_agent(Workspace(cs.store),Driver(coordinator=[]),MemorySaver())


def test_registry_identity_is_bound_and_cannot_change_on_reopen(case):
    from report_agent.tool_discovery import bind_profile, bind_registry
    from report_agent.errors import ActionRejected
    cs,*_=case
    bind_profile(cs.store,"agent-search-v1")
    first={"coordinator":{"first":"one"},"writer":{"second":"two"}}
    bind_registry(cs.store,first)
    bind_registry(cs.store,first)
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_REGISTRY_MISMATCH"):
        bind_registry(cs.store,{"coordinator":{"first":"changed"},"writer":{"second":"two"}})


@pytest.mark.asyncio
async def test_bad_search_is_observed_and_agent_can_correct_it(case):
    cs,*_=case;ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    driver=Driver(coordinator=[invoke("search_tools",query="x",limit=51),
        invoke("search_tools",query="project_status"),invoke("project_status"),AIMessage(content="done")])
    result=await run_report(ws,driver)
    assert result["last_error"] is None, result["last_error"]
    assert any("INVALID_TOOL_SEARCH_ARGUMENTS" in str(m.content) for _,_,messages in driver.calls for m in messages if hasattr(m,"content"))


def test_direct_builder_rejects_changed_native_tool_registry(case,monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from report_agent import deep_runtime
    from report_agent.errors import ActionRejected
    cs,*_=case;ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    deep_runtime.build_agent(ws,Driver(coordinator=[]),MemorySaver())
    original=deep_runtime.business_tools
    def changed(workspace,role,knowledge,text_model):
        registered=original(workspace,role,knowledge,text_model)
        if role == "coordinator":
            def project_status(extra: str):
                """Altered synthetic schema."""
                return {"unexpected":extra}
            return [project_status if getattr(t,"__name__",None)=="project_status" else t for t in registered]
        return registered
    monkeypatch.setattr(deep_runtime,"business_tools",changed)
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_REGISTRY_MISMATCH"):
        deep_runtime.build_agent(Workspace(cs.store),Driver(coordinator=[]),MemorySaver())


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["agent-search-v1", "agent-search-v2"])
async def test_actual_sdk_wire_discloses_only_searched_role_tool(case, profile):
    import json,httpx
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI,model_async_client
    from test_bounded_review import Model
    from test_prompt_native_sdk_inputs import completion
    cs,*_=case;ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":profile})
    models={};wires=[]
    def factory(role):
        if role=="text_tool": return Model("synthetic")
        if role in models: return models[role]
        client=model_async_client(ws.store,role)
        async def respond(request):
            body=json.loads(request.content);wires.append((role,body))
            step=sum(r==role for r,_ in wires)-1
            assert role=="coordinator"
            if step==0:return completion(request,"",("search_tools",{"query":"project_status"}))
            if step==1 and profile=="agent-search-v2":return completion(request,"",("select_tools",{"names":["project_status"]}))
            if step==(2 if profile=="agent-search-v2" else 1):return completion(request,"",("project_status",{}))
            return completion(request,"done")
        client._transport=httpx.MockTransport(respond);client._mounts.clear()
        models[role]=GLMChatOpenAI(model="glm-5.3",api_key="fake",base_url="https://fixture.invalid/v1",
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result=await deep_runtime.run_report(ws,factory)
        assert result["last_error"] is None,result["last_error"]
        names=[{t["function"]["name"] for t in body["tools"]} for _,body in wires]
        selected_index=2 if profile=="agent-search-v2" else 1
        assert len(names)==selected_index+2 and "search_tools" in names[0] and "project_status" not in names[0]
        if profile=="agent-search-v2": assert "project_status" not in names[1] and "select_tools" in names[1]
        assert "project_status" in names[selected_index] and "read_source_page" not in names[selected_index]
        if profile=="agent-search-v2": assert "project_status" not in names[-1]
        from report_agent.prompt_provenance import public_projection
        from report_agent.store import digest
        events=[e for e in ws.store.events() if e["kind"]=="prompt_final_http_input"]
        assert len(events)==len(wires)
        captures=[ws.store.get(e["data"]["capture_key"]) for e in events]
        assert [c["final_tool_schema_sha256"] for c in captures] == [digest(public_projection(body)["tools"]) for _,body in wires]
    finally:
        for model in models.values():
            await model.root_async_client.close();model.root_client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["agent-search-v1", "agent-search-v2"])
async def test_discovery_keeps_reviewer_export_scope_enforced(case,monkeypatch,profile):
    from langchain.agents import create_agent
    from report_agent.content_export import export_snapshot
    from report_agent.content_tasks import delegated_task
    from report_agent.deep_runtime import business_tools,BusinessBoundary
    from report_agent.tool_discovery import ToolDiscovery
    from test_review_binding_v4 import review_call
    from test_review_work_units import configured
    from report_agent import content_export
    cs,output,ws,_=configured(case);co=case[1]
    assigned=export_snapshot(cs,co,"assigned-search",None,deliverable={"kind":"deliverable","operation_id":"published"})["result"]["export_ref"]
    other=export_snapshot(cs,co,"unassigned-search",cs.read(assigned)["payload"]["snapshot_ref"])["result"]["export_ref"]
    criterion=cs.list_objects("Criterion")[0]["ref"]
    request=review_call([criterion],scope={"kind":"mapped","items":[{"criterion_ref":criterion,
        "target_ref":output["refs"]["a"],"assessment_kind":"export","artifact_refs":[assigned],
        "extent":{"kind":"export_structure","artifact_ref":assigned}}]})
    opened=[]; original=content_export._bytes
    def track(*args):
        opened.append(args[1]);return original(*args)
    monkeypatch.setattr(content_export,"_bytes",track)
    with delegated_task(ws,"coordinator",request):
        registered=business_tools(ws,"reviewer",None,None)
        read=next(t for t in registered if getattr(t,"__name__",None)=="read_content_export")
        before_other=[]
        def try_other(messages):
            before_other.extend(opened)
            return invoke("read_content_export",export_ref=other)
        def select():
            return [invoke("select_tools",names=["read_content_export"])] if profile == "agent-search-v2" else []
        driver=Driver(reviewer=[invoke("search_tools",query="read_content_export"),
            *select(), invoke("read_content_export",export_ref=assigned),
            *select(), try_other,AIMessage(content="done")])
        agent=create_agent(model=driver("reviewer"),tools=[read],
            middleware=[BusinessBoundary(ws,"reviewer"),ToolDiscovery([read],profile=profile)])
        await agent.ainvoke({"messages":[__import__("langchain_core.messages",fromlist=["HumanMessage"]).HumanMessage(content="Check the assigned export.")]})
    assert before_other and opened == before_other
    assert any("FORBIDDEN" in str(m.content).upper() for _,_,messages in driver.calls for m in messages if hasattr(m,"content"))


def test_reopen_rejects_changed_runtime_sources(case, monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from report_agent import deep_runtime, prompt_sources
    from report_agent.errors import ActionRejected
    cs,*_=case; ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    deep_runtime.build_agent(ws,Driver(coordinator=[]),MemorySaver())
    def changed(store):
        key="synthetic_changed_runtime"
        store.set(key,{"source_files":{"fixture.py":"a"*64},"project_file_sha256":"b"*64})
        return key
    monkeypatch.setattr(prompt_sources,"record_runtime_version",changed)
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_REGISTRY_MISMATCH"):
        deep_runtime.build_agent(Workspace(cs.store),Driver(coordinator=[]),MemorySaver())


def test_discovery_requires_complete_runtime_identity(case, monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from report_agent import deep_runtime, prompt_sources
    from report_agent.errors import ActionRejected
    cs,*_=case; ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    monkeypatch.setattr(prompt_sources,"record_runtime_version",lambda store: None)
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_RUNTIME_IDENTITY_UNAVAILABLE"):
        deep_runtime.build_agent(ws,Driver(coordinator=[]),MemorySaver())


def test_reopen_rejects_changed_framework_version(case, monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from importlib import metadata
    from report_agent import deep_runtime
    from report_agent.errors import ActionRejected
    cs,*_=case; ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    deep_runtime.build_agent(ws,Driver(coordinator=[]),MemorySaver())
    original=metadata.version
    monkeypatch.setattr(metadata,"version",lambda name: "0.synthetic" if name == "langgraph" else original(name))
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_REGISTRY_MISMATCH"):
        deep_runtime.build_agent(Workspace(cs.store),Driver(coordinator=[]),MemorySaver())


def test_discovery_rejects_missing_framework_version(case, monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from importlib import metadata
    from report_agent import deep_runtime
    from report_agent.errors import ActionRejected
    cs,*_=case; ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v1"})
    original=metadata.version
    def missing(name):
        if name == "langgraph": raise metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(metadata,"version",missing)
    with pytest.raises(ActionRejected,match="TOOL_DISCOVERY_RUNTIME_IDENTITY_UNAVAILABLE"):
        deep_runtime.build_agent(ws,Driver(coordinator=[]),MemorySaver())


@pytest.mark.asyncio
async def test_native_v2_requires_explicit_selection_before_schema(case):
    from report_agent.deep_runtime import run_report
    from report_agent.workspace import Workspace
    from langchain_core.messages import AIMessage
    cs,*_=case; ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v2"})
    driver=Driver(coordinator=[invoke("search_tools",query="project_status"),
        invoke("select_tools",names=["project_status"]),invoke("project_status"),AIMessage(content="done")])
    result=await run_report(ws,driver)
    assert result["last_error"] is None, result["last_error"]
    names=[{tool["name"] for tool in binding} for binding in driver.bindings["coordinator"]]
    assert "project_status" not in names[0] and "project_status" not in names[1]
    assert "project_status" in names[2]


@pytest.mark.asyncio
async def test_native_v2_invalid_selection_observed_then_direct_exact_selection(case):
    from report_agent.deep_runtime import run_report
    from report_agent.workspace import Workspace
    from langchain_core.messages import AIMessage,ToolMessage
    cs,*_=case; ws=Workspace(cs.store)
    cs.store.set("manifest",{**cs.store.manifest,"tool_discovery_profile":"agent-search-v2"})
    driver=Driver(coordinator=[invoke("select_tools",names=["not_a_real_tool"]),
        invoke("select_tools",names=["project_status"]),invoke("project_status"),AIMessage(content="done")])
    result=await run_report(ws,driver)
    assert result["last_error"] is None,result["last_error"]
    assert any("INVALID_TOOL_SELECTION" in str(m.content) for _,_,messages in driver.calls for m in messages if isinstance(m,ToolMessage))
    bindings=[{t["name"] for t in b} for b in driver.bindings["coordinator"]]
    assert "project_status" not in bindings[1] and "project_status" in bindings[2]
