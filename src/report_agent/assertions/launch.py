"""Own the content transaction while the launch host holds its authorization view."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
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

    def produced_ids(self, *, actor, task, subject, kind):
        """IDs available to reissue in this producer's task packet."""
        with self._store.reader() as db:
            return frozenset(row[0] for row in db.execute(
                """SELECT id FROM assertions WHERE body ->> '$.was_attributed_to' = ?
                   AND body ->> '$.was_generated_by' = ? AND body ->> '$.subject' = ?
                   AND body ->> '$.claim.kind' = ?""", (actor, task, subject, kind)))

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
