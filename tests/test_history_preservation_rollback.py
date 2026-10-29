import json
from types import SimpleNamespace
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from report_agent.prompt_provenance import project_plan_history
from report_agent.task_context import TaskContext
from report_agent.store import encode
from test_progress_retention import activate, exchange, ws


def test_plan_history_is_preserved_without_rewriting():
    todos = [{"content": "current", "status": "pending"}]
    old = AIMessage(json.dumps({"review_plan": {"todos": todos}}), id="old")
    request = SimpleNamespace(state={"todos": todos, "messages": [old]}, messages=[old],
        system_message=SystemMessage("Current task bindings and navigation previews.\n" + encode({"native_current_plan": todos})))
    request.override = lambda **kw: SimpleNamespace(**{**request.__dict__, **kw})
    result = project_plan_history(request)
    assert result.messages == [old]
    assert result.messages[0].content == old.content


async def test_history_preview_not_cleared_and_originals_remain_readable(ws):
    activate(ws)
    mw = TaskContext(ws, "coordinator")
    messages = sum((exchange(mw, str(i), ("Evidence %s " % i) * 700) for i in range(4)), [])
    originals = [m.model_dump() for m in messages]
    update = await mw.abefore_model({"messages": messages}, None)
    if update is not None:
        from langgraph.graph.message import add_messages
        messages = add_messages(messages, update["messages"])
    assert [m.content for m in messages] == [m["content"] for m in originals]
    assert all(not m.additional_kwargs.get("report_preview_cleared") for m in messages)


def test_old_cleared_preview_restores_owned_range_only(ws):
    from report_agent.task_context import restore_cleared_previews, read_observation
    activate(ws)
    mw = TaskContext(ws, "coordinator")
    messages = exchange(mw, "old", "Evidence retained in original. " * 300)
    original = messages[-1]
    delivery = original.additional_kwargs["report_observation_delivery"]
    ref = original.additional_kwargs["report_observation_ref"]
    saved = read_observation(ws, "coordinator", ref, 0, 1)
    cleared = {k:v for k,v in saved.items() if k not in {"text", "offset", "end", "next_offset", "complete_tool_result", "complete_field"}}
    cleared.update(preview_cleared=True, previously_presented_range=delivery)
    old = original.model_copy(update={"content":encode(cleared), "additional_kwargs":{**original.additional_kwargs, "report_preview_cleared":True}})
    restored = restore_cleared_previews(ws, "coordinator", [messages[0], old])
    assert json.loads(restored[1].content)["text"] == json.loads(original.content)["text"]
    assert json.loads(old.content)["preview_cleared"] is True
    # Actor mismatch must not turn the reference into another role's data.
    other = restore_cleared_previews(ws, "reviewer", [messages[0], old])
    assert other[1] == old
    corrupt = old.model_copy(update={"content":encode({**cleared, "sha256":"0"*64})})
    assert restore_cleared_previews(ws, "coordinator", [messages[0], corrupt])[1] == corrupt


