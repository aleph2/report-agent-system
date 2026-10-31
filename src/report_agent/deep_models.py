"""Authorized model adapters; agent orchestration belongs to DeepAgents."""
from __future__ import annotations

import os
import asyncio
import re
import json
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlparse

import httpx
import openai
from .request_budget import account_request, RequestBudgetExceeded, HOST_ADMISSION_REASONS
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .errors import ActionForbidden, ActionRejected, ModelRequestDeadlineExceeded
from .transport_observation import observation_scope, observe_model_boundary


from .model_invocation import model_invocation, model_request_timeout, MODEL_REQUEST_DEADLINE_SECONDS


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
    from .prompt_provenance import PromptCompositionError
    if isinstance(exc, PromptCompositionError):
        return {'type':'PromptCompositionError', 'http_status':None,
                'message':str(exc), 'automatic_retry':False}
    from .model_recovery import recovery_block
    blocked = recovery_block(exc)
    if blocked is not None:
        code = blocked.args[0] if len(blocked.args) == 1 else ''
        return {'type': 'RecoveryBlocked', 'http_status': None,
                'message': code if isinstance(code, str) and re.fullmatch(r'RECOVERY_[A-Z_]+', code)
                else 'RECOVERY_POLICY_BLOCKED'}
    chain, seen, current = [], set(), exc
    while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 5:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__
    status = next((value for item in chain if (value := _http_status(item)) is not None), None)
    from .input_capacity import capacity_failure
    capacity = capacity_failure(exc)
    if capacity is not None:
        return {"type": _exception_type(exc), "http_status": capacity['http_status'],
                "message": "MODEL_CONTEXT_CAPACITY_REJECTED", "capacity": capacity}
    if any(isinstance(item, RequestBudgetExceeded) for item in chain):
        budget_error=next(item for item in chain if isinstance(item,RequestBudgetExceeded))
        code=str(budget_error)
        if code not in {'MODEL_REQUEST_BUDGET_REACHED','AUTHORIZED_TOKEN_BUDGET_REACHED',
                        'MODEL_TOKEN_BOUND_NOT_VERIFIED','TOKEN_BOUND_VIOLATION_REQUIRES_DIAGNOSIS',
                        'STREAM_USAGE_BUDGET_NOT_SUPPORTED','TOKEN_LEDGER_SETTLEMENT_FAILED'} | HOST_ADMISSION_REASONS:
            code='MODEL_REQUEST_BUDGET_REACHED'
        return {"type": "RequestBudgetExceeded", "http_status": None,
                "message": code}
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
    facts = getattr(exc, 'model_call_facts', None)
    if facts is not None:
        result['model_call'] = facts
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
        client = self.http_async_client
        store, role = getattr(client, 'observation_store', None), getattr(client, 'observation_role', None)
        async def invoke():
            async with model_invocation(store, role):
                result = await super(GLMChatOpenAI, self)._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs)
                return self._decode_strict(result, kwargs.get('tools'))
        from .model_recovery import load_recovery_policy, recover_model_call
        if not load_recovery_policy(store):
            return await invoke()
        if self.root_async_client.max_retries != 0 or connection_retry_count() != 0:
            from .model_recovery import RecoveryBlocked
            raise RecoveryBlocked('RECOVERY_REQUIRES_SINGLE_RETRY_OWNER')
        payload = self._get_request_payload(messages, stop=stop, **kwargs)
        # Ordinary function schemas only describe possible local tool calls;
        # server-executed/builtin tools are not pure inference recovery.
        safe = all(t.get('type') == 'function' for t in payload.get('tools', []))
        return await recover_model_call(store=store, role=role,
            profile={'model': self.model_name, 'endpoint': str(self.openai_api_base),
                     'strict': self.deepseek_strict}, payload=payload, invoke=invoke, safe=safe,
            parse_raw=lambda raw: self._decode_strict(self._create_chat_result(raw), kwargs.get('tools')),
            on_reuse=self._reused_result)

    @staticmethod
    def _reused_result(result, provenance):
        # Callbacks must not report the cached usage as a second provider call.
        output = result.llm_output or {}
        result.llm_output = {**output, 'token_usage': {},
                             'model_recovery_reused': True,
                             'historical_token_usage': output.get('token_usage'),
                             'model_recovery_provenance': provenance}
        for generation in result.generations:
            message = generation.message
            message.additional_kwargs['model_recovery_reused'] = True
            message.additional_kwargs['historical_usage_metadata'] = message.usage_metadata
            message.additional_kwargs['model_recovery_provenance'] = provenance
            message.response_metadata.pop('token_usage', None)
            message.usage_metadata = None
        return result

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        client = self.http_client
        from .model_recovery import load_recovery_policy, RecoveryBlocked
        if load_recovery_policy(getattr(client, 'observation_store', None)):
            raise RecoveryBlocked('RECOVERY_ASYNC_ENTRYPOINT_REQUIRED')
        with observation_scope(getattr(client, 'observation_store', None),
                               getattr(client, 'observation_role', None)):
            result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            return self._decode_strict(result, kwargs.get('tools'))

    def _create_chat_result(self, response, generation_info=None):
        observe_model_boundary('result_parse_started')
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
        observe_model_boundary('result_parse_completed')
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        observe_model_boundary('payload_started')
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
        observe_model_boundary('payload_completed')
        from .live_messages import validate_wire
        validate_wire(payload, strict=self.deepseek_strict)
        from .prompt_provenance import bind_wire_payload
        bind_wire_payload(payload)
        return payload


