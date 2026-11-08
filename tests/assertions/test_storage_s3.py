from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Barrier

import pytest

from report_agent.assertions.export import export_jsonl, reload_jsonl
from report_agent.assertions.ids import assertion_id, request_digest
from report_agent.assertions.store import Store


ACTOR = "a30e8d39-8264-456e-806f-e9690a03b014"
BINDING = {"actor": ACTOR, "task": "task", "attempt": "attempt", "plan": "p1",
           "packet_digest": "a" * 64, "role": "writer", "snapshot": None}
CLAIM = {"kind": "question", "text": "Which source applies?", "affects": "other"}
DIGEST = request_digest({"action": "ask", "claim": CLAIM})


def question(op="op1"):
    when = datetime.now(timezone.utc).isoformat()
    return dict(id=assertion_id("A", CLAIM, [], ACTOR, "task", op),
                subject="A", claim=CLAIM, grounds=[], was_attributed_to=ACTOR,
                was_generated_by="task", operation_id=op, observed_at=when, recorded_at=when,
                schema_version="s2-proposal-1", check_version="s2-proposal-2")


def submit(store, op="op1"):
    with store.transaction() as db:
        prior = store.lookup(db, op, BINDING, DIGEST, True)
        if prior is not None:
            return prior
        return store.commit(db, question(op), "ask", "writer", None, BINDING, DIGEST)


def test_concurrent_retries_and_permission(tmp_path):
    store = Store(tmp_path)
    ready = Barrier(2)

    def concurrent_submit():
        ready.wait(timeout=10)
        return submit(store)

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(concurrent_submit) for _ in range(2)]
        assert jobs[0].result() == jobs[1].result()
    with store.reader() as db:
        assert db.execute("SELECT count(*) FROM assertions").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 1
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(PermissionError):
            store.lookup(db, "op1", BINDING, DIGEST, False)
        for change in BINDING:
            with pytest.raises(ValueError, match="CONFLICT"):
                store.lookup(db, "op1", {**BINDING, change: "changed"}, DIGEST, True)
        with pytest.raises(ValueError, match="CONFLICT"):
            store.lookup(db, "op1", BINDING, request_digest({"changed": True}), True)
        assert store.lookup(db, "op2", BINDING, DIGEST, True) is None


def test_forged_record_id_and_support_order(tmp_path):
    q = question()
    assert q["id"] != assertion_id("B", CLAIM, [], ACTOR, "task", "op1")
    assert q["id"] != assertion_id("A", CLAIM, [], "writer-2", "task", "op1")
    assert q["id"] == assertion_id("A", dict(reversed(list(CLAIM.items()))), [], ACTOR, "task", "op1")
    store = Store(tmp_path)
    with pytest.raises(ValueError, match="ID"):
        with store.transaction() as db:
            store.commit(db, {**q, "id": "forged"}, "ask", "writer", None, BINDING, DIGEST)


def test_export_is_complete_atomic_and_validated(tmp_path):
    original = Store(tmp_path/"original")
    submitted = submit(original)
    with original.transaction() as db:
        judgment = {"kind": "judgment", "basis": "gap", "question": "q1",
                    "warrant": {"criterion": "method", "criterion_version": "v1", "rationale": "missing"}}
        row = {**question("op2"), "claim": judgment,
               "id": assertion_id("A", judgment, [], ACTOR, "task", "op2")}
        original.commit(db, row, "save_judgment", "writer", None, BINDING, request_digest(judgment))
        db.execute("INSERT INTO producers VALUES (?, ?, ?)", ("p1", "A", ACTOR))
    archive = tmp_path/"records.jsonl"
    export_jsonl(original, archive)
    restored = Store(tmp_path/"restored")
    reload_jsonl(restored, archive)
    assert submit(restored) == submitted
    with restored.reader() as db:
        assert tuple(db.execute("SELECT * FROM producers").fetchone()) == ("p1", "A", ACTOR)
    again = tmp_path/"restored.jsonl"
    export_jsonl(restored, again)
    assert again.read_bytes() == archive.read_bytes()
    with pytest.raises(ValueError, match="EMPTY"):
        reload_jsonl(restored, archive)
    lines = archive.read_bytes().splitlines(keepends=True)
    # A prefix ending at a valid JSONL boundary is still an incomplete export.
    archive.write_bytes(b"".join(lines[:-1]))
    empty = Store(tmp_path/"empty")
    with pytest.raises(ValueError):
        reload_jsonl(empty, archive)
    with empty.reader() as db:
        assert db.execute("SELECT count(*) FROM assertions").fetchone()[0] == 0


