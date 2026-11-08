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
from .assertions.ids import request_digest
from .assertions.session import Commission
from .assertions.refusals import CATALOG
from .assertions.schema.kinds import actor_class_for


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
        return actor_class_for(self.role)

    @property
    def binding(self):
        return dict(actor=self.principal, role=self.role, task=self.task, attempt=self.attempt,
                    plan=self.plan, snapshot=self.snapshot,
                    packet_digest=request_digest([sorted(self.subjects), sorted(self.packet)]))

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
        self.commission = Commission(run_dir)
        self.access = Path(run_dir).resolve() / "assertion-access.sqlite3"
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS grants(actor,role,task,attempt,payload NOT NULL,
                        PRIMARY KEY(actor,role,task,attempt))""")

            # Adopt any fingerprints created by the pre-archive S3 implementation.
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='resources'").fetchone():
                self.commission.pin(db.execute("SELECT family,id,digest FROM resources"))
                db.execute("DROP TABLE resources")

    def authorize(self, grant):
        if grant.role not in CATALOG["roles"] or grant.actions - CATALOG["actions"].keys():
            raise ValueError("Unknown role or action")
        payload = json.dumps(asdict(grant), default=_encode, allow_nan=False)
        with closing(sqlite3.connect(self.access)) as db, db:
            # Lock launch authority first, as the action path does. Pins become durable
            # before the grant can be observed. A lost acknowledgement permits an
            # exact reissue and cannot authorize changed bytes under a pinned ID.
            db.execute("BEGIN IMMEDIATE")
            resources = json.loads(payload)["resources"]
            self.commission.pin_resources(resources)
            db.execute("INSERT OR REPLACE INTO grants VALUES(?,?,?,?,?)", (*grant.key, payload))

    def revoke(self, grant):
        with closing(sqlite3.connect(self.access)) as db, db:
            db.execute("DELETE FROM grants WHERE (actor,role,task,attempt)=(?,?,?,?)", grant.key)

    def bind(self, grant, *, native_call_id, action):
        if action not in CATALOG["actions"] or not isinstance(native_call_id, str) or not native_call_id.strip():
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
            row = db.execute("SELECT payload FROM grants WHERE (actor,role,task,attempt)=(?,?,?,?)",
                             key).fetchone()
            if row is None:
                raise PermissionError("Grant revoked")
            current = Grant(**json.loads(row[0], object_hook=_decode))
            if current.binding != binding:
                raise PermissionError("Packet or assignment binding changed")
            yield current
