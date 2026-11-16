from __future__ import annotations

import inspect
from functools import wraps

from .errors import ActionRejected, ActionForbidden


def feedback_tool(tool):
    """Return rejected domain actions as observations, not whole-run crashes."""
    def rejected(exc):
        return {"accepted": False, "error": error_data(exc),
                "next_action": "Inspect current state and correct the request; permissions are unchanged."}

    if inspect.iscoroutinefunction(tool):
        @wraps(tool)
        async def async_call(*args, **kwargs):
            try:
                return await tool(*args, **kwargs)
            except (ActionRejected, ActionForbidden) as exc:
                return rejected(exc)
        return async_call

    @wraps(tool)
    def call(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except (ActionRejected, ActionForbidden) as exc:
            return rejected(exc)
    return call




def error_data(exc):
    # Do not expose provider exception bodies or credentials through the GUI.
    code = str(exc) if isinstance(exc, (ValueError, PermissionError, RuntimeError)) else ""
    safe = code if code and all(c.isupper() or c in "_0123456789" for c in code) else "EXECUTION_FAILED"
    return {"type": type(exc).__name__, "http_status": getattr(exc, "status_code", None),
            "message": safe}
