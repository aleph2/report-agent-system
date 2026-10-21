"""Task authorization around native delegation, with no custom execution loop."""
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import Field, create_model

from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected


_binding = ContextVar("content_task_binding", default=None)
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


def task_tool(tool):
    """Extend only the coordinator-facing native schema, not the native executor."""
    from .content_models import Ref
    from .task_supervision import ReviewRequirement
    schema = create_model("ContentTaskToolSchema", __base__=tool.args_schema,
        review_snapshot_ref=(Ref | None, Field(default=None,
            description="Reviewer assignment's exact version-bound snapshot. Required with review_requirements.")),
        review_requirements=(list[ReviewRequirement] | None, Field(default=None,
            description="Explicit review outcomes: exact target/criterion, scope_id, required_checks and optional whole-body read refs. For bounded-tool review, declare required_materials for every check: refs require exact local object payloads; source_spans require exact version-bound original text blocks. Both lists empty means unresolved. material_refs and top-level source_ranges are additional eligible pools, not substitutes for required dependencies. Use content_check_scopes to declare needed local or full contains-subtree bodies; bind needed descendants to this scope's material pool. Containers do not stand for child bodies. Task data fixes single/cross-node scope; these are not acceptance judgments or per-node call limits.")),
        supervision_plugin=(str | None, Field(default=None,
            description="Optional server-registered reviewer supervision plugin. Omit for no supervision on new tasks; use list_supervision_plugins to inspect choices. Resumed tasks retain their existing selection.")),
        layout_snapshot_ref=(Ref | None, Field(default=None,
            description="For a layout task, grant presentation-only export access to this exact coordinator-owned snapshot. Required on new layout tasks.")),
        resume_content_task_id=(str | None, Field(default=None,
            description="Existing server-issued content task ID to continue its owned work; omit for a new independent task.")))
    return tool.model_copy(update={"args_schema": schema,
        "description": tool.description + "\nContent tasks have persistent owners. Use resume_content_task_id to ask the original producer to revise its saved work; new tasks cannot overwrite it."})


@contextmanager
def delegated_task(workspace, caller_role, call):
    if caller_role != "coordinator":
        raise ActionForbidden("FORBIDDEN: delegation authority")
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
                           if i['kind'] in {'undeclared', 'oversized_source'}), None)
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
