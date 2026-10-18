"""Read-only freshness projection; graph content is never duplicated in SQL."""
from datetime import datetime, timezone

from .deep_models import error_data


def inspect_evidence(workspace, result_ids, knowledge=None):
    ids = workspace.collect_fact_ids(result_ids)
    checked_at = datetime.now(timezone.utc).isoformat()
    if not ids:
        return {"status": "not_used", "fact_ids": [], "facts": [], "checked_at": checked_at}
    owned = None
    try:
        if hasattr(workspace, "store") and workspace.store.get("knowledge_enabled", True) is False:
            raise RuntimeError("KNOWLEDGE_DISABLED_WITH_ADOPTED_FACTS")
        if knowledge is None:
            from .knowledge import Knowledge
            project_id = workspace.store.get("knowledge_project_id")
            if not project_id:
                raise RuntimeError("KNOWLEDGE_PROJECT_NOT_BOUND")
            owned = knowledge = Knowledge(project_id, embedding=False, writable=False)
        facts = knowledge.read_many(ids)
        changed = [f["id"] for f in facts if not f["current"]]
        return {"status": "needs_assessment" if changed else "current", "fact_ids": ids,
                "changed_fact_ids": changed, "facts": facts, "checked_at": checked_at}
    except Exception as exc:
        return {"status": "unknown", "fact_ids": ids, "facts": [], "checked_at": checked_at,
                "error": {**error_data(exc), "message": "KNOWLEDGE_VALIDITY_CHECK_FAILED"}}
    finally:
        if owned is not None:
            owned.close()


def delivery_state(workspace, draft_id, review_id="", knowledge=None):
    state = workspace.delivery(draft_id, review_id)
    native = hasattr(workspace, "store") and workspace.store.get("active_rubric_hash")
    if native:
        from .review import review_delivery
        state = review_delivery(workspace, draft_id)
    evidence = inspect_evidence(workspace, [draft_id, state["review_id"]] if state["review_id"] else [draft_id], knowledge)
    state["knowledge"] = {k: v for k, v in evidence.items() if k != "facts"}
    if evidence["status"] == "unknown":
        state["status"] = "system_error"
    elif not native and evidence["status"] == "needs_assessment" and state["status"] == "reviewed_draft":
        state["status"] = "needs_attention"
    return state, evidence


def project_state(workspace, knowledge=None):
    state = workspace.status()
    from .hierarchical_tools import enabled as content_enabled
    if content_enabled(workspace):
        from .content_delivery import current_delivery
        projection = current_delivery(workspace.store)
        state.update(content_contract="hierarchical-review-v1",
                     content_current_review=projection,
                     content_delivery=workspace.store.get("content_delivery"),
                     content_final_review=workspace.store.get("content_final_review"),
                     content_execution_decision=workspace.store.get("content_execution_decision"),
                     content_execution_limitation=workspace.store.get("content_execution_limitation"))
        state["execution_status"] = state["status"]
        if workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1" and state["status"] not in {"running", "failed", "interrupted", "needs_human"}:
            if state["content_delivery"] or state["status"] == "reviewed_draft":
                state["status"] = projection["status"]
        return state
    limitation = workspace.store.get("acceptance_limitation") if hasattr(workspace, "store") else None
    if limitation:
        state["acceptance_limitation"] = limitation
    if state["delivery"]:
        old = state["delivery"]
        state["delivery"], _ = delivery_state(workspace, old["draft_id"], old["review_id"], knowledge)
        if state["status"] not in {"running", "failed", "interrupted"}:
            state["status"] = state["delivery"]["status"]
        evidence = state["delivery"]["knowledge"]
        if evidence.get("error"):
            state["last_error"] = state["last_error"] or evidence["error"]
    return state
