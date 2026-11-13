"""Optional native selection on the existing authorized catalog; no search loop."""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from langchain.agents.middleware.tool_selection import LLMToolSelectorMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .errors import ActionRejected
from .store import digest, encode


TOOL_BACKENDS = dict.fromkeys((
    'add_object', 'add_question', 'add_reconciliation', 'add_section',
    'add_substitution', 'ask', 'ask_human', 'assert_source',
    'assess_change_impact', 'calculate', 'calculate_assessment', 'capture_review_sources',
    'confirm_review_reuse', 'content_status', 'correct_own_review', 'edit_file',
    'export_content_snapshot', 'export_content_workbook', 'get_operation_receipt', 'glob',
    'grep', 'import_source_versions', 'inspect_source_page', 'link_convention',
    'list_supervision_plugins', 'ls', 'observe_evidence', 'preview_report',
    'project_status', 'propose_material_issue', 'propose_page_binding', 'publish_planning_draft',
    'read_assigned_page', 'read_commission_plan', 'read_content_export', 'read_content_index',
    'read_content_selection', 'read_context', 'read_decision_state', 'read_delivery_review_context',
    'read_execution_trace', 'read_feedback', 'read_file', 'read_layout_capabilities',
    'read_object_index', 'read_planning_draft', 'read_prepared_method', 'read_prepared_tables',
    'read_qualitative_row', 'read_result', 'read_review_obligation_coverage', 'read_review_status',
    'read_source_page', 'read_summary_observations', 'read_task_assignment', 'read_task_supervision',
    'read_tool_observation', 'record_conflict', 'record_execution_decision', 'record_handoff',
    'record_qualitative_finding', 'render_content_export', 'request_layout_capability', 'request_requirement_resolution',
    'request_system_delivery', 'resolve_skeleton_choice', 'review_carried_items', 'save_assumption',
    'save_commission_plan', 'save_evidence', 'save_gap', 'save_section_prose',
    'search_sources', 'select_content_delivery', 'select_delivery', 'set_candidate_disposition',
    'set_planning_details', 'set_requirement_status', 'set_scope_boundary', 'set_section_judgment',
    'submit_plan', 'submit_review', 'write_file', 'write_todos',
), ())
TOOL_BACKENDS.update({'assess_assigned_object': ('writer',), 'analyze_source_image': ('vision',), 'inspect_rendered_page': ('vision',), 'analyze_text': ('text_tool',), 'analyze_evidence': ('text_tool',), 'process_report_content': ('text_tool',), 'perform_assigned_review': ('text_tool',), 'perform_assigned_artifact_review': ('text_tool',), 'task': ('writer', 'reviewer', 'layout')})

_scope = ContextVar('run_tool_authority', default=None)


@contextmanager
def tool_scope(models, services, *, excluded=()):
    """Trusted per-run models and action scope; no paid selector or stored state."""
    from types import MappingProxyType
    token = _scope.set((frozenset(models), MappingProxyType(dict(services)), frozenset(excluded)))
    try:
        yield
    finally:
        _scope.reset(token)


def _allowed(name, scope):
    models, services, excluded = scope
    dependencies = TOOL_BACKENDS.get(name)
    return (name not in excluded and dependencies is not None
            and all(services.get(role) in models for role in dependencies))


def _name(tool):
    return tool.name if hasattr(tool, 'name') else tool.get('function', {}).get('name')


def scope_catalog(request):
    scope = _scope.get()
    return request if scope is None else request.override(
        tools=[tool for tool in request.tools if _allowed(_name(tool), scope)])


def validate_catalog(tools):
    """Check the final offered catalog, including framework-added definitions."""
    scope = _scope.get()
    if scope is not None and any(not _allowed(_name(tool), scope) for tool in tools):
        raise ActionRejected('TOOL_BACKEND_NOT_AUTHORIZED')


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
    call = request.tool_call
    if _scope.get() is not None and not _allowed(call['name'], _scope.get()):
        return ToolMessage(encode({'ok': False, 'code': 'TOOL_NOT_AUTHORIZED_FOR_RUN',
            'execution_state': 'not_executed',
            'message': 'This run does not authorize this tool. The call was not executed or queued.'}),
            name=call['name'], tool_call_id=call['id'], status='error')
    from .handoff_release import manifest
    if selection_mode(manifest(workspace.store)) == 'off':
        return None
    actor = _actor(workspace, role)
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
