"""Read-only, version-scoped review inventory, including never-reviewed objects.

Persisted ReviewRecord/ReviewReuse/HandlingRecord remain the source of truth.
The inventory describes existing scopes; it does not invent acceptance requirements.
"""
from collections import defaultdict

from .content_delivery import current_delivery
from .content_models import Ref
from .errors import ActionRejected
from .store import encode


def _key(ref):
    return Ref.model_validate(ref).key()


def _logical(ref):
    return ref["type"], ref["id"]


def read_status(contents, snapshot_ref, target_ref=None, export_ref=None, offset=0, limit=20):
    if offset < 0 or not 1 <= limit <= 100:
        raise ActionRejected("INVALID_PAGE")
    snapshot = contents.read(snapshot_ref)
    if snapshot_ref["type"] != "DocumentSnapshot":
        raise ActionRejected("SNAPSHOT_REQUIRED")
    records = contents.list_objects()
    by_key = {_key(r["ref"]): r for r in records}
    members = {_key(r) for r in [snapshot_ref, *snapshot["payload"]["refs"]]}
    selected = contents.store.get("content_delivery")

    def artifact_export(ref):
        record = contents.read(ref)
        if ref["type"] not in {"ExportArtifact", "RenderArtifact"} or record["payload"].get("snapshot_ref") != snapshot_ref:
            raise ActionRejected("ARTIFACT_OUTSIDE_SNAPSHOT")
        return record["payload"]["export_ref"] if ref["type"] == "RenderArtifact" else ref

    if target_ref:
        contents.read(target_ref)
        if target_ref["type"] in {"ExportArtifact", "RenderArtifact"}:
            target_export = artifact_export(target_ref)
            if export_ref and export_ref != target_export:
                raise ActionRejected("TARGET_OUTSIDE_EXPORT")
            export_ref = target_export
        elif _key(target_ref) not in members:
            raise ActionRejected("REVIEW_TARGET_OUTSIDE_SNAPSHOT")
    if not export_ref and selected and selected["snapshot_ref"] == snapshot_ref:
        export_ref = selected["export_ref"]
    if export_ref:
        if export_ref["type"] != "ExportArtifact":
            raise ActionRejected("EXPORT_REQUIRED")
        artifact_export(export_ref)

    reviews = [r for r in records if r["ref"]["type"] == "ReviewRecord"]
    superseded = {_key(r["payload"]["review_ref"]) for r in records if r["ref"]["type"] == "ReviewSupersession"}
    reused = defaultdict(list)
    for record in records:
        if record["ref"]["type"] == "ReviewReuse" and record["payload"]["snapshot_ref"] == snapshot_ref:
            reused[_key(record["payload"]["review_ref"])].append(record["ref"])

    # Sources and standards need not each receive a separate audit. Include them
    # when actually targeted, while always exposing content and absent requirements.
    inventory = [snapshot_ref] + [r for r in snapshot["payload"]["refs"] if r["type"] in {"ContentNode", "Requirement"}]
    inventory += [r["ref"] for r in records if r["ref"]["type"] in {"ExportArtifact", "RenderArtifact"}
        and r["payload"].get("snapshot_ref") == snapshot_ref
        and (export_ref is None or (r["ref"] if r["ref"]["type"] == "ExportArtifact" else r["payload"]["export_ref"]) == export_ref)]
    for review in reviews:
        inventory.extend(i["target_ref"] for i in review["payload"]["items"] if _key(i["target_ref"]) in members)
    inventory = list({_key(ref): ref for ref in inventory}.values())
    if target_ref:
        inventory = [target_ref]
    page = inventory[offset:offset + limit]

    changed_sources = {}
    handling = [r for r in records if r["ref"]["type"] == "HandlingRecord"]
    prior_handling = {_key(r["payload"]["previous_handling_ref"]) for r in handling if r["payload"].get("previous_handling_ref")}
    output = []
    for ref in page:
        own_export = artifact_export(ref) if ref["type"] in {"ExportArtifact", "RenderArtifact"} else export_ref
        groups, history = defaultdict(list), []
        for review in reviews:
            payload, rkey = review["payload"], _key(review["ref"])
            current_snapshot = payload["snapshot_ref"] == snapshot_ref or bool(reused[rkey])
            entries = [(i, i["assessment_kind"], i["criterion_ref"], i["scope"], i["target_ref"]) for i in payload["items"]]
            entries += [(c, c["kind"], None, "delivery:" + c["kind"], payload["target_ref"])
                        for c in payload.get("delivery_checks", [])]
            for item, kind, criterion, scope, assessed_target in entries:
                artifacts = item.get("artifact_refs", [])
                direct = _logical(assessed_target) == _logical(ref)
                associated = ref in artifacts
                # Page checks can also be found on the exact export they examine.
                if ref["type"] == "ExportArtifact":
                    associated |= any(a["type"] == "RenderArtifact" and by_key[_key(a)]["payload"]["export_ref"] == ref for a in artifacts)
                if not direct and not associated:
                    continue
                if rkey not in changed_sources:
                    changed_sources[rkey] = contents.changed_review_sources(payload)
                reasons = []
                if rkey in superseded:
                    reasons.append("review_superseded")
                if not current_snapshot:
                    reasons.append("different_snapshot_requires_explicit_reuse")
                if direct and assessed_target != ref:
                    reasons.append("target_version_changed")
                if kind != "content" and artifacts and not contents.item_applies(
                        {"assessment_kind": kind, "artifact_refs": artifacts}, snapshot_ref, own_export):
                    reasons.append("artifact_version_mismatch")
                if changed_sources[rkey]:
                    reasons.append("independent_source_changed")
                applicable = not reasons or (reasons == ["independent_source_changed"] and item["verdict"] == "not_satisfied")
                record = {"review_ref": review["ref"], "review_snapshot_ref": payload["snapshot_ref"],
                    "reviewer_id": review["owner_id"], "task_id": review["task_id"],
                    "assessed_target_ref": assessed_target, "criterion_ref": criterion, "scope": scope,
                    "assessment_kind": kind, "artifact_refs": artifacts, "execution_state": item["execution_state"],
                    "verdict": item["verdict"], "coverage": item["coverage"], "reason": item["reason"],
                    "findings": item.get("findings", []),
                    "observation_receipts": [o["receipt_id"] for o in item["observations"]],
                    "dependency_refs": payload["dependency_refs"], "reuse_refs": reused[rkey],
                    "applicable": applicable, "recheck_reasons": reasons, "changed_source_refs": changed_sources[rkey]}
                history.append(record)
                if applicable:
                    group_key = encode([assessed_target, criterion, scope, kind, sorted(artifacts, key=_key)])
                    groups[group_key].append(record)
        scopes = []
        for group in groups.values():
            # A later pass, block or handled flag does not withdraw a known defect.
            chosen = next((g for g in reversed(group) if g["verdict"] == "not_satisfied"), group[-1])
            latest = group[-1]
            scopes.append({**{k: chosen[k] for k in ("assessed_target_ref", "criterion_ref", "scope", "assessment_kind", "artifact_refs")},
                "verdict": chosen["verdict"], "judgment": chosen,
                "execution_state": latest["execution_state"],
                "latest_execution": {k: latest[k] for k in ("review_ref", "execution_state", "coverage", "reason", "observation_receipts")},
                "review_refs": [g["review_ref"] for g in group],
                "needs_recheck": any(g["recheck_reasons"] for g in group)})
        states = sorted({s["execution_state"] for s in scopes}) or ["not_started"]
        # Historical scope differences are candidates for the reviewer's impact
        # assessment, not code-assigned review tasks. Superseded records remain
        # visible without demanding that their withdrawn judgments be rechecked.
        candidates = [{k: h[k] for k in ("review_ref", "assessed_target_ref", "criterion_ref", "scope", "assessment_kind", "artifact_refs", "recheck_reasons")}
                      for h in history if h["recheck_reasons"] and "review_superseded" not in h["recheck_reasons"]]
        needs_recheck = bool(candidates)
        own_handling = [r for r in handling if r["payload"]["target_ref"] == ref]
        accounting = [{"review_ref": r["ref"], "review_snapshot_ref": r["payload"]["snapshot_ref"], **a,
                       "same_snapshot_not_superseded": r["payload"]["snapshot_ref"] == snapshot_ref
                                  and _key(r["ref"]) not in superseded}
                      for r in reviews for a in r["payload"].get("coverage_accounting", []) if ref in a["target_refs"]]
        entry = {"target_ref": ref, "kind": by_key[_key(ref)]["payload"].get("kind", ref["type"]),
            "overall_verdict": None, "overall_basis": "complete_object_obligations_not_defined",
            "execution_state": states[0] if len(states) == 1 else None,
            "execution_states": states, "execution_scope": "recorded_scopes_only",
            "has_current_review": bool(scopes), "needs_recheck": needs_recheck,
            "has_review_history": bool(history), "recheck_candidates": candidates,
            "applicability": "needs_recheck" if needs_recheck else "current" if scopes else "historical_only" if history else "not_reviewed",
            "scopes": scopes, "review_history": history,
            "coverage_accounting": accounting,
            "handling_records": [{"ref": r["ref"], **r["payload"], "is_latest_in_chain": _key(r["ref"]) not in prior_handling} for r in own_handling],
            "historical_handling_refs": [r["ref"] for r in handling if _logical(r["payload"]["target_ref"]) == _logical(ref) and r["payload"]["target_ref"] != ref]}
        if ref == snapshot_ref and selected and selected["snapshot_ref"] == snapshot_ref and selected["export_ref"] == export_ref:
            entry["delivery_review"] = current_delivery(contents.store)
            entry["overall_verdict"] = entry["delivery_review"]["overall_verdict"]
            entry["overall_basis"] = "selected_delivery_final_review_and_required_coverage"
        output.append(entry)
    return {"snapshot_ref": snapshot_ref, "export_ref": export_ref, "objects": output,
        "total": len(inventory), "offset": offset, "returned_refs": page,
        "next_offset": offset + limit if offset + limit < len(inventory) else None,
        "unreturned_count": len(inventory) - len(page),
        "limitation": "Review-state metadata, not content or page observations. Scoped verdicts belong to reviewers; no whole-object verdict is inferred from a collection of scopes or child passes. Recheck candidates require the reviewer's applicability assessment, not mandatory execution. Choose further checks from goals and evidence."}
