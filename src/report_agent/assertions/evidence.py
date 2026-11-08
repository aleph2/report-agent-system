"""Project persisted evidence and host-bound method definitions for the approved checks."""
import json
from decimal import Decimal

from .ids import request_digest
from .schema.kinds import Assertion, Judgment, Source


def _verify_source(row, resources):
    source = row.claim
    citation = source.citation
    if citation is None:
        if source.evidence_receipts:
            raise ValueError("C2: receipts must identify the cited source and page")
        return
    material = resources.get("sources", {}).get(citation.source_version, {})
    pages = material.get("pages", {})
    page = pages.get(str(citation.page))
    if not isinstance(page, str) or citation.quote not in page:
        raise ValueError("C2: the exact quotation is missing from the cited source version and page")
    receipts = resources.get("receipts", {})
    image_delivered = False
    for key in source.evidence_receipts:
        receipt = receipts.get(key, {})
        if (receipt.get("actor"), receipt.get("source_version"), receipt.get("page")) != (
            row.was_attributed_to, citation.source_version, citation.page
        ):
            raise ValueError("C2: the cited delivery receipt must identify this actor, source version and page")
        image_delivered |= receipt.get("modality") == "image"
    if source.state != "unknown" and citation.page in material.get("image_pages", ()) and not image_delivered:
        raise ValueError("C2: the image-only observation needs the actor's delivery receipt for that image")


def _strength(claim):
    if claim["kind"] == "source":
        return 0 if claim["state"] == "unknown" else 2
    if claim["kind"] == "judgment":
        return {"evidence": 2, "assumption": 1, "conditional": 0, "gap": 0}[claim["basis"]]
    if claim["kind"] == "derived":
        return {"determined": 2, "provisional": 1, "undetermined": 0}[claim["strength"]]
    return 0


def _method_record(record, definition, version):
    if not version or definition.get("version") != version:
        return
    bands = {}
    for name, interval in definition["bands"].items():
        low, high = Decimal(str(interval["min"])), Decimal(str(interval["max"]))
        if not (low.is_finite() and high.is_finite() and low <= high):
            raise ValueError("C6: invalid bounds in the versioned criterion")
        bands[name] = dict(min=str(low), max=str(high), midpoint=str((low+high)/2))
    record.update(version=version, bands=bands, value_policy=definition.get("value_policy"))


def _matches(source, condition):
    # The method describes predicates in terms of the Source contract. Unknowns never satisfy them.
    allowed = {"predicate","value","coverage","unit","period","state"}
    return bool(source) and bool(condition.get("predicate")) and not (condition.keys() - allowed) and all(
        source.get(key) == value for key, value in condition.items()
    )


def _active(record):
    return record.get("status") == "confirmed" and not record.get("stale",True)


def _grounds(row, records, sources, purpose):
    result = {}
    for ground in row.grounds:
        if ground.purpose != purpose:
            continue
        identifier = ground.assertion_id
        record = records.get(identifier,{})
        if not _active(record) or ground.proposition not in record.get("supports",()):
            continue
        if record["subject"] != row.subject:
            transfer = records.get(ground.transfer_convention,{})
            if not (_active(transfer) and transfer.get("kind") == "convention"
                    and transfer.get("from") == record["subject"] and transfer.get("to") == row.subject
                    and transfer.get("proposition") == ground.proposition):
                continue
        result[identifier] = sources[identifier]
    return result


def _satisfied(conditions, sources):
    return bool(conditions) and all(any(_matches(source, condition) for source in sources)
                                    for condition in conditions)


def _readings(method, decisive):
    results = []
    interpretations = method.get("readings", [])
    exhaustive = bool(interpretations)
    for interpretation in interpretations:
        alternatives = {r["classification"] for r in interpretation if _satisfied(r["when"],decisive)}
        if not alternatives:
            exhaustive = False
        results.extend(sorted(alternatives))
    return list(dict.fromkeys(results)), exhaustive


