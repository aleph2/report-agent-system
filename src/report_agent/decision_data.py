"""Reference-based public observations for decisions; full bytes stay tool-side.

Native AgentMiddleware is the platform boundary. This deterministic formatter
does not analyze source meaning, call models, choose workflows or grant access.
"""
import json
import hashlib
from copy import deepcopy
from typing import Literal
from .content_models import Contract
from .errors import ActionRejected
from .store import digest,encode

POLICY='reference-data-v1'
TOOLS=frozenset({'read_source_page','search_sources','inspect_source_page','analyze_source_image',
    'read_context','read_result','observe_evidence','read_content_selection','read_content_export',
    'analyze_text','analyze_evidence','process_report_content','content_status','perform_assigned_review',
    'perform_assigned_artifact_review'})

def enabled(workspace):
    return workspace.store.manifest.get('decision_data_policy')==POLICY

def bind(workspace):
    selected=workspace.store.manifest.get('decision_data_policy')
    if selected is None:
        if workspace.store.get('decision_data_binding') is not None:
            raise ActionRejected('DECISION_DATA_BINDING_CHANGED')
        return
    if selected!=POLICY:raise ActionRejected('UNKNOWN_DECISION_DATA_POLICY')
    from .task_context import enabled as context_enabled
    if not context_enabled(workspace):raise ActionRejected('DECISION_DATA_REQUIRES_TASK_CONTEXT')
    previous=workspace.store.get('decision_data_binding')
    if previous is None:
        if (workspace.store.root/'checkpoints.db').exists():
            raise ActionRejected('DECISION_DATA_REQUIRES_FRESH_PROJECT')
        workspace.store.set('decision_data_binding',{'policy':POLICY})
        workspace.store.event('decision_data_bound',{'policy':POLICY})
    elif previous!={'policy':POLICY}:raise ActionRejected('DECISION_DATA_BINDING_CHANGED')

def business_envelope(value):
    return (isinstance(value, dict) and type(value.get('ok')) is bool
        and isinstance(value.get('receipt_id'), str)
        and ('result' in value if value['ok'] else 'code' in value))


def public_value(tool, value):
    """Tool-specific data delegation; no field-name/length semantic clipping.

    Authored bodies are adopted by exact receipt/index, while all qualifications
    and generation notes reach the deciding agent. Explicit reads stay exact.
    """
    if tool == 'process_report_content' and isinstance(value, dict):
        outputs = value.get('payloads', [value.get('payload', {})])
        metadata = {k: v for k, v in value.items() if k not in {'payload', 'payloads'}}
        metadata.update(output_count=len(outputs), details_deferred=True,
            outputs={'entries': [dict(
                {k: v for k, v in payload.items() if k != 'body'},
                index=i, payload_digest=digest(payload),
                body_deferred='body' in payload,
                original_path=['payloads', i] if 'payloads' in value else ['payload'])
                for i, payload in enumerate(outputs)], 'total': len(outputs), 'complete': True})
        return metadata, False
    if business_envelope(value):
        return {**value, 'envelope_representation': 'business-return-v1'}, True
    return value, True


def presentation(stored, ref, tool, status, source_material=None):
    try:
        value = json.loads(stored['text'])
    except ValueError:
        value = {'text': stored['text']}
    metadata, complete = public_value(tool, value)
    result = {'policy': POLICY, 'representation': 'exact-public-result-v2',
        'tool': tool, 'status': status, 'metadata': metadata,
        'observation_ref': ref, 'sha256': stored['sha256'],
        'stored_characters': len(stored['text']), 'complete_original_in_decision': complete,
        'exact_data_tool': 'read_tool_observation',
        'control_delivery_capacity': 'platform_managed_not_prevalidated',
        'note': 'Execution status is not semantic acceptance. Explicit reads are complete as returned, '
                'not proof of whole-source coverage. Authored bodies marked deferred are available '
                'by exact owned observation; text_work_id/output index permits unchanged adoption.'}
    if source_material:
        result['source_material'] = source_material
    return result


