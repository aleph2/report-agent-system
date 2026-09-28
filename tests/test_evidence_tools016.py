"""Native tool feedback and capability checks, not semantic quality claims."""
import hashlib

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime, vision
from report_agent.catalog import Catalog
from report_agent.errors import ActionRejected
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke, observation
from test_document_tools import workspace
from test_review_feedback import select, verdict
from test_vision import VisionModel


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setattr(deep_runtime, "load_rules", lambda: "Check the report against its source.")

    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def test_search_filters_before_pagination_and_retains_history_semantics(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile", "sources": [
        {"id": "a", "title": "A", "content": "needle", "coverage": "complete"},
        {"id": "b", "title": "B", "content": ("needle" + " " * 3994) * 3, "coverage": "complete"}]})
    catalog = Catalog(store)
    assert catalog.search("needle")["total"] == 4
    first = catalog.search("needle", limit=2, source_id="b")
    assert first["total"] == 3 and first["next_offset"] == 2
    assert first["scope"] == {"source_id": "b", "include_history": False, "searched_source_ids": ["b"]}
    assert {m["source_id"] for m in first["matches"]} == {"b"}
    last = catalog.search("needle", offset=2, limit=2, source_id="b")
    assert len(last["matches"]) == 1 and last["next_offset"] is None
    for source_id in ("foreign", "B", ""):
        with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
            catalog.search("needle", source_id=source_id)
    catalog.import_file("replacement.txt", b"new needle", replaces_id="a")
    excluded = catalog.search("needle", source_id="a")
    assert excluded["total"] == 0 and excluded["scope"]["searched_source_ids"] == []
    assert catalog.search("needle", 0, 10, True, source_id="a")["total"] == 1
    assert catalog.read("a")["blocks"][0]["text"] == "needle"


@pytest.mark.parametrize("role", ["coordinator", "rubric_grader"])
async def test_native_search_unknown_argument_feedback_then_correction(tmp_path, role):
    ws = workspace(tmp_path)
    ws.initialize()

    def correct(messages):
        error = observation(messages, "search_sources")
        assert not error["accepted"]
        assert "SEARCH_ARGUMENTS_MUST_BE" in str(error)
        assert [m for m in messages if isinstance(m, ToolMessage)][-1].status == "error"
        return invoke("search_sources", query="Frozen", source_id="original")

    def checked(messages):
        result = observation(messages, "search_sources")
        assert result["scope"]["searched_source_ids"] == ["original"]
        assert result["total"] == 1
        return verdict("satisfied") if role == "rubric_grader" else save()

    def save():
        return invoke("submit_result", title="Report", body="Frozen OCR [original].",
                      source_ids=["original"], input_ids=[], replaces_id="")

    steps = [invoke("search_sources", query="Frozen", source="original"), correct, checked]
    driver = Driver(coordinator=steps + [select, AIMessage(content="Ready")] if role == "coordinator"
                    else [save(), select, AIMessage(content="Ready")],
                    rubric_grader=steps if role == "rubric_grader" else [verdict("satisfied")])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result


async def test_native_grader_awaits_vision_and_cannot_write_upstream(tmp_path, monkeypatch):
    ws, model = workspace(tmp_path), VisionModel()
    ws.initialize()
    catalog = Catalog(ws.store)
    manifest, blocks = ws.store.manifest, catalog.read("original")
    original = ws.store.root / "sources" / "original.pdf"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    monkeypatch.setattr(vision, "configured_vision_client", lambda: model)

    def grade(messages):
        result = observation(messages, "analyze_source_image")
        assert result["status"] == "observed" and result["source"]["source_id"] == "original"
        return verdict("satisfied")

    driver = Driver(coordinator=[invoke("submit_result", title="Report", body="Frozen OCR [original].",
                        source_ids=["original"], input_ids=[], replaces_id=""), select, AIMessage(content="Ready")],
                    rubric_grader=[invoke("analyze_source_image", source_id="original", question="Read text", page=1), grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft" and len(model.calls) == 1
    names = {t["name"] for binding in driver.bindings["rubric_grader"] for t in binding}
    assert "analyze_source_image" in names
    assert not names & {"submit_result", "knowledge_write", "knowledge_delete", "ask_human", "select_delivery"}
    assert ws.store.manifest == manifest and catalog.read("original") == blocks
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
