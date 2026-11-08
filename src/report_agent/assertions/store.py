"""Commission-local, atomic SQLite persistence for the assertions action layer."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import re
import sqlite3
from time import monotonic, sleep

from .ids import assertion_id, canonical_json
from .schema.kinds import Assertion, is_canonical_id

FROZEN_FAMILIES = ("snapshots", "scopes", "criteria", "sources", "receipts", "conventions", "rules")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assertions(
    id TEXT PRIMARY KEY NOT NULL, body TEXT NOT NULL, action TEXT NOT NULL,
    role TEXT NOT NULL, snapshot TEXT
);
CREATE TABLE IF NOT EXISTS operations(
    id TEXT PRIMARY KEY NOT NULL, binding TEXT NOT NULL, digest TEXT NOT NULL,
    result TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_pins(
    family TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL,
    PRIMARY KEY(family,id)
);
CREATE TABLE IF NOT EXISTS producers(
    plan TEXT NOT NULL, subject TEXT NOT NULL, actor TEXT NOT NULL,
    PRIMARY KEY(plan,subject)
);
"""


class Store:
    def __init__(self, run_dir):
        directory = Path(run_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "assertions.sqlite3"
        with closing(self._connect()) as db:
            # Two initializers converting the same empty file to WAL can receive
            # SQLITE_BUSY immediately while upgrading their shared schema locks.
            deadline = monotonic() + 10
            while True:
                try:
                    mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                    break
                except sqlite3.OperationalError as error:
                    if error.sqlite_errorcode != sqlite3.SQLITE_BUSY or monotonic() >= deadline:
                        raise
                    sleep(0.01)
            if mode != "wal":
                raise OSError("Assertion store requires WAL journaling")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version in (0, 1):
                db.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\nPRAGMA user_version=2; COMMIT;")
            elif version != 2:
                raise ValueError(f"Unsupported assertion store schema version {version}")

    def _connect(self, readonly=False):
        target = self.path.as_uri() + "?mode=ro" if readonly else self.path
        db = sqlite3.connect(target, uri=readonly, isolation_level=None, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA query_only=ON" if readonly else "PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self):
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @contextmanager
    def reader(self):
        with closing(self._connect(readonly=True)) as db, db:
            db.execute("BEGIN")
            yield db

    @staticmethod
    def pin_resource(db, family, resource_id, digest):
        if (family not in FROZEN_FAMILIES or not is_canonical_id(resource_id)
                or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)):
            raise ValueError("Invalid immutable resource fingerprint")
        db.execute("INSERT INTO resource_pins VALUES(?,?,?) ON CONFLICT DO NOTHING",
                   (family, resource_id, digest))
        actual = db.execute("SELECT digest FROM resource_pins WHERE family=? AND id=?",
                            (family, resource_id)).fetchone()[0]
        if actual != digest:
            raise ValueError("Frozen resource binding conflict")

    @staticmethod
    def lookup(db, operation_id, binding, digest, can_read):
        receipt = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        if receipt is None:
            return None
        if not can_read:
            raise PermissionError("OPERATION_READ_DENIED")
        if receipt["binding"] != canonical_json(binding) or receipt["digest"] != digest:
            raise ValueError("OPERATION_CONFLICT")
        return json.loads(receipt["result"])

    @staticmethod
    def commit(db, assertion, action, role, snapshot, binding, digest):
        if not db.in_transaction:
            raise RuntimeError("An assertion and its receipt require a transaction")
        row = Assertion.model_validate(assertion)
        expected = assertion_id(row.subject, row.claim, row.grounds, row.was_attributed_to,
                                row.was_generated_by, row.operation_id)
        if row.id != expected:
            raise ValueError("ASSERTION_ID_MISMATCH")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("INVALID_REQUEST_DIGEST")
        body = row.model_dump(mode="json")
        serialized = canonical_json(body)
        db.execute("INSERT INTO assertions(id,body,action,role,snapshot) VALUES (?,?,?,?,?)",
                   (row.id, serialized, action, role, snapshot))
        db.execute("INSERT INTO operations(id,binding,digest,result,created_at) VALUES (?,?,?,?,?)",
                   (row.operation_id, canonical_json(binding), digest, serialized, body["recorded_at"]))
        return body
