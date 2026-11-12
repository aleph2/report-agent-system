"""C1 contract: current call state, no saved frames, versioned live history; offline only."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from langchain.agents.middleware.types import ExtendedModelResponse, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command, interrupt

from report_agent import deep_runtime, task_context, summary_recovery
from report_agent.content_tasks import delegated_task
from report_agent.decision_state import compact_context
from report_agent.errors import ActionRejected
from report_agent.task_context import TaskContext, exact_task_context
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline, review_call


def tail(request):
    matches = [m for m in request.messages if m.type == "human"
               and m.text.startswith("[host-observations]\n")]
    assert len(matches) == 1
    return json.loads(matches[0].text.split("\n", 1)[1])


def old_effective_state(middleware, request):
    """Baseline 976cb3b projection, independently of the new tail renderer."""
    exact = exact_task_context(middleware.workspace, middleware.role)
    state = compact_context(exact)
    resources = {key: exact.get(key) for key in ("execution_resources", "execution_token_resources")}
    for key in resources:
        state.pop(key, None)
    task = task_context.current_user_task(middleware.workspace, middleware.role, request.state, request.messages)
    if task is not None:
        state["current_user_task"] = task["text"]
    if middleware.review_materials and middleware.role == "reviewer":
        assigned = exact["assignment"]
        state["review_materials"] = task_context.complete_review_materials(middleware.workspace, assigned)
        state["assignment"] = {k: v for k, v in assigned.items()
                               if k not in {"review_requirements", "review_commission_basis"}}
    if task_context.progress_enabled(middleware.workspace):
        state["received_returns"] = summary_recovery.current_returns(
            middleware.workspace, middleware.role, focused=middleware.focused)
    return deepcopy(state), resources


def request(ws, role, history):
    return ModelRequest(model=Driver()(role), tools=[], state={"messages": history},
                        messages=history, system_message=SystemMessage(content="Existing authored role."))


@pytest.mark.parametrize("role", ["coordinator", "writer", "reviewer", "layout"])
async def test_call_tail_equals_old_effective_state_without_history_or_receipt(ws, role):
    _, _, refs, snapshot, _ = seed(ws)
    with ExitStack() as scope:
        if role != "coordinator":
            task = review_call(snapshot, refs) if role == "reviewer" else {"id": role+"-task", "args": {"subagent_type": role, "description": "Task scope"}}
            if role == "layout":
                task["args"]["layout_snapshot_ref"] = snapshot
            scope.enter_context(delegated_task(ws, "coordinator", task))
        history = [HumanMessage(content="Keep the original task and all its conditions.")]
        middleware = TaskContext(ws, role)
        for turn in range(3):
            ws.store.set("feedback", [{"id": str(turn), "origin": "operator", "message": "current"}] if turn < 2 else [])
            incoming = request(ws, role, history)
            expected, resources = old_effective_state(middleware, incoming)
            before = deepcopy(history)
            async def handler(outgoing):
                value = tail(outgoing)
                assert value["current_state"] == expected
                assert value["current_execution_observations"] == resources
                assert sum(m.type == "human" for m in outgoing.messages) == 2
                return ModelResponse(result=[AIMessage(content="new decision")])
            response = await middleware.awrap_model_call(incoming, handler)
            assert history == before
            assert all(m.type == "ai" for m in response.result)
            history += response.result
        with ws.store.connect() as db:
            assert db.execute("SELECT count(*) FROM state WHERE key LIKE 'task_state_frame:%'").fetchone()[0] == 0

@pytest.mark.parametrize("outcome", ["error", "command"])
async def test_failed_call_and_command_never_persist_tail(ws, outcome):
    seed(ws)
    original = HumanMessage(content="Original instruction.")
    history = [original]
    async def handler(outgoing):
        assert "current_state" in tail(outgoing)
        if outcome == "error":
            raise RuntimeError("offline unknown outcome")
        return ExtendedModelResponse(
            model_response=ModelResponse(result=[AIMessage(content="decision")]),
            command=Command(update={"messages": [HumanMessage(content="program note")]}))
    if outcome == "error":
        with pytest.raises(RuntimeError, match="offline unknown"):
            await TaskContext(ws, "coordinator").awrap_model_call(request(ws, "coordinator", history), handler)
    else:
        result = await TaskContext(ws, "coordinator").awrap_model_call(request(ws, "coordinator", history), handler)
        assert len(result.model_response.result) == 1
        note = result.command.update["messages"][0]
        assert note.content == "program note"
        assert note.additional_kwargs["report_model_command_message"] is True
    assert history == [original]
    with ws.store.connect() as db:
        assert db.execute("SELECT count(*) FROM state WHERE key LIKE 'task_state_frame:%'").fetchone()[0] == 0


async def saved_history(ws, version=None, pending=False):
    graph = StateGraph(MessagesState)
    def node(state):
        if pending:
            interrupt({"issue_id": "synthetic-owner-wait"})
        return {}
    graph.add_node("work", node)
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    async with AsyncSqliteSaver.from_conn_string(str(ws.store.root / "checkpoints.db")) as saver:
        compiled = graph.compile(checkpointer=saver)
        metadata = {} if version is None else {"history_format_version": version}
        await compiled.ainvoke({"messages": [HumanMessage(content="[host-state]\nOld state.")]},
                               {"configurable": {"thread_id": "report"}, "metadata": metadata})


def file_hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.iterdir() if p.is_file() and p.suffix in {".db", ".sqlite3"}}


@pytest.mark.parametrize("version,pending", [(None, False), (None, True), (1, False), (99, True)])
async def test_pre_c1_history_refused_before_live_side_effects(ws, version, pending):
    seed(ws)
    await saved_history(ws, version, pending)
    before = file_hashes(ws.store.root)
    def never_model(*args, **kwargs):
        pytest.fail("Old history must not dispatch model/tools")
    with pytest.raises(ActionRejected, match="HISTORY_FORMAT_REQUIRES_FRESH_RUN"):
        await deep_runtime.run_report(ws, never_model)
    assert file_hashes(ws.store.root) == before


@pytest.mark.parametrize("shape", ["absent", "empty_file", "empty_schema", "current", "current_wait"])
async def test_fresh_or_current_history_passes_admission(ws, shape):
    seed(ws)
    path = ws.store.root / "checkpoints.db"
    if shape == "empty_file":
        path.touch()
    elif shape == "empty_schema":
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            await saver.setup()
    elif shape.startswith("current"):
        await saved_history(ws, 2, shape == "current_wait")
    before = file_hashes(ws.store.root)
    deep_runtime.require_native_runtime(ws)
    assert file_hashes(ws.store.root) == before


def test_frame_classifier_and_delta_writer_are_removed():
    from report_agent import task_state_delivery as delivery
    for name in ("verified_frame", "frame_delivery", "prepare_delivery", "persist_frame", "apply_frame", "delta_ops"):
        assert not hasattr(delivery, name), name


async def test_c1_full_flow_measurement_and_effective_state(tmp_path, monkeypatch, record_property):
    """V1/V2/V6: real operator paths; scripted outputs, no provider-spend claim."""
    from collections import Counter
    from langchain_core.messages.utils import count_tokens_approximately
    from report_agent import task_context
    from test_deep_runtime import ScriptedChat
    from test_fake_draft_flow import test_complete_native_draft_flow
    from test_context_call_delivery import old_effective_state, tail
    measurements=[]
    comparisons=[]
    original_context=task_context.TaskContext.awrap_model_call
    async def compared(self,incoming,handler):
        expected,resources=old_effective_state(self,incoming)
        async def check(outgoing):
            value=tail(outgoing)
            assert value["current_state"]==expected
            assert value["current_execution_observations"]==resources
            comparisons.append(self.role)
            return await handler(outgoing)
        return await original_context(self,incoming,check)
    monkeypatch.setattr(task_context.TaskContext,"awrap_model_call",compared)
    original=ScriptedChat._agenerate
    async def observed(self,messages,**kwargs):
        schemas=self.driver.bindings.get(self.role,[[]])[-1]
        tools=[{"type":"function","function":t} for t in schemas]
        host=[m for m in messages if m.type=="human" and m.text.startswith("[host-observations]\n")]
        states=[json.loads(m.text.split("\n",1)[1]).get("current_state") for m in host]
        states=[v for v in states if v is not None]
        from report_agent.prompt_provenance import _CALL
        call=_CALL.get()
        indicator=bool(call and any(isinstance(part,dict) and 'writer-indicator-step' in part.get('files',[]) for part in call['sources']))
        path='indicator_writer' if indicator else 'prose_writer' if self.role=='writer' else 'qualitative_reviewer' if self.role=='reviewer' else self.role
        measurements.append({
            "path":path,"role":self.role,"call":sum(r["role"]==self.role for r in measurements)+1,
            "total_proxy_tokens":count_tokens_approximately(messages,tools=tools),
            "system_proxy_tokens":count_tokens_approximately([m for m in messages if m.type=="system"]),
            "tools_characters":len(json.dumps(tools,ensure_ascii=False)),
            "tool_result_proxy_tokens":count_tokens_approximately([m for m in messages if m.type=="tool"]),
            "human_proxy_tokens":count_tokens_approximately([m for m in messages if m.type=="human"]),
            "model_proxy_tokens":count_tokens_approximately([m for m in messages if m.type=="ai"]),
            "current_state_characters":sum(len(json.dumps(v,ensure_ascii=False)) for v in states),
            "review_material_characters":sum(len(json.dumps(v.get("review_materials"),ensure_ascii=False)) for v in states if "review_materials" in v),
            "saved_state_frames":sum("report_task_state_frame" in m.additional_kwargs for m in messages)})
        return await original(self,messages,**kwargs)
    monkeypatch.setattr(ScriptedChat,"_agenerate",observed)
    await test_complete_native_draft_flow(tmp_path,False)
    assert {"coordinator","writer","reviewer","text_tool"} <= {r["role"] for r in measurements}
    assert all(r["saved_state_frames"]==0 for r in measurements)
    assert comparisons and all(role=="coordinator" for role in comparisons)
    record_property("v1_full_flow_calls",json.dumps(measurements))
    record_property("v2_state_comparisons",json.dumps(dict(Counter(comparisons))))


async def test_final_boundary_refreshes_resources_after_supporting_request(ws):
    from report_agent.request_budget import RequestBudget, request_budget
    from report_agent.prompt_provenance import AgentPromptBoundary
    seed(ws)
    resources=RequestBudget(20)
    async def supporting_then_model(outgoing):
        resources.reserve()
        async def final(changed):
            assert tail(changed)["current_execution_observations"]["execution_resources"]==resources.snapshot()
            return ModelResponse(result=[AIMessage("done")])
        return await AgentPromptBoundary(ws,"coordinator").awrap_model_call(outgoing,final)
    from report_agent.hierarchical_tools import role_prompt
    incoming=request(ws,"coordinator",[HumanMessage("Current task.")])
    incoming=incoming.override(system_message=SystemMessage(role_prompt("coordinator")))
    with request_budget(resources):
        await TaskContext(ws,"coordinator").awrap_model_call(incoming,supporting_then_model)
