"""Actual DOCX checks for presentation controls, without model-quality claims."""
from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH

from test_hierarchical_content import ws, seed
from report_agent.content_export import export_snapshot
from report_agent.errors import ActionRejected


def document(ws, result):
    return Document(BytesIO((ws.store.root / result['file_ref']).read_bytes()))


def test_v7_composite_header_retains_each_source_binding(ws):
    cs, actor, refs, snap, _ = seed(ws)
    layout = {'toc': False, 'header_parts': [{'node_ref': refs['root'], 'text': 'Report',
        'position': 'left', 'additional_lines': [{'node_ref': refs['claim'], 'text': 'For adopted class B use 70.'}]}]}
    before = cs.read(snap)
    result = export_snapshot(cs, actor, 'composite', snap, layout)['result']
    assert document(ws, result).sections[0].header.paragraphs[0].text == 'Report For adopted class B use 70.'
    assert cs.read(snap) == before
    assert cs.read(result['export_ref'])['payload']['export_config']['layout']['header_parts'][0]['additional_lines'][0]['node_ref'] == refs['claim']
    layout['header_parts'][0]['additional_lines'][0]['text'] = 'Invented stage'
    with pytest.raises(ActionRejected, match='UNIQUE_EXACT_LINE'):
        export_snapshot(cs, actor, 'composite-forgery', snap, layout)
    layout['header_parts'][0]['additional_lines'][0] = {'node_ref': {**refs['claim'], 'version': 999}, 'text': 'For adopted class B use 70.'}
    with pytest.raises(ActionRejected, match='RENDERED_BODY_NODE'):
        export_snapshot(cs, actor, 'composite-wrong-version', snap, layout)


def test_v7_exact_line_height_and_em_indent(ws):
    from docx.enum.text import WD_LINE_SPACING
    cs, actor, refs, snap, _ = seed(ws)
    result = export_snapshot(cs, actor, 'exact-spacing', snap, {'toc': False,
        'styles': [{'name': 'Normal', 'font_size': 14, 'first_line_indent_chars': 4.5, 'line_spacing_pt': 55}],
        'nodes': [{'node_ref': refs['root'], 'paragraphs': [{'text': 'Report', 'font_size': 20, 'first_line_indent_chars': 2, 'line_spacing_pt': 30}]}]})['result']
    doc = document(ws, result)
    style = doc.styles['Normal'].paragraph_format
    assert style.first_line_indent.pt == 63
    assert style.line_spacing.pt == 55 and style.line_spacing_rule == WD_LINE_SPACING.EXACTLY
    title = next(p for p in doc.paragraphs if p.text == 'Report')
    assert title.paragraph_format.first_line_indent.pt == 40
    assert title.paragraph_format.line_spacing.pt == 30
    from report_agent.content_layout import Typography
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Typography(first_line_indent_mm=8, first_line_indent_chars=4.5)


@pytest.mark.parametrize('reverse', [False, True])
def test_v7_em_indent_uses_final_inherited_font_independent_of_order(reverse):
    from report_agent.content_layout import LayoutOptions, setup
    controls = [{'name':'Header','first_line_indent_chars':2},
                {'name':'Footer','first_line_indent_chars':2}, {'name':'Normal','font_size':14}]
    doc = Document()
    setup(doc, LayoutOptions.model_validate({'styles':list(reversed(controls)) if reverse else controls}))
    assert doc.styles['Header'].paragraph_format.first_line_indent.pt == 28
    assert doc.styles['Footer'].paragraph_format.first_line_indent.pt == 28
    assert doc.sections[0].footer.paragraphs[0].paragraph_format.first_line_indent.pt == 28


