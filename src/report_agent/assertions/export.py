"""Offline assertion backup and restore. Restore targets an empty assertion store."""
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile
from uuid import UUID

from .ids import canonical_json, request_digest
from .schema.kinds import actor_class_for, is_canonical_id


_FORMAT = {"format": "report-agent/assertions", "version": 2}
_WITH_SUBMISSIONS = {**_FORMAT, "version": 3}
_CATALOG = json.loads((Path(__file__).parent / "schema/actions.json").read_text(encoding="utf-8"))
_BINDING = {"actor", "role", "task", "attempt", "plan", "snapshot", "packet_digest"}
_SELECT_RECORDS = """
    SELECT a.body, a.id, a.action, a.role, a.snapshot, o.binding, o.digest, o.result, o.created_at
    FROM assertions a LEFT JOIN operations o ON o.id=json_extract(a.body,'$.operation_id')
    ORDER BY a.rowid
"""


def _verify_submissions(db):
    # Each retained body must be referenced by a committed judgment and its frozen launch pin.
    mismatch = db.execute("""
        WITH needed(id) AS (
            SELECT DISTINCT body ->> '$.claim.submission_receipt' FROM assertions
            WHERE action='save_judgment' AND body ->> '$.claim.submission_receipt' IS NOT NULL
        )
        SELECT EXISTS(SELECT id FROM needed EXCEPT SELECT id FROM submission_receipts)
            OR EXISTS(SELECT id FROM submission_receipts EXCEPT SELECT id FROM needed)
            OR EXISTS(SELECT id FROM needed EXCEPT SELECT id FROM resource_pins
                      WHERE family='receipts' AND id=digest)
    """).fetchone()[0]
    if mismatch:
        raise ValueError("Archive and committed judgment submissions disagree")


def _records(db):
    if db.execute("SELECT (SELECT count(*) FROM assertions) != (SELECT count(*) FROM operations)").fetchone()[0]:
        raise ValueError("Assertion and operation counts differ")
    for row in db.execute(_SELECT_RECORDS):
        body = json.loads(row["body"])
        if (row["body"] != row["result"] or body["id"] != row["id"]
                or body["recorded_at"] != row["created_at"]):
            raise ValueError("Assertion and operation receipt disagree")
        yield {"assertion": body, "action": row["action"], "role": row["role"],
               "snapshot": row["snapshot"], "binding": json.loads(row["binding"]), "digest": row["digest"]}
    for row in db.execute("SELECT family,id,digest FROM resource_pins ORDER BY family,id"):
        yield {"resource_pin": list(row)}
    for key, body in db.execute("SELECT id,body FROM submission_receipts ORDER BY id"):
        payload = json.loads(body)
        if request_digest(payload) != key:
            raise ValueError("Corrupt immutable judgment submission")
        yield {"submission_receipt": [key, payload]}
    for row in db.execute("SELECT plan, subject, actor FROM producers ORDER BY plan,subject"):
        yield {"producer": list(row)}


def _line(value):
    return (canonical_json(value) + "\n").encode("utf-8")


def export_jsonl(store, path):
    """Publish a complete, consistent snapshot via an atomic same-directory rename."""
    path = Path(path).resolve()
    if path in {store.path, *(Path(str(store.path) + suffix) for suffix in ("-wal", "-shm", "-journal"))}:
        raise ValueError("Archive path collides with the assertion database")
    if path.exists():
        with path.open("rb") as existing:
            if existing.readline(len(_line(_FORMAT)) + 1) not in (_line(_FORMAT), _line(_WITH_SUBMISSIONS)):
                raise ValueError("Export destination contains a different case artifact")
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            digest = sha256()
            with store.reader() as db:
                _verify_submissions(db)
                has_submissions = db.execute("SELECT 1 FROM submission_receipts LIMIT 1").fetchone()
                header = _line(_WITH_SUBMISSIONS if has_submissions else _FORMAT)
                output.write(header)
                digest.update(header)
                for record in _records(db):
                    data = _line(record)
                    output.write(data)
                    digest.update(data)
            output.write(_line({"sha256": digest.hexdigest()}))
            output.flush()
            os.fsync(output.fileno())
            output.close()
            os.replace(temp, path)
        finally:
            output.close()
            temp.unlink(missing_ok=True)


