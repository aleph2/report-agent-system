"""Actual SDK wire and saved canonical review, with fake model decisions only."""
from collections import Counter
from copy import deepcopy
import json,re
import httpx
import pytest
from report_agent.deep_runtime import run_report
from report_agent.deep_models import GLMChatOpenAI,model_async_client
from report_agent.errors import ActionRejected
from test_deliverable_declaration_v4 import case
from test_review_work_units import configured,unit_todo
from test_prompt_native_sdk_inputs import completion
from test_review_scope_selectors import CONTRACT,IDENTITY


def dereference(node,schema):
    while '$ref' in node:
        ref=node['$ref'];assert ref.startswith('#/')
        node=schema
        for part in ref[2:].split('/'):node=node[part]
    return node


@pytest.mark.parametrize('text_profile',['legacy-v1','concise-v1'])
@pytest.mark.parametrize('enabled',[False,True])
async def test_native_sdk_scope_identity_and_honest_partial_save(case,text_profile,enabled):
    cs,output,ws,request=configured(case)
    manifest={**cs.store.manifest,'report_prompt_profile':text_profile,
              'report_expression_profile':'reader-expression-v2',
              'operation_identity_profile':'native-tool-runtime-v1'}
    if enabled:manifest['review_submission_contract']=CONTRACT
    ws.store.set('manifest',manifest)
    models,bodies,counts={}, {},Counter()
    todo=unit_todo(output['refs']['a-body'])
    todo['content']='Compare the assigned saved text with the actual acceptance outcome.'
    todo['review_unit'].update(material_needs='Read report root and actual body, then compare the original criterion.',
        method='Compare the literal saved body with the assigned outcome; preserve missing support.',
        decision_conditions='A supported conclusion or explicit remaining evidence gap.',
        remaining_work='Read the exact saved objects and check original support.')

    def factory(role):
        if role in models:return models[role]
        client=model_async_client(ws.store,role)
        def transport(request_http):
            body=json.loads(request_http.content);bodies.setdefault(role,[]).append(body)
            step=counts[role];counts[role]+=1
            text='Scoped result retained; unresolved original obligations remain.';tool=None
            if role=='coordinator':
                if step==0:tool=('task',request['args'])
            elif step==0:tool=('write_todos',{'todos':[todo]})
            elif step==1:tool=('read_context',{'target_ref':output['refs']['a']})
            elif step==2:tool=('read_context',{'target_ref':output['refs']['a-body']})
            elif step==3:
                tasks=[t for t in cs.list_objects('DelegatedTask') if t['payload'].get('role')=='reviewer']
                task=tasks[-1]['payload'];requirement=task['review_requirements'][0]
                observed=[]
                for message in body['messages']:
                    if message['role']!='tool' or message.get('name') not in (None,'read_context'):continue
                    try:reply=json.loads(message['content'])
                    except (ValueError,TypeError):continue
                    if isinstance(reply,dict) and reply.get('receipt_id'):
                        observed.append({'receipt_id':reply['receipt_id'],'locator':'Exact saved root/body object',
                            'observation':'Read literal synthetic report content; original support remains to be compared.'})
                if len(observed)==2:
                    item={'scope':'Partial comparison of saved content','execution_state':'running','verdict':None,
                        'observations':observed,'checked_requirement_indexes':[],
                        'check_results':[{'requirement_index':0,'execution_state':'partial',
                            'result':'Read exact saved text; original support comparison remains.',
                            'observation_indexes':[0,1],'remaining':'Compare original support before a conclusion.'}],
                        'coverage':{'checked':[],'unchecked':requirement['required_checks'],'blocked':[],
                                    'basis':'Actual reads do not complete independent verification.'},
                        'reason':'A real partial check, not acceptance or a schema probe.'}
                    if enabled:item['assigned_scope_index']=0
                    else:item.update({k:deepcopy(requirement.get(k,'content' if k=='assessment_kind' else None)) for k in IDENTITY})
                    value={'target_ref':requirement['target_ref'],'snapshot_ref':task['review_snapshot_ref'],
                        'scope':'Partial assigned comparison','criteria_refs':[requirement['criterion_ref']],
                        'dependency_refs':[],'items':[item]}
                    arguments={'review':value}
                    tool=('submit_review',arguments)
                else:text='Required reads did not return two receipts; no review submitted.'
            response=completion(request_http,text,tool)
            value=response.json()
            if tool:value['choices'][0]['message']['tool_calls'][0]['id']=f'fixture-{role}-{step}-{tool[0]}'
            return httpx.Response(200,json=value)
        client._transport=httpx.MockTransport(transport);client._mounts.clear()
        models[role]=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result=await run_report(ws,factory)
        assert result['last_error'] is None,result
        first=bodies['reviewer'][0]
        offered=next(t['function'] for t in first['tools'] if t['function']['name']=='submit_review')
        schema=offered['parameters'];review=dereference(schema['properties']['review'],schema)
        item=dereference(dereference(review['properties']['items'],schema)['items'],schema)
        assert ('assigned_scope_index' in item['properties']) is enabled
        assert (not IDENTITY & item['properties'].keys()) is enabled
        assert 'operation_id' not in schema['properties']
        system=json.dumps([m['content'] for m in first['messages'] if m['role']=='system'],ensure_ascii=False)
        if enabled:assert re.search(r'assigned_scope_index\\?"\s*:\s*0',system),system[-1500:]
        records=cs.list_objects('ReviewRecord');assert len(records)==1
        record=records[0];saved=record['payload']['items'][0]
        task=cs.read({'type':'DelegatedTask','id':record['task_id'],'version':1})['payload']
        requirement=task['review_requirements'][0]
        assert (task.get('review_submission_contract')==CONTRACT) is enabled
        for name in IDENTITY:assert saved[name]==requirement.get(name,'content' if name=='assessment_kind' else None)
        assert 'assigned_scope_index' not in saved
        assert record['owner_id']=='content:reviewer:'+record['task_id']
        assert saved['execution_state']=='running' and saved['verdict'] is None and saved['coverage']['unchecked']
        assert len(saved['observations'])==2
        assert set(bodies)=={'coordinator','reviewer'}
        captures=[ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input']
        reviewer=[c for c in captures if c['purpose']=='reviewer'];assert reviewer
        selected='native-submit-review-selectors' if enabled else 'native-submit-review-v4'
        if text_profile=='concise-v1':selected+='-concise'
        for capture in reviewer:
            assert capture['status']!='unexplained',capture['sources']
            names={f['name']:f for f in capture['source_manifest']['files']}
            assert selected in names and names[selected]['offered_match']!='not_observed'
    finally:
        for model in models.values():
            await model.root_async_client.close();model.root_client.close()


@pytest.mark.parametrize('text_profile',['legacy-v1','concise-v1'])
@pytest.mark.parametrize('enabled',[False,True])
async def test_existing_v4_native_prerequisite_refuses_caller_profile_before_model(case,text_profile,enabled):
    cs,_,ws,_=configured(case)
    manifest={**cs.store.manifest,'report_prompt_profile':text_profile,
              'operation_identity_profile':'caller-operation-v1'}
    if enabled:manifest['review_submission_contract']=CONTRACT
    ws.store.set('manifest',manifest)
    def factory(role):
        pytest.fail('The pre-existing V4 native prerequisite must fail before model construction')
    with pytest.raises(ActionRejected,match='REVIEW_INTERFACE_V4_REQUIRES_NATIVE_RELEASE'):
        await run_report(ws,factory)
    assert not cs.list_objects('ReviewRecord')


async def test_shared_sdk_model_uses_each_child_scope_zero_and_captured_release(case):
    import asyncio
    from report_agent.content_tasks import bound_actor
    from report_agent.workspace import Workspace
    from test_review_binding_v4 import prepared,review_call,task_record
    from test_reviewer_native_profile import candidate
    cs,output,criteria,_=prepared(case);ws=Workspace(cs.store)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT,
                            'report_prompt_profile':'concise-v1','report_expression_profile':'reader-expression-v2'})
    requests=[review_call(criteria[index:index+1],identity='native-child-'+str(index)) for index in range(2)]
    models={};counts=Counter();reviewed={};wires=[]
    def factory(role):
        if role in models:return models[role]
        client=model_async_client(ws.store,role)
        async def transport(request_http):
            body=json.loads(request_http.content);wires.append((role,body))
            if role=='coordinator':
                step=counts[role];counts[role]+=1
                if step:
                    return completion(request_http,'Both independent scoped results retained, not whole-report acceptance.')
                # The graph already owns the release: mutable Store settings cannot switch its children.
                changed={**cs.store.manifest,'goal':'A later unbound goal'}
                changed.pop('review_submission_contract')
                cs.store.set('manifest',changed)
                value=completion(request_http,'',('task',requests[0]['args'])).json()
                calls=value['choices'][0]['message']['tool_calls'];calls[0]['id']=requests[0]['id']
                calls.append({**deepcopy(calls[0]),'id':requests[1]['id'],
                    'function':{'name':'task','arguments':json.dumps(requests[1]['args'])}})
                return httpx.Response(200,json=value)
            actor=bound_actor(ws,'reviewer',None)
            task=task_record(cs,actor)['payload'];requirement=task['review_requirements'][0]
            assert task['review_submission_contract']==CONTRACT
            step=counts[actor.id];counts[actor.id]+=1
            await asyncio.sleep(0)
            if step==0:
                selected=('read_context',{'target_ref':output['refs']['a-body']})
            elif step==1:
                receipts=[]
                for message in body['messages']:
                    if message['role']!='tool':continue
                    try:reply=json.loads(message['content'])
                    except (ValueError,TypeError):continue
                    if isinstance(reply,dict) and reply.get('receipt_id'):receipts.append(reply['receipt_id'])
                assert len(receipts)==1
                value=candidate(task['review_snapshot_ref'],{'root':output['refs']['a'],
                    'k':requirement['criterion_ref'],'support':output['refs']['support']},receipts,
                    verdict=None,state='running')
                for field in IDENTITY:value['items'][0].pop(field,None)
                value['items'][0]['assigned_scope_index']=0
                selected=('submit_review',{'review':value})
                reviewed[actor.task_id]=deepcopy(requirement)
            else:
                return completion(request_http,'Saved actual partial comparison; evidence remains incomplete.')
            value=completion(request_http,'',selected).json()
            value['choices'][0]['message']['tool_calls'][0]['id']=f'{actor.task_id}-{step}'
            return httpx.Response(200,json=value)
        client._transport=httpx.MockTransport(transport);client._mounts.clear()
        models[role]=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result=await run_report(ws,factory)
        assert result['last_error'] is None,result
        records=cs.list_objects('ReviewRecord');assert len(records)==len(reviewed)==2
        assert {r['payload']['items'][0]['criterion_ref']['id'] for r in records}=={r['id'] for r in criteria[:2]}
        assert len({r['payload']['items'][0]['scope_id'] for r in records})==2
        for record in records:
            saved=record['payload']['items'][0];assigned=reviewed[record['task_id']]
            for field in IDENTITY:assert saved[field]==assigned[field]
            assert record['owner_id']=='content:reviewer:'+record['task_id']
            assert saved['verdict'] is None and saved['execution_state']=='running'
        assert {role for role,_ in wires}=={'coordinator','reviewer'}
        assert len([body for role,body in wires if role=='reviewer'])==6
    finally:
        for model in models.values():
            await model.root_async_client.close();model.root_client.close()
