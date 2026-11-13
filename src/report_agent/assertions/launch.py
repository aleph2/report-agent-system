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
    @staticmethod
    @contextmanager
    def freeze_to(source_dir, temporary_dir):
        """Own a temporary read-only source snapshot and verify its source on every exit."""
        import hashlib
        source, temporary = Path(source_dir).resolve(), Path(temporary_dir).resolve()
        if (temporary == source or temporary.is_relative_to(source) or source.is_relative_to(temporary)
                or not temporary.is_dir() or any(temporary.iterdir())):
            raise ValueError("Empty isolated assertion snapshot directory required")
        name = "assertions.sqlite3"
        if (source / name).is_symlink():
            raise ValueError("Assertion snapshot source must not be a symlink")
        names = (name, name + "-wal")
        before = {key: hashlib.sha256((source / key).read_bytes()).hexdigest() for key in names
                  if (source / key).is_file() and (key == name or (source / key).stat().st_size)}
        try:
            if (source / name).is_file():
                with closing(sqlite3.connect((source / name).as_uri() + "?mode=ro", uri=True, timeout=3)) as original:
                    original.execute("PRAGMA query_only=ON")
                    original.execute("BEGIN")
                    with closing(sqlite3.connect(temporary / name)) as frozen:
                        original.backup(frozen)
            yield before
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                (temporary / (name + suffix)).unlink(missing_ok=True)
            after = {key: hashlib.sha256((source / key).read_bytes()).hexdigest() for key in names
                     if (source / key).is_file() and (key == name or (source / key).stat().st_size)}
            if after != before:
                raise ValueError("Assertion snapshot source changed")

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

    def judgment_details(self, judgment_id):
        """Read completed judgment content by its assertion ID, including accepted historical data."""
        return self._store.judgment_details(judgment_id)

    def submission_receipt(self, judgment_id):
        """Read accepted historical hash-linked M2 submissions."""
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

    @staticmethod
    def current_references(directory, ids):
        """Trusted export's read-only status check; it records no claim or action."""
        from .queries import assertion_states
        if not ids or directory is None:
            return {}
        path = Path(directory) / 'assertions.sqlite3'
        if not ids or not path.is_file():
            return {}
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            states = assertion_states(db)
            return {key: states[key] for key in ids if key in states}

    @staticmethod
    def _plan_rows(db):
        return db.execute("""WITH proposals AS (
            SELECT id FROM assertions WHERE action='record_convention' AND role='coordinator'
            AND body ->> '$.claim.scope'='commission_plan')
            SELECT id,action,body FROM assertions WHERE id IN proposals OR
            (role='owner' AND action IN ('confirm','retract') AND body ->> '$.claim.target' IN proposals)
            ORDER BY CASE WHEN action='record_convention' THEN 0 ELSE 1 END,
                     CASE WHEN action='record_convention' AND json_valid(body ->> '$.claim.rule')
                          THEN json_extract(body ->> '$.claim.rule', '$.version') END,
                     rowid""")

    @staticmethod
    def _plan_snapshot(db, live):
        from .queries import assertion_states
        states = assertion_states(db) if live else {}
        return [(action, json.loads(body), states.get(key)) for key, action, body in Commission._plan_rows(db)]

    @staticmethod
    def plan_actions(directory, *, live=False):
        """Read native proposal references and the owner acts that target them in one snapshot."""
        path = Path(directory) / "assertions.sqlite3"
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            return Commission._plan_snapshot(db, live)

    @staticmethod
    def decide_current(ctx, *, subject, claim):
        from .actions import _save_locked
        with ctx.write() as (db, grant):
            if not db.execute("SELECT 1 FROM operations WHERE id=?", (ctx.operation_id,)).fetchone():
                proposals = [key for key, action, _ in Commission._plan_rows(db) if action == "record_convention"]
                if not proposals or proposals[-1] != claim["target"]:
                    raise ValueError("COMMISSION_CHECKPOINT_REPLY_STALE")
            return _save_locked(ctx.action, ctx, db, grant, subject=subject, claim=claim)

    def import_plan_actions(self, directory, select):
        """Restore a business-only case's plan actions with their original receipts."""
        self._import_actions(directory, lambda db: select(self._plan_snapshot(db, True)), {
            ("record_convention", "coordinator"), ("confirm", "owner"), ("retract", "owner")})

    @staticmethod
    def _planning_rows(db, subject=None):
        from .queries import assertion_states
        rows = db.execute("""SELECT id,action,body FROM assertions WHERE (
            (action='record_convention' AND role='coordinator' AND body ->> '$.claim.scope'='commission_requirements')
            OR (body ->> '$.subject' GLOB 'commission-checkpoint/*' AND
                ((action='ask' AND role='coordinator') OR (action='decide' AND role='owner'))))
            AND (? IS NULL OR body ->> '$.subject' = ?) ORDER BY rowid""", (subject, subject)).fetchall()
        if not rows:
            return []
        states = assertion_states(db)
        return [(action, json.loads(body), states[identity]) for identity, action, body in rows]

    @staticmethod
    def planning_actions(directory, subject=None):
        path = Path(directory).resolve() / "assertions.sqlite3"
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            return Commission._planning_rows(db, subject)

    @staticmethod
    def page_records(directory):
        """Host projection of page bindings and extracted facts; not an agent query."""
        from .queries import assertion_states
        path = Path(directory).resolve() / "assertions.sqlite3"
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            states = assertion_states(db)
            return [(json.loads(body), states[key]) for key, body in db.execute(
                """SELECT id,body FROM assertions WHERE
                body ->> '$.claim.scope'='source_page_binding' OR body ->> '$.claim.kind'='source'""")]

    @staticmethod
    def issue_records(directory):
        """Trusted host issue view; never issued as an unrestricted agent query."""
        from .queries import assertion_states
        path = Path(directory).resolve() / 'assertions.sqlite3'
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            states = assertion_states(db)
            result = []
            for identity, raw in db.execute('SELECT id,body FROM assertions ORDER BY rowid'):
                row, state = json.loads(raw), states[identity]
                claim = row['claim']
                if not state['active']:
                    continue
                kind = claim['kind']
                if (kind in {'question', 'conflict', 'finding'} or kind == 'judgment'
                        and (claim['basis'] in {'gap', 'assumption', 'conditional'}
                             or claim.get('question') or claim.get('review_flags'))):
                    result.append({'record': row, 'state': state})
            return result

    @staticmethod
    def issue_actions(directory):
        """Read authenticated replies to runtime questions without opening an agent capability."""
        from .queries import assertion_states
        path = Path(directory).resolve() / 'assertions.sqlite3'
        if not path.is_file():
            return []
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            states = assertion_states(db)
            return [(action, json.loads(raw), states[identity]) for identity, action, raw in db.execute(
                "SELECT id,action,body FROM assertions WHERE body ->> '$.subject' GLOB 'runtime-issue/*' "
                "AND ((action='ask' AND role='coordinator') OR (action='decide' AND role='owner')) ORDER BY rowid")]

    def import_planning_actions(self, directory, select):
        self._import_actions(directory, lambda db: select(self._planning_rows(db)), {
            ("record_convention", "coordinator"), ("ask", "coordinator"), ("decide", "owner")})

    def _import_actions(self, directory, select, permitted):
        from .export import _restore_record
        path = Path(directory).resolve() / "assertions.sqlite3"
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source, self._store.transaction() as db:
            source.execute("BEGIN")
            for assertion in select(source):
                row = source.execute("""SELECT a.body,a.action,a.role,a.snapshot,o.binding,o.digest
                    FROM assertions a JOIN operations o ON a.body=o.result WHERE a.id=? AND o.id=?""",
                    (assertion["id"], assertion["operation_id"])).fetchone()
                if not row or (row[1], row[2]) not in permitted:
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
