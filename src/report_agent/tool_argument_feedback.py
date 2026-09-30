"""Add parser diagnostics to native invalid-call error feedback, without retries."""
import json

from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

from .store import encode


def diagnostic_messages(messages):
    invalid = {}
    result = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.invalid_tool_calls:
                if call.get('id') and isinstance(call.get('args'), str):
                    invalid[call['id']] = call
        if (isinstance(message, ToolMessage) and message.status == 'error'
                and message.tool_call_id in invalid):
            try:
                json.loads(invalid[message.tool_call_id]['args'], strict=False)
            except json.JSONDecodeError as exc:
                diagnostic = {'message': exc.msg, 'line': exc.lineno,
                              'column': exc.colno, 'character_offset': exc.pos}
                try:
                    existing = json.loads(message.content)
                except (TypeError, ValueError):
                    existing = None
                if not (isinstance(existing, dict) and existing.get('code') == 'INVALID_TOOL_ARGUMENT_JSON'
                        and existing.get('parser_diagnostic') == diagnostic):
                    message = message.model_copy(update={'content': encode({
                        'code': 'INVALID_TOOL_ARGUMENT_JSON', 'execution_state': 'not_executed',
                        'diagnostic_origin': 'python_json_parser', 'parser_diagnostic': diagnostic,
                        'native_feedback': message.content})})
            else:
                error = invalid[message.tool_call_id].get('error', '') or ''
                if error.startswith('STRICT_WIRE_DECODE_FAILED:'):
                    message = message.model_copy(update={'content': encode({
                        'code': 'STRICT_WIRE_DECODE_FAILED', 'execution_state': 'not_executed',
                        'diagnostic': error})})
        result.append(message)
    return result


class InvalidToolFeedback(AgentMiddleware):
    """Return unexecuted invalid calls to the native agent as observations.

    Valid siblings keep their normal tool path. No arguments are repaired and no
    request is retried here; the model chooses its next action from the feedback.
    """

    @hook_config(can_jump_to=['model'])
    async def aafter_agent(self, state, runtime):
        latest = next((m for m in reversed(state['messages']) if isinstance(m, AIMessage)), None)
        if latest is not None and latest.invalid_tool_calls and state.get('structured_response') is not None:
            # Native structured-output routing can end after executing valid
            # siblings. Give the model its pending invalid-call observations
            # before accepting a structured result; do not replay valid tools.
            return {'structured_response': None, 'jump_to': 'model'}
        return None

    @hook_config(can_jump_to=['model'])
    async def aafter_model(self, state, runtime):
        messages = state['messages']
        latest = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if latest is None or not latest.invalid_tool_calls:
            return None
        answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
        pending = [c for c in latest.invalid_tool_calls if c.get('id') not in answered]
        if not pending:
            return None
        if any(not c.get('id') for c in pending):
            from .errors import ActionRejected
            raise ActionRejected('INVALID_TOOL_CALL_MISSING_ID')
        # Reuse the harness's actual error wording for invalid calls only. Never
        # tell it that a valid sibling failed before the native tool node ran it.
        invalid_only = latest.model_copy(update={'tool_calls': [], 'invalid_tool_calls': pending})
        patch = PatchToolCallsMiddleware().before_agent({'messages': [invalid_only]}, runtime)
        errors = [m for m in patch['messages'] if isinstance(m, ToolMessage)]
        errors = diagnostic_messages([latest, *errors])[1:]
        updates = {'messages': errors}
        valid_pending = [c for c in latest.tool_calls if c.get('id') not in answered]
        if not valid_pending:
            updates['jump_to'] = 'model'
            if state.get('structured_response') is not None:
                updates['structured_response'] = None
        return updates
