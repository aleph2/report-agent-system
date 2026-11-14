"""No-call acceptance rehearsal; requires an isolated grant-directory bind mount."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphBubbleUp

from report_agent import run_authority
from report_agent.content_store import ContentStore
from report_agent.content_tasks import bound_actor, model_owner_identity
from report_agent.deep_runtime import project_agent, project_view
from report_agent.store import Store, encode
from report_agent.token_budget import token_budget, request_token_bound
from report_agent.tool_selection import tool_scope
from report_agent.workspace import Workspace


class ModelBoundaryReached(GraphBubbleUp):
    pass


def receipts(workspace):
    with closing(sqlite3.connect(workspace.store.path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        return [list(row) for row in db.execute('SELECT * FROM writer_step_receipts ORDER BY rowid')]


async def rehearse(config):
    assert os.readlink('/proc/self/ns/mnt') != config['host_mount_namespace']
    assert os.readlink('/proc/self/ns/net') != config['host_network_namespace']
    marker=Path(config['private_marker'])
    assert marker.read_text()==config['marker_value'], 'PRIVATE_GRANT_COPY_REQUIRED'
    authority_path=Path(config['authority_path'])
    authority=json.loads(authority_path.read_text())
    assert Path(authority['case_path']).is_relative_to(marker.parent)
    workspace=Workspace(Store(Path(authority['case_path'])))
    manifest=workspace.store.manifest
    assert manifest['review_interface_profile']=='review-interfaces-v4'
    assert manifest['operation_identity_profile']=='native-tool-runtime-v1'
    before=receipts(workspace)
    assert {row[1] for row in before}=={'X11','X12'}, 'EXPECTED_EXISTING_X11_X12_RECEIPTS'
    proof={'mode':config['mode'],'profiles':{k:manifest[k] for k in (
        'review_interface_profile','operation_identity_profile')},'model_boundaries':[],
        'scripted_decisions':[],'paid_calls':0,'network_namespace':os.readlink('/proc/self/ns/net')}
    original=BaseChatModel._agenerate_with_cache

    async def probe_request(model,messages,*args,**kwargs):
        identity=model_owner_identity(workspace.store)
        if identity is None:
            from report_agent.hierarchical_tools import actor_for
            identity={'actor':actor_for('coordinator').__dict__}
        actor=identity['actor']
        tools=kwargs.get('tools') or []
        names={tool.get('function',{}).get('name') for tool in tools}
        if config['mode']=='assessment' and actor.get('role')=='coordinator':
            from report_agent.live_messages import _MODEL
            offer=_MODEL.get()
            scope=next(entry['scope'] for entry in offer['resources']
                if entry['resource']['type']=='DelegatedTask' and
                   entry['resource']['id']==config['assessment_task_id'])
            assert not proof['scripted_decisions'], 'UNEXPECTED_COORDINATOR_REENTRY'
            call={'name':'task','id':'rehearsal-task-'+uuid4().hex,'type':'tool_call',
                'args':{'subagent_type':'writer','description':'Continue the existing bound assessment without changing its assignment.',
                        'resume_task_scope':scope}}
            proof['scripted_decisions'].append({'role':'coordinator','call':call})
            return ChatResult(generations=[ChatGeneration(message=AIMessage(id='rehearsal-message-'+uuid4().hex,content='',tool_calls=[call]))])
        if config['mode']=='assessment' and 'assess_assigned_object' in names:
            from report_agent.writer_assessment import read_indicator_step
            who=bound_actor(workspace,'writer',None)
            assert who.task_id==config['assessment_task_id']
            step=read_indicator_step(ContentStore(workspace.store),who)
            proof['next_indicator_before_native_tool']=step
            assert step['indicator_id']==config['expected_indicator'] and step['progress']['recorded']==2
            assert len(proof['scripted_decisions'])==1, 'UNEXPECTED_WRITER_REENTRY'
            call={'name':'assess_assigned_object','id':'rehearsal-assess-'+uuid4().hex,
                  'type':'tool_call','args':{}}
            proof['scripted_decisions'].append({'role':'writer','call':call})
            return ChatResult(generations=[ChatGeneration(message=AIMessage(id='rehearsal-message-'+uuid4().hex,content='',tool_calls=[call]))])
        admission=(run_authority.current_authority() or {}).get('_native_continuation')
        request={'actor':actor,'tools':tools,'messages':[message.model_dump(mode='json') for message in messages],
                 'admission':({k:(sorted(v) if isinstance(v,set) else v) for k,v in admission.items()} if admission else None)}
        proof['model_boundaries'].append(request)
        if config['mode']=='current':
            assert actor.get('task_id')==config['prose_task_id'], 'WRONG_ORIGINAL_CHILD'
            assert admission and len(admission['used'])==1
            used=next(iter(admission['used']))
            assert used[:2]==(config['prose_namespace'],config['prose_checkpoint_id'])
            proof['consumed_original_child']=list(used)
            task=ContentStore(workspace.store).read({'type':'DelegatedTask','id':actor['task_id'],'version':1})
            proof['section_ids']=task['payload']['section_ids']
            assert set(proof['section_ids'])==set(config['section_ids'])
            contract=next(tool['function']['description'] for tool in tools
                if tool.get('function',{}).get('name')=='process_report_content')
            proof['offered_prose_contract']=contract
            assert 'Assigned section prose uses block/text-only/empty' in contract
            assert 'qualifiers; preserve genuine qualifications in rendered text.' in contract
            text=json.dumps(request['messages'],ensure_ascii=False)
            assert config['disposition_text'].strip() and config['feedback_id'].strip()
            proof['disposition_text_present']=config['disposition_text'] in text
            proof['feedback_id_present']=config['feedback_id'] in text
            assert proof['disposition_text_present'] and proof['feedback_id_present']
        else:
            assert actor.get('task_id')==config['assessment_task_id']
            packets=[]
            for message in messages:
                if isinstance(message,HumanMessage) and isinstance(message.content,str):
                    try:value=json.loads(message.content)
                    except ValueError:continue
                    if isinstance(value,dict) and value.get('indicator_id'):packets.append(value)
            assert len(packets)==1 and packets[0]['indicator_id']==config['expected_indicator']
            proof['first_indicator_packet']=packets[0]
        raise ModelBoundaryReached('OFFLINE_REHEARSAL_MODEL_REQUEST_REACHED_NOT_SENT')

    async def probe(model,messages,*args,**kwargs):
        try:
            return await probe_request(model,messages,*args,**kwargs)
        except GraphBubbleUp:
            raise
        except Exception as error:
            proof['failure_messages']=[message.model_dump(mode='json') for message in messages]
            proof['failure_tools']=kwargs.get('tools')
            proof['guard_failure']={'type':type(error).__name__,'message':str(error)}
            raise ModelBoundaryReached('OFFLINE_REHEARSAL_FAILED_LOUDLY') from error

    BaseChatModel._agenerate_with_cache=probe
    try:
        if config['mode']=='current':
            try:
                proof['native_result']=await run_authority.run_authorized_report(workspace,
                    authority_path,config['authority_sha256'],config['env_file'],config['invocation'])
            except ModelBoundaryReached:
                proof['native_result']='model boundary propagated'
        else:
            data=run_authority.preflight(workspace,authority_path,config['authority_sha256'],
                                         config['env_file'],config['invocation'])
            authority,services,policies,budget,criteria=data
            active=run_authority._active.set({**authority,'criteria':criteria,'_native_continuation':None})
            try:
                with (run_authority._environment(authority,services),token_budget(budget),request_token_bound(policies),
                      tool_scope(set(authority['roles'].values()),authority['roles'])):
                    async with project_agent(workspace) as agent:
                        try:
                            await agent.ainvoke({'messages':[HumanMessage(content=encode(project_view(workspace)))],
                                'rubric':''},{'configurable':{'thread_id':'rehearsal-assessment-'+uuid4().hex},
                                **run_authority.graph_config('root')})
                        except ModelBoundaryReached:
                            pass
            finally:
                run_authority._active.reset(active)
    finally:
        BaseChatModel._agenerate_with_cache=original
        after=receipts(workspace)
        proof['committed_step_receipts_unchanged']=before==after
        proof['committed_step_receipt_count']=len(before)
        Path(config['output_path']).write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    assert not proof.get('guard_failure'), proof.get('guard_failure')
    assert len(proof['model_boundaries'])==1, 'EXPECTED_EXACTLY_ONE_TARGET_MODEL_BOUNDARY'
    assert before==after, 'COMMITTED_STEP_RECEIPTS_CHANGED'
    return {'mode':config['mode'],'status':'model_request_reached_not_sent',
            'scripted_decisions':len(proof['scripted_decisions']),'paid_calls':0,
            'step_receipts_unchanged':True,'proof':config['output_path']}


if __name__=='__main__':
    config=json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(asyncio.run(rehearse(config)),indent=2))
