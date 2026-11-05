"""One assigned Writer supplies judgments; the system owns identities and incremental state."""
from copy import deepcopy
import importlib

import pytest
from pydantic import ValidationError

from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission, persistence_input


@pytest.fixture
def api():
    return importlib.import_module('report_agent.writer_assessment')


@pytest.fixture
def assigned(method_commission):
    f=method_commission
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    saved=save(f);approve(f,saved)
    prior=writer(f,saved,section_ids=['4'])
    payload=deepcopy(f.cs.read({'type':'DelegatedTask','id':prior.task_id,'version':1})['payload'])
    payload['assessment_object_id']='S1'
    def register(db):return f.cs._insert(db,f.co,'DelegatedTask',payload)
    task=f.cs.operation(f.co,'host-assessment-assignment',{},register)['result']
    f.actor=Actor('content:writer:'+task['id'],'writer',task['id'])
    f.plan_ref=saved['plan_ref']
    return f


def input_row(f,api,index=0):
    original=persistence_input(f)['indicators'][index]
    rule=f.plan['method_pack']['indicators'][index]
    offered=api.read_assignment(f.cs,f.actor)['indicators'][index]
    def choice(grade_id):
        grade=next(g for g in rule['grades'] if g['id']==grade_id)
        return next(g['choice'] for g in offered['grades'] if g['min_value']==grade['min_value'] and g['max_value']==grade['max_value'])
    return {'indicator':offered['indicator'],'grade':choice(original['grade_id']),'rank':original['rank'],
        'value':original['value'],'basis_kind':original['basis_kind'],'rationale':original['rationale'],
        'rank_reason':original['rank_reason'],'quotes':[citation['quote'] for citation in original['sources']],
        'question':original['question'],'plausible_grades':[choice(g) for g in original['plausible_grades']]}


def test_public_schema_uses_offered_labels_and_has_no_system_identity_fields(assigned,api):
    f=assigned;packet=api.read_assignment(f.cs,f.actor);model=api.indicator_schema(f.cs,f.actor)
    assert packet['object_label']=='Slope 1' and len(packet['indicators'])==4
    assert model is api.indicator_schema(f.cs,f.actor)
    fields=set(model.model_json_schema()['properties'])
    assert {'indicator','grade','rank','value','quotes','visual_pages','rationale','rank_reason'} <= fields
    assert not fields & {'operation_id','object_id','section_id','plan_ref','method_id','method_version','weight_strategy_id','indicator_id','grade_id','source_ref','locator'}
    valid=input_row(f,api);model.model_validate(valid)
    with pytest.raises(ValidationError):model.model_validate({**valid,'indicator':'A'})
    with pytest.raises(ValidationError):model.model_validate({**valid,'grade':'g2'})


@pytest.mark.parametrize('forbidden',['operation_id','object_id','section_id','plan_ref','method_id','source_ref','locator'])
def test_writer_cannot_supply_system_bindings(assigned,api,forbidden):
    f=assigned;row=input_row(f,api)
    with pytest.raises((ValidationError,ActionRejected)):
        api.set_indicator(f.cs,f.actor,'invalid-'+forbidden,{**row,forbidden:'forged'})
    assert api.read_assignment(f.cs,f.actor)['draft']==[]


def test_valid_row_is_durable_and_invalid_next_row_cannot_erase_it(assigned,api):
    f=assigned;first=input_row(f,api)
    api.set_indicator(f.cs,f.actor,'first-indicator',first)
    before=deepcopy(api.read_assignment(f.cs,f.actor)['draft'])
    second=input_row(f,api,1);second['value']='1000'
    with pytest.raises((ValidationError,ActionRejected)):
        api.set_indicator(f.cs,f.actor,'invalid-second',second)
    assert api.read_assignment(f.cs,f.actor)['draft']==before
    assert len(before)==1 and before[0]['indicator']=='Indicator A'
    assert f.cs.list_objects('Assessment')==[]


