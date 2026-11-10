import pytest

from report_agent.assertions.ids import request_digest
from .test_production_fake03 import Commission


def test_judgment_submission_is_bound_to_packet_and_exact_receipt(tmp_path):
    case = Commission(tmp_path, deferred=True)
    initial = case.submit("A/X51", pending=True)
    assert "submission_receipt" not in initial["claim"]
    receipt = {"input": {"missing": "Unreported pit count"}, "rank": 9}
    key = request_digest(receipt)
    claim = {**initial["claim"], "submission_receipt": key}
    with pytest.raises(ValueError, match="C4"):
        case.call("writer", "save_judgment", "A", claim, initial["grounds"])
    case.packet.add(key)
    case.resources["receipts"] = {key: {"rank": 10}}
    with pytest.raises(ValueError, match="C4"):
        case.call("writer", "save_judgment", "A", claim, initial["grounds"])
    case.resources["receipts"] = {key: receipt}
    # Use a fresh commission store for the accepted grant: the invalid host pin
    # above cannot be replaced in the same archive.
    other = Commission(tmp_path / "valid", deferred=True)
    row = other.submit("A/X51", pending=True)
    other.packet.add(key)
    other.resources["receipts"] = {key: receipt}
    accepted = other.call("writer", "save_judgment", "A",
                          {**row["claim"], "submission_receipt": key}, row["grounds"])
    assert accepted["claim"]["submission_receipt"] == key
    from report_agent import assertions
    from report_agent.assertion_host import Grant
    from uuid import uuid4
    narrow = Grant(str(uuid4()), "reviewer", "review-receipt", "narrow", "plan",
                   {"A"}, {accepted["id"]}, set())
    ctx = other.host.issue_once(narrow, "ask", "read")
    assert "submission_receipt" not in assertions.packet(ctx)[0]["claim"]



def _submission_case(root):
    case = Commission(root, deferred=True)
    earlier = case.submit("A/X51", pending=True)
    receipt = {"input": {"missing": "Unreported pit count"}, "rank": 9}
    key = request_digest(receipt)
    unrelated = {"internal": "uncommitted receipt marker"}
    case.packet.add(key)
    case.resources["receipts"] = {key: receipt, request_digest(unrelated): unrelated}
    row = case.call("writer", "save_judgment", "A",
                    {**earlier["claim"], "submission_receipt": key}, earlier["grounds"])
    return case.host.commission, row, earlier, receipt


def test_committed_submission_roundtrips_without_launch_authority(tmp_path):
    from report_agent.assertions.launch import Commission as Archive
    archive = tmp_path / "assertions.jsonl"
    commission, row, earlier, receipt = _submission_case(tmp_path / "live")
    commission.export(archive)
    assert b'uncommitted receipt marker' not in archive.read_bytes()
    restored = Archive(tmp_path / "restored")
    restored.restore(archive)
    assert restored.submission_receipt(row["id"]) == receipt
    assert restored.submission_receipt(earlier["id"]) is None
    assert restored.submission_receipt("unknown") is None
    assert not (tmp_path / "restored" / "assertion-access.sqlite3").exists()
    duplicate = tmp_path / "again.jsonl"
    restored.export(duplicate)
    assert duplicate.read_bytes() == archive.read_bytes()


@pytest.mark.parametrize("change", ["missing", "changed", "orphan", "duplicate"])
def test_rechecks_submission_content_and_binding_on_restore(tmp_path, change):
    import hashlib
    import json
    from report_agent.assertions.export import _line
    from report_agent.assertions.launch import Commission as Archive
    archive = tmp_path / "assertions.jsonl"
    commission, row, _, _ = _submission_case(tmp_path / "live")
    commission.export(archive)
    entries = [json.loads(line) for line in archive.read_bytes().splitlines()][:-1]
    entry, = [e for e in entries if "submission_receipt" in e]
    if change == "missing":
        entries.remove(entry)
    elif change == "changed":
        entry["submission_receipt"][1]["rank"] += 1
    elif change == "orphan":
        entries.append({"submission_receipt": [request_digest({}), {}]})
    else:
        entries.append(entry)
    body = b"".join(map(_line, entries))
    archive.write_bytes(body + _line({"sha256": hashlib.sha256(body).hexdigest()}))
    restored = Archive(tmp_path / "restore")
    with pytest.raises(ValueError):
        restored.restore(archive)
    assert restored.recover_receipt(row["operation_id"]) is None


def test_legacy_archive_preserves_exact_bytes_and_has_no_submission_payload(tmp_path):
    import json
    from report_agent.assertions.launch import Commission as Archive
    case = Commission(tmp_path / "legacy", deferred=True)
    earlier = case.submit("A/X51", pending=True)
    archive = tmp_path / "records.jsonl"
    case.host.commission.export(archive)
    data = archive.read_bytes()
    entries = [json.loads(line) for line in data.splitlines()]
    assert entries[0] == {"format":"report-agent/assertions", "version":2}
    assert not any("submission_receipt" in e for e in entries)
    restored = Archive(tmp_path / "restored")
    restored.restore(archive)
    assert restored.submission_receipt(earlier["id"]) is None
    restored.export(archive)
    assert archive.read_bytes() == data


