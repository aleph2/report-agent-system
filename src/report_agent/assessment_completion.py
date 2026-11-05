"""Trusted one-shot Writer assessment recovery; never resumes a stopped report host."""
import argparse
import asyncio
from contextlib import AsyncExitStack, closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from langchain.agents.middleware import AgentMiddleware, hook_config

from .planning_budget import budget_scope_cost
from .request_budget import RequestBudgetExceeded
from .store import digest

LIMIT = 10_000_000
GRANT_LIMIT = 200_000_000
PRESERVED_ATTEMPT = '6e3df9b9-d8b8-459a-86c7-e3adada9a3e1'
FRESH_OPERATION = 'owner-approved-assessment-completion-fresh-continuation'
READ_TOOLS = frozenset({'project_status', 'read_source_page', 'search_sources', 'inspect_source_page',
    'read_result', 'content_status', 'read_object_index', 'read_context', 'read_content_index',
    'read_content_selection', 'observe_evidence', 'read_feedback', 'get_operation_receipt',
    'read_commission_plan', 'read_task_assignment', 'read_decision_state'})


def read_finance(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('EXISTING_TOKEN_LEDGER_REQUIRED')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        auth = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
        rows = db.execute('SELECT id,model,reserved,used,state,response_id,reason,at FROM attempts ORDER BY id').fetchall()
        db.rollback()
    if auth is None:
        raise ValueError('TOKEN_AUTHORIZATION_REQUIRED')
    return {'auth': list(auth), 'rows': [list(row) for row in rows]}


class CompletionBudget:
    def __init__(self, finance, baseline, grant_baseline, bounds, *, writer_model, maximum_tokens=LIMIT, preserved_hold=None):
        self.finance, self.baseline = finance, deepcopy(baseline)
        self.grant_baseline, self.bounds = deepcopy(grant_baseline), dict(bounds)
        if writer_model not in self.bounds:
            raise ValueError('ASSESSMENT_COMPLETION_WRITER_BOUND_REQUIRED')
        if maximum_tokens not in (LIMIT, 2 * LIMIT):
            raise ValueError('ASSESSMENT_COMPLETION_LIMIT_INVALID')
        self.maximum_tokens = maximum_tokens
        self.writer_model = writer_model
        self.preserved_hold = deepcopy(preserved_hold)
        if preserved_hold is not None and (maximum_tokens != 2 * LIMIT or len(preserved_hold) != 8 or
                preserved_hold[:6] != [PRESERVED_ATTEMPT, writer_model, 2_000_000, None, 'reserved', None]):
            raise ValueError('ASSESSMENT_COMPLETION_PRESERVED_HOLD_INVALID')

    def check(self):
        now = self.finance()
        if self.preserved_hold is not None and next((row for row in now['rows']
                if row[0] == PRESERVED_ATTEMPT), None) != self.preserved_hold:
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_PRESERVED_HOLD_CHANGED')
        used, held, _ = budget_scope_cost(self.baseline, now)
        grant_used, grant_held, _ = budget_scope_cost(self.grant_baseline, now)
        if used + held > self.maximum_tokens:
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_TOKEN_LIMIT')
        if grant_used + grant_held > GRANT_LIMIT:
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_GRANT_LIMIT')
        old = {row[0] for row in self.baseline['rows']}
        added = [row for row in now['rows'] if row[0] not in old]
        if any(row[1] != self.writer_model for row in added):
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_WRITER_MODEL_ONLY')
        pending = [row for row in added if row[4] in ('reserved', 'unknown') and row != self.preserved_hold]
        # Admission runs after reserve: only the current serial request may be held.
        if len(pending) > 1 or any(row[4] == 'unknown' for row in pending):
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_UNRESOLVED_ATTEMPT')
        return used, held

    def observation(self):
        used, held, _ = budget_scope_cost(self.baseline, self.finance())
        return {'scope_id': 'assessment-completion', 'maximum_tokens': self.maximum_tokens, 'recorded_tokens': used,
            'reserved_or_unknown_upper_bounds': held, 'remaining_for_new_reservations': max(0, self.maximum_tokens-used-held),
            'model_reservation_bounds': self.bounds, 'includes_original_phases': True}


def claim_launch(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def _save(path, value):
    temporary = Path(path).with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_decision_pin(decision, approved):
    if decision['ref'] != approved['ref'] or decision['payload_digest'] != approved['payload_digest']:
        raise ValueError('ASSESSMENT_COMPLETION_DECISION_CHANGED')


def require_writer_model(model, expected):
    if (model.model_name != expected or any(getattr(client, 'max_retries', None) != 0
            for client in (model, model.root_client, model.root_async_client))):
        raise ValueError('ASSESSMENT_COMPLETION_WRITER_MODEL_OR_RETRIES_CHANGED')


def selected_tools(tools):
    return [tool for tool in tools if (getattr(tool, 'name', None) or getattr(tool, '__name__', None))
            in READ_TOOLS | {'calculate_assessment'}]


def saved_assessments(contents, plan_ref, object_ids, owner_id):
    result = {}
    for object_id in object_ids:
        ref = contents.store.get('g6_assessment:' + digest([plan_ref, object_id]))
        if ref is None:
            continue
        record = contents.read(ref)
        receipt = contents.store.get('assessment_receipt:' + digest(ref))
        if (ref.get('type') != 'Assessment' or record['payload'].get('commission_plan_ref') != plan_ref
                or record['payload'].get('object_id') != object_id or record['owner_id'] != owner_id
                or not receipt or receipt.get('assessment_ref') != ref):
            raise ValueError('ASSESSMENT_COMPLETION_SELECTION_INVALID')
        result[object_id] = ref
    return result


class AssessmentCompletionStop(AgentMiddleware):
    def __init__(self, complete):
        self.complete = complete

    @hook_config(can_jump_to=['end'])
    async def abefore_model(self, state, runtime):
        if self.complete():
            return {'jump_to': 'end'}


def _preflight(case, evidence, env, grant_file):
    authority, working, paths = [_load(evidence / name) for name in
        ('owner-approval.json', 'working-copy.json', 'financial-authority-paths.json')]
    if authority.get('hard_cap_tokens') != LIMIT or not all(authority.get(k) for k in ('turn_id', 'message_id')):
        raise ValueError('ASSESSMENT_COMPLETION_OWNER_AUTHORITY_REQUIRED')
    if case != Path(working['working_case']).resolve() or case == Path(working['source']).resolve():
        raise ValueError('ASSESSMENT_COMPLETION_WORKING_COPY_REQUIRED')
    if _sha(Path(working['source']) / 'state.db') != working['source_db_sha256']:
        raise ValueError('ASSESSMENT_COMPLETION_SOURCE_CHANGED')
    run = Path(paths['g5_prepared']).resolve().parent
    if run.name != 'g5-candidate-01':
        raise ValueError('ASSESSMENT_COMPLETION_G5_ONLY')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        except (FileNotFoundError, PermissionError):
            continue
        if any(arg == str(run) or arg.startswith(str(run) + '/') for arg in argv):
            raise ValueError('ASSESSMENT_COMPLETION_G5_MUST_BE_STOPPED')
    deployment, prepared, config = [_load(run / name) for name in
        ('deployment.json', 'prepared.json', 'source/config/current.json')]
    if (env != (Path(deployment['repository']) / '.env').resolve()
            or grant_file != Path(deployment['budget_authority']).resolve()
            or _sha(grant_file) != deployment['budget_authority_sha256']):
        raise ValueError('ASSESSMENT_COMPLETION_DEPLOYMENT_AUTHORITY_MISMATCH')
    grant = _load(grant_file)['grant_scope']
    compact = json.dumps(grant['baseline'], sort_keys=True, separators=(',', ':')).encode()
    if grant['maximum_tokens'] != GRANT_LIMIT or hashlib.sha256(compact).hexdigest() != grant['baseline_sha256']:
        raise ValueError('ASSESSMENT_COMPLETION_GRANT_BASELINE_INVALID')
    from .model_config import load_mixed_services, role_service
    load_mixed_services(env)
    os.environ.update(REPORT_SDK_RETRIES='0', REPORT_CONNECT_RETRIES='0', REPORT_REASONING_EFFORT=config['reasoning_effort'])
    name, url, key = role_service('writer')
    if (name != config['models']['writer'] or not key or urlsplit(url).scheme != 'https'
            or hashlib.sha256(url.rstrip('/').encode()).hexdigest() != prepared['endpoint_pins']['writer']):
        raise ValueError('ASSESSMENT_COMPLETION_WRITER_PIN_MISMATCH')
    from .blob_store import verify_case_blobs
    blobs = verify_case_blobs(case)
    ledger = Path(deployment['ledger']).resolve()
    if ledger != Path(paths['account_ledger']).resolve():
        raise ValueError('ASSESSMENT_COMPLETION_LEDGER_MISMATCH')
    now = read_finance(ledger)
    account = _load(grant_file)
    if now['auth'][0] != account['maximum_tokens'] or json.loads(now['auth'][1]) != account['model_bounds']:
        raise ValueError('ASSESSMENT_COMPLETION_ACCOUNT_CHANGED')
    return authority, working, grant, ledger, now, blobs, name, hashlib.sha256(url.rstrip('/').encode()).hexdigest()



def require_prior_process_absent(prior, case):
    """Check the saved process identity and every matching completion argv."""
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            start = (process / 'stat').read_text().rpartition(')')[2].split()[19]
            argv = (process / 'cmdline').read_bytes().decode(errors='replace').split('\0')
            same = (int(process.name) == prior['pid'] and start == prior['process_start_ticks'] and
                process.stat().st_uid == prior['uid'])
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        matching = (int(process.name) != os.getpid() and
            any(arg == str(case) or arg == '--case=' + str(case) for arg in argv) and
            any(arg == 'report_agent.assessment_completion' or arg.endswith('/assessment_completion.py') for arg in argv))
        if same or matching:
            raise ValueError('ASSESSMENT_EXTENSION_PRIOR_PROCESS_PRESENT')


def require_extension(case, evidence, authority_path, binding, now):
    folder = evidence / 'extension-1'
    if (folder / 'writer-launch.json').exists():
        raise FileExistsError('ASSESSMENT_EXTENSION_ALREADY_LAUNCHED_INSPECT_OUTCOME')
    if authority_path != folder / 'owner-approval.json':
        raise ValueError('ASSESSMENT_EXTENSION_AUTHORITY_PATH_INVALID')
    authority = _load(authority_path)
    prior_path, baseline_path = evidence / 'writer-launch.json', evidence / 'completion-budget-baseline.json'
    if (not all(authority.get(k) for k in ('turn_id', 'message_id')) or
            authority.get('additional_tokens') != LIMIT or authority.get('maximum_tokens') != 2 * LIMIT or
            authority.get('grant_limit_unchanged') != GRANT_LIMIT or
            authority.get('prior_launch_path') != str(prior_path) or
            authority.get('original_baseline_path') != str(baseline_path) or
            authority.get('prior_launch_sha256') != _sha(prior_path) or
            authority.get('original_baseline_sha256') != _sha(baseline_path)):
        raise ValueError('ASSESSMENT_EXTENSION_AUTHORITY_OR_BASELINE_INVALID')
    prior, original = _load(prior_path), _load(baseline_path)
    if (prior.get('status') != 'blocked' or prior.get('error_type') != 'RequestBudgetExceeded' or
            prior.get('maximum_tokens') != LIMIT or prior.get('budget', {}).get('maximum_tokens') != LIMIT):
        raise ValueError('ASSESSMENT_EXTENSION_KNOWN_BUDGET_DENIAL_REQUIRED')
    if (prior['binding'] != original['binding'] or
            {k:v for k,v in binding.items() if k != 'code_sha256'} !=
            {k:v for k,v in prior['binding'].items() if k != 'code_sha256'} or
            authority.get('code_sha256') != binding['code_sha256'] or
            authority.get('original_owner_authority_sha256') != binding['authority_sha256']):
        raise ValueError('ASSESSMENT_EXTENSION_PIN_CHANGED')
    actor = prior.get('writer_actor', {})
    checkpoint = case / 'assessment-completion-checkpoints.db'
    if (actor.get('role') != 'writer' or not actor.get('task_id') or
            actor.get('id') != 'content:writer:' + actor['task_id']):
        raise ValueError('ASSESSMENT_EXTENSION_WRITER_PIN_INVALID')
    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise ValueError('ASSESSMENT_EXTENSION_EXISTING_CHECKPOINT_REQUIRED')
    require_prior_process_absent(prior, case)
    used, held, _ = budget_scope_cost(original['baseline'], now)
    old = {row[0] for row in original['baseline']['rows']}
    added = [row for row in now['rows'] if row[0] not in old]
    if held or any(row[4] in ('reserved', 'unknown') for row in added):
        raise ValueError('ASSESSMENT_EXTENSION_PENDING_ATTEMPT_REFUSED')
    if (prior['budget'].get('reserved_or_unknown_upper_bounds') != 0 or
            used != prior['budget'].get('recorded_tokens') or
            any(row[1] != binding['writer_model'] for row in added)):
        raise ValueError('ASSESSMENT_EXTENSION_PRIOR_USAGE_CHANGED')
    return authority, original, prior


def require_continuation_checkpoint(state, fresh_authority=None):
    tasks = state.tasks
    valid_error = ("RecoveryBlocked('RECOVERY_PRIOR_ATTEMPT_UNRESOLVED')" if fresh_authority else
        "RequestBudgetExceeded('ASSESSMENT_COMPLETION_TOKEN_LIMIT')")
    expected_next = ((), ('model',)) if fresh_authority else (('model',),)
    partial_ok = True
    if fresh_authority and len(tasks) == 1:
        result, pinned = getattr(tasks[0],'result',None), fresh_authority.get('native_failed_model_partial_result_sha256')
        partial_ok = (isinstance(result,dict) and set(result) == {'files'} and digest(result) == pinned
            if pinned else result is None)
        partial_ok = partial_ok and not getattr(tasks[0],'interrupts',())
    if (tuple(state.next) not in expected_next or not partial_ok or len(tasks) != 1 or tasks[0].name != 'model' or
            repr(tasks[0].error) != valid_error and tasks[0].error != valid_error or
            state.config.get('configurable', {}).get('thread_id') != 'bounded-assessment-completion' or
            not state.config['configurable'].get('checkpoint_id') or fresh_authority and
            state.config['configurable']['checkpoint_id'] != fresh_authority['checkpoint_id']):
        raise ValueError('ASSESSMENT_EXTENSION_CHECKPOINT_MUST_BE_KNOWN_FAILED_MODEL')
    return {'checkpoint_id': state.config['configurable']['checkpoint_id'], 'next': list(state.next),
        'tasks': [{'id': tasks[0].id, 'name': tasks[0].name, 'error': valid_error}]}




def require_local_preflight_repair(case, evidence, authority, now):
    """One known pre-send repair; keep the consumed fresh receipt immutable."""
    folder = evidence/'extension-1/fresh-continuation'
    local, old, frozen, before = [_load(folder/name) for name in (
        'writer-launch.json','owner-approval.json','execution-source-receipt.json','pre-continuation-preservation.json')]
    changed = {'at_utc','code_sha256','commit','execution_source'}
    prior = _load(evidence/'extension-1/writer-launch.json')
    if (any(authority.get(k) != value for k,value in old.items() if k not in changed) or
            authority.get('known_local_failure_launch_sha256') != _sha(folder/'writer-launch.json') or
            local.get('status') != 'blocked' or local.get('error_type') != 'ValueError' or
            local.get('maximum_tokens') != 2 * LIMIT or 'continuation_checkpoint' in local or
            local.get('assessment_refs') != {} or local.get('writer_actor') != prior['writer_actor'] or
            local.get('budget') != prior['budget'] or
            local['binding'].get('continuation_authority_sha256') != _sha(folder/'owner-approval.json') or
            local['binding'].get('code_sha256') != old.get('code_sha256') or
            frozen.get('owner_authority_sha256') != _sha(folder/'owner-approval.json') or
            frozen.get('execution_source') != old.get('execution_source') or frozen.get('commit') != old.get('commit') or
            _sha(Path(old['execution_source'])/'src/report_agent/assessment_completion.py') != old['code_sha256']):
        raise ValueError('ASSESSMENT_LOCAL_REPAIR_KNOWN_PREFLIGHT_FAILURE_REQUIRED')
    if (now != before['finance'] or authority.get('known_local_finance_sha256') != digest(before['finance']) or
            not authority.get('native_failed_model_partial_result_sha256')):
        raise ValueError('ASSESSMENT_LOCAL_REPAIR_FINANCE_OR_PARTIAL_PIN_CHANGED')
    require_prior_process_absent(local,case)
    start = datetime.fromisoformat(local['at_utc']).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with closing(sqlite3.connect((case/'state.db').as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        kinds = [row[0] for row in db.execute('SELECT kind FROM events WHERE at>=?',(start,))]
    if any(kind != 'prompt_runtime_bound' for kind in kinds):
        raise ValueError('ASSESSMENT_LOCAL_REPAIR_DISPATCH_ABSENCE_NOT_PROVEN')

def require_fresh_continuation(case, evidence, authority_path, binding, now):
    base = evidence / 'extension-1' / 'fresh-continuation'
    repair = authority_path == base/'local-preflight-repair/owner-approval.json'
    if authority_path not in (base/'owner-approval.json',base/'local-preflight-repair/owner-approval.json'):
        raise ValueError('ASSESSMENT_FRESH_AUTHORITY_PATH_INVALID')
    if (authority_path.parent / 'writer-launch.json').exists():
        raise FileExistsError('ASSESSMENT_FRESH_CONTINUATION_ALREADY_LAUNCHED')
    authority = _load(authority_path)
    if repair:
        require_local_preflight_repair(case,evidence,authority,now)
    prior_path, baseline_path = evidence / 'extension-1/writer-launch.json', evidence / 'completion-budget-baseline.json'
    prior, original = _load(prior_path), _load(baseline_path)
    if (not all(authority.get(k) for k in ('turn_id','message_id','checkpoint_id')) or
            authority.get('owner_answer') != 'Continue with the 2M hold preserved' or
            authority.get('maximum_tokens') != 2 * LIMIT or authority.get('held_attempt_id') != PRESERVED_ATTEMPT or
            authority.get('held_tokens') != 2_000_000 or authority.get('grant_limit_unchanged') != GRANT_LIMIT or
            authority.get('prior_launch_path') != str(prior_path) or authority.get('prior_launch_sha256') != _sha(prior_path) or
            authority.get('original_baseline_path') != str(baseline_path) or
            authority.get('original_baseline_sha256') != _sha(baseline_path) or
            authority.get('prior_extension_authority_sha256') != _sha(evidence/'extension-1/owner-approval.json') or
            authority.get('code_sha256') != binding['code_sha256']):
        raise ValueError('ASSESSMENT_FRESH_AUTHORITY_PIN_INVALID')
    base = {k:v for k,v in original['binding'].items() if k != 'code_sha256'}
    if (base != {k:v for k,v in binding.items() if k != 'code_sha256'} or
            any(prior['binding'].get(k) != v for k,v in base.items()) or
            prior['binding'].get('extension_authority_sha256') != authority['prior_extension_authority_sha256'] or
            prior['binding'].get('original_baseline_sha256') != authority['original_baseline_sha256'] or
            prior['binding'].get('prior_launch_sha256') != _sha(evidence/'writer-launch.json') or
            prior.get('status') != 'blocked' or prior.get('error_type') != 'RecoveryBlocked' or
            prior.get('maximum_tokens') != 2 * LIMIT or prior['budget'].get('maximum_tokens') != 2 * LIMIT or
            prior.get('writer_actor') != _load(evidence/'writer-launch.json').get('writer_actor')):
        raise ValueError('ASSESSMENT_FRESH_PRIOR_BINDING_INVALID')
    require_prior_process_absent(prior, case)
    if (not (case/'assessment-completion-checkpoints.db').is_file() or
            (case/'assessment-completion-checkpoints.db').stat().st_size == 0):
        raise ValueError('ASSESSMENT_FRESH_EXISTING_CHECKPOINT_REQUIRED')
    used, held, _ = budget_scope_cost(original['baseline'], now)
    old = {row[0] for row in original['baseline']['rows']}
    added = [row for row in now['rows'] if row[0] not in old]
    pinned = authority.get('held_row')
    if (not isinstance(pinned,list) or digest(pinned) != authority.get('held_row_sha256') or
            len(pinned) != 8 or pinned[:6] != [PRESERVED_ATTEMPT,binding['writer_model'],2_000_000,None,'reserved',None] or
            [row for row in added if row[4] in ('reserved','unknown')] != [pinned] or
            used != prior['budget'].get('recorded_tokens') or held != 2_000_000 or
            prior['budget'].get('reserved_or_unknown_upper_bounds') != held or
            any(row[1] != binding['writer_model'] for row in added)):
        raise ValueError('ASSESSMENT_FRESH_EXACT_HELD_ROW_REQUIRED')
    with closing(sqlite3.connect((case/'state.db').as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        row = db.execute('SELECT value FROM state WHERE key=?',(authority.get('recovery_state_key'),)).fetchone()
    record = json.loads(row[0]) if row else None
    if (not record or digest(record) != authority.get('recovery_record_sha256') or record.get('raw') is not None or
            record.get('state') != 'unknown' or record.get('active') is not False or record.get('role') != 'writer' or
            record.get('full_input_sha256') != authority.get('recovery_full_input_sha256') or
            record.get('invocation_owner',{}).get('actor') != prior['writer_actor'] or
            not authority.get('blocked_body_sha256')):
        raise ValueError('ASSESSMENT_FRESH_RECOVERY_PIN_INVALID')
    return authority, original, prior


def fresh_continuation_notice(authority):
    return (f"Fresh owner decision {authority['message_id']}: Continue with the 2M hold preserved. "
        f"The earlier internal-summary request {authority['held_attempt_id']} was sent but received no response or usage; "
        'its provider outcome remains unknown and its full 2M reservation remains held. The owner explicitly permits '
        'one fresh logical continuation of the SAME Writer task under the existing cumulative20M cap from the ORIGINAL '
        'baseline, including every settled token and this hold. This is not a replay of the unresolved summary or a '
        'business tool. Preserve all prior observations, files, summaries, source evidence and the55 unverified suggestions. '
        'Use a fresh operation_id for post-fix assessment submissions; failed receipts remain historical. '
        'Complete only the five canonical assessments under the unchanged approved plan and current approved method; '
        'do not fabricate unsupported judgments or sources, change no plan, and grant no engineering sign-off. Retain this owner instruction '
        'verbatim in the context summary so the same task can continue without losing its financial and outcome boundary.')


def fresh_request_guard(case, authority, actor):
    """Fence the old logical and actual wire input before financial reservation."""
    async def admit(request):
        from .model_recovery import _ACTIVE, _load_call, RecoveryBlocked
        active = _ACTIVE.get()
        if active is None or Path(active[0].root).resolve() != case or active[1] == authority['recovery_state_key']:
            raise RecoveryBlocked('RECOVERY_FRESH_OWNER_REQUIRED')
        record = _load_call(active[0],active[1])
        payload = json.loads(request.content)
        if (record.get('role') != 'writer' or record.get('invocation_owner',{}).get('actor') != actor or
                record.get('invocation_owner',{}).get('invocation',{}).get('delegate_operation_id') != 'delegate:' + FRESH_OPERATION or
                payload.get('model') != authority['held_row'][1]):
            raise RecoveryBlocked('RECOVERY_FRESH_WRITER_REQUIRED')
        if (record.get('full_input_sha256') == authority['recovery_full_input_sha256'] or
                digest(payload) == authority['recovery_full_input_sha256'] or
                hashlib.sha256(request.content).hexdigest() == authority['blocked_body_sha256']):
            raise RecoveryBlocked('RECOVERY_PREVIOUS_SUMMARY_FENCED')
        notice = fresh_continuation_notice(authority)
        def has_notice(message):
            content = message.get('content')
            return message.get('role') in {'user','system'} and (isinstance(content,str) and notice in content or
                isinstance(content,list) and any(isinstance(part,dict) and notice in str(part.get('text','')) for part in content))
        if not any(has_notice(message) for message in payload.get('messages',[])):
            raise RecoveryBlocked('RECOVERY_FRESH_AUTHORITY_MISSING')
    return admit

def approved_method_context(plan):
    pack = plan['payload']['method_pack']
    return {'method_id': pack['method_id'], 'version': pack['version'], 'sources': pack['sources'],
        'indicators': [{key: row[key] for key in ('id','label','grades','notes')} for row in pack['indicators']],
        'weight_tables': [{'id': table['id'], 'source': table['source'],
            'rows': [row for row in table['rows'] if row['indicator_count'] == len(pack['indicators'])]}
            for table in pack['weight_tables']],
        'method_conventions': plan['payload']['method_conventions']}

async def _run_completion_locked(case, evidence, env, grant_file, extension_authority=None, continuation_authority=None):
    case, evidence, env, grant_file = [Path(p).resolve() for p in (case, evidence, env, grant_file)]
    extension_authority = Path(extension_authority).resolve() if extension_authority else None
    continuation_authority = Path(continuation_authority).resolve() if continuation_authority else None
    if extension_authority and continuation_authority:
        raise ValueError('ASSESSMENT_COMPLETION_ONE_AUTHORITY_ROUTE_REQUIRED')
    output = (continuation_authority.parent if continuation_authority else
        evidence/'extension-1' if extension_authority else evidence)
    launch_path = output / 'writer-launch.json'
    if launch_path.exists():
        raise FileExistsError('ASSESSMENT_COMPLETION_ALREADY_LAUNCHED_INSPECT_ORIGINAL_OUTCOME')
    authority, working, grant, ledger, now, blobs, model_name, endpoint_pin = _preflight(case, evidence, env, grant_file)
    from .store import Store
    from .workspace import Workspace
    from .content_store import ContentStore
    from .commission_plan import _confirmed
    store = Store(case)
    workspace, contents = Workspace(store), ContentStore(store)
    approved = _load(evidence / 'approved-plan.json')
    approved_decision = _load(evidence / 'approved-decision.json')
    with store.connect() as db:
        plan, decision = _confirmed(contents, db)
    if plan['ref'] != approved['ref'] or plan['payload_digest'] != approved['payload_digest']:
        raise ValueError('ASSESSMENT_COMPLETION_PLAN_CHANGED')
    require_decision_pin(decision, approved_decision)
    from .commission_plan import outside_boundary
    reduced = {row['object_id'] for row in decision['payload']['reductions']}
    ids = [obj['object_id'] for obj in plan['payload']['objects'] if not outside_boundary(plan['payload'], obj) and obj['object_id'] not in reduced]
    suggestions = _load(evidence / 'assessment-suggestions.json')
    if len(ids) != 5 or len(suggestions['rows']) != 55 or {row['object_id'] for row in suggestions['rows']} != set(ids):
        raise ValueError('ASSESSMENT_COMPLETION_FIVE_OBJECTS_REQUIRED')
    binding = {'authority_sha256': _sha(evidence/'owner-approval.json'), 'case': str(case), 'plan_ref': plan['ref'],
        'decision_ref': decision['ref'], 'approved_decision_sha256': _sha(evidence/'approved-decision.json'),
        'suggestions_sha256': _sha(evidence/'assessment-suggestions.json'),
        'grant_sha256': _sha(grant_file), 'source_db_sha256': working['source_db_sha256'],
        'environment_sha256': _sha(env),
        'g5_prepared_sha256': _sha(Path(_load(evidence/'financial-authority-paths.json')['g5_prepared'])),
        'writer_model': model_name, 'writer_endpoint_sha256': endpoint_pin, 'code_sha256': _sha(Path(__file__))}
    baseline_path = evidence / 'completion-budget-baseline.json'
    prior = None
    maximum_tokens = LIMIT
    continuation = None
    preserved_hold = None
    if continuation_authority:
        continuation, original, prior = require_fresh_continuation(case,evidence,continuation_authority,binding,now)
        baseline, maximum_tokens = original['baseline'], continuation['maximum_tokens']
        preserved_hold = continuation['held_row']
        binding.update(continuation_authority_sha256=_sha(continuation_authority),
            prior_launch_sha256=continuation['prior_launch_sha256'],
            original_baseline_sha256=continuation['original_baseline_sha256'],
            preserved_hold_sha256=continuation['held_row_sha256'])
    elif extension_authority:
        extension, original, prior = require_extension(case, evidence, extension_authority, binding, now)
        baseline = original['baseline']
        maximum_tokens = extension['maximum_tokens']
        binding.update(extension_authority_sha256=_sha(extension_authority),
            prior_launch_sha256=extension['prior_launch_sha256'],
            original_baseline_sha256=extension['original_baseline_sha256'])
    else:
        if baseline_path.exists():
            saved = _load(baseline_path)
            if saved['binding'] != binding or saved['baseline'] != now:
                raise ValueError('ASSESSMENT_COMPLETION_BASELINE_NOT_FRESH')
        else:
            claim_launch(baseline_path, {'binding': binding, 'baseline': now})
        baseline = now
    guard = CompletionBudget(lambda: read_finance(ledger), baseline, grant['baseline'], json.loads(now['auth'][1]),
        writer_model=model_name, maximum_tokens=maximum_tokens, preserved_hold=preserved_hold)
    guard.check()
    launch = {'at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'binding': binding,
              'maximum_tokens': maximum_tokens, 'source_blobs': blobs, 'assessment_refs': {},
              'pid': os.getpid(), 'uid': os.getuid(),
              'process_start_ticks': Path('/proc/self/stat').read_text().rpartition(')')[2].split()[19]}
    claim_launch(launch_path, launch)
    metrics_path = case / 'runtime-metrics.jsonl'
    metric_offset = metrics_path.stat().st_size if metrics_path.exists() else 0
    actor = None
    try:
        if not prior:
            store.set('manifest', {**store.manifest, 'assembly_contract': 'system-assembler-v1'})
        from .content_tasks import delegated_task
        goal = ('The owner has explicitly approved this bounded assessment-completion extension, hard cap10M tokens. '
            'This does not restart G5, change its approved plan or grant engineering sign-off. '
            'Complete ONLY the five canonical chapter4 assessments under the approved plan. The supplied55 rows are '
            'UNVERIFIED suggestions. Confirm or correct every grade,value,rank and explanation using the approved method '
            'and actual source evidence. Supply rank_reason, basis_kind, rationale, exact source refs and source pages '
            'for every value; assumptions need defensible plausible_grades and a question. Table-wide citations are not '
            'automatic per-indicator evidence. Preserve design-over-survey priority, the four owner exclusions, HP06 '
            'included with owner-provided14m, approved11indicators and A.3-1 n=11. A historical EXCLUDED suffix does not '
            'exclude HP06. Do not author prose/tables, alter plans/decisions/scope or export. Use calculate_assessment; '
            'the system computes arithmetic,tables,levels,sensitivity and assumption comments. Finish when allfive save. '
            'Engineering acceptance remains human. Report missing evidence honestly; never invent source pages.')
        call = {'name': 'task', 'id': 'owner-approved-assessment-completion', 'args': {
            'subagent_type': 'writer', 'section_ids': ['4'], 'description': goal}}
        if prior:
            goal = ('The owner explicitly authorizes an additional 10M tokens: cumulative maximum 20M from the ORIGINAL '
                f"completion baseline, including the prior {prior['budget']['recorded_tokens']:,} settled tokens. Continue the SAME Writer task and "
                'retained native checkpoint; this is a known pre-send budget denial, not an unknown HTTP outcome or '
                'a replay of business tools. Original scope and approved plan remain unchanged: save only the five '
                'canonical assessments; confirm/correct the existing 55 unverified suggestions from retained evidence; '
                'invent no grades, ranks or pages. Prior refusal diagnosed a source alias: two verified guideline refs '
                'have the same source_id, file digest and exact text; the fixed shared guard accepts that equivalence. '
                'Use a fresh operation_id for post-fix assessment submissions; failed receipts remain historical. '
                'Exact source quotes, source-use permissions and all assessment checks still apply. Do not repeat '
                'whole-document research; use the retained evidence and the approved method contract below. '
                'Finish after all five save; engineering acceptance stays human.\nApproved method contract:\n' +
                json.dumps(approved_method_context(plan), ensure_ascii=False))
            call = {'name': 'task', 'id': 'owner-approved-assessment-completion-extension-1', 'args': {
                'subagent_type': 'writer', 'resume_content_task_id': prior['writer_actor']['task_id'], 'description': goal}}
        notice = fresh_continuation_notice(continuation) if continuation else None
        if continuation:
            call = {'name':'task','id':FRESH_OPERATION,'args':{'subagent_type':'writer',
                'resume_content_task_id':prior['writer_actor']['task_id'],'description':notice}}
        from .token_budget import TokenBudget, token_budget
        from .request_budget import request_reservation_observer
        budget = TokenBudget(ledger, now['auth'][0], guard.bounds)
        from .deep_models import configured_model, model_client_ownership
        from langchain_core.messages import HumanMessage
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from .deep_runtime import business_tools
        with delegated_task(workspace, 'coordinator', call) as (native_call, actor):
            if prior and actor.__dict__ != prior['writer_actor']:
                raise ValueError('ASSESSMENT_EXTENSION_WRITER_ACTOR_CHANGED')
            def saved():
                return saved_assessments(contents, plan['ref'], ids, actor.id)
            async with AsyncExitStack() as resources:
                clients = set()
                def own(client, asynchronous):
                    if id(client) not in clients:
                        clients.add(id(client))
                        resources.push_async_callback(client.aclose) if asynchronous else resources.callback(client.close)
                with model_client_ownership(own):
                    model = configured_model(store, 'writer')
                    require_writer_model(model, model_name)
                    if continuation:
                        model.http_async_client.event_hooks['request'].insert(0,
                            fresh_request_guard(case,continuation,actor.__dict__))
                tools = selected_tools(business_tools(workspace, 'writer', None, None))
                launch.update(writer_actor=actor.__dict__, tools=[getattr(t,'name',None) or t.__name__ for t in tools])
                _save(launch_path, launch)
                async with AsyncSqliteSaver.from_conn_string(str(case/'assessment-completion-checkpoints.db')) as saver:
                    agent = build_writer_agent(workspace, model, tools, lambda: len(saved()) == 5, saver, continuation_notice=notice)
                    config = {'configurable': {'thread_id': 'bounded-assessment-completion'}, 'recursion_limit': 10000}
                    if prior:
                        launch['continuation_checkpoint'] = require_continuation_checkpoint(await agent.aget_state(config),fresh_authority=continuation)
                        _save(launch_path, launch)
                    prompt = native_call['args']['description']
                    if not prior:
                        prompt += '\nUnverified system prefill:\n' + json.dumps(suggestions, ensure_ascii=False)
                    with token_budget(budget), request_reservation_observer(guard.check, observation=guard.observation):
                        await agent.ainvoke({'messages': [HumanMessage(content=prompt)]}, config)
                launch['assessment_refs'] = saved()
        launch['status'] = 'completed' if len(launch['assessment_refs']) == 5 else 'incomplete'
        launch['missing_objects'] = sorted(set(ids)-launch['assessment_refs'].keys())
    except BaseException as error:
        launch.update(status='blocked', error_type=type(error).__name__)
        raise
    finally:
        if actor is not None:
            try:
                launch['assessment_refs'] = saved_assessments(contents, plan['ref'], ids, actor.id)
                launch['missing_objects'] = sorted(set(ids) - launch['assessment_refs'].keys())
            except Exception as error:
                launch['assessment_receipt_error_type'] = type(error).__name__
        launch['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            launch['budget'] = guard.observation()
        except Exception as error:
            launch['budget'] = {'status': 'unavailable', 'error_type': type(error).__name__}
        _save(launch_path, launch)
        if metrics_path.exists():
            with metrics_path.open('rb') as stream:
                stream.seek(metric_offset)
                (output/'writer-metrics.jsonl').write_bytes(stream.read())
    return launch


def build_writer_agent(workspace, model, tools, complete, checkpointer, continuation_notice=None):
    from deepagents import create_deep_agent, register_harness_profile, HarnessProfile, GeneralPurposeSubagentProfile
    from deepagents.backends import StateBackend
    from .deep_runtime import BusinessBoundary
    from .hierarchical_tools import role_prompt
    from .prompt_provenance import AgentPromptBoundary
    from .task_context import enabled as context_enabled, TaskContext, bind_projection
    from .prompt_sources import record_runtime_version, review_interface_profile, report_expression_profile, report_prompt_profile
    from .handoff_release import release
    store = workspace.store
    bind_projection(workspace, manifest=store.manifest)
    options = {'interface_profile': review_interface_profile(store), 'expression_profile': report_expression_profile(store),
               'prompt_profile': report_prompt_profile(store)}
    register_harness_profile('openai', HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))
    middleware = [AssessmentCompletionStop(complete),
        *([TaskContext(workspace, 'writer')] if context_enabled(workspace) else []),
        BusinessBoundary(workspace, 'writer'), AgentPromptBoundary(workspace, 'writer', **options)]
    backend = StateBackend()
    if continuation_notice:
        from deepagents.graph import create_summarization_middleware
        from inspect import signature
        default_prompt = signature(create_summarization_middleware).parameters['summary_prompt'].default
        # Replace only the native summary prompt; keep its installed settings and backend.
        escaped = continuation_notice.replace('{','{{').replace('}','}}')
        middleware.append(create_summarization_middleware(model,backend,
            summary_prompt=default_prompt + '\n\n' + escaped))
    authored = role_prompt('writer', **options)
    if continuation_notice:
        from langchain_core.messages import SystemMessage
        authored = SystemMessage(content=[{'type':'text','text':authored},{'type':'text','text':continuation_notice}],
            additional_kwargs={'report_system_contributions':[{'source':'trusted_operator/fresh_continuation',
                'text':continuation_notice}]})
    agent = create_deep_agent(model=model, tools=tools, subagents=[], backend=backend,
        system_prompt=authored, middleware=middleware,
        checkpointer=checkpointer, name='assessment_completion_writer')
    metadata = {'report_runtime_version_ref': record_runtime_version(store)}
    if options['interface_profile'] == 'review-interfaces-v4':
        metadata['report_handoff_release'] = release(store.manifest)
    return agent.with_config(metadata=metadata)


async def run_completion(case, evidence, env, grant_file, extension_authority=None, continuation_authority=None):
    import fcntl
    case, evidence = Path(case).resolve(), Path(evidence).resolve()
    working = _load(evidence / 'working-copy.json')
    if case != Path(working['working_case']).resolve() or case == Path(working['source']).resolve():
        raise ValueError('ASSESSMENT_COMPLETION_WORKING_COPY_REQUIRED')
    with (case / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return await _run_completion_locked(case, evidence, env, grant_file, extension_authority, continuation_authority)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case', 'evidence', 'env', 'grant-baseline'):
        parser.add_argument('--'+name, required=True, type=Path)
    routes = parser.add_mutually_exclusive_group()
    routes.add_argument('--extension-authority', type=Path)
    routes.add_argument('--continuation-authority', type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(run_completion(args.case,args.evidence,args.env,args.grant_baseline,args.extension_authority,args.continuation_authority))
    except BaseException as error:
        print(json.dumps({'status':'blocked','error_type':type(error).__name__}))
        return 1
    print(json.dumps({k:result.get(k) for k in ('status','assessment_refs','missing_objects','budget')},ensure_ascii=False))
    return 0 if result['status']=='completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