def offloaded_controls(presented):
    """Retain controls without undoing platform offload of declared data paths.

    The platform decides when to offload; this neither summarizes text nor
    chooses material for a task. Only these tool-specific paths are deferred;
    unknown shapes and reviewer outcomes remain exact, not recursively clipped.
    """
    metadata = presented['metadata']
    tool = presented['tool']
    if tool not in {'read_source_page', 'search_sources', 'read_context',
                    'read_content_selection', 'read_result', 'inspect_source_page'} or not isinstance(metadata, dict):
        return presented
    metadata = deepcopy(metadata)
    deferred = []

    def defer(container, field, path):
        if field in container:
            value = container[field]
            container[field] = {'platform_deferred': True, 'observation_path': path,
                'recovery': 'read_tool_observation: page the original JSON; field_path supports strings only.'}
            if isinstance(value, str):
                container[field]['field_path'] = path
            elif isinstance(value, dict) and isinstance(value.get('text'), str):
                container[field]['field_path'] = [*path, 'text']
            elif isinstance(value, list):
                container[field]['total_returned'] = len(value)
            deferred.append(path)

    if tool in {'read_source_page', 'search_sources'}:
        for field in ('blocks', 'matches'):
            if isinstance(metadata.get(field), list):
                values = metadata[field]
                metadata[field] = {'total_returned': len(values), 'bodies_deferred': True,
                    'entries': [{k: v for k, v in item.items() if k not in {'text', 'content'}}
                                for item in values]}
                deferred.append([field])
        for i, page in enumerate(metadata.get('source_table_views', [])):
            defer(page, 'tables', ['source_table_views', i, 'tables'])
    elif tool == 'inspect_source_page':
        defer(metadata, 'native_text', ['native_text'])
        for i, block in enumerate(metadata.get('frozen_text_blocks', [])):
            defer(block, 'text', ['frozen_text_blocks', i, 'text'])
        if isinstance(metadata.get('table_view'), dict):
            defer(metadata['table_view'], 'tables', ['table_view', 'tables'])
    elif tool == 'read_context' and business_envelope(metadata) and metadata['ok']:
        for i, obj in enumerate(metadata['result'].get('objects', [])):
            field = {'ContentNode': 'body', 'SourceArtifact': 'content'}.get(obj.get('ref', {}).get('type'))
            if field and isinstance(obj.get('payload'), dict):
                defer(obj['payload'], field, ['result', 'objects', i, 'payload', field])
    elif tool == 'read_content_selection' and business_envelope(metadata) and metadata['ok']:
        for i, item in enumerate(metadata['result'].get('selections', [])):
            if item.get('kind') == 'content_node_selection':
                defer(item, 'body', ['result', 'selections', i, 'body'])
    elif tool == 'read_result' and isinstance(metadata.get('body'), str):
        defer(metadata, 'body', ['body'])
    if not deferred:
        return presented
    return {**presented, 'metadata': metadata, 'complete_original_in_decision': False,
            'platform_offloaded_data_paths': deferred,
            'note': 'Platform offloaded data. Preserved receipts prove what the tool returned, '
                    'not proof that the decision model read the deferred content. '
                    'Recover the original using observation_ref and read_tool_observation.'}


def packet(workspace, role, message, tool_args=None):
    from .task_context import save_observation
    ref, stored = save_observation(workspace, role, message)
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    result = presentation(stored, ref, message.name, message.status, artifact.get('source_material'))
    workspace.store.event('decision_data_delivered', {'actor_id': stored['owner'], 'tool': message.name,
        'observation_ref': ref, 'stored_characters': len(message.content),
        'decision_characters': len(encode(result)),
        'complete_original_in_decision': result['complete_original_in_decision'],
        'representation': result['representation']})
    return result


class DeliveryBinding(Contract):
    representation: Literal['exact-public-result-v2'] = 'exact-public-result-v2'
    owner: str
    tool: str
    tool_call_id: str
    status: Literal['success', 'error']
    observation_ref: str
    sha256: str
    public_digest: str


def delivery_binding(workspace, role, message, presented):
    from .task_context import actor_id
    return DeliveryBinding(owner=actor_id(workspace, role), tool=message.name,
        tool_call_id=message.tool_call_id, status=message.status, observation_ref=presented['observation_ref'],
        sha256=presented['sha256'], public_digest=digest(presented)).model_dump()


def attach_delivery(workspace, role, message, presented):
    return message.model_copy(update={'content': encode(presented),
        'artifact': {**(message.artifact if isinstance(message.artifact, dict) else {}),
            'report_public_delivery': delivery_binding(workspace, role, message, presented)},
        'additional_kwargs': {**message.additional_kwargs,
            'report_observation_ref': presented['observation_ref'],
            'report_observation_delivery': {'representation': 'exact-public-result-v2',
                'complete_tool_result': presented['complete_original_in_decision'],
                'characters': len(encode(presented))}}})


