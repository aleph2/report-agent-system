"""Optional native selection on the existing authorized catalog; no search loop."""
import json
from uuid import uuid4

from langchain.agents.middleware.tool_selection import LLMToolSelectorMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .errors import ActionRejected
from .store import digest, encode


def selection_mode(manifest):
    mode = manifest.get('tool_selection_mode', 'off')
    if mode not in ('off', 'on'):
        raise ActionRejected('TOOL_SELECTION_MODE_INVALID')
    return mode


def _actor(workspace, role):
    from .content_tasks import bound_actor
    from .hierarchical_tools import actor_for
    return bound_actor(workspace, role, actor_for(role))


def selection_context(workspace, role, request):
    from .task_context import exact_task_context, current_user_task
    current = exact_task_context(workspace, role)
    context = {k: current[k] for k in ('role', 'goal', 'scope_instruction', 'assignment',
        'current_invocation', 'scoped_instructions', 'operator_feedback', 'learned_guidance') if k in current}
    user_task = current_user_task(workspace, role, request.state,
                                  request.state.get('messages', request.messages))
    if user_task is not None:
        context['current_user_task'] = user_task['text']
    public = []
    for message in request.messages:
        if isinstance(message, AIMessage) and message.text:
            public.append({'action_intent': message.text})
        elif isinstance(message, ToolMessage):
            item = {'tool': message.name, 'status': message.status}
            try:
                value = json.loads(message.content)
            except (ValueError, TypeError):
                value = None
            if isinstance(value, dict):
                item.update({k: value[k] for k in ('ok', 'code', 'execution_state', 'retryable') if k in value})
                if message.status == 'error' or value.get('ok') is False:
                    # Free-text validation errors can echo input bodies; keep typed recovery fields.
                    diagnostic = value.get('diagnostic')
                    if isinstance(diagnostic, dict):
                        safe = {k: diagnostic[k] for k in ('reason', 'parameter_path', 'allowed_types') if k in diagnostic}
                        if isinstance(diagnostic.get('fields'), list):
                            safe['fields'] = [{k: field[k] for k in
                                ('field', 'reason', 'definition', 'related_fields', 'message') if k in field}
                                for field in diagnostic['fields'] if isinstance(field, dict)]
                        item['diagnostic'] = safe
                    if isinstance(value.get('root_contract'), dict):
                        item['root_contract'] = {k: value['root_contract'][k] for k in
                            ('received_keys', 'required_keys', 'allowed_keys', 'missing_required_keys', 'unexpected_keys')
                            if k in value['root_contract']}
            public.append(item)
    context['public_action_observations'] = public
    return context


class NativeToolSelection(LLMToolSelectorMiddleware):
    def __init__(self, workspace, role):
        super().__init__(max_tools=None)
        self.workspace, self.role = workspace, role

    async def awrap_model_call(self, request, handler):
        from .live_messages import _MODEL, model_offer, _once
        from .prompt_provenance import prompt_call
        context = selection_context(self.workspace, self.role, request)
        offer = _MODEL.get()

        async def business(selected):
            names = [t.name if hasattr(t, 'name') else t.get('function', {}).get('name')
                     for t in selected.tools]
            # The exact request dictionary still binds a selected task/review tool.
            current_offer = offer if offer and offer['function']['name'] in names else None
            with model_offer(current_offer):
                response = await handler(selected.override(messages=request.messages))
            actor = _actor(self.workspace, self.role)
            from .task_state_delivery import model_response
            inner = model_response(response)
            answers = [inner] if isinstance(inner, AIMessage) else inner.result
            for answer in answers:
                if isinstance(answer, AIMessage):
                    key = 'tool_selection_offer:' + uuid4().hex
                    _once(self.workspace.store, key, {'actor_id': actor.id, 'task_id': actor.task_id,
                        'names': names, 'calls_digest': digest(answer.tool_calls)})
                    answer.additional_kwargs['report_tool_selection_offer'] = key
            return response

        with prompt_call(self.workspace.store, 'tool_selector:' + self.role,
                status='native_selection', offered={'context': context,
                    'catalog': [{'name': getattr(t, 'name', None), 'description': getattr(t, 'description', None)}
                                for t in request.tools]}), model_offer(None):
            return await super().awrap_model_call(
                request.override(messages=[HumanMessage(content=encode(context))]), business)


def reject_unoffered(workspace, role, request):
    """Check before task binding/registration, not after a delegated side effect."""
    from .handoff_release import manifest
    if selection_mode(manifest(workspace.store)) == 'off':
        return None
    actor = _actor(workspace, role)
    call = request.tool_call
    history = request.runtime.state.get('messages', []) if request.runtime else []
    for message in reversed(history):
        if not isinstance(message, AIMessage) or not any(c['id'] == call['id'] for c in message.tool_calls):
            continue
        key = message.additional_kwargs.get('report_tool_selection_offer')
        proof = workspace.store.get(key) if isinstance(key, str) and key.startswith('tool_selection_offer:') else None
        if (proof and proof['actor_id'] == actor.id and proof['task_id'] == actor.task_id
                and proof['calls_digest'] == digest(message.tool_calls)
                and call['name'] in proof['names']
                and any(c['id'] == call['id'] and c['name'] == call['name'] and c['args'] == call['args']
                        for c in message.tool_calls)):
            return None
        break
    return ToolMessage(encode({'ok': False, 'code': 'TOOL_NOT_OFFERED',
        'execution_state': 'not_executed',
        'message': 'This call had no current offered definition. Decide again after fresh tool selection; this call was not executed or queued.'}),
        name=call['name'], tool_call_id=call['id'], status='error')
