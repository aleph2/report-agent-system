"""Native framework traces with offline models; no paid calls or quality claims."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent import deep_runtime
from report_agent.native_trace import read_trace, trace_tools, public_message
from report_agent.errors import ActionRejected
from test_deep_runtime import Driver, invoke, observation
from test_task_supervision import ws, offline


async def all_entries(saver, thread):
    before = None
    entries = []
    while True:
        page = await read_trace(saver, thread, before=before, limit=10, content_limit=16000)
        entries.extend(page["entries"])
        before = page["next_before"]
        if before is None:
            return entries


async def test_coordinator_reads_native_child_calls_and_returns(ws):
    def inspect(messages):
        page = observation(messages, "read_execution_trace")
        assert page["source"] == "langgraph_checkpointer"
        assert page['message_text_included'] is False
        assert all('text' not in e for e in page['entries'])
        assert any(e['type']=='ai' and 'calculate' in e['tool_names'] for e in page['entries'])
        assert any(e['type']=='tool' and e['name']=='calculate' and e['status']=='success' for e in page['entries'])
        assert any(e["agent"] == "writer" for e in page["entries"])
        return AIMessage(content="Observed child evidence; not a semantic verdict.")
    driver = Driver(
        coordinator=[invoke("task", subagent_type="writer", description="Calculate a synthetic value."),
                     invoke("read_execution_trace", limit=100, content_limit=16000), inspect],
        writer=[invoke("calculate", terms=[["1.0","2.0"]]), AIMessage(content="Calculated.")])
    async with deep_runtime.project_agent(ws, driver) as agent:
        await agent.ainvoke({"messages":[("user","Delegate then inspect native history.")]},
                           {"configurable":{"thread_id":"trace-case"}})
    assert "read_execution_trace" in {x["name"] for x in driver.bindings["coordinator"][0]}
    assert "read_execution_trace" not in {x["name"] for x in driver.bindings["writer"][0]}
    assert not any(e["kind"] in {"deep_tool_start","deep_tool_end","deep_tool_rejected",
                                "deep_model_request","deep_model_response"} for e in ws.store.events())
    from report_agent.native_trace import recent_tool_events
    from report_agent.native_trace import inspect_checkpoint
    from hashlib import sha256
    checkpoint_path = ws.store.root / 'checkpoints.db'
    before = sha256(checkpoint_path.read_bytes()).hexdigest()
    saved = inspect_checkpoint(ws.store.root, 'trace-case')
    assert saved['found'] and saved['checkpoint_id']
    assert sha256(checkpoint_path.read_bytes()).hexdigest() == before
    events = recent_tool_events(ws.store.root.resolve(), "trace-case", limit=100)
    assert any(e["data"]["role"] == "writer" and e["kind"] == "deep_tool_end" for e in events)
    assert "content" not in json.dumps(events) and "arguments" not in json.dumps(events)
    assert ws.store.get("native_trace_thread_id") == "trace-case"
    from fastapi.testclient import TestClient
    from report_agent.webapp import create_app
    with TestClient(create_app(ws.store.root)) as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    visible = response.json()["events"]
    assert any(e["data"].get("source") == "native_checkpoint" for e in visible)
    assert all("text" not in e["data"] and "arguments" not in e["data"] for e in visible)
    # Reopen the persisted saver, without running another model. Subagent evidence survives.
    async with AsyncSqliteSaver.from_conn_string(str(ws.store.root/"checkpoints.db")) as saver:
        entries = await all_entries(saver, "trace-case")
        assert any(e["agent"] == "writer" and e["type"] == "tool" for e in entries)
        assert not (await read_trace(saver, "unrelated-thread"))["entries"]


async def test_pagination_detail_error_returns_and_thread_binding(ws):
    secret = "opaque-provider-private-value"
    driver = Driver(coordinator=[
        invoke("calculate", weights=[1.0], scores=[2.0,3.0]),
        AIMessage(content="x"*7000, additional_kwargs={"reasoning_content":secret})])
    async with deep_runtime.project_agent(ws, driver) as agent:
        await agent.ainvoke({"messages":[("user","Synthetic invalid arithmetic.")]},
                           {"configurable":{"thread_id":"bound"}})
    async with AsyncSqliteSaver.from_conn_string(str(ws.store.root/"checkpoints.db")) as saver:
        entries = await all_entries(saver, "bound")
        assert any(json.loads(e["text"]).get("status")=="error" for e in entries if e["type"]=="tool")
        message = next(e for e in entries if e["type"]=="ai" and "xxxxx" in e["text"])
        kw = dict(checkpoint_id=message["checkpoint_id"],namespace=message["namespace"],message_id=message["message_id"])
        first = await read_trace(saver,"bound",**kw,content_limit=80)
        second = await read_trace(saver,"bound",**kw,content_offset=80,content_limit=16000)
        assert first["entries"][0]["text"]+second["entries"][0]["text"] == message["text"]
        assert secret not in json.dumps(entries)
        # Caller cannot choose thread/project; only the injected ToolRuntime config binds it.
        fn=trace_tools(saver)[0]
        assert not (await fn(SimpleNamespace(config={"configurable":{"thread_id":"other"}}),limit=100))["entries"]
        with pytest.raises(ActionRejected):
            await read_trace(saver,"bound",limit=101)


def test_projection_excludes_transport_fields():
    msg=AIMessage(content="public",additional_kwargs={"reasoning_content":"private","strict_wire":{"private":"wire"}})
    assert "private" not in json.dumps(public_message(msg))
    assert msg.additional_kwargs["reasoning_content"]=="private"


async def test_tool_overview_omits_bodies_and_targeted_detail_recovers_exact_message(ws):
    import hashlib
    body='Synthetic public output: '+('large evidence text; '*800)
    secret='private-provider-protocol'
    driver=Driver(coordinator=[AIMessage(content=body,additional_kwargs={'reasoning_content':secret})])
    async with deep_runtime.project_agent(ws,driver) as agent:
        await agent.ainvoke({'messages':[('user','Synthetic trace detail check.')]},
                           {'configurable':{'thread_id':'overview'}})
    async with AsyncSqliteSaver.from_conn_string(str(ws.store.root/'checkpoints.db')) as saver:
        fn=trace_tools(saver)[0]
        runtime=SimpleNamespace(config={'configurable':{'thread_id':'overview'}})
        overview=await fn(runtime,limit=100)
        assert not overview['message_text_included']
        assert body not in json.dumps(overview) and secret not in json.dumps(overview)
        message=next(e for e in overview['entries'] if e['type']=='ai' and e['total_chars']>len(body))
        detail=await fn(runtime,checkpoint_id=message['checkpoint_id'],namespace=message['namespace'],
                        message_id=message['message_id'],content_limit=16000)
        entry=detail['entries'][0]
        text=entry['text']
        while entry['next_content_offset'] is not None:
            more=await fn(runtime,checkpoint_id=message['checkpoint_id'],namespace=message['namespace'],
                          message_id=message['message_id'],content_offset=entry['next_content_offset'],content_limit=16000)
            entry=more['entries'][0];text+=entry['text']
        assert json.loads(text)['content']==body and secret not in text
        assert hashlib.sha256(text.encode()).hexdigest()==message['message_sha256']
        full=await fn(runtime,limit=100,include_message_text=True,content_limit=16000)
        assert full['message_text_included'] and any('text' in e for e in full['entries'])


def test_normal_models_install_status_only(monkeypatch, tmp_path):
    from report_agent.deep_models import configured_model, RuntimeStatus, LocalAudit
    from report_agent.store import Store
    monkeypatch.setattr("report_agent.model_config.role_service",lambda role:("deepseek-v4.1-flash-1017","https://api.deepseek.com","synthetic-test-key"))
    model=configured_model(Store(tmp_path/"model"),"coordinator")
    assert any(isinstance(c,RuntimeStatus) for c in model.callbacks)
    assert not any(isinstance(c,LocalAudit) for c in model.callbacks)

