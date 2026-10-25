"""A new display profile cannot rewrite an already successful export operation."""
from io import BytesIO
from openpyxl import load_workbook
from report_agent.content_workbook import export_workbook
from test_content_workbook import prepared
from test_hierarchical_content import ws

def test_note_profile_change_preserves_original_operation_receipt_and_immutable_export(ws):
    cs,actor,_,snapshot,sheets=prepared(ws)
    root=cs.read(snapshot)['payload']['root_ref']
    sheets[0]['note_refs']=[root]
    first=export_workbook(cs,actor,'original-note',snapshot,sheets)
    original=cs.read(first['result']['export_ref'])
    old_bytes=(ws.store.root/first['result']['file_ref']).read_bytes()
    ws.store.set('manifest',{**ws.store.manifest,'report_expression_profile':'reader-expression-v2'})
    assert export_workbook(cs,actor,'original-note',snapshot,sheets)==first
    assert (ws.store.root/first['result']['file_ref']).read_bytes()==old_bytes
    second=export_workbook(cs,actor,'new-profile-note',snapshot,sheets)
    def label(result):
        book=load_workbook(BytesIO((ws.store.root/result['result']['file_ref']).read_bytes()))
        try:return next(a.value for a,b in zip(book.active['A'],book.active['B']) if b.value=='Report')
        finally:book.close()
    assert label(first)=='Note' and label(second)=='备注'
    assert cs.read(first['result']['export_ref'])==original
    assert cs.read(second['result']['export_ref'])['payload']['export_config']['report_expression_profile']=='reader-expression-v2'
