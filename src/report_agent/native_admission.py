"""Bind a native graph pause to one actual denied tool call; no execution loop."""
from langgraph.types import interrupt
from .store import digest


def exact_call_key(prefix, actor, call):
    return prefix + digest([actor, call['id'], digest(call)])


def wait_for_exact_resume(event, expected_resume):
    """Only an adapter's independently verified host disposition can release it."""
    while True:
        answer = interrupt(event)
        expected = expected_resume(event)
        if expected is not None and answer == expected:
            return

