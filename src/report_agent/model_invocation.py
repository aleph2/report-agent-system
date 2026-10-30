"""One logical async model deadline; transport phases retain their own meaning."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import math

import httpx
import openai

from .errors import ModelRequestDeadlineExceeded
from .transport_observation import observation_scope, observe_event


MODEL_REQUEST_DEADLINE_SECONDS = 600


def is_model_timeout(error):
    """Classify actual timeout exceptions, never received HTTP status codes."""
    return isinstance(error, (ModelRequestDeadlineExceeded, openai.APITimeoutError,
                              httpx.TimeoutException)) and not isinstance(error, openai.APIStatusError)


def model_request_timeout():
    return httpx.Timeout(connect=15, read=MODEL_REQUEST_DEADLINE_SECONDS, write=60, pool=60)


@asynccontextmanager
async def model_invocation(store=None, role=None):
    """Bound SDK retries/parsing together; never retry or confirm remote cancellation.

    Facts are diagnostic, not a not-sent proof. External cancellation propagates.
    The sync compatibility client has phase timeouts, not this async deadline.
    """
    with observation_scope(store, role) as trace:
        deadline = asyncio.timeout(MODEL_REQUEST_DEADLINE_SECONDS)
        failure = None
        outcome = 'returned'
        observe_event(trace.store, 'model_invocation_started', {
            'call_id': trace.call_id, 'role': trace.role,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'logical_deadline_seconds': MODEL_REQUEST_DEADLINE_SECONDS,
        })
        try:
            try:
                async with deadline:
                    yield trace
            except TimeoutError as exc:
                if not deadline.expired():
                    raise
                raise ModelRequestDeadlineExceeded(MODEL_REQUEST_DEADLINE_SECONDS) from exc
        except BaseException as exc:
            failure = exc
            outcome = ('cancelled' if isinstance(exc, asyncio.CancelledError) else
                       'local_deadline_exceeded' if isinstance(exc, ModelRequestDeadlineExceeded) else 'failed')
            # Attach only our allowlisted local facts, never provider exception text.
            try:
                exc.model_call_facts = trace.public_facts()
            except Exception:
                pass  # Diagnostic attachment must not replace the actual exception.
            raise
        finally:
            observe_event(trace.store, 'model_invocation_outcome', {
                **trace.public_facts(), 'outcome': outcome,
                'deadline_seconds': MODEL_REQUEST_DEADLINE_SECONDS,
                'exception_type': type(failure).__name__ if failure else None,
                'automatic_retry': False,
            })


def _seconds(value):
    if type(value) in (int, float):
        try:
            if math.isfinite(value) and value >= 0:
                return value
        except OverflowError:
            pass
    return None


def model_wait_status(store, *, now=None, limit=200):
    """Read bounded local facts, not provider liveness, accounting or retry authority."""
    from .transport_observation import timeout_facts
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('MODEL_WAIT_EVENT_LIMIT_INVALID')
    result = {'coverage': 'partial', 'event_limit': limit, 'call_limit': 16,
        'observed_call_count': 0, 'truncated': False, 'calls': [],
        'limitation': 'Recent local events only; missing outcomes do not prove a request is still '
                      'running remotely, cancelled, unsent or free. Sync/vision coverage is not '
                      'guaranteed. No retry authority or token-ledger status.'}
    try:
        events = store.events(limit=limit)
    except Exception as error:
        result.update(coverage='unavailable', exception_type=type(error).__name__)
        return result
    calls = {}
    for event in events:
        if event['kind'] not in {'model_invocation_started', 'model_http_phase', 'model_invocation_outcome'}:
            continue
        data = event['data']
        call_id = data.get('call_id')
        if not isinstance(call_id, str) or not call_id:
            continue
        row = calls.pop(call_id, None) or {'call_id': call_id, 'role': data.get('role'),
            'started_at': None, 'logical_deadline_seconds': None, 'elapsed_seconds': None,
            'latest_known_phase': None, 'effective_timeout': {}, 'local_terminal': False,
            'local_outcome': None, 'provider_unknown': True}
        calls[call_id] = row
        if event['kind'] == 'model_invocation_started':
            row.update(started_at=data.get('started_at'),
                       logical_deadline_seconds=_seconds(data.get('logical_deadline_seconds')))
        elif event['kind'] == 'model_http_phase':
            row.update(latest_known_phase=data.get('phase'),
                       effective_timeout=timeout_facts(data.get('effective_timeout')))
        else:
            row.update(local_terminal=True, local_outcome=data.get('outcome'),
                       elapsed_seconds=_seconds(data.get('elapsed_seconds')))
            attempts = data.get('observed_attempts', [])
            if attempts:
                row['latest_known_phase'] = attempts[-1].get('last_phase') or row['latest_known_phase']
            row['provider_unknown'] = not (data.get('outcome') == 'returned'
                and any(attempt.get('response_complete') is True for attempt in attempts))
    observed_at = now or datetime.now(timezone.utc)
    result['observed_call_count'] = len(calls)
    result['truncated'] = len(calls) > result['call_limit']
    result['calls'] = list(calls.values())[-result['call_limit']:]
    for row in result['calls']:
        if not row['local_terminal'] and row['started_at']:
            try:
                started = datetime.fromisoformat(row['started_at'])
                row['elapsed_seconds'] = max(0, (observed_at - started).total_seconds())
            except (TypeError, ValueError):
                pass  # A partial historical timestamp cannot establish elapsed time.
    return result
