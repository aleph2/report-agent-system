"""Immutable host inputs for commission planning. Owner authority is recorded separately."""
from . import legacy_state as legacy
from .content_store import ContentStore
from .errors import ActionRejected
from .plan_inputs import _head, _save
from .store import Store


TYPES = ("CommissionSourceRoles", "CommissionOwnerRecords", "CommissionSourceUsePolicy", "CommissionSourceManifest")


def _record(storage, kind):
    if isinstance(storage, Store):
        with storage.connect() as db:
            return _head(db, kind)
    return _head(storage, kind)


def source_roles(storage, default=None):
    record = _record(storage, "CommissionSourceRoles")
    return record["payload"] if record else legacy.historical_commission_source_roles(storage, default)


def owner_records(storage, default=None):
    record = _record(storage, "CommissionOwnerRecords")
    return record["payload"] if record else legacy.get_commission_owner_records(storage, default)


def source_policy_ref(storage):
    record = _record(storage, "CommissionSourceUsePolicy")
    return record["ref"] if record else None


def requires_source_policy(storage):
    return bool(_record(storage, "CommissionSourceManifest"))


def install_source_roles(store, roles):
    ContentStore(store)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = source_roles(db, {})
        if any(roles.get(name) != value for name, value in old.items()):
            raise ActionRejected("SOURCE_ROLE_IMMUTABLE")
        return _save("CommissionSourceRoles", db, roles)


def save_owner_records(db, entry):
    return _save("CommissionOwnerRecords", db, entry)


def frozen_refs(db):
    return [r["ref"] for kind in TYPES if (r := _head(db, kind))]
