"""Complete-request admission at the native client boundary; never trims material.

Legacy review policy is read-only compatibility data, not a provider token limit.
Unverified tokenizer/template/image measurements remain explicitly uncertain.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit

from openai import OpenAIError, APIStatusError
from langchain_core.exceptions import ContextOverflowError
from pydantic import BaseModel, ConfigDict, Field

from .errors import ActionRejected
from .store import digest, encode


KEY = 'review_input_capacity'
ROUTE = 'perform_assigned_review'
_LEGACY = ContextVar('report_legacy_review_capacity', default=None)


class CapacityAdmissionRejected(OpenAIError, RuntimeError):
    """Known local capacity refusal; the SDK must not retry it as a network error."""
    def __init__(self, diagnostic):
        super().__init__('MODEL_CONTEXT_CAPACITY_REJECTED')
        self.diagnostic = diagnostic


class CapacityHandlingRequired(OpenAIError, RuntimeError):
    """A saved capacity failure still needs handling; not a new dispatch."""
    def __init__(self, facts):
        super().__init__('SAVED_MODEL_CAPACITY_FAILURE_REQUIRES_HANDLING')
        self.facts = facts


_LOCAL_REASONS = {
    'REQUESTED_OUTPUT_EXCEEDS_MODEL_CAPACITY': 'local_capacity_exceeded',
    'FULL_REQUEST_EXCEEDS_MODEL_CONTEXT': 'local_capacity_exceeded',
    'LEGACY_REVIEW_COMPLETE_REQUEST_EXCEEDS_CAPACITY': 'legacy_constraint_exceeded',
    **{code: 'profile_binding_or_configuration' for code in (
        'TRUSTED_MODEL_PROFILE_MISMATCH', 'TRUSTED_SERVICE_PROFILE_MISMATCH',
        'LEGACY_CAPACITY_CASE_MISMATCH', 'LEGACY_CAPACITY_REQUEST_NOT_BOUND',
        'CAPACITY_CONFIGURATION_OR_MEASUREMENT_INVALID')},
}


def capacity_failure(error):
    """Public facts only; no provider prose, request bodies or inferred usage.

    A framework overflow can be raised before sending or after a provider error.
    Its type alone is therefore not evidence of a received HTTP response.
    """
    chain, seen, current = [], set(), error
    while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 8:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__
    prior = next((e for e in chain if isinstance(e, CapacityHandlingRequired)), None)
    if prior is not None and isinstance(prior.facts, dict):
        reason = prior.facts.get('reason')
        if reason in _LOCAL_REASONS:
            facts = capacity_failure(CapacityAdmissionRejected(prior.facts))
            return {**facts, 'historical_failure': True}
        if reason == 'PROVIDER_CONTEXT_LENGTH_EXCEEDED' and prior.facts.get('http_status') in {400, 413, 422}:
            return {'reason': reason, 'category': 'explicit_provider_context_rejection',
                    'failure_phase': 'provider_response', 'http_status': prior.facts['http_status'],
                    'automatic_retry': False, 'historical_failure': True}
        if reason == 'FRAMEWORK_CONTEXT_OVERFLOW':
            return {'reason': reason, 'category': 'framework_context_overflow',
                    'failure_phase': 'framework_context_check', 'http_status': None,
                    'automatic_retry': False, 'historical_failure': True}
    local = next((e for e in chain if isinstance(e, CapacityAdmissionRejected)), None)
    if local is not None:
        raw = local.diagnostic if isinstance(local.diagnostic, dict) else {}
        reason = raw.get('reason')
        if reason not in _LOCAL_REASONS:
            reason = 'CAPACITY_CONFIGURATION_OR_MEASUREMENT_INVALID'
        facts = {'reason': reason, 'category': _LOCAL_REASONS[reason],
                 'failure_phase': 'local_capacity_admission', 'http_status': None,
                 'automatic_retry': False}
        for key in ('wire_utf8_bytes', 'requested_output_tokens', 'context_tokens',
                    'maximum_output_tokens', 'input_token_lower_bound', 'input_token_upper_bound'):
            value = raw.get(key)
            if value is None or (type(value) is int and value >= 0):
                facts[key] = value
        sha = raw.get('wire_sha256')
        if isinstance(sha, str) and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha):
            facts['wire_sha256'] = sha
        if raw.get('status') in {'refused', 'known_exceeds'}:
            facts['status'] = raw['status']
        legacy = raw.get('legacy_constraint')
        if isinstance(legacy, dict):
            constraint = {k: legacy[k] for k in ('maximum_input_utf8_bytes', 'input_utf8_bytes')
                          if type(legacy.get(k)) is int and legacy[k] >= 0}
            ref = legacy.get('policy_ref')
            if (isinstance(ref, dict) and ref.get('key') == KEY
                    and type(ref.get('version')) is int and ref['version'] >= 1
                    and isinstance(ref.get('digest'), str) and len(ref['digest']) == 64
                    and all(c in '0123456789abcdef' for c in ref['digest'])):
                constraint['policy_ref'] = {k: ref[k] for k in ('key', 'digest', 'version')}
            facts['legacy_constraint'] = constraint
        return facts
    for item in chain:
        if not isinstance(item, APIStatusError) or item.status_code not in {400, 413, 422}:
            continue
        body = item.body
        code = body.get('code') if isinstance(body, dict) else None
        if isinstance(body, dict) and isinstance(body.get('error'), dict):
            code = body['error'].get('code', code)
        if code == 'context_length_exceeded':
            return {'reason': 'PROVIDER_CONTEXT_LENGTH_EXCEEDED',
                    'category': 'explicit_provider_context_rejection',
                    'failure_phase': 'provider_response', 'http_status': item.status_code,
                    'automatic_retry': False}
    if any(isinstance(e, ContextOverflowError) for e in chain):
        return {'reason': 'FRAMEWORK_CONTEXT_OVERFLOW', 'category': 'framework_context_overflow',
                'failure_phase': 'framework_context_check', 'http_status': None,
                'automatic_retry': False}
    return None


def capacity_handling(facts, boundary):
    """Responsibility at an existing boundary, never permission for a new call."""
    if boundary not in {'tool', 'delegated_agent', 'root_agent'}:
        raise ValueError('UNKNOWN_CAPACITY_FAILURE_BOUNDARY')
    maintenance = facts['category'] == 'profile_binding_or_configuration'
    owner = ('maintenance' if maintenance else 'host_operator') if boundary == 'root_agent' else (
        'parent_coordinator' if boundary == 'delegated_agent' else 'calling_agent')
    return {'boundary': boundary, 'handling_owner': owner,
            'technical_owner': 'maintenance' if maintenance else 'host_operator',
            'automatic_retry': False, 'automatic_resume': False, 'fallback_available': False,
            'available_actions': (['inspect_capacity_configuration'] if maintenance else
                ['inspect_capacity_facts', 'assess_work_with_existing_permissions',
                 'request_resource_or_scope_decision_if_needed']),
            'permission_note': 'Options are not authorization to change models, reduce evidence or checks, '
                               'or replay unknown requests. Saved work and unfinished checks remain.'}


def capacity_response_received(error):
    """An actual SDK response in this cause chain; a framework type is not proof."""
    current, seen = error, set()
    while isinstance(current, BaseException) and id(current) not in seen and len(seen) < 8:
        if isinstance(current, APIStatusError):
            return True
        seen.add(id(current))
        current = current.__cause__
    return False


@dataclass(frozen=True)
class InputTokenBounds:
    """Host-certified bounds for this final request, never supplied by an Agent.

    A lower bound may cover a subset. An upper bound must include provider framing,
    tools and all modalities. Local literal tokenizers alone do not provide that.
    """
    lower: int
    upper: int | None
    evidence: str

    def __post_init__(self):
        if (type(self.lower) is not int or self.lower < 0 or not self.evidence
                or (self.upper is not None and (type(self.upper) is not int or self.upper < self.lower))):
            raise ValueError('TRUSTWORTHY_INPUT_TOKEN_BOUNDS_REQUIRED')


@dataclass(frozen=True)
class CapacityProfile:
    model_name: str
    endpoint: str
    context_tokens: int | None = None
    maximum_output_tokens: int | None = None
    evidence: str = 'Uncertified service: provider validation required.'
    measure: object = None

    def __post_init__(self):
        service_identity(self.endpoint)
        for value in (self.context_tokens, self.maximum_output_tokens):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError('POSITIVE_MODEL_CAPACITY_REQUIRED')
        if self.measure is not None and not callable(self.measure):
            raise ValueError('TRUSTED_CAPACITY_MEASURER_REQUIRED')


def profile_for_service(model_name, endpoint):
    """Capture trusted constructor configuration, without guessing other providers.

    These documented windows do not certify the serving tokenizer/chat template.
    Current text and image requests therefore use explicit provider-validation
    compatibility unless a host supplies certified full-request bounds.
    """
    host = urlsplit(str(endpoint)).hostname or ''
    limits = {
        'deepseek-v4.1-flash': (1000000, 393216, 'https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash'),
        'glm-5.3': (1048576, 131072, 'https://help.aliyun.com/zh/model-studio/glm-5-3'),
    }
    known = limits.get(model_name) if host.endswith('.maas.aliyuncs.com') else None
    return CapacityProfile(model_name, str(endpoint), *(known or (None, None,
        'Uncertified service/model/template: provider-validation compatibility.')))


def evaluate_request(payload, profile, *, wire_bytes):
    """Pure full-wire decision. Byte size is metadata, never a token count."""
    output = payload.get('max_completion_tokens', payload.get('max_tokens'))
    output = output if type(output) is int and output > 0 else None
    result = {'status': 'uncertain', 'mode': 'provider_validation',
              'wire_utf8_bytes': wire_bytes, 'requested_output_tokens': output,
              'measurement': 'Complete serialized request; bytes are not token usage.',
              'input_token_lower_bound': None, 'input_token_upper_bound': None}
    if profile is None:
        result['profile_evidence'] = 'No certified constructor profile; provider-validation compatibility.'
        return result
    result.update(profile_evidence=profile.evidence, context_tokens=profile.context_tokens,
                  maximum_output_tokens=profile.maximum_output_tokens)
    if payload.get('model') != profile.model_name:
        result.update(status='refused', reason='TRUSTED_MODEL_PROFILE_MISMATCH')
        return result
    if output is not None and any(limit is not None and output > limit
                                  for limit in (profile.context_tokens, profile.maximum_output_tokens)):
        result.update(status='known_exceeds', reason='REQUESTED_OUTPUT_EXCEEDS_MODEL_CAPACITY')
        return result
    if profile.measure is not None:
        bounds = profile.measure(payload)
        if not isinstance(bounds, InputTokenBounds):
            raise ValueError('TRUSTWORTHY_INPUT_TOKEN_BOUNDS_REQUIRED')
        result.update(input_token_lower_bound=bounds.lower, input_token_upper_bound=bounds.upper,
                      measurement_evidence=bounds.evidence)
        if profile.context_tokens is not None:
            if bounds.lower + (output or 0) > profile.context_tokens:
                result.update(status='known_exceeds', reason='FULL_REQUEST_EXCEEDS_MODEL_CONTEXT')
            elif output is not None and bounds.upper is not None and bounds.upper + output <= profile.context_tokens:
                result.update(status='fit', mode='certified_bound')
    return result


@contextmanager
def review_capacity_scope(store, policy):
    """Only the review caller can bind legacy case/route metadata, never the model."""
    token = _LEGACY.set((store, _validated(store, policy.model_dump())) if policy else None)
    try:
        yield
    finally:
        _LEGACY.reset(token)


def capacity_request_hook(profile=None, store=None):
    """One owner, installed before financial hooks in native sync/async clients."""
    def check(request):
        if request.method != 'POST':
            return
        from .transport_observation import current_observation_store, observe_event
        observed_store = store if store is not None else current_observation_store()
        payload = json.loads(request.content)
        diagnostic = evaluate_request(payload, profile, wire_bytes=len(request.content))
        diagnostic['wire_sha256'] = hashlib.sha256(request.content).hexdigest()
        if profile is not None:
            expected = service_identity(profile.endpoint)
            actual = service_identity(str(request.url))
            if (any(actual[k] != expected[k] for k in ('scheme', 'host', 'port'))
                    or actual['path'] != expected['path'] + '/chat/completions'):
                diagnostic.update(status='refused', reason='TRUSTED_SERVICE_PROFILE_MISMATCH')
        legacy = _LEGACY.get()
        if legacy is not None:
            legacy_store, policy = legacy
            diagnostic['legacy_constraint'] = {'type': 'legacy_complete_literal_text_byte_constraint',
                'policy_ref': policy_ref(policy), 'maximum_input_utf8_bytes': policy.max_input_utf8_bytes,
                'enforced': False, 'disposition': 'Historical byte policy; actual model profile owns admission.'}
            messages = payload.get('messages', [])
            service = service_identity(str(request.url))
            expected = policy.service
            bound = (payload.get('model') == policy.model_name
                and all(service[k] == expected[k] for k in ('scheme', 'host', 'port'))
                and service['path'] == expected['path'] + '/chat/completions'
                and len(messages) == 2 and [m.get('role') for m in messages] == ['system', 'user']
                and all(isinstance(m.get('content'), str) for m in messages))
            diagnostic['legacy_constraint']['request_matches_historical_binding'] = bound
            if bound:
                size = sum(len(m['content'].encode('utf-8')) for m in messages)
                diagnostic['legacy_constraint']['input_utf8_bytes'] = size
            if observed_store is None:
                observed_store = legacy_store
        observe_event(observed_store, 'model_capacity_admission', diagnostic)
        request.extensions['report_capacity_admission'] = diagnostic
        if diagnostic['status'] in {'known_exceeds', 'refused'}:
            raise CapacityAdmissionRejected(diagnostic)

    def admit(request):
        try:
            check(request)
        except CapacityAdmissionRejected as error:
            from .request_budget import record_local_refusal
            record_local_refusal(error, error.diagnostic)
            raise
        except Exception as exc:
            # A broken deterministic profile/measurement must not become SDK
            # network retries or expose its exception text.
            error = CapacityAdmissionRejected({'status': 'refused',
                'reason': 'CAPACITY_CONFIGURATION_OR_MEASUREMENT_INVALID',
                'exception_type': type(exc).__name__})
            from .request_budget import record_local_refusal
            record_local_refusal(error, error.diagnostic)
            raise error from exc
    return admit


class ReviewInputCapacity(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    version: int = Field(ge=1)
    report_id: str = Field(min_length=1)
    case_root: str = Field(min_length=1)
    route: str
    service: dict
    model_name: str = Field(min_length=1)
    max_input_utf8_bytes: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    declared_context_tokens: int = Field(gt=0)
    host_headroom_tokens: int = Field(gt=0)
    tokenizer_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    provider_evidence: str = Field(min_length=1)
    authorization_record: str = Field(min_length=1)


def service_identity(endpoint):
    parts = urlsplit(str(endpoint))
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ActionRejected('REVIEW_CAPACITY_SERVICE_MUST_BE_NONSECRET')
    return {'scheme': parts.scheme, 'host': parts.hostname,
            'port': parts.port, 'path': parts.path.rstrip('/')}


def _validated(store, value):
    policy = ReviewInputCapacity.model_validate(value)
    configured = store.get('role_model_services', {}).get('text_tool')
    if (policy.route != ROUTE or policy.report_id != store.manifest.get('report_id')
            or policy.case_root != str(store.root.resolve())):
        raise ActionRejected('REVIEW_CAPACITY_POLICY_OUTSIDE_CASE_OR_ROUTE')
    if (not configured or policy.model_name != configured['model']
            or policy.service != service_identity(configured['base_url'])):
        raise ActionRejected('REVIEW_CAPACITY_POLICY_SERVICE_MISMATCH')
    # Retain the historical binding, never treat bytes as model tokens or use
    # its byte/output/headroom arithmetic as current request admission.
    return policy


def bind_review_input_capacity(store, value):
    """Host API only, not registered as an agent tool. Native idle lock required.

    A case gets one immutable binding. This is not a dynamic budget platform.
    """
    with store.run_lock():
        policy = _validated(store, value)
        raw = policy.model_dump()
        with store.connect() as db:
            prior = db.execute('SELECT value FROM state WHERE key=?', (KEY,)).fetchone()
            if prior:
                if prior[0] != encode(raw):
                    raise ActionRejected('REVIEW_CAPACITY_POLICY_ALREADY_BOUND')
            else:
                db.execute('INSERT INTO state VALUES (?,?)', (KEY, encode(raw)))
        return {'key': KEY, 'digest': digest(raw), 'version': policy.version}


def review_capacity(store):
    raw = store.get(KEY)
    return _validated(store, raw) if raw is not None else None


def policy_ref(policy):
    return {'key': KEY, 'digest': digest(policy.model_dump()), 'version': policy.version}


def mandatory_material(contents, requirement):
    """Same exact saved-object encoder as perform_review; no receipt of reading."""
    refs = {encode(ref): ref for ref in [requirement['target_ref'],
        *requirement['required_read_refs'],
        *[ref for m in requirement.get('required_materials', []) for ref in m['refs']]]}
    return [{'kind': 'saved_object', 'object': contents.read(ref)} for ref in refs.values()]


def mandatory_capacity_issue(contents, requirement, policy):
    # A material-only byte measurement is neither complete input nor a token
    # lower bound. Readiness must not reject saved source data on this basis.
    return None


def admit_review_packet(store, policy, model, inputs, system, *, cached=False):
    """Audit full literal text. Capacity is separate from semantic request identity.

    Historical byte/headroom values are audit metadata only. The native shared
    hook uses actual model capacity; this audit does not claim model acceptance
    or completed checking.
    """
    if policy is None:
        return
    from .evidence_analysis import model_identity
    identity = model_identity(model)
    count = len(system.encode('utf-8')) + len(encode(inputs).encode('utf-8'))
    audit = {'capacity_policy_ref': policy_ref(policy), 'input_utf8_bytes': count,
        'maximum_input_utf8_bytes': policy.max_input_utf8_bytes,
        'configured_output_tokens': identity['max_tokens'],
        'host_headroom_tokens': policy.host_headroom_tokens,
        'declared_context_tokens': policy.declared_context_tokens,
        'input_digest': digest(inputs), 'system_digest': digest(system),
        'completed_cache_reuse': cached, 'model_called': False}
    audit.update(constraint_type='legacy_complete_literal_text_byte_constraint',
                 enforcement='historical_audit_only', accepted=None)
    store.event('review_input_capacity_audit', audit)
