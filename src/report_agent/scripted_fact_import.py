"""Trusted scripted import of a reviewed register for the offline verification operator."""
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .assertion_host import AssertionHost, Grant
from . import assertions
from .store import digest
from .content_store import ContentStore
from .source_use import source_version_material
from .fact_attestations import attestations_for, load_attestations
from .writer_fact_packet import packet_key


def reviewed_register(directory, pin):
    directory = Path(directory)
    raw = (directory / "confirmed-facts.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("FACT_REGISTER_PIN_MISMATCH")
    return (json.loads(raw), load_attestations(directory / "attestations.json"),
            json.loads((directory / "engineering-review.json").read_bytes()),
            json.loads((directory / "writer-conventions.json").read_bytes()))


def install_facts(store, plan_ref, section_id, register, typed, reviews, selection, pin, *,
                  assigned_observations=None, assigned_attestations=None):
    """Write each assertion and owner confirmation. Publish read grants only after the full import."""
    host = AssertionHost(store.root)
    plan = digest(plan_ref)
    packet, subjects = set(), set()
    resources = {"sources": {}, "receipts": {}}
    versions = {}
    docs = {row["document"] for row in [*register["facts"], *typed]}
    cs = ContentStore(store)
    with store.connect() as db:
        for raw, in db.execute("SELECT data FROM source_versions"):
            doc = json.loads(raw)
            if doc["filename"] not in docs:
                continue
            version, material = source_version_material(cs, doc["id"])
            versions[doc["filename"]] = version
            resources["sources"][version] = material
            packet.add(version)

    coordinator = str(uuid5(NAMESPACE_URL, "scripted-facts/coordinator/" + plan))
    owner = str(uuid5(NAMESPACE_URL, "scripted-facts/owner/" + plan))
    def call(role, name, subject, claim):
        who = coordinator if role == "coordinator" else owner
        identity = digest([name, subject, claim])
        grant = Grant(who, role, "reviewed-facts/" + plan, identity, plan,
                      frozenset({subject}), frozenset(packet), frozenset({name}), resources=resources)
        row = getattr(assertions, name)(host.issue(grant, name, identity), subject=subject, claim=claim)
        packet.add(row["id"])
        subjects.add(subject)
        return row["id"]

    def confirmed(action, subject, claim):
        key = call("owner" if action == "assert_source" else "coordinator", action, subject, claim)
        call("owner", "confirm", subject, dict(kind="act", effect="confirm", target=key,
                                              reason="Scripted owner accepted the reviewed register entry."))
        return key

    def convention(rule, scope, subject="commission"):
        return confirmed("record_convention", subject, dict(kind="convention", rule=rule, scope=scope))

    def citation(row):
        return dict(source_version=versions[row["document"]], page=row["page"], quote=row["quote"])

    obs = {digest(row):confirmed("assert_source", row["applies_to"], dict(
        kind="source", predicate="document_observation", state="value", value=row["fact"],
        citation=citation(row), coverage=row["applies_to"])) for row in register["facts"]}
    typed_ids, typed_receipts = {}, {}
    typed_register_digest = digest(typed)
    for row in typed:
        if row["visual_verified"]:
            raise ValueError("Visual attestation requires an actual image delivery and inspection")
        origin = citation(row)
        # Preserve classification/coverage qualifiers from the reviewed register with the actual text read.
        qualifiers = {k:v for k,v in row.items() if k not in {
            "subject","purpose","coverage","state","document","page","quote","value","unit"}}
        if row["state"] == "explicit_absence":
            qualifiers["value"] = row["value"]
        receipt = dict(actor=owner, source_version=origin["source_version"], page=origin["page"],
                       modality="text", register_sha256=pin, typed_register_digest=typed_register_digest, qualifiers=qualifiers)
        rid = digest(receipt)
        resources["receipts"][rid] = receipt
        packet.add(rid)
        typed_ids[row["fact_id"]] = confirmed("assert_source", row["subject"], dict(
            kind="source", predicate=row["purpose"], coverage=row["coverage"], unit=row.get("unit"),
            period=f'P{row["period_years"]}Y' if row.get("period_years") is not None else None,
            state={"known":"value","unknown":"unknown","explicit_absence":"no_value"}[row["state"]],
            value=row["value"] if row["state"]=="known" else None, citation=origin, evidence_receipts=[rid]))

        typed_receipts[typed_ids[row["fact_id"]]] = rid

    scope = convention(register["scope"], "assessment_scope")
    midpoint = convention(register["midpoint_convention"], "within_band_value")
    indicators = [convention(i, "assigned_indicator") for i in selection["indicators"]]
    roles = {doc:convention(role, "source_role/" + doc) for doc,role in register["source_roles"].items()}
    conflicts, precedences = {}, {}
    for conflict in selection["conflicts"]:
        oid = conflict["subject"]
        members = [typed_ids[k] for k in conflict["observations"]]
        preferred = typed_ids[conflict["preferred"]]
        if preferred not in members:
            raise ValueError("Source precedence must select one of the conflicting observations")
        boundary = "source_precedence/" + digest(members)
        precedence = convention(register["scope"], boundary, oid)
        key = confirmed("record_conflict", oid, dict(kind="conflict", observations=members,
                                                     precedence_convention=precedence))
        conflicts.setdefault(oid, []).extend([key, precedence])
        precedences[precedence] = dict(rule=register["scope"], scope=boundary, resolves=key, preferred=preferred)

    # Only the fixture operator supplies these object/purpose bindings, separately from any Writer.
    transfers = {}
    for binding in selection.get("transfers", []):
        source, target = binding["source"], binding["target"]
        version = digest(binding)
        rule = binding["proposition"]
        boundary = source+" to "+target
        key = confirmed("record_convention",target,dict(kind="convention",rule=rule,scope=boundary,
                                                       criterion_version=version))
        transfers[key] = {"from":source,"to":target,"rule":rule,"scope":boundary,"version":version,
                          "proposition":rule,"purposes":binding["purposes"]}

    indexes = {}
    for oid, unknowns in register["unresolved"].items():
        own_obs = (assigned_observations[oid] if assigned_observations is not None else
                   [r for r in register["facts"] if r["applies_to"] in selection["observation_subjects"][oid]])
        own_typed = (assigned_attestations[oid] if assigned_attestations is not None else attestations_for(typed, oid))
        unknown_ids = [confirmed("assert_source", oid, dict(kind="source", predicate=u, state="unknown",
                                                            coverage=oid)) for u in unknowns]
        review_ids = {}
        for indicator, decision in (reviews or {}).get(oid, {}).items():
            if decision["status"] != "deferred_to_engineering":
                raise ValueError("Unsupported engineering review disposition")
            question = confirmed("ask", oid, dict(kind="question", affects="classification", text=decision["reason"]))
            grades = [convention(g, "conditional_grade/" + indicator, oid) for g in decision["conditional_grades"]]
            review_ids[indicator] = dict(question=question, grades=grades)
        indexes[oid] = dict(scope=scope, midpoint=midpoint, roles=roles, indicators=indicators,
            unknowns=unknown_ids, observations=[obs[digest(r)] for r in own_obs],
            typed=[typed_ids[r["fact_id"]] for r in own_typed] if own_typed is not None else None,
            reviews=review_ids if reviews is not None else None, register_sha256=pin)
    # The assigned source pool may contain the other object's documentary context.
    all_typed = list(dict.fromkeys(k for ix in indexes.values() for k in ix["typed"] or ()))
    excerpts = list(dict.fromkeys(k for ix in indexes.values() for k in ix["observations"]))
    for oid,index in indexes.items():
        principal, role, task, attempt = packet_key(plan_ref, oid, section_id)
        transfer_bindings = {k:v for k,v in transfers.items() if v["to"]==oid}
        ids = {scope, midpoint, *transfer_bindings, *indicators, *roles.values(), *index["unknowns"], *all_typed, *excerpts,
               *conflicts.get(oid, ())}
        for review in (index["reviews"] or {}).values():
            ids.update([review["question"], *review["grades"]])
        index.update(criteria=selection.get("criteria",{}), all_typed=all_typed, excerpts=excerpts, records=sorted(ids),
                     documents={v:k for k,v in versions.items()})
        receipts = {typed_receipts[k]:resources["receipts"][typed_receipts[k]] for k in all_typed}
        host.authorize(Grant(principal,role,task,attempt,plan,frozenset(subjects),
                       frozenset(ids | set(receipts) | set(versions.values())),frozenset(),
                       resources={"scopes":{task:index}, "receipts":receipts,
                                  "conventions":{**{k:v for k,v in precedences.items() if k in ids}, **transfer_bindings}}))
