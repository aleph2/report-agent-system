"""Graph-owned configuration snapshot; business records remain in ContentStore."""
from copy import deepcopy

from .errors import ActionRejected

FIELDS = ('review_interface_profile', 'delegation_prompt_profile', 'operation_identity_profile',
    'content_input_profile', 'report_expression_profile', 'content_contract', 'review_entrypoint',
    'review_execution_mode', 'goal', 'scope_instruction', 'report_id', 'report_category', 'source_use', 'report_prompt_profile', 'review_plan_contract', 'review_submission_contract', 'tool_discovery_profile', 'history_projection_profile')
METADATA = {'review_interface_profile': 'report_review_interface_profile',
    'delegation_prompt_profile': 'report_delegation_prompt_profile',
    'operation_identity_profile': 'report_operation_identity_profile',
    'content_input_profile': 'report_content_input_profile',
    'report_expression_profile': 'report_expression_profile', 'report_prompt_profile':'report_prompt_profile',
    'review_submission_contract': 'report_review_submission_contract'}


def release(manifest):
    from .prompt_sources import (validate_review_interface_profile, validate_delegation_profile,
        validate_content_input_profile, validate_report_expression_profile, validate_report_prompt_profile,
        validate_review_plan_contract, validate_review_submission_contract)
    from .operation_identity import validate_profile
    from .store import digest
    validate_review_interface_profile(manifest)
    if manifest.get('tool_discovery_profile') not in (None, 'agent-search-v1', 'agent-search-v2'):
        raise ActionRejected('UNKNOWN_TOOL_DISCOVERY_PROFILE')
    if manifest.get('history_projection_profile') not in (None, 'exact-history-v1'):
        raise ActionRejected('UNKNOWN_HISTORY_PROJECTION_PROFILE')
    validate_report_prompt_profile(manifest)
    plan_contract = validate_review_plan_contract(manifest)
    validate_review_submission_contract(manifest)
    value = deepcopy({k: manifest[k] for k in FIELDS if k in manifest})
    value.update(delegation_prompt_profile=validate_delegation_profile(manifest),
        operation_identity_profile=validate_profile(manifest),
        content_input_profile=validate_content_input_profile(manifest),
        report_expression_profile=validate_report_expression_profile(manifest))
    if plan_contract:
        # Bind prerequisite projection only for the new contract; old release identities stay exact.
        value.update(context_policy=manifest['context_policy'], context_projection=manifest['context_projection'])
    value['digest'] = digest(value)
    return value


def manifest(store):
    from langgraph.config import get_config
    try:
        metadata = get_config().get('metadata', {})
    except RuntimeError:
        metadata = {}
    bound = metadata.get('report_handoff_release')
    if bound is None:
        if metadata.get('report_review_interface_profile') == 'review-interfaces-v4':
            raise ActionRejected('HANDOFF_RELEASE_REQUIRED')
        return store.manifest
    if (not isinstance(bound, dict) or bound.get('review_interface_profile') != 'review-interfaces-v4'
            or bound.get('digest') != release(bound)['digest']):
        raise ActionRejected('HANDOFF_RELEASE_REQUIRED')
    if any(field in bound and name in metadata and bound[field] != metadata[name]
           for field, name in METADATA.items()):
        raise ActionRejected('HANDOFF_RELEASE_METADATA_MISMATCH')
    return deepcopy(bound)
