"""Offline final-tool/real-DOCX checks against the production package."""
import pytest
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from report_agent.content_layout import LayoutOptions
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.layout_capabilities import capabilities
from test_layout_table_controls import ws, table_snapshot


def export_tool(ws):
    function = next(t for t in business_tools(ws, 'coordinator', None, None)
                    if t.__name__ == 'export_content_snapshot')
    return StructuredTool.from_function(function)


@pytest.mark.parametrize('refresh', [False, True])
@pytest.mark.parametrize('override', [False, True])
def test_final_tool_alignment_and_indent_survive_reexport_and_office(ws, refresh, override):
    if refresh and not capabilities()['directory_refresh']['available']:
        pytest.skip('Native LibreOffice/UNO unavailable')
    cs, actor, table, snap, refs = table_snapshot(ws)
    before = cs.read(snap)
    controls = {'table_alignment': 'center', 'table_cell_alignment': 'center',
                'table_cell_first_line_indent_mm': 0}
    raw = {'toc': refresh, 'refresh_toc': refresh,
           'nodes': [{'node_ref': refs['claim'], 'paragraphs': [{
               'text': 'For adopted class B use 70.', 'heading_level': 2}]}],
           'styles': [{'name': 'Normal', 'alignment': 'justify', 'first_line_indent_chars': 2}]}
    if override:
        raw.update(table_alignment='left', table_cell_alignment='right', table_cell_first_line_indent_mm=4)
        raw['nodes'].append({'node_ref': table, **controls})
    else:
        raw.update(controls)
    tool = export_tool(ws)
    schema = convert_to_openai_tool(tool)['function']['parameters']
    for field in controls:
        assert field in str(schema), 'Effective public tool lost the control schema'
    normalized = LayoutOptions.model_validate(raw).model_dump()
    assert LayoutOptions.model_validate(normalized).model_dump() == normalized
    first = tool.invoke({'operation_id': 'align-first', 'snapshot_ref': snap, 'layout': raw})['result']
    saved = cs.read(first['export_ref'])['payload']['export_config']['layout']
    second = tool.invoke({'operation_id': 'align-reuse', 'snapshot_ref': snap, 'layout': saved})['result']
    for result in (first, second):
        doc = Document(ws.store.root/result['file_ref'])
        assert doc.tables[0].alignment == WD_TABLE_ALIGNMENT.CENTER
        for row in doc.tables[0].rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
                    assert paragraph.paragraph_format.first_line_indent == 0
        assert doc.styles['Normal'].paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
        assert doc.styles['Normal'].paragraph_format.first_line_indent.pt == 24
        assert doc.tables[0].cell(1, 1).text == '强风化；未经确认条件保留'
    assert cs.read(snap) == before


def test_omitted_controls_preserve_old_inheritance(ws):
    _, _, table, snap, _ = table_snapshot(ws)
    result = export_tool(ws).invoke({'operation_id': 'unchanged-defaults', 'snapshot_ref': snap,
        'layout': {'toc': False, 'styles': [{'name': 'Normal', 'alignment': 'justify',
                                          'first_line_indent_chars': 2}]}})['result']
    doc = Document(ws.store.root/result['file_ref'])
    assert doc.tables[0].alignment is None
    assert doc.tables[0].cell(1, 0).paragraphs[0].alignment is None
    assert doc.tables[0].cell(1, 0).paragraphs[0].paragraph_format.first_line_indent is None


@pytest.mark.parametrize('field,value', [('table_alignment', 'center'),
    ('table_cell_alignment', 'center'), ('table_cell_first_line_indent_mm', 0)])
def test_controls_cannot_silently_apply_to_non_table_nodes(ws, field, value):
    _, _, _, snap, refs = table_snapshot(ws)
    with pytest.raises(ActionRejected, match='TABLE_CONTROLS_REQUIRE_TABLE'):
        export_tool(ws).invoke({'operation_id': 'bad-'+field, 'snapshot_ref': snap,
            'layout': {'nodes': [{'node_ref': refs['claim'], field: value}]}})
