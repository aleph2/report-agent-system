"""Trusted operator entrypoint for exactly one fresh HP02 assessment probe."""
import argparse
import asyncio
from contextlib import AsyncExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .assessment_completion import (read_finance, claim_launch, _save, saved_assessments)
from .probe_budget import ProbeBudget
from .token_budget import RequestBound, TokenBudget, token_budget, request_token_bound


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _load(path):
    return json.loads(Path(path).read_text())


def verified_request_bound(proof, env, model, base_url):
    """Verify the existing approved service pin and documented full model ceiling.

    This is conservative accounting, not certified measurement of request fit.
    """
    import httpx
    sources = proof.get('sources', [])
    if (model != 'glm-5.3' or proof.get('model') != model
            or proof.get('input_limit') != 1_048_576 or proof.get('output_limit') != 131_072
            or proof.get('basis') != 'documented_model_ceiling_not_measured_request_fit'
            or proof.get('env_sha256') != _hash(Path(env).read_bytes())
            or proof.get('base_url_sha256') != _hash(base_url.rstrip('/').encode())
            or proof.get('request_url_sha256') != _hash(str(httpx.URL(base_url.rstrip('/')+'/chat/completions')).encode())
            or not isinstance(sources,list)
            or not {'https://docs.z.ai/guides/llm/glm-5.3',
                    'https://help.aliyun.com/zh/model-studio/glm-5-3'} <= set(sources)):
        raise ValueError('PROBE_REQUEST_PROOF_INVALID')
    proof_hash = _hash(json.dumps(proof,sort_keys=True,separators=(',',':')).encode())
    return RequestBound(model,proof['request_url_sha256'],proof['input_limit'],proof['output_limit'],proof_hash)


def refusal_rows(messages):
    from langchain_core.messages import ToolMessage
    result = {}
    for message in messages:
        if not isinstance(message,ToolMessage) or message.status != 'error':
            continue
        try:
            body = json.loads(message.content)
        except (TypeError,ValueError):
            body = {}
        code = body.get('code') if isinstance(body,dict) else None
        result[message.tool_call_id] = {'tool':message.name,'tool_call_id':message.tool_call_id,
            'code':code if isinstance(code,str) and re.fullmatch('[A-Z][A-Z0-9_]{0,150}',code) else 'TOOL_REFUSED'}
    return list(result.values())


