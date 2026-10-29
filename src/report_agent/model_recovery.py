"""Application-owned, opt-in recovery of pure async inference.

One physical attempt still belongs to model_invocation/HTTPX/TokenBudget. This
module owns only persistent recovery permission, never business adoption or
settlement. A new HTTP attempt can duplicate remote compute and billing.
"""
import asyncio
import base64
import copy
import hashlib
import json
import time
from contextvars import ContextVar
from contextlib import contextmanager
from uuid import uuid4

import httpx
import openai
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_fixed

from .model_invocation import is_model_timeout
from .store import digest, encode

POLICY_KEY = 'model_recovery_policy'
STATE_KEY = 'model_recovery_usage'
PREFIX = 'model_recovery_call:'
_ACTIVE = ContextVar('model_recovery_active', default=None)
_OWNER = ContextVar('model_recovery_owner', default=None)
_TASK_PREFIX = ('Current task bindings and navigation previews. Incomplete fields expose '
                'read_decision_state paths; previews do not establish complete instruction or evidence coverage:\n')


class RecoveryBlocked(openai.OpenAIError, RuntimeError):
    """Local permission refusal, not an SDK-retryable connection failure."""


@contextmanager
def recovery_owner(store, owner, operation):
    """Caller supplies its already-authorized task/operation; no permissions added."""
    token = _OWNER.set((str(store.root), {'actor': owner.__dict__ if owner else None,
                                         'operation': operation}))
    try:
        yield
    finally:
        _OWNER.reset(token)


def owner_identity(store, role):
    from .content_tasks import model_owner_identity
    bound = model_owner_identity(store)
    explicit = _OWNER.get()
    if explicit is not None:
        if explicit[0] != str(store.root):
            raise RecoveryBlocked('RECOVERY_OWNER_WORKSPACE_MISMATCH')
        if explicit[1]['actor'] is None and bound is None:
            return None
        return {'binding': bound, 'operation': explicit[1]}
    if bound is not None:
        return bound
    if role == 'coordinator':
        return {'case_root': str(store.root), 'actor': 'coordinator'}
    return None


def canonical_input(payload):
    """Strip only identified server resource counters, never arbitrary user JSON."""
    value = copy.deepcopy(payload)
    for message in value.get('messages', []):
        # Wire messages normally have no envelope id. Tool call ids are retained.
        message.pop('id', None)
        if message.get('role') != 'system':
            continue
        content = message.get('content')
        blocks = content if isinstance(content, list) else [{'type': 'text', 'text': content}]
        for block in blocks:
            text = block.get('text') if isinstance(block, dict) else None
            if not isinstance(text, str) or not text.startswith(_TASK_PREFIX):
                continue
            try:
                context = json.loads(text[len(_TASK_PREFIX):])
            except ValueError:
                continue
            if not isinstance(context, dict) or context.get('origin') != 'server_bound_application_state':
                continue
            context.pop('execution_resources', None)
            context.pop('execution_token_resources', None)
            block['text'] = _TASK_PREFIX + encode(context)
        if not isinstance(content, list):
            message['content'] = blocks[0]['text']
    return value


def activate_recovery(store, *, authorization, blocked_calls=(), blocked_wire_hashes=(), version=1):
    """Explicit host activation; never reset counters, old receipts or token holds.

    blocked_calls are canonical identities certified by historical boundary
    inspection. This is exact identity fencing, not a semantic duplicate oracle.
    """
    if not authorization:
        raise ValueError('RECOVERY_AUTHORIZATION_REQUIRED')
    if type(version) is not int or version not in {1, 2}:
        raise ValueError('INVALID_RECOVERY_POLICY_VERSION')
    policy = {'version': version, 'authorization': authorization, 'extra_per_call': 1,
              'extra_per_case': 4, 'cooldown_seconds': 120, 'exhaustions_to_open': 2,
              'backoff_seconds': 2, 'extra_token_ceiling': 8_000_000,
              'blocked_calls': sorted(set(blocked_calls)),
              'blocked_wire_hashes': sorted(set(blocked_wire_hashes))}
    if version == 2:
        policy.update(extra_per_call=0, extra_per_case=0, extra_token_ceiling=0)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT value FROM state WHERE key=?', (POLICY_KEY,)).fetchone()
        if prior and json.loads(prior[0]) != policy:
            raise RecoveryBlocked('RECOVERY_POLICY_ALREADY_BOUND')
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)', (POLICY_KEY, encode(policy)))
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',
                   (STATE_KEY, encode({'extra_calls': 0, 'extra_token_bounds': 0, 'services': {}})))
    return policy