def _adjustments(row, records, method, support):
    claim = row.claim
    if claim.value is None or not claim.adjustment:
        return []
    criterion = claim.warrant.criterion
    interval = records.get(criterion,{}).get("bands",{}).get(claim.classification)
    if not interval:
        return []
    midpoint = Decimal(interval["midpoint"])
    direction = "lower" if claim.value < midpoint else "higher"
    for rule in method.get("adjustments",()):
        needed = rule["when"]
        if rule.get("direction") != direction or not _satisfied(needed,support.values()):
            continue
        if all(any(_matches(source, cond) for cond in needed) for source in support.values()):
            return [dict(subject=row.subject, criterion=criterion, effective_value=str(claim.value),
                         support_ids=sorted(support))]
    return []


def _validate_references(row, records, resources):
    def require(key, kind=None):
        candidate = records.get(key, {})
        if not candidate or (kind and candidate["kind"] != kind):
            raise ValueError("C4: reference an existing " + (kind or "assertion") + " from the issued packet")
        return candidate

    for ground in row.grounds:
        require(ground.assertion_id)
        if ground.transfer_convention:
            require(ground.transfer_convention, "convention")
    claim = row.claim
    if claim.kind == "judgment":
        if claim.question and require(claim.question, "question")["subject"] != row.subject:
            raise ValueError("C5: select the question for the assessed subject")
        if claim.adjustment:
            for key in claim.adjustment.ground_ids:
                require(key)
    elif claim.kind == "conflict":
        for key in claim.observations:
            require(key, "source")
        if claim.precedence_convention:
            require(claim.precedence_convention, "convention")
    elif claim.kind in ("derived", "recommendation"):
        for key in (claim.inputs if claim.kind == "derived" else claim.basis):
            require(key)
        if claim.kind == "derived":
            if claim.assessment:
                expected = dict(subject=row.subject, claim=claim.model_dump(mode="json"))
                if resources.get("receipts", {}).get(request_digest(expected)) != expected:
                    raise ValueError("C4: assessment requires the exact calculator-issued result")
                for key in claim.inputs:
                    item = require(key, "judgment")
                    if item["subject"] != row.subject or item.get("stale") or item["status"] not in (
                        "proposed", "confirmed", "endorsed"
                    ):
                        raise ValueError("C10: assessment input is stale, contested, or outside its slope")
            if claim.rule_version in records:
                rule = records[claim.rule_version]
                if rule["kind"] not in ("source", "convention") or not _active(rule):
                    raise ValueError("C6: select a confirmed current calculation rule")
            elif resources.get("rules", {}).get(claim.rule_version, {}).get("version") != claim.rule_version:
                raise ValueError("C4: select a bound calculation rule version")


