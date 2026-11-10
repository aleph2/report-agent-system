"""Construct an accepted M5-format synthetic case for historical-reader tests only."""
from report_agent import commission_imports, plan_inputs
from report_agent.source_use import _policy, _version_policy, validate_declaration
from report_agent.errors import ActionRejected


def configure_source_use(store, source_ids, authorization_origin):
    from report_agent.content_store import ContentStore
    ContentStore(store)
    declaration=validate_declaration(dict(source_ids=source_ids,authorization_origin=authorization_origin))
    prior=commission_imports.source_policy_ref(store)
    if prior:
        if _policy(store,prior)["declaration"] != declaration:
            raise ActionRejected("SOURCE_USE_AUTHORITY_IMMUTABLE")
        return prior
    with store.connect() as db:
        return plan_inputs._save("CommissionSourceUsePolicy",db,_version_policy(store,declaration,db))


def restrict_supplied_case_files(store, source_ids):
    """Construct the intake boundary of a synthetic case, without an approval policy."""
    from report_agent.content_store import ContentStore
    ContentStore(store)
    allowed=set(source_ids)
    with store.connect() as db:
        manifest=plan_inputs._head(db,"CommissionSourceManifest")
        payload=dict(manifest["payload"] if manifest else {})
        payload["sources"]=store.sources(sorted(allowed))
        ref=plan_inputs._save("CommissionSourceManifest",db,payload)
        roles=commission_imports.source_roles(db,{})
        plan_inputs._save("CommissionSourceRoles",db,{k:v for k,v in roles.items() if v["id"] in allowed})
        return ref
