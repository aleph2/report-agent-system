"""Offline real-report preservation/export check; not generation or model acceptance.

Copies verified source inputs from this independent application's baseline, never
its old reviews, checkpoints or claimed adoption history. Output must be a new directory.
"""
import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path

from report_agent.content_export import export_snapshot, render_export
from report_agent.content_store import Actor, ContentStore
from report_agent.store import Store, encode


def run(baseline, destination, draft_id):
    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
    with sqlite3.connect((baseline / "state.db").as_uri() + "?mode=ro", uri=True) as db:
        manifest = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
        draft = json.loads(db.execute("SELECT data FROM results WHERE id=?", (draft_id,)).fetchone()[0])
        criteria = [json.loads(row[0]) for row in db.execute("SELECT data FROM results")]
    standard = next(r for r in criteria if r["kind"] == "acceptance" and r["id"] in draft["input_ids"])
    manifest = {k: manifest[k] for k in ("goal", "sources", "scope_instruction") if k in manifest}
    for source in manifest["sources"]:
        if not source.get("copied_path"):
            continue
        path = (baseline / source["copied_path"]).resolve()
        target = (destination / source["copied_path"]).resolve()
        if not path.is_relative_to(baseline / "sources") or not target.is_relative_to(destination / "sources"):
            raise ValueError("SOURCE_PATH_OUTSIDE_PROJECT")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    manifest["content_contract"] = "hierarchical-review-v1"
    store = Store(destination)
    store.initialize(manifest)
    cs, actor = ContentStore(store), Actor("offline-import", "coordinator", "real-report-preservation-check")
    inputs = cs.import_inputs(actor, "inputs", [s["id"] for s in manifest["sources"]])["result"]
    objects = []
    for index, c in enumerate(json.loads(standard["body"])["criteria"]):
        objects.append({"client_key": "k" + str(index), "type": "Criterion", "payload": {
            "requirement_refs": inputs["requirement_refs"], "purpose": "Preserve prior acceptance definition for offline comparison",
            "scope": c["scope"], "expected_outcome": c["condition"], "evidence_expectation": c["evidence_expectation"],
            "allowed_limits": c["allowed_limitations"]}})
    objects.append({"client_key": "root", "type": "ContentNode", "payload": {"kind": "report",
        "body": {"text": draft["title"]}, "qualifiers": {}, "claim_kind": "structure"}})
    chunks = [part for part in re.split(r"(?m)(?=^#{1,3} )", draft["body"]) if part]
    assert "".join(chunks) == draft["body"]
    for index, chunk in enumerate(chunks):
        key = "block" + str(index)
        objects.extend([
            {"client_key": key, "type": "ContentNode", "payload": {"kind": "block", "body": {"text": chunk},
                "qualifiers": {}, "claim_kind": "inference"}},
            {"client_key": "contains" + str(index), "type": "Relation", "payload": {"subject_ref": {"client_key": "root"},
                "object_ref": {"client_key": key}, "predicate": "contains", "position": index, "provenance_kind": "observed_only"}}])
    refs = cs.commit(actor, "import-report", objects)["result"]["refs"]
    frozen = cs.freeze(actor, "freeze", refs["root"], [*inputs["requirement_refs"], *inputs["source_refs"], *refs.values()])["result"]
    exported = export_snapshot(cs, actor, "export", frozen["snapshot_ref"])["result"]
    rendered = render_export(cs, actor, "render", exported["export_ref"])["result"]
    result = {"scope": "Real complete report, deterministic preservation/export/render only; no model generation, semantic review or quality acceptance.",
        "baseline": str(baseline), "original_draft_id": draft_id, "original_body_sha256": hashlib.sha256(draft["body"].encode()).hexdigest(),
        "characters_preserved": len(draft["body"]), "content_blocks": len(chunks), "source_count": len(inputs["source_refs"]),
        "adoption_history_imported": False, "prior_reviews_imported": False, **frozen, **exported, "render": rendered}
    (destination / "check-result.json").write_text(encode(result), encoding="utf-8")
    print(encode(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--draft-id", required=True)
    args = parser.parse_args()
    run(args.baseline, args.output, args.draft_id)
