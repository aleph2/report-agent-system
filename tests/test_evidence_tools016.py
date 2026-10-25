"""Native tool feedback and capability checks, not semantic quality claims."""
import hashlib
import json
import asyncio

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime, vision
from report_agent.catalog import Catalog
from report_agent.errors import ActionRejected
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke, observation
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


def native_source_investigation(tmp_path):
    from report_agent.content_store import ContentStore
    from report_agent.hierarchical_tools import actor_for
    from test_ingestion import pdf_bytes
    data = pdf_bytes(("First physical page", "Second physical page"))
    store = Store(tmp_path)
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources/original.pdf").write_bytes(data)
    store.initialize({"goal": "Investigate the supplied original, leaving any review unperformed.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "sources": [{"id": "original", "title": "Synthetic original", "filename": "original.pdf",
            "content": "Frozen OCR must not be replaced", "coverage": "partial",
            "copied_path": "sources/original.pdf", "sha256": hashlib.sha256(data).hexdigest()}]})
    ws, cs = Workspace(store), ContentStore(store)
    Catalog(store)
    actor = actor_for("coordinator")
    inputs = cs.import_inputs(actor, "inputs", ["original"])["result"]
    refs = cs.commit(actor, "scope", [
        {"client_key": "root", "type": "ContentNode", "payload": {"kind": "report",
            "body": {"text": "Original source investigation"}, "qualifiers": {}, "claim_kind": "structure"}},
        {"client_key": "criterion", "type": "Criterion", "payload": {
            "requirement_refs": [inputs["requirement_ref"]], "purpose": "Investigate the original source",
            "scope": "Supplied source", "expected_outcome": "Return actual observations",
            "evidence_expectation": "Original text and images", "allowed_limits": "No semantic verdict"}}
    ])["result"]["refs"]
    snapshot = cs.freeze(actor, "snapshot", refs["root"],
        [inputs["requirement_ref"], *inputs["source_refs"], *refs.values()])["result"]["snapshot_ref"]
    assignment = {"subagent_type": "reviewer", "description": "Investigate the supplied original source.",
        "review_snapshot_ref": snapshot, "review_requirements": [{"target_ref": refs["root"],
            "criterion_ref": refs["criterion"], "scope_id": "source-investigation",
            "required_checks": ["Inspect original source observations"], "required_materials": [{
                "requirement_index": 0, "purpose": "Assigned target and source",
                "refs": [refs["root"], *inputs["source_refs"]]}]}]}
    return ws, cs, assignment, inputs["source_refs"]


def assert_source_receipt(ws, cs, messages, tool, role, source_refs):
    message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == tool)
    receipt = message.artifact["source_material"]
    issued = ws.store.get("source_material:" + receipt["receipt"])
    assert issued["actor"]["role"] == role
    if role == "reviewer":
        assert issued["actor"]["task_id"] == cs.list_objects("DelegatedTask")[0]["ref"]["id"]
    assert receipt["source_version_refs"] == source_refs


@pytest.mark.parametrize("role", ["coordinator", "reviewer"])
async def test_native_search_unknown_argument_feedback_then_correction(tmp_path, role):
    ws, cs, assignment, source_refs = native_source_investigation(tmp_path)
    manifest, blocks = ws.store.manifest, Catalog(ws.store).read("original")
    original = (tmp_path / "sources/original.pdf").read_bytes()

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
        assert_source_receipt(ws, cs, messages, "search_sources", role, source_refs)
        return AIMessage(content="Source investigation observed; no semantic verdict.")

    steps = [invoke("search_sources", query="Frozen", source="original"), correct, checked]
    driver = Driver(coordinator=steps if role == "coordinator" else [invoke("task", **assignment),
        AIMessage(content="Investigation received; review remains unperformed.")],
        **({"reviewer": steps} if role == "reviewer" else {}))
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert not cs.list_objects("ReviewRecord")
    assert all(called != "rubric_grader" for called, _, _ in driver.calls)
    assert ws.store.manifest == manifest and Catalog(ws.store).read("original") == blocks
    assert (tmp_path / "sources/original.pdf").read_bytes() == original


async def test_native_grader_awaits_vision_and_cannot_write_upstream(tmp_path, monkeypatch):
    ws, cs, assignment, source_refs = native_source_investigation(tmp_path)
    model = VisionModel()
    monkeypatch.setenv("REPORT_VISION_MODEL", model.returned_model)
    catalog = Catalog(ws.store)
    manifest, blocks = ws.store.manifest, catalog.read("original")
    original = ws.store.root / "sources" / "original.pdf"
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    before_objects = cs.list_objects()
    completed = []
    create = model.create
    async def delayed_create(**kwargs):
        await asyncio.sleep(0)
        response = await create(**kwargs)
        completed.append(True)
        return response
    monkeypatch.setattr(model, "create", delayed_create)
    monkeypatch.setattr(vision, "configured_vision_client", lambda: model)

    def grade(messages):
        result = observation(messages, "analyze_source_image")
        assert result["status"] == "observed" and result["source"]["source_id"] == "original"
        assert completed == [True]
        assert_source_receipt(ws, cs, messages, "analyze_source_image", "reviewer", source_refs)
        return AIMessage(content="Actual image observation received; no semantic verdict.")

    driver = Driver(coordinator=[invoke("task", **assignment), AIMessage(content="Source observation received.")],
        reviewer=[invoke("analyze_source_image", source_id="original", question="Read text", page=1), grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert len(model.calls) == 1
    assert model.calls[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    names = {t["name"] for binding in driver.bindings["reviewer"] for t in binding}
    assert "analyze_source_image" in names
    assert not names & {"submit_result", "knowledge_write", "knowledge_delete", "ask_human", "select_delivery",
                        "commit_objects", "save_text_node", "select_content_delivery", "process_report_content"}
    assert ws.store.manifest == manifest and catalog.read("original") == blocks
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    assert [o for o in cs.list_objects() if o["ref"]["type"] != "DelegatedTask"] == before_objects
    assert not cs.list_objects("ReviewRecord")
    assert not any(role == "rubric_grader" for role, _, _ in driver.calls)