def test_missing_rows_and_rank_collisions_are_reported_without_synthesizing_rows(assigned,api,monkeypatch):
    from report_agent import risk_scoring
    f=assigned;first=input_row(f,api);second=input_row(f,api,1);second['rank']=first['rank']
    api.set_indicator(f.cs,f.actor,'save-a',first);api.set_indicator(f.cs,f.actor,'save-b',second)
    def forbidden(*args,**kwargs):raise AssertionError('Incomplete draft reached canonical scoring')
    monkeypatch.setattr(risk_scoring,'save_assessment_in_transaction',forbidden,raising=False)
    result=api.submit_assessment(f.cs,f.actor,'incomplete-submit')['result']
    assert result['accepted'] is False
    assert result['missing_indicators']==['Indicator C','Indicator D']
    assert result['rank_collisions']==[{'rank':first['rank'],'indicators':['Indicator A','Indicator B']}]
    assert len(api.read_assignment(f.cs,f.actor)['draft'])==2
    assert f.cs.list_objects('Assessment')==[]


def test_complete_submission_binds_canonical_method_object_and_source_locations(assigned,api):
    f=assigned
    for i in range(4):api.set_indicator(f.cs,f.actor,'indicator-'+str(i),input_row(f,api,i))
    result=api.submit_assessment(f.cs,f.actor,'complete-submit')['result']
    saved=f.cs.read(result['assessment_ref'])
    assert saved['owner_id']==f.actor.id
    assert saved['payload']['object_id']=='S1' and saved['payload']['section_id']=='4'
    assert saved['payload']['commission_plan_ref']==f.plan_ref
    assert saved['payload']['method_id']==f.plan['method_pack']['method_id']
    assert saved['payload']['method_version']==f.plan['method_pack']['version']
    assert saved['payload']['weight_strategy_id']=='rank-lookup'
    assert saved['payload']['result']['adopted']['total']=='43.5'
    for row in saved['payload']['indicators']:
        for citation in row['sources']:
            source=f.cs.read(citation['source_ref'])['payload']
            with f.ws.store.connect() as db:
                texts=[text for loc,text in db.execute('SELECT locator,text FROM source_blocks WHERE source_id=?',(source['source_id'],))
                    if loc==citation['locator'] or loc.startswith(citation['locator']+';')]
            assert citation['quote'] and citation['quote'] in ''.join(texts)
    assert api.submit_assessment(f.cs,f.actor,'complete-submit')['result']==result


@pytest.mark.parametrize('quote,code',[('S1','QUOTE_AMBIGUOUS'),('not present in an authorized source','QUOTE_NOT_FOUND')])
def test_ambiguous_or_absent_quote_cannot_be_bound_to_an_arbitrary_page(assigned,api,quote,code):
    f=assigned;row=input_row(f,api);row['quotes']=[quote]
    with pytest.raises(ActionRejected,match=code):api.set_indicator(f.cs,f.actor,'bad-quote',row)
    assert api.read_assignment(f.cs,f.actor)['draft']==[]


def test_grade_value_and_assumption_rules_are_shared_with_canonical_validation(assigned,api):
    f=assigned;row=input_row(f,api,2)
    row['plausible_grades']=[]
    with pytest.raises(ActionRejected):api.set_indicator(f.cs,f.actor,'bad-assumption',row)
    valid=input_row(f,api,3);api.set_indicator(f.cs,f.actor,'valid-assumption',valid)
    saved=api.read_assignment(f.cs,f.actor)['draft'][0]
    assert saved['indicator']=='Indicator D'
    assert saved['low']=='0' and saved['high']=='100'


@pytest.mark.parametrize('foreign',['wrong_actor_id','coordinator','different_task'])
def test_draft_is_not_readable_or_writable_as_a_foreign_actor(assigned,api,foreign):
    f=assigned
    other=(Actor('content:writer:forged','writer',f.actor.task_id) if foreign=='wrong_actor_id' else
        f.co if foreign=='coordinator' else writer(f,{'plan_ref':f.plan_ref},section_ids=['4'],operation='foreign-writer'))
    with pytest.raises((ActionForbidden,ActionRejected)):
        api.read_assignment(f.cs,other)
    valid=input_row(f,api)
    with pytest.raises((ActionForbidden,ActionRejected)):
        api.set_indicator(f.cs,other,'foreign-write',valid)


