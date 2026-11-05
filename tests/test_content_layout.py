from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn

from test_hierarchical_content import ws, seed
from report_agent.content_export import export_snapshot
from report_agent.content_tasks import delegated_task, bound_actor
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.errors import ActionForbidden, ActionRejected


def test_layout_delegation_export_only_and_snapshot_grant(ws):
    cs, owner, refs, snap, _ = seed(ws)
    call = {'id': 'layout-task', 'args': {'subagent_type': 'layout', 'description': 'Fix widths', 'layout_snapshot_ref': snap}}
    with delegated_task(ws, 'coordinator', call) as (native, actor):
        assert 'layout_snapshot_ref' not in native['args']
        assert bound_actor(ws, 'layout', None) == actor
        names = {t.__name__ for t in content_tools(ws, 'layout')}
        assert 'export_content_snapshot' in names
        assert not names & {'commit_objects', 'freeze_snapshot', 'submit_review', 'select_content_delivery'}
        result = export_snapshot(cs, actor, 'layout-export', snap, {'toc': False})['result']
        assert cs.read(result['export_ref'])['owner_id'] == actor.id
        with pytest.raises(ActionForbidden):
            cs.commit(actor, 'illegal-write', [{'client_key': 'x', 'type': 'ContentNode', 'payload': cs.read(refs['claim'])['payload']}])
        other = cs.freeze(owner, 'other', refs['root'], cs.read(snap)['payload']['refs'])['result']['snapshot_ref']
        with pytest.raises(ActionForbidden):
            export_snapshot(cs, actor, 'outside', other)
    with pytest.raises(ActionForbidden):
        bound_actor(ws, 'layout', None)
    with pytest.raises(ActionRejected):
        with delegated_task(ws, 'coordinator', {'id': 'no-grant', 'args': {'subagent_type': 'layout', 'description': 'x'}}):
            pass


def test_layout_preserves_conditions_and_rejects_unknown_options(ws):
    cs, owner, refs, snap, _ = seed(ws)
    before = cs.read(snap)
    with pytest.raises(ActionRejected):
        export_snapshot(cs, owner, 'bad', snap, {'replace_text': 'new conclusion'})
    with pytest.raises(ActionRejected):
        export_snapshot(cs, owner, 'bad-ref', snap, {'nodes': [{'node_ref': refs['k']}]})
    result = export_snapshot(cs, owner, 'good', snap, {'toc': False})['result']
    doc = Document(BytesIO((ws.store.root/result['file_ref']).read_bytes()))
    assert 'For adopted class B use 70.' in '\n'.join(p.text for p in doc.paragraphs)
    assert 'condition：class B' in '\n'.join(p.text for p in doc.paragraphs)
    assert cs.read(snap) == before


