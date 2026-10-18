"""Scoped semantic changes retain real node identity and untouched body bytes."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_store import ContentStore, Actor
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.text_work_candidates import candidate_evidence
from report_agent.text_work import QUALIFIER_WORK_PROMPT, TEXT_WORK_PROMPT
from test_bounded_review import Model
from test_deep_runtime import Driver, invoke, observation
from test_task_supervision import ws, offline
from test_text_work import tools, writer_call


TABLE = {'kind':'table', 'body':{'title':'Assessment', 'columns':['Type','Score'],
         'rows':[['Unresolved condition','Not assigned'],['Total','Not established']]},
         'claim_kind':'inference', 'qualifiers':{'technical':'Weathering class not established',
                                             'process':'Old parser note'}}
DELTA = {'qualifiers':{'technical':'Weathering class remains unverified against the original geological description.'}}


def save_fixture(ws, actor, key='base'):
    cs = ContentStore(ws.store)
    return cs.commit(actor, key, [{'client_key':'node', 'type':'ContentNode', 'payload':TABLE}])['result']['refs']['node']


def revision(ref):
    return {'scope':'qualifiers', 'targets':[ref]}


async def test_native_produce_adopt_then_exact_qualifier_revision_preserves_body(ws):
    class Service(Model):
        async def ainvoke(self, messages):
            self.response = json.dumps(TABLE if not self.calls else DELTA)
            return await super().ainvoke(messages)
    service = Service()
    held = {}
    def adopt_base(messages):
        return invoke('save_text_node', operation_id='base', text_work_id=observation(messages,'process_report_content')['text_work_id'])
    def revise(messages):
        held['base'] = observation(messages,'save_text_node')['result']['refs']['text']
        return invoke('process_report_content', operation_id='qualifiers', objective='Retain technical uncertainty and remove process commentary',
            object_type='ContentNode', source_selections=[{'source_id':'s'}], revision=revision(held['base']))
    def adopt_revision(messages):
        result = observation(messages,'process_report_content')
        held['work'] = result
        assert result['payload']['body']==TABLE['body']
        assert result['payload']['qualifiers']==DELTA['qualifiers']
        return invoke('save_text_node', operation_id='revise-node', text_work_id=result['text_work_id'], previous_ref=held['base'])
    driver = Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Done.')],
        writer=[invoke('process_report_content',operation_id='write',objective='Describe evidence',object_type='ContentNode',source_selections=[{'source_id':'s'}]),
                adopt_base, revise, adopt_revision, AIMessage(content='Saved scoped draft; not acceptance.')])
    result = await run_report(ws, lambda role: service if role=='text_tool' else driver(role))
    assert result['last_error'] is None, result
    nodes = ContentStore(ws.store).list_objects('ContentNode')
    assert len(nodes)==2
    assert nodes[0]['payload']==TABLE
    assert nodes[1]['ref']=={**held['base'],'version':2}
    assert nodes[1]['payload']=={**TABLE,**DELTA}
    packet = json.loads(service.calls[1][1][1])
    assert service.calls[0][0][1]==TEXT_WORK_PROMPT
    assert service.calls[1][0][1]==QUALIFIER_WORK_PROMPT
    assert 'complete body, qualifiers and claim_kind together' not in QUALIFIER_WORK_PROMPT
    for shape in packet['output_schema']['oneOf']:
        assert 'body' not in shape.get('properties',{})
    actor = Actor(nodes[1]['owner_id'],'writer',nodes[1]['task_id'])
    candidate = candidate_evidence(ws,actor,{'text_work_id':held['work']['text_work_id']})
    assert candidate['payload']=={**TABLE,**DELTA}
    assert held['base'] in candidate['ancestor_substantive_refs']
    binding = next(b for b in driver.bindings['writer'][0] if b['name']=='process_report_content')
    assert 'revision' in binding['parameters']['properties']


@pytest.mark.parametrize('misuse', ['missing_qualifiers','body_in_output','missing_previous','wrong_target','wrong_owner','stale_target','count','duplicate','authority'])
async def test_revision_boundary_rejects_wrong_shape_identity_or_authority(ws, misuse):
    model = Model(json.dumps({} if misuse=='missing_qualifiers' else {**DELTA,'body':{'text':'rewrite'}} if misuse=='body_in_output' else DELTA))
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        ref = save_fixture(ws,actor)
        other = save_fixture(ws,actor,'other')
        t=tools(ws,'writer',model)
        spec=revision(ref)
        if misuse=='wrong_owner':
            ref=save_fixture(ws,Actor('another','writer','other-task'),'foreign')
            spec=revision(ref)
        elif misuse=='stale_target':
            ContentStore(ws.store).commit(actor,'advance',[{'client_key':'node','type':'ContentNode','payload':TABLE,'previous_ref':ref}])
        elif misuse=='count':
            spec['targets'].append(other)
        elif misuse=='duplicate':
            spec['targets'].append(ref)
        if misuse in {'wrong_owner','stale_target','count','duplicate','body_in_output','missing_qualifiers'}:
            with pytest.raises((ActionRejected,ActionForbidden)):
                await t['process_report_content']('revise','Revise qualifications','ContentNode',
                    output_count=2 if misuse=='duplicate' else 1, revision=spec)
            assert len(model.calls)==(1 if misuse in {'body_in_output','missing_qualifiers'} else 0)
            assert ContentStore(ws.store).read(ref)['payload']==TABLE
            return
        work=await t['process_report_content']('revise','Revise qualifications','ContentNode',revision=spec)
        if misuse=='authority':
            manifest=ws.store.manifest
            ws.store.set('manifest',{**manifest,'scope_instruction':'Different scope'})
        with pytest.raises(ActionRejected,match='EXACT_PREVIOUS_REF|INPUT_OR_AUTHORITY_CHANGED'):
            t['save_text_node']('bad-adopt',work['text_work_id'], previous_ref=(None if misuse=='missing_previous' else other if misuse=='wrong_target' else ref))
        assert ContentStore(ws.store).read(ref)['payload']==TABLE


async def test_revision_includes_target_in_unknown_association_without_explicit_input_refs(ws):
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        ref=save_fixture(ws,actor)
        model=Model(RuntimeError('synthetic unresolved call'))
        t=tools(ws,'writer',model)
        with pytest.raises(RuntimeError):
            await t['process_report_content']('old','Review whole draft','ContentNode',input_refs=[ref])
        model.response=json.dumps(DELTA)
        with pytest.raises(ActionRejected,match='OUTCOME_UNRESOLVED'):
            await t['process_report_content']('new','Revise qualifiers only','ContentNode',revision=revision(ref))
        assert len(model.calls)==1


async def test_revision_replay_after_adoption_preserves_receipt_and_cannot_create_new_node(ws):
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        ref=save_fixture(ws,actor)
        model=Model(json.dumps(DELTA))
        t=tools(ws,'writer',model)
        args=dict(operation_id='revise',objective='Revise qualifiers',object_type='ContentNode',revision=revision(ref))
        work=await t['process_report_content'](**args)
        saved=t['save_text_node']('adopt',work['text_work_id'],previous_ref=ref)
        reused=await t['process_report_content'](**args)
        assert reused['reused'] and reused['text_work_id']==work['text_work_id'] and len(model.calls)==1
        assert t['save_text_node']('adopt',work['text_work_id'],previous_ref=ref)==saved
        with pytest.raises(ActionRejected,match='EXACT_PREVIOUS_REF'):
            t['save_text_node']('new-node',work['text_work_id'])
