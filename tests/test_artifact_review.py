"""Offline scope/publication/coverage checks, not visual model-quality evidence."""
import pytest
import json

from report_agent.artifact_review import artifact_review_tool
from report_agent.content_models import ReviewSubmission
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.task_supervision import reconcile
from test_hierarchical_content import seed, review_item, submission
from test_task_supervision import ws, offline, review_call


def setup(ws, kind='render', pages=37, reference=True):
    cs, actor, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    ws.store.set('manifest', {**ws.store.manifest, 'review_execution_mode': 'bounded-tool-v1',
        'presentation_references': [{'source_id': 's', 'instruction': 'Customer visual reference'}] if reference else []})
    with ws.store.connect() as db:
        export = cs._insert(db, actor, 'ExportArtifact', {'snapshot_ref': snapshot, 'file_ref': 'test.docx'})
        render = cs._insert(db, actor, 'RenderArtifact', {'snapshot_ref': snapshot, 'export_ref': export,
            'page_assets': [{'asset_ref': f'{i}.png', 'sha256': 'fixture'} for i in range(pages)]})
    call = review_call(snapshot, refs)
    req = call['args']['review_requirements'][0]
    req.update(assessment_kind=kind, artifact_refs=[render if kind == 'render' else export])
    if reference and kind == 'render': req['presentation_reference_ref'] = source
    return cs, refs, snapshot, export, render, source, call


def visual(cs, reviewer, render, export, source, physical_page, **changes):
    value = {'status': 'observed', 'observation': 'Offline visual receipt fixture', 'image_sha256': 'fixture-image-hash',
        'source': {'render_ref': render, 'export_ref': export, 'page': physical_page, 'coverage': 'full_page_image',
            'crop': None, 'presentation_reference': {'source_id': 's', 'source_sha256': cs.read(source)['payload']['file_digest'],
                'page': physical_page, 'coverage': 'full_page_image', 'crop': None}}}
    value['source'].update(changes)
    return cs.observe(reviewer, value)['receipt_id']


def payload(snapshot, refs, artifact, receipts, kind='render', complete=True):
    item = review_item(refs['claim'], refs['k'], receipts[0], verdict='undetermined')
    item.update(scope_id='rule-comparison', assessment_kind=kind, artifact_refs=[artifact],
        observations=[{'locator': str(i), 'observation': 'Fixture access receipt', 'receipt_id': r} for i,r in enumerate(receipts)])
    if not complete:
        item.update(execution_state='running', verdict=None,
            coverage={'checked':['some pages'], 'unchecked':['remaining pages'], 'blocked':[], 'basis':'actual receipts'})
    return ReviewSubmission.model_validate(submission(snapshot, refs, item))


def test_bounded_route_exposed_without_manual_content_route(ws):
    setup(ws)
    names = {t.__name__ for t in business_tools(ws, 'reviewer', None, None)}
    assert {'perform_assigned_artifact_review', 'perform_assigned_review'} <= names
    assert not {'submit_artifact_review', 'submit_review', 'correct_own_review'} & names


def test_all_37_paired_pages_publish_and_reconcile(ws):
    cs, refs, snap, export, render, source, call = setup(ws)
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        receipts = [visual(cs,reviewer,render,export,source,p) for p in range(1,38)]
        result = artifact_review_tool(ws)('complete',payload(snap,refs,render,receipts))
        saved = cs.read(result['result']['review_ref'])['payload']
        assert source in saved['dependency_refs']
        assert reconcile(cs,reviewer.task_id)['execution_complete']


@pytest.mark.parametrize('change', [
    {'coverage':'region_only', 'crop':[0,0,1,.2]},
    {'page':38}, {'render_ref':{'type':'RenderArtifact','id':'wrong','version':1}},
    {'presentation_reference':{'source_id':'s','source_sha256':'wrong','page':1,'coverage':'full_page_image'}},
    {'presentation_reference':{}},
])
def test_crop_wrong_page_version_or_reference_cannot_complete(ws, change):
    cs, refs, snap, export, render, source, call = setup(ws,pages=1)
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipt=visual(cs,reviewer,render,export,source,1,**change)
        with pytest.raises(ActionRejected,match='COVERAGE_INCOMPLETE'):
            artifact_review_tool(ws)('bad',payload(snap,refs,render,[receipt]))
        assert not cs.list_objects('ReviewRecord')


