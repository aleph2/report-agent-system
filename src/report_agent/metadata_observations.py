"""Retain exact ranges of verified identity-only write receipts, not report prose."""
import hashlib
import json

from langchain_core.messages import AIMessage, ToolMessage

from .content_models import Ref
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


def identity_receipt(workspace, owner, ref):
    saved = workspace.store.get('tool_observation:' + ref)
    if not saved or saved['owner'] != owner or saved['tool'] != 'commit_objects':
        return None
    sha = hashlib.sha256(saved['text'].encode('utf-8')).hexdigest()
    if saved['sha256'] != sha or ref != digest({'owner': owner, 'tool': saved['tool'], 'sha256': sha}):
        return None
    try:
        original = json.loads(saved['text'])
        if (set(original) != {'ok', 'result', 'receipt_id'} or original['ok'] is not True
                or set(original['result']) != {'refs'} or not isinstance(original['result']['refs'], dict)
                or not isinstance(original['receipt_id'], str) or len(original['receipt_id']) > 256):
            return None
        for key, value in original['result']['refs'].items():
            if (not isinstance(key, str) or len(key) > 120
                    or not isinstance(value, dict) or set(value) != {'type', 'id', 'version'}
                    or len(value['type']) > 60 or len(value['id']) > 128):
                return None
            Ref.model_validate(value)
        with workspace.store.connect() as db:
            row = db.execute('SELECT actor_id,response FROM content_operations WHERE operation_id=?',
                             (original['receipt_id'],)).fetchone()
        if not row or row[0] != owner or json.loads(row[1]) != original:
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return saved


def retain_identity_ranges(workspace, role, messages):
    """Restore only already-returned, provable ranges; keep one copy of each.

    Native message identities and call pairing remain unchanged. Unverified
    material retains the ordinary recovery policy. No source read or review is
    created by this presentation repair.
    """
    from .task_context import actor_id, read_observation
    owner, cache, verified = actor_id(workspace, role), {}, []
    calls = {c['id']: c for m in messages if isinstance(m, AIMessage) for c in m.tool_calls}
    for i, message in enumerate(messages):
        if (not isinstance(message, ToolMessage) or message.status != 'success'
                or message.name != 'read_tool_observation' or not isinstance(message.content, str)):
            continue
        try:
            packet = json.loads(message.content)
            # This retention rule is for raw identity-receipt ranges only.
            # A field-local cursor must never be restored as a raw JSON cursor.
            if (packet.get('field_path') is not None
                    or message.additional_kwargs.get('report_observation_delivery',{}).get('field_path') is not None
                    or calls.get(message.tool_call_id,{}).get('args',{}).get('field_path') is not None):
                continue
            ref = packet['observation_ref']
            if message.additional_kwargs.get('report_observation_ref') != ref:
                continue
            if ref not in cache:
                cache[ref] = identity_receipt(workspace, owner, ref)
            saved = cache[ref]
            if not saved or packet['sha256'] != saved['sha256']:
                continue
            was_cleared = message.additional_kwargs.get('report_preview_cleared', False)
            delivery = message.additional_kwargs['report_observation_delivery']
            if was_cleared:
                prior = packet['previously_presented_range']
                if prior != delivery:
                    continue
                start, end = prior['offset'], prior['end']
            else:
                start, end = packet['offset'], packet['end']
            if (type(start) is not int or type(end) is not int
                    or not 0 <= start <= end <= len(saved['text']) or end - start > 6000
                    or (start == end and end != len(saved['text']))):
                continue
            call = calls.get(message.tool_call_id, {})
            args = call.get('args', {})
            length = args.get('characters', 6000)
            if (call.get('name') != 'read_tool_observation' or args.get('observation_ref') != ref
                    or type(length) is not int or not 1 <= length <= 6000
                    or args.get('offset', 0) != start or min(start + length, len(saved['text'])) != end):
                continue
            exact = read_observation(workspace, role, ref, start, max(1, end - start))
            if not was_cleared and any(packet.get(k) != exact[k] for k in ('sha256', 'text', 'offset', 'end')):
                continue
            verified.append((i, (ref, saved['sha256'], start, end), exact, was_cleared))
        except (ValueError, TypeError, KeyError, AttributeError, ActionForbidden, ActionRejected):
            continue
    latest = {key: i for i, key, _, _ in verified}
    result = list(messages)
    changes = []
    for i, key, exact, was_cleared in verified:
        message = messages[i]
        delivery = {'representation': 'exact_owned_metadata_range', 'offset': key[2], 'end': key[3],
                    'characters': len(exact['text']), 'complete_tool_result': exact['complete_tool_result']}
        kwargs = {**message.additional_kwargs, 'report_observation_delivery': delivery}
        if i == latest[key]:
            kwargs.pop('report_preview_cleared', None)
            value = exact
        else:
            kwargs['report_preview_cleared'] = True
            value = {k: v for k, v in exact.items() if k not in {'text', 'offset', 'end', 'next_offset', 'complete_tool_result'}}
            value.update(preview_cleared=True, previously_presented_range=delivery,
                         duplicate_metadata_range=True,
                         retained_tool_call_id=messages[latest[key]].tool_call_id,
                         note='Same verified identity receipt range is retained once at the named tool call. '
                              'The original and call pairing remain; saving identities is not semantic review.')
        changed = message.model_copy(update={'content': encode(value), 'additional_kwargs': kwargs})
        if changed.model_dump() != message.model_dump():
            result[i] = changed
            changes.append({'tool_call_id': message.tool_call_id, 'observation_ref': key[0],
                            'sha256': key[1], 'range': [key[2], key[3]],
                            'restored': bool(was_cleared and i == latest[key]),
                            'duplicate': i != latest[key]})
    if changes:
        workspace.store.event('identity_metadata_ranges_represented', {
            'actor_id': owner, 'ranges': changes, 'new_model_or_business_operation': False})
    return result