def _audit_message(message):
    data = message.model_dump(mode='json')
    reasoning = data.get('additional_kwargs', {}).pop('reasoning_content', None)
    if reasoning is not None:
        data['protocol_metadata'] = {'reasoning_present': True, 'reasoning_length': len(reasoning)}
    return data


class LocalAudit(BaseCallbackHandler):
    """Historical explicit diagnostic callback; not installed by configured_model.

    Retained for old diagnostic scripts that need effective middleware inputs.
    Normal agent trajectories use the native checkpointer, without this copy.
    """

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


class RuntimeStatus(BaseCallbackHandler):
    """Current activity and sanitized failure metadata, not a model transcript."""

    def __init__(self, store, role, *, model_service_role=None):
        self.store, self.role = store, role
        self.model_service_role = model_service_role

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.store.set("report_activity", self.role)

    def on_llm_error(self, error, *, run_id, **kwargs):
        service = {"model_service_role": self.model_service_role} if self.model_service_role else {}
        self.store.event("deep_model_error", {"run_id": str(run_id), "role": self.role, **service, **error_data(error)})


def connection_retry_count():
    """Opt-in retries only before an HTTP model request can be sent."""
    value = os.environ.get("REPORT_CONNECT_RETRIES", "0")
    if value not in {"0", "1", "2"}:
        raise RuntimeError("MODEL_CONNECT_RETRIES_INVALID")
    return int(value)


def sdk_retry_count():
    """Opt-in provider-request recovery, independent of business/task replay."""
    value = os.environ.get("REPORT_SDK_RETRIES", "0")
    if value not in {"0", "1", "2", "3", "4", "5"}:
        raise RuntimeError("MODEL_SDK_RETRIES_INVALID")
    if value != "0" and connection_retry_count():
        raise RuntimeError("MODEL_RETRY_LAYERS_MUST_NOT_STACK")
    return int(value)


