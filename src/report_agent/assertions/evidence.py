"""Project persisted evidence and host-bound method definitions for the approved checks."""
import json

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


def _method_record(record, definition, version):
    if not version or definition.get("version") != version:
        return
    record["version"] = version


def _active(record):
    return record.get("status") == "confirmed" and not record.get("stale",True)


def _eligible(record):
    return _active(record) or record.get("source_eligible", False)


def _grounds(row, records, sources, purpose):
    result = {}
    for ground in row.grounds:
        if ground.purpose != purpose:
            continue
        identifier = ground.assertion_id
        record = records.get(identifier,{})
        if not _eligible(record) or ground.proposition not in record.get("supports",()):
            continue
        if record["subject"] != row.subject:
            transfer = records.get(ground.transfer_convention,{})
            if not (_active(transfer) and transfer.get("kind") == "convention"
                    and transfer.get("from") == record["subject"] and transfer.get("to") == row.subject
                    and transfer.get("proposition") == ground.proposition):
                continue
        result[identifier] = sources[identifier]
    return result


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
                        raise ValueError("C10: assessment input is stale, contested, or belongs to a different subject")
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
    records, sources = {}, {}
    criteria = resources.get("criteria",{})
    conventions = resources.get("conventions",{})
    for identifier, body in db.execute("SELECT id,body FROM assertions"):
        envelope = json.loads(body)
        claim = envelope["claim"]
        record = {**states.get(identifier,{}), "subject":envelope["subject"],"kind":claim["kind"]}
        records[identifier] = record
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
                for key in ("from","to","proposition","purposes"):
                    if key in binding:
                        record[key] = binding[key]
    for identifier in sources:
        record = records[identifier]
        record["source_eligible"] = not record.get("stale") and record["status"] in ("proposed", "endorsed")
    _validate_references(row, records, resources)
    for ground in row.grounds:
        convention = records.get(ground.transfer_convention,{})
        if "purposes" in convention and ground.purpose not in convention["purposes"]:
            raise ValueError("C5: transfer convention does not cover this use of the observation")
    result: dict = dict(records=records)
    if not isinstance(row.claim, Judgment):
        return result
    criterion = row.claim.warrant.criterion
    method = criteria.get(criterion,{})
    if not _active(records.get(criterion,{})) or records[criterion].get("version") != row.claim.warrant.criterion_version:
        return result
    decisive = _grounds(row,records,sources,"classification")
    if row.claim.basis == "assumption":
        for purpose,selected in (("classification",decisive),("assumption",_grounds(row,records,sources,"assumption"))):
            expected = {g.assertion_id for g in row.grounds if g.purpose == purpose}
            if selected.keys() != expected:
                raise ValueError("C3: cite confirmed current "+purpose+" grounds for the assumption or save a gap")
    question = records.get(row.claim.question,{})
    result["question_effect_conflict"] = bool(method.get("question_effect") and question
                                             and question.get("affects") != method["question_effect"])
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
    result["review_flags"] = tuple(dict.fromkeys(flags))
    return Judgment.model_validate(result)
