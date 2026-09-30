"""Authorized model adapters; agent orchestration belongs to DeepAgents."""
from __future__ import annotations

import os
import re
import json
from urllib.parse import urlparse

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
    """Preserve opaque GLM/DeepSeek tool-turn fields with the SDK and harness.

    The historical class name remains compatible with existing trials/checkpoints.
    Provider-specific parameters are selected explicitly by configured_model.
    """

    deepseek_strict: bool = False

    def _decode_strict(self, result, tools):
        if not self.deepseek_strict:
            return result
        from .deepseek_strict import StrictCodec, WireError
        codecs = {t['function']['name']: StrictCodec(t['function']) for t in tools or []}
        for generation in result.generations:
            message = generation.message
            valid = []
            for call in message.tool_calls:
                try:
                    if call['name'] not in codecs:
                        raise WireError('Tool is not in this request')
                    valid.append({**call, 'args': codecs[call['name']].decode(call['args'])})
                except WireError as exc:
                    message.invalid_tool_calls.append({'type': 'invalid_tool_call', 'id': call['id'],
                        'name': call['name'], 'args': json.dumps(call['args'], ensure_ascii=False),
                        'error': 'STRICT_WIRE_DECODE_FAILED: ' + str(exc)})
            message.tool_calls = valid
        return result

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        return self._decode_strict(result, kwargs.get('tools'))

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        return self._decode_strict(result, kwargs.get('tools'))

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else response.model_dump(warnings=False)
        for generation, choice in zip(result.generations, raw['choices'], strict=True):
            if self.deepseek_strict:
                from .deepseek_strict import VERSION
                generation.message.additional_kwargs['strict_wire'] = {
                    'version': VERSION, 'tool_calls': choice['message'].get('tool_calls') or []}
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
        if self.model_name in {'deepseek-v4.1-flash', 'deepseek-flash'} and 'max_completion_tokens' in payload:
            payload['max_tokens'] = payload.pop('max_completion_tokens')
        # Official thinking mode rejects forced tool selection. The harness may
        # bind `any`/`required` for structured responses; keep tools and thinking,
        # with the supported auto selection instead of disabling reasoning.
        if self.model_name == 'deepseek-flash' and (
                isinstance(payload.get('tool_choice'), dict) or payload.get('tool_choice') in {'any', 'required'}):
            payload['tool_choice'] = 'auto'
        if self.deepseek_strict:
            from .deepseek_strict import StrictCodec
            if urlparse(str(self.openai_api_base)).path.rstrip('/') != '/beta':
                raise ValueError('DEEPSEEK_STRICT_REQUIRES_BETA')
            payload['tools'] = [{'type': 'function', 'function': StrictCodec(t['function']).function}
                                for t in payload.get('tools', [])]
            if not payload['tools']:
                payload.pop('tools')
        for message, wire in zip(messages, payload['messages'], strict=True):
            if isinstance(message, AIMessage) and 'strict_wire' in message.additional_kwargs:
                # Replay exactly the model-generated wire calls, never the decoded
                # business arguments. Old pre-strict checkpoint calls stay unchanged.
                wire['tool_calls'] = message.additional_kwargs['strict_wire']['tool_calls']
                if not wire['tool_calls']:
                    wire.pop('tool_calls')
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
    if name == "deepseek-flash":
        if not key or not url or urlparse(url).scheme != "https" or urlparse(url).netloc != "api.deepseek.com":
            raise RuntimeError("OFFICIAL_DEEPSEEK_CONFIGURATION_REQUIRED")
        effort = os.environ.get("REPORT_REASONING_EFFORT", "max")
        if effort not in {"low", "high", "max"}:
            raise RuntimeError("DEEPSEEK_REASONING_EFFORT_INVALID")
        strict = os.environ.get('REPORT_DEEPSEEK_STRICT', '0') == '1'
        if strict:
            url = 'https://api.deepseek.com/beta'
        return GLMChatOpenAI(model=name, base_url=url, api_key=key, use_responses_api=False, deepseek_strict=strict,
            http_async_client=httpx.AsyncClient(event_hooks={'request': [strict_wire_audit(store, role)]}) if strict else None,
            disable_streaming=True, reasoning_effort=effort, max_tokens=131072 if effort == "max" else 65536,
            max_retries=0, extra_body={"thinking": {"type": "enabled"}},
            timeout=httpx.Timeout(connect=15, read=1800, write=60, pool=60),
            model_kwargs={"parallel_tool_calls": False}, callbacks=[LocalAudit(store, role)])
    if name.lower().replace("-", "").replace(".", "") != "glm53" or not url or not key:
        raise RuntimeError("AUTHORIZED_GLM53_CONFIGURATION_REQUIRED")
    if role in {"rubric_grader", "grader_diagnostic"} and "REPORT_GRADER_MODEL" in os.environ:
        name = os.environ["REPORT_GRADER_MODEL"]
        if name not in {"glm-5.3", "deepseek-v4.1-flash"}:
            raise RuntimeError("AUTHORIZED_GRADER_MODEL_REQUIRED")
    thinking = ({"enable_thinking": True} if name == "deepseek-v4.1-flash" else
                {"thinking": {"type": "enabled", "clear_thinking": False}})
    # SDK retries only transport/transient status failures, not a failed business task.
    # Non-streaming responses do not execute partial tool calls. No whole-run deadline.
    return GLMChatOpenAI(model=name, base_url=url, api_key=key, use_responses_api=False,
                      disable_streaming=True,
                      reasoning_effort="high", max_tokens=65536, max_retries=2,
                      extra_body=thinking,
                      timeout=httpx.Timeout(connect=15, read=1800, write=60, pool=60),
                      model_kwargs={"parallel_tool_calls": False},
                      callbacks=[LocalAudit(store, role)])