def _fresh_import(case, inputs):
    receipt = _load(case/'probe-import.json')
    if (receipt.get('version') != 'business-only-probe-import-v1'
            or receipt.get('case_root') != str(case) or receipt.get('source_unchanged') is not True
            or receipt.get('dependency_manifest',{}).get('old_execution_state_imported') is not False
            or _hash((case/'probe-import.json').read_bytes()) != inputs['import_sha256']
            or _hash((case/'state.db').read_bytes()) != receipt['case_db_sha256']):
        raise ValueError('PROBE_FRESH_BUSINESS_IMPORT_REQUIRED')
    with closing(sqlite3.connect((case/'state.db').as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('SELECT count(*) FROM events').fetchone()[0] or db.execute(
                "SELECT count(*) FROM content_versions WHERE type IN ('DelegatedTask','Assessment')").fetchone()[0]:
            raise ValueError('PROBE_FRESH_BUSINESS_IMPORT_REQUIRED')
    return receipt


async def _run_probe_locked(case, evidence, env):
    """One exclusive launch; every terminal outcome requires owner review, never replay."""
    case,evidence,env = (Path(p).resolve() for p in (case,evidence,env))
    if case.parent != evidence.parent or case == evidence:
        raise ValueError('PROBE_OWNED_EXECUTION_ROOT_REQUIRED')
    launch_path = evidence/'probe-launch.json'
    if launch_path.exists():
        raise FileExistsError('PROBE_ALREADY_LAUNCHED_INSPECT_ORIGINAL_OUTCOME')
    inputs = _load(evidence/'probe-inputs.json')
    authority = _load(evidence/'owner-authority.json')
    required_limits = {'hard_probe_tokens':2_200_000, 'investigation_threshold_tokens':1_000_000,
                       'overall_rescue_tokens':20_000_000, 'preserve_unknown_hold_tokens':2_000_000}
    if (_hash((evidence/'owner-authority.json').read_bytes()) != inputs['authority_sha256']
            or not isinstance(authority,dict)
            or any(type(authority.get(key)) is not int or authority[key] != value
                   for key,value in required_limits.items())
            or authority.get('no_other_slopes_cleanup_export_or_model_tests') is not True):
        raise ValueError('PROBE_OWNER_AUTHORITY_REQUIRED')
    imported = _fresh_import(case, inputs)
    ledger = Path(inputs['ledger']).resolve()
    now = read_finance(ledger)
    if now != inputs['stage_baseline']:
        raise ValueError('PROBE_PERSISTED_BASELINE_CHANGED')
    guard = ProbeBudget(lambda:read_finance(ledger),inputs['original_baseline'],inputs['stage_baseline'],
        maximum_tokens=authority['hard_probe_tokens'],overall_limit=authority['overall_rescue_tokens'],
        preserved_hold=inputs['preserved_hold'],writer_model='glm-5.3')
    guard.check()
    from .planning_budget import budget_scope_cost
    used,held,_ = budget_scope_cost(inputs['original_baseline'],now)
    if used+held+guard.maximum_tokens > guard.overall_limit:
        raise ValueError('PROBE_STAGE_DOES_NOT_FIT_REMAINING_BUDGET')
    from .model_config import load_mixed_services, role_service, bind_role_services
    from .deep_models import (configured_model, model_client_ownership,
                             sdk_retry_count, connection_retry_count, MODEL_KEEPALIVE_EXPIRY_SECONDS)
    load_mixed_services(env)
    name,url,_ = role_service('writer')
    bound = verified_request_bound(inputs['request_bound_proof'],env,name,url)
    connect_retries = connection_retry_count()
    if sdk_retry_count() or connect_retries != 2:
        raise ValueError('PROBE_CONNECTION_ONLY_RETRY_POLICY_REQUIRED')
    from .store import Store
    from .workspace import Workspace
    from .content_store import ContentStore
    from .commission_plan import _confirmed
    from .model_recovery import load_recovery_policy
    store = Store(case)
    contents = ContentStore(store)
    with store.connect() as db:
        plan,decision = _confirmed(contents,db)
    if (plan['ref'] != imported['plan_ref'] or decision['ref'] != imported['decision_ref']
            or plan['ref'] != inputs['plan_ref'] or decision['ref'] != inputs['decision_ref']):
        raise ValueError('PROBE_APPROVED_BINDING_CHANGED')
    object_id = inputs.get('object_id')
    if object_id != 'HP-02-K9023p670-L':
        raise ValueError('PROBE_APPROVED_HP02_ID_REQUIRED')
    selected = [o for o in plan['payload']['objects'] if o['object_id']==object_id]
    if len(selected)!=1 or load_recovery_policy(store):
        raise ValueError('PROBE_FRESH_HP02_ONLY_REQUIRED')
    bind_role_services(store)
    budget = TokenBudget(ledger,now['auth'][0],guard.bounds)
    result = {'at_utc':datetime.now(timezone.utc).isoformat(),'status':'running',
        'object_id':object_id,'object_label':selected[0]['label'],'plan_ref':plan['ref'],
        'decision_ref':decision['ref'],'maximum_tokens':guard.maximum_tokens,'request_bound':bound.total,
        'investigation_threshold_tokens':authority['investigation_threshold_tokens'],
        'investigation_threshold_basis':'settled_stage_tokens',
        'connection_retries':connect_retries,'sdk_retries':0,
        'keepalive_expiry_seconds':MODEL_KEEPALIVE_EXPIRY_SECONDS,
        'retry_scope':'pre_http_connection_only',
        'inputs_sha256':_hash((evidence/'probe-inputs.json').read_bytes()),
        'pid':os.getpid(),'uid':os.getuid(),
        'process_start_ticks':Path('/proc/self/stat').read_text().rpartition(')')[2].split()[19],
        'automatic_continuation':False,'engineering_acceptance':False,
        'visual_verification':'SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE'}
    claim_launch(launch_path,result)
    session = None
    try:
        from .writer_runtime import writer_session
        from .request_budget import request_reservation_observer
        async with AsyncExitStack() as resources:
            clients = set()
            def own(client,asynchronous):
                if id(client) not in clients:
                    clients.add(id(client))
                    resources.push_async_callback(client.aclose) if asynchronous else resources.callback(client.close)
            with model_client_ownership(own):
                model = configured_model(store,'writer')
            if (model.model_name != name or model.root_async_client.max_retries != 0
                    or (getattr(model,'profile',None) or {}).get('image_inputs') is not False):
                raise ValueError('PROBE_EFFECTIVE_MODEL_MISMATCH')
            with (token_budget(budget),request_token_bound(bound),
                  request_reservation_observer(guard.check,observation=guard.observation),
                  writer_session(Workspace(store),selected[0]['label'],model,assessment_only=True) as session):
                result['writer_actor'] = session.actor.__dict__
                result['tools'] = [t.name for t in session.tools]
                _save(launch_path,result)
                config = {**session.config,'recursion_limit':200}
                await session.agent.ainvoke({'messages':[session.initial_message]},config)
                guard.check()
                result['status'] = 'returned'
    except BaseException as error:
        result['status'] = 'stopped'
        result['error_type'] = type(error).__name__
        # Preserve exact trusted local guard codes without provider text or credentials.
        code = str(error)
        if re.fullmatch(r'(PROBE|SCOPED)_[A-Z0-9_]{1,140}',code):
            result['stop_code'] = code
    finally:
        try:
            result['budget'] = guard.observation()
            result['investigation_threshold_reached'] = (
                result['budget']['recorded_tokens'] >= result['investigation_threshold_tokens'])
            result['budget']['effective_request_bound'] = bound.total
            result['budget']['model_reservation_bounds'] = {name:bound.total}
            final = read_finance(ledger)
            total,totalheld,_ = budget_scope_cost(inputs['original_baseline'],final)
            result['overall_rescue'] = {'settled':total,'held':totalheld,
                'remaining':20_000_000-total-totalheld,
                'preserved_hold_unchanged':next((r for r in final['rows'] if r[0]==inputs['preserved_hold'][0]),None)==inputs['preserved_hold']}
            if session is not None:
                refs = saved_assessments(contents,plan['ref'],[object_id],session.actor.id)
                result['assessment_refs'] = refs
                state = await session.agent.aget_state(session.config)
                result['refusals'] = refusal_rows(state.values.get('messages',[]))
                if refs and result['status'] == 'returned':
                    result['status'] = 'assessment_saved'
            from .runtime_metrics import summarize
            result['metrics'] = summarize(case/'runtime-metrics.jsonl')
        except Exception as error:
            result['receipt_error_type'] = type(error).__name__
        result['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        result['next_action'] = 'Owner review of HP02 only; no further stages authorized by this launch.'
        _save(launch_path,result)
    return result


async def run_probe(case, evidence, env):
    import fcntl
    evidence = Path(evidence).resolve()
    with (evidence/'probe-run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return await _run_probe_locked(case,evidence,env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case','evidence','env'):
        parser.add_argument('--'+name,required=True,type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_probe(args.case,args.evidence,args.env))
    print(json.dumps({k:result.get(k) for k in ('status','stop_code','assessment_refs','budget','metrics')},ensure_ascii=False))
    return 0 if result['status']=='assessment_saved' else 1


if __name__=='__main__':
    raise SystemExit(main())
