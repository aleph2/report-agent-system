"""Offline native grader graph and loop tests; no provider or project data."""
import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from pydantic import Field


class ScriptedModel(BaseChatModel):
    replies: list[Any]
    seen: list = Field(default_factory=list, exclude=True)
    bindings: list = Field(default_factory=list, exclude=True)

    @property
    def _llm_type(self):
        return "offline-rubric-test"

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("Expected asynchronous graph")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        if not self.replies:
            raise AssertionError("Unexpected extra model invocation")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")

    def forbid(*args, **kwargs):
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(httpx.Client, "send", forbid)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)


def verdict(passed, count):
    criteria = [{"name": f"Exact required line {n}", "passed": passed,
                 **({} if passed else {"gap": "Add the required exact line"})}
                for n in range(count)]
    return AIMessage("", tool_calls=[{
        "name": "GraderResponse", "id": f"grade-{passed}", "type": "tool_call",
        "args": {"result": "satisfied" if passed else "needs_revision",
                 "explanation": "Synthetic assessment", "criteria": criteria},
    }])
