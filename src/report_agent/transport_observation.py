"""Metadata-only HTTP phases; observation never authorizes replay or usage."""
import hashlib
import logging
import re
from time import monotonic
from uuid import uuid4

_KEY = 'report_http_observer'
_PHASES = {'request_started', 'headers_received', 'body_read_completed', 'usage_accounted'}


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


def install_http_observer(request, store, role):
    if store is None:
        return
    reservation = request.extensions.get('report_token_budget')
    identity = reservation[1] if reservation else str(uuid4())
    retry = request.headers.get('x-stainless-retry-count', '0')
    base = {'role': role, 'attempt_id': identity,
            'token_reservation_id': reservation[1] if reservation else None,
            'retry_index': int(retry) if retry.isdecimal() and len(retry) < 5 else None,
            'body_sha256': hashlib.sha256(request.content).hexdigest()}
    started = monotonic()

    def emit(phase, details):
        if phase not in _PHASES:
            return
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


def has_http_observer(request):
    return _KEY in request.extensions


def observe_http_headers(response):
    fields = {'http_status': response.status_code}
    for name in ('x-request-id', 'request-id', 'x-dashscope-request-id'):
        value = response.headers.get(name)
        if value and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
            fields['provider_request_id'] = value
            break
    observe_http_phase(response.request, 'headers_received', **fields)
