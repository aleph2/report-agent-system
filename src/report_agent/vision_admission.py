"""Vision's trusted identity adapter over shared bounded-call/native-pause facts."""
import json
from .bounded_operations import reserve_once, UNRESOLVED_STATES
from .errors import ActionRejected
from .store import digest, encode
from .native_admission import exact_call_key, wait_for_exact_resume

CODE = 'VISION_OUTCOME_UNRESOLVED'
KIND = 'vision_unknown_admission'


def reserve_vision(store, operation, material_identity, actor):
    # Actor comes from a server-bound tool closure, never a model argument.
    owner = actor.__dict__ if actor is not None else None
    # Exact request identity matches the shared success cache. A different
    # caller cannot turn an unresolved identical request into a fresh dispatch.
    key = 'vision_attempt:' + operation
    def denied(conflicts):
        raise ActionRejected(CODE + ': ' + encode({
            'operation':operation, 'material_identity':material_identity, 'actor':owner,
            'conflicts':conflicts, 'provider_invoked':False,
            'note':'Inspect the original unresolved request. New wording, identifiers or model configuration do not establish new image material or retry authority.'}))

    def check_new(db):
        # Retain protection for receipts written with the earlier owner key.
        for raw, in db.execute("SELECT value FROM state WHERE json_extract(value,'$.kind')='vision' "
                              "AND json_extract(value,'$.operation')=?", (operation,)):
            prior = json.loads(raw)
            if prior['state'] in UNRESOLVED_STATES:
                denied([{'operation':operation, 'state':prior['state']}])
        # Old observations had no actor or durable admission record. Preserve
        # exact unknowns without inventing their owner or broader association.
        last = db.execute("SELECT sequence FROM events WHERE kind='vision_request' "
            "AND json_extract(data,'$.operation')=? AND json_type(data,'$.actor') IS NULL "
            'ORDER BY sequence DESC LIMIT 1', (operation,)).fetchone()
        if last and not db.execute("SELECT 1 FROM events WHERE kind='vision_response' "
                "AND json_extract(data,'$.operation')=? AND sequence>? LIMIT 1",
                (operation,last[0])).fetchone():
            denied([{'operation':operation,'state':'historical_unresolved','actor':None,
                     'scope_limit':'Historical actor unknown; exact operation only.'}])
        if owner is None:
            return  # Non-native direct callers have exact-operation protection only.
        conflicts=[]
        for raw, in db.execute("SELECT value FROM state WHERE json_extract(value,'$.kind')='vision' "
                              "AND json_extract(value,'$.material_identity')=?", (material_identity,)):
            prior=json.loads(raw)
            if prior.get('actor') == owner and prior['state'] in UNRESOLVED_STATES:
                conflicts.append({'operation':prior['operation'],'state':prior['state'],'actor':owner})
        if conflicts:
            denied(conflicts)

    prior = reserve_once(store, key, {'kind':'vision','state':'reserved','operation':operation,
        'material_identity':material_identity,'actor':owner}, check_new=check_new)
    if prior and prior['state'] in UNRESOLVED_STATES:
        denied([{'operation':operation,'state':prior['state'],'actor':owner}])
    return key, prior


async def admitted_call(workspace, role, call, handler):
    from .text_work import actor_for_tool
    actor = actor_for_tool(workspace, role)
    key = exact_call_key('vision_interrupt:', actor.__dict__, call)
    pending = workspace.store.get(key)
    if pending:
        # No vision release adapter exists yet. Boolean/manual resume values
        # cannot release a duplicate. A future host-only exact disposition must
        # be explicitly implemented and verified rather than assumed here.
        wait_for_exact_resume(pending, lambda event: None)
    try:
        return await handler()
    except ActionRejected as exc:
        code, _, details = str(exc).partition(':')
        if code != CODE:
            raise
        event = {'kind':KIND,'pending_key':key,'actor':actor.__dict__,
                 'tool_call_id':call['id'],'call_digest':digest(call),
                 'details':json.loads(details),'provider_invoked':False}
        workspace.store.set(key, event)
        workspace.store.event('vision_admission_paused', event)
        wait_for_exact_resume(event, lambda value: None)

