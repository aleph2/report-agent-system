"""Scripted protocol exercise, not an evaluation of model autonomy or content quality."""
from report_agent import report_state

from report_agent.catalog import Catalog


async def test_import_library_revision_review_export_protocol(tmp_path):
    # Explicit R7 interface migration: actual current whole-report source/revision
    # chain plus the unchanged historical correction-state transaction contract.
    from library_revision_fixture import current_library_revision_protocol, historical_correction_state_control
    await current_library_revision_protocol(tmp_path)
    historical_correction_state_control(tmp_path)


async def test_rejected_tool_request_returns_observation_and_worker_can_continue(tmp_path):
    import json
    from copy import deepcopy
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke, observation
    from test_evidence_tools016 import native_source_investigation

    ws, cs, _, source_refs = native_source_investigation(tmp_path)
    before_objects = deepcopy(cs.list_objects())
    before_manifest = deepcopy(ws.store.manifest)
    before_blocks = Catalog(ws.store).read("original")
    original_pdf = (tmp_path / "sources/original.pdf").read_bytes()
    captured = {}

    def correct(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "search_sources")
        error = observation(messages, "search_sources")
        assert message.status == "error" and not error["accepted"]
        assert "SEARCH_QUERY_REQUIRED" in str(error)
        captured["error"] = deepcopy(error)
        return invoke("search_sources", query="Frozen", source_id="original")

    def read_found(messages):
        result = observation(messages, "search_sources")
        assert result["total"] == 1 and result["scope"]["searched_source_ids"] == ["original"]
        return invoke("read_source_page", source_id="original", offset=0, limit=50)

    def finish_read(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_source_page")
        result = observation(messages, "read_source_page")
        assert result["blocks"] == before_blocks["blocks"] and result["next_offset"] is None
        assert "Frozen OCR must not be replaced" in str(result["blocks"])
        receipt = message.artifact["source_material"]
        issued = ws.store.get("source_material:" + receipt["receipt"])
        assert issued["actor"]["role"] == "writer"
        task = cs.list_objects("DelegatedTask")[0]
        assert issued["actor"]["task_id"] == task["ref"]["id"]
        assert receipt["source_version_refs"] == source_refs
        captured["read"] = deepcopy(result)
        return AIMessage(content=json.dumps({"source_observation": result, "limitation": "Read only; no report or review completed."}))

    def parent(messages):
        returned = observation(messages, "task")
        assert returned["source_observation"] == captured["read"]
        captured["parent_received"] = True
        return AIMessage(content="Actual source observation received; no report or review approval.")

    driver = Driver(coordinator=[invoke("task", subagent_type="writer",
            description="Read the supplied original, correcting failed tool arguments; return observations without writing a report."), parent],
        writer=[invoke("search_sources", query="", source_id="original"), correct, read_found, finish_read])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert captured["parent_received"] and captured["error"]
    assert not cs.list_objects("ReviewRecord")
    assert [o for o in cs.list_objects() if o["ref"]["type"] != "DelegatedTask"] == before_objects
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert not any(role in {"text_tool", "reviewer", "rubric_grader"} for role, _, _ in driver.calls)
    assert report_state.selected_delivery(ws.store) is None
    assert ws.store.manifest == before_manifest and Catalog(ws.store).read("original") == before_blocks
    assert (tmp_path / "sources/original.pdf").read_bytes() == original_pdf
