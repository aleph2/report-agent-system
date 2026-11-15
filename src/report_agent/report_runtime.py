from __future__ import annotations

import inspect
from functools import wraps

from .catalog import Catalog
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


def library_tools(workspace, task_id=None):
    def search_sources(query: str, offset: int = 0, limit: int = 10) -> dict:
        """Search current source text literally. Returned locations are partial observations, not completeness checks."""
        page = Catalog(workspace.store).search(query, offset, limit)
        if task_id:
            workspace.record_read(task_id, source_ids=[m["source_id"] for m in page["matches"]])
            workspace.store.event("source_observation", {"task_id": task_id, "extent": "search_hits",
                "blocks": [{"source_id": m["source_id"], "ordinal": ordinal}
                           for m in page["matches"] for ordinal in m["ordinals"]]})
        return page

    def read_source_page(source_id: str, offset: int = 0, limit: int = 10) -> dict:
        """Read located source blocks, with next_offset and parser limitations. Historical versions remain readable."""
        page = Catalog(workspace.store).read(source_id, offset, limit)
        if task_id and page["blocks"]:
            workspace.record_read(task_id, source_ids=[source_id])
            workspace.store.event("source_observation", {"task_id": task_id, "source_id": source_id,
                "extent": "page", "ordinals": [b["ordinal"] for b in page["blocks"]], "next_offset": page["next_offset"]})
        return page

    def search_results(query: str, offset: int = 0, limit: int = 10) -> dict:
        """Find saved result metadata by literal title/body match. Read selected results to inspect their content."""
        Catalog._page(offset, limit)
        if not query.strip():
            raise ActionRejected("SEARCH_QUERY_REQUIRED")
        matches = [r for r in workspace.status()["results"] if query.casefold() in (r["title"] + "\n" + r["body"]).casefold()]
        return {"matches": [{k: v for k, v in r.items() if k != "body"} for r in matches[offset:offset + limit]],
                "total": len(matches), "next_offset": offset + limit if offset + limit < len(matches) else None,
                "method": "literal substring, not synonym inference"}

    def read_result_page(result_id: str, offset: int = 0, characters: int = 8000) -> dict:
        """Read an immutable shared result's text slice; next_offset identifies unread content."""
        if offset < 0 or not 1 <= characters <= 16000:
            raise ActionRejected("INVALID_RESULT_PAGE")
        result = workspace.result(result_id)
        result["current"] = result_id not in workspace.impact()["affected_result_ids"]
        body = result.pop("body")
        text = body[offset:offset + characters]
        if task_id and text:
            workspace.record_read(task_id, result_ids=[result_id])
        return {"result": result, "text": text, "total_characters": len(body), "offset": offset,
                "next_offset": offset + len(text) if offset + len(text) < len(body) else None}

    return [search_sources, read_source_page, search_results, read_result_page]


def error_data(exc):
    # Do not expose provider exception bodies or credentials through the GUI.
    code = str(exc) if isinstance(exc, (ValueError, PermissionError, RuntimeError)) else ""
    safe = code if code and all(c.isupper() or c in "_0123456789" for c in code) else "EXECUTION_FAILED"
    return {"type": type(exc).__name__, "http_status": getattr(exc, "status_code", None),
            "message": safe}
