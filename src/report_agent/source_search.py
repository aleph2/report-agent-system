"""Project-bound search presentation; source retrieval and original access stay unchanged."""
from __future__ import annotations

from .errors import ActionRejected
from .store import digest, encode


VERSION = "source-search-view-v1"
CONFIG_KEY = "source_search_view"
BINDING_KEY = "source_search_binding"


def _validate(value):
    if (not isinstance(value, dict) or set(value) != {"version", "default_table_detail"}
            or value["version"] != VERSION or value["default_table_detail"] not in ("references", "full")):
        raise ActionRejected("INVALID_SOURCE_SEARCH_VIEW")
    return value


def bind_source_search(workspace):
    """Validate a trusted existing binding; unconfigured projects retain old defaults."""
    selected = workspace.store.get(CONFIG_KEY)
    bound = workspace.store.get(BINDING_KEY)
    if selected is None and bound is None:
        return None
    if selected is None or not isinstance(bound, dict):
        raise ActionRejected("SOURCE_SEARCH_VIEW_BINDING_CHANGED")
    _validate(selected)
    if (bound.get("configuration") != selected
            or bound.get("clean_import_sha256") != digest(workspace.store.get("clean_import"))):
        raise ActionRejected("SOURCE_SEARCH_VIEW_BINDING_CHANGED")
    return dict(selected)


def configure_source_search(workspace, *, default_table_detail="references"):
    """Trusted preparation only: bind once after a fresh source-only candidate import."""
    selected = _validate({"version": VERSION, "default_table_detail": default_table_detail})
    store = workspace.store
    with store.run_lock():
        if store.get(CONFIG_KEY) is not None or store.get(BINDING_KEY) is not None:
            if bind_source_search(workspace) != selected:
                raise ActionRejected("SOURCE_SEARCH_VIEW_BINDING_CHANGED")
            return selected
        imported = store.get("clean_import")
        required_false = ("copied_results", "copied_reviews", "copied_feedback", "copied_issues",
                          "copied_graph", "copied_checkpoints", "new_ocr")
        if (not isinstance(imported, dict) or any(imported.get(key) is not False for key in required_false)
                or store.get("rubric_targets") or store.get("rubric_reviews")
                or store.get("review_context_experiment") is not None
                or store.get("runtime") is not None or store.get("checkpoint_resume")
                or store.get("task006_call_intent") or (store.root/"checkpoints.db").exists()):
            raise ActionRejected("SOURCE_SEARCH_VIEW_REQUIRES_FRESH_CLEAN_CANDIDATE")
        drafts = [row for row in workspace.results() if row["kind"] == "draft"]
        delivery = store.get("delivery") or {}
        if (len(drafts) != 1 or delivery.get("draft_id") != drafts[0]["id"]
                or any(row["kind"] == "review" for row in workspace.results())):
            raise ActionRejected("SOURCE_SEARCH_VIEW_REQUIRES_FRESH_CLEAN_CANDIDATE")
        with store.connect() as db:
            started = db.execute("SELECT 1 FROM events WHERE kind IN "
                "('deep_model_request','deep_model_response','rubric_review_started','trial_attempt_intent') LIMIT 1").fetchone()
            if started:
                raise ActionRejected("SOURCE_SEARCH_VIEW_REQUIRES_FRESH_CLEAN_CANDIDATE")
            binding = {"configuration": selected, "clean_import_sha256": digest(imported),
                       "initial_draft_id": drafts[0]["id"]}
            db.executemany("INSERT OR REPLACE INTO state(key,value) VALUES (?,?)",
                           [(CONFIG_KEY, encode(selected)), (BINDING_KEY, encode(binding))])
            db.execute("INSERT INTO events(kind,data) VALUES (?,?)",
                       ("source_search_view_bound", encode(binding)))
    return selected


def search_observation(workspace, result, table_detail=None):
    """Present a complete catalog search plus full tables or explicit deferred access."""
    selected = bind_source_search(workspace)
    detail = table_detail if table_detail is not None else (
        selected["default_table_detail"] if selected else "full")
    if detail not in ("references", "full"):
        raise ActionRejected("SOURCE_SEARCH_TABLE_DETAIL_MUST_BE_REFERENCES_OR_FULL")
    from .source_tables import present_source_tables
    return present_source_tables(workspace, result, detail)

