"""Request-bound flat business messages; existing task/save validators stay authoritative."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import inspect
import json
from typing import Annotated
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from .errors import ActionRejected
from .store import digest, encode

CHECK_TOOL = 'submit_review'
_MODEL = ContextVar('flat_message_model_offer', default=None)
_TOOL = ContextVar('flat_message_tool_binding', default=None)


def enabled(store):
    from .handoff_release import manifest
    value = manifest(store)
    return value.get('content_contract') == 'hierarchical-review-v1' and value.get('review_interface_profile') == 'review-interfaces-v4'


def _owner(ws, actor):
    return [str(ws.store.root.resolve()), actor.id, actor.task_id]


def _once(store, key, value):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        if row is not None and json.loads(row[0]) != value:
            raise ActionRejected('MESSAGE_CONTRACT_BINDING_CONFLICT')
        db.execute('INSERT OR IGNORE INTO state(key,value) VALUES (?,?)', (key, encode(value)))


def review_tool(ws, actor, contents, identity):
    """Expose the current flat contract, with no alternative model-facing save format."""
    from .review_message import ReviewMessage, save_review_message
    def submit_review(**kwargs):
        operation = kwargs.pop('operation_id')
        who = actor()
        binding = current_review_binding(ws, who)
        if binding is None:
            raise ActionRejected('MESSAGE_CONTRACT_BINDING_REQUIRED')
        return save_review_message(contents, who, operation, binding, kwargs, runtime_identity=identity)
    submit_review.__doc__ = (
        'Save one assigned check using the supplied field dictionary and actual-read receipt directory. '
        'The program binds exact identities and assembles the stored ReviewRecord. '
        'Optional business fields preserve actual findings, outside-assignment notes and object coverage. '
        'Omitting a finding is not a declaration that no defect exists. '
        'Saving neither approves the report nor triggers another agent.')
    fields = ReviewMessage.model_fields
    annotations = {'operation_id': str, 'return': dict,
        **{name: Annotated[field.annotation, field] for name, field in fields.items()}}
    submit_review.__annotations__ = annotations
    submit_review.message_model = ReviewMessage
    submit_review.__signature__ = inspect.Signature([
        inspect.Parameter('operation_id', inspect.Parameter.KEYWORD_ONLY, annotation=str),
        *[inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=annotations[name],
            default=inspect.Parameter.empty if field.is_required() else field.default)
          for name, field in fields.items()]], return_annotation=dict)
    return submit_review


def _label(record, resources=None):
    payload = record['payload']
    name = next((payload[k] for k in ('title', 'name', 'purpose', 'goal', 'body')
                 if isinstance(payload.get(k), str) and payload[k]), '')
    if not name and isinstance(payload.get('body'), dict):
        name = next((payload['body'][k] for k in ('title', 'text')
                     if isinstance(payload['body'].get(k), str)), '')
    result = {'object_type': record['ref']['type'], 'version': record['ref']['version'],
            'kind': payload.get('kind'), 'label_preview': name[:160], 'label_characters': len(name),
            **({'format': payload['file_ref'].rsplit('.', 1)[-1]} if 'file_ref' in payload else {})}
    if resources is not None:
        result['material_scope'] = resources.setdefault(digest(record['ref']), 'm' + str(len(resources)))
    return result


def _receipt_label(contents, value, resources=None, *, actor=None):
    """Index metadata only. Original observations remain in history/authorized read tools."""
    if value.get('native_source_material_receipt'):
        if actor is None:
            raise ActionRejected('MESSAGE_CONTRACT_SOURCE_OWNER_REQUIRED')
        from .review_message import verified_source_observation
        record = verified_source_observation(contents, actor, value)
        materials = []
        for material in record['materials']:
            label = _receipt_label(contents, {'source_id': material['source_id'],
                'source_digest': material['source_payload_digest'], 'kind': material['kind'],
                'coverage': material['coverage'],
                'limitations': material.get('limitations', [])}, resources)
            materials.append({**label, 'selection': deepcopy(material['selection']),
                'source_versions': [ref['version'] for ref in material['source_version_refs']],
                'source_coverage': material['source_coverage'],
                'source_limitations': material['source_limitations']})
        return {'read_kind': 'source_material', 'tool': record['tool'],
                **{k:value[k] for k in ('ok', 'status', 'execution_state') if k in value},
                'materials': materials}
    if isinstance(value.get('objects'), list):
        return {'read_kind': 'objects', 'objects': [_label(o, resources) for o in value['objects']],
                **{k:value[k] for k in ('total', 'next_offset') if k in value}}
    if value.get('export_ref'):
        return {'read_kind': 'export', 'export': _label(contents.read(value['export_ref']), resources),
                'text_characters': len(value.get('text', '')),
                'limitation': value.get('limitation', '')}
    source = value.get('source') or {}
    source_id = value.get('source_id') or source.get('source_id')
    source_label = {}
    if source_id:
        metadata = next((s for s in contents.store.source_catalog() if s['id'] == source_id), {})
        name = next((metadata[k] for k in ('name', 'title', 'file_name', 'path')
                     if isinstance(metadata.get(k), str) and metadata[k]), 'Source material')
        source_label['source_name'] = name.replace('\\', '/').rsplit('/', 1)[-1]
        if resources is not None:
            identity = digest(['source', source_id, value.get('source_digest') or source.get('source_sha256')])
            source_label['material_scope'] = resources.setdefault(identity, 'm' + str(len(resources)))
    return {'read_kind': value.get('kind', 'observation'), 'status': value.get('status'), **source_label,
            **{k:source[k] for k in ('kind', 'page', 'coverage') if k in source},
            **{k:value[k] for k in ('range', 'total', 'next_offset', 'coverage', 'limitations') if k in value},
            'observation_characters': len(value.get('observation', ''))}


def prepare_request(ws, role, request):
    if not enabled(ws.store):
        return request, None
    if role == 'coordinator':
        return _co_request(ws, request)
    if role != 'reviewer':
        return request, None
    from .content_tasks import qualitative_review_active
    if qualitative_review_active():
        return request, None
    from .content_store import ContentStore
    from .content_tasks import bound_actor
    from .review_message import bind_review_message
    actor = bound_actor(ws, role, None)
    contents = ContentStore(ws.store)
    task = contents.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    scopes = task.get('review_requirements') or []
    eligible = bool(scopes) and all(len(s['required_checks']) == 1 for s in scopes)
    tools = request.tools
    if not eligible:
        raise ActionRejected('REVIEW_MESSAGE_REQUIRES_SINGLE_CHECK_PER_SCOPE')
    if not any(getattr(t, 'name', None) == CHECK_TOOL for t in tools):
        raise ActionRejected('REVIEW_MESSAGE_TOOL_NOT_REGISTERED')
    with ws.store.connect() as db:
        receipts = [r[0] for r in db.execute(
            'SELECT id FROM content_observations WHERE actor_id=? ORDER BY rowid', (actor.id,))]
    binding = bind_review_message(contents, actor, receipts)
    scope_packet, resources = [], {}
    for index, scope in enumerate(scopes):
        criterion = contents.read(scope['criterion_ref'])['payload']
        scope_packet.append({'assigned_scope_index': index, 'required_checks': scope['required_checks'],
            'assessment_kind': scope.get('assessment_kind', 'content'),
            'target': _label(contents.read(scope['target_ref']), resources),
            'artifacts': [_label(contents.read(ref), resources) for ref in scope.get('artifact_refs', [])],
            'criterion': {k: criterion[k] for k in (
                'purpose', 'scope', 'expected_outcome', 'evidence_expectation', 'allowed_limits')},
            'artifact_extents': [{k:v for k,v in extent.items() if k != 'artifact_ref'}
                                 for extent in scope.get('artifact_check_scopes', [])],
            'body_extents': [{k:v for k,v in extent.items() if k != 'node_ref'}
                             for extent in scope.get('content_check_scopes', [])]})
    labels = [digest({k:v for k,v in s.items() if k != 'assigned_scope_index'}) for s in scope_packet]
    if len(set(labels)) != len(labels):
        raise ActionRejected('REVIEW_MESSAGE_SCOPE_LABELS_AMBIGUOUS')
    directory = []
    with ws.store.connect() as db:
        for index, entry in enumerate(binding['receipts']):
            value = json.loads(db.execute('SELECT data FROM content_observations WHERE id=?',
                                         (entry['receipt_id'],)).fetchone()[0])
            directory.append({'evidence_index': index, 'read': _receipt_label(contents, value, resources, actor=actor)})
    coverage = [{'object_index': i, **_label(contents.read(ref), resources)}
                for i, ref in enumerate(binding['coverage_refs'])]
    packet = {'tool': CHECK_TOOL, 'field_dictionary': 'Types, requirements and descriptions are in this tool schema.',
        'assigned_scopes': scope_packet, 'actual_read_receipts': directory,
        'coverage_objects': coverage,
        'meaning': 'Evidence indexes follow this task actual-read order, starting at zero. '
                   'material_scope short references identify exact materials within THIS request only; '
                   'the same short reference in the scope and receipt directories means the same exact material. '
                   'Labels may be abbreviated; use the original observations/authorized read tools for full content. '
                   'Actual previous reads only; presence is not verification. Choose the actual check and judgment.'}
    public = convert_to_openai_tool(next(t for t in tools if getattr(t, 'name', None) == CHECK_TOOL))
    from .prompt_provenance import append_declared_system
    changed = append_declared_system(request.override(tools=tools), encode(packet),
                                     'field_dictionary/current_request')
    offer = {'kind': 'reviewer', 'owner': _owner(ws, actor), 'binding': binding, 'packet': packet,
             'function': public['function'],
             'nonce': uuid4().hex}
    return changed, offer


def _co_request(ws, request):
    from .content_store import ContentStore
    from .hierarchical_tools import actor_for
    contents, actor = ContentStore(ws.store), actor_for('coordinator')
    tool = next((t for t in request.tools if getattr(t, 'name', None) == 'task'), None)
    if tool is None:
        return request, None
    records = [r for r in contents.list_objects() if r['ref']['type'] in {
        'DocumentSnapshot', 'ContentNode', 'Criterion', 'ExportArtifact', 'RenderArtifact', 'DelegatedTask'}]
    resources = [{'scope': 's'+str(i), 'resource': r['ref'], 'sha256': digest(r)}
                 for i, r in enumerate(records)]
    refs = {digest(e['resource']): e['scope'] for e in resources}
    public_resources = []
    for entry, record in zip(resources, records):
        item = {'scope': entry['scope'], **_label(record)}
        payload = record['payload']
        if record['ref']['type'] == 'DocumentSnapshot':
            item['document'] = _label(contents.read(payload['root_ref']))
        if record['ref']['type'] == 'Criterion':
            item['criterion'] = {k:payload[k] for k in (
                'purpose', 'scope', 'expected_outcome', 'evidence_expectation', 'allowed_limits')}
        if payload.get('snapshot_ref'):
            item['snapshot_scope'] = refs.get(digest(payload['snapshot_ref']))
        if record['ref']['type'] == 'DelegatedTask':
            item.update(role=payload['role'], goal=payload.get('goal', ''))
        elif record.get('task_id'):
            owner_scope = refs.get(digest({'type': 'DelegatedTask', 'id': record['task_id'], 'version': 1}))
            if owner_scope is not None:
                item['owner_task_scope'] = owner_scope
        public_resources.append(item)
    packet = {'tool': 'task',
        'field_dictionary': 'Types, requirements and conditional business choices are in the task schema.',
        'resource_scopes': public_resources,
        'meaning': 'Short scopes bind exact saved versions in THIS request. Availability grants no extra '
                   'ownership or access. To revise owned work, select its owner_task_scope as resume_task_scope; '
                   'a new task of the same role is a different owner. Select the actual task and full commission basis; '
                   'the program assembles and stores that selection without guessing a review result.'}
    function = convert_to_openai_tool(tool)['function']
    from .prompt_provenance import append_declared_system
    changed = append_declared_system(request, encode(packet), 'field_dictionary/current_request')
    offer = {'kind': 'coordinator', 'owner': _owner(ws, actor), 'resources': resources,
        'packet': packet, 'function': function,
        'nonce': uuid4().hex}
    return changed, offer


def _assemble_task(ws, actor, offer, call):
    from .co_review_message import CoTaskMessage
    from .message_fields import validate_message
    from .content_store import ContentStore
    value = validate_message(CoTaskMessage, call['args'])
    contents = ContentStore(ws.store)
    directory = {e['scope']:e for e in offer['resources']}
    def selected(scope, kinds):
        entry = directory.get(scope)
        if not entry or entry['resource']['type'] not in kinds:
            raise ActionRejected('TASK_RESOURCE_SCOPE_INVALID', diagnostic={
                'scope':scope, 'allowed_scopes':[k for k,e in directory.items() if e['resource']['type'] in kinds]})
        if digest(contents.read(entry['resource'])) != entry['sha256']:
            raise ActionRejected('TASK_RESOURCE_CHANGED')
        return deepcopy(entry['resource'])
    def selection(scopes, kinds):
        if len(set(scopes)) != len(scopes):
            raise ActionRejected('TASK_RESOURCE_SCOPES_MUST_BE_DISTINCT')
        return [selected(s, kinds) for s in scopes]
    args = {'description': value.description, 'subagent_type': value.subagent_type}
    if 'section_ids' in value.model_fields_set:
        args['section_ids'] = value.section_ids
    if value.assessment_object_id is not None:
        args['assessment_object_id'] = value.assessment_object_id
    if value.resume_task_scope is not None:
        args['resume_content_task_id'] = selected(value.resume_task_scope, {'DelegatedTask'})['id']
    elif value.subagent_type == 'layout':
        args['layout_snapshot_ref'] = selected(value.snapshot_scope, {'DocumentSnapshot'})
    elif value.subagent_type == 'reviewer':
        snapshot = selected(value.snapshot_scope, {'DocumentSnapshot'})
        basis = selection(value.commission_criterion_scopes, {'Criterion'})
        criteria = (selection(value.criterion_scopes, {'Criterion'})
                    if 'criterion_scopes' in value.model_fields_set else basis)
        if any(ref not in basis for ref in criteria):
            raise ActionRejected('TASK_CHECK_OUTSIDE_COMMISSION_BASIS')
        scope = {'kind': 'whole_content'}
        if value.review_scope == 'targeted':
            target = selected(value.target_scope, {'DocumentSnapshot', 'ContentNode'})
            kind = value.assessment_kind
            artifacts = selection(value.artifact_scopes, {'ExportArtifact'} if kind == 'export' else {'RenderArtifact'})
            scope = {'kind':'mapped', 'items':[{'criterion_ref': ref, 'target_ref': target,
                'assessment_kind': kind, 'artifact_refs': artifacts} for ref in criteria]}
            if value.content_extent is not None:
                if target['type'] != 'ContentNode':
                    raise ActionRejected('CONTENT_EXTENT_REQUIRES_NODE_TARGET')
                for item in scope['items']:
                    item['extent'] = value.content_extent
            if value.artifact_pages:
                for item in scope['items']:
                    item['extent'] = {'kind':'render_pages', 'artifact_ref': artifacts[0],
                                      'pages': value.artifact_pages, 'requirement_index': 0}
        args['review'] = {'deliverable': {'kind':'snapshot', 'snapshot_ref': snapshot},
            'standards': {'kind':'criteria', 'criterion_refs': basis}, 'scope':scope}
        if value.supervision_plugin is not None:
            args['supervision_plugin'] = value.supervision_plugin
    return {**call, 'args':args}


@contextmanager
def model_offer(offer):
    token = _MODEL.set(offer)
    try:
        yield
    finally:
        _MODEL.reset(token)


def semantic_messages(payload):
    from .task_state_delivery import observation_semantics
    messages = deepcopy(payload.get('messages', []))
    for message in messages:
        message.pop('id', None)
    if messages:
        messages[-1] = observation_semantics(messages[-1])
    return messages


def wire_messages(messages, converted=None):
    """Use the SDK projection and preserve the adapter's exact replay fields."""
    if converted is None:
        from langchain_openai.chat_models.base import (
            _convert_from_v1_to_chat_completions, _convert_message_to_dict)
        converted = [_convert_message_to_dict(
                         _convert_from_v1_to_chat_completions(m) if isinstance(m, AIMessage) else m)
                     for m in messages]
    converted = deepcopy(converted)
    for message, wire in zip(messages, converted, strict=True):
        if isinstance(message, AIMessage) and 'strict_wire' in message.additional_kwargs:
            wire['tool_calls'] = deepcopy(message.additional_kwargs['strict_wire']['tool_calls'])
            if not wire['tool_calls']:
                wire.pop('tool_calls')
        if isinstance(message, AIMessage) and 'reasoning_content' in message.additional_kwargs:
            reasoning = message.additional_kwargs['reasoning_content']
            if not isinstance(reasoning, str):
                raise ValueError('UNSUPPORTED_GLM_REASONING_FIELD')
            wire['reasoning_content'] = reasoning
    return converted