def test_partial_page_findings_remain_saved_and_missing_pages_visible(ws):
    cs, refs, snap, export, render, source, call=setup(ws)
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipt=visual(cs,reviewer,render,export,source,1)
        artifact_review_tool(ws)('partial',payload(snap,refs,render,[receipt],complete=False))
        status=reconcile(cs,reviewer.task_id)
        assert not status['execution_complete']
        assert status['remaining'][0]['artifact_coverage_gaps'][0]['pages']==list(range(2,38))


def test_route_cannot_replace_content_verdict_or_widen_task(ws):
    cs, refs, snap, export, render, source, call=setup(ws,pages=1)
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipt=visual(cs,reviewer,render,export,source,1)
        content=payload(snap,refs,render,[receipt],kind='content')
        with pytest.raises(ActionRejected,match='CONTENT_JUDGMENT_REQUIRES'):
            artifact_review_tool(ws)('content',content)
        wrong=payload(snap,refs,render,[receipt])
        wrong.items[0].scope_id='other-scope'
        with pytest.raises(ActionRejected,match='OUTSIDE_ASSIGNED_SCOPE'):
            artifact_review_tool(ws)('wrong-scope',wrong)


def test_assigned_export_can_publish_without_layout(ws):
    cs, refs, snap, export, render, source, call=setup(ws,kind='export')
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipt=cs.observe(reviewer,{'export_ref':export,'structure':{'paragraphs':[]}})['receipt_id']
        artifact_review_tool(ws)('export',payload(snap,refs,export,[receipt],kind='export'))
        assert reconcile(cs,reviewer.task_id)['execution_complete']


def test_designated_customer_cannot_be_omitted_from_assignment(ws):
    cs, refs, snap, export, render, source, call=setup(ws)
    del call['args']['review_requirements'][0]['presentation_reference_ref']
    with pytest.raises(ActionRejected,match='REQUIRES_CUSTOMER_REFERENCE'):
        with delegated_task(ws,'coordinator',call): pass


def test_completed_atomic_check_must_cite_all_pages(ws):
    cs, refs, snap, export, render, source, call=setup(ws,pages=2)
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipts=[visual(cs,reviewer,render,export,source,p) for p in (1,2)]
        value=payload(snap,refs,render,receipts)
        from report_agent.content_models import CheckResult
        value.items[0].check_results=[CheckResult(requirement_index=0,execution_state='completed',result='Fixture',observation_indexes=[0])]
        with pytest.raises(ActionRejected,match='LINKED_PAGE_COVERAGE'):
            artifact_review_tool(ws)('bad-links',value)


def test_delivery_check_cannot_close_pages_omitted_from_its_receipts(ws):
    cs, refs, snap, export, render, source, call=setup(ws,pages=2)
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipts=[visual(cs,reviewer,render,export,source,p) for p in (1,2)]
        value=payload(snap,refs,render,receipts)
        from report_agent.content_models import DeliveryCheck
        value.delivery_checks=[DeliveryCheck(kind='render',artifact_refs=[render],execution_state='completed',
            verdict='undetermined',observations=value.items[0].observations[:1],coverage=value.items[0].coverage,reason='Fixture')]
        with pytest.raises(ActionRejected,match='DELIVERY_CHECK_COVERAGE_INCOMPLETE'):
            artifact_review_tool(ws)('bad-delivery',value)


def test_failed_export_read_cannot_close_assigned_scope(ws):
    cs, refs, snap, export, render, source, call=setup(ws,kind='export')
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipt=cs.observe(reviewer,{'export_ref':export,'structure':{},'status':'failed'})['receipt_id']
        with pytest.raises(ActionRejected,match='COVERAGE_INCOMPLETE'):
            artifact_review_tool(ws)('failed-read',payload(snap,refs,export,[receipt],kind='export'))


def test_export_subcheck_saves_while_layout_pages_remain_unchecked(ws):
    """Regression: a structure read does not owe images of all report pages."""
    from report_agent.content_models import CheckResult
    cs, refs, snap, export, render, source, call = setup(ws, pages=2)
    req = call['args']['review_requirements'][0]
    req.update(artifact_refs=[render, export], required_checks=['Read structure', 'Inspect pages'],
        artifact_check_scopes=[{'requirement_index': 0, 'kind': 'export_structure',
            'artifact_ref': export, 'pages': []}])
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        read = cs.observe(reviewer, {'export_ref': export, 'structure': {'paragraphs': []}})['receipt_id']
        image = visual(cs, reviewer, render, export, source, 1)
        value = payload(snap, refs, render, [read, image], complete=False)
        from report_agent.content_models import Ref
        value.items[0].artifact_refs = [Ref(**render), Ref(**export)]
        value.items[0].check_results = [
            CheckResult(requirement_index=0, execution_state='completed', result='Structure read', observation_indexes=[0]),
            CheckResult(requirement_index=1, execution_state='partial', result='One page observed', observation_indexes=[1], remaining='Page 2')]
        result = artifact_review_tool(ws)('partial-structure', value)
        assert result['result']['review_ref']
        state = reconcile(cs, reviewer.task_id)
        assert not state['execution_complete']
        assert state['remaining'][0]['missing_checks'] == ['Inspect pages']
        assert state['remaining'][0]['artifact_coverage_gaps'][0]['pages'] == [2]
        value.items[0].check_results[0].observation_indexes = [1]
        with pytest.raises(ActionRejected, match='missing_export_observation'):
            artifact_review_tool(ws)('wrong-structure-evidence', value)