def test_plan_revision_makes_old_assignment_stale_without_importing_old_rows(assigned,api):
    f=assigned;row=input_row(f,api);api.set_indicator(f.cs,f.actor,'before-plan-revision',row)
    revised=deepcopy(f.plan);revised['objects'][0]['reason']='Reconfirmed scope in a new plan version.'
    saved=save(f,revised,operation='revised-plan');approve(f,saved)
    with pytest.raises((ActionForbidden,ActionRejected)):
        api.read_assignment(f.cs,f.actor)
    with pytest.raises((ActionForbidden,ActionRejected)):
        api.set_indicator(f.cs,f.actor,'before-plan-revision',row)


def test_edit_clears_only_own_canonical_selection_and_preserves_saved_records(assigned,api):
    f=assigned
    for i in range(4):api.set_indicator(f.cs,f.actor,'initial-'+str(i),input_row(f,api,i))
    result=api.submit_assessment(f.cs,f.actor,'initial-submit')['result'];ref=result['assessment_ref'];before=deepcopy(f.cs.read(ref))
    changed=input_row(f,api);changed['rank_reason']='Updated professional importance explanation from the same evidence.'
    api.set_indicator(f.cs,f.actor,'edit-one-indicator',changed)
    assert f.ws.store.get('g6_assessment:'+digest([f.plan_ref,'S1'])) is None
    assert f.cs.read(ref)==before


def test_visual_pages_must_use_host_resolution_and_do_not_accept_raw_refs(assigned,api,monkeypatch):
    from report_agent import writer_assignments
    f=assigned;row=input_row(f,api);row['quotes']=[];row['visual_pages']=['issued-page-handle'];called=[]
    def resolve(cs,db,actor,handles):
        called.append((actor.id,handles));return [{**f.cite('design'),'quote':''}]
    monkeypatch.setattr(writer_assignments,'resolve_visual_pages',resolve)
    api.set_indicator(f.cs,f.actor,'visual-row',row)
    assert called==[(f.actor.id,['issued-page-handle'])]
    assert api.read_assignment(f.cs,f.actor)['draft'][0]['visual_pages']==['issued-page-handle']



def test_tool_factory_reuses_the_backend_model_and_keeps_operation_identity_private(assigned,api):
    f=assigned
    tools={tool.__name__:tool for tool in api.tool_functions(f.cs,lambda:f.actor)}
    assert set(tools)=={'read_assignment','set_indicator','submit_assessment'}
    assert tools['set_indicator'].message_model is api.indicator_schema(f.cs,f.actor)
    assert 'operation_id' not in tools['set_indicator'].message_model.model_fields
    assert tools['submit_assessment'].message_model.model_fields=={}
    tools['set_indicator'](operation_id='server-injected-operation',**input_row(f,api))
    assert len(tools['read_assignment']()['draft'])==1


@pytest.mark.parametrize('mode',['missing_only','collision_only'])
def test_each_incomplete_condition_independently_prevents_canonical_submission(assigned,api,monkeypatch,mode):
    from report_agent import risk_scoring
    f=assigned
    for index in range(1 if mode=='missing_only' else 4):
        row=input_row(f,api,index)
        if mode=='collision_only' and index==1:row['rank']=input_row(f,api)['rank']
        api.set_indicator(f.cs,f.actor,'condition-'+str(index),row)
    def forbidden(*args,**kwargs):raise AssertionError('Incomplete draft reached canonical save')
    monkeypatch.setattr(risk_scoring,'save_assessment_in_transaction',forbidden)
    result=api.submit_assessment(f.cs,f.actor,'condition-submit')['result']
    assert result['accepted'] is False
    assert bool(result['missing_indicators'])==(mode=='missing_only')
    assert bool(result['rank_collisions'])==(mode=='collision_only')


def test_invalid_edit_preserves_existing_canonical_selection_and_every_draft_row(assigned,api):
    f=assigned
    for i in range(4):api.set_indicator(f.cs,f.actor,'complete-'+str(i),input_row(f,api,i))
    selected=api.submit_assessment(f.cs,f.actor,'complete-canonical')['result']['assessment_ref']
    before=deepcopy(api.read_assignment(f.cs,f.actor)['draft'])
    invalid=input_row(f,api);invalid['value']='NaN'
    with pytest.raises(ActionRejected):api.set_indicator(f.cs,f.actor,'invalid-replacement',invalid)
    assert api.read_assignment(f.cs,f.actor)['draft']==before
    assert f.ws.store.get('g6_assessment:'+digest([f.plan_ref,'S1']))==selected


