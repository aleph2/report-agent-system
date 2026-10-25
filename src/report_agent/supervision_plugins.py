"""Optional task-supervision implementations around the native delegation boundary.

Plugins receive the already-authorized task and its bound native invocation.
They cannot grant roles or artifact ownership. Business evidence exists separately.
"""
from dataclasses import dataclass
from typing import Protocol

from .errors import ActionRejected


class SupervisionPlugin(Protocol):
    id: str
    description: str
    requires_check_evidence: bool

    async def wrap_return(self, contents, actor, call, invoke): ...


@dataclass(frozen=True)
class SavedTaskChecks:
    id: str
    description: str
    requires_check_evidence: bool = False

    async def wrap_return(self, contents, actor, call, invoke):
        from .task_supervision import supervised_return
        return await supervised_return(contents, actor, call, invoke)


PLUGINS: dict[str, SupervisionPlugin] = {
    "task-checks-v1": SavedTaskChecks("task-checks-v1", "Saved checklist and actual required-read reconciliation; one completion follow-up; preserve remaining work."),
    "task-checks-evidence-v2": SavedTaskChecks("task-checks-evidence-v2", "Per-check results linked to actual observations, separate outside-task notes; one completion follow-up. Evidence links do not prove semantic depth.", True),
}


def resolve_plugin(plugin_id):
    if plugin_id is None:
        return None
    if plugin_id not in PLUGINS:
        raise ActionRejected("UNKNOWN_SUPERVISION_PLUGIN")
    return PLUGINS[plugin_id]


def selected_plugin(contract):
    # Historical tasks predate optional selection; preserve their actual policy.
    # New tasks explicitly save None when no plugin was selected.
    plugin_id = contract.get("supervision_plugin", "task-checks-v1") if contract.get("review_requirements") else None
    return resolve_plugin(plugin_id)


def plugin_catalog():
    return {"optional": True, "default": None,
            "plugins": [{"id": p.id, "description": p.description,
                         "requires_check_evidence": p.requires_check_evidence} for p in PLUGINS.values()],
            "limitation": "Selection changes supervision behavior, not permissions, standards or evidence of correctness. Existing tasks retain their selected policy."}


async def delegated_return(contents, actor, call, invoke):
    from .task_supervision import assignment
    task = assignment(contents, actor.task_id)
    plugin = selected_plugin(task)
    v4 = task.get('review_interface_profile') == 'review-interfaces-v4'
    reservation = 'native_delegation:'+call['id']
    if v4:
        from .store import encode, digest
        request = digest({'actor': actor.__dict__, 'call': call})
        with contents.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT value FROM state WHERE key=?', (reservation,)).fetchone()
            if previous:
                raise ActionRejected('NATIVE_DELEGATION_OUTCOME_UNRESOLVED: original native intent already reserved; recover its native checkpoint/result before any continuation')
            db.execute('INSERT INTO state VALUES (?,?)', (reservation, encode({
                'task_id': actor.task_id, 'native_tool_call_id': call['id'],
                'request_digest': request, 'state': 'reserved'})))
            db.execute("INSERT INTO events(kind,data) VALUES ('native_delegation_reserved',?)",
                       (encode({'task_id': actor.task_id, 'native_tool_call_id': call['id'], 'request_digest': request}),))
    result = await invoke(call) if plugin is None else await plugin.wrap_return(contents, actor, call, invoke)
    if v4:
        # The native graph owns Command/checkpoint serialization; never serialize a second copy.
        try:
            contents.store.set(reservation, {'task_id': actor.task_id, 'native_tool_call_id': call['id'],
                'request_digest': request, 'state': 'returned', 'recovery': 'original_native_checkpoint_only'})
        except Exception:
            pass  # A failed audit update must not discard a completed native result or retry it.
    return result
