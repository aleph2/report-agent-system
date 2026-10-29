"""Fresh strict recovery never repeats a request with an unknown outcome."""
import httpx
import pytest
from report_agent.model_recovery import activate_recovery, recover_model_call, RecoveryBlocked, load_recovery_policy
from report_agent.store import Store
from test_deliverable_declaration_v4 import case

@pytest.mark.asyncio
async def test_strict_unknown_fences_restart_without_another_provider_attempt(tmp_path):
    store=Store(tmp_path);store.initialize({"goal":"Fake", "sources":[{"id":"s","title":"fake","content":"fake","coverage":"complete"}]})
    activate_recovery(store,authorization="fake test only",version=2)
    assert load_recovery_policy(store)["version"] == 2
    sent=[]
    async def invoke():
        sent.append("sent")
        raise httpx.ReadTimeout("synthetic after dispatch")
    args={"store":store,"role":"writer","profile":{"model":"fake","endpoint":"https://fake.invalid"},
          "payload":{"model":"fake","messages":[{"role":"user","content":"fake","coverage":"complete"}]},
          "invoke":invoke,"parse_raw":lambda x:x,"owner":{"task_id":"fake"}}
    with pytest.raises(httpx.ReadTimeout): await recover_model_call(**args)
    assert sent == ["sent"]
    with pytest.raises(RecoveryBlocked,match="RECOVERY_PRIOR_ATTEMPT_UNRESOLVED"):
        await recover_model_call(**args)
    assert sent == ["sent"]


@pytest.mark.asyncio
async def test_real_sdk_unknown_keeps_hold_and_reopened_owner_cannot_resend(tmp_path,monkeypatch):
    from report_agent.model_recovery import recovery_block
    from report_agent.token_budget import TokenBudget, token_budget
    from test_transport_observation import setup_model, use_mock, close
    store,model=setup_model(tmp_path,monkeypatch,role="coordinator")
    model.root_async_client.max_retries=0
    activate_recovery(store,authorization="fake test only",version=2)
    sent=[]
    def respond(request):
        sent.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/"budget.db",200,{"deepseek-v4.1-flash":40})
    try:
        from report_agent.model_invocation import is_model_timeout
        with token_budget(budget), pytest.raises(Exception) as first:
            await model.ainvoke("synthetic input")
        assert is_model_timeout(first.value)
        assert sent == [1]
        first_budget = budget.snapshot()
        assert first_budget["attempt_states"] == {"reserved":1}
        reopened,other=setup_model(tmp_path,monkeypatch,role="coordinator")
        other.root_async_client.max_retries=0
        await use_mock(other,respond)
        try:
            with token_budget(budget), pytest.raises(Exception) as caught:
                await other.ainvoke("synthetic input")
            blocked = recovery_block(caught.value)
            assert blocked is not None and str(blocked) == "RECOVERY_PRIOR_ATTEMPT_UNRESOLVED"
            assert sent == [1]
            assert budget.snapshot() == first_budget
        finally:
            await close(other)
    finally:
        await close(model)


def test_strict_policy_cannot_be_rebound_or_enable_extra_retry(tmp_path):
    from report_agent.model_recovery import POLICY_KEY
    store=Store(tmp_path);store.initialize({"goal":"Fake", "sources":[{"id":"s","title":"fake","content":"fake","coverage":"complete"}]})
    policy=activate_recovery(store,authorization="fake test only",version=2)
    with pytest.raises(RecoveryBlocked,match="RECOVERY_POLICY_ALREADY_BOUND"):
        activate_recovery(store,authorization="fake test only",version=1)
    store.set(POLICY_KEY,{**policy,"extra_per_call":1})
    with pytest.raises(RecoveryBlocked,match="RECOVERY_POLICY_READ_FAILED"):
        load_recovery_policy(store)


def test_invalid_bool_policy_version_fails_closed(tmp_path):
    from report_agent.model_recovery import POLICY_KEY
    store=Store(tmp_path);store.initialize({"goal":"Fake", "sources":[{"id":"s","title":"fake","content":"fake","coverage":"complete"}]})
    policy=activate_recovery(store,authorization="fake test only",version=2)
    store.set(POLICY_KEY,{**policy,"version":True})
    with pytest.raises(RecoveryBlocked,match="RECOVERY_POLICY_READ_FAILED"):
        load_recovery_policy(store)


@pytest.mark.asyncio
async def test_received_body_reused_locally_after_reopen_without_new_provider_attempt(tmp_path):
    from report_agent.model_recovery import capture_response
    store=Store(tmp_path);store.initialize({"goal":"Fake", "sources":[{"id":"s","title":"fake","content":"fake","coverage":"complete"}]})
    activate_recovery(store,authorization="fake test only",version=2)
    sent=[]
    async def invoke():
        sent.append(1)
        request=httpx.Request("POST","https://fake.invalid")
        capture_response(httpx.Response(200,json={"value":"synthetic"},request=request))
        raise httpx.ReadTimeout("synthetic local conversion timeout",request=request)
    def args(target):
        return {"store":target,"role":"writer","profile":{"model":"fake","endpoint":"https://fake.invalid"},
            "payload":{"model":"fake","messages":[{"role":"user","content":"fake"}]},
            "invoke":invoke,"parse_raw":lambda x:x,"owner":{"task_id":"fake"}}
    assert await recover_model_call(**args(store)) == {"value":"synthetic"}
    assert await recover_model_call(**args(Store(tmp_path))) == {"value":"synthetic"}
    assert sent == [1]


