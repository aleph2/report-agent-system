"""Trusted Fake03 planning probe; one launch stops before owner page-sheet approval."""
import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from . import fake_verification as host
from .assessment_completion import claim_launch, _save
from .fake_verification_budget import FakeFlowBudget
from .request_budget import RequestBudgetExceeded
from .token_budget import token_budget, request_token_bound

WORKFLOW = 'fake03-coordinator-page-sheet-probe-v1'
_KEY = host._REPO/'docs/verification/fake03-post-9a/answer-key-v2.json'


def identify():
    return {**host.identify(),'answer_key_sha256':host._sha(_KEY)}


def preflight(path, pin):
    data=json.loads(Path(path).read_bytes())
    cap=data.get('per_run_tokens')
    if (type(cap) is not int or cap not in (3_700_000,5_500_000)
            or data.get('model')!=host.MODEL or data.get('objects')!=['A','B']
            or data.get('proposed_exclusions')!=['C'] or data.get('stop_at')!='page_sheet'
            or data.get('answer_key_sha256')!=host._sha(_KEY)
            or 'fresh_comparison' not in data or 'qualitative_pilot' in data):
        raise ValueError('FAKE_PLANNING_PROBE_SCOPE_MISMATCH')
    return host.preflight(path,pin,workflow=WORKFLOW,per_run_tokens=cap,comparison_count=1)


def prepare(path, pin):
    from .fake_draft_flow import prepare as fresh
    authority=preflight(path,pin)
    root=Path(authority['grant_dir'])/'runs'/authority['run_id']
    root.mkdir(parents=True,exist_ok=False)
    profiles=json.loads((host._REPO/'config/current.json').read_text())['manifest_profiles']
    receipt={**fresh(host.INPUTS,root/'case',profiles),**identify(),'authority_sha256':pin}
    receipt['case_seal']=host._seal(root/'case')
    claim_launch(root/'prepared.json',receipt)
    return {**receipt,'prepared_sha256':host._sha(root/'prepared.json')}


def check_prepared(path,pin,prepared_pin):
    authority=preflight(path,pin)
    root=Path(authority['grant_dir'])/'runs'/authority['run_id']
    if (root/'result.json').exists():raise FileExistsError('FAKE_PROBE_ALREADY_CLAIMED')
    receipt=json.loads((root/'prepared.json').read_text())
    if (host._sha(root/'prepared.json')!=prepared_pin or receipt['authority_sha256']!=pin
            or any(receipt.get(k)!=v for k,v in identify().items())
            or receipt['case_path']!=str(root/'case') or receipt['case_seal']!=host._seal(root/'case')):
        raise ValueError('FAKE_PROBE_PREPARED_CASE_CHANGED')
    return {**receipt,'prepared_sha256':prepared_pin}


