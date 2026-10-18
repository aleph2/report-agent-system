"""Live projection of a selected delivery; saved verdicts are immutable evidence."""
from .content_models import Ref, aggregate, delivery_aggregate
from .content_store import ContentStore


def obligations(contents, snapshot_ref):
    return [{"target_ref": snapshot_ref, "criterion_ref": ref, "scope": "delivery"}
            for ref in contents.read(snapshot_ref)["payload"]["criteria_refs"]]


def _legacy_current_delivery(store):
    selected, final = store.get("content_delivery"), store.get("content_final_review")
    if not selected:
        return {"status": "needs_attention", "overall_verdict": None, "final_review_current": False}
    cs = ContentStore(store)
    required = obligations(cs, selected["snapshot_ref"])
    companion = selected.get("workbook_export_ref")
    historical = cs.review_summary(selected["snapshot_ref"], required, selected["export_ref"], companion)
    matched = bool(final and all(final["target"][k] == selected[k] for k in ("snapshot_ref", "export_ref")))
    superseded = bool(final and any(r["payload"]["review_ref"] == final["review_ref"]
                                  for r in cs.list_objects("ReviewSupersession")))
    matched = matched and not superseded
    payload = cs.read(final["review_ref"])["payload"] if matched else None
    items = [] if payload is None else [i for i in payload["items"] if cs.item_applies(i, selected["snapshot_ref"], selected["export_ref"], companion)]
    checks = [] if payload is None else [c for c in payload.get("delivery_checks", [])
        if not c["artifact_refs"] or cs.item_applies({**c, "assessment_kind": c["kind"]}, selected["snapshot_ref"], selected["export_ref"], companion)]
    summary = delivery_aggregate(aggregate(items, required), checks)
    from .review_coverage import apply_coverage
    summary = apply_coverage(summary, cs.read(selected["snapshot_ref"]), payload)
    changed = cs.changed_review_sources(payload) if payload else []
    if changed:
        summary.update(overall_verdict=None, coverage_complete=False)
    # Only the matching final record supplies positive coverage. Local records
    # can invalidate it; they cannot fill unfinished final review responsibilities.
    if historical["confirmed_violations"] or historical["delivery_violations"] or (
            payload and any(c["verdict"] == "not_satisfied" for c in checks)):
        summary["overall_verdict"] = "not_satisfied"
    verdict = summary["overall_verdict"]
    return {**summary, "status": {"satisfied": "reviewed_draft", "not_satisfied": "changes_required",
            "undetermined": "needs_attention", None: "needs_attention"}[verdict],
            "final_review_current": matched, "changed_review_sources": changed,
            "final_review_superseded": superseded,
            "confirmed_violations": historical["confirmed_violations"], "delivery_violations": historical["delivery_violations"]}


def current_delivery(store):
    """Expose evidence without inventing a snapshot acceptance task or verdict."""
    if store.manifest.get("review_entrypoint") == "native-rubric-v1":
        return _legacy_current_delivery(store)
    selected = store.get("content_delivery")
    result = {"status": "not_assessed", "overall_verdict": None, "coverage_complete": None,
              "final_review_current": False, "items": [], "delivery_checks": [],
              "confirmed_violations": [], "delivery_violations": [], "needs_recheck": [],
              "execution_decision": store.get("content_execution_decision"),
              "limitation": "Recorded scoped evidence only. Accounting, child passes and execution completion do not establish whole-report acceptance."}
    if not selected:
        return result
    cs = ContentStore(store)
    snapshot = cs.read(selected["snapshot_ref"])
    from .review_coverage import inventory
    result.update(snapshot_ref=snapshot["ref"], export_ref=selected["export_ref"],
                  criteria_refs=snapshot["payload"]["criteria_refs"], coverage_accounting=[])
    companion = selected.get("workbook_export_ref")
    if companion is not None:
        result["workbook_export_ref"] = companion
    targeted = set()
    history = (cs.list_objects("ReviewSupersession"), cs.list_objects("ReviewReuse"))
    source_changes = {}
    for review in cs.list_objects("ReviewRecord"):
        payload = review["payload"]
        for index, item in enumerate(payload["items"]):
            withdrawn, relevant, reuse = cs.review_item_state(review, snapshot["ref"], index, history)
            if withdrawn or not relevant:
                continue
            source_key = (Ref.model_validate(payload["snapshot_ref"]).key(),
                          tuple(Ref.model_validate(r).key() for r in cs.item_dependencies(payload, item)))
            if source_key not in source_changes:
                source_changes[source_key] = cs.changed_review_sources(payload, item)
            changed = source_changes[source_key]
            applies = cs.item_applies(item, snapshot["ref"], selected["export_ref"], companion)
            if changed or not applies or item.get("assessment_kind") == "combined":
                result["needs_recheck"].append({"review_ref": review["ref"], "item_index": index,
                    "changed_source_refs": changed, "artifact_current": applies,
                    "legacy_mixed_scope": item.get("assessment_kind") == "combined"})
            if not applies or (changed and item["verdict"] != "not_satisfied"):
                continue
            entry = {"review_ref": review["ref"], "item_index": index, "reuse_refs": reuse, **item}
            result["items"].append(entry)
            targeted.add(Ref.model_validate(item["target_ref"]).key())
            if item["verdict"] == "not_satisfied":
                result["confirmed_violations"].append(entry)
        withdrawn, relevant, _ = cs.review_item_state(review, snapshot["ref"], history=history)
        if relevant and not withdrawn:
            for check in payload.get("delivery_checks", []):
                if cs.item_applies({**check, "assessment_kind": check["kind"]}, snapshot["ref"], selected["export_ref"], companion):
                    entry = {"review_ref": review["ref"], **check}
                    result["delivery_checks"].append(entry)
                    if check["verdict"] == "not_satisfied":
                        result["delivery_violations"].append(entry)
            for accounting in payload.get("coverage_accounting", []):
                result["coverage_accounting"].append({"review_ref": review["ref"], **accounting,
                    "linked_item_current": [not cs.review_item_state(review, snapshot["ref"], i, history)[0]
                                            for i in accounting["item_indexes"]],
                    "semantic_coverage_verified": False})
    result["without_direct_current_item"] = [r for r in inventory(snapshot) if Ref.model_validate(r).key() not in targeted]
    # A scoped finding never becomes an inferred whole-report verdict.
    result["status"] = "review_evidence_available" if result["items"] or result["delivery_checks"] else "not_assessed"
    return result