def test_shared_quote_resolver_deduplicates_repeated_authorized_refs(assigned,api):
    from report_agent.writer_assignments import bound_assignment
    f=assigned
    with f.ws.store.connect() as db:
        context=bound_assignment(f.cs,db,f.actor)
        context['sources'] += list(context['sources'])
        result=api.resolve_judgment_sources(f.cs,db,f.actor,context,[f.cite('design')['quote']])
    assert len(result)==1 and result[0]['source_ref']==f.sources['design']


def test_native_identity_adapter_sees_exact_public_model_and_derives_server_operation(assigned,api):
    from report_agent.native_operation_tools import native_write_tools
    from report_agent import operation_identity
    from report_agent.content_tasks import delegated_task
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'operation_identity_profile':'native-tool-runtime-v1'})
    functions=api.tool_functions(f.cs,lambda:f.actor)
    # Main registers these business writes in the existing native identity mechanism.
    assert {'set_indicator','submit_assessment'} <= operation_identity.NATIVE_WRITES
    tools={tool.name:tool for tool in native_write_tools(f.ws,'writer',functions) if hasattr(tool,'name')}
    assert tools['set_indicator'].tool_call_schema is api.indicator_schema(f.cs,f.actor)
    assert 'operation_id' not in tools['set_indicator'].tool_call_schema.model_fields
    with delegated_task(f.ws,'coordinator',{'name':'task','id':'native-tool-assignment-context',
            'args':{'subagent_type':'writer','resume_content_task_id':f.actor.task_id,
                'description':'Continue the same host-assigned slope assessment.'}}) as (_,bound):
        assert bound==f.actor
        result=tools['set_indicator'].invoke({'name':'set_indicator','id':'native-indicator-call',
            'type':'tool_call','args':{**input_row(f,api),'operation_id':'untrusted-caller-operation'}})
    import json
    response=json.loads(result.content)
    assert response['operation_id']==operation_identity.write_id(f.actor.id,'set_indicator','native-indicator-call')
    assert len(api.read_assignment(f.cs,f.actor)['draft'])==1



def test_edit_never_invalidates_another_writers_canonical_selection(assigned,api):
    from report_agent.risk_scoring import save_assessment
    f=assigned
    payload=deepcopy(f.cs.read({'type':'DelegatedTask','id':f.actor.task_id,'version':1})['payload'])
    task=f.cs.operation(f.co,'host-other-assignment',{},lambda db:f.cs._insert(db,f.co,'DelegatedTask',payload))['result']
    other=Actor('content:writer:'+task['id'],'writer',task['id'])
    foreign=save_assessment(f.cs,other,'other-writer-canonical',persistence_input(f))['result']['assessment_ref']
    original=deepcopy(f.cs.read(foreign))
    api.set_indicator(f.cs,f.actor,'own-draft-row',input_row(f,api))
    assert f.ws.store.get('g6_assessment:'+digest([f.plan_ref,'S1']))==foreign
    assert f.cs.read(foreign)==original


def test_duplicate_display_labels_are_rejected_before_a_writer_schema_is_offered(api):
    pack={'indicators':[{'display_label':'Same label','grades':[]},{'display_label':'Same label','grades':[]}]}
    with pytest.raises(ActionRejected,match='DUPLICATE_INDICATOR_LABEL'):
        api._layout(pack)


def test_grade_choices_must_belong_to_the_selected_indicator(api):
    model=api._input_model((('Slope geometry',('Steep [50–100]',)),('Water',('Dry [0–49]',))))
    row={'indicator':'Slope geometry','grade':'Dry [0–49]','rank':1,'value':'25',
        'basis_kind':'direct_evidence','rationale':'Observed.','rank_reason':'Professional ranking.'}
    with pytest.raises(ValidationError,match='offered'):
        model.model_validate(row)
    row.update(grade='Steep [50–100]',value='60',plausible_grades=['Dry [0–49]'])
    with pytest.raises(ValidationError,match='offered'):
        model.model_validate(row)