def test_table_caption_widths_header_and_heading(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    additions = cs.commit(actor, 'table-content', [
        {'client_key': 't', 'type': 'ContentNode', 'payload': {'kind':'table',
            'body': {'columns':['Value','Basis'], 'rows':[['70','Pending verification']]},
            'qualifiers': {'title':'Score', 'number':'Table 1', 'revision':'internal', 'condition':'unverified'}, 'claim_kind':'structure'}},
        {'client_key':'e','type':'Relation','payload':{'subject_ref':refs['root'], 'object_ref':{'client_key':'t'},'predicate':'contains','position':1,'provenance_kind':'adopted_during_generation'}}
    ])['result']['refs']
    snap = cs.freeze(actor, 'table-snapshot', refs['root'], all_refs+list(additions.values()))['result']['snapshot_ref']
    result = export_snapshot(cs, actor, 'table-export', snap, {'toc':False,'nodes':[{'node_ref':additions['t'],'column_weights':[1,3],'landscape':True}]})['result']
    doc=Document(BytesIO((ws.store.root/result['file_ref']).read_bytes()))
    table=doc.tables[0]
    assert table._tbl.getprevious().tag == qn('w:p')
    assert 'Table 1 Score' in ''.join(table._tbl.getprevious().itertext())
    assert table.rows[0]._tr.find('.//'+qn('w:tblHeader')) is not None
    assert table.columns[1].width > table.columns[0].width * 2
    assert any(s.page_width > s.page_height for s in doc.sections)
    text='\n'.join(p.text for p in doc.paragraphs)
    assert 'revision：internal' not in text
    assert 'condition：unverified' in text


async def test_native_layout_task_returns_export_to_coordinator(ws, monkeypatch):
    import httpx
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke
    def denied(*args, **kwargs):
        pytest.fail('No network in layout protocol test')
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setenv('LANGSMITH_TRACING','false')
    ws.store.set('manifest', {**ws.store.manifest, 'review_entrypoint':'delegated-reviewer-v1'})
    cs, owner, refs, snap, _ = seed(ws)
    driver = Driver(coordinator=[invoke('task', subagent_type='layout', description='Fix layout only', layout_snapshot_ref=snap), AIMessage(content='Export returned; independent review remains.')],
        layout=[invoke('export_content_snapshot', operation_id='native-layout', snapshot_ref=snap, layout={'toc':False}), AIMessage(content='Saved export; not approved.')])
    await deep_runtime.run_report(ws, driver)
    exports=cs.list_objects('ExportArtifact')
    assert len(exports)==2
    assert exports[0]['created_by'].startswith('content:layout:')
    assert not cs.list_objects('ReviewRecord')
    assert cs.read(refs['claim'])['payload']['body']['text']=='For adopted class B use 70.'


def test_interior_heading_preserves_source_and_enters_toc(ws):
    cs, actor, refs, _, all_refs = seed(ws)
    extra = cs.commit(actor, 'interior', [
        {'client_key':'b','type':'ContentNode','payload':{'kind':'block','body':{'text':'Context remains.\n4.3.1 Existing heading\nValue remains 70.'},'qualifiers':{},'claim_kind':'structure'}},
        {'client_key':'e','type':'Relation','payload':{'subject_ref':refs['root'],'object_ref':{'client_key':'b'},'predicate':'contains','position':2,'provenance_kind':'adopted_during_generation'}}])['result']['refs']
    snap = cs.freeze(actor,'interior-snapshot',refs['root'],all_refs+list(extra.values()))['result']['snapshot_ref']
    opts={'toc_depth':3,'nodes':[{'node_ref':extra['b'],'paragraphs':[{'text':'4.3.1 Existing heading','heading_level':3}]}]}
    result = export_snapshot(cs,actor,'interior-export',snap,opts)['result']
    doc=Document(BytesIO((ws.store.root/result['file_ref']).read_bytes()))
    assert any(p.text=='4.3.1 Existing heading' and p.style.name=='Heading 3' for p in doc.paragraphs)
    assert sum(p.text=='4.3.1 Existing heading' for p in doc.paragraphs)==2
    assert 'Context remains.' in [p.text for p in doc.paragraphs]
    assert 'Value remains 70.' in [p.text for p in doc.paragraphs]
    opts['nodes'][0]['paragraphs'][0]['text']='Replacement heading'
    with pytest.raises(ActionRejected):export_snapshot(cs,actor,'bad-interior',snap,opts)


def test_capability_request_is_saved_scoped_feedback(ws):
    from report_agent.layout_capabilities import request_extension
    cs, actor, refs, snap, _=seed(ws)
    with delegated_task(ws,'coordinator',{'id':'cap-task','args':{'subagent_type':'layout','description':'format','layout_snapshot_ref':snap}}) as (_,layout):
        saved=request_extension(cs,layout,'cap-request',snap,'Cannot update endnotes',['Read capabilities and tried current controls'],'endnote placement',['page 2'])['result']
        record=cs.read(saved['handling_ref'])
        assert record['payload']['resume_task_id']==layout.task_id
        assert record['payload']['kind']=='layout_capability_request'
        assert record in cs.feedback(actor)['result']['records']
        other=cs.freeze(actor,'cap-other',refs['root'],cs.read(snap)['payload']['refs'])['result']['snapshot_ref']
        with pytest.raises(ActionForbidden):request_extension(cs,layout,'cap-bad',other,'x',['x'],'x',['x'])


def test_native_directory_refresh_preserves_content_and_remaps(ws):
    from report_agent.layout_capabilities import capabilities
    if not capabilities()['directory_refresh']['available']:
        pytest.skip('Native LibreOffice/UNO is not installed')
    cs, actor, refs, snap, _=seed(ws)
    result=export_snapshot(cs,actor,'native-toc',snap,{'refresh_toc':True,'nodes':[{'node_ref':refs['claim'],
        'paragraphs':[{'text':'For adopted class B use 70.','heading_level':2}]}]})['result']
    payload=cs.read(result['export_ref'])['payload']
    assert payload['export_config']['finalization']['owned_processes_exited']
    assert payload['export_config']['finalization']['toc']
    mapping=cs.read(result['mapping_ref'])['payload']
    assert all(m['block_start'] < m['block_stop'] for m in mapping['anchor_records'])


def test_directory_failure_remains_receipted_without_nested_database_write(ws, monkeypatch):
    from types import SimpleNamespace
    from report_agent import layout_capabilities as cap
    cs, actor, refs, snap, _ = seed(ws)
    monkeypatch.setattr(cap, 'capabilities', lambda: {'directory_refresh': {'available': True}})
    calls = []
    def fail(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stderr=b'converter failed')
    monkeypatch.setattr(cap.subprocess, 'run', fail)
    monkeypatch.setattr(ws.store, 'event', lambda *_: pytest.fail('nested write in export transaction'))
    for _ in range(2):
        with pytest.raises(ActionRejected, match='DIRECTORY_REFRESH_FAILED'):
            export_snapshot(cs, actor, 'failed-directory', snap, {'refresh_toc': True})
    assert len(calls) == 1
    assert cs.receipt(actor, 'failed-directory')['state'] == 'known_failure'
    assert not cs.list_objects('ExportArtifact')
    assert not cs.list_objects('MappingArtifact')
    assert list((ws.store.root / 'diagnostics').glob('*.json'))


def test_refresh_requires_a_root_that_emits_a_directory(ws, monkeypatch):
    from report_agent import layout_capabilities as cap
    cs, actor, refs, snap, _ = seed(ws)
    old = cs.read(refs['root'])
    changed = cs.commit(actor, 'block-root', [{'client_key': 'root', 'type': 'ContentNode',
        'payload': {**old['payload'], 'kind': 'block'}, 'previous_ref': refs['root']}])['result']['refs']['root']
    requirements = [r for r in cs.read(snap)['payload']['refs'] if r['type'] in {'Criterion', 'Requirement'}]
    block_snapshot = cs.freeze(actor, 'block-snapshot', changed, [changed, *requirements])['result']['snapshot_ref']
    monkeypatch.setattr(cap, 'refresh_directory', lambda *_: pytest.fail('must reject before conversion'))
    with pytest.raises(ActionRejected, match='DIRECTORY_REFRESH_REQUIRES_REPORT_ROOT'):
        export_snapshot(cs, actor, 'block-directory', block_snapshot, {'refresh_toc': True})
    assert cs.receipt(actor, 'block-directory')['state'] == 'known_failure'
