"""Offline scope/citation controls; scripted answers do not prove semantic quality."""
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from report_agent.bounded_review import perform_review
from report_agent.content_selection import ContentSelection
from report_agent.content_tasks import delegated_task, normalize_review_requirements
from report_agent.errors import ActionRejected
from report_agent.review_input import review_material_context
from report_agent.store import encode
from test_bounded_review import Model, review_call
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def extent_call(snapshot, refs, kind='subtree_bodies', bind_child=True):
    call = review_call(snapshot, refs)
    req = call['args']['review_requirements'][0]
    req.update(target_ref=refs['root'], required_checks=['Inspect the declared report body extent'],
        required_materials=[{'requirement_index':0, 'purpose':'Report introduction', 'refs':[refs['root']]}],
        content_check_scopes=[{'requirement_index':0, 'node_ref':refs['root'], 'kind':kind}],
        material_refs=[refs['claim']] if bind_child else [])
    return call


def answer(observations, links, *, verdict='satisfied', findings=()):
    return json.dumps({'items':[{'scope_id':'rule-comparison',
        'checked_requirement_indexes':[0], 'execution_state':'completed', 'verdict':verdict,
        'observations':[{'evidence_index':i, 'locator':f'input {i}', 'observation':text}
                        for i,text in observations],
        'check_results':[{'requirement_index':0,'execution_state':'completed',
            'result':'Only the assigned check was assessed.', 'observation_indexes':links, 'remaining':''}],
        'coverage':{'checked':['Assigned check'], 'unchecked':[], 'blocked':[], 'basis':'Located supplied evidence'},
        'reason':'Scoped observations, not whole-report acceptance.', 'findings':list(findings)}]})


def finding(**updates):
    return {'finding_type':'confirmed_defect','locator_state':'located',
        'description':'Value 70 contradicts the supplied permitted interval.',
        'impact':'The adopted value is outside the stated interval.',
        'needed_outcome':'Resolve the adopted value against the original rule.',
        'requirement_index':0,'observation_indexes':[0,1], 'basis_kind':'supplied_content', **updates}


@pytest.mark.parametrize('bind_child', [False, True])
async def test_container_only_subtree_returns_gap_without_checker_or_revision(ws, bind_child):
    cs, _, refs, snapshot, _ = seed(ws)
    before = cs.list_objects('ContentNode')
    model = Model()
    with delegated_task(ws,'coordinator',extent_call(snapshot,refs,bind_child=bind_child)) as (_,actor):
        result = await perform_review(ws,actor,model,'container',['rule-comparison'])
    assert result['code']=='REVIEW_REQUIRED_BODIES_NOT_SUPPLIED'
    gap = result['material_context']['missing_body_extents'][0]
    assert gap['missing_full_body_refs']==[refs['claim']]
    assert gap['unbound_body_refs']==([] if bind_child else [refs['claim']])
    assert result['model_called'] is False and not model.calls
    assert not cs.list_objects('ReviewRecord') and cs.list_objects('ContentNode')==before


