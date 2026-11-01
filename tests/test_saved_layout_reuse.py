"""Exact saved layout reuse through native registration and real DOCX bytes; offline."""
import json
from copy import deepcopy
from zipfile import ZipFile

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_export import export_snapshot
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.layout_revision import status
from report_agent.store import digest
from test_hierarchical_content import ws, seed
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, observation


def word_parts(ws, result):
    with ZipFile(ws.store.root / result['file_ref']) as z:
        return {n:z.read(n) for n in z.namelist() if n.startswith('word/')}


async def test_native_saved_exact_not_latest_layout_real_word_and_receipt(ws):
    cs, actor, refs, snap, members = seed(ws)
    ws.store.set('layout_revision_limit', None)
    layout = {'font_size':13, 'toc':False, 'table_line_spacing':1.5,
              'outer_border_style':'double', 'nodes':[{'node_ref':refs['root'], 'page_break_before':True}]}
    first = export_snapshot(cs,actor,'source',snap,layout)['result']
    original = deepcopy(cs.read(first['export_ref']))
    export_snapshot(cs,actor,'newer-different',snap,{'font_size':14})
    target = cs.derive_snapshot(actor,'same-body-new-snapshot',snap,[])['result']['snapshot_ref']
    activate(ws)
    saved = {}
    def done(messages):
        response = observation(messages,'export_content_snapshot')
        assert response['ok'], response
        saved.update(response['result'])
        return AIMessage(content='Synthetic exact reuse complete; no semantic judgment.')
    driver = Driver(coordinator=[invoke('export_content_snapshot', operation_id='native-reuse',
        snapshot_ref=target,layout_from_export_ref=first['export_ref']),done])
    await run_report(ws,driver)
    schema = next(t for t in driver.bindings['coordinator'][0] if t['name']=='export_content_snapshot')
    assert 'layout_from_export_ref' in schema['parameters']['properties']
    assert 'never remaps node versions' in schema['description']
    assert all(x in json.dumps(schema['parameters']['properties']['layout_from_export_ref']) for x in ('id','version','type'))
    record = cs.read(saved['export_ref'])
    config = record['payload']['export_config']
    assert config['layout'] == original['payload']['export_config']['layout']
    assert record['payload']['snapshot_ref'] == target
    assert record['owner_id'] == actor.id
    assert saved['layout_source'] == config['layout_source'] == {
        'export_ref':first['export_ref'], 'layout_digest':digest(config['layout'])}
    assert cs.read(first['export_ref']) == original
    assert word_parts(ws, saved) == word_parts(ws, first)
    assert b'w:val="26"' in word_parts(ws,saved)['word/styles.xml']
    again = export_snapshot(cs,actor,'native-reuse',target,layout_from_export_ref=first['export_ref'])
    assert again['result'] == saved
    expected = digest({'actor':actor.__dict__,'request':{'export':target,'layout_from_export_ref':first['export_ref']}})
    assert cs.receipt(actor,'native-reuse')['request_digest'] == expected
    assert not cs.list_objects('ReviewRecord')
    with ws.store.connect() as db:
        assert status(db)['revisions_used'] == 2  # selecting an older config is not a reset.


@pytest.mark.parametrize('layout', [None, {}, {'toc':False}])
def test_old_request_identity_and_result_unchanged(ws,layout):
    cs, actor, _, snap, _ = seed(ws)
    result = export_snapshot(cs,actor,'old-call',snap,layout)
    request = {'export':snap}
    if layout is not None: request['layout'] = layout
    assert cs.receipt(actor,'old-call')['request_digest'] == digest({'actor':actor.__dict__,'request':request})
    assert set(result['result']) == {'export_ref','mapping_ref','file_ref','file_digest'}
    assert export_snapshot(cs,actor,'old-call',snap,layout) == result


@pytest.mark.parametrize('scenario', ['both_empty','both_values','not_export','xlsx','missing_config','missing_ref','invalid_config'])
def test_invalid_sources_fail_atomically_in_normal_operation(ws,scenario):
    cs,actor,refs,snap,_ = seed(ws)
    source = export_snapshot(cs,actor,'source',snap)['result']['export_ref']
    options = None
    if scenario.startswith('both'): options = {} if scenario=='both_empty' else {'toc':False}
    elif scenario=='not_export': source = refs['root']
    elif scenario=='missing_ref': source = {**source,'id':'00000000-0000-0000-0000-000000000000'}
    else:
        p = deepcopy(cs.read(source)['payload'])
        if scenario=='xlsx': p['file_ref'] = 'content-assets/synthetic.xlsx'
        elif scenario=='missing_config': p['export_config'].pop('layout')
        elif scenario=='invalid_config': p['export_config']['layout']['replace_text'] = 'forbidden'
        with ws.store.connect() as db:
            source = cs._insert(db,actor,'ExportArtifact',p)
    before = len(cs.list_objects())
    for _ in range(2):
        with pytest.raises(ActionRejected):
            export_snapshot(cs,actor,scenario,snap,options,source)
    assert len(cs.list_objects()) == before
    assert cs.receipt(actor,scenario)['state'] == 'known_failure'


