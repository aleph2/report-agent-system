"""Read-only review-trial metadata and artifact audit; never deserialize checkpoints."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3


def audit(project: Path, after_sequence: int = 0):
    with sqlite3.connect((project.resolve() / "state.db").as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        # Select only ordinary public observations and metadata, never reasoning.
        kinds = ("deep_run_started", "deep_run_finished", "deep_run_error", "deep_run_cancelled",
                 "deep_model_response", "deep_tool_start", "deep_tool_rejected",
                 "rubric_review_started", "rubric_review_observed", "vision_request",
                 "vision_response", "vision_reused", "vision_error", "result_replaced")
        rows = db.execute("SELECT sequence,at,kind,data FROM events WHERE sequence>? AND kind IN ("
                          + ",".join("?" for _ in kinds) + ") ORDER BY sequence",
                          (after_sequence, *kinds)).fetchall()
        keys = ("delivery", "report_status", "rubric_reviews", "rubric_status", "report_error",
                "checkpoint_resume", "native_interrupts", "knowledge_project_id", "knowledge_enabled", "report_issues",
                "active_rubric_hash", "active_reviewer_prompt_hash", "manifest")
        state = {k: json.loads(v) for k, v in db.execute(
            "SELECT key,value FROM state WHERE key IN (" + ",".join("?" for _ in keys) + ")", keys)}
        results = [json.loads(r[0]) for r in db.execute("SELECT data FROM results ORDER BY rowid")]
        blocks = db.execute("SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal").fetchall()
    events = [(seq, at, kind, json.loads(data)) for seq, at, kind, data in rows]
    starts = [at for _, at, kind, _ in events if kind == "deep_run_started"]
    ends = [at for _, at, kind, _ in events if kind in {"deep_run_finished", "deep_run_error", "deep_run_cancelled"}]
    responses = [data for _, _, kind, data in events if kind == "deep_model_response"]
    tools = [data for _, _, kind, data in events if kind == "deep_tool_start"]
    sources = state.pop("manifest")
    original_rows = sources["sources"] + ([sources["scope_instruction"]] if isinstance(sources.get("scope_instruction"), dict) else [])
    originals = []
    for source in original_rows:
        relative = source.get("copied_path")
        if relative:
            path = (project / relative).resolve()
            if not path.is_relative_to(project.resolve() / "sources"):
                raise ValueError("SOURCE_PATH_OUTSIDE_PROJECT")
            originals.append({"id": source.get("id"), "hash_matches":
                              hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]})
    result = {
        "after_sequence": after_sequence, "started_utc": starts, "ended_utc": ends,
        "elapsed_seconds": (datetime.fromisoformat(ends[-1]) - datetime.fromisoformat(starts[0])).total_seconds() if starts and ends else None,
        "model_responses_by_role": dict(Counter(r["role"] for r in responses)),
        "usage": {k: sum((r.get("usage") or {}).get(k, 0) for r in responses) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "usage_complete": all(r.get("usage") is not None for r in responses),
        "responses_without_usage": sum(not r.get("usage") for r in responses),
        "tool_counts": dict(Counter(t["tool"] for t in tools)),
        "tool_counts_by_role": {role: dict(Counter(t["tool"] for t in tools if t["role"] == role)) for role in sorted({t["role"] for t in tools})},
        "review_events": [{"sequence": seq, "at": at, "kind": kind, **data} for seq, at, kind, data in events if kind.startswith("rubric_")],
        "vision_events": [{"sequence": seq, "at": at, "kind": kind, **data} for seq, at, kind, data in events if kind.startswith("vision_")],
        "rejections": [data for _, _, kind, data in events if kind == "deep_tool_rejected"],
        "state": state,
        "results": [{k: r.get(k) for k in ("id", "kind", "owner", "title", "replaces_id", "source_ids", "input_ids")} |
                    {"body_characters": len(r["body"]), "body_sha256": hashlib.sha256(r["body"].encode()).hexdigest()} for r in results],
        "source_blocks": len(blocks),
        "source_blocks_sha256": hashlib.sha256(json.dumps(blocks, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "original_files": originals,
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--after-sequence", type=int, default=0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.project, args.after_sequence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("started_utc", "ended_utc", "elapsed_seconds", "model_responses_by_role", "usage", "tool_counts")}, ensure_ascii=False))
