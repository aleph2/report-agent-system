from io import BytesIO
import pytest
from docx import Document
from docx.oxml.ns import qn
from pydantic import ValidationError
from report_agent.content_export import export_snapshot
from report_agent.content_layout import Typography
from report_agent.errors import ActionRejected
from test_hierarchical_content import ws,seed

def table_snapshot(ws):
    cs,actor,refs,snapshot,all_refs=seed(ws)
    added=cs.commit(actor,'new-tables',[{'client_key':'t','type':'ContentNode',
        'payload':{'kind':'table','body':{'columns':['项目','原文'], 'rows':[['岩性','强风化；未经确认条件保留']]},
                   'qualifiers':{},'claim_kind':'structure'}},
        {'client_key':'edge','type':'Relation','payload':{'subject_ref':refs['root'],
            'object_ref':{'client_key':'t'},'predicate':'contains','position':1,'provenance_kind':'adopted_during_generation'}}])['result']['refs']
    snap=cs.freeze(actor,'table-snap',refs['root'],all_refs+list(added.values()))['result']['snapshot_ref']
    return cs,actor,added['t'],snap,refs

@pytest.mark.parametrize('node_override',[False,True])
def test_parameters_execute_in_actual_docx_and_content_unchanged(ws,node_override):
    cs,actor,table,snap,refs=table_snapshot(ws)
    before=cs.read(snap)
    controls={'table_line_spacing':1.5,'outer_border_style':'double','outer_border_width_pt':0.5}
    options={'toc':False, 'nodes':[{'node_ref':table,**controls}]} if node_override else {'toc':False,**controls}
    result=export_snapshot(cs,actor,'render-table',snap,options)['result']
    doc=Document(BytesIO((ws.store.root/result['file_ref']).read_bytes()))
    t=doc.tables[0]
    assert t.cell(1,1).text=='强风化；未经确认条件保留'
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:assert p.paragraph_format.line_spacing==1.5
    for side in ('top','left','bottom','right'):
        b=t._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:'+side))
        assert b.get(qn('w:val'))=='double' and b.get(qn('w:sz'))=='4'
    assert cs.read(snap)==before

def test_default_and_partial_node_border_controls_inherit_global(ws):
    cs,actor,table,snap,refs=table_snapshot(ws)
    default=export_snapshot(cs,actor,'default',snap,{'toc':False})['result']
    doc=Document(BytesIO((ws.store.root/default['file_ref']).read_bytes()))
    assert doc.tables[0].cell(1,1).paragraphs[0].paragraph_format.line_spacing==1.15
    result=export_snapshot(cs,actor,'override',snap,{'toc':False,'table_line_spacing':1.5,
        'outer_border_style':'double','outer_border_width_pt':1.0,
        'nodes':[{'node_ref':table,'outer_border_width_pt':0.5,'table_line_spacing':2.0}]})['result']
    doc=Document(BytesIO((ws.store.root/result['file_ref']).read_bytes()))
    assert doc.tables[0].cell(1,1).paragraphs[0].paragraph_format.line_spacing==2.0
    border=doc.tables[0]._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:top'))
    assert border.get(qn('w:val'))=='double' and border.get(qn('w:sz'))=='4'
    with pytest.raises(ActionRejected,match='TABLE_CONTROLS_REQUIRE_TABLE'):
        export_snapshot(cs,actor,'ignored',snap,{'nodes':[{'node_ref':refs['claim'],'table_line_spacing':1.5}]})

def test_hanging_indent_executes_and_rejects_ambiguous_first_line():
    from report_agent.content_layout import apply_typography
    d=Document();p=d.add_paragraph('原文不变')
    apply_typography(p,Typography(left_indent_mm=12.7,hanging_indent_mm=12.7))
    assert abs(p.paragraph_format.left_indent.mm-12.7)<0.05
    assert abs(p.paragraph_format.first_line_indent.mm+12.7)<0.05
    for argument in [{'first_line_indent_mm':2},{'first_line_indent_chars':2}]:
        with pytest.raises(ValidationError):Typography(hanging_indent_mm=12.7,**argument)
