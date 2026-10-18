"""Search views and native identity with synthetic sources/models; no semantic claims."""
import copy
import json

import httpx
import pytest
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import HumanMessage

from report_agent.acceptance import active_criteria, bind_mode, criteria_rules, save_criteria
from report_agent.catalog import Catalog
from report_agent.deep_runtime import BusinessBoundary, business_tools
from report_agent.errors import ActionRejected
from report_agent.review import native_review, review_delivery, reviewer_prompt
from report_agent.source_search import (BINDING_KEY, CONFIG_KEY, VERSION, bind_source_search,
                                      configure_source_search, search_observation)
from report_agent.source_tables import with_source_tables
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_acceptance_runtime import verdict
from test_deep_runtime import Driver, invoke, observation
from test_document_tools import snapshot, workspace as source_workspace
from test_source_tables import table_pdf


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    def denied(*args, **kwargs):
        pytest.fail("No network in source-search tests")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


@pytest.fixture
def ws(tmp_path):
    workspace = source_workspace(tmp_path, table_pdf(), content="alpha\n\nbeta\n\nalpha")
    workspace.initialize()
    bind_mode(workspace)
    workspace.store.set("knowledge_enabled", False)
    standard = save_criteria(workspace, actor="coordinator", title="Compilation",
        criteria=[{"condition": "The compilation agrees with the supplied inventory.",
                   "requirement_refs": ["manifest.goal"], "allowed_limitations": ""}],
        source_ids=["original"], input_ids=[], reason="Synthetic commission")
    task = workspace.request_task("draft", "Compile", [])
    draft = workspace.submit(task["id"], actor="writer", title="Inventory", body="alpha and beta [original].",
                             source_ids=["original"], input_ids=[standard["id"]])
    workspace.select_delivery(draft["id"], "")
    workspace.store.set("clean_import", {"baseline": "synthetic source-only import", **{
        key: False for key in ("copied_results", "copied_reviews", "copied_feedback", "copied_issues",
                               "copied_graph", "copied_checkpoints", "new_ocr")}})
    Catalog(workspace.store)
    with workspace.store.connect() as db:
        db.execute("DELETE FROM source_blocks")
        db.executemany("INSERT INTO source_blocks VALUES (?,?,?,?)", [
            ("original", 0, "page 1; chars 1-5", "alpha"),
            ("original", 1, '{"page":2,"method":"ocr"}; chars 1-4', "beta"),
            ("original", 2, "page 1; chars 6-10", "alpha")])
    return workspace


def tools(ws):
    return {tool.__name__: tool for tool in business_tools(ws, "reviewer", None, None)}


def grader(ws, driver=None):
    driver = driver or Driver()
    names = {"search_sources", "read_source_page", "inspect_source_page"}
    return native_review(ws, driver("rubric_grader"), [v for k, v in tools(ws).items() if k in names],
        criteria_rules(active_criteria(ws)), middleware=[TodoListMiddleware(), BusinessBoundary(ws, "rubric_grader")])


def payload(ws, review, identity="synthetic-review"):
    return review._grader_input({"messages": [HumanMessage("Assess the selected candidate.")],
        "rubric": criteria_rules(active_criteria(ws)),
        "_rubric_criteria": [c["id"] for c in active_criteria(ws)["criteria"]],
        "_current_grading_run_id": identity}, 0)


def test_unconfigured_default_and_explicit_full_are_exact_old_observation(ws):
    current = tools(ws)
    before = snapshot(ws)
    expected = with_source_tables(ws, Catalog(ws.store).search("alpha", 0, 1, source_id="original"))
    assert current["search_sources"]("alpha", 0, 1, "original") == expected
    assert current["search_sources"]("alpha", 0, 1, "original", "full") == expected
    assert bind_source_search(ws) is None
    assert snapshot(ws) == before


def test_references_preserve_matches_paging_and_defer_extraction_truthfully(ws, monkeypatch):
    configure_source_search(ws)
    current = tools(ws)
    before = snapshot(ws)
    expected = Catalog(ws.store).search("alpha", 0, 1, source_id="original")
    with monkeypatch.context() as patch:
        patch.setattr("report_agent.source_tables.source_tables", lambda *a, **k: pytest.fail("Deferred access extracted PDF"))
        got = current["search_sources"]("alpha", 0, 1, "original")
    assert {key: got[key] for key in expected} == expected
    assert got["next_offset"] == 1 and got["total"] == 2
    assert "source_table_views" not in got
    ref = got["source_table_references"][0]
    assert ref["source_id"] == "original" and ref["page"] == 1
    assert ref["source_sha256"] == ws.store.manifest["sources"][0]["sha256"]
    assert ref["status"] == "not_expanded" and ref["extraction_status"] == "not_extracted"
    assert ref["original_bytes_verified"] is False
    inspected = current[ref["inspection"]["tool"]](**ref["inspection"]["arguments"])
    assert inspected["table_view"]["tables"][0]["rows"][2] == ["2", "", "7"]
    assert snapshot(ws) == before
    full = current["search_sources"]("alpha", 0, 1, "original", "full")
    assert full == with_source_tables(ws, expected)


def test_cross_page_refs_deduplicate_only_pages_and_keep_unlocated(ws):
    configure_source_search(ws)
    search = tools(ws)["search_sources"]
    assert [v["page"] for v in search("alpha\n\nbeta")["source_table_references"]] == [1, 2]
    got = search("alpha")
    assert len(got["matches"]) == 2 and len(got["source_table_references"]) == 1
    with ws.store.connect() as db:
        db.execute("UPDATE source_blocks SET locator='paragraph alpha' WHERE ordinal=2")
    got = search("alpha")
    assert len(got["matches"]) == 2 and len(got["table_view_unlocated"]) == 1
    assert got["table_view_unlocated"][0]["locator"] == "paragraph alpha"
    empty = search("not present")
    assert empty["matches"] == [] and empty["source_table_references"] == []
    assert "not evidence" in empty["table_view_note"]