@pytest.mark.parametrize('toc', [False, True])
def test_v7_cover_alignment_isolated_and_mapped(ws, toc):
    cs, actor, refs, snap, _ = seed(ws)
    before = cs.read(snap)
    result = export_snapshot(cs, actor, 'cover-center', snap, {'toc': toc,
        'cover_vertical_alignment': 'center', 'hide_first_page_header_footer': True})['result']
    doc = document(ws, result)
    assert len(doc.sections) == 2
    assert doc.tables[0].cell(0,0)._tc.tcPr.find(qn('w:vAlign')).get(qn('w:val')) == 'center'
    assert doc.sections[1]._sectPr.find(qn('w:vAlign')).get(qn('w:val')) == 'top'
    assert [s.different_first_page_header_footer for s in doc.sections] == [True, False]
    assert [p.text for p in doc.tables[0].cell(0,0).paragraphs] == ['Report']
    assert sum(p.text == 'For adopted class B use 70.' for p in doc.paragraphs) == 1
    mapping = cs.read(result['mapping_ref'])['payload']['anchor_records']
    from report_agent.content_layout import remap_blocks
    remap_blocks(doc, mapping)
    assert all(m['block_start'] < m['block_stop'] for m in mapping)
    assert cs.read(snap) == before


def test_v7_cover_container_allows_nested_table_and_keeps_terminal_paragraph():
    from report_agent.content_layout import LayoutOptions, setup, wrap_cover
    doc = Document()
    options = LayoutOptions(cover_vertical_alignment='center')
    setup(doc, options)
    doc.add_paragraph('Cover')
    doc.add_table(rows=1, cols=1).cell(0,0).text = 'Preserved table content'
    wrap_cover(doc, 0, options)
    cell = doc.tables[0].cell(0,0)
    assert cell._tc[-1].tag == qn('w:p')
    assert cell.tables[0].cell(0,0).text == 'Preserved table content'


def test_cover_style_line_override_and_source_header(ws):
    cs, actor, refs, snap, _ = seed(ws)
    before = cs.read(snap)
    result = export_snapshot(cs, actor, 'typography', snap, {
        'toc': False,
        'styles': [{'name': 'Title', 'font_size': 28, 'alignment': 'center', 'east_asia_font': '宋体'}],
        'nodes': [{'node_ref': refs['root'], 'paragraphs': [
            {'text': 'Report', 'font_size': 32, 'alignment': 'right', 'font_family': 'Arial', 'bold': False}]}],
        'header': {'node_ref': refs['root'], 'text': 'Report', 'alignment': 'center', 'font_size': 10}
    })['result']
    doc = document(ws, result)
    title = next(p for p in doc.paragraphs if p.text == 'Report')
    assert title.style.font.size.pt == 28
    assert title.style.element.rPr.rFonts.get(qn('w:eastAsia')) == '宋体'
    assert title.runs[0].font.size.pt == 32
    assert title.runs[0].font.name == 'Arial'
    assert title.runs[0].bold is False
    assert title.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert sum(p.text == 'Report' for p in doc.paragraphs) == 1
    header = doc.sections[0].header.paragraphs[0]
    assert header.text == 'Report' and header.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert cs.read(result['export_ref'])['payload']['export_config']['layout']['header']['node_ref'] == refs['root']
    assert cs.read(snap) == before


@pytest.mark.parametrize('mode', ['dependency', 'replacement', 'wrong_version'])
def test_header_cannot_promote_dependency_or_invent_content(ws, mode):
    cs, actor, refs, snap, all_refs = seed(ws)
    if mode == 'dependency':
        dep = cs.commit(actor, 'dep', [{'client_key': 'd', 'type': 'ContentNode', 'payload': {
            'kind': 'claim', 'body': {'text': 'Not adopted for presentation'}, 'qualifiers': {}, 'claim_kind': 'structure'}}])['result']['refs']['d']
        snap = cs.freeze(actor, 'with-dep', refs['root'], all_refs + [dep])['result']['snapshot_ref']
        header = {'node_ref': dep, 'text': 'Not adopted for presentation'}
    elif mode == 'replacement':
        header = {'node_ref': refs['root'], 'text': 'Approved engineering report'}
    else:
        header = {'node_ref': {**refs['root'], 'version': 2}, 'text': 'Report'}
    with pytest.raises(ActionRejected):
        export_snapshot(cs, actor, 'bad-header', snap, {'header': header})
    assert not cs.list_objects('ExportArtifact')
    assert not list((ws.store.root / 'content-assets').glob('*.docx'))