def test_failed_submission_write_rolls_back_judgment_and_operation(tmp_path, monkeypatch):
    from report_agent.assertions.store import Store
    case = Commission(tmp_path, deferred=True)
    original = case.submit("A/X51", pending=True)
    receipt = {"rank": 9, "input": {"missing": "Unreported pit count"}}
    key = request_digest(receipt)
    case.packet.add(key)
    case.resources["receipts"] = {key: receipt}
    archive = tmp_path / "before.jsonl"
    # Pinning the launch envelope is separate; compare only committed assertions and operations.
    case.host.commission.export(archive)
    import json
    prior = [r for line in archive.read_text().splitlines() if "assertion" in (r := json.loads(line))]
    store_submission = Store.store_submission
    def fail_after_insert(db, key, payload):
        store_submission(db, key, payload)
        raise RuntimeError("disk failure after submission insert")
    monkeypatch.setattr(Store, "store_submission", staticmethod(fail_after_insert))
    with pytest.raises(RuntimeError, match="disk failure"):
        case.call("writer", "save_judgment", "A",
                  {**original["claim"], "submission_receipt": key}, original["grounds"])
    case.host.commission.export(archive)
    entries = [json.loads(line) for line in archive.read_text().splitlines()]
    assert [r for r in entries if "assertion" in r] == prior
    assert not any("submission_receipt" in r for r in entries)


def test_existing_v2_database_opens_with_history_and_exact_archive(tmp_path):
    import sqlite3
    from contextlib import closing
    from report_agent.assertions.launch import Commission as Archive
    case = Commission(tmp_path, deferred=True)
    row = case.submit("A/X51", pending=True)
    path = tmp_path / "snapshot.jsonl"
    case.host.commission.export(path)
    before = path.read_bytes()
    # Recreate the previous on-disk layout with real history and pins.
    with closing(sqlite3.connect(tmp_path / "assertions.sqlite3")) as db, db:
        db.execute("DROP TABLE submission_receipts")
        db.execute("PRAGMA user_version=2")
    reopened = Archive(tmp_path)
    assert reopened.recover_receipt(row["operation_id"])["result"] == row
    assert reopened.submission_receipt(row["id"]) is None
    reopened.export(path)
    assert path.read_bytes() == before


def _details_context(case, label):
    from report_agent.assertion_host import Grant
    from uuid import NAMESPACE_URL, uuid5
    grant = Grant(principal=str(uuid5(NAMESPACE_URL, 'fake03/writer')), role='writer',
                  task='writer-task', attempt=label, plan='fake03', subjects={'A'},
                  packet=frozenset(case.packet), actions={'save_judgment'}, resources=case.resources)
    return case.host.issue_once(grant, 'save_judgment', label)


def test_completed_judgment_details_use_the_judgment_id_and_roundtrip(tmp_path):
    from report_agent import assertions
    from report_agent.assertions.launch import Commission as Archive
    case = Commission(tmp_path/'live', deferred=True)
    original = case.submit('A/X51', pending=True)
    details = {'input':{'missing':'Pit count awaits engineering review'}, 'rank':9,
               'disclosed_context':[{'qualifier':'predominantly', 'state':'unknown'}]}
    ctx = _details_context(case, 'details')
    args = dict(subject='A', claim=original['claim'], grounds=original['grounds'], judgment_details=details)
    row = assertions.save_judgment(ctx, **args)
    assert 'submission_receipt' not in row['claim']
    assert case.host.commission.judgment_details(row['id']) == details
    assert case.host.commission.submission_receipt(row['id']) is None
    assert assertions.save_judgment(ctx, **args) == row
    invalid = _details_context(case, 'nonobject-details')
    with pytest.raises(ValueError, match='details must be an object'):
        assertions.save_judgment(invalid, **{**args, 'judgment_details':[]})
    assert case.host.recover_receipt(invalid.operation_id) is None
    with pytest.raises(ValueError, match='OPERATION_CONFLICT'):
        assertions.save_judgment(ctx, **{**args, 'judgment_details':{**details, 'rank':10}})
    archive = tmp_path/'details.jsonl'
    case.host.commission.export(archive)
    restored = Archive(tmp_path/'restored')
    restored.restore(archive)
    assert restored.judgment_details(row['id']) == details
    copied = tmp_path/'details-again.jsonl'
    restored.export(copied)
    assert copied.read_bytes() == archive.read_bytes()


def test_details_failure_rolls_back_the_judgment_and_its_operation(tmp_path, monkeypatch):
    from report_agent import assertions
    from report_agent.assertions.store import Store
    case = Commission(tmp_path/'live', deferred=True)
    original = case.submit('A/X51', pending=True)
    ctx = _details_context(case, 'rollback-details')
    attempted = []
    save = Store.store_judgment_details
    def fail(db, judgment_id, payload):
        save(db, judgment_id, payload)
        attempted.append(judgment_id)
        raise RuntimeError('simulated details interruption')
    monkeypatch.setattr(Store, 'store_judgment_details', staticmethod(fail))
    with pytest.raises(RuntimeError, match='details interruption'):
        assertions.save_judgment(ctx, subject='A', claim=original['claim'], grounds=original['grounds'],
                                 judgment_details={'rank':9})
    assert case.host.recover_receipt(ctx.operation_id) is None
    assert len(attempted) == 1 and case.host.commission.judgment_details(attempted[0]) is None