def test_page_subcheck_extent_never_closes_whole_report(ws):
    from report_agent.content_models import CheckResult
    cs, refs, snap, export, render, source, call = setup(ws, pages=2)
    call['args']['review_requirements'][0]['artifact_check_scopes'] = [
        {'requirement_index': 0, 'kind': 'render_pages', 'artifact_ref': render, 'pages': [1]}]
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        receipt = visual(cs, reviewer, render, export, source, 1)
        value = payload(snap, refs, render, [receipt], complete=False)
        value.items[0].check_results = [CheckResult(requirement_index=0,
            execution_state='completed', result='Page 1 observed', observation_indexes=[0])]
        artifact_review_tool(ws)('page-scope-partial', value)
        assert not reconcile(cs, reviewer.task_id)['execution_complete']
        value.items[0].execution_state = 'completed'
        with pytest.raises(ActionRejected, match='COVERAGE_INCOMPLETE'):
            artifact_review_tool(ws)('page-scope-false-complete', value)


def test_wrong_or_unbound_reference_page_cannot_complete(ws):
    cs, refs, snap, export, render, source, call = setup(ws, pages=1)
    call['args']['review_requirements'][0]['reference_page_bindings'] = [
        {'render_ref': render, 'page': 1, 'reference_page': 7, 'purpose': 'Body page style'}]
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        wrong = visual(cs, reviewer, render, export, source, 1)
        with pytest.raises(ActionRejected, match='COVERAGE_INCOMPLETE'):
            artifact_review_tool(ws)('wrong-pair', payload(snap, refs, render, [wrong]))
        paired = {'source_id': 's', 'source_sha256': cs.read(source)['payload']['file_digest'],
            'page': 7, 'coverage': 'full_page_image', 'crop': None}
        correct = visual(cs, reviewer, render, export, source, 1, presentation_reference=paired)
        artifact_review_tool(ws)('correct-pair', payload(snap, refs, render, [correct]))
        assert reconcile(cs, reviewer.task_id)['execution_complete']


def test_artifact_check_cannot_assign_foreign_export_or_nonexistent_pages(ws):
    cs, refs, snap, export, render, source, call = setup(ws, pages=1)
    call['args']['review_requirements'][0]['artifact_check_scopes'] = [
        {'requirement_index': 0, 'kind': 'render_pages', 'artifact_ref': render, 'pages': [2]}]
    with pytest.raises(ActionRejected, match='CHECK_PAGE_OUTSIDE_RENDER'):
        with delegated_task(ws, 'coordinator', call): pass
    call['args']['review_requirements'][0]['artifact_check_scopes'] = [
        {'requirement_index': 0, 'kind': 'export_structure', 'artifact_ref': export, 'pages': []}]
    with pytest.raises(ActionRejected, match='CHECK_ARTIFACT_OUTSIDE_ASSIGNED_SCOPE'):
        with delegated_task(ws, 'coordinator', call): pass


def test_partial_check_does_not_accept_empty_remaining_or_completed_remaining():
    from report_agent.content_models import CheckResult
    with pytest.raises(ValueError, match='UNFINISHED_CHECK_REQUIRES_REMAINING_REASON'):
        CheckResult(requirement_index=0, execution_state='partial', result='Incomplete')
    with pytest.raises(ValueError, match='COMPLETED_CHECK_REQUIRES'):
        CheckResult(requirement_index=0, execution_state='completed', result='Read', observation_indexes=[0], remaining='Not read')