def _get(db, key, default=None):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def load_recovery_policy(store):
    """Read authoritative control state, independently of diagnostic get sinks.

    Only an absent row disables recovery. Unreadable/corrupt controls stop local
    admission with a typed non-retryable error; never pretend they are absent.
    """
    if store is None:
        return None
    missing = object()
    try:
        with store.connect() as db:
            policy = _get(db, POLICY_KEY, missing)
        if policy is missing:
            return None
        if (not isinstance(policy, dict) or type(policy.get('version')) is not int or policy.get('version') not in {1, 2}
                or not policy.get('authorization')
                or any(type(policy.get(k)) is not int or policy[k] < 0 for k in (
                    'extra_per_call', 'extra_per_case', 'cooldown_seconds',
                    'exhaustions_to_open', 'backoff_seconds', 'extra_token_ceiling'))
                or any(not isinstance(policy.get(k), list) or any(
                    not isinstance(v, str) or len(v) != 64
                    or any(c not in '0123456789abcdef' for c in v) for v in policy[k])
                    for k in ('blocked_calls', 'blocked_wire_hashes'))
                or (policy.get('version') == 2 and any(policy.get(k) != 0 for k in
                    ('extra_per_call', 'extra_per_case', 'extra_token_ceiling')))):
            raise ValueError('INVALID_RECOVERY_POLICY')
        return policy
    except Exception as exc:
        raise RecoveryBlocked('RECOVERY_POLICY_READ_FAILED') from exc


def _load_call(store, key):
    try:
        with store.connect() as db:
            value = _get(db, key)
        if not isinstance(value, dict):
            raise ValueError('RECOVERY_CALL_MISSING')
        return value
    except Exception as exc:
        raise RecoveryBlocked('RECOVERY_STATE_READ_FAILED') from exc


def admit_recovery_request(request, store=None):
    """Exact historical wire fence before financial admission; no semantic claim."""
    active = _ACTIVE.get()
    store = store if store is not None else active[0] if active is not None else None
    policy = load_recovery_policy(store)
    if policy and hashlib.sha256(request.content).hexdigest() in policy['blocked_wire_hashes']:
        raise RecoveryBlocked('RECOVERY_HISTORICAL_WIRE_FENCED')


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(value)))


def transient(error):
    # HTTP status, schema/empty/length, budget and permission errors are not
    # automatically reissued. External cancellation is never caught here.
    from .input_capacity import CapacityAdmissionRejected, capacity_failure
    from .request_budget import RequestBudgetExceeded
    if capacity_failure(error) is not None:
        return False
    current, seen = error, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, 'non_retryable', False):
            return False
        if isinstance(current, (RecoveryBlocked, CapacityAdmissionRejected,
                                RequestBudgetExceeded, openai.APIStatusError)):
            return False
        current = current.__cause__
    return is_model_timeout(error) or isinstance(error, (
        openai.APIConnectionError, httpx.NetworkError, httpx.RemoteProtocolError))


def recovery_block(error):
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        if isinstance(error, RecoveryBlocked):
            return error
        seen.add(id(error))
        error = error.__cause__
    return None


