"""Isolated full-report review via the actual runtime and official DeepSeek service."""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from dotenv import dotenv_values

from report_agent.content_export import export_snapshot, render_export
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from report_agent.store import Store, encode
from report_agent.workspace import Workspace


def service(env_file):
    config = dotenv_values(env_file)
    values = {k: config.get("HIGHWAY_MODEL_" + k) for k in ("NAME", "BASE_URL", "API_KEY")}
    if values["NAME"] != "deepseek-flash" or (values["BASE_URL"] or "").rstrip("/") != "https://api.deepseek.com" or not values["API_KEY"]:
        raise ValueError("OFFICIAL_DEEPSEEK_CONFIGURATION_REQUIRED")
    for target, source in (("REPORT_MODEL", "NAME"), ("REPORT_BASE_URL", "BASE_URL"), ("REPORT_API_KEY", "API_KEY")):
        os.environ[target] = values[source]
    os.environ.pop("REPORT_GRADER_MODEL", None)
    os.environ["REPORT_REASONING_EFFORT"] = "max"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return {"model": values["NAME"], "base_url": values["BASE_URL"], "reasoning_effort": "max",
            "max_tokens": 131072, "max_retries": 0, "thinking": {"type": "enabled"}}


def prepare(baseline, destination):
    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
    with sqlite3.connect((baseline / "state.db").as_uri() + "?mode=ro", uri=True) as db:
        manifest = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
        records = [json.loads(r[0]) for r in db.execute("SELECT data FROM content_versions ORDER BY rowid")]
    old_snapshot = next(r for r in reversed(records) if r["ref"]["type"] == "DocumentSnapshot")
    objects = [r for r in records if r["ref"] in old_snapshot["payload"]["refs"]
               and r["ref"]["type"] in {"Criterion", "ContentNode", "Relation"}]
    if any(r["ref"]["type"] == "Evidence" for r in records):
        raise ValueError("PREPARER_EXPECTS_PRESERVED_REPORT_NOT_ADOPTION_HISTORY")
    for source in manifest["sources"]:
        if not source.get("copied_path"):
            continue
        path, target = (baseline / source["copied_path"]).resolve(), (destination / source["copied_path"]).resolve()
        if not path.is_relative_to(baseline / "sources") or not target.is_relative_to(destination / "sources"):
            raise ValueError("SOURCE_PATH_OUTSIDE_PROJECT")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("SOURCE_HASH_MISMATCH")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    manifest = {k: v for k, v in manifest.items() if k in {"goal", "sources", "scope_instruction"}}
    manifest.update(content_contract="hierarchical-review-v1", coverage_contract="object-coverage-v1", trial_service="deepseek-official")
    store = Store(destination)
    store.initialize(manifest)
    cs, actor = ContentStore(store), actor_for("coordinator")
    inputs = cs.import_inputs(actor, "inputs", [s["id"] for s in manifest["sources"]])["result"]
    keys = {encode(r["ref"]): "import" + str(i) for i, r in enumerate(objects)}
    def remap(value):
        if isinstance(value, dict):
            if set(value) == {"type", "id", "version"}:
                return {"client_key": keys[encode(value)]}
            return {k: remap(v) for k, v in value.items()}
        return [remap(v) for v in value] if isinstance(value, list) else value
    batch = []
    for record in objects:
        payload = record["payload"]
        if record["ref"]["type"] == "Criterion":
            payload = {**payload, "requirement_refs": inputs["requirement_refs"]}
        else:
            payload = remap(payload)
        batch.append({"client_key": keys[encode(record["ref"])], "type": record["ref"]["type"], "payload": payload})
    refs = cs.commit(actor, "import-report", batch)["result"]["refs"]
    snap = cs.freeze(actor, "freeze", refs[keys[encode(old_snapshot["payload"]["root_ref"])]],
                     inputs["requirement_refs"] + inputs["source_refs"] + list(refs.values()))["result"]["snapshot_ref"]
    export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
    render = render_export(cs, actor, "render", export)["result"]
    instruction = ("本次为现有完整报告的独立审核实测。审核所选快照与成品，保留原文和既有标准，"
                   "自主调查并记录问题、覆盖缺口及后续建议；本轮保留未解决结果，不改写或重生成报告，"
                   "不要把阶段性稿件当成已验收。审核不需要等待用户确认启动；没有预置错误答案。")
    store.set("content_delivery", {"snapshot_ref": snap, "export_ref": export, "ending_reason": "preserve_unresolved", "trial_instruction": instruction})
    store.set("knowledge_enabled", False)
    before = [(r["ref"]["type"], r["payload"]) for r in objects if r["ref"]["type"] == "ContentNode"]
    after = [(r["ref"]["type"], r["payload"]) for r in cs.list_objects("ContentNode")]
    if before != after:
        raise ValueError("REPORT_PRESERVATION_FAILED")
    result = {"baseline": str(baseline), "scope": "complete existing report review, not new report generation",
              "prior_reviews_imported": False, "prior_checkpoints_imported": False,
              "source_count": len(inputs["source_refs"]), "content_nodes": len(after),
              "report_payload_sha256": hashlib.sha256(encode(after).encode()).hexdigest(),
              "snapshot_ref": snap, "export_ref": export, "render": render}
    (destination / "preparation.json").write_text(encode(result), encoding="utf-8")
    return result


