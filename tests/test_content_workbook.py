from io import BytesIO

import pytest
from openpyxl import load_workbook

from test_hierarchical_content import ws, seed
from report_agent.content_workbook import export_workbook
from report_agent.content_export import read_export, export_snapshot
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.errors import ActionForbidden, ActionRejected


def prepared(ws, value='=1+1'):
    cs, actor, refs, original, all_refs = seed(ws)
    added = cs.commit(actor, 'add-table', [
        {'client_key': 'table', 'type': 'ContentNode', 'payload': {'kind': 'table',
            'body': {'columns': ['Question', 'Reply'], 'rows': [[value, '']]},
            'qualifiers': {'condition': 'Pending confirmation'}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'table'}, 'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    snap = cs.freeze(actor, 'tables-snapshot', refs['root'], all_refs + list(added.values()))['result']['snapshot_ref']
    return cs, actor, original, snap, [{'name': '用户反馈', 'table_ref': added['table']}]


def test_workbook_fidelity_provenance_and_idempotency(ws):
    cs, actor, original, snap, sheets = prepared(ws)
    word = export_snapshot(cs, actor, 'word', snap)['result']['export_ref']
    before = cs.read(snap)
    receipt = export_workbook(cs, actor, 'excel', snap, sheets, word)
    assert export_workbook(cs, actor, 'excel', snap, sheets, word) == receipt
    result = receipt['result']
    data = (ws.store.root / result['file_ref']).read_bytes()
    wb = load_workbook(BytesIO(data))
    assert wb.sheetnames == ['用户反馈']
    sheet = wb.active
    assert sheet['B1'].value == 'Pending confirmation'
    assert sheet['A3'].value == '=1+1' and sheet['A3'].data_type == 's'
    assert sheet['B3'].value in (None, '')
    assert sheet.freeze_panes == 'A3'
    assert cs.read(snap) == before
    assert cs.read(result['export_ref'])['payload']['export_config']['report_export_ref'] == word
    observed = read_export(cs, actor, result['export_ref'])
    assert 'Pending confirmation' in str(observed) and '=1+1' in str(observed)


def test_workbook_role_and_snapshot_boundaries(ws):
    cs, actor, original, snap, sheets = prepared(ws)
    with pytest.raises(ActionForbidden):
        export_workbook(cs, actor_for('reviewer'), 'forbidden', snap, sheets)
    with pytest.raises(ActionForbidden):
        export_workbook(cs, actor_for('writer'), 'foreign-owner', snap, sheets)
    with pytest.raises(ActionRejected):
        export_workbook(cs, actor, 'outside', original, sheets)
    assert 'export_content_workbook' in {t.__name__ for t in content_tools(ws, 'coordinator')}
    assert 'export_content_workbook' not in {t.__name__ for t in content_tools(ws, 'reviewer')}


@pytest.mark.parametrize('name', ['bad/name', "'name", '  '])
def test_workbook_rejects_invalid_sheet_names(ws, name):
    cs, actor, _, snap, sheets = prepared(ws)
    sheets[0]['name'] = name
    with pytest.raises(ActionRejected):
        export_workbook(cs, actor, 'bad-name', snap, sheets)


def test_workbook_rejects_silent_truncation_and_duplicate_names(ws):
    cs, actor, _, snap, sheets = prepared(ws, 'x' * 32768)
    with pytest.raises(ActionRejected, match='CELL_TEXT'):
        export_workbook(cs, actor, 'too-long', snap, sheets)


def test_workbook_duplicate_sheet_names(ws):
    cs, actor, _, snap, sheets = prepared(ws)
    with pytest.raises(ActionRejected, match='DUPLICATE'):
        export_workbook(cs, actor, 'duplicate', snap, sheets * 2)


def test_word_workbook_joint_review_binds_same_snapshot(ws):
    from test_hierarchical_content import submission, review_item
    cs, actor, original, snap, sheets = prepared(ws)
    reviewer = actor_for('reviewer')
    members = cs.read(snap)['payload']['refs']
    refs = {'k': next(r for r in members if r['type'] == 'Criterion'),
            'support': next(r for r in members if r['type'] == 'Relation')}
    word = export_snapshot(cs, actor, 'same-word', snap)['result']['export_ref']
    excel = export_workbook(cs, actor, 'same-excel', snap, sheets, word)['result']['export_ref']
    receipt = cs.read_context(reviewer, snap)['receipt_id']
    review = submission(snap, refs, review_item(snap, refs['k'], receipt))
    review['items'][0].update(assessment_kind='export', artifact_refs=[word, excel])
    assert cs.submit_review(reviewer, 'joint', review, {})['result']['review_ref']
    old_word = export_snapshot(cs, actor, 'old-word', original)['result']['export_ref']
    review['items'][0]['artifact_refs'] = [old_word, excel]
    with pytest.raises(ActionRejected, match='REVIEW_VERSION_OUTSIDE_SNAPSHOT'):
        cs.submit_review(reviewer, 'cross-snapshot', review, {})


def test_linked_workbook_rejects_other_word_snapshot_before_asset_creation(ws):
    cs, actor, original, snap, sheets = prepared(ws)
    word = export_snapshot(cs, actor, 'original-word', original)['result']['export_ref']
    with pytest.raises(ActionRejected, match='WORD_WORKBOOK_SNAPSHOT_MISMATCH'):
        export_workbook(cs, actor, 'mismatch', snap, sheets, word)
    assert cs.receipt(actor, 'mismatch')['state'] == 'known_failure'
    assert not list((ws.store.root / 'content-assets').glob('*.xlsx'))


def test_correction_notes_and_qualifiers_reach_actual_workbook_without_table_revision(ws):
    from report_agent.content_workbook import WorkbookSheet
    cs, actor, _, snap, sheets = prepared(ws)
    members = cs.read(snap)['payload']['refs']
    root = cs.read(snap)['payload']['root_ref']
    notes = cs.commit(actor, 'correction-notes', [
        {'client_key': 'note', 'type': 'ContentNode', 'payload': {
            'kind': 'block', 'body': {'text': 'Correction: supplied source exists.\n=This stays literal.'},
            'qualifiers': {'limitation': 'Other source pages remain unchecked.'}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': root,
            'object_ref': {'client_key': 'note'}, 'predicate': 'contains', 'position': 2,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    updated = cs.freeze(actor, 'notes-snapshot', root, members + list(notes.values()))['result']['snapshot_ref']
    sheet = WorkbookSheet(**sheets[0], note_refs=[notes['note']]).model_dump()
    before = cs.read(sheet['table_ref'])
    word = export_snapshot(cs, actor, 'notes-word', updated)['result']['export_ref']
    exported = export_workbook(cs, actor, 'notes-workbook', updated, [sheet], word)['result']
    wb = load_workbook(BytesIO((ws.store.root / exported['file_ref']).read_bytes()))
    assert wb.active['B4'].value == 'Correction: supplied source exists.'
    assert wb.active['B5'].value == '=This stays literal.' and wb.active['B5'].data_type == 's'
    assert wb.active['B6'].value == 'Other source pages remain unchecked.'
    assert wb.active.auto_filter.ref == 'A2:B3'
    mapping = cs.read(exported['mapping_ref'])['payload']
    assert any(m['node_ref'] == notes['note'] and m['kind'] == 'note' for m in mapping['anchor_records'])
    assert notes['note'] not in mapping['unrendered_dependency_nodes']
    assert cs.read(sheet['table_ref']) == before
    wb.close()
    with pytest.raises(ActionRejected, match='NOTE_OUTSIDE_SNAPSHOT'):
        export_workbook(cs, actor, 'outside-note', snap, [sheet])
    with pytest.raises(ActionRejected, match='DUPLICATE_WORKBOOK_NOTE'):
        export_workbook(cs, actor, 'duplicate-note', updated,
                        [{**sheet, 'note_refs': [notes['note'], notes['note']]}])


def test_explicit_workbook_channel_preserves_separate_word_and_excel_same_snapshot(ws):
    cs,actor,refs,original,members=seed(ws)
    added=cs.commit(actor,'separate-workbook-content',[
        {'client_key':'table','type':'ContentNode','payload':{'kind':'table',
         'body':{'columns':['Issue','Source'],'rows':[['ONLY_EXCEL_ROW','Supplied source']]},
         'qualifiers':{},'claim_kind':'structure'}},
        {'client_key':'note','type':'ContentNode','payload':{'kind':'block',
         'body':{'text':'ONLY_WORKBOOK_NOTE\n=Literal, not a formula.'},
         'qualifiers':{},'claim_kind':'structure'}}])['result']['refs']
    all_refs=members+list(added.values())
    with pytest.raises(ActionRejected,match='DETACHED_PRESENTATION_NODE'):
        cs.freeze(actor,'undeclared-still-rejected',refs['root'],all_refs)
    snapshot=cs.freeze(actor,'declared-workbook',refs['root'],all_refs,
                       workbook_refs=list(added.values()))['result']['snapshot_ref']
    before={k:cs.read(r) for k,r in added.items()}
    word=export_snapshot(cs,actor,'separate-word',snapshot)['result']['export_ref']
    word_read=read_export(cs,actor,word)
    assert 'ONLY_WORKBOOK_NOTE' not in str(word_read) and 'ONLY_EXCEL_ROW' not in str(word_read)
    sheets=[{'name':'Issues','table_ref':added['table'],'note_refs':[added['note']]}]
    excel=export_workbook(cs,actor,'separate-excel',snapshot,sheets,word)['result']['export_ref']
    excel_read=read_export(cs,actor,excel)
    assert 'ONLY_WORKBOOK_NOTE' in str(excel_read) and 'ONLY_EXCEL_ROW' in str(excel_read)
    assert cs.read(excel)['payload']['snapshot_ref']==cs.read(word)['payload']['snapshot_ref']==snapshot
    assert before=={k:cs.read(r) for k,r in added.items()}
    with pytest.raises(ActionRejected,match='SELECTION_MISMATCH'):
        export_workbook(cs,actor,'omit-declared-note',snapshot,
                        [{'name':'Issues','table_ref':added['table']}],word)
    with pytest.raises(ActionRejected,match='WORKBOOK_CHANNEL_REQUIRES_TABLE_OR_TEXT_BLOCK'):
        cs.freeze(actor,'cannot-hide-report-node',refs['root'],all_refs,
                  workbook_refs=[refs['root'],*added.values()])
    attached=cs.commit(actor,'attach-note-for-rejection',[{'client_key':'edge','type':'Relation',
        'payload':{'subject_ref':refs['root'],'object_ref':added['note'],
        'predicate':'contains','position':1,'provenance_kind':'adopted_during_generation'}}])['result']['refs']['edge']
    with pytest.raises(ActionRejected,match='WORKBOOK_ONLY_NODE_IN_REPORT'):
        cs.freeze(actor,'report-note-cannot-be-both',refs['root'],all_refs+[attached],
                  workbook_refs=list(added.values()))
    with pytest.raises(ActionRejected,match='WORKBOOK_CHANNEL_OUTSIDE_MANIFEST'):
        cs.freeze(actor,'cannot-import-foreign-node',refs['root'],members,
                  workbook_refs=[added['table']])
    with pytest.raises(ActionForbidden):
        export_workbook(cs,actor_for('reviewer'),'reviewer-cannot-export-channel',snapshot,sheets,word)
