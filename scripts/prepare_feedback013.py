"""Deliver development review observations, without fabricating business decisions."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from report_agent.store import Store
from report_agent.workspace import Workspace


def prepare(project, feedback_path, evidence):
    ws = Workspace(Store(project))
    feedback = feedback_path.read_text(encoding="utf-8")
    with ws.store.run_lock():
        evidence.mkdir(parents=True, exist_ok=True)
        for name in ("state.db", "checkpoints.db"):
            source = project / name
            destination = evidence / name
            if source.exists() and not destination.exists():
                with sqlite3.connect(source) as original, sqlite3.connect(destination) as saved:
                    original.backup(saved)
        drafts = [r for r in ws.results() if r["kind"] == "draft"]
        target = drafts[-1]
        correction = ws.request_correction(target["id"], feedback)
        record = {"target_id": target["id"], "correction_id": correction["id"],
                  "feedback_sha256": hashlib.sha256(feedback.encode()).hexdigest(),
                  "origin": "development_independent_review_not_source_or_human_approval",
                  "delivery": "Persisted as project feedback; model receipt must be verified separately."}
        ws.store.event("development_feedback_delivered", record)
        (evidence / "feedback-receipt.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.project, args.feedback, args.evidence)
