"""Offline five-object acceptance; synthetic judgments test the system, not engineering facts."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.commission_imports import install_source_roles
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.method_pack import register_reviewed_method_pack
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from report_agent.writer_assessment import read_indicator_step
from report_agent.writer_runtime import writer_session
from support.judgment_inputs import install_test_judgment_inputs
from test_deep_runtime import Driver, call
from test_ingestion import pdf_bytes
from test_m1_commission_plan import save, approve
from test_m1_g3_method_pack import pack_data


WEIGHTS = ['0.20','0.15','0.12','0.10','0.09','0.08','0.07','0.06','0.05','0.04','0.04']


@pytest.fixture
def five(tmp_path, monkeypatch, request):
    def forbidden(*args, **kwargs):
        raise AssertionError('No network is permitted in five-slope acceptance tests')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    texts = {'scope':'Assess S1 S2 S3 S4 S5. Use synthetic eleven-indicator rank weights.',
        'outline':'Section 4 assesses each commissioned slope. Section 5 summarizes section 4.',
        'guideline':'Synthetic eleven-indicator method and explicit rank-weight row for acceptance tests.',
        'design':' '.join(f'Slope {i} has synthetic evidence.' for i in range(1,6))}
    ranked = getattr(request, 'param', None) in {'with-owner-ranks','sensitivity'}
    ids = [f'I{i:02d}' for i in range(1,12)]
    rank_quote = 'Owner rank order: ' + ', '.join(ids) + '.'
    if ranked:
        texts['scope'] += ' ' + rank_quote
    store = Store(tmp_path)
    store.initialize({'goal':texts['scope'],'content_contract':'hierarchical-review-v1',
        'commission_checkpoint_required':True,'coverage_contract':'object-coverage-v1',
        'sources':[{'id':name,'title':name,'content':text,'coverage':'complete'} for name,text in texts.items() if name != 'design']})
    ws, co = Workspace(store), actor_for('coordinator'); cs = ContentStore(store)
    pdf_id = Catalog(store).import_file('design.pdf', pdf_bytes([texts['design']]))['source']['id']
    imported = cs.import_inputs(co,'five-inputs',[pdf_id if name=='design' else name for name in texts])['result']['source_refs']
    sources = {cs.read(ref)['payload']['source_id']:ref for ref in imported}
    sources['design'] = sources.pop(pdf_id)
    def cite(name):return {'source_ref':sources[name],'locator':'page 1' if name=='design' else 'manifest text','quote':texts[name]}
    pack = pack_data(); pack['method_id']='synthetic-eleven-five-slope-acceptance'
    prototype = deepcopy(pack['indicators'][0])
    pack['indicators']=[{**deepcopy(prototype),'id':f'I{i:02d}','label':f'Synthetic indicator {i:02d}'} for i in range(1,12)]
    pack['sources']=[cite('guideline')]
    pack['weight_tables']=[{'id':'rank-lookup','source':cite('guideline'),
        'rows':[{'indicator_count':11,'weights':WEIGHTS}]}]
    register_reviewed_method_pack(store,pack,'Hand-derived synthetic acceptance oracle; no engineering judgments claimed.')
    install_source_roles(store, {name:{'id':pdf_id if name == 'design' else name,'purpose':'commission' if name=='scope' else 'source_or_applicable_standard'} for name in texts})
    plan = {'sections':[{'section_id':'4','title':'Assessment','kind':'extracted','outline':cite('outline'),'sources':[cite('design')]},
        {'section_id':'5','title':'Conclusion','kind':'derived','outline':cite('outline'),'sources':[cite('design')],
            'derived_from':['4'],'rule':'Summarize section 4 canonical assessments.'}],
        'inventory_attributes':['height'],
        'objects':[{'object_id':f'S{i}','label':f'Slope {i}','included':True,'reason':'Synthetic commissioned object.',
            'origin':'customer','attributes':[{'name':'height','values':[{'value':'30 m','source':cite('design'),'reason':'Synthetic fact.'}]}],
            'sources':[cite('design'),cite('scope')]} for i in range(1,6)],
        'conventions':[{'source':cite('scope'),'interpretation':'Use the explicitly supplied eleven-item rank weights.'}],
        'deliverables':['Word','Excel'],'reconciliations':[{'sources':[cite('design'),cite('scope')],
            'result':'Five synthetic objects retained.','differences':[]}],'open_questions':[],
        'method_pack':pack,'method_conventions':[{'key':'weights','source':cite('scope'),'interpretation':'Use n=11 rank row exactly.',
            'status':'specified','method_id':pack['method_id'],'strategy_id':'rank-lookup'}]}
    if ranked:
        plan['indicator_rank_order'] = {'indicator_ids':ids,
            'source':{**cite('scope'),'quote':rank_quote}}
    f=SimpleNamespace(ws=ws,cs=cs,co=co,plan=plan,sources=sources)
    saved=save(f);approve(f,saved);f.plan_ref=saved['plan_ref']
    store.set('manifest',{**store.manifest,'assembly_contract':'system-assembler-v1'})
    if ranked:
        last = pack['indicators'][-1]
        classifications = {rule['id']:rule['grades'][1]['id'] for rule in pack['indicators']}
        if request.param=='sensitivity':
            classifications[last['id']] = last['grades'][3]['id']
        for i in range(1,6):
            install_test_judgment_inputs(f, f'S{i}', pdf_id, 1, f'Slope {i} has synthetic evidence.',
                                         classifications=classifications)
    return f


def action(name, identity, **args):
    return AIMessage(content='',tool_calls=[call(name,args,identity)])


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


@pytest.mark.asyncio
@pytest.mark.parametrize('five',['sensitivity'],indirect=True)
async def test_five_native_writers_complete_eleven_durable_rows_without_cross_scope_or_replacement(five):
    f=five; captures=[]; task_ids=[]; refs=[]
    for slope in range(1,6):
        def choose(messages):
            packet=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
            rank=packet['rank']
            prior=next((m for m in reversed(messages) if isinstance(m,ToolMessage)),None)
            if prior and rank!=11:
                raise AssertionError(str(prior.content))
            grades=[g['choice'] for g in packet['grades']]
            data={'grade':grades[1], 'value':'40', 'rationale':f'ONLY_SLOPE_{slope}_PRIVATE_END',
                  'quotes':[f'Slope {slope} has synthetic evidence.']}
            name='save_evidence'
            if rank in (1,11):
                name='save_assumption'
                data.update(question='Confirm the applicable synthetic grade.',
                            plausible_grades=[grades[0],grades[1],grades[3]])
                if rank==11:
                    data.update(value='100',grade=grades[3])
            else:
                data['basis_kind']='direct_evidence'
            tag='valid'
            if rank==11:
                if not any(isinstance(m,ToolMessage) for m in messages):
                    data['value']='1000'; tag='invalid'
                else:
                    assert next(m for m in reversed(messages) if isinstance(m,ToolMessage)).status=='error'
                    assert read_indicator_step(f.cs,session.actor)['progress']['recorded']==10
            return action(name,f'slope-{slope}-row-{rank}-{tag}',**data)

        driver=Driver(writer=[choose,choose])
        with writer_session(f.ws,f'Slope {slope}',driver('writer'),assessment_only=True,indicator_steps=True) as session:
            receipt=await session.run()
            assert receipt['progress']=={'recorded':11,'total':11} and not receipt['interrupted_indicators']
            assert len(driver.calls)==12
            task_ids.append(session.actor.task_id)
            task=f.cs.read({'type':'DelegatedTask','id':session.actor.task_id,'version':1})['payload']
            assert task['assessment_object_id']==f'S{slope}' and task['section_ids']==['4']
            saved=f.cs.read(receipt['assessment_ref']);refs.append(receipt['assessment_ref'])
            assert saved['owner_id']==session.actor.id and saved['task_id']==session.actor.task_id
            assert saved['payload']['object_id']==f'S{slope}' and saved['payload']['commission_plan_ref']==f.plan_ref
            assert saved['payload']['method_id']==f.plan['method_pack']['method_id']
            rows=saved['payload']['indicators']; assert [r['indicator_id'] for r in rows]==[f'I{i:02d}' for i in range(1,12)]
            outcome=saved['payload']['result']
            assert [Decimal(outcome[mode]['total']) for mode in ['adopted','low','high']]==[Decimal('42.4'),Decimal('30.4'),Decimal('54.4')]
            assert [outcome[mode]['level'] for mode in ['adopted','low','high']]==['II','II','III']
            assert outcome['affects_level'] is True
            assert [Decimal(r['weight']) for r in outcome['rows']]==list(map(Decimal,WEIGHTS))
            first=driver.calls[0][2]
            assert not any(isinstance(m,(AIMessage,ToolMessage)) for m in first)
            assert not any(f'ONLY_SLOPE_{other}_PRIVATE_END' in str(m.content) for other in range(1,slope) for m in first)
            schemas=driver.bindings['writer'][0]
            for schema in schemas:
                assert not {'operation_id','object_id','section_id','method_id','indicator_id','source_ref','locator'} & schema['parameters'].get('properties',{}).keys()
            messages_json=[m.model_dump(mode='json') for m in first]
            payload=encoded({'messages':messages_json,'tools':schemas})
            assert len(payload)<60000
            loaded=encoded({'messages':[m.model_dump(mode='json') for m in driver.calls[1][2]], 'tools':schemas})
            assert len(loaded)<60000
            captures.append({'slope':slope,'task_id':session.actor.task_id,'first_request':json.loads(payload),
                'serialized_bytes':len(payload),'messages_bytes':len(encoded(messages_json)),'tool_schemas_bytes':len(encoded(schemas)),
                'sha256':hashlib.sha256(payload).hexdigest(),'assignment_loaded_bytes':len(loaded),
                'token_estimate':{'available':False,'reason':'Exact byte measurements only; no tokenizer downloads in offline tests.'},
                'native_fake_requests':len(driver.calls),'draft_rows':11,'invalid_row_preserved_prior_rows':True,
                'canonical_ref':receipt['assessment_ref'],'total':'42.4','low':'30.4','high':'54.4','levels':['II','II','III']})
            foreign={key:deepcopy(saved['payload'][key]) for key in ('object_id','section_id','method_id','method_version','weight_strategy_id','indicators')}
            from report_agent.risk_scoring import save_assessment
            with pytest.raises(ActionRejected, match='ASSESSMENT_NATIVE_INPUTS_REQUIRED'):
                save_assessment(f.cs, session.actor, f'raw-over-native-{slope}', foreign)
            foreign['object_id']=f'S{(slope%5)+1}'
            with pytest.raises(ActionRejected,match='ASSESSMENT_OBJECT_OUTSIDE_WRITER_ASSIGNMENT'):
                save_assessment(f.cs,session.actor,f'cross-slope-{slope}',foreign)
    assert len(set(task_ids))==5 and len(f.cs.list_objects('Assessment'))==5
    # A fresh producer may draft, but cannot overwrite another producer's selected canonical result.
    original=deepcopy(f.cs.read(refs[0]))
    with writer_session(f.ws,'Slope 1',Driver(writer=[])('writer'),assessment_only=True,indicator_steps=True) as replacement:
        from report_agent.risk_scoring import save_assessment
        original_input={key:deepcopy(original['payload'][key]) for key in
                        ('object_id','section_id','method_id','method_version','weight_strategy_id','indicators')}
        with pytest.raises(ActionForbidden,match='assessment producer ownership'):
            save_assessment(f.cs,replacement.actor,'replace-other-producer',original_input)
    assert f.cs.read(refs[0])==original
    from report_agent.assessment_projection import selected_assessment
    with f.ws.store.connect() as db:
        assert selected_assessment(db, f.plan_ref, 'S1') == refs[0]
    assert len(f.cs.list_objects('Assessment'))==5
    if destination:=os.environ.get('W1_FIVE_EVIDENCE'):
        Path(destination).write_text(json.dumps({'offline':True,'synthetic':True,'network_denied':True,
            'five_completed_tasks':task_ids,'canonical_assessments':refs,'captures':captures,
            'replacement_attempt':'refused; canonical producer unchanged','cross_slope_writes':'all five refused'},
            ensure_ascii=False,indent=2)+'\n')
