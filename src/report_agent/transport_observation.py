"""Metadata-only HTTP phases; observation never authorizes replay or usage."""
import hashlib
import logging
import math
import re
import asyncio
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from uuid import uuid4

import httpx

_KEY = 'report_http_observer'
_PHASES = {'request_started', 'headers_received', 'body_read_completed', 'usage_accounted'}
_ACTIVE = ContextVar('report_transport_observation', default=None)
_TRACE_KEY = 'report_transport_trace'
_CONNECT_KEY = 'report_connection_trace'
_MAX_EVENTS = 64
_MAX_REQUESTS = 16
_NATIVE_STAGES = {
    'connection.connect_tcp', 'connection.connect_unix_socket',
    'connection.start_tls', 'connection.retry', 'proxy.start_tls',
    *{f'{protocol}.{stage}' for protocol in ('http11', 'http2') for stage in (
        'send_connection_init', 'send_request_headers', 'send_request_body',
        'receive_response_headers', 'receive_response_body', 'response_closed')},
}


def _error_type(error):
    name = type(error).__name__
    return name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'Exception'


class _RequestTrace:
    def __init__(self, store, base):
        self.store, self.base = store, base
        self.started = monotonic()
        self.events = deque(maxlen=_MAX_EVENTS)
        self.count = 0
        self.last_native_event = None
        self.last_failure_event = None
        self.callback = self.previous = None
        self.http_status = self.provider_request_id = self.accounting_state = None
        self.recorded_tokens = None
        self.response_complete = False

    def record(self, phase, error=None):
        row = {'phase': phase, 'elapsed_seconds': monotonic() - self.started}
        if error is not None:
            row['exception_type'] = _error_type(error)
        self.count += 1
        self.events.append(row)

    def native(self, event, info):
        stage, _, suffix = event.rpartition('.')
        if stage not in _NATIVE_STAGES or suffix not in {'started', 'complete', 'failed'}:
            return
        self.last_native_event = event
        if suffix == 'failed':
            self.last_failure_event = event
        # Never serialize native info: it contains hosts, headers and streams.
        self.record(event, info.get('exception') if suffix == 'failed' else None)


class _CallTrace:
    def __init__(self, store, role, boundary):
        self.store, self.role, self.boundary = store, role, boundary
        self.requests = []
        self.dropped_requests = 0
        self.started = monotonic()
        self.markers = deque(maxlen=_MAX_EVENTS)
        self.marker_count = 0
        self.call_id = str(uuid4())

    def marker(self, name):
        self.marker_count += 1
        self.markers.append({'phase': name, 'elapsed_seconds': monotonic() - self.started})

    def public_facts(self):
        attempts = [{**t.base, 'last_phase': t.events[-1]['phase'] if t.events else None,
                     'last_native_event': t.last_native_event,
                     'http_status': t.http_status, 'provider_request_id': t.provider_request_id,
                     'response_complete': t.response_complete,
                     'accounting_state': t.accounting_state, 'recorded_tokens': t.recorded_tokens}
                    for t in self.requests]
        return {'call_id': self.call_id, 'role': self.role,
                'observed_attempts': attempts, 'dropped_attempts': self.dropped_requests,
                'elapsed_seconds': monotonic() - self.started,
                'limitation': 'Local observations only. Missing observations do not prove no dispatch, '
                              'zero usage or remote cancellation. No retry authority.'}

    def flush(self, outcome, error):
        if self.store is not None and not self.requests:
            observe_event(self.store, 'model_transport_call', {
                'call_id': self.call_id, 'role': self.role, 'boundary': self.boundary, 'outcome': outcome,
                'exception_type': _error_type(error) if error is not None else None,
                'elapsed_seconds': monotonic() - self.started,
                'request_count': 0, 'no_http_observed': True,
                'model_markers': list(self.markers),
                'dropped_model_markers': max(0, self.marker_count - _MAX_EVENTS),
                'limitation': 'No observed HTTP request is not proof of no dispatch or zero usage.',
            })
        for index, trace in enumerate(self.requests):
            observe_event(trace.store, 'model_transport_trace', {
                **trace.base, 'call_id': self.call_id, 'request_index': index,
                'boundary': self.boundary, 'outcome': outcome,
                'exception_type': _error_type(error) if error is not None else None,
                'elapsed_seconds': monotonic() - trace.started,
                'last_phase': trace.events[-1]['phase'] if trace.events else None,
                'last_native_event': trace.last_native_event,
                'last_failure_event': trace.last_failure_event,
                'events': list(trace.events), 'dropped_events': max(0, trace.count - _MAX_EVENTS),
                'model_markers': list(self.markers),
                'dropped_model_markers': max(0, self.marker_count - _MAX_EVENTS),
                'dropped_requests': self.dropped_requests,
                'buffer_truncated': (trace.count > _MAX_EVENTS or self.marker_count > _MAX_EVENTS
                                     or self.dropped_requests > 0),
                'limitations': 'Best effort local stages; no separate DNS/pool/reuse/first-byte '
                               'measurement or proof of provider receipt/queue/inference. '
                               'httpx_send excludes subsequent SDK parsing and streamed body reads.',
            })


