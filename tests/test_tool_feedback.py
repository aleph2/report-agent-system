import pytest

from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.report_runtime import feedback_tool, worker_tools
from test_report_trunk import workspace


@pytest.mark.parametrize('error', [ValueError('decode failed'), PermissionError('file denied'), RuntimeError('unexpected')])
def test_unexpected_errors_are_not_converted_to_request_feedback(error):
    def broken():
        raise error
    with pytest.raises(type(error)) as caught:
        feedback_tool(broken)()
    assert caught.value is error


@pytest.mark.parametrize('error', [ActionRejected('INVALID_REQUEST'), ActionForbidden('RESULT_OWNER_MISMATCH')])
async def test_domain_errors_are_feedback_for_sync_and_async_tools(error):
    def broken():
        raise error
    async def async_broken():
        raise error
    assert feedback_tool(broken)()['accepted'] is False
    assert (await feedback_tool(async_broken)())['error']['message'] == str(error)


async def test_analysis_failure_does_not_record_successful_source_observation(tmp_path, monkeypatch, request):
    # Explicit migration: source-only public analysis, not the retired materials
    # worker or its used_source_ids counter. Failure is never changed into success.
    from copy import deepcopy
    import json
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.catalog import Catalog
    from report_agent.content_store import ContentStore
    from test_deep_runtime import Driver, call, observation
    purpose = "Summarize the supplied access restriction."
    args = {"source_id": "s", "purpose": purpose, "offset": 0, "limit": 10}
    def fresh_project(folder):
        store = Store(folder)
        store.initialize({"goal": "Inspect optional source analysis only.",
            "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
            "sources": [{"id": "s", "content": "Daytime access only.", "coverage": "complete"}]})
        ws = Workspace(store)
        original = deepcopy(store.manifest["sources"])
        blocks = Catalog(store).read("s", 0, 10)
        return ws, original, blocks
    failed_ws, failed_sources, failed_blocks = fresh_project(tmp_path / "failed-case")
    failures = []
    original_error_data = deep_runtime.error_data
    def capture(exc):
        failures.append({"type": type(exc).__name__, "message": str(exc)})
        return original_error_data(exc)
    monkeypatch.setattr(deep_runtime, "error_data", capture)
    def failed_model(messages):
        raise RuntimeError("SYNTHETIC_ANALYSIS_FAILURE")
    failed_driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("analyze_text", args, "failed-source-analysis")])],
                           text_tool=[failed_model])
    failed = await deep_runtime.run_report(failed_ws, failed_driver)
    assert failed["last_error"]["type"] == "RuntimeError", failed
    assert {"type": "RuntimeError", "message": "SYNTHETIC_ANALYSIS_FAILURE"} in failures
    assert sum(role == "text_tool" for role, _, _ in failed_driver.calls) == 1
    with failed_ws.store.connect() as db:
        attempts = [(key, json.loads(value)) for key, value in db.execute(
            "SELECT key,value FROM state WHERE key LIKE 'bounded_review_attempt:%'").fetchall()]
        assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM content_observations").fetchone()[0] == 0
    assert len(attempts) == 1 and attempts[0][1]["state"] in {"reserved", "unknown"}
    assert not any(e["kind"] in {"evidence_analysis_completed", "evidence_analysis_reused"} for e in failed_ws.store.events())
    assert not ContentStore(failed_ws.store).list_objects()
    # Direct admission control only: this does not pretend to resume a native checkpoint.
    tools = {t.__name__: t for t in deep_runtime.business_tools(failed_ws, "coordinator", None, failed_driver("text_tool"))}
    calls_before = len(failed_driver.calls)
    with pytest.raises(ActionRejected, match="REVIEW_ANALYSIS_PREVIOUS_ATTEMPT_UNRESOLVED"):
        await tools["analyze_text"](**args)
    assert len(failed_driver.calls) == calls_before
    assert failed_ws.store.manifest["sources"] == failed_sources
    assert Catalog(failed_ws.store).read("s", 0, 10) == failed_blocks
    success_ws, success_sources, success_blocks = fresh_project(tmp_path / "independent-success-case")
    observed, packets = {}, []
    def successful_model(messages):
        packet = json.loads(messages[-1].content)
        packets.append(deepcopy(packet))
        assert packet["question"] == purpose
        assert {k: packet["evidence"][0]["observation"][k] for k in success_blocks} == success_blocks
        return AIMessage(content="Synthetic analysis result: daytime access only.")
    def fresh_result(messages):
        value = observation(messages, "analyze_text")
        assert value["reused"] is False
        assert value["analysis"] == "Synthetic analysis result: daytime access only."
        assert {k: value["evidence"][0]["observation"][k] for k in success_blocks} == success_blocks
        observed["first"] = deepcopy(value)
        return AIMessage(content="", tool_calls=[call("analyze_text", args, "successful-source-analysis-reuse")])
    def reused_result(messages):
        value = observation(messages, "analyze_text")
        assert value["reused"] is True
        assert {**value, "reused": False} == observed["first"]
        return AIMessage(content="Source observation only, no verified report or coverage claim.")
    success_driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("analyze_text", args, "successful-source-analysis")]),
                                          fresh_result, reused_result], text_tool=[successful_model])
    succeeded = await deep_runtime.run_report(success_ws, success_driver)
    assert succeeded["last_error"] is None, succeeded
    assert sum(role == "text_tool" for role, _, _ in success_driver.calls) == len(packets) == 1
    kinds = [e["kind"] for e in success_ws.store.events()]
    assert kinds.count("evidence_analysis_completed") == kinds.count("evidence_analysis_reused") == 1
    with success_ws.store.connect() as db:
        assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 1
        attempt = json.loads(db.execute("SELECT value FROM state WHERE key LIKE 'bounded_review_attempt:%'").fetchone()[0])
    assert attempt["state"] == "completed"
    assert not ContentStore(success_ws.store).list_objects()
    assert success_ws.store.manifest["sources"] == success_sources
    assert Catalog(success_ws.store).read("s", 0, 10) == success_blocks
    request.node.user_properties.append(("source_analysis_control", json.dumps({
        "failed_attempt": attempts, "captured_failures": failures, "successful_packets": packets,
        "first_success_observation": observed["first"]}, ensure_ascii=False)))
