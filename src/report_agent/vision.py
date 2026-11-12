"""Optional image observation/OCR; no delegation, source edits or business decisions."""

from .prompt_sources import load_prompt
import base64
import asyncio
import hashlib
import logging
import os
from contextvars import ContextVar

from .deep_models import configured_vision_client, error_data
from .model_invocation import model_invocation
from .input_capacity import CapacityAdmissionRejected, capacity_failure, capacity_handling, capacity_response_received
from .errors import ActionRejected
from .store import digest
from .request_budget import RequestBudgetExceeded
from .prompt_provenance import PromptCompositionError


VISION_INSTRUCTION = load_prompt('source-vision')

VISION_MODEL = "deepseek-v4.1-flash-1017"
MAX_OUTPUT_TOKENS = 8192
MAX_IMAGE_EDGE = 1024

_PRIVATE_REQUEST = ContextVar("vision_private_request", default=False)


class _PrivateRequestLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REQUEST.get()


# OpenAI SDK debug options include the full JSON image payload. Suppress only
# this coroutine's SDK request logs; other agent calls keep their logging policy.
logging.getLogger("openai._base_client").addFilter(_PrivateRequestLogFilter())


def _public_response(response):
    """Allowlisted observations only; provider extras never enter agent state."""
    result = {}
    for key in ('id', 'model'):
        value = getattr(response, key, None)
        if isinstance(value, str):
            result['response_id' if key == 'id' else 'model_returned'] = value
    choices = getattr(response, 'choices', None)
    result['response_shape'] = {'choices_is_list': isinstance(choices, list),
                                'choice_count': len(choices) if isinstance(choices, list) else None}
    if isinstance(choices, list) and choices:
        choice = choices[0]
        finish = getattr(choice, 'finish_reason', None)
        if isinstance(finish, str):
            result['finish_reason'] = finish
        content = getattr(getattr(choice, 'message', None), 'content', None)
        if isinstance(content, str):
            result['observation'] = content
    usage = getattr(response, 'usage', None)
    counts = {}
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        value = getattr(usage, key, None)
        if isinstance(value, int) and not isinstance(value, bool):
            counts[key] = value
    for key, fields in (
        ('prompt_tokens_details', ('cached_tokens', 'audio_tokens')),
        ('completion_tokens_details', ('reasoning_tokens', 'audio_tokens',
                                       'accepted_prediction_tokens', 'rejected_prediction_tokens'))):
        detail = getattr(usage, key, None)
        values = {field: getattr(detail, field, None) for field in fields}
        values = {field: value for field, value in values.items()
                  if isinstance(value, int) and not isinstance(value, bool)}
        if values:
            counts[key] = values
    result['usage'] = counts or None
    return result


async def observe_source_image(workspace, source_id: str, question: str,
                               page: int = 1, crop: list[float] | None = None, *, client=None, actor=None):
    from .document_tools import vision_source_image

    if not isinstance(question, str) or not question.strip():
        raise ActionRejected("VISION_QUESTION_REQUIRED")
    # Source resolution happens before a request. No arbitrary local path or remote URL.
    from .source_use import validate_source_versions
    policy_ref = validate_source_versions(workspace, actor, [source_id])
    png, provenance = vision_source_image(workspace, source_id, page, crop, max_edge=MAX_IMAGE_EDGE)
    owns_client = client is None
    try:
        client = client or configured_vision_client()
    except Exception as exc:
        result = {"status": "failed", "source": provenance, "error": error_data(exc),
                  "reused": False, "limitation": "Visual service configuration failed; source information is not missing."}
        workspace.store.event("vision_error", result)
        return result
    try:
        return await _observe(workspace.store, png, provenance, question, client, actor, policy_ref=policy_ref)
    finally:
        if owns_client:
            await client.close()


