"""Case-local immutable input versions used to assemble a commission proposal."""
from functools import partial
import json
from typing import overload

from .store import Store


_PLAN_INPUTS = ("PlanSkeleton", "PlanDraft", "PlanTextProfiles")


PRIVATE_INPUT_TYPES = frozenset(_PLAN_INPUTS) | {"CommissionSourceRoles", "CommissionOwnerRecords", "CommissionSourceUsePolicy", "CommissionSourceManifest"}
PRIVATE_INPUT_TYPES |= {'IssueWaits', 'IssueRecord', 'IssueBinding', 'IssueRoute', 'IssueAnswer', 'ImportedSourceReadFacts'}


def _head(db, kind):
    # A fresh or historical Store can be inspected before ContentStore is installed.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_heads'").fetchone():
        return None
    row = db.execute("""SELECT v.data FROM content_heads h JOIN content_versions v USING(type,id,version)
                        WHERE h.type=? AND h.id=?""", (kind, kind)).fetchone()
    return json.loads(row[0]) if row else None


@overload
def _get[T](kind, storage, default: T) -> dict | T: ...


@overload
def _get(kind, storage, default: None = None) -> dict | None: ...


def _get(kind, storage, default=None):
    if isinstance(storage, Store):
        with storage.connect() as db:
            return _get(kind, db, default)
    record = _head(storage, kind)
    return record["payload"] if record else default


def _save(kind, db, value, *, actor=None):
    from .content_store import Actor, ContentStore
    previous = _head(db, kind)
    if previous and previous["payload"] == value:
        return previous["ref"]
    ref = previous["ref"] if previous else None
    return ContentStore._insert(db, actor or Actor("host", "host", "commission-preparation"),
                                kind, value, id=kind, version=ref["version"] + 1 if ref else 1,
                                previous_ref=ref)


get_skeleton = partial(_get, "PlanSkeleton")
get_draft = partial(_get, "PlanDraft")
get_text_profiles = partial(_get, "PlanTextProfiles")
save_skeleton = partial(_save, "PlanSkeleton")
save_draft = partial(_save, "PlanDraft")
save_text_profiles = partial(_save, "PlanTextProfiles")


def current_refs(db):
    """Read the current version references."""
    return [record["ref"] for kind in _PLAN_INPUTS if (record := _head(db, kind))]


def frozen_refs(db):
    """Pin the host inputs used by a submitted proposal; drafts remain work in progress."""
    refs = []
    for kind in ("PlanSkeleton", "PlanTextProfiles"):
        record = _head(db, kind)
        if record:
            refs.append(record["ref"])
    from . import commission_imports
    return refs + commission_imports.frozen_refs(db)
