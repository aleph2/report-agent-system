"""Trusted one-request continuation of a frozen fake Writer indicator."""
from . import plan_authority
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path

from .assessment_completion import claim_launch, require_writer_model
from .content_store import ContentStore
from .content_tasks import delegated_task
from .deep_models import configured_model, connection_retry_count, sdk_retry_count
from .fake_verification import BOUND, MODEL, _utc, identify
from .fake_verification_budget import FakeContinuationBudget
from .model_config import bind_role_services, load_mixed_services, role_service
from .model_recovery import load_recovery_policy
from .store import Store
from .token_budget import current_token_observation, request_token_bound, token_budget
from .workspace import Workspace
from .writer_indicator_steps import IndicatorRun, PAGE_LIMIT
from .writer_probe import verified_request_bound
from .writer_runtime import writer_tools


def require(check, reason):
    if not check:
        raise ValueError(reason)


def pinned_json(path, expected):
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'RETRY_INPUT_CHANGED')
    return json.loads(raw)


def prior_rows(store, assignment):
    from .writer_judgments import read_progress
    return read_progress(store, assignment)['rows']


def rows_hash(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def restore_reads(case, capture_sha, indicator, previous_attempt):
    data = pinned_json(case/'blobs'/capture_sha[:2]/capture_sha, capture_sha)
    require(data['attempt_id']==previous_attempt and data['public_input']['model']==MODEL,'RETRY_CAPTURE_REQUEST')
    messages = data['public_input']['messages']
    require([m['role'] for m in messages] == ['system','user'] + ['assistant','tool']*PAGE_LIMIT,
            'RETRY_CAPTURE_SHAPE')
    step = json.loads(messages[1]['content'])
    require(step['indicator_id'] == indicator, 'RETRY_CAPTURE_INDICATOR')
    reads = []
    for request, response in zip(messages[2::2],messages[3::2],strict=True):
        call, = request['tool_calls']
        require(call['function']['name']=='read_assigned_page' and response['tool_call_id']==call['id'],
                'RETRY_READ_IDENTITY')
        args=json.loads(call['function']['arguments'])
        content=response['content']
        require(isinstance(content,list) and len(content)==1 and content[0]['type']=='text', 'RETRY_TEXT_ONLY')
        result=json.loads(content[0]['text'])
        location={k:args[k] for k in ('source_handle','page')}
        require(all(result[k]==v for k,v in location.items()),'RETRY_READ_LOCATION')
        reads.append({'location':location,'content':content[0]['text']})
    return step,reads


async def retry(run, authority, old_receipt, model, budget):
    """The trusted caller owns route verification, the budget binding and the case lock."""
    case=run/'case'
    ws=Workspace(Store(case))
    cs=ContentStore(ws.store)
    step,reads=restore_reads(case,authority['capture_sha256'],authority['indicator'],budget.previous_attempt)
    require(step['object_label']==authority['object_label'], 'RETRY_OBJECT_CHANGED')
    task=authority['task_id']
    require(old_receipt['slopes'][0]['writer_actor']=='content:writer:'+task,'RETRY_TASK_CHANGED')
    before=prior_rows(ws.store,step['assignment_digest'])
    require(rows_hash(before)==authority['saved_rows_sha256'] and len(before)==7
            and authority['indicator'] not in before,'RETRY_SAVED_ROWS_CHANGED')
    claim={'started_at_utc':_utc(),'old_attempt':budget.previous_attempt,'task_id':task,
           'run_id':budget.run_id,'indicator':authority['indicator'],'saved_rows_sha256':rows_hash(before),
           'candidate_commit':authority['candidate_commit'],'original_result_sha256':authority['original_result_sha256']}
    claim_launch(run/'indicator-retry-claim.json',claim)
    result={**claim,'status':'interrupted'}
    try:
        call={'name':'task','id':'one-request-retry-'+budget.previous_attempt,'args':{
              'subagent_type':'writer','description':'Resume the current assigned indicator.',
              'resume_content_task_id':task}}
        with delegated_task(ws,'coordinator',call) as (_,actor):
            require(actor.task_id==task and cs.read(old_receipt['plan_ref'])['ref']==old_receipt['plan_ref'],
                    'RETRY_TASK_OR_PLAN_CHANGED')
            from .writer_assignments import bound_assignment
            from .writer_fact_packet import bind_writer_facts
            from .writer_judgment_authority import provision_criteria
            with ws.store.connect() as db:
                scope = bound_assignment(cs, db, actor)
            bind_writer_facts(cs, actor, scope)
            provision_criteria(cs, scope)
            tools=writer_tools(ws,actor,include_images=False,assessment_only=True)
            session=IndicatorRun(ws,actor,model,tools)
            await session.run(continuation=(step,reads))
            result['refusals']=session.refusals
            result['step_interruptions']=session.progress['interrupted_indicators']
    except Exception as error:
        result['error_type']=type(error).__name__
    finally:
        after=prior_rows(ws.store,step['assignment_digest'])
        original={k:after.get(k) for k in before}
        result['seven_rows_preserved']=original==before
        extra=set(after)-set(before)
        result['scope_preserved']=result['seven_rows_preserved'] and extra <= {authority['indicator']}
        if not result['scope_preserved']:
            result['status']='integrity_failure'
        elif extra:
            result['status']='row_saved'
        elif 'error_type' not in result:
            result['status']=('save_rejected' if result.get('step_interruptions') else 'returned_without_save')
        with closing(budget.connect()) as db:
            old=db.execute('SELECT state,reserved,used FROM attempts WHERE id=?',(budget.previous_attempt,)).fetchone()
            mapped=db.execute("SELECT 1 FROM sqlite_master WHERE name='fake_continuations'").fetchone()
            new=db.execute("""SELECT a.id,a.state,a.reserved,a.used FROM attempts a JOIN fake_continuations c
                              ON a.id=c.retry_id WHERE c.previous_id=?""",(budget.previous_attempt,)).fetchone() if mapped else None
        result['old_hold_preserved']=bool(old and old[0] in ('reserved','unknown') and old[1:]==(BOUND,None))
        result['retry_attempt']=dict(zip(('id','state','reserved','used'),new)) if new else None
        if not result['old_hold_preserved'] or not result['scope_preserved']:
            result['status']='integrity_failure'
        elif new and new[1] in ('reserved','unknown'):
            result['status']='unknown_outcome'
        result.update(finished_at_utc=_utc(),budget=budget.run_snapshot(),campaign=budget.snapshot())
        claim_launch(run/'indicator-retry-result.json',result)
    return result


async def launch(authority_path, authority_sha):
    a=pinned_json(authority_path,authority_sha)
    run=Path(a['run_dir'])
    require(run.is_absolute() and run.resolve()==run and run.name==a['run_id']
            and run.parent.name=='runs','RETRY_RUN_PATH')
    grant=run.parent.parent
    old=pinned_json(run/'result.json',a['original_result_sha256'])
    prepared=pinned_json(run/'prepared.json',old['prepared_sha256'])
    original=pinned_json(Path(a['original_authority']),old['authority_sha256'])
    pins=identify()
    require(a['candidate_commit']==pins['candidate_commit'] and
            pins['fixture_manifest_sha256']==old['fixture_manifest_sha256'] and
            old['status']=='interrupted' and old['run_id']==original['run_id']==a['run_id']
            and Path(original['grant_dir'])==grant and Path(prepared['case_path'])==run/'case'
            and old['plan_ref']==prepared['plan_ref'] and old['decision_ref']==prepared['decision_ref'],
            'RETRY_RUN_BINDING')
    gate=pinned_json(Path(a['regression_file']),a['regression_sha256'])
    require(gate['status']=='passed' and gate['source_frozen'] and gate['candidate_commit']==pins['candidate_commit']
            and not gate['failures'] and gate['passed']+gate['skipped']==gate['expected_nodes']
            and not any(gate[k] for k in ('missing','extra','duplicate_nodes','collection_errors')),
            'RETRY_REGRESSION_REQUIRED')
    require(current_token_observation() is None,'RETRY_SEPARATE_GRANT_REQUIRED')
    budget=FakeContinuationBudget(grant,a['run_id'],a['previous_attempt'])
    require(budget.model_bounds=={MODEL:BOUND} and old['budget']==budget.run_snapshot(),'RETRY_BUDGET_CHANGED')
    env=Path(a['service_env'])
    load_mixed_services(env)
    name,url,_=role_service('writer')
    bound=verified_request_bound(original['request_bound_proof'],env,name,url)
    require(bound.total==BOUND and sdk_retry_count()==0 and connection_retry_count()==0,'RETRY_SERVICE_POLICY')
    store=Store(run/'case')
    with store.run_lock(), token_budget(budget), request_token_bound(bound):
        require(not load_recovery_policy(store),'RETRY_RECOVERY_DISABLED_REQUIRED')
        require(plan_authority.plan_ref(store)==old['plan_ref'] and plan_authority.decision_ref(store)==old['decision_ref'],
                'RETRY_PLAN_CHANGED')
        with closing(budget.connect()) as db:
            held=db.execute('SELECT id,reserved,used,state FROM attempts WHERE id=?',(budget.previous_attempt,)).fetchone()
        require(held and held[1]==BOUND and held[2] is None and held[3] in ('reserved','unknown'),'RETRY_HOLD_CHANGED')
        bind_role_services(store)
        model=configured_model(store,'writer')
        try:
            require_writer_model(model,MODEL)
            require((model.profile or {}).get('image_inputs') is False,'RETRY_TEXT_ONLY')
            return await retry(run,a,old,model,budget)
        finally:
            try: await model.root_async_client.close()
            finally: model.root_client.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authority',required=True,type=Path)
    parser.add_argument('--authority-sha256',required=True)
    args=parser.parse_args()
    result=asyncio.run(launch(args.authority,args.authority_sha256))
    print(json.dumps({'status':result['status'],'budget':result['budget']}))
    raise SystemExit(0 if result['status']=='row_saved' else 1)
