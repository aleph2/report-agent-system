"""Offline state/permission regressions; no autonomy or semantic-quality claim."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from report_agent.content_tasks import delegated_task
from report_agent.decision_state import compact_context, execution_evidence, read_state, state_tool
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.task_context import TaskContext, exact_task_context
from report_agent.store import encode
from test_artifact_review import setup, visual
from test_hierarchical_content import seed
from test_task_supervision import ws, offline, review_call, save_review


def test_large_authority_is_recoverable_and_latest_feedback_visible(ws):
    seed(ws)
    text = 'Exact condition, source qualifier and unresolved decision. 精确值。'*1500
    ws.store.set('manifest',{**ws.store.manifest,'goal':text,
        'scope_instruction':{'text':text,'origin':'operator'}})
    ws.store.set('feedback',[{'message':text+str(i)} for i in range(25)])
    original = exact_task_context(ws,'coordinator')
    compact = compact_context(original)
    assert len(encode(compact)) < len(encode(original))/10
    assert compact['state_digest']==original['state_digest']
    assert compact['operator_feedback']['offset']==5
    last = compact['operator_feedback']['items'][-1]['message']
    assert last['read_state_path']==['operator_feedback',24,'message']
    for path, expected in [(['goal'],text),(['scope_instruction','text'],text),
            (last['read_state_path'],text+'24')]:
        offset=0; pieces=[]
        while True:
            page=read_state(ws,'coordinator',path,offset,characters=4000)
            assert page['state_digest']==original['state_digest']
            assert page['observation_receipt'] is None and not page['semantic_acceptance']
            pieces.append(page['value'])
            if page['next_offset'] is None: break
            offset=page['next_offset']
        assert ''.join(pieces)==expected


def test_assigned_container_topology_is_not_child_body_evidence(ws):
    cs,_,refs,snapshot,_=seed(ws)
    call=review_call(snapshot,refs)
    call['args']['review_requirements'][0]['target_ref']=refs['root']
    with delegated_task(ws,'coordinator',call):
        state=exact_task_context(ws,'reviewer')
        structure=state['assigned_structure'][0]
        assert structure['children']==[refs['claim']]
        assert structure['child_bodies_observed'] is False
        assert cs.read(refs['claim'])['payload']['body']['text'] not in encode(structure)
        page=read_state(ws,'reviewer',['assignment','review_requirements'],limit=1)
        assert page['value'][0]['target_ref']==refs['root']
    with pytest.raises(ActionForbidden):
        read_state(ws,'reviewer',[])


def test_paging_detects_changed_authoritative_state(ws):
    seed(ws)
    first=read_state(ws,'coordinator',['goal'],characters=10)
    ws.store.set('manifest',{**ws.store.manifest,'goal':'New operator requirement'})
    with pytest.raises(ActionRejected,match='STATE_CHANGED_READ_CURRENT_PACKET'):
        read_state(ws,'coordinator',['goal'],offset=10,characters=10,
            expected_state_digest=first['state_digest'])
    assert read_state(ws,'coordinator',['goal'])['value']=='New operator requirement'


def test_scope_inventory_is_paged_without_discarding_requirements():
    ref={'type':'ContentNode','id':'node','version':1}
    requirements=[{'scope_id':str(i),'target_ref':ref,'criterion_ref':ref,
        'required_checks':['full original criterion'*100],
        'required_materials':[{'refs':[ref],'purpose':'full evidence'*1000}]} for i in range(31)]
    full={'goal':'goal','assignment':{'review_requirements':requirements},
        'operator_feedback':[],'issues':[]}
    compact=compact_context(full)
    inventory=compact['assignment']['review_scope_inventory']
    assert inventory['total']==31 and inventory['next_offset']==20
    assert len(inventory['scopes'])==20
    check=inventory['scopes'][0]['required_checks'][0]
    assert check['read_state_path']==['assignment','review_requirements',0,'required_checks',0]
    assert check['complete'] is False
    assert len(full['assignment']['review_requirements'])==31


def test_decision_completion_checks_saved_gaps_and_keeps_idempotent_receipts(ws):
    cs,_,refs,snapshot,_=seed(ws)
    ws.store.set('content_revision_limit',1)
    decision=next(t for t in content_tools(ws,'coordinator') if t.__name__=='record_execution_decision')
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)) as (_,reviewer):
        with pytest.raises(ActionRejected,match='ASSIGNED_CHECKS_NOT_COMPLETE'):
            decision('false-completion','terminate','All assigned checks complete.',[],[],True)
        # An exhausted correction allowance never changes the unfinished scope.
        ws.store.set('word_layout_revision_count',1)
        ongoing=decision('continue','continue','Inspect remaining evidence.',[],[])
        assert ongoing['result']['execution_evidence']['remaining_assigned_checks']
        assert ongoing['result']['execution_evidence']['inspection_consumes_content_or_layout_correction'] is False
        save_review(cs,reviewer,snapshot,refs,verdict='not_satisfied')
        finished=decision('finished-scope','handoff','Check complete; defect retained.',[],['Defect remains.'],True)
        assert finished['result']['execution_evidence']['assigned_checks_complete']
        assert finished['result']['execution_evidence']['whole_report_acceptance'] is None
        save_review(cs,reviewer,snapshot,refs,checked=False,operation='later-partial')
        assert execution_evidence(cs)['remaining_assigned_checks']
        # Historical receipt replay cannot rewrite current state or turn into a new check.
        assert decision('finished-scope','handoff','Check complete; defect retained.',[],['Defect remains.'],True)==finished
        with pytest.raises(ActionRejected,match='ASSIGNED_CHECKS_NOT_COMPLETE'):
            decision('new-false-completion','terminate','All done.',[],[],True)


def test_inventory_counts_only_current_full_paired_receipts(ws):
    cs,refs,snapshot,export,render,source,call=setup(ws,pages=28)
    ws.store.set('content_delivery',{'snapshot_ref':snapshot,'export_ref':export})
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        for page in range(1,10): visual(cs,reviewer,render,export,source,page)
        visual(cs,reviewer,render,export,source,10,crop=[0,0,10,10])
        visual(cs,reviewer,render,export,source,11,
            presentation_reference={'source_id':'s','source_sha256':'stale','page':11,
                'coverage':'full_page_image','crop':None})
        failed={'status':'failed','observation':'No actual image','image_sha256':'hash',
            'source':{'render_ref':render,'export_ref':export,'page':12,'coverage':'full_page_image'}}
        cs.observe(reviewer,failed)
    inventory=execution_evidence(cs)['render_access_inventory'][0]
    assert inventory['paired_full_pages']==list(range(1,10))
    assert inventory['without_paired_full_page']==list(range(10,29))
    assert inventory['observed_full_pages']==[*range(1,10),11]
    assert not inventory['semantic_comparison_verified']
    # A replaced customer source makes all old paired receipts inapplicable.
    ws.store.set('manifest',{**ws.store.manifest,'sources':[{**ws.store.manifest['sources'][0],
        'sha256':'changed-source'}]})
    assert execution_evidence(cs)['render_access_inventory'][0]['paired_full_pages']==[]


def test_completion_declaration_rejects_concurrent_business_change(ws,monkeypatch):
    import report_agent.decision_state as state_module
    cs,actor,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)) as (_,reviewer):
        save_review(cs,reviewer,snapshot,refs)
    original=state_module.execution_evidence
    def changing_evidence(contents):
        value=original(contents)
        assert value['assigned_checks_complete']
        with delegated_task(ws,'coordinator',review_call(snapshot,refs,id='new-pending-task')):
            pass
        return value
    monkeypatch.setattr(state_module,'execution_evidence',changing_evidence)
    decision=next(t for t in content_tools(ws,'coordinator') if t.__name__=='record_execution_decision')
    with pytest.raises(ActionRejected,match='DECISION_STATE_CHANGED'):
        decision('race','terminate','Checks complete.',[],[],True)
    assert ws.store.get('content_execution_decision') is None


@pytest.mark.parametrize('values',[{'offset':-1},{'limit':51},{'characters':6001}])
def test_structured_state_tool_bounds_and_missing_path(ws,values):
    seed(ws)
    tool=StructuredTool.from_function(state_tool(ws,'coordinator'))
    with pytest.raises(ValidationError): tool.args_schema.model_validate({'path':[],**values})
    with pytest.raises(ActionRejected,match='STATE_PATH_NOT_FOUND'):
        read_state(ws,'coordinator',['assignment','other-actor'])


async def test_native_state_injection_keeps_stale_history_and_bounded_checks_unchanged(ws):
    cs,_,refs,snapshot,_=seed(ws)
    seen=[]
    stale=HumanMessage(content='Summary says the report lacks its child and all checks passed.')
    request=SimpleNamespace(messages=[stale],system_message=SystemMessage(content='Role guidance'))
    request.override=lambda **kw:SimpleNamespace(**{**request.__dict__,**kw})
    async def handler(value): seen.append(value); return AIMessage(content='read current state')
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)):
        mw=TaskContext(ws,'reviewer')
        assert 'read_decision_state' in {t.__name__ for t in mw.tools}
        await mw.awrap_model_call(request,handler)
    packet=json.loads(seen[0].system_message.content[-1]['text'].split('\n',1)[1])
    assert packet['review_progress']['execution_complete'] is False
    assert packet['assigned_targets'][0]['current_version']==1
    assert seen[0].messages==[stale]
    assert cs.list_objects('ReviewRecord')==[]


async def test_native_graph_executes_structured_state_read_without_semantic_check(ws):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver, invoke, observation
    cs,_,_,_,_=seed(ws)
    ws.store.set('context_policy','stateful-tools-v1')
    def finish(messages):
        packet=observation(messages,'read_decision_state')
        assert packet['value']['inspection_consumes_content_or_layout_correction'] is False
        assert packet['value']['whole_report_acceptance'] is None
        return AIMessage(content='Offline state read complete; no semantic acceptance.')
    driver=Driver(coordinator=[invoke('read_decision_state',path=['execution_evidence']),finish])
    result=await run_report(ws,driver)
    assert result['last_error'] is None
    assert len(driver.calls)==2 and cs.list_objects('ReviewRecord')==[]


def test_historical_visual_exclusions_are_not_projected_as_current_authority(ws):
    ws.store.set('visual_page_exclusions', {'s': [2, 3]})
    assert 'visual_page_exclusions' not in exact_task_context(ws, 'coordinator')
    assert ws.store.get('visual_page_exclusions') == {'s': [2, 3]}