def deliver_controls(workspace, role, message):
    """Final model-facing boundary, after native filesystem message eviction.

    Artifact is program-side identity, never proof of model visibility. Rebuild
    from the same immutable owned return, preserve the native notice and media.
    Old checkpoints without this binding retain their explicit compatibility path.
    """
    from langchain_core.messages import ToolMessage
    from pydantic import ValidationError
    from .task_context import actor_id
    if not isinstance(message, ToolMessage) or not isinstance(message.artifact, dict):
        return message
    binding = message.artifact.get('report_public_delivery')
    if binding is None:
        return message
    try:
        binding = DeliveryBinding.model_validate(binding)
    except ValidationError as exc:
        raise ActionRejected('PUBLIC_DELIVERY_BINDING_INVALID') from exc
    if (binding.owner != actor_id(workspace, role) or binding.tool != message.name
            or binding.tool_call_id != message.tool_call_id or message.status != binding.status):
        raise ActionRejected('PUBLIC_DELIVERY_OWNER_OR_CALL_MISMATCH')
    stored = workspace.store.get('tool_observation:' + binding.observation_ref)
    if (not stored or stored['owner'] != binding.owner or stored['tool'] != binding.tool
            or stored['sha256'] != binding.sha256
            or hashlib.sha256(stored['text'].encode('utf-8')).hexdigest() != binding.sha256
            or digest({'owner': binding.owner, 'tool': binding.tool, 'sha256': binding.sha256}) != binding.observation_ref):
        raise ActionRejected('PUBLIC_DELIVERY_ORIGINAL_CHANGED')
    source_material = message.artifact.get('source_material')
    if source_material:
        from .task_context import save_observation
        save_observation(workspace, role, message.model_copy(update={'content': stored['text']}))
    presented = presentation(stored, binding.observation_ref, message.name, message.status, source_material)
    if digest(presented) != binding.public_digest:
        raise ActionRejected('PUBLIC_DELIVERY_VIEW_CHANGED')
    if message.content == encode(presented):
        return message
    controls = offloaded_controls(presented)
    previous = message.additional_kwargs.get('report_platform_notice')
    if previous is not None and message.content == [
            *previous, {'type': 'text', 'text': encode(controls)}]:
        return message
    notice = message.content if isinstance(message.content, list) else [{'type': 'text', 'text': message.content}]
    return message.model_copy(update={'content': [*notice, {'type': 'text', 'text': encode(controls)}],
        'additional_kwargs': {**message.additional_kwargs, 'report_platform_notice': notice,
            'report_controls_restored': True,
            'report_observation_delivery': {'representation': 'exact-public-result-v2',
                'complete_tool_result': controls['complete_original_in_decision'],
                'characters': len(encode(controls))}}})


def refresh_producer_observation(workspace, role, message, *, _reference_policy=None):
    """Refresh an existing owned metadata message from its immutable original.

    This is a representation repair, not a new tool execution, evidence receipt,
    business decision or restoration of messages already absent from history.
    """
    import hashlib
    from langchain_core.messages import ToolMessage
    from .task_context import actor_id
    if (not isinstance(message, ToolMessage)
            or message.name != 'process_report_content' or message.status != 'success'
            or not isinstance(message.content, str)
            or message.additional_kwargs.get('report_observation_delivery', {}).get(
                'representation') != 'metadata_and_literal_fragments'):
        return message
    try:
        previous = json.loads(message.content)
        metadata = previous['metadata']
        if 'producer_observations_note' in metadata:
            return message
        if not (enabled(workspace) if _reference_policy is None else _reference_policy()):
            return message
        ref = previous['observation_ref']
        if (previous['policy'] != POLICY or previous['tool'] != message.name
                or previous['status'] != message.status
                or ref != message.additional_kwargs.get('report_observation_ref')):
            return message
        saved = workspace.store.get('tool_observation:' + ref)
        if not saved or saved['owner'] != actor_id(workspace, role) or saved['tool'] != message.name:
            return message
        sha = hashlib.sha256(saved['text'].encode('utf-8')).hexdigest()
        if (sha != saved['sha256'] or sha != previous['sha256']
                or ref != digest({'owner': saved['owner'], 'tool': saved['tool'], 'sha256': sha})):
            return message
        original = json.loads(saved['text'])
        receipt = workspace.store.get('text_work_receipt:' + original['text_work_id'])
        from .text_work import actor_for_tool
        actor = actor_for_tool(workspace, role)
        if (original.get('actor_id') != actor.id or original.get('task_id') != actor.task_id
                or not receipt or receipt['state'] != 'completed'
                or receipt['result'] != {k: v for k, v in original.items() if k != 'reused'}):
            return message
        if any(metadata.get(k) != original.get(k) for k in
               ('text_work_id', 'object_type', 'actor_id', 'task_id', 'state')):
            return message
        outputs = original.get('payloads', [original.get('payload', {})])
        identities = [{'index': i, 'kind': p.get('kind'), 'payload_digest': digest(p)}
                      for i, p in enumerate(outputs)]
        if (metadata.get('output_count') != len(outputs)
                or metadata['outputs'] != {'entries': identities, 'total': len(outputs), 'complete': True}):
            return message
    except (ValueError, TypeError, KeyError, AttributeError):
        return message
    refreshed = packet(workspace, role, message.model_copy(update={'content': saved['text']}))
    workspace.store.event('producer_observation_reprojected', {
        'actor_id': saved['owner'], 'observation_ref': ref, 'sha256': sha,
        'message_id': message.id, 'tool_call_id': message.tool_call_id,
        'before_digest': digest(previous), 'after_digest': digest(refreshed),
        'new_model_or_business_operation': False})
    return attach_delivery(workspace, role, message, refreshed)