async def test_partial_child_is_not_a_full_subtree_body(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model()
    with delegated_task(ws,'coordinator',extent_call(snapshot,refs)) as (_,actor):
        result = await perform_review(ws,actor,model,'partial',['rule-comparison'],
            content_selections=[ContentSelection(ref=refs['claim'],limit=4)])
    assert result['material_context']['missing_body_extents'][0]['missing_full_body_refs']==[refs['claim']]
    assert not model.calls


async def test_complete_child_body_allows_subtree_check_and_exact_reuse(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(answer([(0,'Report introduction'),(1,'For adopted class B use 70.')],[0,1]))
    with delegated_task(ws,'coordinator',extent_call(snapshot,refs)) as (_,actor):
        selection = [ContentSelection(ref=refs['claim'])]
        first = await perform_review(ws,actor,model,'full',['rule-comparison'],content_selections=selection)
        again = await perform_review(ws,actor,model,'same-input',['rule-comparison'],content_selections=selection)
    assert again['reused'] and first['review_ref']==again['review_ref'] and len(model.calls)==1
    packet = json.loads(model.calls[0][1][1])
    context = packet['evidence'][-1]['structure']
    assert not context['missing_body_extents']
    assert {encode(r) for r in context['body_extents'][0]['required_body_refs']}=={encode(refs['root']),encode(refs['claim'])}


async def test_local_introduction_check_does_not_require_unassigned_children(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(answer([(0,'Report introduction')],[0]))
    with delegated_task(ws,'coordinator',extent_call(snapshot,refs,kind='local_body',bind_child=False)) as (_,actor):
        result = await perform_review(ws,actor,model,'local',['rule-comparison'])
    assert result['review_ref'] and len(model.calls)==1
    context = json.loads(model.calls[0][1][1])['evidence'][-1]['structure']
    child = next(r for r in context['inventory'] if r['ref']==refs['claim'])
    assert child['body_input']=='not_supplied' and child['eligible_for_body_selection'] is False
    assert 'heading_preview' not in child
    assert 'For adopted class B use 70.' not in json.dumps(context)


async def test_existing_unselected_node_is_present_in_structure_without_body_receipt(ws):
    from report_agent.task_supervision import observed_refs
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(answer([(0,'The selected value is 70.'),(1,'Root exists in frozen topology')],[0,1]))
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)) as (_,actor):
        result = await perform_review(ws,actor,model,'metadata',['rule-comparison'])
        item = result['items'][0]
        actual_reads = observed_refs(cs,actor.id,item['observations'])
    context = json.loads(model.calls[0][1][1])['evidence'][-1]['structure']
    root = next(r for r in context['inventory'] if r['ref']==refs['root'])
    assert root['body_input']=='not_supplied' and root['children']==[refs['claim']]
    assert encode(refs['root']) not in actual_reads


async def test_completed_subtree_cannot_cite_only_intro_or_metadata(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(answer([(0,'Introduction'),(2,'Child exists in topology')],[0,1]))
    with delegated_task(ws,'coordinator',extent_call(snapshot,refs)) as (_,actor):
        with pytest.raises(ActionRejected,match='COMPLETED_CHECK_MISSING_TARGET_OR_BODY_EXTENT'):
            await perform_review(ws,actor,model,'insufficient-citation',['rule-comparison'],
                content_selections=[ContentSelection(ref=refs['claim'])])
    assert len(model.calls)==1 and not cs.list_objects('ReviewRecord')
    with ws.store.connect() as db:
        assert db.execute('select count(*) from analyses').fetchone()[0]==1


async def test_supplied_full_body_does_not_make_partial_citation_complete(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(answer([(0,'Introduction'),(1,'Only four child characters')],[0,1]))
    with delegated_task(ws,'coordinator',extent_call(snapshot,refs)) as (_,actor):
        with pytest.raises(ActionRejected,match='COMPLETED_CHECK_MISSING_TARGET_OR_BODY_EXTENT'):
            await perform_review(ws,actor,model,'partial-citation',['rule-comparison'],content_selections=[
                ContentSelection(ref=refs['claim'],limit=4),ContentSelection(ref=refs['claim'])])
    assert len(model.calls)==1 and not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('case,expected',[
    ('unlinked','FINDING_REQUIRES_VALID_OBSERVATION_LINKS'),
    ('input_gap','INPUT_GAP_IS_NOT_CONFIRMED_CONTENT_DEFECT'),
    ('metadata_as_content','STRUCTURE_METADATA_IS_NOT_CONTENT_EVIDENCE'),
    ('structure_without_structure','STRUCTURE_FINDING_REQUIRES_SNAPSHOT_EVIDENCE'),
    ('wrong_check','REVIEW_FINDING_OUTSIDE_ASSIGNED_CHECK'),
])
async def test_unsupported_finding_is_rejected_preserving_raw_response(ws,case,expected):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type']=='SourceArtifact')
    f = finding()
    observations = [(0,'Adopted 70'),(1,'Allowed 75 to 100')]
    if case=='unlinked': f['observation_indexes']=[2]
    if case=='input_gap': f['basis_kind']='input_gap'
    if case=='metadata_as_content':
        observations.append((2,'Snapshot topology')); f['observation_indexes']=[2]
    if case=='structure_without_structure': f['basis_kind']='snapshot_structure'
    if case=='wrong_check': f['requirement_index']=1
    model = Model(answer(observations,list(range(len(observations))),verdict='not_satisfied',findings=[f]))
    with delegated_task(ws,'coordinator',review_call(snapshot,refs,reads=[source])) as (_,actor):
        with pytest.raises((ActionRejected,ValidationError),match=expected):
            await perform_review(ws,actor,model,'invalid',['rule-comparison'])
    assert not cs.list_objects('ReviewRecord') and len(model.calls)==1
    with ws.store.connect() as db:
        assert db.execute('select count(*) from analyses').fetchone()[0]==1


async def test_valid_observed_defect_remains_accepted(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type']=='SourceArtifact')
    model = Model(answer([(0,'Adopted B value 70'),(1,'Original B interval 75 to 100')],[0,1],
        verdict='not_satisfied', findings=[finding()]))
    with delegated_task(ws,'coordinator',review_call(snapshot,refs,reads=[source])) as (_,actor):
        result = await perform_review(ws,actor,model,'actual-defect',['rule-comparison'])
    assert result['items'][0]['findings'][0]['finding_type']=='confirmed_defect'
    assert result['items'][0]['verdict']=='not_satisfied'


async def test_finding_cannot_use_another_checks_observations(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    call = review_call(snapshot,refs)
    req = call['args']['review_requirements'][0]
    req['required_checks']=['Inspect local claim','Inspect local wording']
    req['required_materials'].append({'requirement_index':1,'purpose':'Local wording','refs':[refs['claim']]})
    raw = json.loads(answer([(0,'Value 70'),(0,'Wording claim')],[0],verdict='not_satisfied',
        findings=[finding(observation_indexes=[1])]))
    item = raw['items'][0]
    item['checked_requirement_indexes']=[0,1]
    item['check_results'].append({**item['check_results'][0],'requirement_index':1,'observation_indexes':[1]})
    model = Model(json.dumps(raw))
    with delegated_task(ws,'coordinator',call) as (_,actor):
        with pytest.raises(ActionRejected,match='REVIEW_FINDING_OUTSIDE_CHECK_OBSERVATIONS'):
            await perform_review(ws,actor,model,'cross-check',['rule-comparison'])
    assert not cs.list_objects('ReviewRecord')


def test_another_scope_does_not_grant_subtree_body_permission(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    req = extent_call(snapshot,refs,bind_child=False)['args']['review_requirements'][0]
    evidence = [{'kind':'saved_object','object':cs.read(r)} for r in [refs['root'],refs['claim']]]
    context = review_material_context(cs,snapshot,[req],evidence,{encode(r):r for r in [refs['root'],refs['claim']]})
    gap = context['missing_body_extents'][0]
    assert not gap['missing_full_body_refs'] and gap['unbound_body_refs']==[refs['claim']]


async def test_content_extent_root_outside_task_pool_is_rejected_before_call(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    call = review_call(snapshot,refs)
    call['args']['review_requirements'][0]['content_check_scopes']=[
        {'requirement_index':0,'node_ref':refs['root'],'kind':'subtree_bodies'}]
    with pytest.raises(ActionRejected,match='CONTENT_CHECK_SCOPE_OUTSIDE_ASSIGNMENT'):
        with delegated_task(ws,'coordinator',call): pass


def test_empty_new_extent_keeps_legacy_resume_identity(ws):
    _, _, refs, snapshot, _ = seed(ws)
    old = review_call(snapshot,refs)['args']['review_requirements']
    new = deepcopy(old); new[0]['content_check_scopes']=[]
    assert normalize_review_requirements(old)==normalize_review_requirements(new)


async def test_partial_inventory_cannot_support_confirmed_absence(ws, monkeypatch):
    import report_agent.review_input as inputs
    monkeypatch.setattr(inputs,'MAX_STRUCTURE_NODES',1)
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(answer([(0,'Selected claim'),(1,'Incomplete topology preview')],[0,1],
        verdict='not_satisfied',findings=[finding(basis_kind='snapshot_structure',
            locator_state='absent',observation_indexes=[1])]))
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)) as (_,actor):
        with pytest.raises(ActionRejected,match='INCOMPLETE_INVENTORY_CANNOT_ESTABLISH_ABSENCE'):
            await perform_review(ws,actor,model,'absence',['rule-comparison'])
    assert not cs.list_objects('ReviewRecord')
    context = json.loads(model.calls[0][1][1])['evidence'][-1]['structure']
    assert context['inventory_complete'] is False and context['next_offset']==1


async def test_native_graph_supplies_full_declared_extent_without_extra_checker_call(ws):
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke
    cs, _, refs, snapshot, _ = seed(ws)
    ws.store.set('manifest',{**ws.store.manifest,'review_execution_mode':'bounded-tool-v1'})
    ws.store.set('context_policy','stateful-tools-v1')
    response = answer([(0,'Introduction'),(1,'Actual child body')],[0,1])
    driver = Driver(coordinator=[AIMessage(content='',tool_calls=[extent_call(snapshot,refs)]),
        AIMessage(content='Only declared body extent validated.')],
        reviewer=[invoke('perform_assigned_review',operation_id='native',scope_ids=['rule-comparison'],
            source_selections=[],content_selections=[{'ref':refs['claim']}]),
            AIMessage(content='Saved scoped result.')],text_tool=[AIMessage(content=response)])
    await deep_runtime.run_report(ws,driver)
    assert len(cs.list_objects('ReviewRecord'))==1
    assert len([c for c in driver.calls if c[0]=='text_tool'])==1