def capture_response(response):
    """Called after complete body read. No headers, images or input bodies saved.

    The private raw body may contain reasoning; it is never put in public events
    or agent checkpoints. Accounting remains independent and is not rewritten.
    """
    active = _ACTIVE.get()
    if active is None:
        return
    store, key, owner, ordinal = active
    reservation = response.request.extensions.get('report_token_budget')
    raw = {'status': response.status_code, 'body_base64': base64.b64encode(response.content).decode('ascii'),
           'attempt_id': reservation[1] if reservation is not None else None,
           'recorded_at': time.time()}
    try:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            call = _get(db, key)
            if call is None or call['owner'] != owner or call['ordinal'] != ordinal:
                raise RecoveryBlocked('RECOVERY_CAPTURE_OWNER_MISMATCH')
            call.update(raw=raw, state='response_received')
            _put(db, key, call)
    except Exception as exc:
        raise RecoveryBlocked('RECOVERY_RAW_PERSISTENCE_FAILED') from exc


def _raw_json(raw):
    return json.loads(base64.b64decode(raw['body_base64']))


def _claim(store, key, service, policy, full_hash, *, role=None, invocation_owner=None):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        call = _get(db, key)
        if call is not None:
            # A prior primary cannot become a fresh primary after restart. Raw
            # may be reparsed locally, but unknown/inflight work is fenced.
            if call.get('raw') is not None and not call.get('active'):
                return call, False
            raise RecoveryBlocked('RECOVERY_PRIOR_ATTEMPT_UNRESOLVED')
        if key[len(PREFIX):] in policy['blocked_calls']:
            raise RecoveryBlocked('RECOVERY_HISTORICAL_ATTEMPT_FENCED')
        call = {'owner': str(uuid4()), 'service': service, 'state': 'inflight', 'active': True,
                'ordinal': 0, 'full_input_sha256': full_hash, 'extra_calls': 0}
        if role is not None:call.update(role=role,invocation_owner=invocation_owner)
        _put(db, key, call)
        return call, True


def _transition(store, key, owner, policy, *, retry=False, success=False, error=None, extra_bound=None):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        call, usage = _get(db, key), _get(db, STATE_KEY)
        if call['owner'] != owner:
            raise RecoveryBlocked('RECOVERY_OWNER_MISMATCH')
        if success:
            call['state'] = 'returned'
            call['active'] = False
        elif (retry and extra_bound is not None
              and call['extra_calls'] < policy['extra_per_call']
              and usage['extra_calls'] < policy['extra_per_case']
              and usage['extra_token_bounds'] + extra_bound <= policy['extra_token_ceiling']):
            # Reserve permission atomically before platform retry/dispatch. A crash
            # consumes this permission conservatively; it never releases money.
            usage['extra_calls'] += 1
            usage['extra_token_bounds'] += extra_bound
            call.setdefault('attempt_history', []).append({
                'ordinal': call['ordinal'], 'state': 'unknown',
                'exception_type': type(error).__name__,
                'model_call_facts': getattr(error, 'model_call_facts', None)})
            call.update(extra_calls=call['extra_calls'] + 1, ordinal=call['ordinal'] + 1,
                        state='inflight', raw=None)
            _put(db, key, call)
            _put(db, STATE_KEY, usage)
            return True
        else:
            call['state'] = ('cancelled' if isinstance(error, asyncio.CancelledError) else
                             'response_received' if call.get('raw') else 'unknown')
            call['active'] = False
            call['exception_type'] = type(error).__name__ if error is not None else None
            from .input_capacity import capacity_failure, capacity_response_received
            capacity = capacity_failure(error)
            if capacity is not None:
                from .request_budget import current_not_dispatched_proof
                proof = current_not_dispatched_proof(error)
                received = bool(call.get('raw')) or capacity_response_received(error)
                call.update(capacity=capacity, state='capacity_blocked',
                            raw_response_received=received,
                            provider_outcome='not_dispatched' if proof else 'response_received' if received else 'unknown')
                if proof is not None:
                    call['admission_proof'] = proof
            else:
                from .request_budget import RequestBudgetExceeded, current_not_dispatched_proof
                proof=current_not_dispatched_proof(error) if isinstance(error,RequestBudgetExceeded) else None
                if proof is not None:
                    call.update(state='local_admission_blocked',provider_outcome='not_dispatched',admission_proof=proof)
                    error.report_local_admission_key=key
        _put(db, key, call)
        _put(db, STATE_KEY, usage)
        return False