def test_margins_apply_to_landscape_table_and_restored_section(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    additions = cs.commit(actor, 'table', [
        {'client_key': 't', 'type': 'ContentNode', 'payload': {'kind': 'table',
            'body': {'columns': ['A', 'B'], 'rows': [['1', '2']]}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'e', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 't'}, 'predicate': 'contains', 'position': 1, 'provenance_kind': 'adopted_during_generation'}}
    ])['result']['refs']
    snap = cs.freeze(actor, 'table-snap', refs['root'], all_refs + list(additions.values()))['result']['snapshot_ref']
    result = export_snapshot(cs, actor, 'margins', snap, {'toc': False,
        'top_margin_mm': 25.4, 'bottom_margin_mm': 24, 'left_margin_mm': 31.8, 'right_margin_mm': 15,
        'header': {'node_ref': refs['root'], 'text': 'Report'},
        'nodes': [{'node_ref': additions['t'], 'landscape': True}]})['result']
    doc = document(ws, result)
    for section in doc.sections:
        assert section.top_margin.mm == pytest.approx(25.4, abs=.03)
        assert section.left_margin.mm == pytest.approx(31.8, abs=.03)
        assert section.right_margin.mm == pytest.approx(15, abs=.03)
        assert section.header.paragraphs[0].text == 'Report'
    assert sum(c.width.mm for c in doc.tables[0].columns) == pytest.approx(297 - 31.8 - 15, abs=.06)


def test_chapter_first_line_and_interior_heading_keep_toc_and_text(ws):
    cs, actor, refs, _, all_refs = seed(ws)
    additions = cs.commit(actor, 'chapter', [
        {'client_key': 'c', 'type': 'ContentNode', 'payload': {'kind': 'chapter',
            'body': {'text': 'Chapter One\nInterior heading\nValue **70** remains.'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'e', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'c'}, 'predicate': 'contains', 'position': 1, 'provenance_kind': 'adopted_during_generation'}}
    ])['result']['refs']
    snap = cs.freeze(actor, 'chapter-snap', refs['root'], all_refs + list(additions.values()))['result']['snapshot_ref']
    result = export_snapshot(cs, actor, 'chapter-layout', snap, {'toc_depth': 3, 'nodes': [
        {'node_ref': additions['c'], 'paragraphs': [
            {'text': 'Chapter One', 'alignment': 'center'},
            {'text': 'Interior heading', 'heading_level': 2}]}]})['result']
    doc = document(ws, result)
    assert sum(p.text == 'Chapter One' for p in doc.paragraphs) == 2
    actual = next(p for p in doc.paragraphs if p.text == 'Chapter One' and p.style.name == 'Heading 1')
    assert actual.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert sum(p.text == 'Interior heading' for p in doc.paragraphs) == 2
    assert 'Value 70 remains.' in [p.text for p in doc.paragraphs]


