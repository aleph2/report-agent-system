"""Actual native material/producer/adoption path; no paid or semantic acceptance."""
import hashlib
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.content_models import Evidence
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.source_materials import issue, verify
from report_agent.store import digest, encode
from report_agent.task_context import save_observation, TaskContext
from report_agent.text_work import material_identity, prepare_material, produce, adopt
from test_task_supervision import ws, offline
from test_hierarchical_content import seed
from test_text_work import writer_call, tools, content
from test_bounded_review import Model
from test_deep_runtime import Driver, invoke, observation


def setup(ws):
    cs,_,_,_,refs=seed(ws)
    return cs,next(r for r in refs if r['type']=='SourceArtifact')


def payload(source):
    return {'source_refs':[source],'locator':'s / selected block 0',
            'excerpt':'Class B permits 75 to 100.'}


@pytest.mark.parametrize('route',['source_selection','owned_observation'])
async def test_native_explicit_binding_produces_and_adopts_actual_evidence(ws,route):
    cs,source=setup(ws)
    manifest=ws.store.manifest
    manifest['decision_data_policy']='reference-data-v1'
    ws.store.set('manifest',manifest)
    ws.store.set('context_policy','stateful-tools-v1')
    refs_seen=[]
    def request(messages):
        result=observation(messages,'read_source_page')
        message=next(m for m in reversed(messages) if isinstance(m,ToolMessage) and m.name=='read_source_page')
        assert message.artifact['source_material']==result['source_material']
        assert result['source_material']['source_version_refs']==[source]
        stored=ws.store.get('tool_observation:'+result['observation_ref'])
        assert stored['sha256']==hashlib.sha256(stored['text'].encode()).hexdigest()
        refs_seen.append(result['observation_ref'])
        return invoke('process_report_content',operation_id='bound-work',objective='Preserve the selected rule as evidence',
            object_type='Evidence',source_version_refs=[source],
            **({'source_selections':[{'source_id':'s','offset':0,'limit':1}]} if route=='source_selection'
               else {'observation_refs':[result['observation_ref']]}))
    def save(messages):
        result=observation(messages,'process_report_content')['metadata']
        return invoke('commit_objects',operation_id='bound-save',objects=[{
            'client_key':'rule','type':'Evidence','text_work_id':result['text_work_id']}])
    def done(messages):
        saved=observation(messages,'commit_objects')
        obj=cs.read(saved['result']['refs']['rule'])
        assert obj['payload']==Evidence.model_validate(payload(source)).model_dump()
        return AIMessage(content='Saved scoped evidence; no report acceptance.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Done.')],
        writer=[invoke('read_source_page',source_id='s',offset=0,limit=1),request,save,done],
        text_tool=[AIMessage(content=json.dumps(payload(source)))])
    result=await run_report(ws,driver)
    assert result['last_error'] is None and refs_seen
    producer=[messages for role,_,messages in driver.calls if role=='text_tool']
    assert len(producer)==1
    packet=json.loads(producer[0][-1].content)
    binding=next(e for e in packet['evidence'] if e['kind']=='source_version_binding')
    assert binding['object']['ref']==source and 'content' not in binding['object']['payload']
    assert any('Class B permits' in encode(e) for e in packet['evidence'] if e['kind']!='source_version_binding')
    for batch in driver.bindings['writer']:
        tool=next(t for t in batch if t['name']=='process_report_content')
        assert 'source_version_refs' in tool['parameters']['properties']
        assert 'SourceArtifact' in encode(tool)


async def test_empty_pool_and_objective_uuid_fail_before_reservation_or_provider(ws):
    _,source=setup(ws)
    model=Model(json.dumps(payload(source)))
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        with pytest.raises(ActionRejected,match='SOURCE_POOL_EMPTY'):
            await produce(ws,actor,model,'impossible','Use '+source['id'],'Evidence',
                          source_selections=[{'source_id':'s'}])
        assert not model.calls
        assert ws.store.get('text_work:'+actor.id+':impossible') is None


async def test_empty_pool_native_tool_observation_precedes_text_service(ws):
    _,source=setup(ws)
    def check(messages):
        failure=observation(messages,'process_report_content')
        assert failure['code']=='TEXT_WORK_EVIDENCE_SOURCE_POOL_EMPTY'
        return AIMessage(content='No legal source reference supplied; no producer was called.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Done.')],
        writer=[invoke('process_report_content',operation_id='no-pool',objective='Use '+source['id'],
            object_type='Evidence',source_selections=[{'source_id':'s'}]),check])
    result=await run_report(ws,driver)
    assert result['last_error'] is None and not any(role=='text_tool' for role,_,_ in driver.calls)


