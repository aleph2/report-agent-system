"""Fork a completed trial's pre-review checkpoint into a new isolated trial.

Trusted, explicit preparation only: no model invocation, OCR, semantic feedback,
graph access, or baseline writes. Execute under WSL, like the production runtime.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from uuid import uuid4

from langchain_core.language_models import BaseChatModel

from report_agent.deep_runtime import project_agent
from report_agent.review import export_configuration, load_rules, reviewer_prompt
from report_agent.store import Store, digest, encode
from report_agent.workspace import Workspace


REVIEW_NODE = "FeedbackRubric.after_agent"
PARENT_NODE = "TodoListMiddleware.after_model"
READ_TOOLS = {"project_status", "read_source_page", "search_sources", "inspect_source_page",
              "analyze_source_image", "calculate", "read_result", "knowledge_search",
              "knowledge_read", "knowledge_traverse", "read_review_export"}
REVIEW_EVENTS = {"rubric_review_started", "rubric_review_observed", "deep_model_request",
                 "deep_model_response", "deep_tool_start", "deep_tool_end", "deep_tool_rejected", "deep_run_finished",
                 "deep_repetition_observed", "vision_request", "vision_response", "vision_reused"}


class NoCallModel(BaseChatModel):
    """Build the native graph without provider configuration or callable inference."""

    model_name: str = "offline-checkpoint-preparation"

    @property
    def _llm_type(self):
        return "offline-no-call"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise RuntimeError("PREPARATION_MUST_NOT_INVOKE_MODEL")

    async def _agenerate(self, *args, **kwargs):
        raise RuntimeError("PREPARATION_MUST_NOT_INVOKE_MODEL")


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def baseline_lock(baseline):
    import fcntl

    # Open the existing lock read-only: preparation must not create baseline files.
    with (baseline / "run.lock").open("rb") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("BASELINE_ALREADY_RUNNING") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def read_database(source):
    # SQLite mode=ro can create WAL sidecars in the source directory. Read a
    # locked byte snapshot instead, preserving any committed WAL pages. SQLite's
    # own backup API then resolves that snapshot into the destination database.
    with tempfile.TemporaryDirectory(prefix="review017-sqlite-") as folder:
        snapshot = Path(folder) / source.name
        shutil.copyfile(source, snapshot)
        wal = source.with_name(source.name + "-wal")
        if wal.exists():
            shutil.copyfile(wal, snapshot.with_name(snapshot.name + "-wal"))
        db = sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            yield db
        finally:
            db.close()


def backup(source, destination):
    with read_database(source) as src:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()


def inspect_baseline(baseline):
    with read_database(baseline / "state.db") as db:
        db.execute("BEGIN")
        state = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM state")}
        results = [json.loads(row[0]) for row in db.execute("SELECT data FROM results ORDER BY rowid")]
        blocks = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal").fetchall()
        if db.execute("SELECT count(*) FROM source_versions").fetchone()[0]:
            raise ValueError("FROZEN_MANIFEST_SOURCES_REQUIRED")
        if db.execute("SELECT count(*) FROM events WHERE kind IN ('feedback_received','human_decision')").fetchone()[0]:
            raise ValueError("HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED")
        event_end = db.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0]
    if state.get("feedback") or any(i.get("decision_origin") for i in state.get("report_issues", [])):
        raise ValueError("HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED")
    if state.get("report_error") or state.get("last_error") or state.get("native_interrupts"):
        raise ValueError("BASELINE_HAS_UNRESOLVED_EXECUTION_STATE")
    if any(result.get("fact_ids") for result in results):
        raise ValueError("GRAPH_DEPENDENT_RESULTS_CANNOT_USE_GRAPH_FREE_IMPORT")
    manifest = state["manifest"]
    if manifest.get("feedback"):
        raise ValueError("HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED")
    source_ids = {s["id"] for s in manifest["sources"]}
    if source_ids != {row[0] for row in blocks}:
        raise ValueError("BASELINE_SOURCE_INDEX_INCOMPLETE")
    if any(set(result.get("source_ids", [])) - source_ids for result in results):
        raise ValueError("RESULT_SOURCE_OUTSIDE_FROZEN_MANIFEST")
    draft_id = (state.get("delivery") or {}).get("draft_id")
    draft = next((r for r in results if r["id"] == draft_id and r["kind"] == "draft"), None)
    if not draft:
        raise ValueError("SELECTED_SAVED_DRAFT_REQUIRED")
    scope = manifest.get("scope_instruction")
    sources = manifest["sources"] + ([scope] if isinstance(scope, dict) and scope.get("copied_path") else [])
    for source in sources:
        relative = Path(source["copied_path"])
        path = baseline / relative
        if relative.is_absolute() or path.is_symlink() or not path.resolve().is_relative_to(baseline / "sources"):
            raise ValueError("SOURCE_PATH_NOT_PROJECT_BOUND")
        if file_hash(path) != source["sha256"]:
            raise ValueError("BASELINE_SOURCE_HASH_MISMATCH")
    return state, results, blocks, sources, draft, event_end


def review_event_boundary(baseline, run_id, state, draft):
    key = run_id + ":0"
    target = state.get("rubric_targets", {}).get(key, {})
    if (target.get("draft_id") != draft["id"] or target.get("draft_body_sha256") !=
            hashlib.sha256(draft["body"].encode()).hexdigest()):
        raise ValueError("BASELINE_REVIEW_TARGET_DOES_NOT_MATCH_SAVED_DRAFT")
    with read_database(baseline / "state.db") as db:
        row = db.execute("SELECT sequence FROM events WHERE kind='rubric_review_started' "
                         "AND json_extract(data,'$.key')=? ORDER BY sequence", (key,)).fetchone()
        if row is None:
            raise ValueError("BASELINE_REVIEW_BOUNDARY_NOT_FOUND")
        boundary = row[0] - 1
        # Never read provider responses or private reasoning; only event kinds and
        # the tool's public role/name are needed to rule out later business writes.
        rows = db.execute("SELECT kind,json_extract(data,'$.role'),json_extract(data,'$.tool'),json_extract(data,'$.type') "
                          "FROM events WHERE sequence>? ORDER BY sequence", (boundary,)).fetchall()
    for kind, role, tool, error_type in rows:
        if kind not in REVIEW_EVENTS:
            raise ValueError("BUSINESS_OR_ERROR_EVENT_AFTER_REVIEW_BOUNDARY: " + kind)
        if kind in {"deep_tool_start", "deep_tool_end", "deep_tool_rejected"} and (role != "rubric_grader" or tool not in READ_TOOLS):
            raise ValueError("NON_REVIEW_TOOL_AFTER_REVIEW_BOUNDARY")
        if kind == "deep_tool_rejected" and error_type not in {"ActionRejected", "ActionForbidden", "ToolInputError"}:
            raise ValueError("UNEXPLAINED_REVIEW_TOOL_ERROR")
        if kind in {"deep_model_request", "deep_model_response"} and role != "rubric_grader":
            raise ValueError("NON_REVIEW_MODEL_AFTER_REVIEW_BOUNDARY")
    return boundary


def copied_files(baseline):
    paths = [baseline / "state.db", baseline / "checkpoints.db"]
    for database in tuple(paths):
        for suffix in ("-wal", "-shm"):
            sidecar = database.with_name(database.name + suffix)
            if sidecar.exists():
                paths.append(sidecar)
    for name in ("sources", "previews", "exports"):
        folder = baseline / name
        if folder.is_symlink():
            raise ValueError("BASELINE_SYMLINK_NOT_ALLOWED")
        if folder.exists():
            for path in sorted(folder.rglob("*")):
                if path.is_symlink() or not path.resolve().is_relative_to(baseline):
                    raise ValueError("BASELINE_SYMLINK_NOT_ALLOWED")
                if path.is_file():
                    paths.append(path)
    return paths


async def prepare(baseline: Path, destination: Path, checkpoint_id: str):
    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
    with baseline_lock(baseline):
        state, results, blocks, sources, draft, event_end = inspect_baseline(baseline)
        files = copied_files(baseline)
        hashes = {str(p.relative_to(baseline)): file_hash(p) for p in files}
        destination.mkdir(parents=True)
        for name in ("state.db", "checkpoints.db"):
            backup(baseline / name, destination / name)
        for path in files:
            if path.parent == baseline:
                continue
            target = destination / path.relative_to(baseline)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if file_hash(target) != hashes[str(path.relative_to(baseline))]:
                raise ValueError("COPIED_FILE_HASH_MISMATCH")
        # Old preview evidence remains readable within the destination. The next
        # native grade creates its own bound preview; no old approval is imported.
        for summary_path in (destination / "previews").glob("*/summary.json"):
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["docx"]["path"] = str(summary_path.parent / "report.docx")
            summary_path.write_text(encode(summary), encoding="utf-8")
        workspace = Workspace(Store(destination))
        workspace.store.set("knowledge_enabled", False)
        workspace.store.set("report_status", "preparation_incomplete")
        workspace.store.set("checkpoint_resume", False)
        rules = load_rules()
        async with project_agent(workspace, lambda role: NoCallModel(), rules=rules) as agent:
            latest = await agent.aget_state({"configurable": {"thread_id": "report"}})
            if latest.next or latest.interrupts or latest.values.get("_rubric_status") != "satisfied":
                raise ValueError("COMPLETED_BASELINE_REVIEW_REQUIRED")
            original = await agent.aget_state({"configurable": {
                "thread_id": "report", "checkpoint_ns": "", "checkpoint_id": checkpoint_id}})
            if (original.next != (REVIEW_NODE,) or original.interrupts or not original.values.get("messages")
                    or original.values.get("_rubric_evaluations") or original.values.get("_rubric_iterations", 0)
                    or original.values.get("_rubric_status") or any(t.error for t in original.tasks)):
                raise ValueError("PRISTINE_PENDING_NATIVE_REVIEW_CHECKPOINT_REQUIRED")
            old_run = original.values.get("_current_grading_run_id")
            if not old_run:
                raise ValueError("BASELINE_GRADING_RUN_ID_REQUIRED")
            boundary = review_event_boundary(baseline, old_run, state, draft)
            reset = agent.report_review_middleware.before_agent(
                {**original.values, "rubric": rules, "_active_rubric": None}, None)
            new_config = await agent.aupdate_state(original.config,
                {**reset, "rubric": rules, "rubric_terminal_handoff": False}, as_node=PARENT_NODE)
            fork = await agent.aget_state(new_config)
            new_run = fork.values.get("_current_grading_run_id")
            if (fork.next != (REVIEW_NODE,) or new_run == old_run or not new_run
                    or fork.values.get("_rubric_evaluations") or fork.values.get("_rubric_iterations") != 0
                    or fork.values.get("_active_rubric") != rules or fork.values.get("rubric") != rules
                    or fork.values.get("messages") != original.values["messages"]
                    or any(t.result or t.error for t in fork.tasks)):
                raise ValueError("NATIVE_REVIEW_FORK_VERIFICATION_FAILED")
        old_attempt = state.get("task006_call_intent")
        with workspace.store.connect() as db:
            db.executemany("DELETE FROM state WHERE key=?", [(key,) for key in (
                "rubric_targets", "rubric_reviews", "rubric_status", "agent_summary", "report_activity",
                "task006_call_intent", "knowledge_project_id", "native_interrupts", "report_error")])
        workspace.store.set("active_rubric_hash", digest(rules))
        workspace.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt()))
        workspace.store.set("knowledge_enabled", False)
        workspace.store.set("report_status", "unreviewed_draft")
        workspace.store.set("delivery", {**state["delivery"], "status": "unreviewed_draft", "review_id": ""})
        workspace.store.set("checkpoint_resume", True)
        if any(file_hash(baseline / path) != value for path, value in hashes.items()):
            raise ValueError("BASELINE_CHANGED_DURING_PREPARATION")
        receipt = {
            "schema": "review-continuation017-v1", "attempt_id": str(uuid4()),
            "baseline": str(baseline), "destination": str(destination), "baseline_files_sha256": hashes,
            "baseline_checkpoint_id": checkpoint_id, "baseline_grading_run_id": old_run,
            "checkpoint_id": new_config["configurable"]["checkpoint_id"], "grading_run_id": new_run,
            "next": list(fork.next), "message_count": len(fork.values["messages"]),
            "baseline_pre_review_event_boundary": boundary, "historical_event_end": event_end,
            "draft_id": draft["id"], "draft_body_sha256": hashlib.sha256(draft["body"].encode()).hexdigest(),
            "source_blocks": len(blocks), "source_blocks_sha256": digest(blocks),
            "sources": [{"id": s.get("id"), "sha256": s["sha256"]} for s in sources],
            "result_ids": [r["id"] for r in results], "results_sha256": digest(results),
            "rubric_hash": digest(rules), "reviewer_prompt_hash": digest(reviewer_prompt()),
            "export_configuration_hash": export_configuration(workspace),
            "baseline_call_intent": old_attempt, "baseline_graph_project_id": state.get("knowledge_project_id"),
            "graph_copied": False, "graph_dependencies": 0, "new_ocr": False,
            "model_calls": 0, "manual_feedback_imported": False, "prior_review_projection_cleared": True,
            "verification": "native pending review only; preserved messages/results/OCR; baseline hashes unchanged",
        }
        workspace.store.set("review_import017", receipt)
        workspace.store.event("review_continuation_prepared", receipt)
        (destination / "import-receipt.json").write_text(encode(receipt), encoding="utf-8")
        return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--checkpoint-id", required=True)
    args = parser.parse_args()
    print(encode(asyncio.run(prepare(args.baseline, args.project, args.checkpoint_id))))
