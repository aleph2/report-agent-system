"""Trusted launch-side capabilities for the commission's assertion store."""
from base64 import b64decode, b64encode
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
import json
import sqlite3
from uuid import UUID
from pathlib import Path
from functools import partial

from .operation_identity import bound_native_id
from .assertions import launch


@dataclass(frozen=True)
class Grant:
    principal: str
    role: str
    task: str
    attempt: str
    plan: str
    subjects: frozenset[str]
    packet: frozenset[str]
    actions: frozenset[str]
    snapshot: str | None = None
    resources: dict = field(default_factory=dict)

    def __post_init__(self):
        if str(UUID(self.principal)) != self.principal:
            raise ValueError("Canonical principal UUID required")
        for name in ("subjects", "packet", "actions"):
            object.__setattr__(self, name, frozenset(getattr(self, name)))
        for value in [self.task, self.attempt, self.plan, *self.subjects, *self.packet]:
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError("Invalid binding identifier")

    @property
    def actor_class(self):
        return launch.actor_class_for(self.role)

    @property
    def binding(self):
        return dict(actor=self.principal, role=self.role, task=self.task, attempt=self.attempt,
                    plan=self.plan, snapshot=self.snapshot,
                    packet_digest=launch.request_digest([sorted(self.subjects), sorted(self.packet)]))

    @property
    def key(self):
        return (self.principal, self.role, self.task, self.attempt)


def _encode(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, bytes):
        return {"$base64": b64encode(value).decode("ascii")}
    raise TypeError("Unsupported launch resource")


def _decode(obj):
    return b64decode(obj["$base64"], validate=True) if obj.keys() == {"$base64"} else obj


class AssertionHost:
    def __init__(self, run_dir):
        self.commission = launch.Commission(run_dir)
        self.access = Path(run_dir).resolve() / "assertion-access.sqlite3"
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS grants(actor,role,task,attempt,payload NOT NULL,
                        PRIMARY KEY(actor,role,task,attempt))""")

            # Adopt any fingerprints created by the pre-archive S3 implementation.
            db.execute("BEGIN IMMEDIATE")
            if "revoked" not in {r[1] for r in db.execute("PRAGMA table_info(grants)")}:
                db.execute("ALTER TABLE grants ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE IF NOT EXISTS source_payloads(version TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='resources'").fetchone():
                self.commission.pin(db.execute("SELECT family,id,digest FROM resources"))
                db.execute("DROP TABLE resources")

    @staticmethod
    def _load(db, key):
        row = db.execute("SELECT payload,revoked FROM grants WHERE (actor,role,task,attempt)=(?,?,?,?)",
                         key).fetchone()
        if row is None or row[1]:
            return None
        payload = json.loads(row[0], object_hook=_decode)
        if "stored_sources" in payload:
            sources = {}
            for version in payload.pop("stored_sources"):
                reference = db.execute("SELECT payload FROM source_payloads WHERE version=?", (version,)).fetchone()
                if reference is None:
                    raise ValueError("Missing pinned source payload")
                sources[version] = json.loads(reference[0], object_hook=_decode)
            payload["resources"]["sources"] = sources
        return Grant(**payload)

    def grant_exists(self, key):
        """True for issued and revoked grants, so missing configuration cannot mask revocation."""
        with closing(sqlite3.connect(self.access.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT 1 FROM grants WHERE (actor,role,task,attempt)=(?,?,?,?)",
                              key).fetchone() is not None

    def lookup(self, key):
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("BEGIN")
            return self._load(db, key)

    def _authorize(self, grant, *, once):
        launch.validate_launch(grant.role, grant.actions)
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if once:
                exists = db.execute("SELECT revoked FROM grants WHERE (actor,role,task,attempt)=(?,?,?,?)",
                                    grant.key).fetchone()
                if exists is not None:
                    if exists[0]:
                        raise PermissionError("Grant revoked")
                    live = self._load(db, grant.key)
                    if live is None or live.binding != grant.binding:
                        raise ValueError("OPERATION_CONFLICT")
                    return live
            payload = json.loads(json.dumps(asdict(grant), default=_encode, allow_nan=False))
            resources = payload["resources"]
            self.commission.pin_resources(resources)
            if "sources" in resources:
                sources = resources.pop("sources")
                for version, material in sources.items():
                    db.execute("INSERT OR IGNORE INTO source_payloads VALUES(?,?)",
                               (version, json.dumps(material, ensure_ascii=False)))
                payload["stored_sources"] = sorted(sources)
            db.execute("INSERT OR REPLACE INTO grants(actor,role,task,attempt,payload,revoked) VALUES(?,?,?,?,?,0)",
                       (*grant.key, json.dumps(payload, ensure_ascii=False)))
        return grant

    def authorize(self, grant):
        self._authorize(grant, once=False)

    def issue_once(self, grant, action, call_id):
        ctx = self.bind(grant, native_call_id=call_id, action=action)
        self._authorize(grant, once=True)
        return ctx

    def recover_receipt(self, operation_id):
        return self.commission.recover_receipt(operation_id)

    def revoke(self, grant):
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("UPDATE grants SET revoked=1 WHERE (actor,role,task,attempt)=(?,?,?,?)", grant.key)

    def bind(self, grant, *, native_call_id, action):
        launch.validate_launch(grant.role, [action])
        if not isinstance(native_call_id, str) or not native_call_id.strip():
            raise ValueError("Valid native action and call ID required")
        return self.commission.bind(partial(self._authorized, grant.key, grant.binding), grant.binding, action,
                                    bound_native_id(grant.principal, action, native_call_id))

    def issue(self, grant, action, call_id):
        self.authorize(grant)
        return self.bind(grant, native_call_id=call_id, action=action)

    @contextmanager
    def _authorized(self, key, binding):
        # Hold a reader lock on launch authority until the content transaction finishes.
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("BEGIN")
            current = self._load(db, key)
            if current is None:
                raise PermissionError("Grant revoked")
            if current.binding != binding:
                raise PermissionError("Packet or assignment binding changed")
            yield current
