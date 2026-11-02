from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .errors import ActionRejected, LocalStorageBusy


def _busy(error):
    code = getattr(error, 'sqlite_errorcode', None)
    return isinstance(error, sqlite3.OperationalError) and isinstance(code, int) and code & 255 == sqlite3.SQLITE_BUSY


class _Connection(sqlite3.Connection):
    def _local_retry(self, action):
        # Retry only the same SQLite statement/commit, never its caller or a model.
        timeout = None
        try:
            for attempt in range(3):
                try:
                    return action()
                except sqlite3.OperationalError as error:
                    if getattr(error, 'sqlite_errorcode', None) != sqlite3.SQLITE_BUSY or attempt == 2:
                        raise
                    if timeout is None:
                        timeout = super().execute('PRAGMA busy_timeout').fetchone()[0]
                    super().execute('PRAGMA busy_timeout=100')
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if timeout is not None:
                super().execute(f'PRAGMA busy_timeout={timeout}')

    def execute(self, *args, **kwargs):
        return self._local_retry(lambda: super(_Connection, self).execute(*args, **kwargs))

    def commit(self):
        return self._local_retry(super().commit)


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Store:
    """One isolated project; immutable source snapshot and transactional receipts."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.db"
        with self.connect() as db:
            if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
                raise RuntimeError('PROJECT_DATABASE_WAL_REQUIRED')
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS analyses (operation TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT NOT NULL, data TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, factory=_Connection)
        try:
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except BaseException as error:
            db.rollback()
            if _busy(error):
                raise LocalStorageBusy() from error
            raise
        finally:
            db.close()

    @contextmanager
    def run_lock(self):
        # The initial CLI is WSL/Linux and deliberately single-worker per project.
        import fcntl

        with (self.root / "run.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("PROJECT_ALREADY_RUNNING") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def initialize(self, manifest: dict):
        sources = manifest["sources"]
        if not manifest.get("goal") or not sources:
            raise ValueError("GOAL_AND_SOURCES_REQUIRED")
        ids = [s["id"] for s in sources]
        references = manifest.get("presentation_references", [])
        if not isinstance(references, list) or any(
            not isinstance(r, dict) or r.get("source_id") not in ids
            or not isinstance(r.get("instruction", ""), str) for r in references
        ):
            raise ValueError("INVALID_PRESENTATION_REFERENCE")
        if len(set(ids)) != len(ids):
            raise ValueError("DUPLICATE_SOURCE_ID")
        for source in sources:
            if not source["id"] or not source["content"] or source["coverage"] not in {"complete", "partial"}:
                raise ValueError("INVALID_SOURCE")
        declaration = manifest.get('source_use')
        if declaration is not None:
            from .source_use import validate_declaration
            validate_declaration(declaration, ids)
        with self.connect() as db:
            old = db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()
            if old and old[0] != encode(manifest):
                raise ValueError("PROJECT_INPUT_IMMUTABLE_CREATE_NEW_PROJECT")
            db.execute("INSERT OR IGNORE INTO state VALUES ('manifest', ?)", (encode(manifest),))
            if old is None:
                # Creation marker only; opening an old empty project is not migration.
                db.execute("INSERT OR IGNORE INTO state VALUES ('acceptance_default', ?)",
                           (encode("requirement-derived-v1"),))
            db.execute("INSERT OR IGNORE INTO state VALUES ('status', ?)", (encode("ready"),))
        if declaration is not None:
            from .source_use import configure_source_use
            configure_source_use(self, **declaration)
        for result in manifest.get("existing_artifacts", []):
            self.save_material(**result, owner="materials", origin="fixture_existing")

    def get(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        result = json.loads(row[0]) if row else default
        if key.startswith('prompt_capture:') and isinstance(result, dict) and result.get('capture_blob'):
            from .blob_store import BlobStore
            result = json.loads(BlobStore(self.root).read(result['capture_blob']))
            if key != 'prompt_capture:' + digest(result):
                raise ActionRejected('PROMPT_CAPTURE_INTEGRITY_MISMATCH')
        return result

    def set(self, key: str, value: object):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, encode(value)))

    @property
    def manifest(self) -> dict:
        result = self.get("manifest")
        if result is None:
            raise ValueError("PROJECT_NOT_INITIALIZED")
        return result

    def sources(self, source_ids: list[str]) -> list[dict]:
        from .catalog import Catalog
        available = {s["id"]: s for s in Catalog(self).sources()}
        if any(i not in available for i in source_ids):
            raise ActionRejected("SOURCE_NOT_IN_PROJECT")
        return [available[i] for i in dict.fromkeys(source_ids)]

    def source_catalog(self):
        from .catalog import Catalog
        return Catalog(self).metadata()

    def superseded_sources(self):
        return {s["replaces_id"]: s["id"] for s in self.source_catalog() if s.get("replaces_id")}

    def artifacts(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT data FROM artifacts ORDER BY rowid").fetchall()
        return [json.loads(r[0]) for r in rows]

    def status(self) -> dict:
        manifest = self.manifest
        result = {
            "goal": manifest["goal"], "status": self.get("status"),
            "sources": [{k: s[k] for k in ("id", "title", "coverage")} for s in manifest["sources"]],
            "artifacts": self.artifacts(), "issues": self.get("issues", []),
            "last_error": self.get("last_error"), "selected_artifact": self.get("selected_artifact"),
            "feedback": self.get("feedback", []),
        }
        from .review_steps import metrics
        steps = metrics(self)
        if steps['drafts']:
            result['reviewer_steps'] = steps
        return result

    def add_feedback(self, message: str):
        """Explicit operator input, not a tool available to the materials agent."""
        if not message.strip():
            raise ValueError("FEEDBACK_REQUIRED")
        with self.run_lock(), self.connect() as db:
            if not db.execute("SELECT 1 FROM state WHERE key='manifest'").fetchone():
                raise ValueError("PROJECT_NOT_INITIALIZED")
            row = db.execute("SELECT value FROM state WHERE key='feedback'").fetchone()
            feedback = json.loads(row[0]) if row else []
            item = {"id": str(uuid4()), "message": message.strip(), "origin": "operator"}
            feedback.append(item)
            db.execute("INSERT OR REPLACE INTO state VALUES ('feedback', ?)", (encode(feedback),))
            db.execute("INSERT OR REPLACE INTO state VALUES ('selected_artifact', 'null')")
            db.execute("INSERT OR REPLACE INTO state VALUES ('status', ?)", (encode("ready"),))
            db.execute("INSERT INTO events(kind,data) VALUES ('feedback_received', ?)", (encode(item),))
        return item

    def save_material(self, title: str, body: str, source_ids: list[str], *, owner: str,
                      origin: str = "agent") -> dict:
        if owner != "materials":
            raise PermissionError("UPSTREAM_MATERIALS_READ_ONLY")
        if not title.strip() or not body.strip() or not source_ids:
            raise ValueError("MATERIAL_AND_SOURCES_REQUIRED")
        sources = self.sources(sorted(set(source_ids)))
        data = {"title": title, "body": body, "source_ids": sorted(set(source_ids)),
                "source_snapshot": digest(sources), "goal": self.manifest["goal"], "owner": owner}
        operation = digest(data)
        # Artifact and operation receipt are the same transaction. Repeating the exact
        # submit after losing its response returns the same immutable artifact.
        with self.connect() as db:
            row = db.execute("SELECT data FROM artifacts WHERE operation=?", (operation,)).fetchone()
            if row:
                return {"reused": True, "artifact": json.loads(row[0])}
            data.update(id=str(uuid4()), operation=operation, origin=origin, review="not_reviewed")
            db.execute("INSERT INTO artifacts VALUES (?, ?, ?)", (data["id"], operation, encode(data)))
            db.execute("INSERT INTO events(kind,data) VALUES ('artifact_committed', ?)",
                       (encode({"artifact_id": data["id"], "operation": operation, "origin": origin}),))
        return {"reused": False, "artifact": data}

    def select_result(self, artifact_id: str) -> dict:
        result = next((a for a in self.artifacts() if a["id"] == artifact_id), None)
        if result is None:
            raise ValueError("ARTIFACT_NOT_IN_PROJECT")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES ('selected_artifact', ?)", (encode(artifact_id),))
            db.execute("INSERT OR REPLACE INTO state VALUES ('status', ?)", (encode("draft_ready"),))
        return {"status": "draft_ready", "artifact_id": artifact_id, "review": "not_reviewed"}

    def analysis(self, operation: str, result: dict | None = None):
        with self.connect() as db:
            if result is not None:
                db.execute("INSERT OR IGNORE INTO analyses VALUES (?, ?)", (operation, encode(result)))
            row = db.execute("SELECT data FROM analyses WHERE operation=?", (operation,)).fetchone()
        return json.loads(row[0]) if row else None

    def event(self, kind: str, data: object):
        from .runtime_metrics import emit
        # An observed call fact remains useful even if SQLite cannot record it.
        # Metrics are diagnostic only, never an authorization or operation receipt.
        try:
            emit(self.root, kind, data)
        except (OSError, ValueError) as error:
            import logging
            logging.getLogger(__name__).warning('Runtime metrics unavailable: %s', type(error).__name__)
        with self.connect() as db:
            db.execute("INSERT INTO events(kind,data) VALUES (?, ?)", (kind, encode(data)))

    def events(self, limit: int | None = None) -> list[dict]:
        with self.connect() as db:
            if limit is None:
                rows = db.execute("SELECT sequence, at, kind, data FROM events ORDER BY sequence").fetchall()
            else:
                rows = list(reversed(db.execute(
                    "SELECT sequence, at, kind, data FROM events ORDER BY sequence DESC LIMIT ?", (limit,)
                ).fetchall()))
        return [{"sequence": n, "at": at, "kind": kind, "data": json.loads(data)} for n, at, kind, data in rows]