async def test_old_preview_reaches_sdk_after_sqlite_checkpoint_reopen(ws):
    import httpx
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.graph import StateGraph, MessagesState, START, END
    from langgraph.types import Command, interrupt
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.task_context import read_observation
    from test_prompt_native_sdk_inputs import completion
    from test_hierarchical_content import seed
    activate(ws); seed(ws)
    mw = TaskContext(ws, "coordinator")
    ai, original = exchange(mw, "old", "Evidence on the original page. " * 300)
    delivery = original.additional_kwargs["report_observation_delivery"]
    ref = original.additional_kwargs["report_observation_ref"]
    saved = read_observation(ws, "coordinator", ref, 0, 1)
    cleared = {k:v for k,v in saved.items() if k not in {"text", "offset", "end", "next_offset", "complete_tool_result", "complete_field"}}
    cleared.update(preview_cleared=True, previously_presented_range=delivery)
    old = original.model_copy(update={"content":encode(cleared), "additional_kwargs":{**original.additional_kwargs,"report_preview_cleared":True}})
    wires=[]
    client=model_async_client(ws.store, "coordinator")
    async def respond(request):
        wires.append(json.loads(request.content))
        return completion(request, "done")
    client._transport=httpx.MockTransport(respond); client._mounts.clear()
    model=GLMChatOpenAI(model="glm-5.3",api_key="fake",base_url="https://fixture.invalid/v1",
        use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
    async def node(state):
        assert interrupt("pause") == "continue"
        req=SimpleNamespace(state=state,messages=state["messages"],system_message=SystemMessage("Role."))
        req.override=lambda **kw: SimpleNamespace(**{**req.__dict__,**kw})
        async def handler(request):
            return await model.ainvoke([request.system_message,*request.messages])
        await mw.awrap_model_call(req,handler)
        return {}
    def graph(saver):
        b=StateGraph(MessagesState);b.add_node("work",node);b.add_edge(START,"work");b.add_edge("work",END)
        return b.compile(checkpointer=saver)
    path=str(ws.store.root / "history-rollback-checkpoint.db");config={"configurable":{"thread_id":"rollback"}}
    try:
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await graph(saver).ainvoke({"messages":[ai,old]},config)
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            g=graph(saver);await g.ainvoke(Command(resume="continue"),config)
            state=await g.aget_state(config)
            assert next(m for m in state.values["messages"] if m.id==old.id).content==old.content
        assert len(wires)==1
        tool=next(m for m in wires[0]["messages"] if m.get("tool_call_id")==old.tool_call_id)
        assert json.loads(tool["content"])["text"] == json.loads(original.content)["text"]
    finally:
        await model.root_async_client.close();model.root_client.close()


def test_cleared_empty_tail_restores_only_if_it_is_the_exact_end(ws):
    from report_agent.task_context import restore_cleared_previews, save_observation, read_observation
    activate(ws); mw=TaskContext(ws, "coordinator")
    ref,_=save_observation(ws,"coordinator",ToolMessage("abc",name="read_source",tool_call_id="source"))
    exact=read_observation(ws,"coordinator",ref,3,1)
    original=mw.bound_result(ToolMessage(encode(exact),name="read_tool_observation",tool_call_id="read",id="old"))
    delivery=original.additional_kwargs["report_observation_delivery"]
    cleared={k:v for k,v in exact.items() if k not in {"text","offset","end","next_offset","complete_tool_result","complete_field"}}
    cleared.update(preview_cleared=True,previously_presented_range=delivery)
    old=original.model_copy(update={"content":encode(cleared),"additional_kwargs":{**original.additional_kwargs,"report_preview_cleared":True}})
    result=restore_cleared_previews(ws,"coordinator",[old])
    assert json.loads(result[0].content)["text"] == ""
    assert json.loads(result[0].content)["offset"] == 3
    assert json.loads(old.content)["preview_cleared"]


def test_tampered_field_identity_is_not_restored(ws):
    from report_agent.task_context import restore_cleared_previews, save_observation, read_observation
    activate(ws);mw=TaskContext(ws,"coordinator")
    ref,_=save_observation(ws,"coordinator",ToolMessage(encode({"a":"evidence"}),name="read_source",tool_call_id="source"))
    exact=read_observation(ws,"coordinator",ref,0,4,["a"])
    original=mw.bound_result(ToolMessage(encode(exact),name="read_tool_observation",tool_call_id="read",id="old"))
    delivery={**original.additional_kwargs["report_observation_delivery"],"field_sha256":"0"*64}
    cleared={k:v for k,v in exact.items() if k not in {"text","offset","end","next_offset","complete_tool_result","complete_field"}}
    cleared.update(preview_cleared=True,previously_presented_range=delivery)
    old=original.model_copy(update={"content":encode(cleared),"additional_kwargs":{**original.additional_kwargs,"report_observation_delivery":delivery,"report_preview_cleared":True}})
    assert restore_cleared_previews(ws,"coordinator",[old])[0] == old