def strict_wire_audit(store, role):
    """Capture actual HTTP parameters/schema identity, without headers or reasoning."""
    async def observe(request):
        from .store import digest
        payload = json.loads(request.content)
        definitions = payload.get('tools', [])
        identity = digest(definitions)
        key = 'deepseek_wire_schema:' + identity
        if store.get(key) is None:
            store.set(key, definitions)
        params = {k: payload[k] for k in ('model', 'thinking', 'reasoning_effort', 'max_tokens',
            'stream', 'parallel_tool_calls', 'tool_choice', 'response_format', 'temperature', 'top_p') if k in payload}
        store.event('deep_model_wire', {'role': role, 'endpoint': str(request.url.copy_with(query=None)),
            'parameters': params, 'tool_schema_digest': identity, 'tool_count': len(definitions),
            'all_functions_strict': all(t.get('function', {}).get('strict') is True for t in definitions),
            'message_count': len(payload.get('messages', []))})
    return observe


def bind_grader_trial(store):
    """Contain experimental model switching to a fresh isolated review fork.

    Do not relabel an old GLM approval or switch a partially executed review.
    Existing bindings survive recovery and require the same explicit selection.
    This is an execution identity guard, not a content-review stage.
    """
    selected = os.environ.get("REPORT_GRADER_MODEL", os.environ.get("REPORT_MODEL", ""))
    bound = store.get("grader_model_trial")
    if bound:
        if selected != bound["model"]:
            raise RuntimeError("GRADER_MODEL_SWITCH_REQUIRES_FRESH_REVIEW_FORK")
        return
    if selected == "deepseek-flash":
        if store.manifest.get("trial_service") != "deepseek-official":
            raise RuntimeError("DEEPSEEK_REQUIRES_ISOLATED_TRIAL_PROJECT")
        store.set("grader_model_trial", {"model": selected, "scope": "isolated_official_deepseek_trial"})
        return
    if selected == "deepseek-v4.1-flash":
        receipt = store.get("review_import017") or {}
        if (receipt.get("next") != ["FeedbackRubric.after_agent"] or not store.get("checkpoint_resume")
                or store.get("rubric_targets") or store.get("rubric_reviews")):
            raise RuntimeError("GRADER_MODEL_SWITCH_REQUIRES_FRESH_REVIEW_FORK")
        store.set("grader_model_trial", {"model": selected, "scope": "isolated_review_fork",
                                        "import_attempt_id": receipt["attempt_id"]})


def configured_vision_client():
    """Use the SDK directly so image payloads do not enter inherited model callbacks."""
    url, key = os.environ.get("REPORT_BASE_URL"), os.environ.get("REPORT_API_KEY")
    if not url or not key:
        raise RuntimeError("VISION_SERVICE_CONFIGURATION_REQUIRED")
    return openai.AsyncOpenAI(base_url=url, api_key=key,
                             max_retries=0 if urlparse(url).netloc == "api.deepseek.com" else 2,
                             timeout=httpx.Timeout(connect=15, read=1800, write=60, pool=60))