@contextmanager
def observation_scope(store=None, role=None, *, boundary='model_call', join=False, deadline=None):
    """One diagnostic owner; nested HTTPX sends join the model/vision call.

    No IO at native stage callbacks. Flush after classification, never changing
    exception/cancellation, accounting, retries, transport or request contents.
    """
    current = _ACTIVE.get()
    if (join and current is not None
            and (store is None or store is current.store)
            and (role is None or role == current.role)):
        yield current
        return
    scope = _CallTrace(store, role, boundary)
    token = _ACTIVE.set(scope)
    outcome, error = 'returned', None
    try:
        yield scope
    except BaseException as exc:
        error = exc
        outcome = 'cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed'
        from .errors import ModelRequestDeadlineExceeded
        if (isinstance(exc, ModelRequestDeadlineExceeded)
                or (isinstance(exc, TimeoutError) and deadline is not None and deadline.expired())):
            outcome = 'local_deadline_exceeded'
        raise
    finally:
        _ACTIVE.reset(token)
        observe_safely(lambda: scope.flush(outcome, error))


def observe_model_boundary(name):
    if name not in {'payload_started', 'payload_completed', 'result_parse_started',
                    'result_parse_completed'}:
        return
    scope = _ACTIVE.get()
    if scope is not None:
        observe_safely(lambda: scope.marker(name))


class ObservedAsyncClient(httpx.AsyncClient):
    """Public send boundary fallback; the native transport/proxy stays owned by HTTPX."""
    def __init__(self, *, observation_store=None, observation_role=None, **kwargs):
        self.observation_store, self.observation_role = observation_store, observation_role
        super().__init__(**kwargs)

    async def send(self, *args, **kwargs):
        with observation_scope(self.observation_store, self.observation_role, boundary='httpx_send', join=True):
            return await super().send(*args, **kwargs)


class ObservedClient(httpx.Client):
    def __init__(self, *, observation_store=None, observation_role=None, **kwargs):
        self.observation_store, self.observation_role = observation_store, observation_role
        super().__init__(**kwargs)

    def send(self, *args, **kwargs):
        with observation_scope(self.observation_store, self.observation_role, boundary='httpx_send', join=True):
            return super().send(*args, **kwargs)


def observe_safely(callback):
    """Diagnostic IO must never change request execution or its retry outcome.

    This boundary is only for observations, never admission, authorization,
    token accounting, business writes or cancellation.
    """
    try:
        callback()
    except Exception as exc:
        try:
            logging.getLogger(__name__).warning('HTTP observation unavailable: %s', type(exc).__name__)
        except Exception:
            pass  # A broken diagnostic sink cannot authorize a second dispatch.


def observe_event(store, kind, data):
    if store is not None:
        observe_safely(lambda: store.event(kind, data))


def timeout_facts(value):
    """Only final HTTPX phase timeout numbers; never copy arbitrary extensions."""
    if not isinstance(value, dict):
        return {}
    facts = {}
    for key in ('connect', 'read', 'write', 'pool'):
        if key not in value:
            continue
        number = value[key]
        if number is None:
            facts[key] = None
        elif type(number) in (int, float):
            try:
                if math.isfinite(number):
                    facts[key] = number
            except OverflowError:
                pass
    return facts