def _restore_record(store, db, entry, *, submissions):
    if submissions and set(entry) == {"submission_receipt"}:
        fields = entry["submission_receipt"]
        if not isinstance(fields, list) or len(fields) != 2:
            raise ValueError("Malformed judgment submission entry")
        if db.execute("SELECT 1 FROM submission_receipts WHERE id=?", (fields[0],)).fetchone():
            raise ValueError("Duplicate immutable judgment submission")
        store.store_submission(db, *fields)
        return
    if set(entry) == {"resource_pin"}:
        pin = entry["resource_pin"]
        if not isinstance(pin, list) or len(pin) != 3:
            raise ValueError("Malformed immutable resource fingerprint")
        if db.execute("SELECT 1 FROM resource_pins WHERE family=? AND id=?", pin[:2]).fetchone():
            raise ValueError("Duplicate immutable resource fingerprint")
        store.pin_resource(db, *pin)
        return
    if set(entry) == {"producer"}:
        fields = entry["producer"]
        if not isinstance(fields, list) or len(fields) != 3 or not all(map(is_canonical_id, fields)):
            raise ValueError("Invalid producer binding")
        db.execute("INSERT INTO producers(plan,subject,actor) VALUES (?,?,?)", fields)
        return
    if set(entry) != {"assertion", "action", "role", "snapshot", "binding", "digest"}:
        raise ValueError("Malformed assertion entry")
    body, role, action, binding = (entry[k] for k in ("assertion", "role", "action", "binding"))
    if not isinstance(binding, dict) or set(binding) != _BINDING:
        raise ValueError("Malformed operation binding")
    for field in _BINDING - {"snapshot", "packet_digest"}:
        if not is_canonical_id(binding[field]):
            raise ValueError("Invalid bound identity")
    if str(UUID(binding["actor"])) != binding["actor"]:
        raise ValueError("Noncanonical archived principal")
    if (not isinstance(binding["packet_digest"], str)
            or not re.fullmatch("[0-9a-f]{64}", binding["packet_digest"])):
        raise ValueError("Invalid packet digest")
    if binding["snapshot"] != entry["snapshot"] or (
            entry["snapshot"] is not None and not is_canonical_id(entry["snapshot"])):
        raise ValueError("Invalid snapshot binding")
    if (binding["actor"] != body["was_attributed_to"] or binding["task"] != body["was_generated_by"]
            or role != binding["role"]):
        raise ValueError("Assertion provenance disagrees with its receipt")
    spec = _CATALOG["actions"].get(action)
    claim = body["claim"]
    if not spec or spec["kind"] != claim["kind"] or role not in _CATALOG["roles"]:
        raise ValueError("Invalid action or role")
    agent_allowed = "@agent" in spec["roles"] and actor_class_for(role) == "agent"
    historical_source = (body.get("check_version") == "s2-proposal-2"
                         and action == "assert_source" and role == "coordinator")
    if role not in spec["roles"] and not agent_allowed and not historical_source:
        raise ValueError("Role is ineligible for the archived action")
    if claim["kind"] in {"act", "decision"}:
        allowed = {"answer", "dismiss_challenge"} if action == "decide" else {action}
        if claim.get("effect") not in allowed:
            raise ValueError("Archived effect is inconsistent with the action")
    stored = store.commit(db, body, action, role, entry["snapshot"], binding, entry["digest"])
    if stored != body:
        raise ValueError("Noncanonical assertion envelope")


def _verify_producers(db):
    sql = """
        WITH needed AS (
            SELECT DISTINCT json_extract(o.binding,'$.plan'), json_extract(a.body,'$.subject'),
                            json_extract(a.body,'$.was_attributed_to')
            FROM assertions a JOIN operations o ON o.id=json_extract(a.body,'$.operation_id')
            WHERE a.action='save_judgment'
        )
        SELECT EXISTS(SELECT * FROM needed EXCEPT SELECT plan,subject,actor FROM producers)
            OR EXISTS(SELECT plan,subject,actor FROM producers EXCEPT SELECT * FROM needed)
    """
    if db.execute(sql).fetchone()[0]:
        raise ValueError("Archived producer claims disagree with saved judgments")


def reload_jsonl(store, path):
    """Restore bodies, exact retry receipts, and producer ownership as one transaction."""
    with Path(path).open("rb") as source, store.transaction() as db:
        if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
               for table in ("assertions", "operations", "producers", "resource_pins", "submission_receipts")):
            raise ValueError("RESTORE_REQUIRES_EMPTY_STORE")
        header = source.readline()
        if header not in (_line(_FORMAT), _line(_WITH_SUBMISSIONS)):
            raise ValueError("Unsupported assertion archive")
        submissions = header == _line(_WITH_SUBMISSIONS)
        digest = sha256(header)
        for line in source:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("Malformed assertion archive")
            if set(entry) == {"sha256"}:
                if entry["sha256"] != digest.hexdigest() or source.read(1):
                    raise ValueError("Invalid archive checksum or trailing data")
                _verify_producers(db)
                _verify_submissions(db)
                return
            digest.update(line)
            try:
                _restore_record(store, db, entry, submissions=submissions)
            except (KeyError, TypeError, sqlite3.IntegrityError) as exc:
                raise ValueError("Malformed or duplicate archive record") from exc
        raise ValueError("Missing assertion archive checksum")
