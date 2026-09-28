"""Authorized GLM adapter; agent orchestration belongs to DeepAgents."""
from __future__ import annotations

import os
import re

import httpx
import openai
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .errors import ActionForbidden, ActionRejected


def _http_status(exc):
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
    elif isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    else:
        return None
    return status if type(status) is int and 100 <= status <= 599 else None


def _exception_type(exc):
    name = type(exc).__name__
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) else "Exception"


def error_data(exc):
    """Presentation only: inspect trusted types/status, never provider text or URLs."""
    chain, seen, current = [], set(), exc
    while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 5:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__
    status = next((value for item in chain if (value := _http_status(item)) is not None), None)
    safe = None
    # Only the existing domain/builtin business-code path may expose an argument.
    # Provider exception subclasses never qualify, even with uppercase bodies.
    if isinstance(exc, (ActionRejected, ActionForbidden)) or type(exc) in (ValueError, PermissionError, RuntimeError):
        if len(exc.args) == 1 and type(exc.args[0]) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", exc.args[0]):
            safe = exc.args[0]
    if safe is None:
        safe = "EXECUTION_FAILED"
        if status == 401 or any(isinstance(item, openai.AuthenticationError) for item in chain):
            safe = "MODEL_AUTHENTICATION_FAILED"
        elif status == 403 or any(isinstance(item, openai.PermissionDeniedError) for item in chain):
            safe = "MODEL_PERMISSION_DENIED"
        elif status == 429 or any(isinstance(item, openai.RateLimitError) for item in chain):
            safe = "MODEL_RATE_LIMITED"
        elif status in {408, 504} or any(isinstance(item, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)) for item in chain):
            safe = "MODEL_REQUEST_TIMEOUT"
        elif any(isinstance(item, (openai.APIConnectionError, httpx.NetworkError, httpx.RemoteProtocolError,
                                   httpx.ProxyError, ConnectionError)) for item in chain):
            safe = "MODEL_CONNECTION_FAILED"
        elif status is not None and status >= 500:
            safe = "MODEL_SERVICE_UNAVAILABLE"
        elif status is not None and status >= 400:
            safe = "MODEL_REQUEST_REJECTED"
    result = {"type": _exception_type(exc), "http_status": status, "message": safe}
    if len(chain) > 1:
        result["cause_types"] = [_exception_type(item) for item in chain[1:]]
    if current is not None:
        result["cause_chain_truncated"] = True
    return result


class GLMChatOpenAI(ChatOpenAI):
    """Preserve GLM's opaque tool-turn field using the existing SDK and harness."""

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else response.model_dump(warnings=False)
        for generation, choice in zip(result.generations, raw['choices'], strict=True):
            reasoning = choice['message'].get('reasoning_content')
            if reasoning is not None:
                if not isinstance(reasoning, str):
                    raise ValueError('UNSUPPORTED_GLM_REASONING_FIELD')
                generation.message.additional_kwargs['reasoning_content'] = reasoning
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        if payload.get('stream') or 'messages' not in payload:
            raise ValueError('GLM_ADAPTER_REQUIRES_NONSTREAMING_CHAT_COMPLETIONS')
        for message, wire in zip(messages, payload['messages'], strict=True):
            if isinstance(message, AIMessage) and 'reasoning_content' in message.additional_kwargs:
                reasoning = message.additional_kwargs['reasoning_content']
                if not isinstance(reasoning, str):
                    raise ValueError('UNSUPPORTED_GLM_REASONING_FIELD')
                wire['reasoning_content'] = reasoning
        return payload


def _audit_message(message):
    data = message.model_dump(mode='json')
    reasoning = data.get('additional_kwargs', {}).pop('reasoning_content', None)
    if reasoning is not None:
        data['protocol_metadata'] = {'reasoning_present': True, 'reasoning_length': len(reasoning)}
    return data


class LocalAudit(BaseCallbackHandler):
    """Local project audit only; never serialize a client or its credentials."""

    def __init__(self, store, role):
        self.store, self.role = store, role

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.store.event("deep_model_request", {
            "run_id": str(run_id), "role": self.role,
            "messages": [[_audit_message(m) for m in batch] for batch in messages],
        })
        self.store.set("report_activity", self.role)

    def on_llm_end(self, response, *, run_id, **kwargs):
        self.store.event("deep_model_response", {
            "run_id": str(run_id), "role": self.role,
            "generations": [[_audit_message(g.message) for g in batch] for batch in response.generations],
            "usage": (response.llm_output or {}).get("token_usage"),
        })

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.store.event("deep_model_error", {"run_id": str(run_id), "role": self.role, **error_data(error)})


def configured_model(store, role):
    name = os.environ.get("REPORT_MODEL", "").removeprefix("openai/")
    url, key = os.environ.get("REPORT_BASE_URL"), os.environ.get("REPORT_API_KEY")
    if name.lower().replace("-", "").replace(".", "") != "glm53" or not url or not key:
        raise RuntimeError("AUTHORIZED_GLM53_CONFIGURATION_REQUIRED")
    # SDK retries only transport/transient status failures, not a failed business task.
    # Non-streaming responses do not execute partial tool calls. No whole-run deadline.
    return GLMChatOpenAI(model=name, base_url=url, api_key=key, use_responses_api=False,
                      disable_streaming=True,
                      reasoning_effort="high", max_tokens=65536, max_retries=2,
                      extra_body={"thinking": {"type": "enabled", "clear_thinking": False}},
                      timeout=httpx.Timeout(connect=15, read=1800, write=60, pool=60),
                      model_kwargs={"parallel_tool_calls": False},
                      callbacks=[LocalAudit(store, role)])


def configured_vision_client():
    """Use the SDK directly so image payloads do not enter inherited model callbacks."""
    url, key = os.environ.get("REPORT_BASE_URL"), os.environ.get("REPORT_API_KEY")
    if not url or not key:
        raise RuntimeError("VISION_SERVICE_CONFIGURATION_REQUIRED")
    return openai.AsyncOpenAI(base_url=url, api_key=key, max_retries=2,
                             timeout=httpx.Timeout(connect=15, read=1800, write=60, pool=60))
