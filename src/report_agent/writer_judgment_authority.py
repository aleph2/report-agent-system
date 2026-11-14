"""Bind the Writer's proposed judgment to the approved plan and independently issued observations."""

from uuid import NAMESPACE_URL, uuid5

from . import assertions
from .assertion_host import AssertionHost, Grant
from .source_use import immutable_version_digest
from .store import digest
from .writer_fact_packet import _writer_key, packet_grant


def rule_pin(rule):
    """Pin all approved indicator semantics and the normalized, versioned presentation."""
    from .method_pack import IndicatorRule

    return digest(IndicatorRule.model_validate(rule).model_dump(mode="json"))


def _authorized_method(scope, rule):
    plan, decision = scope["plan"], scope["decision"]
    pack = plan["payload"]["method_pack"]
    approved = decision["payload"]
    version = digest(pack)
    if (
        plan["owner_id"] != "content:coordinator"
        or plan["created_by"] != plan["owner_id"]
        or decision["owner_id"] != "operator"
        or decision["created_by"] != "operator"
        or approved.get("approved") is not True
        or approved["plan_ref"] != plan["ref"]
        or approved.get("confirmed_rules", {}).get("method")
        != dict(id=pack["method_id"], version=pack["version"], digest=version)
        or rule not in pack["indicators"]
    ):
        raise ValueError("WRITER_CONFIRMED_METHOD_REQUIRED")
    return version


def _inputs_key(plan_ref, subject, section):
    task = digest([plan_ref, subject, section])
    return str(uuid5(NAMESPACE_URL, "judgment-inputs/" + task)), "writer", task, "confirmed-inputs"


def _commission_scope(cs, plan_ref, subject, section):
    from .commission_plan import _confirmed as confirmed_plan

    with cs.store.connect() as db:
        plan, decision = confirmed_plan(cs, db)
    obj = next((item for item in plan["payload"]["objects"] if item["object_id"] == subject), None)
    if (
        plan["ref"] != plan_ref
        or not obj
        or not obj["included"]
        or any(red["object_id"] == subject for red in decision["payload"]["reductions"])
        or not any(s["section_id"] == section and s["kind"] == "extracted" for s in plan["payload"]["sections"])
    ):
        raise ValueError("WRITER_APPROVED_CRITERION_SCOPE_MISMATCH")
    return dict(plan=plan, decision=decision, object=obj, section_id=section)


def grant_judgment_inputs(store, plan_ref, object_id, section_id, source_ids, criteria):
    """Trusted commissioning input for previously confirmed sources and reviewed method interpretations."""
    from .content_store import ContentStore

    cs = ContentStore(store)
    scope = _commission_scope(cs, plan_ref, object_id, section_id)
    key = _inputs_key(plan_ref, object_id, section_id)
    version = digest(criteria)
    grant = Grant(
        *key,
        digest(plan_ref),
        frozenset([object_id]),
        frozenset([*source_ids, version]),
        frozenset(),
        resources={"scopes": {version: criteria}},
    )
    AssertionHost(store.root).issue_once(grant, "ask", "inspect-confirmed-inputs")
    provision_criteria(cs, scope)


def _criterion(host, scope, rule, version, interpretation):
    plan, decision = scope["plan"], scope["decision"]
    subject = scope["object"]["object_id"]
    plan_key = digest(plan["ref"])
    spec = dict(interpretation)
    if spec and spec.pop("rule_digest", None) != rule_pin(rule):
        raise ValueError("WRITER_CRITERION_INTERPRETATION_VERSION_MISMATCH")
    method = dict(
        version=version,
        authority=dict(
            plan_ref=plan["ref"],
            decision_ref=decision["ref"],
            method=decision["payload"]["confirmed_rules"]["method"],
            rule=rule,
            sources=plan["payload"]["method_pack"]["sources"],
        ),
        bands={g["id"]: dict(min=g["min_value"], max=g["max_value"]) for g in rule["grades"]},
        value_policy="confirmed_midpoint" if "midpoint_convention" in scope else "criterion_range",
    )
    if spec.keys() - {"readings", "purposes", "adjustments", "question_effect"}:
        raise ValueError("WRITER_CRITERION_INTERPRETATION_INVALID")
    method.update(spec)
    boundary = digest([plan["ref"], decision["ref"], subject, rule["id"]])

    # Project the archived coordinator proposal and the exact, already recorded operator decision.
    # Interpretation resources originate at commissioning, never in the Writer submission.
    def project(action, role, original, packet, claim):
        principal = str(uuid5(NAMESPACE_URL, original["created_by"]))
        operation = digest([boundary, action, claim])
        grant = Grant(
            principal,
            role,
            original["task_id"],
            operation,
            plan_key,
            frozenset([subject]),
            frozenset(packet),
            frozenset([action]),
        )
        return getattr(assertions, action)(
            host.issue_once(grant, action, operation), subject=subject, claim=claim
        )["id"]

    key = project(
        "record_convention",
        "coordinator",
        plan,
        [],
        dict(kind="convention", rule=rule["id"], scope=boundary, criterion_version=version),
    )
    project(
        "confirm",
        "owner",
        decision,
        [key],
        dict(
            kind="act",
            effect="confirm",
            target=key,
            reason="Archived CommissionDecision " + digest(decision["ref"]) + " approved method " + version,
        ),
    )
    return key, method


