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
    plugin = selected_plugin(assignment(contents, actor.task_id))
    if plugin is None:
        return await invoke(call)
    return await plugin.wrap_return(contents, actor, call, invoke)
