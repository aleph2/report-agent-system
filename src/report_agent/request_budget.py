"""Explicit per-run transport budget, shared by agent and SDK tool requests.

No default quota. The caller must opt in with an authorized limit.
"""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from math import isfinite
from threading import Lock
from time import monotonic
import re
from openai import OpenAIError


class RequestBudgetExceeded(OpenAIError, RuntimeError):
    """Deterministic local refusal: the SDK must not retry it as a transport error."""
    pass


# Fixed local codes only; never disclose arbitrary host/provider exception text.
HOST_ADMISSION_REASONS = frozenset({
    'HOST_TOKEN_BUDGET_REACHED', 'HOST_ADMISSION_WINDOW_ENDED',
    'HOST_TECHNICAL_FAILURE_PENDING', 'HOST_BASELINE_CHANGED',
})


class RequestBudget:
    def __init__(self, maximum, *, deadline_monotonic=None):
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            raise ValueError('POSITIVE_REQUEST_LIMIT_REQUIRED')
        self.maximum = maximum
        self.count = 0
        self._lock = Lock()
        if deadline_monotonic is not None and (isinstance(deadline_monotonic, bool)
                or not isinstance(deadline_monotonic, (int, float)) or not isfinite(deadline_monotonic)):
            raise ValueError('FINITE_HOST_DEADLINE_REQUIRED')
        # Observation only. The host remains the sole owner of its execution timeout.
        self.deadline_monotonic = deadline_monotonic

    def snapshot(self):
        with self._lock:
            result = {'origin': 'active_host_transport_budget',
                'maximum_http_attempts': self.maximum, 'reserved_http_attempts': self.count,
                'remaining_http_attempts': self.maximum-self.count,
                'includes': 'All POST reservations in this shared budget, including agent, independent tools and SDK retries.',
                'note': 'Observation before the next reservation; concurrent requests may consume remaining attempts. This grants no additional calls and prescribes no actions.'}
        if self.deadline_monotonic is not None:
            result['remaining_seconds'] = max(0.0, self.deadline_monotonic-monotonic())
            result['time_origin'] = 'host_supplied_monotonic_deadline'
        else:
            result['remaining_seconds'] = None
            result['time_origin'] = 'not_bound'
        return result

    def reserve(self):
        _reserve_budgets((self,))


def _reserve_budgets(budgets):
    """Atomic precheck/count using existing locks, including enclosing limits."""
    unique = tuple(dict.fromkeys(budgets))
    with ExitStack() as locks:
        for budget in sorted(unique, key=id):
            locks.enter_context(budget._lock)
        if any(budget.count >= budget.maximum for budget in unique):
            raise RequestBudgetExceeded('MODEL_REQUEST_BUDGET_REACHED')
        for budget in unique:
            budget.count += 1


_active = ContextVar('report_request_budget', default=())
_admission_trace = ContextVar('report_logical_admission_trace', default=None)
_reservation_observer = ContextVar('report_host_reservation_observer', default=())


class AdmissionTrace:
    """Facts from the request hook for exactly one logical provider invocation.

    Admission is conservative: passing the hook may precede a transport failure.
    Zero admissions proves no dispatch only alongside this hook's actual refusal.
    """
    def __init__(self):
        self._lock = Lock()
        self.admitted = 0
        self.refused = 0
        self.last_refusal = None
        self.refusal_context = None

    def accepted(self):
        with self._lock:
            self.admitted += 1

    def rejected(self, error, admission_context=None, *, guard_origin=None):
        from .token_budget import current_token_observation
        codes = {'AUTHORIZED_TOKEN_BUDGET_REACHED', 'MODEL_REQUEST_BUDGET_REACHED',
                 'MODEL_TOKEN_BOUND_NOT_VERIFIED', 'TOKEN_BOUND_VIOLATION_REQUIRES_DIAGNOSIS',
                 'STREAM_USAGE_BUDGET_NOT_SUPPORTED', 'MODEL_CONTEXT_CAPACITY_REJECTED',
                 'PROMPT_FINAL_WIRE_COMPOSITION_MISMATCH', 'PROMPT_EXTRA_BODY_OVERRIDES_COMPOSITION'}
        code = str(error) if str(error) in codes | HOST_ADMISSION_REASONS else 'LOCAL_REQUEST_ADMISSION_REFUSED'
        context = {'reason_code': code}
        if guard_origin is not None:
            context['admission_boundary'] = guard_origin
        if admission_context is not None:
            context['capacity_admission'] = admission_context
        for name, read in [('token_budget_at_refusal', current_token_observation),
                           ('request_budget_at_refusal', current_budget_observation)]:
            try:
                context[name] = read()
            except Exception:
                context[name] = {'context_unavailable': True}
        with self._lock:
            self.refused += 1
            self.last_refusal = error
            self.refusal_context = context

    def not_dispatched_proof(self, error):
        with self._lock:
            if self.admitted or not self.refused or self.last_refusal is not error:
                return None
            return {'origin': 'logical_request_admission_hook',
                    'admitted_http_attempts': 0, 'refused_before_send': self.refused,
                    'provider_outcome': 'not_dispatched', **self.refusal_context}