def _criteria_key(scope):
    subject = scope["object"]["object_id"]
    principal, role, task, _ = _inputs_key(scope["plan"]["ref"], subject, scope["section_id"])
    return principal, role, task, "approved-criteria/" + digest(scope["decision"]["ref"])


def provision_criteria(cs, scope):
    """Trusted coordinator launch imports the original checkpoint before exposing Writer actions."""
    subject, section = scope["object"]["object_id"], scope["section_id"]
    current = _commission_scope(cs, scope["plan"]["ref"], subject, section)
    if scope["decision"]["ref"] != current["decision"]["ref"]:
        raise ValueError("WRITER_APPROVED_CRITERION_SCOPE_MISMATCH")
    scope = current
    host = AssertionHost(cs.store.root)
    plan_ref = scope["plan"]["ref"]
    template = packet_grant(cs.store.root, plan_ref, subject, section)
    definitions = {}
    if template:
        index = template.resources["scopes"][template.task]
        definitions = index.get("criteria", {})
        scope = {**scope, "midpoint_convention": index["midpoint"]}
    extra_key = _inputs_key(plan_ref, subject, section)
    if extra := host.lookup(extra_key):
        if definitions:
            raise ValueError("WRITER_AMBIGUOUS_CRITERION_AUTHORITY")
        (pin,) = extra.resources["scopes"]
        definitions = extra.resources["scopes"][pin]
        if pin != digest(definitions) or pin not in extra.packet:
            raise ValueError("WRITER_INTERPRETATION_PIN_MISMATCH")
    elif host.grant_exists(extra_key):
        raise ValueError("WRITER_JUDGMENT_INPUTS_REVOKED")
    key = _criteria_key(scope)
    edition = digest([scope["plan"]["ref"], scope["decision"]["ref"], definitions, bool(template)])
    if issued := host.lookup(key):
        if edition not in issued.packet:
            raise ValueError("WRITER_CRITERION_PROVISION_CHANGED")
        return
    if host.grant_exists(key):
        raise ValueError("WRITER_CRITERION_PROVISION_REVOKED")
    methods, identifiers = {}, {}
    for rule in scope["plan"]["payload"]["method_pack"]["indicators"]:
        version = _authorized_method(scope, rule)
        criterion, method = _criterion(host, scope, rule, version, definitions.get(rule["id"], {}))
        methods[criterion] = method
        identifiers[rule["id"]] = criterion
    grant = Grant(
        *key,
        digest(plan_ref),
        frozenset([subject]),
        frozenset([*methods, edition]),
        frozenset(),
        resources={"scopes": {key[2]: identifiers}, "criteria": methods},
    )
    host.issue_once(grant, "ask", "read-commissioned-criteria")


def _confirmed(host, grant):
    return {
        r["id"]: r
        for r in assertions.packet(
            host.bind(grant, native_call_id="inspect-inputs", action="ask"), confirmed_only=True
        )
    }