def test_declared_page_extent_completes_task_without_completing_whole_render(ws):
    """Assigned page2 completion cannot become a whole two-page review pass."""
    cs,refs,snap,export,render,source,call=setup(ws,pages=2)
    call['args']['review_requirements'][0]['artifact_check_scopes']=[
        {'requirement_index':0,'kind':'render_pages','artifact_ref':render,'pages':[2]}]
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        receipt=visual(cs,reviewer,render,export,source,2)
        data=payload(snap,refs,render,[receipt],complete=False).model_dump()
        item=data['items'][0]
        item.update(checked_requirement_indexes=[0],verdict=None,
            check_results=[{'requirement_index':0,'execution_state':'completed',
                'result':'Observed assigned page2; no whole render conclusion.',
                'observation_indexes':[0],'remaining':''}],
            coverage={'checked':['Page2 comparison'],'unchecked':[],'blocked':[],
                'basis':'Actual page2 paired receipt'},
            outside_assignment_notes=['Unassigned page1 is not claimed inspected.'])
        saved=artifact_review_tool(ws)('page2-scope',ReviewSubmission.model_validate(data))
        current=reconcile(cs,reviewer.task_id)
        assert current['execution_complete']
        assert current['requirements'][0]['completion_extent']=='declared_artifact_subchecks'
        assert current['requirements'][0]['verdict'] is None
        assert cs.read(saved['result']['review_ref'])['payload']['items'][0]['execution_state']=='running'
        item.update(execution_state='completed',verdict='undetermined')
        with pytest.raises(ActionRejected,match='ARTIFACT_REVIEW_COVERAGE_INCOMPLETE'):
            artifact_review_tool(ws)('false-whole',ReviewSubmission.model_validate(data))


async def test_native_deepagents_tool_publication_uses_server_task_binding(ws):
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver, invoke
    from report_agent.hierarchical_tools import actor_for
    cs, refs, snap, export, render, source, call=setup(ws,kind='export')
    read_receipts=[]
    returned=[]
    def publish(messages):
        read=next(json.loads(m.content) for m in reversed(messages) if isinstance(m,ToolMessage) and m.name=='read_content_export')
        read_receipts.append(read['receipt_id'])
        return invoke('perform_assigned_artifact_review',operation_id='native-publication',
            scope_ids=['rule-comparison'],observation_receipts=[read['receipt_id']])
    def checker(messages):
        request=json.loads(messages[-1].content)
        task=cs.list_objects('DelegatedTask')[0]
        assert request['task_id']==task['ref']['id']
        assert request['snapshot_ref']==snap
        assert request['requirements'][0]['artifact_refs']==[export]
        assert request['evidence'][0]['receipt_id']==read_receipts[0]
        with ws.store.connect() as db:
            row=db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                (read_receipts[0],)).fetchone()
        assert request['evidence'][0]['actual_observation']==json.loads(row[1])
        value=payload(snap,refs,export,read_receipts,kind='export')
        return AIMessage(content=value.model_dump_json())
    def inspect_return(messages):
        result=next(json.loads(m.content) for m in reversed(messages) if isinstance(m,ToolMessage)
            and m.name=='perform_assigned_artifact_review')
        saved=cs.read(result['result']['review_ref'])
        assert result['review']==saved['payload']
        assert result['review_identity']['task_id']==saved['task_id']
        returned.append(result)
        return AIMessage(content='Scoped result saved by the independent comparison tool.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[call]),AIMessage(content='Return saved scoped artifact result.')],
        reviewer=[invoke('read_content_export',export_ref=export),publish,inspect_return],text_tool=[checker])
    # The read capability remains the native function; use a real Word export
    # so the receipt is produced by its normal byte/structure path.
    from report_agent.content_export import export_snapshot
    actual=export_snapshot(cs,actor_for('coordinator'),'native-word',snap)['result']['export_ref']
    export=actual
    call['args']['review_requirements'][0]['artifact_refs']=[actual]
    driver.scripts['reviewer'][0]=invoke('read_content_export',export_ref=actual)
    result=await run_report(ws,driver)
    assert result['last_error'] is None,result
    record=cs.list_objects('ReviewRecord')[0]
    assert record['payload']['runtime_identity']['mode']=='bounded-artifact-text-work-v1'
    assert record['task_id']==cs.list_objects('DelegatedTask')[0]['ref']['id']
    with ws.store.connect() as db:
        owner=db.execute('SELECT actor_id FROM content_observations WHERE id=?',(read_receipts[0],)).fetchone()[0]
    assert record['owner_id']==owner
    assert returned[0]['review']==record['payload'] and not returned[0]['reused']
    assert sum(role=='text_tool' for role,_,_ in driver.calls)==1
    assert reconcile(cs,record['task_id'])['execution_complete']
