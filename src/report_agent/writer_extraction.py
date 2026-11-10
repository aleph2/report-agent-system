"""Native quote extraction: identities, page applicability and delivery come from the host."""
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5
from langchain_core.tools import InjectedToolCallId, StructuredTool

from . import assertions, page_bindings
from .assertion_host import AssertionHost, Grant
from .content_store import ContentStore
from .errors import ActionRejected
from .source_use import source_version_material
from .store import digest


def tools(workspace, actor):
    cs = ContentStore(workspace.store)

    def current():
        from .writer_assessment import _assignment, _step_state
        with cs.store.connect() as db:
            scope = _assignment(cs, db, actor)
            _, _, rule, _ = _step_state(cs, db, scope, actor)
        if rule is None:
            raise ActionRejected("WRITER_INDICATOR_STEP_MISMATCH")
        return scope, rule

    def save(action, call, scope, claim, packet, resources=None, grounds=()):
        grant = Grant(str(uuid5(NAMESPACE_URL, actor.id)), actor.role, actor.task_id,
                      scope["assignment_digest"] + ":" + call, digest(scope["plan"]["ref"]),
                      frozenset({scope["object"]["object_id"]}), frozenset(packet), frozenset({action}), resources=resources or {})
        try:
            return getattr(assertions, action)(
                AssertionHost(cs.store.root).issue_once(grant,action,call),
                subject=scope["object"]["object_id"],claim=claim,grounds=grounds)
        except (ValueError, PermissionError) as error:
            raise ActionRejected(str(error)) from error

    def assert_source(source_handle: str, page: int, quote: str, predicate: str,
                      state: Literal["value","no_value","unknown"], coverage: str,
                      tool_call_id: Annotated[str, InjectedToolCallId],
                      value: str | int | float | bool | None = None,
                      unit: str | None = None, period: str | None = None) -> dict:
        """Save an extracted value with its exact quote from a confirmed applicable page.
        Choose a relevant offered fact_predicate when supplied.
        The system binds the current object/indicator, source version and native operation.
        The value remains proposed for independent review; missing material never proves absence.
        """
        from .writer_assignments import _prepared
        from .writer_judgments import delivered_pages
        scope, rule = current()
        with cs.store.connect() as db:
            _, index = _prepared(cs,db,actor)
            source = next((s for s in index["sources"] if s["source_handle"] == source_handle), None)
            if not source:
                raise ActionRejected("WRITER_SOURCE_HANDLE_UNKNOWN")
            source_id = cs._read(db,source["source_ref"])["payload"]["source_id"]
            version, material = source_version_material(cs,source_id)
            deliveries = [(key,r) for key,r in delivered_pages(db,scope["assignment_digest"])
                          if r["actor"] == actor.__dict__ and r["source_version"] == version and r["page"] == page
                          and (r["modality"] != "image" or r.get("image_delivered"))]
        if not deliveries:
            raise ActionRejected("WRITER_PAGE_RECEIPT_NOT_DELIVERED")
        bindings = [r for r in page_bindings.confirmed(cs.store,scope["plan"]["ref"],
                    scope["object"]["object_id"],rule["id"])
                    if dict(source_version=version,page=page) in r["claim"]["page_binding"]["pages"]]
        if not bindings:
            raise ActionRejected("C3: page is not confirmed for this object and indicator")
        binding = bindings[0]["id"]
        principal = str(uuid5(NAMESPACE_URL,actor.id))
        receipts = {key:dict(actor=principal,source_version=version,page=page,modality=r["modality"])
                    for key,r in deliveries if r["modality"] == "image"}
        claim = dict(kind="source",predicate=predicate,state=state,coverage=coverage,
                     value=value,unit=unit,period=period,citation=dict(source_version=version,page=page,quote=quote),
                     evidence_receipts=list(receipts))
        return save("assert_source",tool_call_id,scope,claim,[binding,version,*receipts],
                    dict(sources={version:material},receipts=receipts),
                    [dict(assertion_id=binding,purpose="context",proposition="source_page_binding")])

    def record_conflict(observations: list[str], tool_call_id: Annotated[str, InjectedToolCallId]) -> dict:
        """Keep conflicting extracted fact IDs for this assigned object without discarding either quote."""
        scope, _ = current()
        allowed = {r["id"] for r,s in page_bindings.records(cs.store,scope["plan"]["ref"],
                   scope["object"]["object_id"]) if r["claim"]["kind"] == "source" and page_bindings.current(s)}
        if not set(observations) <= allowed:
            raise ActionRejected("C4: conflict observations must be in this object's extracted packet")
        return save("record_conflict",tool_call_id,scope,
                    dict(kind="conflict",observations=observations),observations)

    return [StructuredTool.from_function(f) for f in (assert_source,record_conflict)]