def _inputs(cs, db, host, actor, scope, indicator):
    plan_ref, subject, section = scope["plan"]["ref"], scope["object"]["object_id"], scope["section_id"]
    template = packet_grant(cs.store.root, plan_ref, subject, section)
    rows, by_handle, conventions, interpretation, review = {}, {}, {}, {}, {}
    if template:
        live = host.lookup(_writer_key(actor, scope))
        if not live or live.packet != template.packet:
            raise ValueError("WRITER_ASSIGNED_FACT_PACKET_REQUIRED")
        records = _confirmed(host, live)
        index = live.resources["scopes"][template.task]
        for key in index["all_typed"]:
            row = records[key]
            (receipt,) = row["claim"]["evidence_receipts"]
            qualifiers = live.resources["receipts"][receipt]["qualifiers"]
            by_handle[qualifiers["fact_id"]] = key
            rows[key] = {**row, "qualifiers": qualifiers}
        conventions = live.resources.get("conventions", {})
        interpretation = index.get("criteria", {}).get(indicator, {})
        review = (index.get("reviews") or {}).get(indicator, {})
        if review:
            review = dict(
                question=review["question"], grades=[records[k]["claim"]["rule"] for k in review["grades"]]
            )
    key = _inputs_key(plan_ref, subject, section)
    if extra := host.lookup(key):
        if interpretation:
            raise ValueError("WRITER_AMBIGUOUS_CRITERION_AUTHORITY")
        (version,) = extra.resources["scopes"]
        explicit = extra.resources["scopes"][version]
        if version != digest(explicit) or version not in extra.packet:
            raise ValueError("WRITER_INTERPRETATION_PIN_MISMATCH")
        interpretation = explicit.get(indicator, {})
        rows.update({k: r for k, r in _confirmed(host, extra).items() if r["claim"]["kind"] == "source"})
    elif host.grant_exists(key):
        raise ValueError("WRITER_JUDGMENT_INPUTS_REVOKED")
    from .page_bindings import records as page_records, current
    for row, state in page_records(cs.store, plan_ref, subject):
        if row["claim"]["kind"] == "source" and current(state):
            rows[row["id"]] = {**row, "status": state["status"]}
    allowed = {immutable_version_digest(cs._read(db, ref)["payload"]) for ref in scope["sources"]}
    if any((row["claim"].get("citation") or {}).get("source_version") not in allowed for row in rows.values()):
        raise ValueError("WRITER_JUDGMENT_SOURCE_OUTSIDE_ASSIGNMENT")
    return rows, by_handle, conventions, interpretation, review


def _detail(row, role):
    source = row["claim"]
    item = dict(
        assertion_id=row["id"],
        role=role,
        subject=row["subject"],
        claim=source,
        status=row.get("status", "confirmed"),
        strength_rank=0 if source["state"] == "unknown" else 2,
    )
    if "qualifiers" in row:
        item.update(qualifiers=row["qualifiers"], attestation_receipt=source["evidence_receipts"][0])
    return item


def disclosed_context(cs, db, actor, scope, indicator, original):
    """Preserve nondecisive observations, including displaced/contrary facts, in the immutable receipt."""
    handles = [(role, key) for role in ("context_fact_ids", "contrary_fact_ids") for key in original.get(role, [])]
    if not handles:
        return []
    rows, by_handle, *_ = _inputs(cs, db, AssertionHost(cs.store.root), actor, scope, indicator)
    if any(key not in by_handle for _, key in handles):
        raise ValueError("C4: disclosed context must be from the issued packet")
    return [_detail(rows[by_handle[key]], role) for role, key in handles]


def _grounds(subject, value, original, rows, by_handle, conventions, interpretation, citations, versions):
    grounds = []

    def add(key, purpose):
        row = rows[key]
        prop = row["claim"]["predicate"]
        transfer = None
        if row["subject"] != subject:
            for candidate, spec in conventions.items():
                if (
                    spec.get("from") == row["subject"]
                    and spec.get("to") == subject
                    and (
                        spec.get("proposition") == prop
                        or purpose == "context"
                        and spec.get("proposition") == "document_scope_context"
                    )
                    and purpose in spec.get("purposes", [purpose])
                ):
                    transfer, prop = candidate, spec["proposition"]
                    break
            if transfer is None:
                raise ValueError(
                    "C5: no confirmed transfer for " + purpose + " from " + row["subject"] + " to " + subject
                )
        ground = dict(assertion_id=key, purpose=purpose, proposition=prop, transfer_convention=transfer)
        if ground not in grounds:
            grounds.append(ground)

    for purpose, handles in (
        ("classification", (original.get("grade_claim") or {}).get("fact_ids", [])),
        ("assumption", (original.get("assumption_basis") or {}).get("fact_ids", [])),
        ("adjustment", (original.get("adjustment_claim") or {}).get("fact_ids", [])),
        ("context", original.get("fact_ids", []) if value["kind"] == "gap" else []),
    ):
        for handle in handles:
            if handle not in by_handle:
                raise ValueError("C4: select a confirmed observation from the issued packet")
            add(by_handle[handle], purpose)
    if not by_handle:
        # Ordinary page-based Writers identify an already confirmed observation by its exact citation.
        for citation in citations:
            for key, row in rows.items():
                source = row["claim"]["citation"]
                if source["quote"] != citation["quote"] or source["source_version"] != versions.get(
                    digest(citation["source_ref"])
                ):
                    continue
                from .document_tools import physical_page_number

                if physical_page_number(citation["locator"]) != source["page"]:
                    continue
                purposes = interpretation.get("purposes", {})
                for purpose in ["context"] if value["kind"] == "gap" else ["classification", "assumption"]:
                    if purpose == "assumption" and value["kind"] != "assumption":
                        continue
                    if purpose == "context" or row["claim"]["predicate"] in purposes.get(purpose, []):
                        add(key, purpose)
    return grounds