def install_http_observer(request, store, role, *, asynchronous=False):
    scope = _ACTIVE.get()
    if store is None and scope is not None:
        store, role = scope.store, scope.role
    if store is None:
        return
    reservation = request.extensions.get('report_token_budget')
    identity = reservation[1] if reservation else str(uuid4())
    retry = request.headers.get('x-stainless-retry-count', '0')
    base = {'role': role, 'attempt_id': identity,
            'call_id': scope.call_id if scope is not None else None,
            'effective_timeout': timeout_facts(request.extensions.get('timeout')),
            'token_reservation_id': reservation[1] if reservation else None,
            'retry_index': int(retry) if retry.isdecimal() and len(retry) < 5 else None,
            'body_sha256': hashlib.sha256(request.content).hexdigest()}
    started = monotonic()
    trace = None
    if scope is not None:
        if len(scope.requests) < _MAX_REQUESTS:
            previous = prior_native_trace(request)
            trace = _RequestTrace(store, base)
            scope.requests.append(trace)
            request.extensions[_TRACE_KEY] = trace
            # A freshly installed opt-in connection observer is part of this
            # attempt; only previous-send wrappers should have been removed.
            connection = request.extensions.get(_CONNECT_KEY)
            if connection is not None and request.extensions.get('trace') is connection[0]:
                previous = connection[0]
            if asynchronous:
                async def native_trace(event, info):
                    observe_safely(lambda: trace.native(event, info))
                    if previous is not None:
                        await previous(event, info)
            else:
                def native_trace(event, info):
                    observe_safely(lambda: trace.native(event, info))
                    if previous is not None:
                        return previous(event, info)
            request.extensions['trace'] = native_trace
            trace.callback, trace.previous = native_trace, previous
        else:
            scope.dropped_requests += 1
            previous = prior_native_trace(request, reset=True)
            if previous is None:
                request.extensions.pop('trace', None)
            else:
                request.extensions['trace'] = previous

    def emit(phase, details):
        if phase not in _PHASES:
            return
        if trace is not None:
            observe_safely(lambda: trace.record(phase))
            if phase == 'body_read_completed':
                trace.response_complete = True
            for field in ('http_status', 'provider_request_id', 'accounting_state', 'recorded_tokens'):
                if field in details:
                    setattr(trace, field, details[field])
        allowed = {k: v for k, v in details.items()
                   if k in {'http_status', 'provider_request_id', 'accounting_state', 'recorded_tokens'}}
        observe_event(store, 'model_http_phase', {**base, 'phase': phase,
                      'elapsed_seconds': monotonic() - started, **allowed})

    request.extensions[_KEY] = emit
    emit('request_started', {})


def observe_http_phase(request, phase, **details):
    observer = request.extensions.get(_KEY)
    if observer is not None:
        observer(phase, details)


def current_observation_store():
    """Trusted local context for direct SDK clients, never request-body metadata."""
    scope = _ACTIVE.get()
    return scope.store if scope is not None else None


def has_http_observer(request):
    return _KEY in request.extensions


def prior_native_trace(request, *, reset=False):
    """Unwrap only our callbacks when a public Request is sent again."""
    callback = request.extensions.get('trace')
    old = request.extensions.get(_TRACE_KEY)
    connection = request.extensions.get(_CONNECT_KEY)
    for _ in range(2):
        if old is not None and callback is old.callback:
            callback = old.previous
        elif connection is not None and callback is connection[0]:
            callback = connection[1]
        else:
            break
    if reset:
        request.extensions.pop(_TRACE_KEY, None)
        request.extensions.pop(_CONNECT_KEY, None)
    return callback


def remember_connection_trace(request, callback, previous):
    request.extensions[_CONNECT_KEY] = (callback, previous)
    request.extensions['trace'] = callback


def observe_http_headers(response):
    fields = {'http_status': response.status_code}
    for name in ('x-request-id', 'request-id', 'x-dashscope-request-id'):
        value = response.headers.get(name)
        if value and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
            fields['provider_request_id'] = value
            break
    observe_http_phase(response.request, 'headers_received', **fields)