def finalize_offer(store, request, call):
    """Bind the assembled request once; local nonce never changes wire identity."""
    offer = _MODEL.get()
    if offer is None:
        return
    from .prompt_provenance import _refuse
    if 'prompt_call_id' in offer or offer['owner'][0] != str(store.root.resolve()):
        _refuse('MESSAGE_CONTRACT_OFFER_REUSED', 'final_request_boundary')
    messages = wire_messages([request.system_message, *request.messages])
    functions = [convert_to_openai_tool(t)['function'] for t in request.tools]
    selected = [f for f in functions if f['name'] == offer['function']['name']]
    if len(selected) != 1:
        _refuse('MESSAGE_CONTRACT_TOOL_UNAVAILABLE', 'final_request_boundary')
    offer.update(function=selected[0], prompt_call_id=call['call_id'],
                 request_messages_digest=digest(semantic_messages({'messages': messages})))
    _once(store, 'message_offer:' + digest(offer), offer)


def validate_wire(payload, *, strict):
    offer = _MODEL.get()
    if offer is None:
        return
    expected = offer['function']
    if strict:
        from .deepseek_strict import StrictCodec
        expected = StrictCodec(expected).function
    actual = [t['function'] for t in payload.get('tools', [])
              if t.get('function', {}).get('name') == offer['function']['name']]
    from .prompt_provenance import _CALL, _refuse
    call = _CALL.get()
    try:
        matched = digest(semantic_messages(payload)) == offer.get('request_messages_digest')
    except (ValueError, TypeError, KeyError, AttributeError):
        matched = False
    if (actual != [expected] or not matched or call is None
            or call['call_id'] != offer.get('prompt_call_id')):
        _refuse('MESSAGE_CONTRACT_WIRE_MISMATCH', 'adapter_before_serialization')


