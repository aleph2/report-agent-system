"""Offline scope/publication/coverage checks, not visual model-quality evidence."""
import pytest
import json

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


def test_designated_customer_cannot_be_omitted_from_assignment(ws):
    cs, refs, snap, export, render, source, call=setup(ws)
    del call['args']['review_requirements'][0]['presentation_reference_ref']
    with pytest.raises(ActionRejected,match='REQUIRES_CUSTOMER_REFERENCE'):
        with delegated_task(ws,'coordinator',call): pass


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


@pytest.mark.parametrize('customer_instruction', [None, '客户协议样本：逐项核对设计与地勘差异，保留资料限定。'])
async def test_native_deepagents_tool_publication_uses_server_task_binding(ws, customer_instruction, record_property):
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver, invoke
    from report_agent.hierarchical_tools import actor_for
    cs, refs, snap, export, render, source, call=setup(ws,kind='export')
    instruction = None
    if customer_instruction:
        from report_agent.prompt_instructions import configure_report, save_instruction, release_instruction
        ws.store.set('context_policy','stateful-tools-v1')
        configure_report(ws.store,'fixture-report')
        instruction = save_instruction(ws.store, {'id':'customer-scope', 'topic':'scope', 'scope':'report',
            'report_id':'fixture-report', 'roles':['reviewer'], 'text':customer_instruction,
            'source_decision':'Protocol fixture operator input'})
        release_instruction(ws.store,'customer-scope',1,expected_active=None,reason='Fixture release')
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
        if instruction:
            assert request['commission']['scoped_instructions']['effective'] == [instruction]
        else:
            assert 'scoped_instructions' not in request['commission']
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
    from test_review_target_capability import retain_native_evidence
    path = retain_native_evidence(ws, driver, 'artifact-instructions-'+str(bool(instruction)),
        customer_instruction=instruction, saved_review=record)
    record_property('native_evidence_path',str(path))
