"""Portable public responses from one synthetic paid probe; entirely fake LLM replay.

These cases verify local message delivery/cache/tool flow, not provider capacity,
financial accounting, autonomous model decisions or engineering report acceptance.
"""
import hashlib
import json
from pathlib import Path
import socket

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from report_agent.content_store import Actor
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Public-response replay must not use HTTP or sockets")
    for cls in (httpx.Client, httpx.AsyncClient):
        monkeypatch.setattr(cls, "send", forbidden)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


def fixture():
    return json.loads((Path(__file__).parent / "fake_data" /
                       "synthetic_real_public_replay.json").read_text(encoding="utf-8"))


async def test_actual_public_ds_response_replays_full_packet_and_native_raw_cache(tmp_path):
    recorded = fixture()["ds"]
    packet = recorded["packet"]
    assert hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest() == recorded["packet_sha256"]
    assert len(packet["evidence"]) == 8 and len(json.dumps(packet)) > 64000
    driver = Driver(text_tool=[AIMessage(content=recorded["public_response"])])
    model = driver("text_tool")
    model.model_name = recorded["model"]
    store = Store(tmp_path / "synthetic-case")
    store.initialize({"goal": "Synthetic public response replay", "sources": [
        {"id": "synthetic", "content": "Synthetic data only", "coverage": "complete"}]})
    ws = Workspace(store)
    actor = Actor("synthetic-reviewer", "reviewer", "synthetic-task")

    first = await analyze_evidence_packet(
        ws, model, packet, recorded["system_prompt"], recorded["contract"],
        reserve_attempt=True, owner=actor, caller_operation_id="public-replay-ds")
    assert not first["reused"] and len(driver.calls) == 1
    messages = driver.calls[0][2]
    assert len(messages) == 2 and messages[0].content == recorded["system_prompt"]
    assert json.loads(messages[1].content) == packet
    assert len(messages[1].content) > 64000
    assert json.loads(first["analysis"]) == {"item_count": 8, "last_sentinel": "END-7"}

    second = await analyze_evidence_packet(
        ws, model, packet, recorded["system_prompt"], recorded["contract"],
        reserve_attempt=True, owner=actor, caller_operation_id="public-replay-ds")
    assert second["reused"] and len(driver.calls) == 1
    assert second["operation"] == first["operation"]
    assert second["analysis"] == first["analysis"]


async def test_actual_public_glm_responses_drive_real_local_tool_and_exact_answer():
    recorded = fixture()["glm"]
    public = recorded["public_messages"]
    ai = [AIMessage(content=row["content"], tool_calls=row["tool_calls"])
          for row in public if row["type"] == "ai"]
    expected_tools = [row for row in public if row["type"] == "tool"]
    assert len(ai) == 2 and len(expected_tools) == 1
    assert ai[0].tool_calls[0]["id"] == expected_tools[0]["tool_call_id"]
    driver = Driver(writer=ai)
    model = driver("writer")
    model.model_name = recorded["model"]
    invoked = []

    @tool
    def add_numbers(a: int, b: int) -> int:
        """Add two supplied integers and return their sum."""
        invoked.append([a, b])
        return a + b

    graph = create_agent(model, tools=[add_numbers])
    output = await graph.ainvoke(
        {"messages": [HumanMessage(content=recorded["human_prompt"])]},
        {"recursion_limit": 6})
    assert len(driver.calls) == 2 and invoked == [[19, 23]]
    actual, = [m for m in output["messages"] if isinstance(m, ToolMessage)]
    expected = expected_tools[0]
    assert actual.tool_call_id == expected["tool_call_id"]
    assert actual.name == expected["name"] == "add_numbers"
    assert actual.content == expected["content"] == "42"
    assert json.loads(output["messages"][-1].content) == {"sum": 42}
    second_input = driver.calls[1][2]
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == actual.tool_call_id
               and m.content == "42" for m in second_input)
