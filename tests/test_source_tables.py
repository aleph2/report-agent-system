"""Generic table geometry, retrieval and isolation regressions; no paid calls."""
from io import BytesIO
import json

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from report_agent.catalog import Catalog
from report_agent.document_tools import physical_page_number, source_page_info
from report_agent.source_tables import source_tables, with_source_tables
from test_document_tools import workspace, snapshot
from test_ingestion import pdf_bytes


def table_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    lines = [f'10 {y} m 220 {y} l S' for y in [20, 50, 80, 110]]
    lines += [f'{x} 20 m {x} 110 l S' for x in [10, 150, 220]]
    lines += ['80 20 m 80 80 l S']  # Deliberately merged heading; retain null.
    for x, y, value in [(20, 90, 'Group'), (160, 90, 'Kind'),
                        (20, 60, 'Count'), (90, 60, 'Other'), (160, 60, 'Total'),
                        (20, 30, '2'), (160, 30, '7')]:
        lines.append(f'BT /F1 9 Tf {x} {y} Td ({value}) Tj ET')
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(lines).encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_blank_page(width=300, height=300)
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def test_generic_cells_preserve_columns_blanks_merges_and_original(tmp_path):
    ws = workspace(tmp_path, table_pdf())
    before = snapshot(ws)
    files = set(tmp_path.rglob('*'))
    first, second = source_tables(ws, 'original', [1, 2, 1])
    assert first['status'] == 'extracted'
    assert first['source_sha256'] == ws.store.manifest['sources'][0]['sha256']
    assert first['extractor']['version'] == '0.11.10'
    table = first['tables'][0]
    assert table['rows'] == [['Group', None, 'Kind'], ['Count', 'Other', 'Total'], ['2', '', '7']]
    bounds = {(c['row'], c['column']): c['bbox'] for c in table['nonempty_cell_bounds']}
    assert bounds[1, 1] == (10, 190, 150, 220)
    assert (3, 2) not in bounds and bounds[3, 3][0] == 150
    assert second['status'] == 'no_tables_detected' and second['native_character_count'] == 0
    assert source_page_info(ws, 'original', 1)['table_view']['tables'] == first['tables']
    assert snapshot(ws) == before
    assert set(tmp_path.rglob('*')) == files


@pytest.mark.parametrize('locator,expected', [
    ('page 2; chars 1-3', 2), ('{"page":3,"method":"ocr"}; chars 9-12', 3),
    ('{"page":true}', None), ('{"page":"2"}', None), ('{"page":0}', None),
    ('{"page":2} through {"page":3}', None), ('page 2 through page 3', None),
    ('not page 2', None), ('manifest text; chars 1-2', None), (None, None),
])
def test_only_explicit_physical_locators(locator, expected):
    assert physical_page_number(locator) == expected


def test_cross_page_matches_keep_all_locators_and_pagination(tmp_path):
    ws = workspace(tmp_path, table_pdf(), content='alpha\n\nbeta\n\nalpha')
    cat = Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("DELETE FROM source_blocks")
        db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)', [
            ('original', 9, 'page 1; chars 1-5', 'alpha'),
            ('original', 25, '{"page":2,"method":"ocr"}; chars 1-4', 'beta'),
            ('original', 31, 'page 1; chars 6-10', 'alpha'),
        ])
    before = snapshot(ws)
    cross = cat.search('alpha\n\nbeta')
    assert len(cross['matches'][0]['locators']) == 2
    enriched = with_source_tables(ws, cross)
    assert {v['page'] for v in enriched['source_table_views']} == {1, 2}
    assert all(enriched[k] == v for k, v in cross.items())
    one = cat.search('alpha', limit=1, source_id='original')
    enriched = with_source_tables(ws, one)
    assert enriched['total'] == 2 and enriched['next_offset'] == 1
    assert [v['page'] for v in enriched['source_table_views']] == [1]
    assert all(enriched[k] == v for k, v in one.items())
    assert [v['page'] for v in with_source_tables(ws, cat.read('original', 0, 3))['source_table_views']] == [1, 2]
    assert snapshot(ws) == before


def test_missing_physical_locator_never_uses_block_ordinal(tmp_path):
    ws = workspace(tmp_path, table_pdf())
    cat = Catalog(ws.store)
    value = with_source_tables(ws, cat.read('original'))
    assert value['source_table_views'] == []
    assert value['table_view_unlocated'][0]['status'] == 'physical_page_not_located'
    assert value['blocks'][0]['text'] == 'Frozen OCR must not be replaced'


@pytest.mark.parametrize('metadata,error', [
    ({'copied_path': '../outside.pdf'}, 'SOURCE_ORIGINAL_OUTSIDE_PROJECT'),
    ({'sha256': '0' * 64}, 'SOURCE_ORIGINAL_SHA256_MISMATCH'),
    ({'copied_path': '', 'original_path': ''}, 'SOURCE_ORIGINAL_UNAVAILABLE'),
    ({'filename': 'original.docx'}, 'DOCX_PHYSICAL_PAGES_UNAVAILABLE'),
])
def test_unavailable_derived_view_preserves_frozen_text(tmp_path, metadata, error):
    ws = workspace(tmp_path, table_pdf(), **metadata)
    cat = Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("UPDATE source_blocks SET locator='page 1; chars 1-31'")
    baseline = cat.read('original')
    value = with_source_tables(ws, baseline)
    assert value['source_table_views'][0]['error'] == error
    assert value['blocks'] == baseline['blocks']


def test_no_cached_cross_project_or_modified_original_views(tmp_path):
    ws = workspace(tmp_path / 'one', table_pdf())
    assert source_tables(ws, 'original', [1])[0]['status'] == 'extracted'
    (ws.store.root / 'sources/original.pdf').write_bytes(pdf_bytes(('changed',)))
    assert source_tables(ws, 'original', [1])[0]['error'] == 'SOURCE_ORIGINAL_SHA256_MISMATCH'
    assert source_tables(ws, 'unknown', [1])[0]['error'] == 'SOURCE_NOT_IN_PROJECT'
    other = workspace(tmp_path / 'two', table_pdf(), copied_path=str(ws.store.root / 'sources/original.pdf'))
    assert source_tables(other, 'original', [1])[0]['error'] == 'SOURCE_ORIGINAL_OUTSIDE_PROJECT'


def test_parser_failure_and_page_range_do_not_remove_text(tmp_path, monkeypatch):
    ws = workspace(tmp_path, table_pdf())
    def fail(*args, **kwargs):
        raise ValueError('private parser internals')
    monkeypatch.setattr('report_agent.source_tables.pdfplumber.open', fail)
    one, three = source_tables(ws, 'original', [1, 3])
    assert one['error'] == 'SOURCE_TABLE_PDF_UNREADABLE'
    assert three['error'] == 'SOURCE_PAGE_OUT_OF_RANGE'
    assert 'private' not in json.dumps(one)
    assert 'Group' in source_page_info(ws, 'original', 1)['native_text']
