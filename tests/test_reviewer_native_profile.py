"""Native Reviewer regression contracts; scripted decisions are not quality evals.

These tests use actual task binding, tools, checkpointer and ContentStore. They
must fail on the former organizer-only runtime, rather than mocking submit.
"""
import json

import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import role_prompt
from test_hierarchical_content import ws, seed, submission, review_item
from test_deep_runtime import Driver, invoke, observation, call


def native(ws):
    ws.store.set('manifest', {**ws.store.manifest,
        'review_entrypoint':'delegated-reviewer-v1', 'review_execution_mode':'native-reviewer-v2'})


def commission(snapshot, refs, source=None):
    requirement = {'scope_id':'delivery', 'target_ref':refs['root'],
        'criterion_ref':refs['k'], 'required_checks':['Compare delivered claim with authorized rule'],
        'material_refs':[refs['claim']],
        'required_materials':[{'requirement_index':0, 'purpose':'Exact claim and governing rule',
            'refs':[refs['claim']], **({'source_spans':[{'source_ref':source,'offset':0,'limit':1}]} if source else {})}],
        'content_check_scopes':[{'requirement_index':0, 'kind':'local_body', 'node_ref':refs['claim']}]}
    return {'subagent_type':'reviewer', 'description':'Verify the saved deliverable against the assigned criterion; keep real limitations.',
            'review_snapshot_ref':snapshot, 'review_requirements':[requirement]}


def candidate(snapshot, refs, receipts, *, verdict='not_satisfied', state='completed'):
    item = review_item(refs['root'], refs['k'], receipts[0] if receipts else None, verdict)
    item.update(scope_id='delivery', execution_state=state,
        observations=[{'locator':f'actual observation {i}', 'observation':'Scoped protocol fixture, not an engineering acceptance.',
                       'receipt_id':r} for i,r in enumerate(receipts)],
        checked_requirement_indexes=[0] if state=='completed' else [],
        check_results=[{'requirement_index':0, 'execution_state':'completed' if state=='completed' else 'partial',
            'result':'Compared the declared fixture inputs.' if state=='completed' else 'A known discrepancy with remaining investigation.',
            'observation_indexes':list(range(len(receipts))), 'remaining':'' if state=='completed' else 'Other assigned evidence remains unchecked.'}],
        coverage={'checked':['rule comparison'] if state=='completed' else [], 'unchecked':[] if state=='completed' else ['remaining comparison'],
                  'blocked':[], 'basis':'Actual fixture scope; todo status is not acceptance.'})
    return submission(snapshot, refs, item)


async def test_native_reviewer_uses_configured_role_and_direct_submission(ws):
    """R01/R11/P01/E01: actual model-facing role/tools, no hidden second judge."""
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r['ref'] for r in cs.list_objects('SourceArtifact'))
    saved = []
    def first(messages):
        assert messages[0].type == 'system'
        text = messages[0].text
        assert role_prompt('reviewer') in text
        assert 'call perform_assigned_review for' not in text
        return invoke('read_context', target_ref=refs['claim'])
    def submit(messages):
        body = observation(messages, 'read_context')['receipt_id']
        page = observation(messages, 'read_source_page')
        assert page['blocks'] and page['receipt_id']
        return invoke('submit_review', operation_id='native-save',
                      review=candidate(snapshot,refs,[body,page['receipt_id']]))
    def final(messages):
        value = observation(messages, 'submit_review')
        assert value['ok'], value
        saved.append(value)
        return AIMessage(content=json.dumps(value))
    driver = Driver(coordinator=[invoke('task', **commission(snapshot,refs,source)), AIMessage(content='Retained actual scoped result.')],
        reviewer=[first, invoke('read_source_page',source_id='s',offset=0,limit=1), submit, final])
    result = await deep_runtime.run_report(ws,driver)
    assert result['last_error'] is None, result
    assert len(saved)==1
    record, = cs.list_objects('ReviewRecord')
    assert saved[0]['result']['review_ref']==record['ref']
    assert record['payload']['runtime_identity']['review_profile']=='native-reviewer-v2'
    assert record['payload']['items'][0]['verdict']=='not_satisfied'
    assert record['owner_id']=='content:reviewer:'+record['task_id']
    tools = {t['name'] for t in driver.bindings['reviewer'][0]}
    assert {'submit_review','correct_own_review','analyze_evidence'} <= tools
    assert not {'perform_assigned_review','perform_assigned_artifact_review','commit_objects','task'} & tools
    assert not any(role in {'text_tool','rubric_grader'} for role,_,_ in driver.calls)
    assert not ws.store.get('content_final_review')


