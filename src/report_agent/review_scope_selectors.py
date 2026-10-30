"""Task-local wire selectors; canonical review identities and judgments stay separate."""
from copy import deepcopy

from .errors import ActionForbidden, ActionRejected

CONTRACT = 'task-scope-selectors-v1'
IDENTITY_FIELDS = ('target_ref', 'criterion_ref', 'scope_id', 'assessment_kind')


def requirements_view(task):
    """Display global positions without changing the authoritative saved list."""
    requirements = task.get('review_requirements') or []
    if task.get('review_submission_contract') != CONTRACT:
        return requirements
    return [{**deepcopy(value), 'assigned_scope_index': index}
            for index, value in enumerate(requirements)]


def validate_contract(manifest):
    if 'review_submission_contract' not in manifest:
        return None
    if manifest['review_submission_contract'] != CONTRACT:
        raise ActionRejected('UNKNOWN_REVIEW_SUBMISSION_CONTRACT')
    if (manifest.get('review_interface_profile') != 'review-interfaces-v4'
            or manifest.get('review_execution_mode') != 'native-reviewer-v2'):
        raise ActionRejected('REVIEW_SUBMISSION_SELECTORS_REQUIRE_NATIVE_V4')
    return CONTRACT


def bind_contract(workspace, manifest):
    selected = validate_contract(manifest)
    bound = workspace.store.get('review_submission_contract_binding')
    if bound is not None:
        if selected != bound:
            raise ActionRejected('REVIEW_SUBMISSION_CONTRACT_BINDING_CHANGED')
    elif selected is not None:
        from .model_config import _execution_history
        if _execution_history(workspace.store):
            raise ActionRejected('REVIEW_SUBMISSION_SELECTORS_REQUIRE_FRESH_PROJECT')
        workspace.store.set('review_submission_contract_binding', selected)
    return selected


def expand_submission(contents, actor, value):
    """Resolve only four identity fields from this actor's immutable assignment."""
    from .content_tasks import bound_actor
    from .workspace import Workspace
    if actor.role != 'reviewer' or bound_actor(Workspace(contents.store), 'reviewer', None) != actor:
        raise ActionForbidden('FORBIDDEN: review scope selector task binding')
    task = contents.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    payload = task['payload']
    if (payload.get('role') != 'reviewer' or actor.id != 'content:reviewer:' + actor.task_id
            or payload.get('review_submission_contract') != CONTRACT):
        raise ActionForbidden('FORBIDDEN: review scope selector contract')
    requirements = payload['review_requirements']
    result = deepcopy(value)
    if not isinstance(result.get('items'), list):
        raise ActionRejected('REVIEW_SCOPE_SELECTOR_INVALID', diagnostic={
            'parameter_path': ['review', 'items'], 'expected': 'nonempty item list'})
    for position, item in enumerate(result['items']):
        path = ['review', 'items', position, 'assigned_scope_index']
        index = item.get('assigned_scope_index') if isinstance(item, dict) else None
        if type(index) is not int or not 0 <= index < len(requirements):
            raise ActionRejected('REVIEW_SCOPE_SELECTOR_INVALID', diagnostic={
                'parameter_path': path, 'allowed_index_range': [0, len(requirements) - 1]})
        mixed = sorted(set(IDENTITY_FIELDS) & item.keys())
        if mixed:
            raise ActionRejected('REVIEW_SCOPE_SELECTOR_MIXED_IDENTITY', diagnostic={
                'parameter_path': path[:-1], 'unexpected_fields': mixed})
        assigned = requirements[index]
        del item['assigned_scope_index']
        item.update({name: deepcopy(assigned[name]) for name in IDENTITY_FIELDS[:-1]})
        item['assessment_kind'] = assigned.get('assessment_kind', 'content')
    return result