def test_default_margins_and_long_report_title_selected_without_split(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    default = document(ws, export_snapshot(cs, actor, 'default', snap, {'toc': False})['result'])
    assert default.sections[0].left_margin.mm == pytest.approx(25, abs=.03)
    assert not default.sections[0].header.paragraphs[0].text
    title = 'A' * 105 + '。' + 'Continuation'
    changed = cs.commit(actor, 'long-title', [{'client_key': 'r', 'type': 'ContentNode',
        'previous_ref': refs['root'], 'payload': {**cs.read(refs['root'])['payload'], 'body': {'text': title}}}])['result']['refs']['r']
    requirements = [r for r in all_refs if r['type'] in {'Requirement', 'Criterion'}]
    snap = cs.freeze(actor, 'long-snap', changed, [changed, *requirements])['result']['snapshot_ref']
    result = export_snapshot(cs, actor, 'long-layout', snap, {'toc': False, 'nodes': [
        {'node_ref': changed, 'paragraphs': [{'text': title, 'alignment': 'center'}]}]})['result']
    assert [p.text for p in document(ws, result).paragraphs] == [title]


def test_header_cannot_use_ignored_text_in_rendered_table(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    extra = cs.commit(actor, 'hidden-table-text', [
        {'client_key': 't', 'type': 'ContentNode', 'payload': {'kind': 'table', 'body': {
            'columns': ['A'], 'rows': [['Visible']], 'text': 'Hidden content'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'e', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 't'}, 'predicate': 'contains', 'position': 1, 'provenance_kind': 'adopted_during_generation'}}
    ])['result']['refs']
    snap = cs.freeze(actor, 'hidden-snap', refs['root'], all_refs + list(extra.values()))['result']['snapshot_ref']
    with pytest.raises(ActionRejected, match='HEADER_REQUIRES_RENDERED_TEXT_NODE'):
        export_snapshot(cs, actor, 'hidden-export', snap, {'header': {'node_ref': extra['t'], 'text': 'Hidden content'}})
    assert not cs.list_objects('ExportArtifact')


def test_footer_style_override_applies_to_page_number_paragraph(ws):
    cs, actor, refs, snap, _ = seed(ws)
    result = export_snapshot(cs, actor, 'footer', snap, {'toc': False,
        'styles': [{'name': 'Footer', 'alignment': 'right', 'font_size': 9}]})['result']
    p = document(ws, result).sections[0].footer.paragraphs[0]
    assert p.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert p.runs[0].font.size.pt == 9
    assert p._p.find('.//' + qn('w:instrText')).text.strip() == 'PAGE'


def test_multipart_header_indent_and_first_page_survive_sections(ws):
    from test_content_workbook import prepared
    cs, actor, _, snap, sheets = prepared(ws)
    refs = cs.read(snap)['payload']['refs']
    root = cs.read(snap)['payload']['root_ref']
    claim = next(r for r in refs if r['type'] == 'ContentNode' and cs.read(r)['payload']['kind'] == 'claim')
    layout = {'toc': False, 'hide_first_page_header_footer': True,
        'styles': [{'name':'Normal', 'first_line_indent_mm':8}],
        'header_parts': [
            {'node_ref':root,'text':'Report','position':'left','font_family':'Arial'},
            {'node_ref':claim,'text':cs.read(claim)['payload']['body']['text'],'position':'right','font_family':'Times New Roman'}],
        'nodes':[{'node_ref':sheets[0]['table_ref'],'landscape':True},
                 {'node_ref':claim,'paragraphs':[{'text':cs.read(claim)['payload']['body']['text'],'first_line_indent_mm':0}]}]}
    doc = document(ws, export_snapshot(cs,actor,'v5',snap,layout)['result'])
    assert len(doc.sections) == 3
    assert [s.different_first_page_header_footer for s in doc.sections] == [True,False,False]
    assert not doc.sections[0].first_page_header.paragraphs[0].text
    assert not doc.sections[0].first_page_footer.paragraphs[0].text
    assert doc.styles['Normal'].paragraph_format.first_line_indent.mm == pytest.approx(8,abs=.03)
    assert len(doc.styles['Header'].paragraph_format.tab_stops) == 0
    p = next(p for p in doc.paragraphs if p.text.startswith('For adopted'))
    assert p.paragraph_format.first_line_indent.mm == 0
    for section in doc.sections:
        header = section.header.paragraphs[0]
        assert header.paragraph_format.first_line_indent.mm == 0
        assert header.runs[0].font.name == 'Arial'
        assert header.runs[-1].font.name == 'Times New Roman'
        assert header.text == 'Report\tFor adopted class B use 70.'
        assert header.paragraph_format.tab_stops[-1].position.mm == pytest.approx(section.page_width.mm-50,abs=.05)


def test_header_parts_preserve_exact_source_and_unique_position(ws):
    cs, actor, refs, snap, _ = seed(ws)
    part = {'node_ref':refs['root'],'text':'Report','position':'left'}
    with pytest.raises(ActionRejected,match='DUPLICATE_POSITION'):
        export_snapshot(cs,actor,'duplicates',snap,{'header_parts':[part,part]})
    with pytest.raises(ActionRejected,match='UNIQUE_EXACT_LINE'):
        export_snapshot(cs,actor,'new-content',snap,{'header_parts':[{**part,'text':'Invented content'}]})
    with pytest.raises(ActionRejected,match='CONTROLS_CONFLICT'):
        export_snapshot(cs,actor,'conflict',snap,{'header':{'node_ref':refs['root'],'text':'Report'},'header_parts':[part]})


def test_first_chapter_heading_override_matches_directory_cache(ws):
    cs, actor, refs, _, all_refs = seed(ws)
    extra = cs.commit(actor, 'chapter-level', [
        {'client_key': 'c', 'type': 'ContentNode', 'payload': {'kind': 'chapter', 'body': {
            'text': 'Selected heading\nUnchanged body'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'e', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'c'}, 'predicate': 'contains', 'position': 1, 'provenance_kind': 'adopted_during_generation'}}
    ])['result']['refs']
    snap = cs.freeze(actor, 'level-snap', refs['root'], all_refs + list(extra.values()))['result']['snapshot_ref']
    result = export_snapshot(cs, actor, 'level-export', snap, {'toc_depth': 3, 'nodes': [{
        'node_ref': extra['c'], 'paragraphs': [{'text': 'Selected heading', 'heading_level': 3}]}]})['result']
    rows = [p for p in document(ws, result).paragraphs if p.text == 'Selected heading']
    assert len(rows) == 2
    assert rows[0].paragraph_format.left_indent.mm == pytest.approx(10, abs=.03)
    assert rows[1].style.name == 'Heading 3'


def test_first_page_empty_parts_exist_before_any_reader_materializes_them():
    from report_agent.content_layout import LayoutOptions, setup
    doc = Document()
    setup(doc, LayoutOptions(hide_first_page_header_footer=True))
    section = doc.sections[0]._sectPr
    for tag in ('headerReference', 'footerReference'):
        assert any(r.get(qn('w:type')) == 'first' for r in section.findall(qn('w:' + tag)))
    assert 'PAGE' in doc.sections[0].footer._element.xml
    assert 'PAGE' not in doc.sections[0].first_page_footer._element.xml


def test_multipart_header_only_uses_stops_for_present_positions():
    from report_agent.content_layout import LayoutOptions, setup
    r = {'type':'ContentNode','id':'synthetic','version':1}
    doc = Document()
    setup(doc, LayoutOptions.model_validate({'header_parts':[
        {'node_ref':r,'text':'Long left text that passes the center','position':'left'},
        {'node_ref':r,'text':'Right title','position':'right'}]}))
    p = doc.sections[0].header.paragraphs[0]
    assert p.text == 'Long left text that passes the center\tRight title'
    assert len(p.paragraph_format.tab_stops) == 1
    assert p.paragraph_format.tab_stops[0].position == doc.sections[0].page_width-doc.sections[0].left_margin-doc.sections[0].right_margin


def test_qualifiers_can_move_without_loss_or_snapshot_mutation(ws):
    cs, actor, refs, snap, _ = seed(ws)
    original = cs.read(snap)
    result = export_snapshot(cs, actor, 'end-notes', snap, {'toc': False,
        'nodes':[{'node_ref':refs['claim'], 'qualifier_placement':'end_notes'}]})['result']
    doc = document(ws, result)
    texts = [p.text for p in doc.paragraphs]
    assert 'For adopted class B use 70.' in texts
    assert texts.count('〔说明 1〕') == 1
    assert texts[-1] == '〔说明 1〕condition：class B'
    assert sum('condition：class B' in t for t in texts) == 1
    assert cs.read(snap) == original
    mapping = cs.read(result['mapping_ref'])['payload']
    note = mapping['qualifier_anchor_records'][0]
    assert note['node_ref'] == refs['claim']
    assert note['qualifiers'] == {'condition':'class B'}
    assert note['block_start'] >= max(m['block_stop'] for m in mapping['anchor_records'])
    from report_agent.content_layout import remap_blocks
    remap_blocks(doc, mapping['anchor_records'] + mapping['qualifier_anchor_records'])
    with pytest.raises(ActionRejected):
        export_snapshot(cs, actor, 'hide-notes', snap, {'nodes':[
            {'node_ref':refs['claim'], 'qualifier_placement':'hidden'}]})