def test_native_completed_check_cannot_skip_declared_body(ws):
    """S02 negative: title-only root identity does not stand for real bodies."""
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    request = commission(snapshot,refs)
    request['review_requirements'][0]['required_materials'] = []
    with delegated_task(ws,'coordinator',call('task',request,'body-task')) as (_, actor):
        root_receipt = cs.read_context(actor,refs['root'])['receipt_id']
        with pytest.raises(ActionRejected,match='MISSING_BODY_EXTENT|MISSING_REQUIRED_MATERIAL'):
            cs.submit_review(actor,'missing-body',candidate(snapshot,refs,[root_receipt]),{})
    assert cs.list_objects('ReviewRecord')==[]


def test_native_completed_check_cannot_bypass_assigned_scope(ws):
    """S06 negative: a valid snapshot member is not an assigned review scope."""
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'scope-task')) as (_, actor):
        receipt = cs.read_context(actor,refs['claim'])['receipt_id']
        value = candidate(snapshot,refs,[receipt])
        value['items'][0]['scope_id']='unassigned-scope'
        with pytest.raises(ActionRejected,match='REVIEW_ITEM_OUTSIDE_ASSIGNMENT'):
            cs.submit_review(actor,'outside',value,{})
    assert cs.list_objects('ReviewRecord')==[]


async def test_native_schema_rejection_retains_original_tool_candidate_in_checkpoint(ws):
    """S04: native tool validation can reject before Store.operation is entered."""
    from langchain_core.messages import ToolMessage
    from langgraph.checkpoint.sqlite import SqliteSaver
    from report_agent.native_trace import checkpoint_messages
    native(ws);cs,_,refs,snap,_=seed(ws)
    def bad(messages):
        value=candidate(snap,refs,[observation(messages,'read_context')['receipt_id']])
        del value['items'][0]['reason']
        return invoke('submit_review',operation_id='invalid-native-tool',review=value)
    def after(messages):
        error=next(m for m in reversed(messages) if isinstance(m,ToolMessage))
        assert error.status=='error' and 'reason' in error.text
        assert not cs.list_objects('ReviewRecord')
        return AIMessage(content='Raw candidate retained; expression requires correction. No acceptance.')
    driver=Driver(coordinator=[invoke('task',**commission(snap,refs)),AIMessage(content='Unfinished review retained.')],
        reviewer=[invoke('read_context',target_ref=refs['claim']),bad,after])
    result=await deep_runtime.run_report(ws,driver);assert result['last_error'] is None,result
    retained=[]
    with SqliteSaver.from_conn_string(str(ws.store.root/'checkpoints.db')) as saver:
        for row in saver.list(None):
            for _,message in checkpoint_messages(row):
                if isinstance(message,AIMessage):
                    retained.extend(c for c in message.tool_calls if c['name']=='submit_review' and c['args']['operation_id']=='invalid-native-tool')
    assert retained and all('reason' not in c['args']['review']['items'][0] for c in retained)
    assert not cs.list_objects('ReviewRecord')


async def test_native_optional_analysis_is_observation_not_automatic_saved_judgment(ws):
    """R11: advisory analysis has no hidden judge/save effect."""
    native(ws);cs,_,refs,snap,_=seed(ws)
    def after(messages):
        returned=observation(messages,'analyze_evidence')
        assert returned['analysis'] and returned['receipt_id']
        assert not cs.list_objects('ReviewRecord')
        return AIMessage(content='Advice remains unadopted; own checking and formal submission still required.')
    driver=Driver(coordinator=[invoke('task',**commission(snap,refs)),AIMessage(content='Incomplete review retained.')],
        reviewer=[invoke('analyze_evidence',question='Compare the assigned synthetic claim with located rule.',
            result_selections=[],snapshot_ref=snap,content_selections=[{'ref':refs['claim']}],
            source_selections=[{'source_id':'s','offset':0,'limit':1}]),after],
        text_tool=[AIMessage(content='Advisory analysis from actual synthetic inputs, not a saved judgment.')])
    result=await deep_runtime.run_report(ws,driver);assert result['last_error'] is None,result
    assert not cs.list_objects('ReviewRecord')
