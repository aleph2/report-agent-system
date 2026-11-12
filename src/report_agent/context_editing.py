"""One outgoing-only stock clearing policy; immutable readers stay recoverable."""
import json

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.context_editing import ContextEditingMiddleware, ClearToolUsesEdit
from langchain_core.messages import AIMessage, ToolMessage

TRIGGER = 12_000
CLEAR_AT_LEAST = 4_000
CLEARED = "result cleared; repeat the original call with the same arguments to see it again"


class ToolResultEditing(AgentMiddleware):
    def __init__(self, workspace, role):
        self.workspace, self.role = workspace, role

    async def awrap_model_call(self, request, handler):
        # A later model selector could remove the recovery reader.
        if self.workspace.store.manifest.get("tool_selection_mode", "off") != "off":
            return await handler(request)
        offered = {tool.name if hasattr(tool, "name") else
            tool.get("name", tool.get("function", {}).get("name")) for tool in request.tools}
        allowed = {"read_qualitative_row"}
        if self.role != "reviewer":
            allowed.add("read_content_index")
        allowed &= offered
        calls = {call["id"]: call for message in request.messages if isinstance(message, AIMessage)
                 for call in message.tool_calls}
        results = [message for message in request.messages if isinstance(message, ToolMessage)]
        for message in results:
            call = calls.get(message.tool_call_id, {})
            name = message.name or call.get("name")
            if name not in allowed:
                continue
            try:
                value = json.loads(message.content) if isinstance(message.content, str) else None
            except (ValueError, TypeError):
                value = None
            if (message.status != "success" or message.artifact is not None
                    or call.get("name") != name or not isinstance(value, dict)
                    or value.get("ok") is False or {"receipt_id", "evidence_handle"} & value.keys()):
                allowed.discard(name)
        if not allowed:
            return await handler(request)
        names = offered | {message.name for message in results} | {call["name"] for call in calls.values()}
        editor = ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=TRIGGER,
            clear_at_least=CLEAR_AT_LEAST, keep=3, clear_tool_inputs=False,
            exclude_tools=tuple(names - allowed), placeholder=CLEARED)])
        return await editor.awrap_model_call(request, handler)
