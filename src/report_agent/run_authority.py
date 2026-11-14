"""Pinned production launch admission; the Coordinator owns all report actions."""
from contextlib import contextmanager, closing
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import re
import subprocess

from dotenv import dotenv_values
from .token_budget import CampaignRunBudget, RequestBound, token_budget, request_token_bound
from .store import digest
from .request_budget import RequestBudgetExceeded

_REPO = Path(__file__).resolve().parents[2]
_active = ContextVar('report_run_authority', default=None)


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha(path):
    return _sha_bytes(Path(path).read_bytes())


def current_authority():
    return _active.get()


OFFLINE_GRAPH_STEP_LIMIT = 10000


def graph_config(scope, authority=None):
    authority = current_authority() if authority is None else authority
    if authority is None:
        return {'recursion_limit': OFFLINE_GRAPH_STEP_LIMIT}
    limits = authority.get('graph_limits')
    if (not isinstance(limits, dict) or set(limits) != {'root', 'assessment'}
            or any(type(value) is not int or value < 1 for value in limits.values())):
        raise ValueError('REPORT_GRAPH_LIMITS_REQUIRED')
    return {'recursion_limit': limits[scope]}


def _service_bound(proof, env_bytes, model, base_url):
    """Reviewed pinned limits, cross-checked against documented capacity metadata.

    Neither the proof nor the capacity preset certifies measured request fit.
    """
    import httpx
    from urllib.parse import urlsplit
    from .input_capacity import profile_for_service
    capacity=profile_for_service(model,base_url)
    sources=proof.get('sources')
    suffix=proof.get('endpoint_host_suffix')
    output=proof.get('output_limit')
    error='REPORT_VISION_PROOF_INVALID' if 'image_max_edge' in proof else 'REPORT_REQUEST_PROOF_INVALID'
    if (any(type(n) is not int or n<1 for n in (capacity.context_tokens,capacity.maximum_output_tokens))
            or proof.get('model')!=model or proof.get('input_limit')!=capacity.context_tokens
            or type(output) is not int or not 0<output<=capacity.maximum_output_tokens
            or not isinstance(proof.get('basis'),str) or not proof['basis'].strip()
            or urlsplit(base_url).scheme!='https'
            or not isinstance(suffix,str) or not suffix.startswith('.')
            or not (urlsplit(base_url).hostname or '').endswith(suffix)
            or proof.get('env_sha256')!=_sha_bytes(env_bytes)
            or proof.get('base_url_sha256')!=_sha_bytes(base_url.rstrip('/').encode())
            or proof.get('request_url_sha256')!=_sha_bytes(str(httpx.URL(base_url.rstrip('/')+'/chat/completions')).encode())
            or not isinstance(sources,list) or not sources
            or any(not isinstance(url,str) or urlsplit(url).scheme!='https' or not urlsplit(url).hostname for url in sources)
            or ('image_max_edge' in proof)!=('wire_output_limit' in proof)):
        raise ValueError(error)
    proof_hash=_sha_bytes(json.dumps(proof,sort_keys=True,separators=(',',':')).encode())
    return RequestBound(model,proof['request_url_sha256'],proof['input_limit'],output,proof_hash,
                        image_max_edge=proof.get('image_max_edge'),wire_output_limit=proof.get('wire_output_limit'))


def _verify_checkpoint_reply(workspace, issue_id, issue, path, pin):
    from . import commission_assertions
    from .commission_plan import verified_confirmer
    from .content_store import ContentStore
    answer=issue.get('decision')
    answer=json.loads(answer) if isinstance(answer,str) else answer
    if not isinstance(answer,dict):
        raise ValueError('REPORT_NATIVE_CONFIRMER_DECISION_REQUIRED')
    verified_confirmer(workspace.store.root,answer.get('confirmer'),path,pin)
    cs=ContentStore(workspace.store)
    with workspace.store.connect() as db:
        checkpoint=commission_assertions.checkpoint(db,'plan',issue_id)
        ref=commission_assertions.checkpoint_answer(db,'plan',issue_id)
    if not checkpoint or not ref:
        raise ValueError('REPORT_NATIVE_CONFIRMER_DECISION_REQUIRED')
    record=cs.read(ref);decision=record['payload']
    if (record['owner_id']!='operator' or record['created_by']!='operator' or decision['plan_ref']!=checkpoint['plan_ref']
            or any(answer.get(k)!=decision.get(k) for k in ('plan_ref','approved','confirmer'))):
        raise ValueError('REPORT_NATIVE_CONFIRMER_DECISION_MISMATCH')
    verified_confirmer(workspace.store.root,decision.get('confirmer'),path,pin)
    return ref


