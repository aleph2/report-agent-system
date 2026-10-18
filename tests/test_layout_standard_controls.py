"""Real DOCX/XML and native Office controls; not real-report visual acceptance."""
from io import BytesIO
from zipfile import ZipFile
from lxml import etree

import pytest
from docx import Document
from docx.oxml.ns import qn
from pydantic import ValidationError
from report_agent.content_export import export_snapshot
from report_agent.content_layout import Typography, LayoutOptions
from report_agent.layout_capabilities import capabilities
from test_hierarchical_content import ws, seed


@pytest.mark.parametrize('values', [
    {'line_spacing': 2.5, 'line_spacing_pt': 25},
    {'space_before_pt': 10, 'space_before_lines': .2},
    {'space_after_pt': 0, 'space_after_lines': 0},
])
def test_conflicting_spacing_units_rejected(values):
    with pytest.raises(ValidationError):
        Typography(**values)


def test_line_spacing_survives_real_tool_normalization_and_reexport(ws):
    from langchain_core.tools import StructuredTool
    from report_agent.deep_runtime import business_tools
    cs, actor, refs, snap, _ = seed(ws)
    function = next(t for t in business_tools(ws, 'coordinator', None, None)
                    if t.__name__ == 'export_content_snapshot')
    export = StructuredTool.from_function(function)
    raw = {'toc': False, 'nodes': [{'node_ref': refs['claim'], 'paragraphs': [{
        'text': 'For adopted class B use 70.', 'space_before_lines': .2,
        'space_after_lines': .2, 'line_spacing': 2.5}]}]}
    validated = LayoutOptions.model_validate(raw)
    assert LayoutOptions.model_validate(validated.model_dump()).model_dump() == validated.model_dump()
    result = export.invoke({'operation_id': 'public-spacing', 'snapshot_ref': snap, 'layout': raw})['result']
    saved = cs.read(result['export_ref'])['payload']['export_config']['layout']
    result2 = export.invoke({'operation_id': 'public-spacing-reuse', 'snapshot_ref': snap, 'layout': saved})['result']
    for item in (result, result2):
        doc = Document(ws.store.root/item['file_ref'])
        p = next(p for p in doc.paragraphs if p.text == 'For adopted class B use 70.')
        assert p.paragraph_format.line_spacing == 2.5
        assert p._p.pPr.spacing.get(qn('w:beforeLines')) == '20'
        assert p._p.pPr.spacing.get(qn('w:afterLines')) == '20'
    raw['nodes'][0]['paragraphs'][0]['space_before_pt'] = 0
    with pytest.raises(ValidationError, match='point or line'):
        export.invoke({'operation_id': 'public-spacing-conflict', 'snapshot_ref': snap, 'layout': raw})


@pytest.mark.parametrize('refresh', [False, True])
def test_actual_export_honors_toc_fonts_and_multiple_spacing_after_refresh(ws, refresh):
    if refresh and not capabilities()['directory_refresh']['available']:
        pytest.skip('Native LibreOffice/UNO unavailable')
    cs, actor, refs, _, all_refs = seed(ws)
    chapter = cs.commit(actor, 'font-chapter', [
        {'client_key': 'chapter', 'type': 'ContentNode', 'payload': {
            'kind': 'chapter', 'body': {'text': 'Font probe chapter'},
            'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {
            'subject_ref': refs['root'], 'object_ref': {'client_key': 'chapter'},
            'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    snap = cs.freeze(actor, 'font-snapshot', refs['root'],
                     [*all_refs, *chapter.values()])['result']['snapshot_ref']
    original = cs.read(snap)
    options = {'refresh_toc': refresh, 'toc_depth': 3, 'line_spacing': 1.5,
        'styles': [
            {'name': 'Heading 1', 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
             'font_size': 18, 'line_spacing': 1.5, 'space_before_pt': 10, 'space_after_pt': 10},
            {'name': 'Heading 2', 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
             'font_size': 15, 'line_spacing': 1.5, 'space_before_lines': .2, 'space_after_lines': .2},
            {'name': 'TOC Heading', 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
             'font_size': 16, 'bold': True},
            {'name': 'TOC 1', 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
             'font_size': 12, 'line_spacing': 1.5, 'bold': True},
            {'name': 'TOC 2', 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
             'font_size': 12, 'line_spacing': 1.5, 'bold': False}],
        'nodes': [{'node_ref': refs['root'], 'paragraphs': [
            {'text': 'Report', 'line_spacing': 1.0}]},
            {'node_ref': refs['claim'], 'paragraphs': [
                {'text': 'For adopted class B use 70.', 'heading_level': 2,
                 'line_spacing': 2.5, 'space_before_lines': .2, 'space_after_lines': .2}]}]}
    result = export_snapshot(cs, actor, 'standards-'+str(refresh), snap, options)['result']
    data = (ws.store.root/result['file_ref']).read_bytes()
    doc = Document(BytesIO(data))
    title = next(p for p in doc.paragraphs if p.text == 'Report')
    assert title.paragraph_format.line_spacing == 1.0
    claim = next(p for p in doc.paragraphs if p.text == 'For adopted class B use 70.'
                 and p.style.name.lower() == 'heading 2')
    assert claim.paragraph_format.line_spacing == 2.5
    spacing = claim._p.pPr.find(qn('w:spacing'))
    if not refresh:
        assert spacing.get(qn('w:beforeLines')) == '20'
        assert spacing.get(qn('w:afterLines')) == '20'
    for name in ('Heading 1', 'Heading 2', 'TOC 1', 'TOC 2'):
        # Office may rewrite the display name; verify the actual style used by
        # the document through its stable OOXML identity.
        selected = next(s for s in doc.styles if s.style_id == name.replace(' ', ''))
        fonts = selected.element.rPr.rFonts
        assert fonts.get(qn('w:ascii')) == 'Times New Roman'
        assert fonts.get(qn('w:eastAsia')) == '宋体'
        assert not fonts.get(qn('w:asciiTheme')) and not fonts.get(qn('w:eastAsiaTheme'))
    with ZipFile(BytesIO(data)) as archive:
        xml = etree.fromstring(archive.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    # Office stores the refreshed index inside an SDT; Document.paragraphs
    # alone would omit it. Check all actual TOC paragraphs, not body headings.
    entries = xml.xpath('.//w:p[w:pPr/w:pStyle[@w:val="TOC2"]]', namespaces=ns)
    assert entries and any('For adopted class B use 70.' in ''.join(p.itertext()) for p in entries)
    toc_style = doc.styles['TOC 2']
    assert toc_style.font.size.pt == 12 and toc_style.paragraph_format.line_spacing == 1.5
    for p in entries:
        for direct in p.xpath('./w:pPr/w:spacing', namespaces=ns):
            if direct.get(qn('w:line')) is not None:
                assert direct.get(qn('w:line')) == '360'
        for size in p.xpath('.//w:rPr/w:sz', namespaces=ns):
            assert size.get(qn('w:val')) == '24'
    assert cs.read(snap) == original
