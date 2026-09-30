"""Task authorization around native delegation, with no custom execution loop."""
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import Field, create_model

from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected


_binding = ContextVar("content_task_binding", default=None)


def bound_actor(workspace, role, fallback):
    if role not in {"writer", "reviewer"}:
        return fallback
    binding = _binding.get()
    if not binding or binding[0] != str(workspace.store.root.resolve()) or binding[1].role != role:
        raise ActionForbidden("FORBIDDEN: delegated task binding required")
    return binding[1]


def task_tool(tool):
    """Extend only the coordinator-facing native schema, not the native executor."""
    schema = create_model("ContentTaskToolSchema", __base__=tool.args_schema,
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
    role = args.get("subagent_type")
    if role not in {"writer", "reviewer"} or not call.get("id"):
        raise ActionRejected("INVALID_CONTENT_DELEGATION")
    from .hierarchical_tools import actor_for
    cs, coordinator = ContentStore(workspace.store), actor_for("coordinator")
    def register(db):
        if resumed:
            record = cs._read(db, {"type": "DelegatedTask", "id": resumed, "version": 1})
            if record["owner_id"] != coordinator.id or record["payload"]["role"] != role:
                raise ActionForbidden("FORBIDDEN: task resumption scope")
            return {"task_ref": record["ref"]}
        return {"task_ref": cs._insert(db, coordinator, "DelegatedTask", {
            "role": role, "goal": args.get("description", ""),
            "write_scope": "Only artifacts produced by this task; read other project artifacts.",
            "delegated_by": coordinator.id})}
    saved = cs.operation(coordinator, "delegate:" + call["id"], {"native_task": args, "resume": resumed}, register)
    task_id = saved["result"]["task_ref"]["id"]
    actor = Actor("content:" + role + ":" + task_id, role, task_id)
    token = _binding.set((str(workspace.store.root.resolve()), actor))
    try:
        yield {**call, "args": args}, actor
    finally:
        _binding.reset(token)
