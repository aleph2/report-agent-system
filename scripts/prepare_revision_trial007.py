"""Import a frozen draft and located sources into an isolated revision trial.

No model calls, OCR, semantic source decisions or imported approval/checkpoint state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from report_agent.catalog import Catalog
from report_agent.store import Store, encode
from report_agent.workspace import Workspace


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(baseline: Path, destination: Path, draft_id: str, feedback: Path, export_config: dict):
    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
    with sqlite3.connect((baseline / "state.db").as_uri() + "?mode=ro", uri=True) as db:
        manifest = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
        row = db.execute("SELECT data FROM results WHERE id=?", (draft_id,)).fetchone()
        if row is None:
            raise ValueError("BASELINE_DRAFT_NOT_FOUND")
        draft = json.loads(row[0])
        if draft["kind"] != "draft":
            raise ValueError("BASELINE_MUST_BE_DRAFT")
        if db.execute("SELECT count(*) FROM source_versions").fetchone()[0]:
            raise ValueError("TRIAL_REQUIRES_FROZEN_MANIFEST_SOURCES")
        blocks = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal").fetchall()
    source_ids = {s["id"] for s in manifest["sources"]}
    if set(draft["source_ids"]) - source_ids or {r[0] for r in blocks} != source_ids:
        raise ValueError("BASELINE_SOURCE_INDEX_INCOMPLETE")
    copies = []
    scope = manifest.get("scope_instruction")
    originals = manifest["sources"] + ([scope] if isinstance(scope, dict) and scope.get("copied_path") else [])
    for source in originals:
        relative = Path(source["copied_path"])
        original = (baseline / relative).resolve()
        target = (destination / relative).resolve()
        if relative.is_absolute() or not original.is_relative_to(baseline / "sources") or not target.is_relative_to(destination / "sources"):
            raise ValueError("SOURCE_PATH_NOT_PROJECT_BOUND")
        if file_hash(original) != source["sha256"]:
            raise ValueError("BASELINE_SOURCE_HASH_MISMATCH")
        copies.append((source, original, target))
    feedback_text = feedback.read_text(encoding="utf-8")
    original_goal = manifest["goal"]
    public_scope = scope.get("text", "") if isinstance(scope, dict) else scope
    manifest["goal"] = original_goal + "\n\n" + feedback_text
    manifest["name"] = "Task007 autonomous revision"
    manifest["export"] = {**export_config, "metadata": {
        **export_config.get("metadata", {}), "scope": public_scope or original_goal}}
    for source, original, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        if file_hash(target) != source["sha256"]:
            raise ValueError("COPIED_SOURCE_HASH_MISMATCH")
    store = Store(destination)
    store.initialize(manifest)
    Catalog(store)
    with store.connect() as db:
        db.execute("DELETE FROM source_blocks")
        db.executemany("INSERT INTO source_blocks VALUES (?,?,?,?)", blocks)
    workspace = Workspace(store)
    workspace.initialize()
    workspace._seed("draft", "Previous unapproved model draft: " + draft["title"], draft["body"], draft["source_ids"])
    imported = workspace.results()[-1]
    receipt = {"baseline": str(baseline), "baseline_draft_id": draft_id,
               "baseline_body_sha256": hashlib.sha256(draft["body"].encode()).hexdigest(),
               "imported_draft_id": imported["id"], "source_blocks": len(blocks),
               "sources": [{"id": s["id"], "sha256": s["sha256"]} for s in manifest["sources"]],
               "feedback_sha256": hashlib.sha256(feedback_text.encode()).hexdigest(),
               "copied_approval": False, "copied_checkpoints": False, "new_ocr": False}
    store.set("revision_import", receipt)
    store.event("revision_imported", receipt)
    (destination / "import-receipt.json").write_text(encode(receipt), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--export-config", type=json.loads, default={"template": "technical_zh"})
    args = parser.parse_args()
    print(encode(prepare(args.baseline, args.project, args.draft_id, args.feedback, args.export_config)))
