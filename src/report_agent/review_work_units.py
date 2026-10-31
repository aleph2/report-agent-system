"""Task-bound planning declarations; structure is neither evidence nor semantic approval."""
from copy import deepcopy
from dataclasses import replace
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator
from langchain.agents.middleware import TodoListMiddleware
from langgraph.types import Command
from langchain_core.messages import AIMessage

from .content_models import Ref
from .content_store import ContentStore
from .content_tasks import bound_actor
from .errors import ActionForbidden, ActionRejected
from .store import digest


def bind_contract(workspace, manifest):
    from .prompt_sources import validate_review_plan_contract
    selected = validate_review_plan_contract(manifest)
    bound = workspace.store.get('review_plan_contract_binding')
    if bound is not None:
        if selected != bound:
            raise ActionRejected('REVIEW_PLAN_CONTRACT_BINDING_CHANGED')
    elif selected is not None:
        from .model_config import _execution_history
        if _execution_history(workspace.store):
            raise ActionRejected('REVIEW_PLAN_REQUIRES_FRESH_PROJECT')
        workspace.store.set('review_plan_contract_binding', selected)
    return selected


class ReviewUnit(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    assigned_scope_indexes: list[Annotated[int, Field(ge=0, strict=True)]] = Field(min_length=1)
    material_refs: list[Ref] = Field(default_factory=list)
    material_needs: str = Field(min_length=1)
    method: str = Field(min_length=1)
    decision_conditions: str = Field(min_length=1)
    remaining_work: str

    @model_validator(mode='after')
    def unique_scope_indexes(self):
        if len(set(self.assigned_scope_indexes)) != len(self.assigned_scope_indexes):
            raise ValueError('DUPLICATE_REVIEW_SCOPE_INDEX')
        return self


class ReviewTodo(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str
    status: Literal['pending', 'in_progress', 'completed']
    review_unit: ReviewUnit | None = None


class ReviewPlanning(TodoListMiddleware):
    """Keep the installed native handlers, state channel and Command protocol."""
    def __init__(self, workspace):
        from .prompt_sources import load_prompt
        super().__init__(system_prompt='',
                         tool_description=load_prompt('review-work-units-tool').strip())
        self.workspace = workspace
        tool = self.tools[0]
        schema = create_model('ReviewTodoInput', __base__=tool.args_schema,
                              todos=(list[ReviewTodo], Field(...)))
        self.tools = [tool.model_copy(update={'args_schema': schema})]

    def _request(self, request):
        return request

    def wrap_model_call(self, request, handler):
        return handler(self._request(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._request(request))

    def after_model(self, state, runtime):
        existing = super().after_model(state, runtime)
        if existing:
            return existing
        try:
            todos = public_plan_update(self.workspace, state)
        except ActionRejected:
            # The tool boundary returns the same precise error before any check.
            return None
        return {'todos': todos} if todos is not None else None


def parse_todos(todos):
    if not isinstance(todos, list):
        raise ActionRejected('REVIEW_PLAN_INVALID', diagnostic={'field': 'todos', 'expected': 'list'})
    parsed = []
    for index, todo in enumerate(todos):
        try:
            parsed.append(ReviewTodo.model_validate(todo))
        except ValidationError as error:
            raise ActionRejected('REVIEW_PLAN_INVALID', diagnostic={'fields': [
                {'path': [index, *item['loc']], 'type': item['type']} for item in error.errors()]}) from None
    return parsed


def public_plan_update(workspace, state):
    if current_binding(workspace) is None:
        return None
    messages = state.get('messages', [])
    message = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    if message is None:
        return None
    text = message.text.strip()
    if not text.startswith('{'):
        return None
    from .tool_transport import _unique_object, _no_constant, _finite_float
    try:
        value = json.loads(text, object_pairs_hook=_unique_object,
                           parse_constant=_no_constant, parse_float=_finite_float)
    except (ValueError, RecursionError):
        try:
            first_key, _ = json.JSONDecoder().raw_decode(text[1:].lstrip())
        except (ValueError, RecursionError):
            return None
        if first_key != 'review_plan':
            return None
        raise ActionRejected('REVIEW_PLAN_INVALID', diagnostic={'field': 'public.review_plan',
            'reason': 'A strict JSON object is required; no repair was attempted.'}) from None
    pending = [value]
    has_plan_key = False
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if 'review_plan' in item:
                has_plan_key = True
                break
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    if not has_plan_key:
        return None
    if (not isinstance(value, dict) or set(value) != {'review_plan'}
            or not isinstance(value['review_plan'], dict) or set(value['review_plan']) != {'todos'}):
        raise ActionRejected('REVIEW_PLAN_INVALID', diagnostic={'field': 'public.review_plan',
            'reason': 'Use exactly review_plan.todos without additional wrappers or fields.'})
    todos = value['review_plan']['todos']
    public = [todo.model_dump(mode='json', exclude_none=True) for todo in parse_todos(todos)]
    writes = [call for call in message.tool_calls if call['name'] == 'write_todos']
    if len(writes) > 1:
        raise ActionRejected('REVIEW_PLAN_CONFLICTING_DECLARATIONS')
    for call in writes:
        args = call.get('args')
        if not isinstance(args, dict) or set(args) != {'todos'}:
            raise ActionRejected('REVIEW_PLAN_CONFLICTING_DECLARATIONS')
        native = [todo.model_dump(mode='json', exclude_none=True) for todo in parse_todos(args['todos'])]
        if native != public:
            raise ActionRejected('REVIEW_PLAN_CONFLICTING_DECLARATIONS')
    return validate_todos(workspace, todos, declaration=True)


def current_binding(workspace):
    try:
        actor = bound_actor(workspace, 'reviewer', None)
    except ActionForbidden:
        from .handoff_release import manifest
        if manifest(workspace.store).get('review_plan_contract'):
            raise
        return None
    task = ContentStore(workspace.store).read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    if task['payload'].get('review_plan_contract') != 'work-units-v1':
        return None
    payload = task['payload']
    stamp = digest({'actor': actor.id, 'task': task['ref'],
                    'snapshot': payload['review_snapshot_ref'],
                    'basis': payload['review_commission_basis']['digest'],
                    'release': payload['handoff_release_digest']})
    return task['payload'], stamp


def material_allowed(workspace, task, ref, allowed):
    if ref.key() in allowed:
        return True
    if ref.type != 'RenderArtifact':
        return False
    contents = ContentStore(workspace.store)
    actor = bound_actor(workspace, 'reviewer', None)
    try:
        render = contents.read(ref.model_dump())
        if (render['owner_id'] != actor.id or render['created_by'] != actor.id
                or render['task_id'] != actor.task_id):
            return False
        payload = render['payload']
        exported = Ref.model_validate(payload.get('export_ref'))
        if exported.type != 'ExportArtifact' or exported.key() not in allowed:
            return False
        export = contents.read(exported.model_dump())['payload']
    except (ActionRejected, ActionForbidden, ValidationError):
        return False
    return (payload.get('snapshot_ref') == task['review_snapshot_ref']
            and export.get('snapshot_ref') == task['review_snapshot_ref']
            and bool(export.get('file_digest'))
            and payload.get('export_digest') == export['file_digest'])


def validate_todos(workspace, todos, *, declaration):
    binding = current_binding(workspace)
    if binding is None:
        return None
    task, stamp = binding
    raw = deepcopy(todos)
    if not isinstance(raw, list):
        return parse_todos(raw)
    if not declaration:
        for index, todo in enumerate(raw):
            if not isinstance(todo, dict):
                raise ActionRejected('REVIEW_PLAN_BINDING_MISMATCH', diagnostic={'todo_index': index})
            unit = todo.get('review_unit')
            if unit is not None and (not isinstance(unit, dict) or unit.pop('_binding', None) != stamp):
                raise ActionRejected('REVIEW_PLAN_BINDING_MISMATCH', diagnostic={'todo_index': index})
    parsed = parse_todos(raw)
    units = [todo.review_unit for todo in parsed if todo.review_unit is not None]
    expected = set(range(len(task['review_requirements'])))
    if not units:
        raise ActionRejected('REVIEW_PLAN_REQUIRED', diagnostic={'assigned_scope_indexes': sorted(expected)})
    selected = {index for unit in units for index in unit.assigned_scope_indexes}
    if selected != expected:
        raise ActionRejected('REVIEW_PLAN_SCOPE_MISMATCH', diagnostic={
            'missing_scope_indexes': sorted(expected - selected), 'outside_scope_indexes': sorted(selected - expected)})
    from .task_context import complete_review_materials
    allowed = {Ref.model_validate(record['ref']).key()
               for record in complete_review_materials(workspace, task)['objects']}
    for todo_index, todo in enumerate(parsed):
        if todo.review_unit is not None:
            for ref_index, ref in enumerate(todo.review_unit.material_refs):
                if not material_allowed(workspace, task, ref, allowed):
                    raise ActionRejected('REVIEW_PLAN_MATERIAL_OUTSIDE_ASSIGNMENT', diagnostic={
                        'todo_index': todo_index, 'material_ref_index': ref_index})
    result = [todo.model_dump(mode='json', exclude_none=True) for todo in parsed]
    for todo in result:
        if 'review_unit' in todo:
            todo['review_unit']['_binding'] = stamp
    return result


def prepare_native_todos(workspace, role, call, state):
    if role != 'reviewer' or call['name'] != 'write_todos' or current_binding(workspace) is None:
        return None
    public_plan_update(workspace, state)
    unexpected = sorted(set(call['args']) - {'todos'})
    if unexpected:
        raise ActionRejected('REVIEW_PLAN_INVALID', diagnostic={'unexpected_keys': unexpected})
    todos = call['args'].get('todos')
    parsed = parse_todos(todos)
    if any(todo.review_unit is not None for todo in parsed):
        return validate_todos(workspace, todos, declaration=True)
    return [todo.model_dump(mode='json', exclude_none=True) for todo in parsed]


def retain_native_todos(result, todos):
    if todos is None:
        return result
    if not isinstance(result, Command) or not isinstance(result.update, dict):
        raise ActionRejected('REVIEW_PLAN_NATIVE_COMMAND_REQUIRED')
    update = {**result.update, 'todos': todos}
    # The complete current plan is projected once; do not echo its full body again.
    update['messages'] = [message.model_copy(update={'content':
        f'Accepted {len(todos)} current-task todos; working intentions, not review evidence.'})
        if getattr(message, 'type', None) == 'tool' else message
        for message in update.get('messages', [])]
    return replace(result, update=update)


def require_before_verification(workspace, role, call, state):
    if role != 'reviewer':
        return
    verification = call['name'] in {'calculate', 'inspect_rendered_page', 'analyze_source_image', 'analyze_text',
        'analyze_evidence', 'submit_review', 'confirm_review_reuse', 'correct_own_review'}
    verification |= call['name'] == 'observe_evidence' and call['args'].get('kind') == 'calculation'
    if verification:
        if current_binding(workspace) is not None:
            declared = public_plan_update(workspace, state)
            if declared is not None and declared != state.get('todos'):
                raise ActionRejected('REVIEW_PLAN_STATE_NOT_APPLIED')
        validate_todos(workspace, state.get('todos', []), declaration=False)