def model_async_client(store=None, role=None, extra_hooks=(), *, capacity_profile=None):
    from .transport_observation import install_http_observer, observe_http_headers, observe_event, ObservedAsyncClient
    retries = connection_retry_count()
    sdk_retries = sdk_retry_count()
    async def observe_start(request):
        install_http_observer(request, store, role, asynchronous=True)
    async def observe_headers(response):
        observe_http_headers(response)
    from .input_capacity import capacity_request_hook
    check_capacity = capacity_request_hook(capacity_profile, store)
    async def admit_capacity(request):
        from .model_recovery import admit_recovery_request
        admit_recovery_request(request, store)
        check_capacity(request)
    from .prompt_provenance import admit_prompt_request, observe_prompt_request
    async def admit_prompt(request):
        admit_prompt_request(request)
    async def observe_prompt(request):
        observe_prompt_request(request, store, role)
    # Configured adapter hooks precede the guard and financial reservation.
    hooks = [admit_capacity, *extra_hooks, admit_prompt, account_request, observe_start, observe_prompt]
    from .token_budget import account_response
    responses = [observe_headers, account_response]
    if sdk_retries:
        async def observe_attempt(request):
            if store is not None:
                import hashlib
                observe_event(store, "model_http_attempt_started", {"role": role,
                    "retry_index": int(request.headers.get("x-stainless-retry-count", "0")),
                    "sdk_retries": sdk_retries,
                    "body_sha256": hashlib.sha256(request.content).hexdigest()})
        async def observe_response(response):
            # Do not let a provider's retry override repeat permanent 4xx errors.
            if 400 <= response.status_code < 500 and response.status_code not in {408,409,429}:
                response.headers['x-should-retry'] = 'false'
            if store is not None:
                observe_event(store, "model_http_attempt_response", {"role": role,
                    "retry_index": int(response.request.headers.get("x-stainless-retry-count", "0")),
                    "http_status": response.status_code})
        hooks.append(observe_attempt); responses.append(observe_response)
        if store is not None:
            observe_event(store, "model_transport_retry_policy", {"role": role, "connect_retries": 0,
                "sdk_retries": sdk_retries, "read_write_status_retries": True})
    if retries and store is not None:
        async def observe_connections(request):
            from .transport_observation import prior_native_trace, remember_connection_trace
            previous = prior_native_trace(request, reset=True)
            async def trace(event, info):
                if previous is not None:
                    await previous(event, info)
                if event in {"connection.connect_tcp.failed", "connection.connect_unix_socket.failed",
                             "connection.start_tls.failed", "connection.retry.started"}:
                    observe_event(store, "model_connection_retry_trace", {
                        "role": role, "event": event, "connect_retries": retries})
            remember_connection_trace(request, trace, previous)
        hooks.insert(2, observe_connections)
        observe_event(store, "model_transport_retry_policy", {"role": role, "connect_retries": retries,
            "sdk_retries": 0, "read_write_status_retries": False})
    options = {"event_hooks": {"request": hooks, "response": responses}}
    if retries:
        # HTTPX's native transport retries ConnectError/ConnectTimeout only.
        # It does not repeat HTTP requests after a read/write/status failure.
        options["transport"] = httpx.AsyncHTTPTransport(retries=retries)
    return ObservedAsyncClient(observation_store=store, observation_role=role, **options)


def model_sync_client(store=None, role=None, *, capacity_profile=None):
    from .request_budget import account_request_sync
    from .token_budget import account_response_sync
    from .transport_observation import install_http_observer, observe_http_headers, ObservedClient
    retries = connection_retry_count()
    sdk_retries = sdk_retry_count()
    def observe_start(request):
        install_http_observer(request, store, role)
    def permanent_error(response):
        if 400 <= response.status_code < 500 and response.status_code not in {408,409,429}:
            response.headers['x-should-retry'] = 'false'
    from .input_capacity import capacity_request_hook
    from .prompt_provenance import admit_prompt_request, observe_prompt_request
    return ObservedClient(observation_store=store, observation_role=role,
        transport=httpx.HTTPTransport(retries=retries),
        event_hooks={'request':[capacity_request_hook(capacity_profile, store), admit_prompt_request,
                               account_request_sync, observe_start,
                               lambda request: observe_prompt_request(request,store,role)],
                    'response':[observe_http_headers, account_response_sync, *([permanent_error] if sdk_retries else [])]})


_CLIENT_OWNER = ContextVar('report_model_client_owner', default=None)


@contextmanager
def model_client_ownership(owner):
    token = _CLIENT_OWNER.set(owner)
    try:
        yield
    finally:
        _CLIENT_OWNER.reset(token)


