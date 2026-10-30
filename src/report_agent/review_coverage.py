"""Version-bound object accounting; semantic applicability remains with reviewers."""
from .content_models import Ref
from .errors import ActionRejected

CONTRACT = "object-coverage-v1"


def inventory(snapshot):
    return [r for r in snapshot["payload"]["refs"] if r["type"] in {"ContentNode", "Requirement"}]


def validate_accounting(snapshot, review):
    allowed = {Ref.model_validate(r).key() for r in inventory(snapshot)}
    seen = set()
    members = {Ref.model_validate(r).key() for r in snapshot["payload"]["refs"]}
    for entry_index, entry in enumerate(review.get("coverage_accounting", [])):
        indexes = entry["item_indexes"]
        if any(type(i) is not int or i < 0 or i >= len(review["items"]) for i in indexes):
            raise ActionRejected("COVERAGE_ITEM_INDEX_INVALID")
        for ref_index, ref in enumerate(entry["target_refs"]):
            key = Ref.model_validate(ref).key()
            if key not in allowed:
                raise ActionRejected("COVERAGE_OBJECT_OUTSIDE_SNAPSHOT", diagnostic={
                    "reason": "unsupported_coverage_object_type" if key in members else "object_not_in_snapshot",
                    "allowed_object_types": ["ContentNode", "Requirement"],
                    "parameter_path": ["review", "coverage_accounting", entry_index, "target_refs", ref_index]})
            if key in seen:
                raise ActionRejected("DUPLICATE_COVERAGE_OBJECT")
            seen.add(key)
        if entry["state"] in {"assessed", "not_applicable"}:
            if not indexes or any(review["items"][i]["verdict"] is None or
                                  not review["items"][i]["observations"] for i in indexes):
                raise ActionRejected("COVERAGE_REQUIRES_OBSERVED_JUDGMENT")
            if entry["state"] == "not_applicable" and any(r["type"] == "Requirement" for r in entry["target_refs"]):
                raise ActionRejected("REVIEWER_CANNOT_CANCEL_REQUIREMENT")


def coverage_summary(snapshot, review):
    if snapshot["payload"].get("coverage_contract") != CONTRACT:
        return {"contract": None, "required": False, "complete": None}
    required = inventory(snapshot)
    entries = {Ref.model_validate(r).key(): e for e in (review or {}).get("coverage_accounting", []) for r in e["target_refs"]}
    missing = [r for r in required if Ref.model_validate(r).key() not in entries]
    incomplete = [r for r in required if (e := entries.get(Ref.model_validate(r).key()))
                  and (e["state"] in {"partial", "not_assessed"} or any(
                      review["items"][i]["execution_state"] != "completed" or
                      review["items"][i]["coverage"]["unchecked"] or review["items"][i]["coverage"]["blocked"]
                      for i in e["item_indexes"]))]
    return {"contract": CONTRACT, "required": True, "expected_count": len(required),
            "accounted_count": len(entries), "missing_refs": missing, "incomplete_refs": incomplete,
            "complete": not missing and not incomplete,
            "note": "Accounting and reference completeness, not proof of correct understanding or exhaustive issue discovery."}


def apply_coverage(summary, snapshot, review):
    coverage = coverage_summary(snapshot, review)
    result = {**summary, "object_coverage": coverage}
    if coverage["required"] and not coverage["complete"]:
        result["coverage_complete"] = False
        if result["overall_verdict"] != "not_satisfied":
            result["overall_verdict"] = None
    return result
