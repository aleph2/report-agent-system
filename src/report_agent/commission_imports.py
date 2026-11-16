"""Immutable host inputs for commission planning. Owner authority is recorded separately."""
from functools import partial
from .content_store import ContentStore
from .errors import ActionRejected
from .plan_inputs import _get, _head, _save
from .store import Store


TYPES = ("CommissionSourceRoles", "CommissionOwnerRecords", "CommissionSourceUsePolicy", "CommissionSourceManifest")


def _record(storage, kind):
    if isinstance(storage, Store):
        with storage.connect() as db:
            return _head(db, kind)
    return _head(storage, kind)


source_roles = partial(_get, "CommissionSourceRoles")
owner_records = partial(_get, "CommissionOwnerRecords")


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