@pytest.mark.asyncio
async def test_strict_saved_sdk_response_reuses_without_new_reservation(tmp_path,monkeypatch):
    from report_agent.deep_models import GLMChatOpenAI
    from report_agent.errors import ModelRequestDeadlineExceeded
    from report_agent.token_budget import TokenBudget, token_budget
    from test_transport_observation import setup_model, use_mock, close, body
    store,model=setup_model(tmp_path,monkeypatch,role="coordinator")
    model.root_async_client.max_retries=0
    activate_recovery(store,authorization="fake test only",version=2)
    seen=[]; parse_count=[]; original=GLMChatOpenAI._create_chat_result
    def parse(self,*args,**kwargs):
        parse_count.append(1)
        if len(parse_count)==1: raise ModelRequestDeadlineExceeded(600)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(GLMChatOpenAI,"_create_chat_result",parse)
    def respond(request):
        seen.append(1);return httpx.Response(200,json=body())
    await use_mock(model,respond)
    budget=TokenBudget(tmp_path/"budget.db",200,{"deepseek-v4.1-flash":40})
    try:
        with token_budget(budget):
            assert (await model.ainvoke("synthetic input")).content=="unchanged result"
            initial=budget.snapshot()
            assert (await model.ainvoke("synthetic input")).content=="unchanged result"
        assert seen==[1] and budget.snapshot()==initial
        assert initial["attempt_states"] == {"settled":1} and initial["recorded_tokens"] == 10
    finally:
        await close(model)


@pytest.mark.asyncio
async def test_native_completed_writer_return_is_not_reexecuted_after_co_interruption(case):
    from report_agent.deep_runtime import run_report
    from report_agent.workspace import Workspace
    from langchain_core.messages import AIMessage,ToolMessage
    from test_deep_runtime import Driver,invoke
    cs,*_=case; ws=Workspace(cs.store); seen=[]
    def writer(messages):
        seen.append("writer-completed");return AIMessage(content="Synthetic writer result")
    def interrupted(messages):
        raise RuntimeError("synthetic coordinator interruption")
    first=Driver(coordinator=[invoke("task",subagent_type="writer",description="Synthetic task"),interrupted],writer=[writer])
    result=await run_report(ws,first)
    assert result["last_error"] is not None and seen==["writer-completed"]
    def forbidden_writer(messages):
        pytest.fail("Completed writer was reexecuted")
    second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[forbidden_writer])
    resumed=await run_report(Workspace(Store(cs.store.root)),second)
    assert resumed["last_error"] is None and seen==["writer-completed"]
    assert any(role=="coordinator" and any(isinstance(m,ToolMessage) and m.name=="task" and "Synthetic writer result" in m.content for m in messages) for role,_,messages in second.calls)


@pytest.mark.asyncio
async def test_native_writer_unknown_then_interruption_never_resends(ws, monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from report_agent.content_store import ContentStore
    from report_agent.deep_runtime import run_report
    from report_agent.token_budget import TokenBudget, token_budget
    from report_agent.workspace import Workspace
    from test_bounded_deadline import offline_model, close_model
    from test_deep_runtime import Driver, invoke
    from test_text_work import writer_call
    activate_recovery(ws.store,authorization="fake test only",version=2)
    model=offline_model(ws,monkeypatch); model.root_async_client.max_retries=0
    monkeypatch.setattr("report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS",600)
    seen=[]
    async def timeout(request):
        seen.append(1)
        raise httpx.ReadTimeout("fake post dispatch",request=request)
    model.http_async_client._transport=httpx.MockTransport(timeout)
    model.http_async_client._mounts.clear()
    budget=TokenBudget(tmp_path / "budget.db",20000,{"glm-5.3":10000})
    def interrupted(messages):
        raise RuntimeError("fake interruption after unknown tool result")
    first=Driver(coordinator=[AIMessage(content="",tool_calls=[writer_call()])],
        writer=[invoke("process_report_content",operation_id="unknown",objective="Describe source",
            object_type="ContentNode",source_selections=[{"source_id":"s"}]),interrupted])
    try:
        with token_budget(budget):
            result=await run_report(ws,model_factory=lambda role:model if role=="text_tool" else first(role))
        assert result["last_error"] is not None and seen==[1]
        initial=budget.snapshot()
        assert initial["reserved_or_unknown_upper_bounds"]==10000
        second=Driver(coordinator=[AIMessage(content="unused"),AIMessage(content="continued")],writer=[AIMessage(content="unused"),AIMessage(content="No result adopted")])
        with token_budget(budget):
            resumed=await run_report(Workspace(Store(ws.store.root)),model_factory=lambda role:model if role=="text_tool" else second(role))
        assert seen==[1] and budget.snapshot()==initial
        assert resumed["last_error"] is None
        from langchain_core.messages import ToolMessage
        assert any(role == "writer" and any(isinstance(m, ToolMessage) and "EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED" in str(m.content) for m in messages) for role,_,messages in second.calls)
        assert ContentStore(ws.store).list_objects("ContentNode")==[]
    finally:
        await close_model(model)

from test_task_supervision import ws