def bind_response(ws, offer, response):
    if offer is None:
        return
    if 'prompt_call_id' not in offer:
        for answer in response.result:
            if not isinstance(answer, AIMessage):
                continue
            calls = [c for c in answer.tool_calls if c['name'] in {CHECK_TOOL, 'task'}]
            if not calls:
                continue
            key = answer.additional_kwargs.get('report_tool_selection_offer')
            proof = ws.store.get(key) if isinstance(key, str) and key.startswith('tool_selection_offer:') else None
            # Proven omissions must reach reject_unoffered, without acquiring a binding.
            if not (offer['owner'][0] == str(ws.store.root.resolve())
                    and isinstance(proof, dict)
                    and proof.get('actor_id') == offer['owner'][1]
                    and proof.get('task_id') == offer['owner'][2]
                    and proof.get('calls_digest') == digest(answer.tool_calls)
                    and isinstance(proof.get('names'), list)
                    and all(c['name'] not in proof['names'] for c in calls)):
                raise ActionRejected('MESSAGE_CONTRACT_OFFER_UNAVAILABLE')
        return
    ref = 'message_offer:' + digest(offer)
    if ws.store.get(ref) != offer:
        raise ActionRejected('MESSAGE_CONTRACT_OFFER_UNAVAILABLE')
    for answer in response.result:
        if not isinstance(answer, AIMessage):
            continue
        for call in answer.tool_calls:
            if not (call['name'] == CHECK_TOOL or (offer['kind'] == 'coordinator'
                    and call['name'] == 'task')):
                continue
            link = {'offer': ref, 'owner': offer['owner'], 'message': answer.id,
                    'call_id': call['id'], 'args_digest': digest(call['args'])}
            _once(ws.store, 'message_call:' + digest([offer['owner'], call['id']]), link)
        answer.additional_kwargs['message_contract_offer'] = ref


