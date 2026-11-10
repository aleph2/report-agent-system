"""Native draft workbook keeps document order and prints its clarification rows."""
from openpyxl import load_workbook
from report_agent.content_export import export_snapshot
from report_agent.content_workbook import companion_sheets
from test_hierarchical_content import ws
from test_m1_g3_exports import fixture, issue


def test_companion_tables_follow_word_order_not_record_insertion_order():
    def ref(kind, key): return dict(type=kind, id=key, version=1)
    root, first, second = [ref('ContentNode', key) for key in ('root', 'first', 'second')]
    def record(r, payload): return dict(ref=r, payload=payload)
    records = {('ContentNode','second',1):record(second,dict(kind='table', body={})),
        ('ContentNode','first',1):record(first,dict(kind='table',body={})),
        ('ContentNode','root',1):record(root,dict(kind='report',body={}))}
    for i, target in enumerate([first, second]):
        r=ref('Relation',str(i));records[('Relation',str(i),1)]=record(r,dict(predicate='contains',subject_ref=root,object_ref=target,position=i))
    snap=dict(payload=dict(root_ref=root))
    sheets=companion_sheets(snap,records,set(records))
    assert [s['table_ref'] for s in sheets] == [first,second]
    snap['payload']['workbook_refs']=[second,first]
    assert [s['table_ref'] for s in companion_sheets(snap,records,set(records))] == [second,first]


def test_clarification_print_settings_and_row_heights_are_explicit(ws):
    cs,actor,snapshot,_=fixture(ws)
    pair=export_snapshot(cs,actor,'printable-pair',snapshot,dict(toc=False))['result']
    book=load_workbook(ws.store.root/pair['workbook']['file_ref'])
    sheet=book['资料澄清清单']
    assert sheet.page_setup.orientation == 'landscape'
    assert int(sheet.page_setup.paperSize) == int(sheet.PAPERSIZE_A3)
    assert sheet.page_setup.fitToWidth == 1 and sheet.page_setup.fitToHeight == 0
    assert all(sheet.row_dimensions[i].height is not None for i in range(1,sheet.max_row+1))
    book.close()


def test_long_mixed_language_clarification_keeps_native_print_allowance(ws):
    basis = '坡段 B 的边坡处治工程措施类型（抗滑桩、锚固工程、注浆类工程或挡土墙工程）未见任何文字证据。设计说明中坡段 B 仅给出桩号与分级情况，未列防护或支挡措施；地勘记录明确仅覆盖坡段 A。措施类型可能标注于横断面图（06_drawing），但本次文字通道无法核读图像。'
    cs, actor, snapshot, _ = fixture(ws, dict(columns=['指标','采用值'], rows=[['工程措施','75']],
        material_issues=[dict(issue(), basis=basis)]))
    pair = export_snapshot(cs, actor, 'long-print-row', snapshot, dict(toc=False))['result']
    book = load_workbook(ws.store.root / pair['workbook']['file_ref'])
    sheet = book['资料澄清清单']
    assert sheet.cell(2, 5).value == basis
    # Native Excel clipped the last line at 83pt; this passage needs at least seven 15pt lines.
    assert sheet.row_dimensions[2].height >= 110
    book.close()