def evidence_projection(db, row: Assertion, resources: dict, states: dict):
    """Only the host supplies resources. Infer applicability from stored, current records."""
    if isinstance(row.claim,Source):
        _verify_source(row,resources)
    records, sources, conflicts = {}, {}, []
    criteria = resources.get("criteria",{})
    conventions = resources.get("conventions",{})
    for identifier, body in db.execute("SELECT id,body FROM assertions"):
        envelope = json.loads(body)
        claim = envelope["claim"]
        record = {**states.get(identifier,{}), "subject":envelope["subject"],"kind":claim["kind"]}
        records[identifier] = record
        record["strength_rank"] = 0
        if _active(record) or record.get("status") == "endorsed" and not record.get("stale",True):
            record["strength_rank"] = _strength(claim)
        if claim["kind"] == "question":
            record["affects"] = claim["affects"]
        if claim["kind"] == "source":
            sources[identifier] = claim
            record["state"] = claim["state"]
            record["supports"] = [claim["predicate"]] if claim["state"] != "unknown" else []
            if identifier in criteria:
                _method_record(record, criteria[identifier], (claim.get("citation") or {}).get("source_version"))
        if claim["kind"] == "convention":
            if identifier in criteria:
                _method_record(record, criteria[identifier], claim.get("criterion_version"))
            binding = conventions.get(identifier,{})
            if (binding and binding.get("rule") == claim["rule"] and binding.get("scope") == claim["scope"]
                    and binding.get("version") == claim.get("criterion_version")):
                for key in ("from","to","proposition","purposes","resolves","preferred"):
                    if key in binding:
                        record[key] = binding[key]
        if claim["kind"] == "conflict" and record.get("status") not in ("retracted","superseded"):
            conflicts.append((identifier,claim))
    displaced = set()
    for identifier, conflict in conflicts:
        precedence = records.get(conflict.get("precedence_convention"), {})
        preferred = precedence.get("preferred")
        if (_active(precedence) and precedence.get("resolves") == identifier
                and preferred in conflict["observations"] and _active(records.get(preferred, {}))):
            displaced.update(key for key in conflict["observations"] if key != preferred)
        for fact in conflict["observations"]:
            if fact in records:
                records[fact].setdefault("conflicts",[]).append(
                    dict(id=identifier,precedence=conflict.get("precedence_convention")))
    _validate_references(row, records, resources)
    for ground in row.grounds:
        convention = records.get(ground.transfer_convention,{})
        if "purposes" in convention and ground.purpose not in convention["purposes"]:
            raise ValueError("C5: transfer convention does not cover this use of the observation")
    result = dict(records=records, applicable_readings=[],readings_exhaustive=False,permitted_adjustments=[])
    if not isinstance(row.claim, Judgment):
        return result
    criterion = row.claim.warrant.criterion
    method = criteria.get(criterion,{})
    if not _active(records.get(criterion,{})) or records[criterion].get("version") != row.claim.warrant.criterion_version:
        return result
    # Method predicates restrict which observed facts are relevant for each purpose.
    required = method.get("purposes",{})
    for g in row.grounds:
        if g.purpose in required and g.proposition not in required[g.purpose]:
            raise ValueError("C3: cite an applicable "+g.purpose+" observation or save a gap")
    decisive = _grounds(row,records,sources,"classification")
    if row.claim.basis == "assumption":
        for purpose,selected in (("classification",decisive),("assumption",_grounds(row,records,sources,"assumption"))):
            expected = {g.assertion_id for g in row.grounds if g.purpose == purpose}
            if not selected or selected.keys() != expected:
                raise ValueError("C3: cite confirmed current "+purpose+" grounds for the assumption or save a gap")
    # Evaluate every interpretation against all current observations, even when the
    # Writer omits a same-subject fact. Its own selected grounds must also suffice.
    available = {i:fact for i,fact in sources.items() if records[i]["subject"] == row.subject
                 and _active(records[i]) and fact["state"] in ("value","no_value")}
    available.update(decisive)
    for key in displaced:
        available.pop(key, None)
    outcomes, exhaustive = _readings(method,available.values())
    if row.claim.basis == "evidence":
        supported, _ = _readings(method,decisive.values())
        exhaustive = exhaustive and row.claim.classification in supported
    question = records.get(row.claim.question,{})
    result["question_effect_conflict"] = bool(method.get("question_effect") and question
                                             and question.get("affects") != method["question_effect"])
    result.update(applicable_readings=outcomes, readings_exhaustive=exhaustive,
                  permitted_adjustments=_adjustments(row,records,method,_grounds(row,records,sources,"adjustment")))
    return result


def normalize_judgment(row: Assertion, projection: dict):
    """Keep the original adjustment and question visible when the effective value changes."""
    claim = row.claim
    if not isinstance(claim,Judgment):
        return claim
    flags = list(claim.review_flags)
    if claim.question:
        flags.append("QUESTION_REQUIRES_SEMANTIC_REVIEW")
    if projection.get("question_effect_conflict"):
        flags.append("QUESTION_EFFECT_CONFLICT")
    if claim.basis == "gap":
        flags.append("GAP_RATIONALE_REQUIRES_SEMANTIC_REVIEW")
    if claim.basis == "assumption":
        flags.append("ASSUMPTION_REQUIRES_SEMANTIC_REVIEW")
    result = claim.model_dump()
    method = projection["records"].get(claim.warrant.criterion,{})
    band = method.get("bands",{}).get(claim.classification)
    if (band and claim.value is not None and method.get("value_policy") == "confirmed_midpoint" and claim.adjustment
            and claim.adjustment.disposition == "accepted_with_flag" and not projection["permitted_adjustments"]
            and claim.value != Decimal(band["midpoint"])):
        # C6 still refuses an out-of-band *classification* proposal. Fallback applies only within its band.
        if Decimal(band["min"]) <= claim.value <= Decimal(band["max"]):
            result["value"] = Decimal(band["midpoint"])
            result["adjustment"]["disposition"] = "refused_midpoint_retained"
            flags.append("UNSUPPORTED_ADJUSTMENT_RETAINED_MIDPOINT")
    result["review_flags"] = tuple(dict.fromkeys(flags))
    return Judgment.model_validate(result)
