"""One planning sheet authorizes pages; Writer facts remain independently reviewable."""
from uuid import NAMESPACE_URL, uuid5

from . import assertions
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


def records(store, plan_ref, subject=None):
    rows = Commission.page_records(store.root)
    bindings = {row["id"] for row, _ in rows if row["claim"]["kind"] == "convention"
                and row["claim"]["rule"] == encode(plan_ref)}
    return [(row, state) for row, state in rows if
            (row["id"] in bindings or any(g["assertion_id"] in bindings for g in row["grounds"]))
            and (subject is None or row["subject"] == subject)]


def current(state):
    return state["active"] and not state["stale"] and not state["challenged"]


def confirmed(store, plan_ref, subject, indicator=None):
    return [row for row, state in records(store, plan_ref, subject)
            if row["claim"]["kind"] == "convention" and current(state) and state["status"] == "confirmed"
            and (indicator is None or row["claim"]["page_binding"]["indicator_id"] == indicator)]


def propose(cs, actor, operation, subject, indicator, pages):
    from .planning_assertions import _issuer
    from .commission_plan import read_plan
    from .source_use import source_version_material, validate_source_versions
    principal = _issuer(cs, actor, subject)
    plan = read_plan(cs.store)
    if not plan or not any(o["object_id"] == subject for o in plan["payload"]["objects"]):
        raise ActionRejected("PAGE_BINDING_SAVED_PLAN_OBJECT_REQUIRED")
    pack = plan["payload"].get("method_pack") or {}
    if indicator not in {r["id"] for r in pack.get("indicators", [])}:
        raise ActionRejected("PAGE_BINDING_METHOD_INDICATOR_REQUIRED")
    bound = []
    for item in pages:
        validate_source_versions(cs, actor, source_ids=[item["source_id"]])
        version, material = source_version_material(cs, item["source_id"])
        if str(item["page"]) not in material["pages"]:
            # A scanned/drawing page can exist without a frozen text block.
            from .document_tools import source_page_info
            from .workspace import Workspace
            try:
                source_page_info(Workspace(cs.store), item["source_id"], item["page"])
            except ActionRejected:
                raise ActionRejected("PAGE_BINDING_PHYSICAL_PAGE_REQUIRED") from None
        bound.append(dict(source_version=version, page=item["page"]))
    if pages:
        cs.capture_sources(actor, "page-binding-sources:" + operation, list(dict.fromkeys(p["source_id"] for p in pages)))
    claim = dict(kind="convention", scope="source_page_binding", rule=encode(plan["ref"]),
                 page_binding=dict(indicator_id=indicator, pages=bound))
    grant = Grant(principal, actor.role, actor.task_id, "page-binding:" + operation, digest(plan["ref"]),
                  frozenset({subject}), frozenset(p["source_version"] for p in bound), frozenset({"record_convention"}))
    return assertions.record_convention(AssertionHost(cs.store.root).issue_once(grant,"record_convention",operation),
                                        subject=subject, claim=claim)


def confirm_reply(store, owner, issue, checkpoint, decision_ref):
    from . import commission_assertions
    commission_assertions._require_actor(owner, "owner")
    if commission_assertions.checkpoint_answer(store,"plan",issue) != decision_ref:
        raise ActionRejected("PAGE_BINDING_SAVED_OWNER_REPLY_REQUIRED")
    decision = ContentStore(store).read(decision_ref)["payload"]
    if not decision["approved"]:
        return
    excluded = set(decision.get("unconfirmed_page_bindings", []))
    sheet = checkpoint.get("page_bindings", [])
    if not excluded <= set(sheet):
        raise ActionRejected("PAGE_BINDING_EXCEPTION_OUTSIDE_SHEET")
    rows = {r["id"]:r for r,_ in records(store, checkpoint["plan_ref"])}
    host = AssertionHost(store.root)
    for key in sheet:
        if key in excluded:
            continue
        row = rows.get(key)
        if row is None or row["claim"]["kind"] != "convention":
            raise ActionRejected("PAGE_BINDING_SHEET_RECORD_MISSING")
        operation = "page-confirm:" + issue + ":" + key
        grant = Grant(str(uuid5(NAMESPACE_URL, owner.id)), "owner", owner.task_id, operation,
                      digest(checkpoint["plan_ref"]), frozenset({row["subject"]}), frozenset({key}), frozenset({"confirm"}))
        assertions.confirm(host.issue_once(grant,"confirm",operation), subject=row["subject"],
            claim=dict(kind="act",effect="confirm",target=key,reason="Planning reply " + encode(decision_ref)))


def sheet_route(store, plan_ref):
    """A page-sheet checkpoint retires file approval only for that exact plan."""
    from . import commission_assertions
    for action, body, state in commission_assertions._rows(store):
        if action == "ask" and current(state):
            import json
            data = json.loads(body["claim"]["text"])
            if data.get("plan_ref") == plan_ref and "page_bindings" in data:
                return True
    return False


def extracted_pages(store, plan_ref, subject, quote, indicator=None):
    bindings = {r["id"] for r in confirmed(store,plan_ref,subject,indicator)}
    return {(r["claim"]["citation"]["source_version"],r["claim"]["citation"]["page"])
            for r,state in records(store,plan_ref,subject)
            if r["claim"]["kind"] == "source" and current(state)
            and r["claim"].get("citation",{}).get("quote") == quote
            and any(g["assertion_id"] in bindings for g in r["grounds"])}
