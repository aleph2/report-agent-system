"""One planning sheet authorizes pages; Writer facts remain independently reviewable."""
from uuid import NAMESPACE_URL, uuid5

from . import assertions
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


def records(store, plan_ref, subject=None):
    rows = Commission.page_records(store.root)
    bindings = {row["id"] for row, _ in rows if row["claim"]["kind"] == "convention"
                and row["claim"]["rule"] == encode(plan_ref)}
    return [(row, state) for row, state in rows if
            (row["id"] in bindings or any(g["assertion_id"] in bindings for g in row["grounds"]))
            and (subject is None or row["subject"] == subject)]


def current(state):
    return state["active"] and not state["stale"] and not state["challenged"]


def confirmed(store, plan_ref, subject, indicator=None):
    return [row for row, state in records(store, plan_ref, subject)
            if row["claim"]["kind"] == "convention" and current(state) and state["status"] == "confirmed"
            and (indicator is None or row["claim"]["page_binding"]["indicator_id"] == indicator)]


def propose(cs, actor, operation, subject, indicator, pages):
    # Trusted single-item callers retain the same contract; the model uses only lists.
    return propose_many(cs, actor, operation,
        [dict(subject=subject, indicator_ids=[indicator], pages=pages)])['bindings'][0]


def propose_many(cs, actor, operation, items):
    from .planning_assertions import _issuer, BindingProposalInput
    from .planning_inputs import model_value
    from .commission_planning import _batch_error, _reject_batch
    from .commission_plan import read_plan
    from .source_use import source_version_material, validate_source_versions
    from .assertions.actions import _record_convention_batch
    if not isinstance(items, list) or not items:
        raise ActionRejected('PAGE_BINDING_NONEMPTY_BATCH_REQUIRED')
    plan = read_plan(cs.store)
    object_ids = {o['object_id'] for o in plan['payload']['objects']} if plan else set()
    indicator_ids = {r['id'] for r in (plan['payload'].get('method_pack') or {}).get('indicators', [])} if plan else set()
    prepared, errors, seen, source_ids = [], [], set(), []
    normalized = []
    for index, raw in enumerate(items):
        try:
            item = model_value(BindingProposalInput, raw, 'binding').model_dump(mode='json')
            subject = item['subject']
            principal = _issuer(cs, actor, subject)
            if not plan or subject not in object_ids:
                raise ActionRejected('PAGE_BINDING_SAVED_PLAN_OBJECT_REQUIRED')
            fields = []
            unknown = [key for key in item['indicator_ids'] if key not in indicator_ids]
            if unknown:
                fields.append(dict(field='indicator_ids', reason='PAGE_BINDING_METHOD_INDICATOR_REQUIRED',
                    choices=sorted(indicator_ids), message='Unknown indicator IDs: ' + ', '.join(unknown)))
            duplicates = []
            for key in item['indicator_ids']:
                pair = (subject, key)
                if pair in seen:
                    duplicates.append(key)
                seen.add(pair)
            if duplicates:
                fields.append(dict(field='indicator_ids', reason='PAGE_BINDING_DUPLICATE_PAIR',
                    message='Duplicate object/indicator pairs: ' + ', '.join(duplicates)))
            bound = []
            for page_index, page in enumerate(item['pages']):
                try:
                    validate_source_versions(cs, actor, source_ids=[page['source_id']])
                    version, material = source_version_material(cs, page['source_id'])
                    if str(page['page']) not in material['pages']:
                        from .document_tools import source_page_info
                        from .workspace import Workspace
                        try:
                            source_page_info(Workspace(cs.store), page['source_id'], page['page'])
                        except ActionRejected:
                            raise ActionRejected('PAGE_BINDING_PHYSICAL_PAGE_REQUIRED') from None
                    bound.append(dict(source_version=version, page=page['page']))
                    if page['source_id'] not in source_ids:
                        source_ids.append(page['source_id'])
                except (ActionRejected, ActionForbidden) as error:
                    fields.append(dict(field='pages.' + str(page_index), reason=str(error).split(':')[0],
                        message=str(error)))
            if fields:
                raise ActionRejected('PAGE_BINDING_ITEMS_INVALID: ' + '; '.join(field['reason'] for field in fields),
                    diagnostic={'fields': fields})
            normalized.append(item)
            prepared.append((principal, subject, item['indicator_ids'], bound))
        except (ActionRejected, ActionForbidden) as error:
            errors.append(_batch_error(index, error, 'binding'))
    if errors:
        _reject_batch(errors)
    # Prepared source versions precede assertions; failed assertions may retain these snapshots.
    if source_ids:
        cs.capture_sources(actor, 'page-binding-sources:' + operation, source_ids)
    request_pin = digest({'plan_ref': plan['ref'], 'items': normalized})
    host, entries = AssertionHost(cs.store.root), []
    for principal, subject, indicators, bound in prepared:
        for indicator in indicators:
            index = len(entries)
            child = operation + ':' + str(index)
            grant = Grant(principal, actor.role, actor.task_id,
                'page-binding:' + operation + ':' + request_pin + ':' + str(index), digest(plan['ref']),
                frozenset({subject}), frozenset(page['source_version'] for page in bound), frozenset({'record_convention'}))
            claim = dict(kind='convention', scope='source_page_binding', rule=encode(plan['ref']),
                         page_binding=dict(indicator_id=indicator, pages=bound))
            try:
                context = host.issue_once(grant, 'record_convention', child)
            except (ValueError, PermissionError) as error:
                raise ActionRejected(str(error)) from error
            entries.append((context, dict(subject=subject, claim=claim)))
    try:
        bindings = _record_convention_batch(entries)
    except (ValueError, PermissionError) as error:
        raise ActionRejected(str(error)) from error
    return {'bindings': bindings}


