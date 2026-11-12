"""C2 outgoing-only clearing: real stock edit, recovery and native boundaries."""
from copy import deepcopy
import json

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.context_editing import ToolResultEditing, CLEARED
from test_task_supervision import ws, offline
from test_hierarchical_content import seed
from test_deep_runtime import Driver, invoke


def exchanges(name="read_content_index", count=7):
    result = [HumanMessage("Use the frozen assignment and preserve its qualifiers.")]
    for i in range(count):
        result += [AIMessage("", tool_calls=[dict(name=name, id=str(i),
            args={"snapshot_ref": {"type": "DocumentSnapshot", "id": "fixed", "version": 1}}, type="tool_call")]),
            ToolMessage(json.dumps({"snapshot_ref": {"type": "DocumentSnapshot", "id": "fixed", "version": 1},
                "body": "Frozen complete material. " * 1800}), name=name, tool_call_id=str(i))]
    return result


def offered(name):
    return {"type": "function", "function": {"name": name, "description": "Fixture",
        "parameters": {"type": "object", "properties": {}}}}


async def edited(ws, history, *, name="read_content_index", role="coordinator", tools=None):
    seen = []
    incoming = ModelRequest(model=Driver()(role), messages=history, state={"messages": history},
        tools=[offered(name)] if tools is None else tools)
    async def receive(request):
        seen.append(request)
        return ModelResponse(result=[AIMessage("Done")])
    await ToolResultEditing(ws, role).awrap_model_call(incoming, receive)
    return seen[0]


async def test_only_outgoing_copy_clears_and_exact_args_ids_recent_results_survive(ws):
    history = exchanges()
    original = deepcopy(history)
    outgoing = await edited(ws, history)
    cleared = [m for m in outgoing.messages if m.type == "tool" and m.content == CLEARED]
    assert cleared
    assert history == original and outgoing.state["messages"] == original
    assert [(m.type, getattr(m, "tool_call_id", None)) for m in outgoing.messages] == [
        (m.type, getattr(m, "tool_call_id", None)) for m in history]
    assert [m.tool_calls for m in outgoing.messages if m.type == "ai"] == [
        m.tool_calls for m in history if m.type == "ai"]
    assert [m.content for m in outgoing.messages if m.type == "tool"][-3:] == [
        m.content for m in history if m.type == "tool"][-3:]
    assert all(m.response_metadata["context_editing"]["cleared"] for m in cleared)


@pytest.mark.parametrize("name", ["read_source_page", "inspect_source_page", "read_planning_draft",
    "read_commission_plan", "read_tool_observation", "read_assigned_page", "process_report_content",
    "commit_objects", "record_qualitative_finding"])
async def test_mutable_source_receipt_paid_write_and_bounded_reads_never_clear(ws, name):
    history = exchanges(name)
    outgoing = await edited(ws, history, name=name)
    assert outgoing.messages == history


@pytest.mark.parametrize("variant", ["error", "receipt", "nontext", "malformed", "mismatched-call"])
async def test_one_unsafe_variant_excludes_the_whole_reader_name(ws, variant):
    history = exchanges()
    result = history[2]
    if variant == "error":
        history[2] = result.model_copy(update={"status": "error"})
    elif variant == "receipt":
        history[2] = result.model_copy(update={"content": json.dumps({"receipt_id": "new-observation"})})
    elif variant == "nontext":
        history[2] = result.model_copy(update={"content": [{"type": "image", "base64": "fixture"}]})
    elif variant == "malformed":
        history[2] = result.model_copy(update={"content": "not a proved structured result"})
    else:
        history[1] = history[1].model_copy(update={"tool_calls": [dict(
            name="commit_objects", id="0", args={}, type="tool_call")]})
    assert (await edited(ws, history)).messages == history


async def test_unoffered_reader_native_receipt_variant_and_selector_stay_visible(ws):
    history = exchanges()
    assert (await edited(ws, history, tools=[])).messages == history
    assert (await edited(ws, history, role="reviewer")).messages == history
    ws.store.set("manifest", {**ws.store.manifest, "tool_selection_mode": "on"})
    assert (await edited(ws, history)).messages == history


async def test_frozen_qualitative_rows_clear_in_growing_reviewer_session(ws):
    history = exchanges("read_qualitative_row")
    outgoing = await edited(ws, history, name="read_qualitative_row", role="reviewer")
    assert any(m.type == "tool" and m.content == CLEARED for m in outgoing.messages)