def prepare_inputs_only(baseline, destination):
    """Start a clean full run using only the authorized source/OCR snapshot."""
    from import_verified_sources import rows_hash
    from prepare_clean_trial009 import prepare as prepare_clean

    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError("NEW_ISOLATED_DESTINATION_REQUIRED")
    with sqlite3.connect((baseline / "state.db").as_uri() + "?mode=ro", uri=True) as db:
        original = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
        for source in original["sources"]:
            rows = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal",
                              (source["id"],)).fetchall()
            if len(rows) != source.get("blocks") or rows_hash(rows) != source.get("blocks_sha256"):
                raise ValueError("FROZEN_SOURCE_BLOCKS_MISMATCH")
    receipt = prepare_clean(baseline, destination)
    store = Store(destination)
    manifest = store.manifest
    manifest.update(content_contract="hierarchical-review-v1", coverage_contract="object-coverage-v1", trial_service="deepseek-official")
    store.set("manifest", manifest)
    with store.connect() as db:
        for source in manifest["sources"]:
            rows = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal",
                              (source["id"],)).fetchall()
            if len(rows) != source["blocks"] or rows_hash(rows) != source["blocks_sha256"]:
                raise ValueError("COPIED_SOURCE_BLOCKS_MISMATCH")
    store.set("knowledge_enabled", False)
    cs = ContentStore(store)
    assert not cs.list_objects()
    result = {"scope": "clean end-to-end from coordinator; no prior plan, criteria, report, reviews or checkpoints",
              "baseline": str(baseline), "source_count": len(manifest["sources"]),
              "source_blocks": receipt["source_blocks"], "source_index_sha256": receipt["source_index_sha256"],
              "existing_content_objects": 0, "original_commission_preserved": True}
    (destination / "preparation.json").write_text(encode(result), encoding="utf-8")
    return result


async def run(project, env_file, resume):
    settings = service(env_file)
    store = Store(project)
    if store.get("live_trial_intent") and not resume:
        raise ValueError("ATTEMPT_EXISTS_INSPECT_BEFORE_RESUME")
    root = Path(__file__).resolve().parents[1]
    code = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "src/report_agent").rglob("*")) if p.suffix in {".py", ".md"}}
    store.set("live_trial_intent", {"authorization": "User requested deployment/real data testing and specifically DeepSeek service",
                                   "settings": settings, "resume": resume, "code_sha256": code})
    result = await run_report(Workspace(store))
    summary = {k: result.get(k) for k in ("status", "last_error", "content_delivery", "content_final_review")}
    summary["settings"] = settings
    (project / "live-result.json").write_text(encode(summary), encoding="utf-8")
    print(encode(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--prepare-inputs-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=18159)
    args = parser.parse_args()
    if args.prepare_inputs_only:
        print(encode(prepare_inputs_only(args.baseline, args.project)))
    elif args.prepare:
        print(encode(prepare(args.baseline, args.project)))
    elif args.serve:
        import uvicorn
        from report_agent.webapp import create_app
        service(args.env_file)
        uvicorn.run(create_app(args.project), host="127.0.0.1", port=args.port)
    else:
        asyncio.run(run(args.project, args.env_file, args.resume))
