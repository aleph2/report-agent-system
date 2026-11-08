"""The O3 contract comprises the vocabulary, action catalog and SQL checks."""
from copy import deepcopy
import json
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src/report_agent/assertions/schema"
LOG = ROOT / "docs/reviews/s2-amendments.json"


def check(directory=SCHEMA, ledger=None, *, require_acknowledged=False):
    verify = run_path(str(ROOT / "scripts/check_s2_contract.py"))["verify"]
    return verify(directory, json.loads(LOG.read_text()) if ledger is None else ledger,
                  require_acknowledged=require_acknowledged)


def test_current_contract_matches_dated_log():
    check()


@pytest.mark.parametrize("changed", ["actions.json", "checks.sql", "kinds.py"])
def test_unrecorded_file_change_fails(tmp_path, changed):
    for name in ["actions.json", "checks.sql", "kinds.py"]:
        (tmp_path / name).write_bytes((SCHEMA / name).read_bytes() + (b"\n" if name == changed else b""))
    with pytest.raises(ValueError, match=changed.replace(".", r"\.")):
        check(tmp_path)


def test_logged_change_needs_owner_reference_for_milestone():
    ledger = json.loads(LOG.read_text())
    proposal = deepcopy(ledger)
    entry = proposal["changes"][-1]
    entry["status"] = "pending"
    entry["owner_record"] = None
    with pytest.raises(ValueError, match=entry["id"]):
        check(ledger=proposal, require_acknowledged=True)
    for change in proposal["changes"]:
        change["status"] = "acknowledged"
        change["owner_record"] = "synthetic owner decision for this test"
    check(ledger=proposal, require_acknowledged=True)


def test_discontinuous_amendment_fails():
    ledger = json.loads(LOG.read_text())
    ledger["changes"][-1]["before_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="predecessor"):
        check(ledger=ledger)


def test_current_vocabulary_cannot_be_declared_the_original_approved_baseline():
    ledger = json.loads(LOG.read_text())
    ledger["baseline_sha256"]["kinds.py"] = ledger["changes"][-1]["after_sha256"]
    ledger["changes"] = []
    with pytest.raises(ValueError, match="O3 baseline"):
        check(ledger=ledger, require_acknowledged=True)

@pytest.mark.parametrize("decision", ["deferred", "declined"])
def test_owner_reference_alone_cannot_authorize_milestone(decision):
    ledger = json.loads(LOG.read_text())
    for change in ledger["changes"]:
        change.update(status="acknowledged", owner_record="synthetic acceptance")
    ledger["changes"][-1].update(status=decision, owner_record="synthetic decision to wait")
    with pytest.raises(ValueError, match=ledger["changes"][-1]["id"]):
        check(ledger=ledger, require_acknowledged=True)


@pytest.mark.parametrize("mistake", ["duplicate_id", "missing_revision", "blank_summary"])
def test_recorded_changes_are_individually_traceable(mistake):
    ledger = json.loads(LOG.read_text())
    entry = ledger["changes"][-1]
    if mistake == "duplicate_id":
        entry["id"] = ledger["changes"][0]["id"]
    elif mistake == "missing_revision":
        del entry["revision"]
    else:
        entry["summary"] = " "
    with pytest.raises(ValueError, match="amendment entry"):
        check(ledger=ledger)
