"""Task authorization around native delegation, with no custom execution loop."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from pydantic import Field, create_model

from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .prompt_sources import BOUNDED_REVIEW, NATIVE_REVIEW, load_prompt


_binding = ContextVar("content_task_binding", default=None)


def model_owner_identity(store):
    """Read-only identity for transport recovery; grants no task permissions."""
    binding = _binding.get()
    if binding is None:
        return None
    root, actor, invocation = binding
    if root != str(store.root.resolve()):
        raise ActionForbidden('FORBIDDEN: model recovery workspace binding')
    return {'actor': actor.__dict__, 'invocation': invocation}
ASSIGNMENT_NOTE = (
    "assignment is the immutable initial contract, including original goal and permissions. "
    "current_invocation is the instruction for this actual call; it may revise the action "
    "requested by the original goal, but cannot expand permissions or change saved review scopes."
)


def normalize_review_requirements(requirements):
    from .task_supervision import ReviewRequirement
    values = [ReviewRequirement.model_validate(r).model_dump() for r in requirements]
    for value in values:
        for material in value['required_materials']:
            if not material['source_spans']:
                material.pop('source_spans')
            else:
                for span in material['source_spans']:
                    if span['table_detail'] is None:
                        span.pop('table_detail')
        # New optional fields must not alter a legacy task's replay identity.
        for key in ("material_refs", "required_materials", "source_ranges", "presentation_reference_ref",
                    "artifact_check_scopes", "reference_page_bindings", "content_check_scopes"):
            if not value[key]:
                value.pop(key)
    return values


def bound_actor(workspace, role, fallback):
    if role not in {"writer", "reviewer", "layout"}:
        return fallback
    binding = _binding.get()
    if not binding or binding[0] != str(workspace.store.root.resolve()) or binding[1].role != role:
        raise ActionForbidden("FORBIDDEN: delegated task binding required")
    return binding[1]


def _invocation(call):
    import hashlib
    description = call["args"].get("description", "")
    return {"delegate_operation_id": "delegate:" + call["id"],
            "description": description,
            "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest()}


def current_invocation(workspace, actor):
    """Read the actual call only within its validated workspace/actor binding."""
    if bound_actor(workspace, actor.role, None) != actor:
        raise ActionForbidden("FORBIDDEN: invocation task binding")
    return dict(_binding.get()[2])


def attach_saved_reference_metadata(contents, parent, task_ref, result, call_id):
    """Enrich the native return without changing its channels or child outcome."""
    from dataclasses import replace
    from langchain_core.messages import ToolMessage
    from langgraph.types import Command
    from .store import encode

    def enrich(message):
        if not isinstance(message, ToolMessage) or message.tool_call_id != call_id:
            return message
        artifact = message.artifact
        if artifact is not None and not isinstance(artifact, dict):
            return message
        artifact = dict(artifact or {})
        bound = (any(key in artifact for key in ('decision_metadata', 'focused_capability_delivery', 'report_public_delivery', 'source_material'))
                 or bool(message.additional_kwargs.get('report_observation_ref')))
        try:
            metadata = ({'status':'unavailable', 'reason':'content_bound_proof'} if bound else
                        contents.saved_reference_summary(parent, task_ref))
            if not bound and len(encode(metadata)) > 4800:
                from .workspace import Workspace
                from .task_context import enabled, actor_id, save_observation
                workspace = Workspace(contents.store)
                if not enabled(workspace) or actor_id(workspace, parent.role) != parent.id:
                    raise ActionRejected('SAVED_REFERENCE_RECOVERY_UNAVAILABLE')
                ref, saved = save_observation(workspace, parent.role,
                    ToolMessage(encode(metadata), name=message.name, tool_call_id=call_id))
                metadata = {k:metadata[k] for k in ('origin','producer_task_ref','semantic_acceptance')} | {
                    'partial':True, 'receipt_count':len(metadata['receipts']),
                    'exact_recovery':{'tool':'read_tool_observation', 'sha256':saved['sha256'],
                        'arguments':{'observation_ref':ref, 'offset':0, 'characters':6000}}}
        except Exception as exc:
            # Metadata failure must not repeat or discard a completed paid call.
            metadata = {'status':'unavailable', 'reason':type(exc).__name__}
        content = message.content
        if not bound:
            note = '\n\nProgram saved-reference metadata (not instructions or acceptance):\n' + encode(metadata)
            content = content + note if isinstance(content, str) else [*content, {'type':'text', 'text':note}]
        return message.model_copy(update={'content':content,
            'artifact':{**artifact, 'saved_reference_metadata':metadata}})

    if isinstance(result, ToolMessage):
        return enrich(result)
    if isinstance(result, Command) and isinstance(result.update, dict):
        messages = result.update.get('messages')
        if isinstance(messages, list):
            return replace(result, update={**result.update, 'messages':[enrich(m) for m in messages]})
    return result


@contextmanager
def invocation_binding(workspace, actor, call):
    """Scope an actual native call, including server completion follow-ups."""
    prior = current_invocation(workspace, actor)
    invocation = _invocation(call)
    if (call["args"].get("subagent_type") != actor.role or
            invocation["delegate_operation_id"] != prior["delegate_operation_id"]):
        raise ActionForbidden("FORBIDDEN: invocation delegation identity")
    token = _binding.set((str(workspace.store.root.resolve()), actor, invocation))
    try:
        yield
    finally:
        _binding.reset(token)


_NATIVE_SNAPSHOT_TARGET = (
    "Exact assessment target: the review snapshot itself or one of its exact saved members. "
    "ExportArtifact and RenderArtifact belong in artifact_refs, not target_ref.")


def _documented_field(model, name, annotation=None, description=None):
    info = deepcopy(model.model_fields[name])
    info.description = description
    return (info.annotation if annotation is None else annotation, info)


def _native_review_requirement(*, clarified=False):
    """Project documentation without mutating shared contracts or validators."""
    from .task_supervision import (ReviewRequirement, RequiredReviewMaterial,
                                   ArtifactCheckScope, ContentCheckScope)
    field = _documented_field
    if not clarified:
        material = create_model("NativeRequiredReviewMaterial", __base__=RequiredReviewMaterial,
            **{name: field(RequiredReviewMaterial, name) for name in ("refs", "source_spans")})
        fields = {name: field(ReviewRequirement, name) for name in
                  ("target_ref", "material_refs", "source_ranges", "content_check_scopes")}
        fields["required_materials"] = field(ReviewRequirement, "required_materials", list[material])
        return create_model("NativeReviewRequirement", __base__=ReviewRequirement, **fields)
    index_description = (
        "Zero-based index into required_checks of this ReviewRequirement, not the outer "
        "review_requirements position; must be less than len(required_checks).")
    material = create_model("NativeRequiredReviewMaterial", __base__=RequiredReviewMaterial,
        **{name: field(RequiredReviewMaterial, name) for name in ("refs", "source_spans")},
        requirement_index=field(RequiredReviewMaterial, "requirement_index", description=index_description))
    artifact_scope = create_model("NativeArtifactCheckScope", __base__=ArtifactCheckScope,
        requirement_index=field(ArtifactCheckScope, "requirement_index", description=index_description))
    content_scope = create_model("NativeContentCheckScope", __base__=ContentCheckScope,
        requirement_index=field(ContentCheckScope, "requirement_index", description=index_description))
    fields = {name: field(ReviewRequirement, name) for name in
              ("material_refs", "source_ranges")}
    fields["target_ref"] = field(ReviewRequirement, "target_ref", description=_NATIVE_SNAPSHOT_TARGET)
    fields["required_materials"] = field(ReviewRequirement, "required_materials", list[material])
    fields["content_check_scopes"] = field(ReviewRequirement, "content_check_scopes", list[content_scope],
        "Optional declared content extents. The same local check may name different nodes; "
        "the (requirement_index, exact node_ref) pair must be unique. Declared versions and "
        "permissions remain binding. Omission does not establish that any body was read or verified.")
    fields["artifact_check_scopes"] = field(ReviewRequirement, "artifact_check_scopes", list[artifact_scope],
        "Optional per-check artifact extents; at most one explicit extent per local required_checks "
        "index in this ReviewRequirement. Export structure needs the actual export read; render "
        "checks need the listed full pages. For a check comparing multiple assigned artifacts, "
        "omit its explicit extent to retain full assigned artifact coverage. Omission never "
        "removes required_checks, exact versions, permissions or whole-item completion duties.")
    return create_model("NativeReviewRequirement", __base__=ReviewRequirement, **fields)


def native_review_submission_schema(*, v4=False, scope_selectors=False):
    """Native tool documentation only; preserve the original save validators."""
    from .content_models import ReviewSubmission, ReviewItem, CheckResult, Finding
    field = _documented_field
    index = ("Zero-based index into required_checks of the saved scope matching this ReviewItem, "
             "not an outer items or review_requirements position.")
    observations = ("Zero-based indexes into this ReviewItem.observations, "
                    "not another item's observations or outer items.")
    check = create_model("NativeCheckResult", __base__=CheckResult,
        requirement_index=field(CheckResult, "requirement_index", description=index),
        observation_indexes=field(CheckResult, "observation_indexes", description=observations))
    finding = create_model("NativeFinding", __base__=Finding,
        requirement_index=field(Finding, "requirement_index", description=index),
        observation_indexes=field(Finding, "observation_indexes", description=observations))
    item = create_model("NativeReviewItem", __base__=ReviewItem,
        **({'scope_id': (str, Field(min_length=1,
            description='Required exact server-assigned scope_id from the current saved assignment; never invent one.'))} if v4 else {}),
        target_ref=field(ReviewItem, "target_ref", description=_NATIVE_SNAPSHOT_TARGET),
        check_results=field(ReviewItem, "check_results", list[check] | None),
        findings=field(ReviewItem, "findings", list[finding]))
    if scope_selectors:
        if not v4:
            raise ActionRejected('REVIEW_SUBMISSION_SELECTORS_REQUIRE_NATIVE_V4')
        from .content_models import Contract
        from .review_scope_selectors import IDENTITY_FIELDS
        fields = {name: field(item, name, description=info.description)
                  for name, info in item.model_fields.items() if name not in IDENTITY_FIELDS}
        fields['checked_requirement_indexes'] = field(ReviewItem, 'checked_requirement_indexes',
            description='Zero-based indexes of actually performed required_checks within the selected assigned scope, not outer scope indexes.')
        item = create_model('NativeReviewScopeItem', __base__=Contract, **fields,
            assigned_scope_index=(int, Field(ge=0, strict=True,
                description="Zero-based index into this current task's full saved review_requirements; the program binds its exact target_ref, criterion_ref, scope_id and assessment_kind. Free-text scope remains model-supplied.")))
    return create_model("NativeReviewSubmission", __base__=ReviewSubmission,
        target_ref=field(ReviewSubmission, "target_ref", description=_NATIVE_SNAPSHOT_TARGET),
        items=field(ReviewSubmission, "items", list[item]))


def task_tool(tool, *, review_profile=BOUNDED_REVIEW, interface_profile='review-interfaces-v1',
              subagent_descriptions=(), prompt_profile='legacy-v1'):
    """Extend only the coordinator-facing native schema, not the native executor."""
    if interface_profile == 'review-interfaces-v4':
        if review_profile != NATIVE_REVIEW:
            raise ActionRejected('REVIEW_INTERFACE_PROFILE_REQUIRES_NATIVE_HIERARCHICAL')
        from .review_binding import ReviewSelection
        from .content_models import Ref
        from .prompt_sources import report_rule_source
        schema = create_model('MinimalContentTaskToolSchema', __base__=tool.args_schema,
            description=_documented_field(tool.args_schema, 'description',
                description=load_prompt(report_rule_source('native-task-description-v4', prompt_profile)).strip()),
            review=(ReviewSelection | None, Field(default=None,
                description='Reviewer only: choose the saved deliverable, complete acceptance-standard basis and current scope. The program binds versions; Reviewer plans and verifies.')),
            supervision_plugin=(str | None, Field(default=None, description='Optional existing reviewer supervision plugin.')),
            layout_snapshot_ref=(Ref | None, Field(default=None, description='Exact saved snapshot presentation grant, layout only.')),
            resume_content_task_id=(str | None, Field(default=None, description='Saved task to continue within unchanged permissions.')))
        descriptions = '\n\n'.join(f'- {name}: {description}' for name, description in subagent_descriptions)
        return tool.model_copy(update={'args_schema': schema,
            'description': load_prompt(report_rule_source('native-review-handoff-v4', prompt_profile)).strip()+'\n\n'+descriptions})
    if review_profile not in {BOUNDED_REVIEW, NATIVE_REVIEW}:
        raise ActionRejected("UNKNOWN_REVIEW_EXECUTION_PROFILE")
    from .prompt_sources import REVIEW_INTERFACE_V1, REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3, review_handoff_source
    if interface_profile not in {REVIEW_INTERFACE_V1, REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3}:
        raise ActionRejected('UNKNOWN_REVIEW_INTERFACE_PROFILE')
    if interface_profile in {REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3} and review_profile != NATIVE_REVIEW:
        raise ActionRejected('REVIEW_INTERFACE_PROFILE_REQUIRES_NATIVE_HIERARCHICAL')
    from .content_models import Ref
    from .task_supervision import ReviewRequirement
    schema = create_model("ContentTaskToolSchema", __base__=tool.args_schema,
        review_snapshot_ref=(Ref | None, Field(default=None,
            description="Reviewer assignment's exact version-bound snapshot. Required with review_requirements. This is a version anchor; bounded content target_ref must be a ContentNode, not this DocumentSnapshot.")),
        review_requirements=(list[ReviewRequirement] | None, Field(default=None,
            description="Explicit review outcomes: exact target/criterion, scope_id, required_checks and optional whole-body read refs. For bounded-tool review, declare required_materials for every check: refs require exact local object payloads; source_spans require exact version-bound original text blocks. Both lists empty means unresolved. material_refs and top-level source_ranges are additional eligible pools, not substitutes for required dependencies. Use content_check_scopes to declare needed local or full contains-subtree bodies; bind needed descendants to this scope's material pool. Containers do not stand for child bodies. Task data fixes single/cross-node scope; these are not acceptance judgments or per-node call limits.")),
        supervision_plugin=(str | None, Field(default=None,
            description="Optional server-registered reviewer supervision plugin. Omit for no supervision on new tasks; use list_supervision_plugins to inspect choices. Resumed tasks retain their existing selection.")),
        layout_snapshot_ref=(Ref | None, Field(default=None,
            description="For a layout task, grant presentation-only export access to this exact coordinator-owned snapshot. Required on new layout tasks.")),
        resume_content_task_id=(str | None, Field(default=None,
            description="Existing server-issued content task ID to continue its owned work; omit for a new independent task.")))
    description = tool.description + "\nContent tasks have persistent owners. Use resume_content_task_id to ask the original producer to revise its saved work; new tasks cannot overwrite it."
    if review_profile == NATIVE_REVIEW:
        snapshot = deepcopy(schema.model_fields["review_snapshot_ref"])
        requirements = deepcopy(schema.model_fields["review_requirements"])
        snapshot.description = requirements.description = None
        schema = create_model("NativeContentTaskToolSchema", __base__=schema,
            review_snapshot_ref=(snapshot.annotation, snapshot),
            review_requirements=(list[_native_review_requirement(clarified=interface_profile in {REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3})] | None, requirements))
        description = load_prompt(review_handoff_source(interface_profile)).strip() + "\n\n" + description
    return tool.model_copy(update={"args_schema": schema, "description": description})


@contextmanager
def delegated_task(workspace, caller_role, call):
    if caller_role != "coordinator":
        raise ActionForbidden("FORBIDDEN: delegation authority")
    from .prompt_sources import review_interface_profile
    if review_interface_profile(workspace.store) == 'review-interfaces-v4':
        with _v4_task(workspace, call) as bound:
            yield bound
        return
    args = dict(call["args"])
    resumed = args.pop("resume_content_task_id", None)
    review_snapshot = args.pop("review_snapshot_ref", None)
    requirements = args.pop("review_requirements", None)
    selection_supplied = args.get("supervision_plugin") is not None
    supervision_plugin = args.pop("supervision_plugin", None)
    from .supervision_plugins import resolve_plugin
    resolve_plugin(supervision_plugin)
    if hasattr(review_snapshot, "model_dump"):
        review_snapshot = review_snapshot.model_dump()
    if requirements is not None:
        from .task_supervision import ReviewRequirement
        from pydantic import ValidationError
        try:
            requirements = normalize_review_requirements(requirements)
        except ValidationError as exc:
            raise ActionRejected("INVALID_REVIEW_REQUIREMENTS: " + str(exc)) from exc
    layout_snapshot = args.pop("layout_snapshot_ref", None)
    if hasattr(layout_snapshot, "model_dump"):
        layout_snapshot = layout_snapshot.model_dump()
    role = args.get("subagent_type")
    if supervision_plugin is not None and role != "reviewer":
        raise ActionRejected("SUPERVISION_PLUGIN_REQUIRES_REVIEWER")
    if role not in {"writer", "reviewer", "layout"} or not call.get("id"):
        raise ActionRejected("INVALID_CONTENT_DELEGATION")
    from .hierarchical_tools import actor_for
    cs, coordinator = ContentStore(workspace.store), actor_for("coordinator")
    if requirements is not None or review_snapshot is not None:
        from .task_supervision import validate_requirements
        if role != "reviewer" or not review_snapshot:
            raise ActionRejected("REVIEW_CONTRACT_REQUIRES_REVIEWER_AND_SNAPSHOT")
        readiness = validate_requirements(cs, review_snapshot, requirements)
        impossible = next((i for i in readiness['issues']
                           if i['kind'] in {'undeclared', 'capability', 'unbound_body'}), None)
        if (not resumed and workspace.store.manifest.get('review_execution_mode') == 'bounded-tool-v1'
                and impossible is not None
                and cs.receipt(coordinator, 'delegate:' + call['id'])['state'] == 'unknown'):
            from .store import encode
            raise ActionRejected(impossible['code'] + ': ' + encode(readiness))
    def register(db):
        if resumed:
            record = cs._read(db, {"type": "DelegatedTask", "id": resumed, "version": 1})
            if record["owner_id"] != coordinator.id or record["payload"]["role"] != role:
                raise ActionForbidden("FORBIDDEN: task resumption scope")
            if selection_supplied and supervision_plugin != record["payload"].get("supervision_plugin", "task-checks-v1"):
                raise ActionForbidden("FORBIDDEN: changed supervision plugin requires new task")
            if layout_snapshot and record["payload"].get("layout_snapshot_ref") != layout_snapshot:
                raise ActionForbidden("FORBIDDEN: changed layout grant requires new task")
            prior_requirements = record["payload"].get("review_requirements")
            if prior_requirements:
                from .task_supervision import ReviewRequirement
                prior_requirements = normalize_review_requirements(prior_requirements)
            if ((requirements is not None and requirements != prior_requirements) or
                    (review_snapshot is not None and review_snapshot != record["payload"].get("review_snapshot_ref"))):
                raise ActionForbidden("FORBIDDEN: changed review assignment requires new task")
            return {"task_ref": record["ref"]}
        if role == "layout":
            if not layout_snapshot or layout_snapshot.get("type") != "DocumentSnapshot":
                raise ActionRejected("LAYOUT_SNAPSHOT_REQUIRED")
            snapshot = cs._read(db, layout_snapshot)
            if snapshot["owner_id"] != coordinator.id:
                raise ActionForbidden("FORBIDDEN: layout snapshot grant owner")
        task_ref = cs._insert(db, coordinator, "DelegatedTask", {
            "role": role, "goal": args.get("description", ""),
            **({"review_snapshot_ref": review_snapshot, "review_requirements": requirements} if requirements else {}),
            **({"supervision_plugin": supervision_plugin} if role == "reviewer" else {}),
            **({"layout_snapshot_ref": layout_snapshot} if role == "layout" else {}),
            "write_scope": "Only artifacts produced by this task; read other project artifacts.",
            "delegated_by": coordinator.id})
        if policy_ref:
            from .store import encode
            db.execute('INSERT INTO state VALUES (?,?)',
                ('source_use_task_binding:' + task_ref['id'], encode(policy_ref)))
        return {"task_ref": task_ref}
    request = {"native_task": args, "resume": resumed}
    if selection_supplied or not resumed:
        request["supervision_plugin"] = supervision_plugin
    if requirements is not None:
        request.update(review_requirements=requirements, review_snapshot_ref=review_snapshot)
    if layout_snapshot:
        request["layout_snapshot_ref"] = layout_snapshot
    from .source_use import report_binding
    from .store import digest
    prior = cs.receipt(coordinator, 'delegate:' + call['id'])
    # A saved legacy operation must keep its old request identity. A failed
    # operation has no task sidecar: compare the original request digest too.
    if resumed:
        policy_ref = workspace.store.get('source_use_task_binding:' + resumed)
    elif prior['state'] == 'known_success':
        prior_task = prior['response']['result']['task_ref']['id']
        policy_ref = workspace.store.get('source_use_task_binding:' + prior_task)
    else:
        policy_ref = report_binding(workspace.store)
    if policy_ref:
        bound_request = {**request, 'source_use_policy_ref': policy_ref}
        if prior['state'] != 'unknown' and prior['request_digest'] == digest({'actor': coordinator.__dict__, 'request': request}):
            policy_ref = None
        else:
            request = bound_request
    saved = cs.operation(coordinator, "delegate:" + call["id"], request, register)
    task_id = saved["result"]["task_ref"]["id"]
    actor = Actor("content:" + role + ":" + task_id, role, task_id)
    payload = cs.read(saved["result"]["task_ref"])["payload"]
    if payload.get("review_requirements"):
        from .store import encode
        args["description"] = args.get("description", "") + "\nSaved review assignment (account for these exact scopes; reading alone is not checking):\n" + encode({
            "review_snapshot_ref": payload["review_snapshot_ref"], "review_requirements": payload["review_requirements"]})
        from .supervision_plugins import selected_plugin
        plugin = selected_plugin(payload)
        if plugin and plugin.requires_check_evidence:
            args["description"] += "\nSelected supervision plugin requires check_results for each required check: requirement_index, actual execution_state, result, observation_indexes into this item's actual observations, and remaining reason for unfinished checks. Outside-assignment notes belong in outside_assignment_notes, never cancel assigned work. Linked evidence is not proof of correctness."
    native_call = {**call, "args": args}
    token = _binding.set((str(workspace.store.root.resolve()), actor, _invocation(native_call)))
    try:
        yield native_call, actor
    finally:
        _binding.reset(token)


@contextmanager
def _v4_task(workspace, call):
    """Register business bindings atomically before entering the native executor."""
    from uuid import uuid4
    from .hierarchical_tools import actor_for
    from .review_binding import bind, identity, canonical_selection
    from .source_use import report_binding
    args = deepcopy(call['args'])
    review = canonical_selection(args.pop('review', None))
    resumed = args.pop('resume_content_task_id', None)
    layout = args.pop('layout_snapshot_ref', None)
    plugin = args.pop('supervision_plugin', None)
    from .supervision_plugins import resolve_plugin
    resolve_plugin(plugin)
    role = args.get('subagent_type')
    if role not in {'writer', 'reviewer', 'layout'} or not call.get('id'):
        raise ActionRejected('INVALID_CONTENT_DELEGATION')
    if 'review_snapshot_ref' in args or 'review_requirements' in args:
        raise ActionRejected('V4_REQUIRES_BUSINESS_REVIEW_SELECTION')
    if (review is not None and role != 'reviewer') or (plugin is not None and role != 'reviewer'):
        raise ActionRejected('REVIEW_CONTRACT_REQUIRES_REVIEWER_AND_SNAPSHOT')
    cs, co = ContentStore(workspace.store), actor_for('coordinator')
    def register(db):
        if resumed:
            saved = cs._read(db, {'type': 'DelegatedTask', 'id': resumed, 'version': 1})
            payload = saved['payload']
            if saved['owner_id'] != co.id or payload['role'] != role:
                raise ActionForbidden('FORBIDDEN: task resumption scope')
            if ((review is not None and review != payload.get('review_selection'))
                    or (layout is not None and layout != payload.get('layout_snapshot_ref'))
                    or (plugin is not None and plugin != payload.get('supervision_plugin'))):
                raise ActionForbidden('FORBIDDEN: changed assignment requires new task')
            return {'task_ref': saved['ref']}
        task_id = str(uuid4())
        payload = {'role': role, 'goal': args.get('description', ''), 'delegated_by': co.id,
            'write_scope': 'Only artifacts produced by this task; read other project artifacts.',
            'review_interface_profile': 'review-interfaces-v4'}
        from .handoff_release import manifest
        from .prompt_instructions import instruction_context
        payload['commission_origin'] = {k:manifest(workspace.store).get(k) for k in ('goal','scope_instruction')}
        from .handoff_release import release
        payload['handoff_release_digest'] = release(manifest(workspace.store))['digest']
        payload['scoped_instructions'] = instruction_context(workspace.store, role, task_id=task_id, db=db)
        if role == 'reviewer':
            if manifest(workspace.store).get('review_submission_contract') is not None:
                payload['review_submission_contract'] = manifest(workspace.store)['review_submission_contract']
            if manifest(workspace.store).get('review_plan_contract') is not None:
                payload['review_plan_contract'] = manifest(workspace.store)['review_plan_contract']
            if review is None:
                raise ActionRejected('REVIEW_SELECTION_REQUIRED')
            payload.update(bind(cs, db, co, review, 'delegate:'+call['id'], task_id))
            payload['supervision_plugin'] = plugin
        if role == 'layout':
            from .deliverables import export_allowed
            if layout is None:
                raise ActionRejected('LAYOUT_SNAPSHOT_REQUIRED')
            snapshot = cs._read(db, layout)
            if not export_allowed(cs, db, co, snapshot):
                raise ActionForbidden('FORBIDDEN: layout snapshot parent')
            payload['layout_snapshot_ref'] = layout
        from .deliverables import source_authority
        from .store import encode
        import json
        source_authority(cs, db, co, [])
        policy_row = db.execute("SELECT value FROM state WHERE key='source_use_authority_binding'").fetchone()
        policy = json.loads(policy_row[0]) if policy_row else None
        if policy:
            from .store import encode
            payload['source_use_policy_ref'] = policy
            db.execute('INSERT INTO state VALUES (?,?)', ('source_use_task_binding:'+task_id, encode(policy)))
        return {'task_ref': cs._insert(db, co, 'DelegatedTask', payload, id=task_id)}
    raw = {'native_task': args, 'resume': resumed, 'review': review,
           'layout_snapshot_ref': layout, 'supervision_plugin': plugin}
    saved = cs.operation(co, 'delegate:'+call['id'], raw, register,
        binding_identity=lambda db, result: identity(cs, db, co, result))
    task_ref = saved['result']['task_ref']
    actor = Actor('content:'+role+':'+task_ref['id'], role, task_ref['id'])
    native_call = {**call, 'args': args}
    token = _binding.set((str(workspace.store.root.resolve()), actor, _invocation(native_call)))
    try:
        yield native_call, actor
    finally:
        _binding.reset(token)