def configured_model(store, role):
    from .model_config import role_service, role_generation
    name, url, key = role_service(role)
    name = name.removeprefix("openai/")
    from .input_capacity import profile_for_service
    client_owner = _CLIENT_OWNER.get()
    def clients(response_hooks=()):
        profile = profile_for_service(name, url)
        asynchronous = model_async_client(store, role, list(response_hooks), capacity_profile=profile)
        if client_owner is not None:
            client_owner(asynchronous, True)
        synchronous = model_sync_client(store, role, capacity_profile=profile)
        if client_owner is not None:
            client_owner(synchronous, False)
        return {'http_async_client': asynchronous, 'http_client': synchronous}
    if name.startswith("deepseek-") and urlparse(url).hostname == "api.deepseek.com":
        role_generation(store, role, name, url)
        if not key or not url or urlparse(url).scheme != "https":
            raise RuntimeError("OFFICIAL_DEEPSEEK_CONFIGURATION_REQUIRED")
        effort = os.environ.get("REPORT_REASONING_EFFORT", "high")
        if effort not in {"low", "high", "max"}:
            raise RuntimeError("DEEPSEEK_REASONING_EFFORT_INVALID")
        strict = os.environ.get('REPORT_DEEPSEEK_STRICT', '0') == '1'
        if strict:
            url = 'https://api.deepseek.com/beta'
        return GLMChatOpenAI(model=name, base_url=url, api_key=key, use_responses_api=False, deepseek_strict=strict,
            **clients([strict_wire_audit(store, role)] if strict else []),
            disable_streaming=True, reasoning_effort=effort, max_tokens=131072 if effort == "max" else 65536,
            max_retries=sdk_retry_count(), extra_body={"thinking": {"type": "enabled"}},
            timeout=model_request_timeout(),
            model_kwargs={"parallel_tool_calls": False}, callbacks=[RuntimeStatus(store, role)])
    is_deepseek = name.startswith("deepseek-")
    if (not is_deepseek and name.lower().replace("-", "").replace(".", "") != "glm53") or not url or not key:
        raise RuntimeError("AUTHORIZED_GLM53_CONFIGURATION_REQUIRED")
    if role in {"rubric_grader", "grader_diagnostic"} and "REPORT_GRADER_MODEL" in os.environ:
        name = os.environ["REPORT_GRADER_MODEL"]
        if name not in {"glm-5.3", "deepseek-v4.1-flash"}:
            raise RuntimeError("AUTHORIZED_GRADER_MODEL_REQUIRED")
    is_deepseek = name.startswith("deepseek-")
    generation = role_generation(store, role, name, url)
    # Apply retries at construction: changing the Pydantic field afterward does
    # not update the SDK clients already initialized by ChatOpenAI.
    return GLMChatOpenAI(model=name, base_url=url, api_key=key, use_responses_api=False,
                      **({"profile": {"image_inputs": False, "image_tool_message": False}} if not is_deepseek else {}),
                      **clients(),
                      **generation, max_retries=sdk_retry_count(),
                      timeout=model_request_timeout(),
                      model_kwargs={"parallel_tool_calls": False},
                      callbacks=[RuntimeStatus(store, role)])


def strict_wire_audit(store, role):
    """Capture actual HTTP parameters/schema identity, without headers or reasoning."""
    from .transport_observation import observe_safely
    def record(request):
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
    async def observe(request):
        observe_safely(lambda: record(request))
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
    from .model_config import role_service
    model, url, key = role_service("vision")
    from .input_capacity import profile_for_service
    if not url or not key:
        raise RuntimeError("VISION_SERVICE_CONFIGURATION_REQUIRED")
    return openai.AsyncOpenAI(base_url=url, api_key=key,
                             http_client=model_async_client(role="vision", capacity_profile=profile_for_service(model.removeprefix("openai/"), url)),
                             max_retries=sdk_retry_count(),
                             timeout=model_request_timeout())
