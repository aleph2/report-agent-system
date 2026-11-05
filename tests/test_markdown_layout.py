"""Final public export and actual saved Markdown payload, offline only."""

import pytest
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from langchain_core.messages import AIMessage

from report_agent.errors import ActionRejected
from report_agent.deep_runtime import run_report
from test_hierarchical_content import ws, seed
from test_task_supervision import offline
from test_table_alignment_boundary import export_tool
from test_deep_runtime import Driver, invoke

CONTROLS={'table_line_spacing':1.5,'table_alignment':'center','table_cell_alignment':'center',
          'table_cell_first_line_indent_mm':0,'outer_border_style':'double','outer_border_width_pt':0.5}

def prepared(ws, actual=False, text=None):
    cs, actor, refs, _, all_refs=seed(ws)
    payload={
        'kind':'block','body':{'text':'Exact preface.\n\n| Name | Basis |\n|---|---|\n| A | **Emphasis** and *caution* |\n\nExact ending.'},
        'claim_kind':'structure','qualifiers':{}}
    if text is not None:
        payload['body']['text']=text
    added=cs.commit(actor,'embedded-tables',[{'client_key':'b','type':'ContentNode','payload':payload},
        {'client_key':'e','type':'Relation','payload':{'subject_ref':refs['root'],'object_ref':{'client_key':'b'},
            'predicate':'contains','position':2,'provenance_kind':'adopted_during_generation'}}])['result']['refs']
    snap=cs.freeze(actor,'markdown-snapshot',refs['root'],all_refs+list(added.values()))['result']['snapshot_ref']
    return cs, actor, refs, added['b'], snap

def check_tables(doc):
    assert doc.tables
    for table in doc.tables:
        assert table.alignment==WD_TABLE_ALIGNMENT.CENTER
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    assert p.alignment==WD_ALIGN_PARAGRAPH.CENTER
                    assert p.paragraph_format.line_spacing==1.5
                    assert p.paragraph_format.first_line_indent==0
        for side in ('top','left','bottom','right'):
            border=table._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:'+side))
            assert border.get(qn('w:val'))=='double' and border.get(qn('w:sz'))=='4'

@pytest.mark.parametrize('local',[False,True])
def test_actual_markdown_final_tool_and_saved_config_reexport(ws,local):
    cs,actor,refs,node,snap=prepared(ws)
    before=cs.read(node)
    raw={'toc':False,'nodes':[{'node_ref':node,**CONTROLS}]} if local else {'toc':False,**CONTROLS}
    result=export_tool(ws).invoke({'operation_id':'public-md','snapshot_ref':snap,'layout':raw})['result']
    path=ws.store.root/result['file_ref']
    doc=Document(path)
    check_tables(doc)
    cells=[[c.text for row in t.rows for c in row.cells] for t in doc.tables]
    stored=cs.read(result['export_ref'])['payload']['export_config']['layout']
    result2=export_tool(ws).invoke({'operation_id':'public-md-reexport','snapshot_ref':snap,'layout':stored})['result']
    doc2=Document(ws.store.root/result2['file_ref'])
    check_tables(doc2)
    assert [[c.text for row in t.rows for c in row.cells] for t in doc2.tables]==cells
    assert cs.read(node)==before and not cs.list_objects('ReviewRecord')

async def test_native_layout_task_uses_embedded_controls_without_authority_expansion(ws):
    ws.store.set('manifest',{**ws.store.manifest,'review_entrypoint':'delegated-reviewer-v1'})
    cs,actor,refs,node,snap=prepared(ws)
    before=cs.read(node)
    driver=Driver(coordinator=[invoke('task',subagent_type='layout',description='Use supplied table controls',layout_snapshot_ref=snap),
                               AIMessage(content='Actual export remains subject to independent review.')],
        layout=[invoke('export_content_snapshot',operation_id='native-md',snapshot_ref=snap,
                      layout={'toc':False,**CONTROLS}),AIMessage(content='Saved actual Word; no semantic acceptance.')])
    await run_report(ws,driver)
    exports=cs.list_objects('ExportArtifact')
    assert len(exports)==2
    word,= [e for e in exports if e['payload']['file_ref'].endswith('.docx')]
    book,= [e for e in exports if e['payload']['file_ref'].endswith('.xlsx')]
    assert word['owner_id'].startswith('content:layout:') and book['owner_id']==word['owner_id']
    assert word['payload']['snapshot_ref']==book['payload']['snapshot_ref']==snap
    assert book['payload']['export_config']['report_export_ref']==word['ref']
    doc=Document(ws.store.root/word['payload']['file_ref'])
    check_tables(doc)
    assert cs.read(node)==before and not cs.list_objects('ReviewRecord')

