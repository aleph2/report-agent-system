"""Own the content transaction while the launch host holds its authorization view."""
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, ContextManager

from .export import export_jsonl, reload_jsonl
from .ids import request_digest
from .store import FROZEN_FAMILIES, Store


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