@contextmanager
def logical_request_admission(*, reuse_current=False):
    if reuse_current and _admission_trace.get() is not None:
        yield _admission_trace.get()
        return
    trace = AdmissionTrace()
    token = _admission_trace.set(trace)
    try:
        yield trace
    finally:
        _admission_trace.reset(token)


def _host_limit_snapshot(value):
    """Copy only typed resource facts; no host prose, URLs or instructions."""
    numbers = {'maximum_tokens', 'recorded_tokens', 'reserved_or_unknown_upper_bounds',
               'remaining_for_new_reservations'}
    required = numbers | {'scope_id', 'model_reservation_bounds', 'includes_original_phases'}
    if (not isinstance(value, dict) or not required <= value.keys()
            or value.keys() - required - {'status'}
            or value.get('status', 'observed') != 'observed'):
        raise ValueError('INVALID_HOST_LIMIT_OBSERVATION')
    identifier = r'[A-Za-z0-9_.:-]{1,128}'
    if (not isinstance(value['scope_id'], str) or not re.fullmatch(identifier, value['scope_id'])
            or any(type(value[key]) is not int or value[key] < 0 for key in numbers)
            or value['maximum_tokens'] < 1
            or type(value['includes_original_phases']) is not bool):
        raise ValueError('INVALID_HOST_LIMIT_OBSERVATION')
    bounds = value['model_reservation_bounds']
    if (not isinstance(bounds, dict) or not bounds or any(
            not isinstance(model, str) or not re.fullmatch(identifier, model)
            or type(bound) is not int or bound < 1 for model, bound in bounds.items())):
        raise ValueError('INVALID_HOST_LIMIT_OBSERVATION')
    remaining = max(0, value['maximum_tokens'] - value['recorded_tokens']
                    - value['reserved_or_unknown_upper_bounds'])
    if value['remaining_for_new_reservations'] != remaining:
        raise ValueError('INCONSISTENT_HOST_LIMIT_OBSERVATION')
    return {key: value[key] for key in numbers} | {
        'scope_id': value['scope_id'], 'status': 'observed',
        'model_reservation_bounds': dict(bounds),
        'includes_original_phases': value['includes_original_phases']}


def current_budget_observation():
    budgets = _active.get()
    if not budgets:
        return None
    result = budgets[-1].snapshot()
    if len(budgets) > 1:
        result['enclosing_request_budgets'] = [budget.snapshot() for budget in budgets[:-1]]
    limits = []
    for _, observation in _reservation_observer.get():
        if observation is not None:
            try:
                limits.append(_host_limit_snapshot(observation()))
            except Exception:
                # Observation is failsoft; the real guard still runs before send.
                limits.append({'status': 'unavailable'})
    if limits:
        result['host_run_limits'] = limits
    return result


@contextmanager
def request_budget(budget):
    budgets = _active.get()
    token = _active.set(budgets if budget in budgets else (*budgets, budget))
    try:
        yield budget
    finally:
        _active.reset(token)


@contextmanager
def request_reservation_observer(observer, *, observation=None):
    """Compose trusted guards and read-only observations; grant no extra calls.

    An inner recovery scope must not replace an outer host cap or its visibility.
    Providers return public resource facts only, never exception/credential text.
    """
    if not callable(observer) or observation is not None and not callable(observation):
        raise TypeError('CALLABLE_HOST_RESERVATION_OBSERVER_REQUIRED')
    token = _reservation_observer.set((*_reservation_observer.get(), (observer, observation)))
    try:
        yield
    finally:
        _reservation_observer.reset(token)


def account_request_sync(request):
    budgets = _active.get()
    if request.method == 'POST':
        from .token_budget import reserve_request
        reservation = None
        trace = _admission_trace.get()
        try:
            reservation = reserve_request(request)
            _reserve_budgets(budgets)
            for observer, _ in _reservation_observer.get():
                try:
                    observer()
                except RequestBudgetExceeded:
                    raise
                except Exception as exc:
                    # Do not let the SDK turn a local persistence failure into
                    # APIConnectionError and a fresh transport retry.
                    raise RequestBudgetExceeded('RECOVERY_RESERVATION_PERSISTENCE_FAILED') from exc
        except BaseException as exc:
            if reservation:
                reservation[0].before_send_cancelled(reservation[1])
            if trace is not None and isinstance(exc, RequestBudgetExceeded):
                trace.rejected(exc)
            raise
        if trace is not None:
            trace.accepted()


async def account_request(request):
    account_request_sync(request)


def record_local_refusal(error, context, *, guard_origin=None):
    """Trusted pre-financial capacity/composition admission hooks only."""
    trace = _admission_trace.get()
    if trace is not None:
        trace.rejected(error, context, guard_origin=guard_origin)


def current_not_dispatched_proof(error):
    """Read same-exception proof; no new admission scope or dispatch authority."""
    trace = _admission_trace.get()
    return trace.not_dispatched_proof(error) if trace is not None else None