async def recover_model_call(*, store, role, profile, payload, invoke, parse_raw, safe=True,
                             owner=None, on_reuse=None):
    """At most one extra inference; no new deadline, model selection or graph loop.

    `invoke` owns one existing model_invocation and one physical SDK call. Raw
    protocol reconstruction runs locally and still passes original validators.
    """
    policy = load_recovery_policy(store)
    owner = owner if owner is not None else owner_identity(store, role) if store is not None else None
    if not policy or not safe or owner is None:
        return await invoke()
    service = digest({'model': profile.get('model'), 'endpoint': str(profile.get('endpoint', '')).rstrip('/')})
    identity = digest({'service': service, 'role': role, 'owner': owner,
                       'profile': profile, 'input': canonical_input(payload)})
    key = PREFIX + identity
    call, fresh = _claim(store, key, service, policy, digest(payload),role=role,invocation_owner=owner)
    if not fresh:
        if call['raw']['status'] != 200:
            raise RecoveryBlocked('RECOVERY_PRIOR_RESPONSE_NOT_SUCCESSFUL')
        result = parse_raw(_raw_json(call['raw']))
        store.event('model_recovery_raw_reused', {'identity': identity, 'role': role,
                    'origin_attempt_id': call['raw']['attempt_id'], 'new_http_attempt': False})
        provenance = {'source_attempt_id': call['raw']['attempt_id'], 'source_operation': key,
                      'recorded_at': call['raw']['recorded_at'], 'reused': True, 'no_new_http': True}
        return on_reuse(result, provenance) if on_reuse is not None else result
    owner = call['owner']

    async def attempt():
        # The persisted gate advances ordinal before Tenacity starts its next
        # attempt. Do not capture the primary ordinal in the callback closure.
        current = _load_call(store, key)
        token = _ACTIVE.set((store, key, owner, current['ordinal']))
        try:
            return await invoke()
        except Exception as exc:
            # A full response, even if local conversion timed out, takes
            # precedence over paying for a second inference.
            saved = _load_call(store, key)
            if saved.get('raw') is not None:
                try:
                    if saved['raw']['status'] != 200:
                        raise exc
                    result = parse_raw(_raw_json(saved['raw']))
                except Exception:
                    raise exc
                return result
            raise
        finally:
            _ACTIVE.reset(token)

    def permitted_retry(error):
        return transient(error) and _load_call(store, key).get('raw') is None

    def reserve_extra(retry_state):
        error = retry_state.outcome.exception()
        from .token_budget import current_model_token_bound
        if not _transition(store, key, owner, policy, retry=True, error=error,
                           extra_bound=current_model_token_bound(payload.get('model'))):
            raise error

    # One maintained engine for agent models, standalone text tools and vision.
    # SDK/connect/graph retries remain disabled. Project CAS owns permission and
    # accounting, not retry execution, sleeping or a second agent loop.
    engine = AsyncRetrying(retry=retry_if_exception(permitted_retry),
        stop=stop_after_attempt(policy['extra_per_call'] + 1),
        wait=wait_fixed(policy['backoff_seconds']), before_sleep=reserve_extra, reraise=True)
    from .request_budget import logical_request_admission
    # Preserve any enclosing tool/summary admission trace. Otherwise bind one
    # for the complete logical model invocation, including physical attempts.
    with logical_request_admission(reuse_current=True):
        try:
            result = await engine(attempt)
        except BaseException as exc:
            if _load_call(store, key).get('active'):
                _transition(store, key, owner, policy, error=exc)
            raise
        _transition(store, key, owner, policy, success=True)
    return result