def test_saved_node_controls_do_not_remap_to_new_node_or_version(ws):
    cs,actor,refs,snap,members = seed(ws)
    source = export_snapshot(cs,actor,'source',snap,{'nodes':[{'node_ref':refs['root'],'page_break_before':True}]})['result']['export_ref']
    revised = cs.commit(actor,'new-root',[{'client_key':'root','type':'ContentNode','previous_ref':refs['root'],
        'payload':cs.read(refs['root'])['payload']}])['result']['refs']['root']
    edge = cs.read(refs['edge'])
    new_edge = cs.commit(actor,'new-edge',[{'client_key':'edge','type':'Relation','previous_ref':refs['edge'],
        'payload':{**edge['payload'],'subject_ref':revised}}])['result']['refs']['edge']
    target = cs.derive_snapshot(actor,'new-version',snap,[],[
        {'previous_ref':refs['root'],'new_ref':revised},{'previous_ref':refs['edge'],'new_ref':new_edge}])['result']['snapshot_ref']
    before = len(cs.list_objects('ExportArtifact'))
    with pytest.raises(ActionRejected,match='LAYOUT_REQUIRES_UNIQUE_SNAPSHOT_NODE'):
        export_snapshot(cs,actor,'stale-control',target,layout_from_export_ref=source)
    assert len(cs.list_objects('ExportArtifact')) == before
    assert cs.receipt(actor,'stale-control')['state']=='known_failure'


def test_owner_and_layout_delegation_permissions_preserved(ws):
    cs,actor,refs,snap,members = seed(ws)
    source = export_snapshot(cs,actor,'source',snap)['result']['export_ref']
    with pytest.raises(ActionForbidden,match='snapshot owner'):
        export_snapshot(cs,actor_for('writer'),'foreign-target',snap,layout_from_export_ref=source)
    with pytest.raises(ActionForbidden,match='export producer'):
        export_snapshot(cs,actor_for('reviewer'),'reviewer',snap,layout_from_export_ref=source)
    other = cs.freeze(actor,'other',refs['root'],members)['result']['snapshot_ref']
    with delegated_task(ws,'coordinator',{'id':'layout-reuse','args':{'subagent_type':'layout','description':'Reuse exact layout','layout_snapshot_ref':snap}}) as (_, layout):
        reused = export_snapshot(cs,layout,'delegated',snap,layout_from_export_ref=source)['result']
        assert cs.read(reused['export_ref'])['owner_id']==layout.id
        assert cs.read(source)['owner_id']==actor.id
        with pytest.raises(ActionForbidden,match='snapshot owner'):
            export_snapshot(cs,layout,'other-target',other,layout_from_export_ref=source)
    assert 'export_content_snapshot' not in {t.__name__ for t in content_tools(ws,'reviewer')}


def test_reuse_cannot_reset_revision_limit_or_change_receipt_intent(ws):
    ws.store.set('layout_revision_limit', 1)
    cs,actor,_,snap,_ = seed(ws)
    first = export_snapshot(cs,actor,'first',snap)['result']['export_ref']
    second = export_snapshot(cs,actor,'second',snap,{'toc':False})['result']['export_ref']
    export_snapshot(cs,actor,'current',snap,layout_from_export_ref=second)
    with pytest.raises(ActionRejected,match='LAYOUT_REVISION_LIMIT_REACHED'):
        export_snapshot(cs,actor,'return-old',snap,layout_from_export_ref=first)
    with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
        export_snapshot(cs,actor,'current',snap,layout_from_export_ref=first)


def test_reused_table_spacing_border_and_column_controls_are_in_actual_bytes(ws):
    from test_content_workbook import prepared
    from docx import Document
    from docx.oxml.ns import qn
    cs,actor,_,snap,sheets = prepared(ws,'Actual issue')
    layout = {'toc':False,'table_line_spacing':1.5,'outer_border_style':'double',
              'nodes':[{'node_ref':sheets[0]['table_ref'],'column_weights':[1,3]}]}
    first = export_snapshot(cs,actor,'table-source',snap,layout)['result']
    reused = export_snapshot(cs,actor,'table-reuse',snap,layout_from_export_ref=first['export_ref'])['result']
    assert word_parts(ws,first) == word_parts(ws,reused)
    table = Document(ws.store.root / reused['file_ref']).tables[0]
    assert table.columns[1].width > table.columns[0].width * 2
    assert any(n.get(qn('w:line')) == '360' for n in table._tbl.iter(qn('w:spacing')))
    borders = table._tbl.tblPr.find(qn('w:tblBorders'))
    assert all(borders.find(qn('w:'+side)).get(qn('w:val'))=='double' for side in ('top','bottom','left','right'))
