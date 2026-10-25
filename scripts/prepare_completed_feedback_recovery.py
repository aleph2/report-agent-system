"""Prepare an isolated completed-report recovery; never invoke a model or rewind state."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import shutil

from prepare_review_trial017 import NoCallModel, backup, baseline_lock, file_hash, read_database
from report_agent.acceptance import MODE, active_criteria, criteria_identity, criteria_rules
from report_agent.deep_runtime import project_agent, project_view
from report_agent.knowledge_state import project_state
from report_agent.review import observation_version, review_delivery
from report_agent.store import Store, digest, encode
from report_agent.workspace import Workspace


ORIGIN = "development_independent_review_not_source_or_human_approval"
PREFIX = "研发独立复核反馈：不是 operator 需求变更、工程决定或工程签发。请依据既有委托与原始资料核查以下观察。\n\n"
DATABASES = ("state.db", "checkpoints.db")
DB_FILES = {name + suffix for name in DATABASES for suffix in ("", "-wal", "-shm")}


def no_links(path: Path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ValueError("SYMLINK_OR_JUNCTION_NOT_ALLOWED")


def tree_hashes(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        no_links(path)
        if not path.resolve().is_relative_to(root):
            raise ValueError("PATH_OUTSIDE_PROJECT")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = file_hash(path)
    return result


def read_public_state(path: Path):
    with read_database(path) as db:
        db.execute("BEGIN")
        schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        state = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM state")}
        results = [json.loads(row[0]) for row in db.execute("SELECT data FROM results ORDER BY rowid")]
        blocks = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal").fetchall()
        if db.execute("SELECT count(*) FROM source_versions").fetchone()[0]:
            raise ValueError("FROZEN_MANIFEST_SOURCES_REQUIRED")
        events = db.execute("SELECT sequence,at,kind,data FROM events ORDER BY sequence").fetchall()
        unchanged_tables = {name: db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                            for name in ("results", "work_items", "result_replacements", "artifacts",
                                         "analyses", "source_versions", "source_blocks")}
    return state, results, blocks, events, schema, digest(unchanged_tables)


def validate_baseline(baseline: Path, public, draft_id: str, expected_hash: str):
    state, results, blocks, events, _, _ = public
    if (state.get("acceptance_mode") != MODE or state.get("knowledge_enabled") is not False
            or any(r.get("fact_ids") for r in results)):
        raise ValueError("REQUIREMENT_ACCEPTANCE_WITHOUT_GRAPH_REQUIRED")
    if (state.get("checkpoint_resume") or state.get("native_interrupts")
            or state.get("report_error") or state.get("last_error")
            or state.get("report_status") in {"running", "failed", "interrupted", "needs_human", "preparation_incomplete"}
            or state.get("rubric_status") != "satisfied"):
        raise ValueError("COMPLETED_SUCCESSFUL_BASELINE_REQUIRED")
    lifecycle = [row[2] for row in events if row[2] in
                 {"deep_run_started", "deep_run_finished", "deep_run_error", "deep_run_cancelled"}]
    if not lifecycle or lifecycle[-1] != "deep_run_finished":
        raise ValueError("COMPLETED_RUN_EVENT_REQUIRED")
    draft = next((r for r in results if r["id"] == draft_id and r["kind"] == "draft"), None)
    if not draft or (state.get("delivery") or {}).get("draft_id") != draft_id:
        raise ValueError("EXACT_SELECTED_DRAFT_REQUIRED")
    if hashlib.sha256(draft["body"].encode()).hexdigest() != expected_hash:
        raise ValueError("DRAFT_BODY_HASH_MISMATCH")
    manifest = state["manifest"]
    sources = list(manifest["sources"])
    ids = {s["id"] for s in sources}
    if ids != {b[0] for b in blocks} or any(set(r.get("source_ids", [])) - ids for r in results):
        raise ValueError("SOURCE_INDEX_OR_RESULT_BINDING_INVALID")
    scope = manifest.get("scope_instruction")
    if isinstance(scope, dict) and scope.get("copied_path"):
        sources.append(scope)
    for source in sources:
        relative = Path(source["copied_path"])
        path = (baseline / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(baseline / "sources"):
            raise ValueError("SOURCE_PATH_NOT_PROJECT_BOUND")
        if not path.is_file() or file_hash(path) != source["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH")
    return sources


def relocate_previews(baseline: Path, destination: Path):
    changes = []
    for path in sorted((destination / "previews").glob("*/summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        old = summary["docx"]["path"]
        original = Path(old)
        expected_relative = path.parent.relative_to(destination) / "report.docx"
        if not original.is_absolute() or original.resolve() != baseline / expected_relative:
            raise ValueError("PREVIEW_PATH_NOT_BASELINE_BOUND")
        target = (destination / expected_relative).resolve()
        if not target.is_relative_to(destination) or file_hash(target) != summary["docx"]["sha256"]:
            raise ValueError("PREVIEW_COPY_HASH_MISMATCH")
        before = file_hash(path)
        summary["docx"]["path"] = str(target)
        path.write_text(encode(summary), encoding="utf-8")
        changes.append({"file": path.relative_to(destination).as_posix(), "field": "docx.path",
                        "old": old, "new": str(target), "before_sha256": before,
                        "after_sha256": file_hash(path)})
    return changes


async def prepare(baseline: Path, destination: Path, feedback: Path,
                  draft_id: str, expected_body_sha256: str):
    for path in (baseline, destination, feedback):
        no_links(path.absolute())
    baseline, destination, feedback = baseline.resolve(), destination.resolve(), feedback.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_body_sha256):
        raise ValueError("EXPLICIT_SHA256_REQUIRED")
    feedback_bytes = feedback.read_bytes()
    feedback_text = feedback_bytes.decode("utf-8").strip()
    if not feedback_text:
        raise ValueError("FEEDBACK_REQUIRED")
    description = PREFIX + feedback_text
    with baseline_lock(baseline):
        baseline_hashes = tree_hashes(baseline)
        if not all(name in baseline_hashes for name in DATABASES):
            raise ValueError("COMPLETED_PROJECT_DATABASES_REQUIRED")
        original = read_public_state(baseline / "state.db")
        sources = validate_baseline(baseline, original, draft_id, expected_body_sha256)
        old_state, old_results, blocks, events, old_schema, unchanged_hash = original
        destination.mkdir(parents=True)
        try:
            for name in DATABASES:
                backup(baseline / name, destination / name)
            for relative, expected in baseline_hashes.items():
                if relative in DB_FILES or relative == "run.lock":
                    continue
                target = (destination / relative).resolve()
                if not target.is_relative_to(destination):
                    raise ValueError("COPY_PATH_OUTSIDE_DESTINATION")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(baseline / relative, target)
                if file_hash(target) != expected:
                    raise ValueError("COPIED_FILE_HASH_MISMATCH")
            path_changes = relocate_previews(baseline, destination)
            workspace = Workspace(Store(destination))
            with workspace.store.run_lock():
                criteria = active_criteria(workspace)
                if not criteria or not criteria["current"]:
                    raise ValueError("CURRENT_ORIGINAL_CRITERIA_REQUIRED")
                identity = criteria_identity(criteria)
                before_review = review_delivery(workspace, draft_id)
                if before_review["status"] != "reviewed_draft":
                    raise ValueError("EXACT_HISTORICAL_SATISFIED_REVIEW_REQUIRED")
                checkpoint_before = file_hash(destination / "checkpoints.db")
                async with project_agent(workspace, lambda role: NoCallModel(),
                                         rules=criteria_rules(criteria)) as agent:
                    snapshot = await agent.aget_state({"configurable": {"thread_id": "report"}})
                    # Do not access .values, .tasks, message bodies or private reasoning.
                    checkpoint = snapshot.config.get("configurable", {}).get("checkpoint_id")
                    terminal = {"checkpoint_id": checkpoint, "next": list(snapshot.next),
                                "interrupt_count": len(snapshot.interrupts),
                                "step": (snapshot.metadata or {}).get("step"),
                                "source": (snapshot.metadata or {}).get("source")}
                    if not checkpoint or snapshot.next or snapshot.interrupts:
                        raise ValueError("TERMINAL_CHECKPOINT_REQUIRED")
                if file_hash(destination / "checkpoints.db") != checkpoint_before:
                    raise ValueError("CHECKPOINT_CHANGED_DURING_READ")
                old_observation = observation_version(workspace, draft_id)
                correction = workspace.request_correction(draft_id, description)
                if correction["status"] != "pending":
                    raise ValueError("NEW_PENDING_CORRECTION_REQUIRED")
                after_review = review_delivery(workspace, draft_id)
                view = project_view(workspace)
                if (after_review["status"] != "needs_attention"
                        or after_review["rubric_review"] != before_review["rubric_review"]
                        or observation_version(workspace, draft_id) == old_observation
                        or not any(c["id"] == correction["id"] and c["description"] == description
                                   for c in view["corrections"])):
                    raise ValueError("CORRECTION_PROJECTION_OR_VISIBILITY_INVALID")
                if project_state(workspace)["status"] == "reviewed_draft":
                    raise ValueError("RECOVERY_WOULD_SKIP_COORDINATOR")
                if criteria_identity(active_criteria(workspace)) != identity or not active_criteria(workspace)["current"]:
                    raise ValueError("ORIGINAL_CRITERIA_CHANGED")
                record = {"origin": ORIGIN, "target_id": draft_id, "correction_id": correction["id"],
                          "feedback_file": str(feedback), "feedback_sha256": hashlib.sha256(feedback_bytes).hexdigest(),
                          "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
                          "baseline": str(baseline), "body_sha256": expected_body_sha256,
                          "delivery": "Saved as a result-bound correction. Actual model receipt must be audited separately."}
                workspace.store.event("development_feedback_delivered", record)
                current = read_public_state(destination / "state.db")
                new_state, new_results, new_blocks, new_events, new_schema, new_unchanged_hash = current
                changed_keys = sorted(k for k in set(old_state) | set(new_state) if old_state.get(k) != new_state.get(k))
                if (changed_keys != ["corrections"] or new_results != old_results or new_blocks != blocks
                        or new_schema != old_schema or new_unchanged_hash != unchanged_hash
                        or new_events[:len(events)] != events
                        or [r[2] for r in new_events[len(events):]] != ["correction_requested", "development_feedback_delivered"]):
                    raise ValueError("UNDECLARED_BUSINESS_OR_HISTORY_CHANGE")
                if tree_hashes(baseline) != baseline_hashes or feedback.read_bytes() != feedback_bytes:
                    raise ValueError("BASELINE_OR_FEEDBACK_CHANGED")
                receipt = {"schema": "completed-feedback-recovery-v1", "status": "prepared",
                    "baseline": str(baseline), "destination": str(destination),
                    "baseline_files_sha256": baseline_hashes,
                    "copied_files": sorted(set(baseline_hashes) - DB_FILES - {"run.lock"}),
                    "database_copy": "SQLite backup from locked temporary main/WAL byte snapshots; no rewind or checkpoint update.",
                    "checkpoint": terminal, "copied_checkpoint_sha256": checkpoint_before,
                    "path_changes": path_changes, "state_keys_changed": changed_keys,
                    "new_event_kinds": [r[2] for r in new_events[len(events):]],
                    "historical_event_end": events[-1][0], "prepared_event_end": new_events[-1][0],
                    "results_sha256": digest(old_results), "source_blocks_sha256": digest(blocks),
                    "sources": [{k: s[k] for k in ("copied_path", "sha256")} for s in sources],
                    "acceptance_identity": identity, "feedback": record,
                    "historical_grading_run_id": before_review["rubric_review"]["grading_run_id"],
                    "review_projection_before": before_review["status"], "review_projection_after": after_review["status"],
                    "historical_reviews_unchanged": True, "project_view_contains_correction": True,
                    "new_grading_run_not_yet_started": True, "baseline_unchanged": True,
                    "model_calls": 0, "new_ocr": False, "graph_used": False,
                    "script_sha256": file_hash(Path(__file__))}
                (destination / "feedback-recovery-receipt.json").write_text(encode(receipt), encoding="utf-8")
                return receipt
        except Exception:
            # Never reuse or auto-launch a partial destination; retain it for inspection.
            (destination / "feedback-recovery-incomplete.json").write_text(
                encode({"status": "preparation_failed", "launch": "forbidden_without_successful_receipt"}), encoding="utf-8")
            if tree_hashes(baseline) != baseline_hashes:
                raise RuntimeError("BASELINE_CHANGED_DURING_FAILED_PREPARATION") from None
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--expected-body-sha256", required=True)
    args = parser.parse_args()
    result = asyncio.run(prepare(args.baseline, args.destination, args.feedback, args.draft_id,
                                 args.expected_body_sha256))
    print(encode({k: result[k] for k in ("status", "destination", "model_calls", "baseline_unchanged")}))