def _resolved(cs, db, actor, scope, rule, original, entry):
    rows, handles, conventions, spec, review = _inputs(
        cs, db, AssertionHost(cs.store.root), actor, scope, rule["id"]
    )
    versions = {digest(ref): immutable_version_digest(cs._read(db, ref)["payload"]) for ref in scope["sources"]}
    citations = entry.get("sources", entry.get("judgment", {}).get("sources", []))
    grounds = _grounds(
        scope["object"]["object_id"],
        entry["input"],
        original,
        rows,
        handles,
        conventions,
        spec,
        citations,
        versions,
    )
    return grounds, rows, conventions, spec, review


def ground_details(cs, db, actor, scope, rule, original, entry):
    """Copy the exact current, confirmed grounds into the reviewable immutable submission receipt."""
    grounds, rows, *_ = _resolved(cs, db, actor, scope, rule, original, entry)
    return [
        {
            **_detail(rows[g["assertion_id"]], g["purpose"]),
            "proposition": g["proposition"],
            "transfer_convention": g["transfer_convention"],
        }
        for g in grounds
    ]


def prepare_judgment(cs, db, actor, scope, rule, operation_id, entry, *, submission):
    from .writer_assessment import _grade

    host = AssertionHost(cs.store.root)
    version = _authorized_method(scope, rule)
    subject, plan = scope["object"]["object_id"], digest(scope["plan"]["ref"])
    value, original = entry["input"], submission["original"]
    grounds, _, conventions, spec, review = _resolved(cs, db, actor, scope, rule, original, entry)
    issued = host.lookup(_criteria_key(scope))
    if not issued:
        raise ValueError("WRITER_APPROVED_CRITERION_PACKET_REQUIRED")
    criterion = issued.resources["scopes"][issued.task][rule["id"]]
    method = issued.resources["criteria"][criterion]
    if entry["kind"] != "gap" and not spec.get("purposes", {}).get("classification"):
        raise ValueError(
            "C3: no independently bound interpretation for the approved criterion; request an owner-confirmed interpretation and use save_gap while it is unresolved"
        )
    principal = str(uuid5(NAMESPACE_URL, actor.id))

    def bind(action, packet, resources=None):
        attempt = digest([scope["assignment_digest"], action, operation_id])
        grant = Grant(
            principal,
            actor.role,
            actor.task_id,
            attempt,
            plan,
            frozenset([subject]),
            frozenset(packet),
            frozenset([action]),
            resources=resources or {},
        )
        return host.issue_once(grant, action, operation_id)

    accompanying_question = None
    question = review.get("question")
    if not question and value.get("question"):
        from .assertion_host import question_id

        question_claim = dict(
            kind="question",
            text=value["question"],
            affects={"grade": "classification", "in_band_value": "value"}.get(
                value.get("question_effect"), "other"
            ),
        )
        ask_ctx = bind("ask", [])
        question = question_id(ask_ctx, subject, question_claim)
        accompanying_question = ask_ctx, question_claim
    grades = {_grade(g): g["id"] for g in rule["grades"]}
    kind = value["kind"]
    if review and kind != "gap":
        raise ValueError("C7: unresolved engineering interpretation")
    claim = dict(
        kind="judgment",
        basis="conditional" if review else kind,
        question=question,
        warrant=dict(
            criterion=criterion,
            criterion_version=version,
            rationale=value.get("rationale") or value["missing"] or value["question"],
        ),
    )
    if review:
        claim["alternatives"] = review["grades"]
    if kind != "gap":
        claim.update(classification=grades[value["grade"]], value=value["value"])
        if kind == "assumption":
            claim.update(
                alternatives=[grades[g] for g in value["plausible_grades"]],
                defeaters=[value.get("question") or original["assumption_basis"]["narrowing"]],
            )
        checks = entry.get("claim_checks", {})
        claim["review_flags"] = list(checks.get("review_flags", []))
        if original.get("adjustment_claim") or checks.get("adjustment"):
            declined = checks.get("adjustment", {})
            claim["adjustment"] = dict(
                proposed=original["value"],
                rationale=original.get("value_reason") or original["rationale"],
                disposition=declined.get("status", "accepted_with_flag"),
                ground_ids=[g["assertion_id"] for g in grounds if g["purpose"] == "adjustment"],
            )
            if "ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW" not in claim["review_flags"]:
                claim["review_flags"].append("ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW")
    packet = {criterion, *[g["assertion_id"] for g in grounds], *conventions}
    if question:
        packet.add(question)
    return (
        bind(
            "save_judgment",
            packet,
            dict(criteria={criterion: method}, conventions=conventions),
        ),
        claim,
        grounds,
        accompanying_question,
    )