async def test_new_version_metadata_does_not_release_unknown_material(ws):
    _,source=setup(ws)
    model=Model(RuntimeError('synthetic unknown'))
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        with pytest.raises(RuntimeError,match='synthetic unknown'):
            await produce(ws,actor,model,'unknown','Describe source','ContentNode',source_selections=[{'source_id':'s'}])
        with pytest.raises(ActionRejected,match='SAME_EVIDENCE_OUTCOME_UNRESOLVED'):
            await produce(ws,actor,model,'new-metadata','Describe source','ContentNode',
                source_selections=[{'source_id':'s'}],source_version_refs=[source])
        assert len(model.calls)==1


@pytest.mark.parametrize('damage',['owner','sha','range','source_version'])
async def test_origin_receipt_cannot_be_forged_or_rebound(ws,damage):
    cs,source=setup(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        text=json.dumps({'source_id':'s','text':'Class B permits 75 to 100.'})
        meta=issue(ws,actor,'read_source_page',text,[{'source_id':'s','kind':'synthetic_origin',
            'selection':{'units':'Unicode characters','range':[0,25]},'coverage':{'complete_source':False}}])
        if damage=='owner':
            from report_agent.content_store import Actor
            with pytest.raises(ActionForbidden):
                verify(ws,Actor('other','writer','other-task'),meta['receipt'],text,'read_source_page')
        elif damage in {'sha','range'}:
            record=ws.store.get('source_material:'+meta['receipt'])
            if damage=='sha': record['public_sha256']='0'*64
            else: record['materials'][0]['selection']['range']=[0,99999]
            ws.store.set('source_material:'+meta['receipt'],record)
            with pytest.raises(ActionRejected,match='RECEIPT_INVALID'):
                prepare_material(ws,[],[],[meta['body_ref']],actor,source_version_refs=[source])
        else:
            manifest=ws.store.manifest
            manifest['sources'][0]['content']='Changed source fact'
            ws.store.set('manifest',manifest)
            with pytest.raises(ActionRejected,match='VERSION_NOT_CURRENT'):
                prepare_material(ws,[],[],[meta['body_ref']],actor,source_version_refs=[source])


def test_arbitrary_artifact_is_not_a_source_receipt(ws):
    setup(ws)
    with delegated_task(ws,'coordinator',writer_call()):
        message=ToolMessage('public',name='read_source_page',tool_call_id='fake',
            artifact={'source_material':{'receipt':'unissued'}})
        with pytest.raises(ActionRejected,match='RECEIPT_INVALID'):
            save_observation(ws,'writer',message)


async def test_no_match_receipt_cannot_bind_searched_but_unread_source(ws):
    _,source=setup(ws)
    from types import SimpleNamespace
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        t=tools(ws,'writer',Model())
        returned=t['search_sources']('not present',runtime=SimpleNamespace(tool_call_id='search'))
        assert returned.artifact['source_material']['source_ids']==[]
        ref,_=save_observation(ws,'writer',returned)
        with pytest.raises(ActionRejected,match='REQUIRES_MATCHING_MATERIAL'):
            prepare_material(ws,[],[],[ref],actor,source_version_refs=[source])


async def test_legacy_observation_route_is_explicit_and_unchanged_success_reuses(ws):
    _,source=setup(ws)
    model=Model(json.dumps(payload(source)))
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        t=tools(ws,'writer',model)
        original=t['read_source_page']('s',0,1)  # Historical public shape, no native artifact.
        message=ToolMessage(json.dumps(original,ensure_ascii=False),name='read_source_page',tool_call_id='old')
        ref,_=save_observation(ws,'writer',message)
        assert ws.store.get('source_material_observation:'+ref) is None
        work=await produce(ws,actor,model,'legacy','Retain rule','Evidence',observation_refs=[ref],source_version_refs=[source])
        packet=json.loads(model.calls[0][1][1])
        binding=packet['evidence'][-1]
        assert binding['material_kinds']==['legacy-source-return-shapes-v1:read_source_page']
        assert adopt(ws,actor,work['text_work_id'],'Evidence')==Evidence.model_validate(payload(source)).model_dump()
        assert (await produce(ws,actor,model,'legacy','Retain rule','Evidence',observation_refs=[ref],source_version_refs=[source]))['reused']
        assert len(model.calls)==1


async def test_different_valid_source_outside_prepared_pool_is_rejected(ws):
    cs,source=setup(ws)
    from report_agent.hierarchical_tools import actor_for
    different=cs.capture_sources(actor_for('coordinator'),'other-version',['s'])['result']['source_refs'][0]
    model=Model(json.dumps(payload(different)))
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        with pytest.raises(ActionRejected,match='UNSUPPLIED_REFERENCE'):
            await produce(ws,actor,model,'bad-ref','Retain rule','Evidence',
                source_selections=[{'source_id':'s'}],source_version_refs=[source])
        state=ws.store.get('text_work:'+actor.id+':bad-ref')
        assert state['state']=='known_failed' and len(model.calls)==1
