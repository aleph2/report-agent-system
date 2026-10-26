"""Task-local selectors remove transcription work, never review judgment."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from report_agent.content_tasks import native_review_submission_schema
from report_agent.errors import ActionRejected
from report_agent.handoff_release import release
from test_deliverable_declaration_v4 import case

IDENTITY = {'target_ref', 'criterion_ref', 'scope_id', 'assessment_kind'}
CONTRACT = 'task-scope-selectors-v1'


def wire_submission():
    snapshot = {'type':'DocumentSnapshot','id':'synthetic-snapshot','version':1}
    criterion = {'type':'Criterion','id':'synthetic-criterion','version':1}
    return {'target_ref':snapshot,'snapshot_ref':snapshot,'scope':'Assigned comparison',
        'criteria_refs':[criterion],'dependency_refs':[], 'items':[{
            'assigned_scope_index':0,'scope':'Assigned comparison','execution_state':'not_started',
            'verdict':None,'observations':[],
            'coverage':{'checked':[],'unchecked':['Actual comparison remains'],'blocked':[],
                        'basis':'No evidence inspected yet.'},
            'reason':'Not started; no acceptance claimed.'}]}


def test_selector_schema_replaces_only_repeated_scope_identity():
    old = native_review_submission_schema(v4=True).model_json_schema()
    old_item = old['$defs']['NativeReviewItem']['properties']
    assert IDENTITY <= old_item.keys()
    assert 'assigned_scope_index' not in old_item
    new = native_review_submission_schema(v4=True, scope_selectors=True)
    value = new.model_validate(wire_submission()).model_dump()
    assert value['items'][0]['assigned_scope_index'] == 0
    assert not IDENTITY & value['items'][0].keys()
    schema = new.model_json_schema()
    item_ref = schema['properties']['items']['items']['$ref'].rsplit('/',1)[1]
    item = schema['$defs'][item_ref]
    assert not IDENTITY & item['properties'].keys()
    assert item['additionalProperties'] is False
    assert 'operation_id' not in schema['properties']
    assert native_review_submission_schema(v4=True).model_json_schema() == old


@pytest.mark.parametrize('index',[True,False,'0',0.0,-1,None])
def test_selector_requires_strict_nonnegative_integer(index):
    value=wire_submission(); value['items'][0]['assigned_scope_index']=index
    with pytest.raises(ValidationError):
        native_review_submission_schema(v4=True,scope_selectors=True).model_validate(value)


@pytest.mark.parametrize('field', sorted(IDENTITY))
def test_selector_wire_rejects_mixed_machine_identity(field):
    value=wire_submission()
    values={'target_ref':{'type':'ContentNode','id':'synthetic-node','version':1},
            'criterion_ref':{'type':'Criterion','id':'synthetic-criterion','version':1},
            'scope_id':'synthetic-scope','assessment_kind':'content'}
    value['items'][0][field]=values[field]
    with pytest.raises(ValidationError) as error:
        native_review_submission_schema(v4=True,scope_selectors=True).model_validate(value)
    assert any(e['type']=='extra_forbidden' and e['loc'][-1]==field for e in error.value.errors())


def test_submission_selector_is_explicit_release_bound_and_legacy_absence_unchanged(case):
    cs,*_=case
    original=deepcopy(cs.store.manifest); before=release(original)
    assert 'review_submission_contract' not in before
    bound=release({**original,'review_submission_contract':CONTRACT})
    assert bound['review_submission_contract']==CONTRACT
    assert bound['digest']!=before['digest']
    assert release(original)==before
    with pytest.raises(ActionRejected,match='UNKNOWN_REVIEW_SUBMISSION_CONTRACT'):
        release({**original,'review_submission_contract':'unknown'})
    with pytest.raises(ActionRejected,match='REVIEW_SUBMISSION_SELECTORS_REQUIRE_NATIVE_V4'):
        release({**original,'review_submission_contract':CONTRACT,
                 'review_interface_profile':'review-interfaces-v3'})

def test_selectors_are_not_available_on_legacy_interface():
    with pytest.raises(ActionRejected,match='REVIEW_SUBMISSION_SELECTORS_REQUIRE_NATIVE_V4'):
        native_review_submission_schema(scope_selectors=True)


def test_selector_expands_only_identity_from_current_immutable_task(case):
    from report_agent.review_scope_selectors import expand_submission
    from report_agent.content_tasks import delegated_task
    from report_agent.workspace import Workspace
    from test_review_binding_v4 import prepared,review_call,task_record
    cs,_,criteria,_=prepared(case)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    ws=Workspace(cs.store)
    with delegated_task(ws,'coordinator',review_call(criteria,identity='selector-expansion')) as (_,actor):
        task=task_record(cs,actor)['payload']
        chosen=task['review_requirements'][1]
        value=wire_submission();value['items'][0]['assigned_scope_index']=1
        value.update(target_ref=task['review_snapshot_ref'],snapshot_ref=task['review_snapshot_ref'],criteria_refs=criteria)
        before=deepcopy(value)
        cs.store.set('manifest',{**cs.store.manifest,'goal':'Later mutable goal','review_submission_contract':'unknown'})
        actual=expand_submission(cs,actor,value)
        assert value==before
        assert 'assigned_scope_index' not in actual['items'][0]
        for name in IDENTITY:
            assert actual['items'][0][name]==chosen.get(name,'content' if name=='assessment_kind' else None)
        assert {k:v for k,v in actual['items'][0].items() if k not in IDENTITY}=={
            k:v for k,v in before['items'][0].items() if k!='assigned_scope_index'}
        assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('index',[-1,True,'0',0.0,999,None])
def test_invalid_scope_index_has_local_item_path_without_save(case,index):
    from report_agent.review_scope_selectors import expand_submission
    from report_agent.content_tasks import delegated_task
    from report_agent.workspace import Workspace
    from test_review_binding_v4 import prepared,review_call
    cs,_,criteria,_=prepared(case)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    with delegated_task(Workspace(cs.store),'coordinator',review_call(criteria[:1],identity='selector-invalid')) as (_,actor):
        value=wire_submission();value['items'][0]['assigned_scope_index']=index
        with pytest.raises(ActionRejected,match='REVIEW_SCOPE_SELECTOR_INVALID') as error:
            expand_submission(cs,actor,value)
        assert error.value.diagnostic['parameter_path']==['review','items',0,'assigned_scope_index']
        assert error.value.diagnostic['allowed_index_range']==[0,0]
        assert not cs.list_objects('ReviewRecord')

@pytest.mark.parametrize('text_profile',['legacy-v1','concise-v1'])
def test_selector_role_has_no_conflicting_machine_field_instruction(text_profile):
    from report_agent.hierarchical_tools import role_prompt
    options={'interface_profile':'review-interfaces-v4','prompt_profile':text_profile,
             'expression_profile':'reader-expression-v2'}
    original=role_prompt('reviewer',**options)
    selected=role_prompt('reviewer',review_submission_contract=CONTRACT,**options)
    assert 'Each item uses its server scope_id' not in selected
    assert 'Use the supplied scope_id' not in selected
    assert 'Set assessment_kind to' not in selected
    assert role_prompt('reviewer',**options)==original
    for role in ('writer','coordinator','layout'):
        assert role_prompt(role,review_submission_contract=CONTRACT,**options)==role_prompt(role,**options)


def test_scope_selector_is_required_not_defaulted_to_first_scope():
    value=wire_submission();del value['items'][0]['assigned_scope_index']
    with pytest.raises(ValidationError) as error:
        native_review_submission_schema(v4=True,scope_selectors=True).model_validate(value)
    assert any(e['type']=='missing' and e['loc'][-1]=='assigned_scope_index' for e in error.value.errors())

def test_contract_binding_survives_reopen_and_refuses_deletion(case):
    from report_agent.review_scope_selectors import bind_contract
    from report_agent.workspace import Workspace
    from report_agent.store import Store
    cs,*_=case; original=deepcopy(cs.store.manifest)
    selected={**original,'review_submission_contract':CONTRACT}
    assert bind_contract(Workspace(cs.store),selected)==CONTRACT
    reopened=Workspace(Store(cs.store.root))
    assert bind_contract(reopened,selected)==CONTRACT
    with pytest.raises(ActionRejected,match='REVIEW_SUBMISSION_CONTRACT_BINDING_CHANGED'):
        bind_contract(reopened,original)
    assert reopened.store.get('review_submission_contract_binding')==CONTRACT


def test_contract_cannot_be_enabled_over_prior_execution_or_reset_unknown(case):
    from report_agent.review_scope_selectors import bind_contract
    from report_agent.workspace import Workspace
    cs,*_=case
    cs.store.event('model_invocation_outcome',{'id':'synthetic-prior','status':'unknown'})
    before=cs.store.events()
    with pytest.raises(ActionRejected,match='REVIEW_SUBMISSION_SELECTORS_REQUIRE_FRESH_PROJECT'):
        bind_contract(Workspace(cs.store),{**cs.store.manifest,'review_submission_contract':CONTRACT})
    assert cs.store.events()==before
    assert cs.store.get('review_submission_contract_binding') is None


def test_selector_views_preserve_full_list_positions_and_canonical_assignment(case):
    from report_agent.review_scope_selectors import requirements_view
    from report_agent.content_tasks import delegated_task
    from report_agent.workspace import Workspace
    from report_agent.decision_state import read_state,compact_context
    from report_agent.task_context import complete_review_materials,exact_task_context
    from report_agent.hierarchical_tools import content_tools
    from test_review_binding_v4 import prepared,review_call,task_record
    cs,_,criteria,_=prepared(case)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    ws=Workspace(cs.store)
    with delegated_task(ws,'coordinator',review_call(criteria,identity='selector-views')) as (_,actor):
        task=task_record(cs,actor)['payload'];original=deepcopy(task)
        materials=complete_review_materials(ws,task)
        assert [r['assigned_scope_index'] for r in materials['requirements']]==list(range(7))
        assert [r['scope_id'] for r in materials['requirements']]==[r['scope_id'] for r in task['review_requirements']]
        page=read_state(ws,'reviewer',['assignment','review_requirements'],offset=3,limit=2)
        assert [r['assigned_scope_index'] for r in page['value']]==[3,4]
        projected=compact_context(exact_task_context(ws,'reviewer'))
        assert [r['assigned_scope_index'] for r in projected['assignment']['review_scope_inventory']['scopes']]==list(range(7))
        tool=next(tool for tool in content_tools(ws,'reviewer') if getattr(tool,'__name__',None)=='read_task_assignment')
        shown=tool()['assignment']['review_requirements']
        assert shown==requirements_view(task)
        materials['requirements'][0]['target_ref']['id']='must-not-mutate-authority'
        assert task==original and task_record(cs,actor)['payload']==original


def test_scope_index_zero_never_uses_another_current_actor(case):
    from report_agent.review_scope_selectors import expand_submission
    from report_agent.content_tasks import delegated_task
    from report_agent.errors import ActionForbidden
    from report_agent.workspace import Workspace
    from test_review_binding_v4 import prepared,review_call,task_record
    cs,_,criteria,_=prepared(case);ws=Workspace(cs.store)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    with delegated_task(ws,'coordinator',review_call(criteria[:1],identity='selector-owner-a')) as (_,first):
        first_scope=task_record(cs,first)['payload']['review_requirements'][0]
    with delegated_task(ws,'coordinator',review_call(criteria[1:2],identity='selector-owner-b')) as (_,second):
        actual=expand_submission(cs,second,wire_submission())
        assert actual['items'][0]['criterion_ref']==criteria[1]
        assert actual['items'][0]['scope_id']!=first_scope['scope_id']
        with pytest.raises(ActionForbidden,match='task binding'):
            expand_submission(cs,first,wire_submission())
    assert not cs.list_objects('ReviewRecord')


async def test_interleaved_tasks_have_independent_zero_index_maps(case):
    import asyncio
    from report_agent.review_scope_selectors import expand_submission
    from report_agent.content_tasks import delegated_task
    from report_agent.workspace import Workspace
    from test_review_binding_v4 import prepared,review_call,task_record
    cs,_,criteria,_=prepared(case);ws=Workspace(cs.store)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    async def expand(index):
        with delegated_task(ws,'coordinator',review_call(criteria[index:index+1],identity='interleaved-'+str(index))) as (_,actor):
            await asyncio.sleep(0)
            value=expand_submission(cs,actor,wire_submission())
            assert value['items'][0]['criterion_ref']==criteria[index]
            assert value['items'][0]['scope_id']==task_record(cs,actor)['payload']['review_requirements'][0]['scope_id']
            return actor.task_id,value
    first,second=await asyncio.gather(expand(0),expand(1))
    assert first[0]!=second[0]
    assert first[1]['items'][0]['scope_id']!=second[1]['items'][0]['scope_id']


def test_repeated_selector_items_preserve_order_and_original_duplicate_semantics(case):
    from report_agent.review_scope_selectors import expand_submission
    from report_agent.content_models import ReviewSubmission
    from report_agent.content_tasks import delegated_task
    from report_agent.workspace import Workspace
    from test_review_binding_v4 import prepared,review_call,task_record
    cs,_,criteria,_=prepared(case)
    cs.store.set('manifest',{**cs.store.manifest,'review_submission_contract':CONTRACT})
    with delegated_task(Workspace(cs.store),'coordinator',review_call(criteria[:1],identity='selector-duplicate')) as (_,actor):
        value=wire_submission();value['items'].append(deepcopy(value['items'][0]))
        value['items'][1]['reason']='A distinct partial note about the same assigned scope.'
        result=expand_submission(cs,actor,value)
        assert len(result['items'])==2 and result['items'][1]['reason']==value['items'][1]['reason']
        assert result['items'][0]['scope_id']==result['items'][1]['scope_id']
        canonical=ReviewSubmission.model_validate(result)
        assert len(canonical.items)==2
        assert canonical.items[1].reason==value['items'][1]['reason']
