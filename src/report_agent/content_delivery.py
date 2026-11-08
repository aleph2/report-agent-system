"""Live projection of a selected delivery; saved verdicts are immutable evidence."""
from . import legacy_state as legacy
from .content_models import Ref, aggregate, delivery_aggregate
from .content_store import ContentStore


def obligations(contents, snapshot_ref):
    return [{"target_ref": snapshot_ref, "criterion_ref": ref, "scope": "delivery"}
            for ref in contents.read(snapshot_ref)["payload"]["criteria_refs"]]


def _legacy_current_delivery(store):
    selected, final = legacy.get_content_delivery(store), legacy.get_content_final_review(store)
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
    result = _current_delivery(store)
    from .commission_plan import enabled
    if enabled(store):
        from .review_coverage import commission_completion
        cs = ContentStore(store)
        selected = legacy.get_content_delivery(store)
        coverage = commission_completion(cs, cs.read(selected['snapshot_ref']) if selected else None)
        result['commission_coverage'] = coverage
        if not coverage['complete']:
            result.update(status='incomplete', coverage_complete=False, overall_verdict=None)
    return result


def _current_delivery(store):
    """Expose evidence without inventing a snapshot acceptance task or verdict."""
    selected = legacy.get_content_delivery(store)
    if selected and selected.get('review_interface_profile') == 'review-interfaces-v4':
        return _v4_delivery(store, selected)
    if store.manifest.get("review_entrypoint") == "native-rubric-v1":
        return _legacy_current_delivery(store)
    selected = legacy.get_content_delivery(store)
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


def _v4_delivery(store, selected):
    from .task_supervision import reconcile
    from .store import encode
    cs = ContentStore(store)
    basis_task = cs.read(selected['review_basis_assignment_ref']) if selected.get('review_basis_assignment_ref') else None
    basis = basis_task['payload']['review_commission_basis'] if basis_task else None
    basis_digest = basis['digest'] if basis else None
    criteria = basis['criterion_refs'] if basis else []
    owner = basis_task['owner_id'] if basis_task else selected['selected_by']
    relevant_tasks = [t for t in cs.list_objects('DelegatedTask') if t['owner_id'] == owner
        and t['payload'].get('review_snapshot_ref') == selected['snapshot_ref']
        and t['payload'].get('review_requirements')]
    tasks = [t for t in relevant_tasks if basis and t['payload'].get('review_commission_basis', {}).get('digest') == basis_digest]
    prior_tasks = [{'task_ref':t['ref'], 'basis_digest':t['payload'].get('review_commission_basis', {}).get('digest'),
        'basis_state':'recorded' if t['payload'].get('review_commission_basis') else 'not_recorded', 'adopted':False,
        'criterion_refs':t['payload'].get('review_commission_basis', {}).get('criterion_refs'),
        'assigned_scopes':t['payload']['review_requirements'],
        'accounting':reconcile(cs, t['ref']['id'])} for t in relevant_tasks
        if not basis or t['payload'].get('review_commission_basis', {}).get('digest') != basis_digest]
    adopted = {encode(r) for r in selected['adopted_review_task_refs']}
    assigned = {encode(r['criterion_ref']) for t in tasks for r in t['payload']['review_requirements']}
    accounts, items, violations, prior_findings = [], [], [], []
    for task in tasks:
        account = reconcile(cs, task['ref']['id'])
        account['adopted'] = encode(task['ref']) in adopted
        accounts.append(account)
        if not account['adopted']:
            continue
        for result in account['requirements']:
            if result.get('review_ref'):
                item = cs.read(result['review_ref'])['payload']['items'][result['item_index']]
                if cs.item_applies(item, selected['snapshot_ref'], selected['export_ref'], selected.get('workbook_export_ref')):
                    items.append({'review_ref':result['review_ref'], 'item_index':result['item_index'],
                                  'adopted_task_ref':task['ref'], **item})
    # Known defects remain visible even when their task's positive work is not adopted.
    for review in cs.list_objects('ReviewRecord'):
        for index, item in enumerate(review['payload']['items']):
            withdrawn, relevant, _ = cs.review_item_state(review, selected['snapshot_ref'], index)
            if (relevant and not withdrawn and item['verdict'] == 'not_satisfied'
                    and cs.item_applies(item, selected['snapshot_ref'], selected['export_ref'], selected.get('workbook_export_ref'))):
                entry = {'review_ref':review['ref'], 'item_index':index, **item}
                if item['criterion_ref'] in criteria:
                    violations.append(entry)
                else:
                    prior_findings.append({**entry, 'applicability':'prior_standard_requires_review'})
    return {'status':'review_evidence_available' if items else 'not_assessed',
        'overall_verdict':None, 'semantic_coverage_verified':False, 'coverage_complete':None,
        **selected, 'criteria_refs':criteria if basis else None,
        'original_requirement_refs':basis['original_requirement_refs'] if basis else None, 'review_commission_basis':basis,
        'unassigned_criterion_refs':[r for r in criteria if encode(r) not in assigned] if basis else None,
        'review_tasks':accounts, 'prior_basis_tasks':prior_tasks, 'prior_basis_findings':prior_findings,
        'items':items, 'confirmed_violations':violations,
        'delivery_checks':[], 'delivery_violations':[], 'needs_recheck':[],
        'execution_decision':store.get('content_execution_decision'),
        'limitation':'Mechanical assignment and saved-evidence accounting only; no semantic or engineering acceptance.'}