def test_markdown_content_emphasis_defaults_and_non_table_rejection(ws):
    cs,actor,refs,node,snap=prepared(ws,False)
    result=export_tool(ws).invoke({'operation_id':'defaults-md','snapshot_ref':snap,'layout':{'toc':False}})['result']
    doc=Document(ws.store.root/result['file_ref'])
    cell=doc.tables[0].cell(1,1)
    assert cell.text=='Emphasis and caution'
    assert any(r.text=='Emphasis' and r.bold for r in cell.paragraphs[0].runs)
    assert any(r.text=='caution' and r.italic for r in cell.paragraphs[0].runs)
    assert all(r.font.size.pt==10.5 for r in cell.paragraphs[0].runs)
    assert cell.paragraphs[0].alignment==WD_ALIGN_PARAGRAPH.LEFT
    assert 'Exact preface.' in [p.text for p in doc.paragraphs]
    assert 'Exact ending.' in [p.text for p in doc.paragraphs]
    with pytest.raises(ActionRejected,match='TABLE_CONTROLS_REQUIRE_TABLE'):
        export_tool(ws).invoke({'operation_id':'not-table','snapshot_ref':snap,
            'layout':{'nodes':[{'node_ref':refs['claim'],**CONTROLS}]}})


def test_actual_wide_markdown_landscape_is_scoped_and_round_trips(ws):
    cs,actor,refs,node,snap=prepared(ws)
    options={'toc':False,**CONTROLS,'nodes':[{'node_ref':node,'landscape':True,'table_font_size':10.5}]}
    first=export_tool(ws).invoke({'operation_id':'wide-md','snapshot_ref':snap,'layout':options})['result']
    source=ws.store.root/first['file_ref']
    saved=cs.read(first['export_ref'])['payload']['export_config']['layout']
    second=export_tool(ws).invoke({'operation_id':'wide-md-reexport','snapshot_ref':snap,'layout':saved})['result']
    for result in (first,second):
        doc=Document(ws.store.root/result['file_ref'])
        assert [s.page_width>s.page_height for s in doc.sections]==[False,True,False]
        check_tables(doc)


def test_final_parse_cannot_be_broken_by_paragraph_selector_and_mismatched_widths(ws):
    cs,actor,refs,node,snap=prepared(ws,False)
    with pytest.raises(ActionRejected,match='PARAGRAPH_CONTROL_INTERSECTS_MARKDOWN_TABLE'):
        export_tool(ws).invoke({'operation_id':'split-table','snapshot_ref':snap,'layout':{'nodes':[
            {'node_ref':node,'table_line_spacing':1.5,'paragraphs':[{'text':'| A | **Emphasis** and *caution* |'}]}]}})
    with pytest.raises(ActionRejected,match='LAYOUT_COLUMN_WEIGHTS_INVALID'):
        export_tool(ws).invoke({'operation_id':'wrong-columns','snapshot_ref':snap,'layout':{'nodes':[
            {'node_ref':node,'column_weights':[1,1,1]}]}})
    with pytest.raises(ActionRejected,match='LANDSCAPE_REQUIRES_TABLE_OR_FIGURE'):
        export_tool(ws).invoke({'operation_id':'no-table-landscape','snapshot_ref':snap,'layout':{'nodes':[
            {'node_ref':refs['claim'],'landscape':True}]}})


def test_heading_cannot_extract_first_row_and_destroy_real_table(ws):
    cs,actor,refs,node,snap=prepared(ws,False,text='| Name | Basis |\n|---|---|\n| A | Kept |')
    with pytest.raises(ActionRejected,match='HEADING_CONTROL_INTERSECTS_MARKDOWN_TABLE'):
        export_tool(ws).invoke({'operation_id':'table-heading','snapshot_ref':snap,'layout':{'nodes':[
            {'node_ref':node,'heading_level':2,'table_line_spacing':1.5}]}})
    result=export_tool(ws).invoke({'operation_id':'intact-table','snapshot_ref':snap,
        'layout':{'toc':False,**CONTROLS}})['result']
    check_tables(Document(ws.store.root/result['file_ref']))
