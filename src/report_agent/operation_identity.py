"""Native call identity for opt-in writes; no new receipt store."""
from .errors import ActionRejected

CALLER = 'caller-operation-v1'
NATIVE = 'native-tool-runtime-v1'
ATOMIC_WRITES = frozenset({
    'commit_objects',
    'submit_review', 'record_handoff',
    'save_section_prose', 'propose_material_issue', 'request_system_delivery',
    'save_indicator_outcome', 'save_evidence', 'save_assumption', 'save_gap',
    'export_content_snapshot',
    'export_content_workbook', 'request_layout_capability',
    'save_commission_plan', 'record_assessment_outcome',
    'set_requirement_status', 'link_convention', 'set_scope_boundary', 'set_planning_details',
    'publish_planning_draft', 'add_object', 'add_section', 'add_reconciliation', 'submit_plan', 'request_requirement_resolution'})
NATIVE_WRITES = ATOMIC_WRITES


def validate_profile(manifest):
    value = manifest.get('operation_identity_profile', CALLER)
    if not isinstance(value, str):
        raise ActionRejected('UNKNOWN_OPERATION_IDENTITY_PROFILE')
    return value


def profile(store):
    from langgraph.config import get_config
    try:
        metadata = get_config().get('metadata', {})
    except RuntimeError:
        metadata = {}
    if 'report_operation_identity_profile' in metadata:
        return validate_profile({'operation_identity_profile': metadata['report_operation_identity_profile']})
    return validate_profile(store.manifest)


def native_id(tool_call_id):
    if not isinstance(tool_call_id, str):
        raise ActionRejected('NATIVE_TOOL_CALL_ID_REQUIRED')
    return 'native:process_report_content:' + tool_call_id


def write_id(actor_id, tool_name, tool_call_id):
    if not isinstance(tool_call_id, str):
        raise ActionRejected('NATIVE_TOOL_CALL_ID_REQUIRED')
    if not isinstance(actor_id, str):
        raise ActionRejected('NATIVE_OPERATION_ACTOR_REQUIRED')
    return bound_native_id(actor_id, tool_name, tool_call_id)


def bound_native_id(actor_id, tool_name, tool_call_id):
    """Hash a tool call after the issuing host has validated its own allowlist."""
    from .store import digest
    return 'native:' + tool_name + ':' + digest([actor_id, tool_name, tool_call_id])


def effective_call(store, call, actor_id=None):
    """Only admission uses this trusted copy; persisted model calls stay exact."""
    if call['name'] == 'process_report_content' and profile(store) == NATIVE:
        return {**call, 'args': {**call['args'], 'operation_id': native_id(call.get('id'))}}
    if call['name'] in NATIVE_WRITES and profile(store) == NATIVE:
        return {**call, 'args': {**call['args'], 'operation_id': write_id(actor_id, call['name'], call.get('id'))}}
    return call