@contextmanager
def tool_binding(ws, role, request):
    token = None
    try:
        call = request.tool_call
        flat_co = call['name'] == 'task' and role == 'coordinator' and enabled(ws.store)
        if (call['name'] == CHECK_TOOL and enabled(ws.store)) or flat_co:
            if role not in {'reviewer', 'coordinator'} or not enabled(ws.store):
                raise ActionRejected('MESSAGE_CONTRACT_NOT_ENABLED')
            from .text_work import actor_for_tool
            actor = actor_for_tool(ws, role)
            owner = _owner(ws, actor)
            link = ws.store.get('message_call:' + digest([owner, call['id']]))
            messages = request.state.get('messages', [])
            answers = [m for m in messages if isinstance(m, AIMessage)
                       and any(c['id'] == call['id'] for c in m.tool_calls)]
            if (not link or link['owner'] != owner or link['call_id'] != call['id'] or link['args_digest'] != digest(call['args'])
                    or len(answers) != 1 or answers[0].id != link['message']
                    or not any(c['id'] == call['id'] and c['name'] == call['name']
                               and digest(c['args']) == digest(call['args']) for c in answers[0].tool_calls)
                    or answers[0].additional_kwargs.get('message_contract_offer') != link['offer']):
                raise ActionRejected('MESSAGE_CONTRACT_CALL_UNBOUND')
            offer = ws.store.get(link['offer'])
            if not offer or link['offer'] != 'message_offer:' + digest(offer) or offer['owner'] != owner:
                raise ActionRejected('MESSAGE_CONTRACT_OFFER_UNAVAILABLE')
            if flat_co:
                if offer['kind'] != 'coordinator' or role != 'coordinator':
                    raise ActionRejected('MESSAGE_CONTRACT_BINDING_CHANGED')
                request = request.override(tool_call=_assemble_task(ws, actor, offer, call))
            else:
                if offer['kind'] != 'reviewer' or role != 'reviewer':
                    raise ActionRejected('MESSAGE_CONTRACT_BINDING_CHANGED')
                token = _TOOL.set((owner, offer['binding']))
        yield request
    finally:
        if token is not None:
            _TOOL.reset(token)


def current_review_binding(ws, actor):
    bound = _TOOL.get()
    if bound is None:
        return None
    if bound[0] != _owner(ws, actor):
        raise ActionRejected('MESSAGE_CONTRACT_BINDING_CHANGED')
    return bound[1]
