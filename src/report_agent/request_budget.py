"""Explicit per-run transport budget, shared by agent and SDK tool requests.

No default quota. The caller must opt in with an authorized limit.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from math import isfinite
from threading import Lock
from time import monotonic
from openai import OpenAIError


class RequestBudgetExceeded(OpenAIError, RuntimeError):
    """Deterministic local refusal: the SDK must not retry it as a transport error."""
    pass


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
        with self._lock:
            if self.count >= self.maximum:
                raise RequestBudgetExceeded('MODEL_REQUEST_BUDGET_REACHED')
            self.count += 1


_active = ContextVar('report_request_budget', default=None)
_admission_trace = ContextVar('report_logical_admission_trace', default=None)


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

    def rejected(self, error):
        from .token_budget import current_token_observation
        codes = {'AUTHORIZED_TOKEN_BUDGET_REACHED', 'MODEL_REQUEST_BUDGET_REACHED',
                 'MODEL_TOKEN_BOUND_NOT_VERIFIED', 'TOKEN_BOUND_VIOLATION_REQUIRES_DIAGNOSIS',
                 'STREAM_USAGE_BUDGET_NOT_SUPPORTED'}
        code = str(error) if str(error) in codes else 'LOCAL_REQUEST_ADMISSION_REFUSED'
        context = {'reason_code': code}
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
def logical_request_admission():
    trace = AdmissionTrace()
    token = _admission_trace.set(trace)
    try:
        yield trace
    finally:
        _admission_trace.reset(token)


def current_budget_observation():
    budget = _active.get()
    return budget.snapshot() if budget is not None else None


@contextmanager
def request_budget(budget):
    token = _active.set(budget)
    try:
        yield budget
    finally:
        _active.reset(token)


def account_request_sync(request):
    budget = _active.get()
    if request.method == 'POST':
        from .token_budget import reserve_request
        reservation = None
        trace = _admission_trace.get()
        try:
            reservation = reserve_request(request)
            if budget is not None:
                budget.reserve()
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
