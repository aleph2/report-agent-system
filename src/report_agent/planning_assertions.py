"""Coordinator planning actions backed by case-local, host-issued assertion grants."""
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from langchain.tools import ToolRuntime
from langchain_core.tools import InjectedToolArg
from pydantic import Field

from . import assertions, plan_inputs
from . import plan_authority
from .assertion_host import AssertionHost, Grant
from .content_tasks import model_owner_identity
from .content_models import Contract
from .errors import ActionForbidden, ActionRejected
from .source_use import _commission, source_version_material, validate_source_versions
from .store import digest


def _issuer(cs, actor, subject):
    from .hierarchical_tools import actor_for
    if actor != actor_for('coordinator') or model_owner_identity(cs.store) is not None:
        raise ActionForbidden('PLANNING_ASSERTION_COORDINATOR_REQUIRED')
    with cs.store.connect() as db:
        draft = plan_inputs.get_draft(db, {})
        if subject not in draft.get('items', {}).get('object', {}):
            ref = plan_authority.plan_ref(db)
            if not ref or not any(o['object_id'] == subject for o in cs._read(db, ref)['payload']['objects']):
                raise ActionForbidden('PLANNING_ASSERTION_INVENTORY_SUBJECT_REQUIRED')
    return str(uuid5(NAMESPACE_URL, actor.id))


def _source_ids(host, principal, actor, subject):
    return host.commission.produced_ids(actor=principal, task=actor.task_id, subject=subject, kind='source')


def read_source_index(cs, actor, subject, page, page_size, view_ref, *, bindings=False):
    principal = _issuer(cs, actor, subject)
    if bindings:
        from .commission_plan import read_plan
        from .page_bindings import records
        plan = read_plan(cs.store)
        rows = [dict(id=r["id"], status=state["status"], **r["claim"]["page_binding"])
                for r,state in records(cs.store,plan["ref"],subject) if r["claim"]["kind"] == "convention"] if plan else []
        ids = sorted(rows, key=lambda r:r["id"])
    else:
        ids = sorted(_source_ids(AssertionHost(cs.store.root), principal, actor, subject))
    current = digest([subject, ids])
    if (view_ref and view_ref != current) or (page > 1 and not view_ref):
        raise ActionRejected('PLANNING_SOURCE_INDEX_VIEW_CHANGED_OR_REQUIRED')
    if page > max(1, (len(ids) + page_size - 1) // page_size):
        raise ActionRejected('PLANNING_SOURCE_INDEX_PAGE_OUT_OF_RANGE')
    end = page * page_size
    return dict(subject=subject, **{("page_bindings" if bindings else "source_assertion_ids"): ids[end-page_size:end]}, total=len(ids),
                view_ref=current, next_page=page + 1 if end < len(ids) else None)


# ToolRuntime remains optional for direct calls, and absent from the model-facing schema.
NativeRuntime = Annotated[ToolRuntime | None, InjectedToolArg]


class BindingPageRequest(Contract):
    source_id: str
    page: int = Field(ge=1, strict=True)


def planning_assertion_tools(cs, get_actor):
    def save(name, subject, claim, runtime, *, source_id=None):
        actor = get_actor()
        principal = _issuer(cs, actor, subject)
        if runtime is None or not runtime.tool_call_id:
            raise ActionRejected('NATIVE_TOOL_CALL_ID_REQUIRED')
        host = AssertionHost(cs.store.root)
        packet, resources = set(), {}
        if source_id is not None:
            validate_source_versions(cs, actor, source_ids=[source_id])
            version, material = source_version_material(cs, source_id)
            claim['citation']['source_version'] = version
            packet.add(version)
            resources['sources'] = {version: material}
        if name == 'record_conflict':
            packet = set(claim['observations'])
            if not packet <= _source_ids(host, principal, actor, subject):
                raise ActionForbidden('PLANNING_CONFLICT_REQUIRES_OWN_SUBJECT_OBSERVATIONS')
        # The top-level planning work item has no separately issued task attempt.
        # Its native call scopes this grant, including exact replay and revocation.
        grant = Grant(principal, actor.role, actor.task_id, 'native-call:' + runtime.tool_call_id,
                      _commission(cs.store), frozenset({subject}), frozenset(packet), frozenset({name}), resources=resources)
        try:
            ctx = host.issue_once(grant, name, runtime.tool_call_id)
            return getattr(assertions, name)(ctx, subject=subject, claim=claim)
        except (ValueError, PermissionError) as error:
            raise ActionRejected(str(error)) from error

    def propose_page_binding(subject: str, indicator_id: str, pages: list[BindingPageRequest],
                             runtime: NativeRuntime = None) -> dict:
        """Propose applicable physical pages for one object/indicator of the saved plan.
        Select source_id/page from the supplied material. Empty pages record unresolved support.
        The system fills source versions and plan reference; the owner confirms the sheet once.
        Writer extracts the values, not Coordinator.
        """
        from .page_bindings import propose
        if runtime is None or not runtime.tool_call_id:
            raise ActionRejected("NATIVE_TOOL_CALL_ID_REQUIRED")
        return propose(cs, get_actor(), runtime.tool_call_id, subject, indicator_id, [BindingPageRequest.model_validate(p).model_dump() for p in pages])

    def record_conflict(subject: str, observations: list[str], runtime: NativeRuntime = None) -> dict:
        """Record disagreement between distinct source assertion IDs for this inventory object; both observations remain visible."""
        return save('record_conflict', subject, dict(kind='conflict', observations=observations), runtime)

    def ask(subject: str, text: str, affects: Literal['classification','value','presentation','other'],
            runtime: NativeRuntime = None) -> dict:
        """Record an open question about an inventory object and what depends on its answer."""
        return save('ask', subject, dict(kind='question', text=text, affects=affects), runtime)

    return [propose_page_binding, record_conflict, ask]