@pytest.mark.parametrize("stop_at", ["between_inserts", "before_commit", "after_commit"])
def test_process_death_is_atomic(tmp_path, stop_at):
    store = Store(tmp_path)
    child = """
import os
import sys
from report_agent.assertions.store import Store
from test_storage_s3 import question, BINDING, DIGEST, ACTOR
store = Store(sys.argv[1])
with store.transaction() as db:
    db.execute("INSERT INTO producers VALUES (?, ?, ?)", ("p1", "A", ACTOR))
    if sys.argv[2] == "between_inserts":
        db.create_function("kill_process", 0, lambda: os._exit(73))
        db.execute("CREATE TEMP TRIGGER kill_after_assertion AFTER INSERT ON assertions "
                   "BEGIN SELECT kill_process(); END")
    store.commit(db, question(), "ask", "writer", None, BINDING, DIGEST)
    if sys.argv[2] == "before_commit":
        os._exit(73)
os._exit(73)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(Path(__file__).parent), env.get("PYTHONPATH", "")])
    child_result = subprocess.run([sys.executable, "-B", "-c", child, str(tmp_path), stop_at],
                                  env=env, timeout=20)
    assert child_result.returncode == 73
    with store.reader() as db:
        for table in ("assertions", "operations", "producers"):
            assert db.execute("SELECT count(*) FROM " + table).fetchone()[0] == int(stop_at == "after_commit")
    assert submit(store)["operation_id"] == "op1"

@pytest.mark.parametrize("damage", ["record_id", "role", "actor", "task", "snapshot", "packet_digest",
                                     "effect", "action", "producer"])
def test_archive_rejects_inconsistent_receipts_even_with_fresh_checksum(tmp_path, damage):
    store = Store(tmp_path/"original")
    submit(store)
    path = tmp_path/"export.jsonl"
    export_jsonl(store, path)
    header, row, _ = path.read_bytes().splitlines(keepends=True)
    record = json.loads(row)
    if damage == "record_id":
        record["assertion"]["id"] = "forged"
    elif damage in {"actor", "task", "role", "snapshot", "packet_digest"}:
        record["binding"][damage] = "another"
    elif damage == "effect":
        record["assertion"]["claim"]["effect"] = "release"
    elif damage == "action":
        record["action"] = "release"
    extra = b'{"producer":["p1","A","other-writer"]}\n' if damage == "producer" else b""
    data = header + (json.dumps(record, ensure_ascii=False) + "\n").encode() + extra
    path.write_bytes(data + (json.dumps({"sha256": sha256(data).hexdigest()}) + "\n").encode())
    restored = Store(tmp_path/"empty")
    with pytest.raises(ValueError):
        reload_jsonl(restored, path)
    with restored.reader() as db:
        assert not db.execute("SELECT 1 FROM assertions").fetchone()
        assert not db.execute("SELECT 1 FROM operations").fetchone()
        assert not db.execute("SELECT 1 FROM producers").fetchone()


def test_id_binds_ground_purpose_and_proposition():
    ground = {"assertion_id": "fact", "purpose": "context", "proposition": "covers A"}

    def key(item):
        return assertion_id("A", CLAIM, [item], ACTOR, "task", "op1")

    for changed in ({"assertion_id": "other"}, {"purpose": "assumption"},
                    {"proposition": "covers B"}, {"transfer_convention": "other"}):
        assert key(ground) != key({**ground, **changed})
    assert key(ground) == key({**ground, "transfer_convention": None})


def test_new_reader_can_attach_before_writer_commits(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as writing:
        store.commit(writing, question(), "ask", "writer", None, BINDING, DIGEST)
        other = Store(tmp_path)
        with other.reader() as reading:
            assert reading.execute("SELECT count(*) FROM assertions").fetchone()[0] == 0
    with other.reader() as reading:
        assert reading.execute("SELECT count(*) FROM assertions").fetchone()[0] == 1


def test_first_open_of_a_new_commission_is_safe_for_independent_clients(tmp_path):
    for i in range(5):
        barrier = Barrier(4)

        def open_and_submit():
            barrier.wait(timeout=10)
            return submit(Store(tmp_path / str(i)))

        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [pool.submit(open_and_submit) for _ in range(4)]
            results = [job.result() for job in jobs]
        assert all(result == results[0] for result in results)

@pytest.mark.parametrize(("role", "allowed"), [
    ("writer", True), ("calculator", False), ("text_tool", False), ("owner", False), ("engineer", False),
])
def test_archive_applies_same_agent_class_rule_as_issued_grant(tmp_path, role, allowed):
    from report_agent.assertion_host import Grant

    grant = Grant(principal=ACTOR, role=role, task="task", attempt="attempt", plan="p1",
                  subjects=frozenset({"A"}), packet=frozenset(), actions=frozenset({"ask"}))
    assert (grant.actor_class == "agent") is allowed
    store = Store(tmp_path / "original")
    # A trusted operator may receive an internally inconsistent archive.
    with store.transaction() as db:
        store.commit(db, question(), "ask", role, None, grant.binding, DIGEST)
    path = tmp_path / "export.jsonl"
    export_jsonl(store, path)
    destination = Store(tmp_path / "reopened")
    if allowed:
        reload_jsonl(destination, path)
        with destination.reader() as db:
            assert destination.lookup(db, "op1", grant.binding, DIGEST, True)["claim"] == CLAIM
    else:
        with pytest.raises(ValueError, match="ineligible"):
            reload_jsonl(destination, path)

def test_export_cannot_replace_other_case_records(tmp_path):
    store = Store(tmp_path)
    destination = tmp_path / "case.json"
    original = b'{"held": 2000000}\n'
    destination.write_bytes(original)
    with pytest.raises(ValueError, match="destination"):
        export_jsonl(store, destination)
    assert destination.read_bytes() == original

def test_fingerprint_conflict_rolls_back_other_pins_in_failed_grant(tmp_path):
    from report_agent.assertion_host import AssertionHost, Grant

    host = AssertionHost(tmp_path)
    original = Grant(principal=ACTOR, role="writer", task="task", attempt="attempt", plan="plan",
                     subjects=frozenset({"A"}), packet=frozenset(), actions=frozenset({"ask"}),
                     resources={"criteria": {"original": {"meaning": "v1"}}})
    host.authorize(original)
    conflict = replace(original, task="new", resources={"criteria": {
        "new": {"meaning": "discard"}, "original": {"meaning": "v2"}}})
    with pytest.raises(ValueError, match="Frozen resource binding conflict"):
        host.authorize(conflict)
    # The rejected grant has no authority and did not pin its unrelated new key.
    from report_agent.assertions import packet
    with pytest.raises(PermissionError):
        packet(host.bind(conflict, native_call_id="attempt", action="ask"))
    corrected = replace(conflict, resources={"criteria": {"new": {"meaning": "corrected"}}})
    host.authorize(corrected)
    assert packet(host.bind(corrected, native_call_id="attempt", action="ask")) == ()


def test_archive_rejects_restore_over_a_previously_pinned_resource(tmp_path):
    original = Store(tmp_path / "source")
    destination = Store(tmp_path / "destination")
    with original.transaction() as db:
        original.pin_resource(db, "sources", "page", "a" * 64)
    with destination.transaction() as db:
        destination.pin_resource(db, "sources", "page", "b" * 64)
    archive = tmp_path / "preserved.jsonl"
    export_jsonl(original, archive)
    with pytest.raises(ValueError, match="EMPTY"):
        reload_jsonl(destination, archive)
    with destination.reader() as db:
        assert db.execute("SELECT digest FROM resource_pins").fetchone()[0] == "b" * 64

def test_existing_launch_fingerprints_are_preserved_on_upgrade(tmp_path):
    from report_agent.assertion_host import AssertionHost, Grant

    previous = {"meaning": "v1"}
    with closing(sqlite3.connect(tmp_path / "assertion-access.sqlite3")) as db, db:
        db.execute("CREATE TABLE resources(family, id, digest, PRIMARY KEY(family,id))")
        db.execute("INSERT INTO resources VALUES(?,?,?)", ("criteria", "method", request_digest(previous)))
    host = AssertionHost(tmp_path)
    changed = Grant(principal=ACTOR, role="writer", task="work", attempt="test", plan="plan",
                    subjects=frozenset({"A"}), packet=frozenset(), actions=frozenset({"ask"}),
                    resources={"criteria": {"method": {"meaning": "different"}}})
    with pytest.raises(ValueError, match="Frozen resource binding conflict"):
        host.authorize(changed)
    with Store(tmp_path).reader() as db:
        assert db.execute("SELECT digest FROM resource_pins").fetchone()[0] == request_digest(previous)
