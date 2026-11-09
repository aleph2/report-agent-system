"""Own the content transaction while the launch host holds its authorization view."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Callable, ContextManager

from .export import export_jsonl, reload_jsonl
from .ids import request_digest
from .store import FROZEN_FAMILIES, Store
from .refusals import CATALOG
from .schema.kinds import actor_class_for

# Trusted launch API; kept separate from the agent-callable actions and queries.
__all__ = ["Commission", "actor_class_for", "request_digest", "validate_launch"]


def validate_launch(role, actions):
    if role not in CATALOG["roles"] or set(actions) - CATALOG["actions"].keys():
        raise ValueError("Unknown role or action")


class Commission:
    def __init__(self, run_dir):
        self._store = Store(run_dir)

    def pin(self, fingerprints):
        with self._store.transaction() as db:
            for family, key, digest in fingerprints:
                self._store.pin_resource(db, family, key, digest)

    def pin_resources(self, resources):
        self.pin((family, key, request_digest(value)) for family in FROZEN_FAMILIES
                 for key, value in resources.get(family, {}).items())

    def recover_receipt(self, operation_id):
        """Read a committed outcome for this commission after its agent grant expired."""
        with self._store.reader() as db:
            row = db.execute("SELECT binding,digest,result,created_at FROM operations WHERE id=?",
                             (operation_id,)).fetchone()
            if row is None:
                return None
            return {"operation_id": operation_id, "binding": json.loads(row["binding"]),
                    "digest": row["digest"], "result": json.loads(row["result"]),
                    "created_at": row["created_at"]}

    def submission_receipt(self, judgment_id):
        """Read the immutable submission supporting a committed judgment for host-side projection."""
        return self._store.submission_receipt(judgment_id)

    def producer(self, plan, subject):
        """Return the Writer already bound by an immutable judgment in this commission."""
        with self._store.reader() as db:
            row = db.execute("SELECT actor FROM producers WHERE plan=? AND subject=?", (plan, subject)).fetchone()
            return row[0] if row else None

    @staticmethod
    def preexisting_producer(directory, plan, subject):
        """Observe an M2 ownership pin without initializing or changing its archive."""
        path = Path(directory) / "assertions.sqlite3"
        if not path.is_file():
            return None
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT actor FROM producers WHERE plan=? AND subject=?", (plan, subject)).fetchone()
            return row[0] if row else None

    def produced_ids(self, *, actor, task, subject, kind):
        """IDs available to reissue in this producer's task packet."""
        with self._store.reader() as db:
            return frozenset(row[0] for row in db.execute(
                """SELECT id FROM assertions WHERE body ->> '$.was_attributed_to' = ?
                   AND body ->> '$.was_generated_by' = ? AND body ->> '$.subject' = ?
                   AND body ->> '$.claim.kind' = ?""", (actor, task, subject, kind)))

    @staticmethod
    def committed_projections(directory, pins):
        """Resolve a set of operation/record pairs against one live status snapshot."""
        from .queries import assertion_states
        path = Path(directory) / "assertions.sqlite3"
        if not pins or not path.is_file():
            return {}
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            states = assertion_states(db)
            results = {}
            for operation_id, assertion_id in pins:
                row = db.execute("""SELECT o.binding,a.body FROM operations o JOIN assertions a
                    ON a.id=? AND a.body=o.result WHERE o.id=?""", (assertion_id, operation_id)).fetchone()
                if row:
                    assertion = json.loads(row[1])
                    inputs = [states.get(key, {}) for key in assertion["claim"].get("inputs", ())]
                    results[assertion_id] = json.loads(row[0]), assertion, states[assertion_id], inputs
            return results

    @staticmethod
    def committed_projection(directory, operation_id, assertion_id):
        return Commission.committed_projections(directory, [(operation_id, assertion_id)]).get(assertion_id)

    def publish_in_case(self, case_db, ctx, *, subject, claim):
        """Publish a plan action inside its caller's case transaction and savepoint."""
        from .actions import _save_locked
        databases = {name: Path(path) for _, name, path in case_db.execute("PRAGMA database_list")}
        if (not case_db.in_transaction or ctx._store is not self._store
                or databases["main"] != self._store.path.parent / "state.db"):
            raise ValueError("Plan publication requires the owning case transaction")
        if "plan_assertions" not in databases:
            case_db.execute("ATTACH DATABASE ? AS plan_assertions", (str(self._store.path),))
        elif databases["plan_assertions"] != self._store.path:
            raise ValueError("Incorrect assertion database for this case")
        previous = case_db.row_factory
        try:
            case_db.row_factory = sqlite3.Row
            with ctx._authorized() as grant:
                return _save_locked(ctx.action, ctx, case_db, grant, subject=subject, claim=claim)
        finally:
            case_db.row_factory = previous

    def import_plan_actions(self, directory, links):
        """Restore a business-only case's plan actions with their original receipts."""
        from .export import _restore_record
        path = Path(directory).resolve() / "assertions.sqlite3"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source, self._store.transaction() as db:
            source.execute("BEGIN")
            for link in links:
                row = source.execute("""SELECT a.body,a.action,a.role,a.snapshot,o.binding,o.digest
                    FROM assertions a JOIN operations o ON a.body=o.result WHERE a.id=? AND o.id=?""",
                    (link["assertion_id"], link["operation_id"])).fetchone()
                if not row or (row[1], row[2]) not in (
                        ("record_convention", "coordinator"), ("confirm", "owner"), ("retract", "owner")):
                    raise ValueError("Missing plan action for business import")
                _restore_record(self._store, db, {
                    "assertion": json.loads(row[0]), "action": row[1], "role": row[2],
                    "snapshot": row[3], "binding": json.loads(row[4]), "digest": row[5]}, submissions=False)

    def export(self, path):
        export_jsonl(self._store, path)

    def restore(self, path):
        reload_jsonl(self._store, path)

    def bind(self, authorized, binding, action, operation_id):
        return _Context(self._store, authorized, binding, action, operation_id)


@dataclass(frozen=True)
class _Context:
    _store: Store
    _authorized: Callable[[], ContextManager]
    binding: dict
    action: str
    operation_id: str

    @contextmanager
    def _open(self, transaction):
        with self._authorized() as grant, transaction() as db:
            yield db, grant

    def write(self):
        return self._open(self._store.transaction)

    def read(self):
        return self._open(self._store.reader)
