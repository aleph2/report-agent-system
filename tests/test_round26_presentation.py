"""R26: customer presentation preserves frozen facts and spreadsheet safety."""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from report_agent.content_workbook import export_workbook
from test_content_workbook import prepared
from test_hierarchical_content import ws


@pytest.mark.parametrize('expression,label', [('report-expression-v1','Note'),('reader-expression-v2','备注')])
@pytest.mark.parametrize('note_text', ['本表仅作资料核对，不构成工程验收。', '=HYPERLINK("https://invalid.example", "原文，不执行")'])
def test_customer_workbook_note_has_readable_label_and_preserves_literal_text(ws, note_text, expression, label):
    ws.store.set('manifest',{**ws.store.manifest,'report_expression_profile':expression})
    cs, actor, _, snapshot, sheets = prepared(ws)
    root = cs.read(snapshot)['payload']['root_ref']
    added = cs.commit(actor, 'customer-note', [{'client_key': 'note', 'type': 'ContentNode',
        'payload': {'kind': 'block', 'body': {'text': note_text},
                    'qualifiers': {'适用范围': '仅模拟资料'}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': root,
            'object_ref': {'client_key': 'note'}, 'predicate': 'contains', 'position': 2,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    saved = added['note']
    old = cs.read(snapshot)
    frozen = cs.freeze(actor, 'customer-note-snapshot', old['payload']['root_ref'],
                       [*old['payload']['refs'], *added.values()])['result']['snapshot_ref']
    before = cs.read(saved)
    sheets[0]['note_refs'] = [saved]
    result = export_workbook(cs, actor, 'customer-note-export', frozen, sheets)['result']
    workbook = load_workbook(BytesIO((ws.store.root / result['file_ref']).read_bytes()))
    worksheet = workbook.active
    matching = [(a, b) for a, b in zip(worksheet['A'], worksheet['B']) if b.value == note_text]
    assert len(matching) == 1
    label_cell, value = matching[0]
    assert label_cell.value == label
    assert value.value == note_text and value.data_type == 's'
    assert any(a.value == '适用范围' and b.value == '仅模拟资料'
               for a, b in zip(worksheet['A'], worksheet['B']))
    assert cs.read(saved) == before
    assert cs.read(result['export_ref'])['payload']['snapshot_ref'] == frozen


@pytest.mark.parametrize('duplicate,distinct', [
    ('适用范围：仅模拟资料','冲突：数量原因待确认'),
    ('待确认：9块','待确认：9块，其中2块缺少记录')])
def test_word_deduplicates_only_exact_full_qualifier_lines_and_keeps_mapping(ws, duplicate, distinct):
    from docx import Document
    from report_agent.content_export import export_snapshot
    from test_hierarchical_content import seed
    cs, actor, refs, _, members = seed(ws)
    key, value = duplicate.split('：',1)
    dkey, dvalue = distinct.split('：',1)
    # Separate keys in first case; same key in second verifies a nonidentical value is retained.
    qualifiers = {key:value} if key == dkey else {key:value,dkey:dvalue}
    body = duplicate if key != dkey else distinct
    added = cs.commit(actor,'duplicate-claim',[
        {'client_key':'claim','type':'ContentNode','payload':{'kind':'block',
            'body':{'text':body},'qualifiers':qualifiers,'claim_kind':'structure'}},
        {'client_key':'edge','type':'Relation','payload':{'subject_ref':refs['root'],
            'object_ref':{'client_key':'claim'},'predicate':'contains','position':1,
            'provenance_kind':'adopted_during_generation'}}])['result']['refs']
    revised = added['claim']
    snap = cs.freeze(actor,'duplicate-snapshot',refs['root'],[*members,*added.values()])['result']['snapshot_ref']
    before = cs.read(revised)
    output = export_snapshot(cs,actor,'duplicate-export',snap,{'toc':False})['result']
    doc = Document(BytesIO((ws.store.root/output['file_ref']).read_bytes()))
    text = '\n'.join(p.text for p in doc.paragraphs)
    if key != dkey:
        assert text.count(duplicate) == 1
        assert distinct in text
    else:
        assert duplicate in [p.text for p in doc.paragraphs]  # A partial value match cannot suppress the qualifier.
        assert distinct in text
    assert cs.read(revised) == before
    mapping = cs.read(output['mapping_ref'])['payload']
    assert any(m['node_ref'] == revised and m['qualifiers'] == qualifiers for m in mapping['anchor_records'])


@pytest.mark.parametrize('auxiliary_text',[123,'待确认：9块'])
def test_table_auxiliary_text_cannot_suppress_the_only_visible_qualification(ws,auxiliary_text):
    from docx import Document
    from report_agent.content_export import export_snapshot
    from test_hierarchical_content import seed
    cs,actor,refs,_,members=seed(ws)
    added=cs.commit(actor,'auxiliary-table',[
        {'client_key':'table','type':'ContentNode','payload':{'kind':'table',
            'body':{'columns':['数量'],'rows':[[9]],'text':auxiliary_text},
            'qualifiers':{'待确认':'9块'},'claim_kind':'structure'}},
        {'client_key':'edge','type':'Relation','payload':{'subject_ref':refs['root'],
            'object_ref':{'client_key':'table'},'predicate':'contains','position':1,
            'provenance_kind':'adopted_during_generation'}}])['result']['refs']
    snap=cs.freeze(actor,'auxiliary-snapshot',refs['root'],[*members,*added.values()])['result']['snapshot_ref']
    result=export_snapshot(cs,actor,'auxiliary-export',snap,{'toc':False})['result']
    doc=Document(BytesIO((ws.store.root/result['file_ref']).read_bytes()))
    assert '待确认：9块' in [p.text for p in doc.paragraphs]
    assert doc.tables[0].cell(1,0).text=='9'