def test_read_and_inspect_unchanged_and_full_still_checks_original(ws):
    current = tools(ws)
    old_read = current["read_source_page"]("original", 0, 2)
    old_inspect = current["inspect_source_page"]("original", 1)
    configure_source_search(ws)
    assert current["read_source_page"]("original", 0, 2) == old_read
    assert current["inspect_source_page"]("original", 1) == old_inspect
    (ws.store.root/"sources/original.pdf").write_bytes(b"changed original")
    ref = current["search_sources"]("alpha")["source_table_references"][0]
    assert ref["original_bytes_verified"] is False
    assert current["search_sources"]("alpha", table_detail="full")["source_table_views"][0]["error"] == "SOURCE_ORIGINAL_SHA256_MISMATCH"
    with pytest.raises(ActionRejected, match="SHA256_MISMATCH"):
        current["inspect_source_page"]("original", 1)
    with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
        current["search_sources"]("alpha", source_id="another-project-source")


@pytest.mark.parametrize("change", ["missing_import", "copied_review", "prior_review", "model_event", "checkpoint", "legacy"])
def test_only_fresh_clean_candidate_can_configure(ws, change):
    if change == "missing_import":
        ws.store.set("clean_import", None)
    elif change == "copied_review":
        ws.store.set("clean_import", {**ws.store.get("clean_import"), "copied_reviews": True})
    elif change == "prior_review":
        ws.store.set("rubric_reviews", [{"result": "satisfied"}])
    elif change == "model_event":
        ws.store.event("deep_model_request", {"role": "rubric_grader"})
    elif change == "checkpoint":
        (ws.store.root/"checkpoints.db").write_bytes(b"")
    else:
        ws.store.set("review_context_experiment", {"input_mode": "artifact", "grounded_verdict": True})
    with pytest.raises(ActionRejected, match="FRESH_CLEAN_CANDIDATE"):
        configure_source_search(ws)
    assert ws.store.get(CONFIG_KEY) is None and ws.store.get(BINDING_KEY) is None


def test_binding_is_idempotent_recovers_and_cannot_switch_or_disappear(ws):
    identity = configure_source_search(ws)
    before = snapshot(ws)
    assert identity == {"version": VERSION, "default_table_detail": "references"}
    assert configure_source_search(ws) == identity
    assert snapshot(ws) == before
    reopened = Workspace(Store(ws.store.root))
    assert bind_source_search(reopened) == identity
    with pytest.raises(ActionRejected, match="BINDING_CHANGED"):
        configure_source_search(ws, default_table_detail="full")
    assert ws.store.get(CONFIG_KEY) == identity
    ws.store.set(CONFIG_KEY, None)
    with pytest.raises(ActionRejected, match="BINDING_CHANGED"):
        bind_source_search(reopened)
    with pytest.raises(ActionRejected, match="BINDING_CHANGED"):
        grader(reopened)  # Direct native construction also guards recovery.


def test_direct_grader_target_binding_and_old_review_projection(ws):
    identity = configure_source_search(ws)
    review = grader(ws)
    payload(ws, review)
    target = ws.store.get("rubric_targets")["synthetic-review:0"]
    assert target["source_search_view"] == identity
    assert review._system_prompt == reviewer_prompt(requirement_acceptance=True)
    assert ws.store.get("review_context_experiment") is None
    record = {"target": target, "result": "satisfied", "unverified": False}
    ws.store.set("rubric_reviews", [record])
    assert review_delivery(ws, target["draft_id"])["status"] == "reviewed_draft"
    old = copy.deepcopy(record)
    del old["target"]["source_search_view"]
    ws.store.set("rubric_reviews", [old])
    assert review_delivery(ws, target["draft_id"])["status"] == "unreviewed_draft"
    ws.store.set(CONFIG_KEY, {"version": VERSION, "default_table_detail": "full"})
    with pytest.raises(ActionRejected, match="BINDING_CHANGED"):
        payload(ws, review)


def test_old_unconfigured_target_identity_stays_unchanged(ws):
    review = grader(ws)
    payload(ws, review)
    target = ws.store.get("rubric_targets")["synthetic-review:0"]
    assert "source_search_view" not in target
    ws.store.set("rubric_reviews", [{"target": target, "result": "satisfied", "unverified": False}])
    assert review_delivery(ws, target["draft_id"])["status"] == "reviewed_draft"


async def test_native_tool_schema_exposes_choice_and_exact_full_access(ws):
    configure_source_search(ws)
    def inspect_ref(messages):
        got = observation(messages, "search_sources")
        assert got["matches"][0]["text"] == "alpha"
        assert got["table_detail"] == "references"
        return invoke("search_sources", query="alpha", limit=1, source_id="original", table_detail="full")
    def finish(messages):
        got = observation(messages, "search_sources")
        assert got["source_table_views"][0]["tables"][0]["rows"][2] == ["2", "", "7"]
        return verdict(ws, ["satisfied"])
    driver = Driver(rubric_grader=[invoke("search_sources", query="alpha", limit=1, source_id="original"), inspect_ref, finish])
    review = grader(ws, driver)
    result = await review._ensure_grader().ainvoke(payload(ws, review))
    assert result["structured_response"].result == "satisfied"
    schema = next(t for t in driver.bindings["rubric_grader"][0] if t["name"] == "search_sources")
    assert "table_detail" in schema["parameters"]["properties"]
    assert "configure_source_search" not in {t["name"] for t in driver.bindings["rubric_grader"][0]}
    assert len(driver.calls) == 3