def _continuation_authority(workspace, authority, invocation):
    """A new entry links immutable prior authority; it never refreshes the run budget."""
    entries = authority.get('continuations', {})
    if not isinstance(entries, dict):
        raise ValueError('REPORT_CONTINUATION_AUTHORITY_REQUIRED')
    continuation = entries.get(invocation)
    if continuation is None:
        return None
    names = authority['invocations']
    index = names.index(invocation)
    if (not isinstance(continuation, dict) or index == 0
            or continuation.get('prior_invocation') != names[index - 1]
            or not isinstance(continuation.get('prior_authority'), dict)
            or not isinstance(continuation.get('checkpoint_id'), str)
            or not continuation['checkpoint_id'].strip()):
        raise ValueError('REPORT_CONTINUATION_AUTHORITY_REQUIRED')
    selected = continuation['prior_authority']
    prior_pin = selected.get('sha256')
    prior_path = selected.get('path')
    if (not isinstance(prior_pin, str) or not re.fullmatch('[0-9a-f]{64}', prior_pin)
            or not isinstance(prior_path, str) or not Path(prior_path).is_absolute()):
        raise ValueError('REPORT_CONTINUATION_PIN_MISMATCH')
    prior_raw = Path(prior_path).read_bytes()
    if _sha_bytes(prior_raw) != prior_pin:
        raise ValueError('REPORT_CONTINUATION_PIN_MISMATCH')
    prior_authority = json.loads(prior_raw)
    if not isinstance(prior_authority, dict) or not isinstance(prior_authority.get('budget'), dict):
        raise ValueError('REPORT_CONTINUATION_SCOPE_MISMATCH')
    # Compare the authority itself so new schema fields are invariant by default.
    revised = {'owner_authority_ref', 'candidate_commit', 'candidate_tag',
               'invocations', 'continuations', 'budget', 'graph_limits'}
    old_budget = prior_authority.get('budget', {})
    new_budget = authority.get('budget', {})
    if ({k:v for k,v in authority.items() if k not in revised}
            != {k:v for k,v in prior_authority.items() if k not in revised}
            or {k:v for k,v in entries.items() if k != invocation} != prior_authority.get('continuations', {})
            or prior_authority.get('invocations') != names[:index]
            or {k:v for k,v in old_budget.items() if k != 'preserved_holds'}
               != {k:v for k,v in new_budget.items() if k != 'preserved_holds'}
            or any(row not in new_budget.get('preserved_holds', [])
                   for row in old_budget.get('preserved_holds', []))):
        raise ValueError('REPORT_CONTINUATION_SCOPE_MISMATCH')
    root = Path(authority['record_dir']) / continuation['prior_invocation']
    prior = json.loads((root / 'result.json').read_bytes())
    launched = json.loads((root / 'launch.json').read_bytes())
    failed_prior = prior.get('status') == 'failed'
    if (prior.get('status') not in {'unknown_outcome_held', 'failed'}
            or (failed_prior and (not isinstance(prior.get('error'), dict)
                or not isinstance(prior['error'].get('type'), str) or not prior['error']['type'].strip()))
            or any(record.get('authority_sha256') != prior_pin
                   or record.get('run_id') != authority['run_id']
                   or record.get('invocation') != continuation['prior_invocation']
                   for record in (prior, launched))):
        raise ValueError('REPORT_CONTINUATION_PRIOR_REQUIRED')
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    with closing(sqlite3.connect(Path(new_budget['ledger']).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        bindings = tables & {'fake_flow_runs', 'report_runs'}
        if len(bindings) != 1:
            raise ValueError('REPORT_CAMPAIGN_SCHEMA_UNRECOGNIZED')
        run_table = bindings.pop()
        attempt_table = 'fake_run_attempts' if run_table == 'fake_flow_runs' else 'report_run_attempts'
        binding = db.execute(f'SELECT maximum,authority FROM {run_table} WHERE run_id=?',
                             (authority['run_id'],)).fetchone()
        if (binding is None or binding[0] != new_budget['per_run_tokens']
                or not re.fullmatch('[0-9a-f]{64}', binding[1] or '')):
            raise RequestBudgetExceeded('REPORT_RUN_AUTHORITY_CHANGED')
        started = datetime.fromisoformat(launched['started_utc'])
        finished = datetime.fromisoformat(prior['finished_utc'])
        if (started.tzinfo is None or finished.tzinfo is None or started > finished
                or prior.get('started_utc') != launched['started_utc']):
            raise ValueError('REPORT_CONTINUATION_PRIOR_REQUIRED')
        old_ids = {row[0] for row in old_budget['preserved_holds']}
        created = [list(row) for row in db.execute(
            f"SELECT a.* FROM attempts a JOIN {attempt_table} r ON r.attempt_id=a.id "
            "WHERE r.run_id=? AND a.state IN ('reserved','unknown')", (authority['run_id'],))
            if row[0] not in old_ids and started <= datetime.fromisoformat(row[7]) <= finished]
        if failed_prior and created:
            raise ValueError('REPORT_CONTINUATION_PRIOR_REQUIRED')
        if sorted(new_budget['preserved_holds']) != sorted(old_budget['preserved_holds'] + created):
            raise RequestBudgetExceeded('REPORT_UNRESOLVED_ATTEMPT')
    checkpoint_path = workspace.store.root / 'checkpoints.db'
    if not checkpoint_path.is_file():
        raise ValueError('REPORT_CONTINUATION_CHECKPOINT_MISMATCH')
    with closing(sqlite3.connect(checkpoint_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        saver = SqliteSaver(db)
        saver.is_setup = True  # Existing checkpoint inspection must not initialize storage.
        head = saver.get_tuple({'configurable': {'thread_id': 'report', 'checkpoint_ns': ''}})
    if head is None or head.config['configurable']['checkpoint_id'] != continuation['checkpoint_id']:
        raise ValueError('REPORT_CONTINUATION_CHECKPOINT_MISMATCH')
    return binding[1]


def preflight(workspace, path, pin, env_file, invocation):
    """Read-only admission; no model construction, paid call or financial write."""
    if not path or not isinstance(pin,str) or not re.fullmatch('[0-9a-f]{64}',pin):
        raise ValueError('REPORT_AUTHORITY_PIN_REQUIRED')
    path, env_file = Path(path).resolve(), Path(env_file).resolve() if env_file else None
    raw=path.read_bytes()
    if _sha_bytes(raw) != pin:
        raise ValueError('REPORT_AUTHORITY_PIN_MISMATCH')
    authority = json.loads(raw)
    env_raw=env_file.read_bytes() if env_file and env_file.is_file() else b''
    if (not isinstance(authority,dict) or authority.get('case_path') != str(workspace.store.root.resolve())
            or not isinstance(authority.get('owner_authority_ref'),str) or not authority['owner_authority_ref'].strip()
            or not isinstance(authority.get('confirmers'),dict) or not authority['confirmers']
            or not isinstance(authority.get('issue_routes'),dict)
            or not env_file or not env_file.is_file() or env_file.is_relative_to(_REPO)
            or env_file.is_relative_to(workspace.store.root.resolve())
            or path.is_relative_to(workspace.store.root.resolve())
            or authority.get('case_manifest_digest') != digest(workspace.store.manifest)
            or authority.get('env_sha256') != _sha_bytes(env_raw)):
        raise ValueError('REPORT_AUTHORITY_SCOPE_MISMATCH')
    graph_config('root', authority)
    from .commission_plan import verified_confirmer
    for identity,person in authority['confirmers'].items():
        verified_confirmer(workspace.store.root,{**person,'id':identity,'authority_sha256':pin},path,pin)
    roles, services = authority.get('roles'), authority.get('services')
    required={'coordinator','writer','reviewer','text_tool','vision','layout'}
    if (not isinstance(roles,dict) or not required <= roles.keys()
            or set(roles)-required-{'rubric_grader','grader_diagnostic'}
            or not isinstance(services,dict) or set(services)!=set(roles.values())):
        raise ValueError('REPORT_ROLE_AUTHORITY_REQUIRED')
    commit = subprocess.check_output(['git','-C',str(_REPO),'rev-parse','HEAD'],text=True).strip()
    tag = authority.get('candidate_tag')
    if (not isinstance(tag,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*',tag)
            or commit != authority.get('candidate_commit')
            or subprocess.check_output(['git','-C',str(_REPO),'rev-parse','--verify','refs/tags/'+tag+'^{commit}'],text=True).strip()!=commit
            or subprocess.run(['git','-C',str(_REPO),'diff','--quiet','HEAD'],check=False).returncode):
        raise ValueError('REPORT_CANDIDATE_PIN_MISMATCH')
    inputs=authority.get('inputs')
    if not isinstance(inputs,list) or not inputs or any(_sha(p['path'])!=p['sha256'] for p in inputs):
        raise ValueError('REPORT_INPUT_PIN_MISMATCH')
    criteria_spec=authority.get('criteria')
    if not isinstance(criteria_spec,dict):
        raise ValueError('REPORT_CRITERIA_PIN_MISMATCH')
    criteria_raw=Path(criteria_spec['path']).read_bytes()
    if _sha_bytes(criteria_raw)!=criteria_spec.get('sha256'):
        raise ValueError('REPORT_CRITERIA_PIN_MISMATCH')
    criteria=json.loads(criteria_raw).get('criteria')
    if not isinstance(criteria,dict):
        raise ValueError('REPORT_CRITERIA_REQUIRED')
    config=dotenv_values(stream=StringIO(env_raw.decode('utf-8'))); resolved={}; policies=[]
    for model, service in services.items():
        prefix=service.get('config_prefix')
        if not isinstance(prefix,str) or not re.fullmatch('[A-Z][A-Z0-9_]*_',prefix):
            raise ValueError('REPORT_SERVICE_CONFIGURATION_REQUIRED')
        values=tuple(config.get(prefix+k) for k in ('NAME','BASE_URL','API_KEY'))
        if values[0]!=model or not all(values) or not values[1].startswith('https://'):
            raise ValueError('REPORT_SERVICE_CONFIGURATION_MISMATCH')
        proof=service.get('request_bound_proof')
        if not isinstance(proof,dict):
            raise ValueError('REPORT_SERVICE_PROOF_REQUIRED')
        policies.append(_service_bound(proof,env_raw,*values[:2]))
        resolved[model]=values
    bounds={p.model:p for p in policies}
    if bounds[roles['vision']].image_max_edge is None or any(bounds[model].image_max_edge is not None for role,model in roles.items() if role!='vision'):
        raise ValueError('REPORT_ROLE_SERVICE_CAPABILITY_MISMATCH')
    transport=authority.get('transport')
    if (not isinstance(transport,dict) or type(transport.get('sdk_retries')) is not int or transport.get('sdk_retries')!=0
            or type(transport.get('connect_retries')) is not int or not 0<=transport['connect_retries']<=2
            or transport.get('vision_thinking') not in {'enabled','disabled'}):
        raise ValueError('REPORT_TRANSPORT_POLICY_REQUIRED')
    names=authority.get('invocations')
    if (not isinstance(names,list) or not names or len(set(names))!=len(names)
            or any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',n) for n in names)
            or invocation not in names):
        raise ValueError('REPORT_INVOCATION_NOT_AUTHORIZED')
    root=Path(authority['record_dir'])
    if not root.is_absolute() or root.resolve()!=root or root.is_relative_to(_REPO) or root.is_relative_to(workspace.store.root.resolve()) or path.is_relative_to(root):
        raise ValueError('REPORT_SEPARATE_RECORD_DIRECTORY_REQUIRED')
    if (root/invocation/'launch.json').exists():
        raise ValueError('REPORT_ALREADY_LAUNCHED_INSPECT_ORIGINAL_OUTCOME')
    options=authority.get('budget')
    if not isinstance(options,dict):
        raise ValueError('REPORT_CAMPAIGN_AUTHORITY_REQUIRED')
    binding_pin = _continuation_authority(workspace, authority, invocation)
    budget=CampaignRunBudget(options['ledger'],authority['run_id'],
        maximum_tokens=options['per_run_tokens'],aggregate_tokens=options['aggregate_tokens'],
        model_bounds={p.model:p.total for p in policies},authority_sha256=binding_pin or pin,
        preserved_holds=options['preserved_holds'],guard_sha256=options['guard_sha256'])
    index=names.index(invocation)
    if index==0:
        if any(budget.run_snapshot()[k] for k in ('settled','held')):
            raise ValueError('REPORT_FRESH_RUN_REQUIRED')
    elif binding_pin is None:
        prior=json.loads((root/names[index-1]/'result.json').read_bytes())
        if prior.get('status')!='needs_human' or prior.get('authority_sha256')!=pin or prior.get('error'):
            raise ValueError('REPORT_PRIOR_CHECKPOINT_REQUIRED')
        from .issue_state import get_report_issues
        issues={i['id']:i for i in get_report_issues(workspace.store,[])}
        pending=workspace.store.get('native_interrupts') or []
        if (not pending or pending!=prior.get('native_interrupts')
                or any(issues.get(i['value'].get('issue_id'),{}).get('decision_origin')!='operator' for i in pending)):
            raise ValueError('REPORT_NATIVE_OWNER_REPLY_REQUIRED')
        for item in pending:
            issue_id=item['value'].get('issue_id')
            _verify_checkpoint_reply(workspace,issue_id,issues[issue_id],path,pin)
    run=budget.run_snapshot()
    if run['settled']+run['held']+max(p.total for p in policies)>run['maximum_tokens']:
        raise ValueError('REPORT_RUN_HEADROOM_REQUIRED')
    if budget.snapshot()['remaining_for_new_reservations']<max(p.total for p in policies):
        raise ValueError('REPORT_CAMPAIGN_HEADROOM_REQUIRED')
    return authority,resolved,tuple(policies),budget,criteria


@contextmanager
def _environment(authority, services):
    updates={}
    for role,model in authority['roles'].items():
        for key,value in zip(('MODEL','BASE_URL','API_KEY'),services[model]):
            updates['REPORT_'+role.upper()+'_'+key]=value
    for key,value in zip(('MODEL','BASE_URL','API_KEY'),services[authority['roles']['coordinator']]):
        updates['REPORT_'+key]=value
    updates.update(REPORT_SDK_RETRIES=str(authority['transport']['sdk_retries']),
        REPORT_CONNECT_RETRIES=str(authority['transport']['connect_retries']),
        REPORT_VISION_THINKING=authority['transport']['vision_thinking'],
        LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
    previous={key:os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


async def run_authorized_report(workspace, path, pin, env_file, invocation, *, dry_run=False, decision_only=False):
    import fcntl
    from .deep_runtime import run_report
    from .model_recovery import load_recovery_policy
    from .tool_selection import tool_scope
    from .tool_trace import ToolTrace, capture_tools
    from .hierarchical_tools import actor_for
    data=preflight(workspace,path,pin,env_file,invocation)
    authority,services,policies,budget,criteria=data
    if load_recovery_policy(workspace.store):
        raise ValueError('REPORT_AUTOMATIC_RECOVERY_NOT_AUTHORIZED')
    if dry_run:
        return {'status':'preflight_passed','authority_sha256':pin,'roles':authority['roles'],
                'budget':budget.run_snapshot(),'paid_calls':0}
    root=Path(authority['record_dir']);root.mkdir(parents=True,exist_ok=True)
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        authority,services,policies,budget,criteria=preflight(workspace,path,pin,env_file,invocation)
        stage=root/invocation;stage.mkdir(exist_ok=True)
        started=datetime.now(timezone.utc).isoformat()
        before=budget.run_snapshot()
        launch=dict(authority_sha256=pin,run_id=authority['run_id'],invocation=invocation,
            candidate_commit=authority['candidate_commit'],candidate_tag=authority['candidate_tag'],
            started_utc=started,budget_before=before,automatic_retry=False)
        if invocation in authority.get('continuations', {}):
            launch['continuation'] = authority['continuations'][invocation]
        with (stage/'launch.json').open('x') as out:json.dump(launch,out,indent=2)
        active=_active.set({**authority,'criteria':criteria})
        result={**launch,'status':'interrupted'}
        try:
            if authority['issue_routes']:
                from .plan_authority import decision_ref
                if decision_ref(workspace.store) is not None:
                    from .content_store import Actor, ContentStore
                    from .system_assembler import record_issue_routes
                    record_issue_routes(ContentStore(workspace.store),Actor('operator','operator','operator'),
                        'run-routes:'+pin,authority['issue_routes'],note='Owner-pinned production run authority.')
            with (_environment(authority,services),token_budget(budget),request_token_bound(policies),
                  tool_scope(set(authority['roles'].values()),authority['roles']),
                  capture_tools(ToolTrace(workspace,invocation,stage/'tool-trace.jsonl',actor_for('coordinator')))):
                continuation = authority.get('continuations', {}).get(invocation)
                state=await run_report(workspace,decision_only=decision_only,
                    **({'continue_from_checkpoint': continuation['checkpoint_id']} if continuation else {}))
            if budget.run_snapshot()['held'] > before['held']:
                result['status']='unknown_outcome_held'
                raise RequestBudgetExceeded('REPORT_UNKNOWN_OUTCOME_HELD')
            result.update(state=state,status=state.get('execution_status') or state.get('status'),
                          error=state.get('last_error'),native_interrupts=workspace.store.get('native_interrupts') or [])
            return state
        except BaseException as exc:
            result['error']={'type':type(exc).__name__}
            raise
        finally:
            _active.reset(active)
            result.update(finished_utc=datetime.now(timezone.utc).isoformat(),budget=budget.run_snapshot(),
                campaign_budget=budget.snapshot(),admission_refusal=getattr(budget,'admission_refusal',None))
            if result['budget']['held'] > before['held']:
                result['status']='unknown_outcome_held'
            result['stage_tokens']=result['budget']['settled']-before['settled']
            with (stage/'result.json').open('x') as out:json.dump(result,out,indent=2)
