"""Protocol and boundary checks; scripted decisions are not model-quality evidence."""
import json
import httpx
import pytest
from langchain_core.messages import AIMessage
from report_agent import deep_runtime
from report_agent.content_export import export_snapshot
from report_agent.content_delivery import current_delivery
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.content_models import Ref
from test_hierarchical_content import ws, seed, submission, review_item
from test_deep_runtime import Driver, invoke, observation, call


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    def denied(*args, **kwargs):
        pytest.fail("Network forbidden in protocol tests")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


def new_path(ws):
    ws.store.set("manifest", {**ws.store.manifest, "review_entrypoint": "delegated-reviewer-v1"})


def review_assignment(snapshot, refs):
    return {"subagent_type": "reviewer", "description": "Check exact assigned delivery content",
            "review_snapshot_ref": snapshot, "review_requirements": [{"target_ref": refs["claim"],
            "criterion_ref": refs["k"], "scope_id": "delivery", "required_checks": ["rule comparison"]}]}


def test_final_submission_atomic_idempotent_permissions_and_version(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
    data = submission(snapshot, refs, review_item(snapshot, refs["k"], verdict=None))
    for role in ("coordinator", "writer", "rubric_grader"):
        with pytest.raises(ActionForbidden):
            cs.submit_review(actor_for(role), "bad-"+role, data, {}, export)
    with delegated_task(ws, "coordinator", call("task", {"subagent_type":"reviewer", "description":"Review"}, "review-task")) as (_, reviewer):
        result = cs.submit_review(reviewer, "final", data, {}, export)
        assert cs.submit_review(reviewer, "final", data, {}, export) == result
        assert len(cs.list_objects("ReviewRecord")) == 1
        assert ws.store.get("content_final_review")["review_ref"] == result["result"]["review_ref"]
        ws.store.set("content_delivery", {"snapshot_ref":snapshot,"export_ref":export})
        assert current_delivery(ws.store)["overall_verdict"] is None
        wrong = {**data,"target_ref":export}
        with pytest.raises(ActionRejected, match="REVIEW_TARGET_OUTSIDE_SNAPSHOT"):
            cs.submit_review(reviewer,"wrong",wrong,{},export)
        assert len(cs.list_objects("ReviewRecord")) == 1
        local_wrong = {**data,"items":[{**data["items"][0],"target_ref":export}]}
        with pytest.raises(ActionRejected, match=r"items\[0\].target_ref"):
            cs.submit_review(reviewer,"wrong-local",local_wrong,{})


@pytest.mark.parametrize("verdict", ["not_satisfied", "undetermined", None])
async def test_feedback_returns_control_without_automatic_grader(ws, verdict):
    new_path(ws)
    cs, actor, refs, snapshot, _ = seed(ws)
    export = export_snapshot(cs, actor,"export",snapshot)["result"]["export_ref"]
    def submit(messages):
        receipt = observation(messages,"read_context")["receipt_id"]
        data = submission(snapshot,refs,review_item(refs["claim"],refs["k"],receipt,verdict))
        return invoke("submit_review",operation_id="review",review=data,delivery_export_ref=export)
    driver = Driver(coordinator=[
        invoke("select_content_delivery",operation_id="select",snapshot_ref=snapshot,export_ref=export),
        invoke("task",**review_assignment(snapshot, refs)),
        invoke("record_execution_decision",operation_id="decision",decision="continue",reason="Investigate next useful correction",evidence=["saved review"],unresolved=["remaining checks"]),
        invoke("read_feedback"), AIMessage(content="Preserved incomplete delivery.")],
        reviewer=[invoke("read_context",target_ref=snapshot),submit,AIMessage(content="Saved review and limitations.")])
    result=await deep_runtime.run_report(ws,driver)
    assert result["last_error"] is None, result
    assert "rubric_grader" not in driver.created
    assert ws.store.get("content_execution_decision")["decision"] == "continue"
    assert current_delivery(ws.store)["items"]
    assert not current_delivery(ws.store)["final_review_current"]
    assert result["execution_status"] == "completed"
    assert current_delivery(ws.store)["overall_verdict"] != "satisfied"
    assert any("read_feedback" in str(m.tool_calls) for role,_,msgs in driver.calls if role=="coordinator" for m in msgs if isinstance(m,AIMessage))


async def test_final_text_and_termination_do_not_approve(ws):
    new_path(ws)
    driver=Driver(coordinator=[invoke("record_execution_decision",operation_id="stop",decision="terminate",reason="No available evidence",evidence=[],unresolved=["No report reviewed"]),AIMessage(content="Done")])
    result=await deep_runtime.run_report(ws,driver)
    assert result["last_error"] is None
    assert current_delivery(ws.store)["overall_verdict"] is None
    assert ws.store.get("content_final_review") is None


def test_role_service_bundles_do_not_mix_credentials(tmp_path,monkeypatch):
    from report_agent.model_config import load_mixed_services, role_service
    from report_agent.deep_models import configured_model
    from report_agent.store import Store
    path=tmp_path/"config.env"
    path.write_text("HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-flash\nHIGHWAY_MODEL_DEEPSEEK_BASE_URL=https://api.deepseek.com\nHIGHWAY_MODEL_DEEPSEEK_API_KEY=ds-test\nHIGHWAY_MODEL_NAME=glm-5.3\nHIGHWAY_MODEL_BASE_URL=https://glm.example/v1\nHIGHWAY_MODEL_API_KEY=glm-test\n")
    # Restore process environment after loader mutation.
    import os
    with monkeypatch.context() as m:
        m.setattr(os,"environ",os.environ.copy())
        os.environ["REPORT_REVIEWER_MODEL"]="stale-model"
        os.environ["REPORT_COORDINATOR_API_KEY"]="stale-key"
        safe=load_mixed_services(path)
        assert "test" not in json.dumps(safe)
        assert role_service("writer")==("glm-5.3","https://glm.example/v1","glm-test")
        assert role_service("reviewer")[2]=="ds-test"
        assert role_service("coordinator")[2]=="ds-test"
        store=Store(tmp_path/"store")
        assert configured_model(store,"writer").model_name=="glm-5.3"
        assert configured_model(store,"reviewer").model_name=="deepseek-flash"
        del os.environ["REPORT_WRITER_API_KEY"]
        with pytest.raises(RuntimeError,match="INCOMPLETE_ROLE_SERVICE"):
            configured_model(store,"writer")


async def test_delegated_transport_error_is_feedback_not_business_stop(ws):
    new_path(ws)
    cs, actor, refs, snapshot, _ = seed(ws)
    driver=Driver(coordinator=[invoke("task",**review_assignment(snapshot, refs)),
        invoke("record_execution_decision",operation_id="after-error",decision="handoff",reason="Service failed; preserve execution uncertainty",evidence=["tool feedback"],unresolved=["review unexecuted"]),AIMessage(content="Unresolved")])
    driver.fail_once=("reviewer",0)
    result=await deep_runtime.run_report(ws,driver)
    assert result["last_error"] is None, result
    assert ws.store.get("content_execution_decision")["decision"]=="handoff"
    assert any(e["kind"]=="content_delegation_failed" for e in ws.store.events())


async def test_native_checkpoint_resume_without_grader(ws):
    new_path(ws)
    driver=Driver(coordinator=[invoke("content_status"),AIMessage(content="Preserve incomplete work")])
    driver.fail_once=("coordinator",1)
    first=await deep_runtime.run_report(ws,driver)
    assert first["status"]=="failed"
    second=await deep_runtime.run_report(ws,driver)
    assert second["last_error"] is None, second
    assert "rubric_grader" not in driver.created


@pytest.mark.parametrize("cancelled", [False, True])
async def test_program_errors_and_cancellation_are_not_semantic_feedback(ws,cancelled):
    import asyncio
    new_path(ws)
    cs, actor, refs, snapshot, _ = seed(ws)
    def fail(messages):
        if cancelled:
            raise asyncio.CancelledError()
        raise TypeError("Synthetic implementation failure")
    driver=Driver(coordinator=[invoke("task",**review_assignment(snapshot, refs))],reviewer=[fail])
    if cancelled:
        from types import SimpleNamespace
        request=SimpleNamespace(tool=None, tool_call=call("task",review_assignment(snapshot, refs),"cancel-task"))
        request.override=lambda **kwargs: request
        async def cancel_handler(request):
            raise asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await deep_runtime.BusinessBoundary(ws,"coordinator").awrap_tool_call(request,cancel_handler)
    else:
        result=await deep_runtime.run_report(ws,driver)
        assert result["status"]=="failed"
    assert not any(e["kind"]=="content_delegation_failed" for e in ws.store.events())


def test_final_positive_projection_invalidates_on_export_change_and_local_defect(ws):
    from hierarchical_fixtures import delivery_evidence
    cs,actor,refs,snapshot,_=seed(ws)
    export=export_snapshot(cs,actor,"export",snapshot)["result"]["export_ref"]
    ws.store.set("content_delivery",{"snapshot_ref":snapshot,"export_ref":export})
    with delegated_task(ws,"coordinator",call("task",{"subagent_type":"reviewer","description":"Final"},"final-task")) as (_, reviewer):
        receipt=cs.read_context(reviewer,snapshot)["receipt_id"]
        data=submission(snapshot,refs,review_item(snapshot,refs["k"],receipt,"satisfied"))
        data["delivery_checks"]=delivery_evidence(cs,snapshot,export,reviewer)
        cs.submit_review(reviewer,"pass",data,{},export)
        assert current_delivery(ws.store)["overall_verdict"]=="satisfied"
        export2=export_snapshot(cs,actor,"export2",snapshot)["result"]["export_ref"]
        ws.store.set("content_delivery",{"snapshot_ref":snapshot,"export_ref":export2})
        assert current_delivery(ws.store)["overall_verdict"] is None
        ws.store.set("content_delivery",{"snapshot_ref":snapshot,"export_ref":export})
        negative=submission(snapshot,refs,review_item(refs["claim"],refs["k"],receipt,"not_satisfied"))
        cs.submit_review(reviewer,"local-negative",negative,{})
        assert current_delivery(ws.store)["overall_verdict"]=="not_satisfied"


def test_service_binding_rejects_endpoint_or_role_switch(tmp_path,monkeypatch):
    from report_agent.model_config import bind_role_services
    from report_agent.store import Store
    for role in ("COORDINATOR","REVIEWER","WRITER","TEXT_TOOL"):
        for key,value in (("MODEL","glm-5.3"),("BASE_URL","https://example.test/v1"),("API_KEY","secret-test")):
            monkeypatch.setenv("REPORT_"+role+"_"+key,value)
    store=Store(tmp_path)
    store.initialize({"goal":"Test","sources":[{"id":"s","content":"test","coverage":"complete"}]})
    bind_role_services(store)
    assert "secret-test" not in json.dumps(store.get("role_model_services"))
    monkeypatch.setenv("REPORT_WRITER_BASE_URL","https://different.test/v1")
    with pytest.raises(RuntimeError,match="REQUIRES_FRESH"):
        bind_role_services(store)
