"""Bounded exact selection/receipt metadata; never a semantic review or new read."""
import hashlib
import json

from .store import digest, encode

REPRESENTATION = 'selected-content-receipt-v1'


def verified_selection_return(db, owner, observation_ref, text, sha256):
    """Recover only the exact owned public return backed by a real read receipt."""
    from .errors import ActionRejected
    try:
        row = db.execute('SELECT value FROM state WHERE key=?',
                         ('tool_observation:' + observation_ref,)).fetchone()
        saved = json.loads(row[0]) if row else None
        sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if (not saved or saved['owner'] != owner or saved['tool'] != 'read_content_selection'
                or saved['text'] != text or saved['sha256'] != sha256 or sha != sha256
                or observation_ref != digest({'owner':owner, 'tool':'read_content_selection', 'sha256':sha})):
            raise ValueError('unverified public return')
        original = json.loads(text)
        if metadata(original) is None:
            raise ValueError('not a successful selection return')
        row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                         (original['receipt_id'],)).fetchone()
        if not row or row[0] != owner or json.loads(row[1]) != original['result']:
            raise ValueError('read receipt mismatch')
        return original['result']
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ActionRejected('TEXT_WORK_SELECTION_OBSERVATION_UNVERIFIED') from exc


def metadata(value, maximum=4700):
    if (not isinstance(value, dict) or value.get('ok') is not True
            or not isinstance(value.get('receipt_id'), str)
            or not isinstance(value.get('result'), dict)):
        return None
    data = value['result']
    items = data.get('selections')
    if not isinstance(items, list) or not isinstance(data.get('snapshot_ref'), dict):
        return None
    result = {'selection_representation': REPRESENTATION,
        'receipt_id': value['receipt_id'], 'snapshot_ref': data['snapshot_ref'],
        'selection_count': len(items), 'selections': [], 'complete_selection_metadata': False,
        'next_selection_index': 0, 'body_and_qualifiers_deferred': True,
        'exact_return_path': 'result.selections',
        'recovery_note': 'next_selection_index is an array index, not a character offset. Recover the exact owned return using read_tool_observation(observation_ref, offset=0), then its returned next_offset; no new content read receipt is needed.',
        'scope_note': 'Actual saved read receipt, not semantic acceptance. Only selected ranges were read; no implicit descendants or sources. Complete body selection does not mean completed review. Full bodies and qualifications remain in the exact owned return.'}
    manifests = {item.get('manifest_digest') for item in items if isinstance(item, dict)}
    if len(manifests) == 1 and isinstance(next(iter(manifests)), str):
        result['manifest_digest'] = next(iter(manifests))
    if len(encode(result)) > maximum:
        return {'selection_representation': REPRESENTATION, 'selection_count': len(items),
            'complete_selection_metadata': False, 'identities_deferred': True,
            'note': 'Exact identities exceed this metadata envelope; recover the owned original. IDs are never shortened.'}
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get('selection'), dict):
            break
        selection = item['selection']
        entry = {'index': index, 'ref': selection.get('ref'), 'unit': selection.get('unit'),
            'requested_offset': selection.get('offset'), 'requested_limit': selection.get('limit'),
            **{key: item[key] for key in ('selected_range', 'total_units', 'next_offset',
                'complete_body_selection', 'node_kind', 'claim_kind') if key in item},
            'qualifier_fields': len(item['qualifiers']) if isinstance(item.get('qualifiers'), dict) else None}
        result['selections'].append(entry)
        result['next_selection_index'] = index + 1
        if len(encode(result)) > maximum:
            result['selections'].pop()
            result['next_selection_index'] = index
            break
    result['complete_selection_metadata'] = len(result['selections']) == len(items)
    if result['complete_selection_metadata']:
        result['next_selection_index'] = None
    # Final completeness/null markers can be slightly longer than the in-loop
    # partial markers. Enforce the envelope after their actual serialization.
    while len(encode(result)) > maximum and result['selections']:
        result['selections'].pop()
        result['complete_selection_metadata'] = False
        result['next_selection_index'] = len(result['selections'])
    if len(encode(result)) > maximum:
        return {'selection_representation': REPRESENTATION, 'selection_count': len(items),
            'complete_selection_metadata': False, 'identities_deferred': True,
            'note': 'Exact identities exceed this metadata envelope; recover the owned original. IDs are never shortened.'}
    return result


def refresh(workspace, role, message, *, _reference_policy=None):
    """Reproject an existing same-owner receipt; preserve the original message IDs."""
    from langchain_core.messages import ToolMessage
    from .decision_data import POLICY, enabled, packet, attach_delivery
    from .task_context import actor_id
    if (not isinstance(message, ToolMessage)
            or message.name != 'read_content_selection' or message.status != 'success'
            or not isinstance(message.content, str)
            or message.additional_kwargs.get('report_observation_delivery', {}).get(
                'representation') != 'metadata_and_literal_fragments'):
        return message
    try:
        previous = json.loads(message.content)
        if previous['metadata'].get('selection_representation') == REPRESENTATION:
            return message
        if not (enabled(workspace) if _reference_policy is None else _reference_policy()):
            return message
        ref = previous['observation_ref']
        if (previous['policy'] != POLICY or previous['tool'] != message.name
                or previous['status'] != message.status
                or ref != message.additional_kwargs.get('report_observation_ref')):
            return message
        saved = workspace.store.get('tool_observation:' + ref)
        owner = actor_id(workspace, role)
        if not saved or saved['owner'] != owner or saved['tool'] != message.name:
            return message
        sha = hashlib.sha256(saved['text'].encode('utf-8')).hexdigest()
        if (sha != saved['sha256'] or sha != previous['sha256']
                or ref != digest({'owner': owner, 'tool': message.name, 'sha256': sha})):
            return message
        original = json.loads(saved['text'])
        if metadata(original) is None:
            return message
        with workspace.store.connect() as db:
            row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                (original['receipt_id'],)).fetchone()
        if not row or row[0] != owner or json.loads(row[1]) != original['result']:
            return message
    except (ValueError, TypeError, KeyError, AttributeError):
        return message
    refreshed = packet(workspace, role, message.model_copy(update={'content': saved['text']}))
    workspace.store.event('selection_observation_reprojected', {
        'actor_id': owner, 'observation_ref': ref, 'sha256': sha,
        'receipt_id': original['receipt_id'], 'message_id': message.id,
        'tool_call_id': message.tool_call_id, 'before_digest': digest(previous),
        'after_digest': digest(refreshed), 'new_model_or_business_operation': False})
    return attach_delivery(workspace, role, message, refreshed)