def refresh_structural_observation(workspace, role, message, *, _reference_policy=None):
    """Repair structural projections from the same owned immutable public return."""
    import hashlib
    from langchain_core.messages import ToolMessage
    from .task_context import actor_id
    if (not isinstance(message, ToolMessage)
            or message.name not in TOOLS-{'process_report_content','read_content_selection'} or message.status != 'success'
            or not isinstance(message.content, str)
            or message.additional_kwargs.get('report_observation_delivery', {}).get(
                'representation') != 'metadata_and_literal_fragments'):
        return message
    try:
        previous = json.loads(message.content)
        if (previous['metadata'].get('envelope_representation') == 'business-return-v1'
                or (message.name == 'content_status' and
                    previous['metadata'].get('inventory_representation') == 'paged-object-index-v1')):
            return message
        metadata = previous['metadata']
        old_envelope_shape = (metadata == {} or {'ok','receipt_id'} <= metadata.keys()
            or (metadata.get('metadata_partial') is True and
                {'ok','result','receipt_id'} <= set(metadata.get('keys',[]))))
        if message.name != 'content_status' and not old_envelope_shape:
            return message  # No disk read for ordinary unchanged source projections.
        if not (enabled(workspace) if _reference_policy is None else _reference_policy()):
            return message
        ref = previous['observation_ref']
        if (previous['policy'] != POLICY or previous['tool'] != message.name
                or previous['status'] != message.status
                or ref != message.additional_kwargs.get('report_observation_ref')):
            return message
        saved = workspace.store.get('tool_observation:' + ref)
        if not saved or saved['owner'] != actor_id(workspace, role) or saved['tool'] != message.name:
            return message
        sha = hashlib.sha256(saved['text'].encode('utf-8')).hexdigest()
        if (sha != saved['sha256'] or sha != previous['sha256']
                or ref != digest({'owner': saved['owner'], 'tool': saved['tool'], 'sha256': sha})):
            return message
        original = json.loads(saved['text'])
        status_inventory = message.name == 'content_status' and isinstance(original.get('objects'),list)
        if not status_inventory and not business_envelope(original):
            return message
    except (ValueError, TypeError, KeyError, AttributeError):
        return message
    refreshed = packet(workspace, role, message.model_copy(update={'content': saved['text']}))
    workspace.store.event('status_observation_reprojected' if status_inventory else 'business_envelope_reprojected', {
        'actor_id': saved['owner'], 'observation_ref': ref, 'sha256': sha,
        'message_id': message.id, 'tool_call_id': message.tool_call_id,
        'before_digest': digest(previous), 'after_digest': digest(refreshed),
        'new_model_or_business_operation': False})
    return attach_delivery(workspace, role, message, refreshed)


refresh_status_observation = refresh_structural_observation


def refresh_history_observations(workspace, role, messages):
    """One current representation-policy read per synchronous history pass.

    Only relevant old observations request the policy. The local closure expires
    with this pass; it caches neither actor authority nor source/receipt validity.
    Standalone refresh calls still check current policy themselves.
    """
    from langchain_core.messages import ToolMessage
    from .selection_observations import refresh as refresh_selection
    routes = {name:refresh_structural_observation for name in TOOLS}
    routes.update({'process_report_content': refresh_producer_observation,
                   'read_content_selection': refresh_selection})
    policy = None

    def current_policy():
        nonlocal policy
        if policy is None:
            policy = enabled(workspace)
        return policy

    result = []
    for message in messages:
        repair = routes.get(message.name) if isinstance(message, ToolMessage) else None
        result.append(repair(workspace, role, message, _reference_policy=current_policy)
                      if repair else message)
    return result