def confirm_reply(store, owner, issue, checkpoint, decision_ref):
    from . import commission_assertions
    commission_assertions._require_actor(owner, "owner")
    if commission_assertions.checkpoint_answer(store,"plan",issue) != decision_ref:
        raise ActionRejected("PAGE_BINDING_SAVED_OWNER_REPLY_REQUIRED")
    decision = ContentStore(store).read(decision_ref)["payload"]
    if not decision["approved"]:
        return
    excluded = set(decision.get("unconfirmed_page_bindings", []))
    sheet = checkpoint.get("page_bindings", [])
    if not excluded <= set(sheet):
        raise ActionRejected("PAGE_BINDING_EXCEPTION_OUTSIDE_SHEET")
    rows = {r["id"]:r for r,_ in records(store, checkpoint["plan_ref"])}
    host = AssertionHost(store.root)
    for key in sheet:
        if key in excluded:
            continue
        row = rows.get(key)
        if row is None or row["claim"]["kind"] != "convention":
            raise ActionRejected("PAGE_BINDING_SHEET_RECORD_MISSING")
        operation = "page-confirm:" + issue + ":" + key
        grant = Grant(str(uuid5(NAMESPACE_URL, owner.id)), "owner", owner.task_id, operation,
                      digest(checkpoint["plan_ref"]), frozenset({row["subject"]}), frozenset({key}), frozenset({"confirm"}))
        assertions.confirm(host.issue_once(grant,"confirm",operation), subject=row["subject"],
            claim=dict(kind="act",effect="confirm",target=key,reason="Planning reply " + encode(decision_ref)))


def sheet_route(store, plan_ref):
    """A page-sheet checkpoint retires file approval only for that exact plan."""
    from . import commission_assertions
    for action, body, state in commission_assertions._rows(store):
        if action == "ask" and current(state):
            import json
            data = json.loads(body["claim"]["text"])
            if data.get("plan_ref") == plan_ref and "page_bindings" in data:
                return True
    return False


def extracted_pages(store, plan_ref, subject, quote, indicator=None):
    bindings = {r["id"] for r in confirmed(store,plan_ref,subject,indicator)}
    return {(r["claim"]["citation"]["source_version"],r["claim"]["citation"]["page"])
            for r,state in records(store,plan_ref,subject)
            if r["claim"]["kind"] == "source" and current(state)
            and r["claim"].get("citation",{}).get("quote") == quote
            and any(g["assertion_id"] in bindings for g in r["grounds"])}
