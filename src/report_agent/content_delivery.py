"""Live projection of a selected delivery; saved verdicts are immutable evidence."""
from .content_models import aggregate, delivery_aggregate
from .content_store import ContentStore


def obligations(contents, snapshot_ref):
    return [{"target_ref": snapshot_ref, "criterion_ref": ref, "scope": "delivery"}
            for ref in contents.read(snapshot_ref)["payload"]["criteria_refs"]]


def current_delivery(store):
    selected, final = store.get("content_delivery"), store.get("content_final_review")
    if not selected:
        return {"status": "needs_attention", "overall_verdict": None, "final_review_current": False}
    cs = ContentStore(store)
    required = obligations(cs, selected["snapshot_ref"])
    historical = cs.review_summary(selected["snapshot_ref"], required, selected["export_ref"])
    matched = bool(final and all(final["target"][k] == selected[k] for k in ("snapshot_ref", "export_ref")))
    superseded = bool(final and any(r["payload"]["review_ref"] == final["review_ref"]
                                  for r in cs.list_objects("ReviewSupersession")))
    matched = matched and not superseded
    payload = cs.read(final["review_ref"])["payload"] if matched else None
    items = [] if payload is None else [i for i in payload["items"] if cs.item_applies(i, selected["snapshot_ref"], selected["export_ref"])]
    checks = [] if payload is None else [c for c in payload.get("delivery_checks", [])
        if not c["artifact_refs"] or cs.item_applies({**c, "assessment_kind": c["kind"]}, selected["snapshot_ref"], selected["export_ref"])]
    summary = delivery_aggregate(aggregate(items, required), checks)
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
