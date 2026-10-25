"""Classify Pydantic failures only at a received model-output boundary."""
from contextlib import contextmanager

from pydantic import ValidationError

from .errors import ActionRejected
from .store import encode


@contextmanager
def received_output(code, operation):
    try:
        yield
    except ValidationError as exc:
        raise ActionRejected(code + ": " + encode({
            "failure_phase": "output",
            "raw_operation": operation,
            "raw_response_received": True,
            "errors": exc.errors(include_input=False, include_context=False, include_url=False),
        })) from exc
