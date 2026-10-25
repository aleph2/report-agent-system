"""Native compaction mechanics only, not live GLM continuity or summary quality."""

from copy import deepcopy

import httpx
import pytest
from deepagents.backends import FilesystemBackend
from deepagents.middleware.summarization import (
    SUMMARIZATION_EVENT_KEY,
    SummarizationMiddleware,
)
from langchain.agents.middleware.types import (
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import Field

from report_agent.deep_models import GLMChatOpenAI


class OfflineSummary(BaseChatModel):
    prompts: list = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):
        return "offline-summary-test"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("Expected native asynchronous summarization")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(deepcopy(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage("Synthetic summary"))])


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP is forbidden in native summary tests")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


@pytest.mark.parametrize("keep", [3, 1], ids=["pair-boundary", "inside-tool-results"])
async def test_native_summary_and_restored_event_preserve_retained_protocol(tmp_path, keep):
    opaque = "synthetic-opaque\n  exact whitespace\t\n"
    evicted_opaque = "synthetic-evicted-field"
    prefix = [
        HumanMessage("old request", id="old-user"),
        AIMessage("old answer", id="old-ai",
                  additional_kwargs={"reasoning_content": evicted_opaque}),
        HumanMessage("older question", id="older-user"),
        AIMessage("legacy answer without field", id="legacy-ai"),
        HumanMessage("current question", id="current-user"),
    ]
    retained = [
        AIMessage("", id="retained-ai", additional_kwargs={"reasoning_content": opaque},
                  tool_calls=[{"name": "calculate", "args": {"value": n},
                               "id": f"call-{n}", "type": "tool_call"} for n in (1, 2)]),
        ToolMessage("one", id="tool-1", tool_call_id="call-1"),
        ToolMessage("two", id="tool-2", tool_call_id="call-2"),
    ]
    state = {"messages": [*prefix, *retained]}
    before = deepcopy(state)
    summary_model = OfflineSummary()
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    middleware = SummarizationMiddleware(
        model=summary_model, backend=backend, trigger=("messages", 7),
        keep=("messages", keep), trim_tokens_to_summarize=None,
    )
    adapter = GLMChatOpenAI(
        model="glm-5.3", api_key="synthetic", base_url="https://model.invalid/v1",
        use_responses_api=False, disable_streaming=True,
    )
    captured = []

    async def handler(request):
        captured.append((request.messages, adapter._get_request_payload(request.messages)["messages"]))
        return ModelResponse(result=[AIMessage("Synthetic continuation")])

    result = await middleware.awrap_model_call(
        ModelRequest(model=adapter, messages=state["messages"], state=state), handler,
    )
    assert isinstance(result, ExtendedModelResponse)
    assert result.command is not None
    event = result.command.update[SUMMARIZATION_EVENT_KEY]
    # keep=1 initially points inside two tool results; native pairing retains their AI.
    assert event["cutoff_index"] == len(prefix)
    assert len(summary_model.prompts) == 1
    assert "old request" in summary_model.prompts[0][0].content
    assert event["file_path"] is not None
    assert (tmp_path / event["file_path"].lstrip("/")).is_file()
    effective, wire = captured[0]
    assert effective[0] == event["summary_message"]
    assert effective[0].additional_kwargs == {"lc_source": "summarization"}
    assert [m.id for m in effective[1:]] == [m.id for m in retained]
    assert wire[1]["reasoning_content"] == opaque
    assert [t["id"] for t in wire[1]["tool_calls"]] == [w["tool_call_id"] for w in wire[2:]]
    assert "reasoning_content" not in wire[0]
    assert all(m.id not in {p.id for p in prefix} for m in effective)
    assert evicted_opaque not in str(wire)
    assert state == before

    # Persist the actual native event and raw messages, not a hand-built summary.
    serializer = JsonPlusSerializer()
    resumed = serializer.loads_typed(serializer.dumps_typed({**state, **result.command.update}))
    assert resumed["messages"] == before["messages"]
    resumed["messages"].extend([
        AIMessage("", id="legacy-next", tool_calls=[
            {"name": "calculate", "args": {}, "id": "next-call", "type": "tool_call"}]),
        ToolMessage("next observation", id="next-tool", tool_call_id="next-call"),
    ])
    resumed_before = deepcopy(resumed)
    fresh_model = OfflineSummary()
    fresh_middleware = SummarizationMiddleware(
        model=fresh_model, backend=backend, trigger=("messages", 7),
        keep=("messages", keep), trim_tokens_to_summarize=None,
    )
    await fresh_middleware.awrap_model_call(
        ModelRequest(model=adapter, messages=resumed["messages"], state=resumed), handler,
    )
    assert fresh_model.prompts == []  # Six effective messages: reuse the saved event.
    effective_again, wire_again = captured[1]
    assert [m.id for m in effective_again[1:]] == [m.id for m in resumed["messages"][len(prefix):]]
    assert wire_again[:4] == wire
    assert wire_again[1]["reasoning_content"] == opaque
    assert "reasoning_content" not in wire_again[-2]  # Legacy missing fields stay missing.
    assert wire_again[-1]["tool_call_id"] == wire_again[-2]["tool_calls"][0]["id"]
    assert resumed == resumed_before
    assert state == before