def test_resolved_manifest_quote_remains_export_readable(assigned, api):
    from report_agent.g3_export import citation_text
    f = assigned
    with f.ws.store.connect() as db:
        scope = api._assignment(f.cs, db, f.actor)
        citations = api.resolve_judgment_sources(f.cs, db, f.actor, scope, [f.cite('design')['quote']])
    assert citations[0]['locator'] == 'manifest text'
    from report_agent.content_models import Ref
    records = {Ref.model_validate(c['source_ref']).key(): f.cs.read(c['source_ref']) for c in citations}
    assert 'design' in citation_text({'kind': 'paragraph', 'citations': citations}, records)


def test_compact_assignment_includes_bound_inventory_and_approved_method(assigned, api):
    f = assigned
    packet = api.read_assignment(f.cs, f.actor)
    assert packet['inventory_facts'][0]['name'] == 'height'
    assert packet['inventory_facts'][0]['values'][0]['value'] == '30 m'
    assert packet['owner_conventions'][0]['interpretation'] == f.plan['conventions'][0]['interpretation']
    assert packet['approved_method']['indicator_count'] == 4
    assert packet['approved_method']['weight_rule']['interpretation'] == f.plan['method_conventions'][0]['interpretation']
    assert packet['approved_method']['rank_weights'] == ['0.4', '0.3', '0.2', '0.1']
    assert packet['boundary']['excluded_objects'] == []
    assert 'source_ref' not in str(packet) and 'method_id' not in str(packet)


def test_second_scoped_writer_cannot_replace_canonical_producer(assigned, api):
    f = assigned
    for index in range(4):
        api.set_indicator(f.cs, f.actor, 'producer-row-' + str(index), input_row(f, api, index))
    first = api.submit_assessment(f.cs, f.actor, 'producer-submit')['result']
    original = f.actor
    task = deepcopy(f.cs.read({'type': 'DelegatedTask', 'id': original.task_id, 'version': 1})['payload'])
    with f.ws.store.connect() as db:
        ref = f.cs._insert(db, f.co, 'DelegatedTask', task)
    f.actor = Actor('content:writer:' + ref['id'], 'writer', ref['id'])
    for index in range(4):
        api.set_indicator(f.cs, f.actor, 'other-row-' + str(index), input_row(f, api, index))
    with pytest.raises(ActionForbidden, match='producer ownership'):
        api.submit_assessment(f.cs, f.actor, 'other-submit')
    assert len(f.cs.list_objects('Assessment')) == 1
    from report_agent.commission_plan import _state
    with f.ws.store.connect() as db:
        assert _state(db, 'g6_assessment:' + digest([f.plan_ref, 'S1'])) == first['assessment_ref']


def test_producer_binding_survives_invalidating_own_current_assessment(assigned, api):
    from report_agent.commission_plan import _state
    f = assigned
    for index in range(4):
        api.set_indicator(f.cs, f.actor, 'first-' + str(index), input_row(f, api, index))
    initial = api.submit_assessment(f.cs, f.actor, 'first-submit')['result']
    original = f.actor
    changed = input_row(f, api); changed['value'] = '31'
    api.set_indicator(f.cs, original, 'original-correction', changed)
    selection = 'g6_assessment:' + digest([f.plan_ref, 'S1'])
    with f.ws.store.connect() as db:
        assert _state(db, selection) is None
        payload = f.cs._read(db, {'type': 'DelegatedTask', 'id': original.task_id, 'version': 1})['payload']
        ref = f.cs._insert(db, f.co, 'DelegatedTask', payload)
    f.actor = Actor('content:writer:' + ref['id'], 'writer', ref['id'])
    for index in range(4):
        api.set_indicator(f.cs, f.actor, 'foreign-' + str(index), input_row(f, api, index))
    with pytest.raises(ActionForbidden, match='producer ownership'):
        api.submit_assessment(f.cs, f.actor, 'foreign-submit')
    assert len(f.cs.list_objects('Assessment')) == 1
    corrected = api.submit_assessment(f.cs, original, 'original-resubmit')['result']
    assert corrected['assessment_ref'] != initial['assessment_ref']
    assert f.cs.read(corrected['assessment_ref'])['owner_id'] == original.id
    with f.ws.store.connect() as db:
        assert _state(db, selection) == corrected['assessment_ref']