async def launch(path,pin,prepared_pin,env_file):
    from . import model_config, deep_models
    from .writer_probe import verified_request_bound
    from .store import Store
    from .workspace import Workspace
    from .hierarchical_tools import actor_for
    from .model_recovery import load_recovery_policy
    from .fake_draft_flow import plan
    from .tool_trace import ToolTrace,capture_tools,summarize_trace
    from . import page_bindings,plan_authority

    authority=preflight(path,pin);receipt=check_prepared(path,pin,prepared_pin)
    case=Path(receipt['case_path']);root=case.parent;env_file=Path(env_file).resolve()
    if env_file.is_relative_to(root) or env_file.is_relative_to(host._REPO):
        raise ValueError('FAKE_EXTERNAL_SERVICE_CONFIG_REQUIRED')
    model_config.load_mixed_services(env_file)
    service=model_config.role_service('writer')
    bound=verified_request_bound(authority['request_bound_proof'],env_file,*service[:2])
    if deep_models.sdk_retry_count()!=0 or deep_models.connection_retry_count()!=2:
        raise ValueError('FAKE_SERVICE_POLICY_REQUIRED')
    # One approved GLM service for every constructible role; the HTTP guard admits only planning.
    for role in ('COORDINATOR','WRITER','REVIEWER','TEXT_TOOL','LAYOUT','RUBRIC_GRADER','MATERIALS'):
        for suffix,value in zip(('MODEL','BASE_URL','API_KEY'),service):os.environ['REPORT_'+role+'_'+suffix]=value
    ws=Workspace(Store(case))
    if load_recovery_policy(ws.store):raise ValueError('FAKE_RECOVERY_DISABLED_REQUIRED')
    budget=FakeFlowBudget(authority['grant_dir'],authority['run_id'],authority['fresh_comparison'],pin,
                          maximum_tokens=authority['per_run_tokens'])
    budget.check_fresh()
    if budget.snapshot()['remaining_for_new_reservations']<bound.total:
        raise RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED')
    model_config.bind_role_services(ws.store)
    result=dict(status='claimed',run_id=authority['run_id'],workflow=WORKFLOW,authority_sha256=pin,
        candidate_commit=authority['candidate_commit'],started_utc=datetime.now(timezone.utc).isoformat(),
        automatic_continuation=False,model=host.MODEL,request_reservation=bound.total,
        pid=os.getpid(),uid=os.getuid(),process_start_ticks=Path('/proc/self/stat').read_text().rpartition(')')[2].split()[19])
    claim_launch(root/'result.json',result)
    trace=ToolTrace(ws,authority['run_id'],root/'tool-trace.jsonl',actor_for('coordinator'))
    try:
        async with AsyncExitStack() as clients:
            seen=set()
            def own(client,asynchronous):
                if id(client) not in seen:
                    seen.add(id(client))
                    clients.push_async_callback(client.aclose) if asynchronous else clients.callback(client.close)
            def factory(role):
                model=deep_models.configured_model(ws.store,role)
                if model.model_name!=host.MODEL or (model.profile or {}).get('image_inputs') is not False:
                    raise ValueError('FAKE_PROBE_EFFECTIVE_MODEL_MISMATCH')
                def admit(request):
                    if role!='coordinator':raise RequestBudgetExceeded('FAKE_PROBE_COORDINATOR_ONLY')
                async def admit_async(request):admit(request)
                model.http_client.event_hooks['request'].insert(0,admit)
                model.http_async_client.event_hooks['request'].insert(0,admit_async)
                return model
            with (deep_models.model_client_ownership(own),token_budget(budget),request_token_bound(bound),capture_tools(trace)):
                result['planning_result']=await plan(ws,factory)
        result['status']='planning_stopped'
        ref=plan_authority.plan_ref(ws.store)
        result['plan_ref']=ref
        result['page_bindings']=[{'record':r,'state':s} for r,s in page_bindings.records(ws.store,ref)] if ref else []
        if result['planning_result'].get('status')=='needs_human':
            result['status']='page_sheet_checkpoint' if ref and page_bindings.sheet_route(ws.store,ref) else 'other_human_checkpoint'
    except BaseException as error:
        result.update(status='stopped',error_type=type(error).__name__)
        if isinstance(error,RequestBudgetExceeded):result['stop_code']=str(error)
        raise
    finally:
        from .runtime_metrics import summarize
        result.update(runtime_metrics=summarize(case/'runtime-metrics.jsonl'),
            finished_utc=datetime.now(timezone.utc).isoformat(),budget=budget.run_snapshot(),
            campaign_budget=budget.snapshot(),trace_summary=summarize_trace(root/'tool-trace.jsonl'))
        if result['budget']['held']:result['status']='unknown_outcome_held'
        elif result['status']=='planning_stopped' and trace.last_admission_code in {
                'FAKE_RUN_TOKEN_LIMIT','AUTHORIZED_TOKEN_BUDGET_REACHED'}:
            result['status']='budget_stop'
        if trace.last_admission_code:result['stop_code']=trace.last_admission_code
        _save(root/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['identify','prepare','check','run'])
    parser.add_argument('--authority',type=Path);parser.add_argument('--authority-sha256')
    parser.add_argument('--prepared-sha256');parser.add_argument('--env',type=Path)
    args=parser.parse_args()
    if args.action=='identify':result=identify()
    else:
        if not args.authority or not args.authority_sha256:parser.error('authority and separately pinned digest required')
        if args.action=='prepare':result=prepare(args.authority,args.authority_sha256)
        elif args.action=='check':result=check_prepared(args.authority,args.authority_sha256,args.prepared_sha256)
        else:
            if not args.env or not args.prepared_sha256:parser.error('external config and prepared digest required')
            result=asyncio.run(launch(args.authority,args.authority_sha256,args.prepared_sha256,args.env))
            result={k:result[k] for k in ('status','run_id','budget','campaign_budget','trace_summary')}
    print(json.dumps(result,ensure_ascii=False))
    return int(args.action=='run' and result['status'] not in {'page_sheet_checkpoint','other_human_checkpoint'})


if __name__=='__main__':raise SystemExit(main())