async def _observe(store, png, provenance, question, client, actor=None, *, policy_ref=None):
    from .transport_observation import observation_scope
    from .bounded_operations import record_outcome
    from .request_budget import logical_request_admission
    from .vision_admission import reserve_vision
    # Explicit provider configuration takes priority over historical test defaults.
    model = os.environ.get("REPORT_VISION_MODEL") or VISION_MODEL
    thinking = os.environ.get('REPORT_VISION_THINKING', 'enabled')
    if thinking not in {'enabled', 'disabled'}:
        raise ActionRejected('VISION_THINKING_MODE_INVALID')
    from urllib.parse import urlparse
    options = ({'thinking': {'type': thinking}} if urlparse(str(client.base_url)).hostname == 'api.deepseek.com'
               else {'enable_thinking': thinking == 'enabled'})
    settings = {"thinking": thinking, "model": model, "endpoint_hash": digest(str(client.base_url)),
                "max_completion_tokens": MAX_OUTPUT_TOKENS, "instruction": VISION_INSTRUCTION,
                "contract": "source-vision-v2"}
    if policy_ref:
        settings['source_use_policy_ref'] = policy_ref
    operation = digest({**settings, "source": provenance, "question": question,
                        "image_sha256": hashlib.sha256(png).hexdigest()})
    saved = store.analysis(operation)
    if saved:
        store.event("vision_reused", {"operation": operation, "source_id": provenance["source_id"]})
        return {**saved, "reused": True}
    material_identity = digest({'source':provenance, 'image_sha256':hashlib.sha256(png).hexdigest()})
    attempt_key, prior = reserve_vision(store, operation, material_identity, actor)
    if prior:
        # A received invalid response is evidence, not a successful observation
        # or a reason to pay for the identical request again.
        return {**prior['result'], 'reused':True}
    request = {**({'source_use_policy_ref': policy_ref} if policy_ref else {}),
               "operation": operation, "model_requested": model,
               "source": provenance, "question": question,
               "image_sha256": hashlib.sha256(png).hexdigest(),
               "sdk_max_retries": client.max_retries,
               "actor": actor.__dict__ if actor is not None else None}
    # Keep image payloads/credentials out of events and agent checkpoints.
    store.event("vision_request", request)
    response = None
    try:
        token = _PRIVATE_REQUEST.set(True)
        try:
            # Bound the entire logical call, including the sole SDK retry loop.
            with logical_request_admission() as admission:
                payload = dict(model=model, max_completion_tokens=MAX_OUTPUT_TOKENS, stream=False, extra_body=options,
                        messages=[{"role": "system", "content": VISION_INSTRUCTION},
                        {"role": "user", "content": [{"type": "text", "text": question},
                            {"type": "image_url", "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
                                "detail": "high"}}]}])
                role = actor.role if actor is not None else 'vision'
                async def invoke():
                    from .prompt_provenance import check_static_prompt, prompt_call, bind_wire_payload
                    check_static_prompt(VISION_INSTRUCTION, 'source-vision')
                    with prompt_call(store, 'source_vision', sources=['source-vision'], status='exact', offered=payload):
                        bind_wire_payload(payload)
                        async with model_invocation(store, role):
                            return await client.chat.completions.create(**payload)
                from .model_recovery import recover_model_call
                from .model_recovery import load_recovery_policy, RecoveryBlocked
                from .deep_models import connection_retry_count
                if load_recovery_policy(store) and (client.max_retries != 0 or connection_retry_count() != 0):
                    raise RecoveryBlocked('RECOVERY_REQUIRES_SINGLE_RETRY_OWNER')
                from openai.types.chat import ChatCompletion
                response = await recover_model_call(store=store, role=role,
                    profile={'model': model, 'endpoint': str(client.base_url)}, payload=payload,
                    owner={'actor': actor.__dict__, 'operation': operation} if actor is not None else None,
                    invoke=invoke, parse_raw=ChatCompletion.model_validate)
        finally:
            _PRIVATE_REQUEST.reset(token)
        choice = response.choices[0]
        message, finish = choice.message, choice.finish_reason
        content = message.content
        refusal = bool(message.refusal)
        unexpected_tools = bool(message.tool_calls)
        model_returned = response.model
        mismatch = bool(model_returned and model_returned != model)
        usage = _public_response(response)['usage']
    except (RequestBudgetExceeded, CapacityAdmissionRejected, PromptCompositionError) as exc:
        proof = admission.not_dispatched_proof(exc)
        if proof is not None:
            from .bounded_operations import record_not_dispatched
            result = {'status': 'failed', **request, 'error': error_data(exc),
                      'provider_outcome': 'not_dispatched', 'raw_response_received': False,
                      'admission_proof': proof,
                      'reused': False, 'limitation': 'Local admission refused before dispatch; no visual response or source-absence conclusion.'}
            capacity = capacity_failure(exc)
            if capacity is not None:
                result.update(capacity=capacity, handling=capacity_handling(capacity, 'tool'),
                              failure_phase=capacity['failure_phase'], adoptable_result=False)
            record_not_dispatched(store, [(attempt_key, {'operation': operation})], proof, result=result)
        if isinstance(exc, (CapacityAdmissionRejected, PromptCompositionError)):
            if proof is None:
                if isinstance(exc, PromptCompositionError):
                    raise  # No zero-admission proof; preserve the unresolved intent.
                result = {'status': 'failed', **request, 'error': error_data(exc),
                          'provider_outcome': 'unknown', 'raw_response_received': False,
                          'usage': None, 'adoptable_result': False, 'reused': False}
                capacity = capacity_failure(exc)
                result.update(capacity=capacity, handling=capacity_handling(capacity, 'tool'),
                              failure_phase=capacity['failure_phase'])
                record_outcome(store, attempt_key, 'unknown', result=result)
            store.event('vision_error', result)
            return result
        raise
    except Exception as exc:
        from openai import APIStatusError
        received = response is not None or isinstance(exc, APIStatusError) or capacity_response_received(exc)
        result = {"status": "failed", **request, "error": error_data(exc),
                  "reused": False, "provider_outcome":"response_received" if received else "unknown",
                  "raw_response_received":received,
                  "limitation": "Visual request failed; this is not evidence that source information is absent."}
        if response is not None:
            result.update(_public_response(response))
        capacity = capacity_failure(exc)
        if capacity is not None:
            result.update(capacity=capacity, handling=capacity_handling(capacity, 'tool'),
                          failure_phase=capacity['failure_phase'], adoptable_result=False)
        record_outcome(store, attempt_key, 'received_invalid' if received else 'unknown', result=result)
        store.event("vision_error", result)
        return result
    complete = (finish == "stop" and isinstance(content, str) and bool(content.strip())
                and not refusal and not unexpected_tools and not mismatch)
    result = {"status": "observed" if complete else "incomplete", **request,
              "observation": content if isinstance(content, str) else "",
              "model_returned": model_returned or "unknown", "response_id": response.id,
              "finish_reason": finish, "usage": usage,
              "refusal": refusal, "unexpected_tool_calls": unexpected_tools, "model_mismatch": mismatch,
              "limitations": ["Model observation is not a confirmed fact or engineering approval.",
                              "Coverage is only the supplied page/region; no whole-document OCR claim.",
                              "Original sources and existing OCR are unchanged."],
              "reused": False}
    if not complete:
        result["limitations"].append("Response was empty, refused, unsupported, truncated, from a different model or did not confirm normal completion; not cached as a successful observation.")
    record_outcome(store, attempt_key, 'completed' if complete else 'received_invalid',
                   result=result, cache_operation=operation if complete else None)
    store.event("vision_response", result)
    return result
