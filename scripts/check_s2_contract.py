"""Verify the three S2 contract files against the O3 baseline and dated changes."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
O3_REVISION = "0f495a237e14075608f5ad5602173073e45400bf"
O3_HASHES = {
    "actions.json": "324b61faedaa94b63aaee0c039fadc59e8c9de036b0be98c3ed3d5d72482bb54",
    "checks.sql": "7a251238174ac30ee301e854130ef5fc00acc4bc4a59529c5b8df558a6ffd568",
    "kinds.py": "d0da040f17566a16c113076f4f3ff489d4ad295693aad12fbe54a7687589bc0a"
}


def verify(directory, ledger, *, require_acknowledged=False):
    expected = ledger["baseline_sha256"].copy()
    if ledger["o3_revision"] != O3_REVISION or expected != O3_HASHES:
        raise ValueError("Changed O3 baseline")
    pending = []
    seen = set()
    for change in ledger["changes"]:
        entry = change.get("id", "")
        category = change.get("category")
        status = change.get("status")
        if (not entry.strip() or entry in seen or not change.get("summary", "").strip()
                or not re.fullmatch(r"[a-f0-9]{40}", change.get("revision", ""))
                or category not in {"implementation", "vocabulary", "action", "check"}
                or status not in {"pending", "acknowledged", "deferred", "declined", "accepted_implementation"}
                or (status == "accepted_implementation" and category != "implementation")):
            raise ValueError(f"Invalid amendment entry: {entry}")
        seen.add(entry)
        name = change["file"]
        date.fromisoformat(change["date"])
        if name not in expected or expected[name] != change["before_sha256"]:
            raise ValueError(f"{change['id']}: predecessor does not match {name}")
        expected[name] = change["after_sha256"]
        if status not in {"acknowledged", "accepted_implementation"} or not (change["owner_record"] or "").strip():
            pending.append(change["id"])
    for name, wanted in expected.items():
        # Compare Git's LF text across Linux and Windows checkouts.
        data = (directory / name).read_bytes().replace(b"\r\n", b"\n")
        if sha256(data).hexdigest() != wanted:
            raise ValueError(f"{name}: differs from the recorded contract")
    if require_acknowledged and pending:
        raise ValueError("Owner acknowledgment pending for " + ", ".join(pending))
    return pending


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-acknowledged", action="store_true",
                        help="Also require a recorded owner decision for each change")
    args = parser.parse_args()
    log = json.loads((ROOT / "docs/reviews/s2-amendments.json").read_text(encoding="utf-8"))
    try:
        pending = verify(ROOT / "src/report_agent/assertions/schema", log,
                         require_acknowledged=args.require_acknowledged)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print("All three S2 files match the log.")
    if pending:
        print("Awaiting owner acknowledgment: " + ", ".join(pending))
