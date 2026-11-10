"""Project the issued fact packet for a confirmed plan, object and assessment section."""
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from .assertion_host import AssertionHost
from .assertions import packet
from .store import digest
from .errors import ActionRejected
from .source_use import immutable_version_digest


def packet_key(plan_ref, object_id, section_id):
    plan = digest(plan_ref)
    task = digest([plan, object_id, section_id])
    return str(uuid5(NAMESPACE_URL, "assessment-packet/" + task)), "writer", task, plan


def packet_grant(root, plan_ref, object_id, section_id):
    if not (root / "assertion-access.sqlite3").is_file():
        return None
    host = AssertionHost(root)
    key = packet_key(plan_ref, object_id, section_id)
    grant = host.lookup(key)
    if grant is None and host.grant_exists(key):
        raise ActionRejected("WRITER_ASSIGNED_FACT_PACKET_REQUIRED")
    return grant


def _writer_key(actor, scope):
    return (str(uuid5(NAMESPACE_URL, actor.id)), actor.role, actor.task_id, scope["assignment_digest"])


def bind_writer_facts(cs, actor, scope):
    """Trusted delegation gives this task the read-only packet issued for its scope."""
    grant = packet_grant(cs.store.root, scope["plan"]["ref"], scope["object"]["object_id"], scope["section_id"])
    if grant is not None:
        principal, role, task, attempt = _writer_key(actor, scope)
        host = AssertionHost(cs.store.root)
        issued = replace(grant, principal=principal, role=role, task=task, attempt=attempt)
        host.issue_once(issued, "ask", "read-assigned-facts")


def assigned_facts(cs, db, actor, scope, *, exact_receipt=False):
    template = packet_grant(cs.store.root, scope["plan"]["ref"], scope["object"]["object_id"], scope["section_id"])
    if not (cs.store.root / "assertion-access.sqlite3").is_file():
        return {}
    host = AssertionHost(cs.store.root)
    grant = host.lookup(_writer_key(actor, scope))
    if template is None and grant is None:
        from .page_bindings import records, confirmed, current
        subject = scope["object"]["object_id"]
        pages = [dict(binding_id=r["id"], **r["claim"]["page_binding"])
                 for r in confirmed(cs.store,scope["plan"]["ref"],subject)]
        indicators = {r["binding_id"]:r["indicator_id"] for r in pages}
        values = [dict(assertion_id=r["id"], status=state["status"], claim=r["claim"],
                       indicator_ids=sorted({indicators[g["assertion_id"]] for g in r["grounds"]
                                             if g["assertion_id"] in indicators}))
                  for r,state in records(cs.store,scope["plan"]["ref"],subject)
                  if r["claim"]["kind"] == "source" and current(state)]
        return dict(object_facts=dict(applicable_pages=pages, extracted_values=values),
                    assigned_indicators=[r["id"] for r in scope["plan"]["payload"]["method_pack"]["indicators"]])
    if template is None or grant is None or grant.packet != template.packet:
        raise ActionRejected("WRITER_ASSIGNED_FACT_PACKET_REQUIRED")
    allowed = {immutable_version_digest(cs._read(db, ref)["payload"]) for ref in scope["sources"]}
    ctx = host.bind(grant, native_call_id="read-assigned-facts", action="ask")
    records = {row["id"]:row for row in packet(ctx, confirmed_only=not exact_receipt)}
    index = grant.resources["scopes"][template.task]
    required = set(index["records"])
    if not required <= records.keys():
        raise ActionRejected("WRITER_ASSIGNED_FACT_NO_LONGER_CONFIRMED")

    def claim(key):
        return records[key]["claim"]

    def source(key):
        item = claim(key)
        citation = item.get("citation")
        if not citation or citation["source_version"] not in allowed:
            raise ActionRejected("WRITER_FACT_SOURCE_OUTSIDE_ASSIGNMENT")
        return item, dict(document=index["documents"][citation["source_version"]],
                          page=citation["page"], quote=citation["quote"])

    def attestation(key):
        item, origin = source(key)
        receipt_id, = item["evidence_receipts"]
        receipt = grant.resources["receipts"][receipt_id]
        if digest(receipt) != receipt_id:
            raise ActionRejected("WRITER_ATTESTATION_PIN_MISMATCH")
        return {**receipt["qualifiers"], **origin, "subject": records[key]["subject"],
                "state": {"value":"known", "unknown":"unknown", "no_value":"explicit_absence"}[item["state"]],
                "purpose": item["predicate"], "coverage": item["coverage"],
                "value": item["value"] if item["state"] != "no_value" else receipt["qualifiers"].get("value"),
                "unit": item["unit"]}

    facts = {"source_roles": {name:claim(key)["rule"] for name,key in index["roles"].items()},
             "scope": claim(index["scope"])["rule"], "observations": [],
             "unresolved": [claim(key)["predicate"] for key in index["unknowns"]]}
    for key in index["observations"]:
        item, origin = source(key)
        facts["observations"].append({"applies_to": records[key]["subject"], "fact": item["value"], **origin})
    if index["typed"] is not None:
        facts["attestations"] = [attestation(key) for key in index["typed"]]
    if index["reviews"] is not None:
        facts["engineering_reviews"] = {
            indicator: {"status":"deferred_to_engineering", "reason":claim(review["question"])["text"],
                        "conditional_grades":[claim(key)["rule"] for key in review["grades"]]}
            for indicator,review in index["reviews"].items()}
    return dict(object_facts=facts, midpoint_convention=claim(index["midpoint"])["rule"],
                assigned_indicators=[claim(key)["rule"] for key in index["indicators"]],
                attested_facts=[attestation(key) for key in index["all_typed"]] if index["typed"] is not None else None,
                registered_excerpts=[source(key)[1]["quote"] for key in (*index["excerpts"], *index["all_typed"])],
                register_sha256=index["register_sha256"])