async def test_native_stack_clears_real_immutable_index_and_rereads_it(ws, monkeypatch):
    from report_agent import context_editing
    from report_agent.deep_runtime import run_report
    from report_agent.content_selection import content_index
    from report_agent.content_store import ContentStore
    seed_result = seed(ws)
    snapshot = seed_result[3]
    ws.store.set("context_policy", "stateful-tools-v1")
    monkeypatch.setattr(context_editing, "TRIGGER", 300)
    monkeypatch.setattr(context_editing, "CLEAR_AT_LEAST", 100)
    expected = content_index(ContentStore(ws.store), snapshot)
    captured = []
    def finish(messages):
        captured.extend(messages)
        results = [m for m in messages if m.type == "tool" and m.name == "read_content_index"]
        assert any(m.content == CLEARED for m in results)
        assert json.loads(results[-1].content) == expected
        tails = [m for m in messages if m.type == "human" and m.text.startswith("[host-observations]\n")]
        assert len(tails) == 1
        return AIMessage("Frozen index re-read; not a content review.")
    models = Driver(coordinator=[*[invoke("read_content_index", snapshot_ref=snapshot) for _ in range(7)], finish])
    result = await run_report(ws, models)
    assert result["last_error"] is None, result
    import sqlite3
    with sqlite3.connect(f"file:{ws.store.root / 'checkpoints.db'}?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        blobs = db.execute("SELECT type,value FROM writes WHERE channel='messages'").fetchall()
    assert blobs
    assert not any(CLEARED.encode() in bytes(body) for _, body in blobs)
    last = [m for m in captured if m.type == "tool" and m.name == "read_content_index"][-1]
    assert any(last.content.encode() in bytes(body) for _, body in blobs)
    assert content_index(ContentStore(ws.store), snapshot) == expected


async def test_stock_nearest_ai_limitation_keeps_unmatched_result_visible(ws):
    history = exchanges()
    history.insert(2, AIMessage("A program-authored note between the call and result."))
    outgoing = await edited(ws, history)
    assert outgoing.messages[3].content == history[3].content
    assert any(m.type == "tool" and m.content == CLEARED for m in outgoing.messages)


def test_source_text_can_be_frozen_while_its_public_receipt_changes(ws):
    from report_agent.content_store import ContentStore
    from report_agent.hierarchical_tools import actor_for
    from report_agent.source_materials import issue
    actor = actor_for("coordinator")
    value = json.dumps({"source_id": "s", "page": 1, "native_text": "same frozen words"})
    materials = [{"source_id": "s", "kind": "synthetic frozen page"}]
    first = issue(ws, actor, "inspect_source_page", value, materials)
    ContentStore(ws.store).capture_sources(actor, "synthetic-source-import", ["s"])
    second = issue(ws, actor, "inspect_source_page", value, materials)
    assert not first["source_version_refs"] and len(second["source_version_refs"]) == 1
    assert first["public_sha256"] == second["public_sha256"]
    assert first["receipt"] != second["receipt"]


async def test_real_summary_threshold_still_counts_stored_history(ws, record_property):
    from langchain_core.messages.utils import count_tokens_approximately
    from report_agent.working_summary import working_summary, compute_summarization_defaults
    model = Driver(coordinator=[AIMessage("Unverified concise notes; preserve original references.")])("coordinator")
    settings = compute_summarization_defaults(model)
    assert settings["trigger"] == ("tokens", 170000)
    history = exchanges(count=1)
    while count_tokens_approximately(history) <= 170000:
        number = len(history)
        history += [AIMessage("", tool_calls=[dict(name="read_content_index", id=str(number),
            args={"snapshot_ref": {"type": "DocumentSnapshot", "id": "fixed", "version": 1}}, type="tool_call")]),
            ToolMessage(json.dumps({"body": "frozen value " * 5000}),
                name="read_content_index", tool_call_id=str(number))]
    for i, message in enumerate(history):
        message.id = f"threshold-{i}"
    original = deepcopy(history)
    summary = working_summary(model, ws.store, "coordinator")
    update = await summary.abefore_model({"messages": history}, None)
    outgoing = await edited(ws, history)
    before = count_tokens_approximately(history)
    after = count_tokens_approximately(outgoing.messages)
    assert history == original and update and update.get("messages")
    assert after < 170000 < before
    record_property("v7", json.dumps({"configured_trigger": settings["trigger"],
        "stored_proxy_tokens": before, "outgoing_proxy_tokens_without_summary": after,
        "summary_fired": True, "trigger_changed": False}))
