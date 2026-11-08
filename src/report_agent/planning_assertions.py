"""Coordinator planning actions backed by case-local, host-issued assertion grants."""
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from langchain.tools import ToolRuntime
from pydantic import Field

from . import assertions, legacy_state as legacy
from .assertion_host import AssertionHost, Grant
from .content_tasks import model_owner_identity
from .errors import ActionForbidden, ActionRejected
from .source_use import _commission, source_version_material, validate_source_versions
from .store import digest


def _issuer(cs, actor, subject):
    from .hierarchical_tools import actor_for
    if actor != actor_for('coordinator') or model_owner_identity(cs.store) is not None:
        raise ActionForbidden('PLANNING_ASSERTION_COORDINATOR_REQUIRED')
    with cs.store.connect() as db:
        draft = legacy.get_commission_planning_draft(db, {})
        if subject not in draft.get('items', {}).get('object', {}):
            ref = legacy.get_commission_plan(db)
            if not ref or not any(o['object_id'] == subject for o in cs._read(db, ref)['payload']['objects']):
                raise ActionForbidden('PLANNING_ASSERTION_INVENTORY_SUBJECT_REQUIRED')
    return str(uuid5(NAMESPACE_URL, actor.id))


def _source_ids(host, principal, actor, subject):
    return host.commission.produced_ids(actor=principal, task=actor.task_id, subject=subject, kind='source')


def read_source_index(cs, actor, subject, page, page_size, view_ref):
    principal = _issuer(cs, actor, subject)
    ids = sorted(_source_ids(AssertionHost(cs.store.root), principal, actor, subject))
    current = digest([subject, ids])
    if (view_ref and view_ref != current) or (page > 1 and not view_ref):
        raise ActionRejected('PLANNING_SOURCE_INDEX_VIEW_CHANGED_OR_REQUIRED')
    if page > max(1, (len(ids) + page_size - 1) // page_size):
        raise ActionRejected('PLANNING_SOURCE_INDEX_PAGE_OUT_OF_RANGE')
    end = page * page_size
    return dict(subject=subject, source_assertion_ids=ids[end-page_size:end], total=len(ids),
                view_ref=current, next_page=page + 1 if end < len(ids) else None)


def planning_assertion_tools(cs, get_actor):
    def save(name, subject, claim, runtime, *, source_id=None, observed_at=None):
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
                      _commission(cs.store), {subject}, packet, {name}, resources=resources)
        try:
            ctx = host.issue_once(grant, name, runtime.tool_call_id)
            if name == 'assert_source':
                return assertions.assert_source(ctx, subject=subject, claim=claim, observed_at=observed_at)
            return getattr(assertions, name)(ctx, subject=subject, claim=claim)
        except (ValueError, PermissionError) as error:
            raise ActionRejected(str(error)) from error

    def assert_source(subject: str, predicate: str, state: Literal['value', 'no_value', 'unknown'],
                      coverage: str, value: str | int | float | bool | None = None,
                      unit: str | None = None, period: str | None = None, source_id: str | None = None,
                      page: Annotated[int | None, Field(ge=1)] = None, quote: str | None = None,
                      observed_at: str | None = None, runtime: ToolRuntime = None) -> dict:
        """Propose a sourced fact for a planning inventory object. Cite the source ID, physical page and exact frozen text. Explicit absence needs a citation; silence allows only unknown. Set observed_at only for an explicit observation date/time in the quote (ISO date or zoned timestamp)."""
        citation = None
        if any(x is not None for x in (source_id, page, quote)):
            if not (source_id and page and quote and quote.strip()):
                raise ActionRejected('PLANNING_COMPLETE_SOURCE_CITATION_REQUIRED')
            citation = dict(page=page, quote=quote)
        claim = dict(kind='source', predicate=predicate, state=state, coverage=coverage, value=value,
                     unit=unit, period=period, citation=citation)
        return save('assert_source', subject, claim, runtime, source_id=source_id, observed_at=observed_at)

    def record_conflict(subject: str, observations: list[str], runtime: ToolRuntime = None) -> dict:
        """Record disagreement between distinct source assertion IDs for this inventory object; both observations remain visible."""
        return save('record_conflict', subject, dict(kind='conflict', observations=observations), runtime)

    def ask(subject: str, text: str, affects: Literal['classification','value','presentation','other'],
            runtime: ToolRuntime = None) -> dict:
        """Record an open question about an inventory object and what depends on its answer."""
        return save('ask', subject, dict(kind='question', text=text, affects=affects), runtime)

    return [assert_source, record_conflict, ask]
