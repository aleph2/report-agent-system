"""Offline G3 export checks against real DOCX/XLSX bytes and frozen nodes."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from docx import Document
from openpyxl import load_workbook
import pytest

from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.errors import ActionRejected
from test_hierarchical_content import seed, ws


def test_source_views_preserve_surrounding_text_and_render_pinned_crop():
    from report_agent.content_export import _emit_source_views
    from PIL import Image
    png = BytesIO()
    Image.new('RGB', (300, 600), 'white').save(png, format='PNG')
    doc = Document()
    calls = []
    view = {'text': '表格原文\n逐格文字', 'source_id': 'template-pinned', 'page': 22, 'crop': [.1, .2, .9, .8]}
    def render(item):
        calls.append(item)
        return png.getvalue()
    _emit_source_views(doc, '3.2 方法\n表格原文\n逐格文字\n计算公式保持原文', [view],
        lambda text: doc.add_paragraph(text), render, 170)
    assert calls == [view]
    assert [p.text for p in doc.paragraphs if p.text] == ['3.2 方法\n', '\n计算公式保持原文']
    assert len(doc.inline_shapes) == 1
    shape=doc.inline_shapes[0]
    section=doc.sections[-1]
    assert shape.height < section.page_height-section.top_margin-section.bottom_margin
    assert view['text'] == '表格原文\n逐格文字'
    saved=BytesIO();doc.save(saved)
    with ZipFile(BytesIO(saved.getvalue())) as archive:
        media=[name for name in archive.namelist() if name.startswith('word/media/')]
        assert len(media)==1 and archive.read(media[0])==png.getvalue()


@pytest.mark.parametrize('text, views', [
    ('重复 重复', [{'text':'重复'}]),
    ('abcdef', [{'text':'abcd'}, {'text':'cdef'}]),
    ('原文', [{'text':'不存在'}]),
])
def test_source_views_reject_ambiguous_overlapping_or_missing_passages_before_render(text,views):
    from report_agent.content_export import _emit_source_views
    doc=Document();calls=[]
    with pytest.raises(ActionRejected,match='SOURCE_VIEW'):
        _emit_source_views(doc,text,views,lambda value:calls.append(value),lambda view:calls.append(view),170)
    assert calls==[] and len(doc.inline_shapes)==0


def issue(identifier="assumption-1", kind="indirect_assumption", row=0):
    return dict(id=identifier, kind=kind, object_label="坡A", basis="邻近钻孔推定" if kind != "no_evidence_assumption" else "无间接资料，取不利值",
        sources=[dict(document="勘察文件", page=12)] if kind != "no_evidence_assumption" else [],
        adopted_value="75", question="请确认地下水条件", anchor=dict(row=row, column=1), affects_level=True)


def fixture(ws, body=None, *, paragraph=None, detached=False, qualifiers=None):
    cs, actor, refs, _, members = seed(ws)
    body = body or dict(columns=["指标", "采用值"], rows=[["地下水", "75"], ["地层", "75"]],
        material_issues=[issue(), issue("assumption-2", "no_evidence_assumption", 1)])
    objects = [{"client_key": "table", "type": "ContentNode", "payload": {
        "kind": "table", "body": body, "qualifiers": qualifiers or {}, "claim_kind": "structure"}}]
    if paragraph:
        objects.append({"client_key": "passage", "type": "ContentNode", "payload": {
            "kind": "block", "body": paragraph, "qualifiers": {}, "claim_kind": "structure"}})
    for position, key in enumerate(["table"] + (["passage"] if paragraph else []), 1):
        if detached and key == "table":
            continue
        objects.append({"client_key": "edge-" + key, "type": "Relation", "payload": {
            "subject_ref": refs["root"], "object_ref": {"client_key": key}, "predicate": "contains",
            "position": position, "provenance_kind": "adopted_during_generation"}})
    added = cs.commit(actor, "g3-fixture", objects)["result"]["refs"]
    snapshot = cs.freeze(actor, "g3-snapshot", refs["root"], members + list(added.values()),
        workbook_refs=[added["table"]] if detached else None)["result"]["snapshot_ref"]
    return cs, actor, snapshot, added


def exports(ws, cs, actor, snapshot, added):
    word = export_snapshot(cs, actor, "g3-word", snapshot, {"toc": False})["result"]
    excel = export_workbook(cs, actor, "g3-excel", snapshot,
        [{"name": "评估", "table_ref": added["table"]}], report_export_ref=word["export_ref"])["result"]
    return ((ws.store.root / word["file_ref"]).read_bytes(), (ws.store.root / excel["file_ref"]).read_bytes())


def test_comments_match_clarification_rows_and_anchor_exact_values(ws):
    cs, actor, snapshot, added = fixture(ws)
    before = deepcopy(cs.list_objects())
    word, excel = exports(ws, cs, actor, snapshot, added)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(BytesIO(word)) as archive:
        comments = ET.fromstring(archive.read("word/comments.xml"))
        document = ET.fromstring(archive.read("word/document.xml"))
    comment_texts = ["".join(c.itertext()) for c in comments]
    assert len(comment_texts) == 2
    assert any("无证据假设" in c for c in comment_texts)
    assert any("间接证据假设" in c and "勘察文件" in c and "12" in c for c in comment_texts)
    assert all("影响等级" in c and "请确认地下水条件" in c for c in comment_texts)
    for start in document.findall(".//w:commentRangeStart", ns):
        paragraph = next(p for p in document.findall(".//w:p", ns) if start in list(p))
        children = list(paragraph)
        end = next(c for c in children if c.tag.endswith("commentRangeEnd") and c.attrib == start.attrib)
        assert "".join(t.text or "" for c in children[children.index(start)+1:children.index(end)] for t in c.findall(".//w:t", ns)) == "75"
    book = load_workbook(BytesIO(excel))
    assert book.sheetnames == ["评估", "资料澄清清单"]
    rows = list(book["资料澄清清单"].values)
    assert len(rows) == 3
    assert rows[1][1] == "无证据假设" and rows[2][1] == "间接证据假设"
    assert rows[1][5] == rows[2][5] == "75"
    assert rows[1][7] is None and rows[2][7] is None
    assert book["资料澄清清单"].auto_filter.ref == "A1:I3"
    assert all(cs.read(r["ref"]) == r for r in before)


def test_table_merges_preserve_one_value_and_header(ws):
    body = dict(columns=["指标", "等级"], rows=[["地下水", "I"], ["地下水", "II"]],
        merges=[dict(start_row=0, end_row=1, start_col=0, end_col=0)])
    cs, actor, snapshot, added = fixture(ws, body)
    word, excel = exports(ws, cs, actor, snapshot, added)
    table = Document(BytesIO(word)).tables[0]
    assert table.cell(0, 0).text == "指标"
    assert table.cell(1, 0).text == "地下水"
    assert table.cell(1, 0)._tc is table.cell(2, 0)._tc
    book = load_workbook(BytesIO(excel))
    assert str(next(iter(book["评估"].merged_cells.ranges))) == "A2:A3"
    assert book["评估"]["A2"].value == "地下水"
    assert book.sheetnames == ["评估"]


@pytest.mark.parametrize("mutation", ["bounds", "overlap", "loss", "anchor", "missing_anchor", "duplicate", "false_source", "merged_anchor"])
@pytest.mark.parametrize("format", ["word", "excel"])
def test_invalid_issue_or_merge_refuses_export_without_artifact(ws, mutation, format):
    body = dict(columns=["指标", "采用值"], rows=[["地下水", "75"], ["地层", "75"]], material_issues=[issue()])
    if mutation in {"bounds", "overlap", "loss"}:
        merge = dict(start_row=0, end_row=1, start_col=0, end_col=0)
        if mutation == "bounds": merge["end_row"] = 2
        if mutation == "overlap": body["rows"][1][0] = "地下水"
        body["merges"] = [merge, merge] if mutation == "overlap" else [merge]
    elif mutation == "anchor": body["material_issues"][0]["adopted_value"] = "99"
    elif mutation == "missing_anchor": body["material_issues"][0]["anchor"] = dict(row=8, column=1)
    elif mutation == "duplicate": body["material_issues"].append(issue())
    elif mutation == "false_source": body["material_issues"][0]["kind"] = "no_evidence_assumption"
    else:
        body["merges"] = [dict(start_row=0, end_row=1, start_col=1, end_col=1)]
        body["material_issues"][0]["anchor"]["row"] = 1
    cs, actor, snapshot, added = fixture(ws, body)
    with pytest.raises(ActionRejected, match="MATERIAL_ISSUE|TABLE_MERGE"):
        if format == "word": export_snapshot(cs, actor, "bad-word", snapshot)
        else: export_workbook(cs, actor, "bad-excel", snapshot, [{"name": "评估", "table_ref": added["table"]}])
    assert not cs.list_objects("ExportArtifact")


def test_detached_dependency_issues_not_added_to_word_or_clarifications(ws):
    cs, actor, snapshot, added = fixture(ws, detached=True)
    word, excel = exports(ws, cs, actor, snapshot, added)
    with ZipFile(BytesIO(word)) as archive:
        assert "word/comments.xml" not in archive.namelist()
    assert load_workbook(BytesIO(excel)).sheetnames == ["评估"]


def test_clarification_cell_is_text_even_when_question_looks_like_formula(ws):
    body = dict(columns=["指标", "采用值"], rows=[["地下水", "75"]], material_issues=[issue()])
    body["material_issues"][0]["question"] = "=HYPERLINK(\"https://example.invalid\")"
    cs, actor, snapshot, added = fixture(ws, body)
    _, excel = exports(ws, cs, actor, snapshot, added)
    cell = load_workbook(BytesIO(excel))["资料澄清清单"]["G2"]
    assert cell.data_type == "s" and cell.value.startswith("=")


@pytest.mark.parametrize("passage", ["本坡采用 **75** 分。", "本坡采用 75 分；另一处为 75 分。", "本坡采用 80 分。"])
def test_paragraph_comment_matches_actual_unique_rendered_value(ws, passage):
    annotation = issue("passage-issue", "conflict")
    annotation["anchor"] = {"text": "75"}
    body = dict(columns=["指标", "采用值"], rows=[["地下水", "75"]])
    cs, actor, snapshot, added = fixture(ws, body,
        paragraph=dict(text=passage, material_issues=[annotation]))
    if passage != "本坡采用 **75** 分。":
        with pytest.raises(ActionRejected, match="MATERIAL_ISSUE"):
            export_snapshot(cs, actor, "paragraph-fails", snapshot)
        return
    word, excel = exports(ws, cs, actor, snapshot, added)
    doc = Document(BytesIO(word))
    assert len(doc.comments) == 1
    paragraph = next(p for p in doc.paragraphs if p.text == "本坡采用 75 分。")
    assert next(r for r in paragraph.runs if r.text == "75").bold
    assert len(list(load_workbook(BytesIO(excel))["资料澄清清单"].values)) == 2


@pytest.mark.parametrize("page, expected", [("page 12", "《勘察文件》第12页"),
    (12, "《勘察文件》第12页"), ("PDF第12页", "《勘察文件》第12页"),
    ("manifest text", "《勘察文件》全文"), ("line 17", "《勘察文件》第17行")])
def test_material_issue_accepts_readable_scoring_source_locator(page, expected):
    from report_agent.material_issues import validate_node
    annotation = issue()
    annotation["sources"][0]["page"] = page
    parsed, _ = validate_node({"kind": "table", "body": {
        "columns": ["指标", "采用值"], "rows": [["地下水", "75"]], "material_issues": [annotation]}})
    assert parsed[0].source_text() == expected


def test_clarification_requires_rendered_word_pointer_proof(ws):
    cs, actor, snapshot, added = fixture(ws)
    with pytest.raises(ActionRejected, match="WORD_EXPORT_REQUIRED_FOR_MATERIAL_ISSUES"):
        export_workbook(cs, actor, "unlinked", snapshot, [{"name": "评估", "table_ref": added["table"]}])
    assert not cs.list_objects("ExportArtifact")


def test_clarification_refuses_corrupt_linked_word_bytes(ws):
    cs, actor, snapshot, added = fixture(ws)
    word = export_snapshot(cs, actor, 'word-before-corruption', snapshot, {'toc': False})['result']
    (ws.store.root / word['file_ref']).write_bytes(b'corrupted fixture bytes')
    with pytest.raises(ActionRejected, match='ASSET_DIGEST_MISMATCH'):
        export_workbook(cs, actor, 'corrupt-linked-word', snapshot,
            [{'name': '评估', 'table_ref': added['table']}], report_export_ref=word['export_ref'])
    assert len(cs.list_objects('ExportArtifact')) == 2


def test_workbook_qualifiers_match_word_visible_labels(ws):
    body = dict(columns=["指标", "采用值"], rows=[["地下水", "75"]])
    cs, actor, snapshot, added = fixture(ws, body,
        qualifiers={'source_note': '设计文件第12页', 'revision': 'PRIVATE_REVISION'})
    word, excel = exports(ws, cs, actor, snapshot, added)
    word_text = '\n'.join(p.text for p in Document(BytesIO(word)).paragraphs)
    excel_values = [value for row in load_workbook(BytesIO(excel)).active.values for value in row]
    assert '来源说明：设计文件第12页' in word_text
    assert '来源说明' in excel_values and '设计文件第12页' in excel_values
    assert 'source_note' not in excel_values and 'PRIVATE_REVISION' not in excel_values


@pytest.mark.parametrize('as_note', [False, True])
def test_g3_workbook_cannot_publish_detached_unchecked_nodes(tmp_path, as_note):
    from report_agent.content_store import ContentStore
    from report_agent.hierarchical_tools import actor_for
    from report_agent.store import Store
    from test_m1_g3_presentation import fixture as presentation_fixture
    _, snap, records, _ = presentation_fixture()
    rendered_table = {'type': 'ContentNode', 'id': 'rendered-table', 'version': 1}
    records[('ContentNode', 'rendered-table', 1)] = {'ref': rendered_table, 'payload': {
        'kind': 'table', 'body': {'columns': ['采用值'], 'rows': [['75']], 'section_id': '2'},
        'qualifiers': {}, 'claim_kind': 'structure',
        'citations': records[('ContentNode', 'extracted', 1)]['payload']['citations']}}
    records[('Relation', 'table-edge', 1)] = {'ref': {'type': 'Relation', 'id': 'table-edge', 'version': 1},
        'payload': {'predicate': 'contains', 'subject_ref': snap['payload']['root_ref'],
                    'object_ref': rendered_table, 'position': 3}}
    store = Store(tmp_path)
    store.initialize({'goal': 'Offline workbook boundary fixture', 'sources': [
        {'id': 'seed', 'title': 'seed', 'content': 'seed', 'coverage': 'complete'}]})
    cs, actor = ContentStore(store), actor_for('coordinator')
    records[('SourceArtifact', 'source', 1)]['payload']['source_id'] = 'synthetic-source'
    with store.connect() as db:
        for record in records.values():
            cs._insert(db, actor, record['ref']['type'], record['payload'], id=record['ref']['id'])
        extra = cs._insert(db, actor, 'ContentNode', {'kind': 'block' if as_note else 'table',
            'body': {'text': 'source_id: private'} if as_note else {'columns': ['source_id'], 'rows': [['private']]},
            'qualifiers': {}, 'claim_kind': 'structure'})
        refs = [r['ref'] for r in records.values()] + [extra]
        snapshot = cs._insert(db, actor, 'DocumentSnapshot', {**snap['payload'], 'refs': refs})
    sheet = {'name': '评估', 'table_ref': rendered_table if as_note else extra}
    if as_note: sheet['note_refs'] = [extra]
    with pytest.raises(ActionRejected, match='G3_WORKBOOK_NODE_NOT_RENDERED'):
        export_workbook(cs, actor, 'unrendered-g3', snapshot, [sheet])
    assert not cs.list_objects('ExportArtifact')


def double_header_body():
    return dict(columns=['分类', '分值范围', '取值'],
        header_rows=[['分类', '基本分值（Rᵢⱼ）', ''], ['', '分值范围', '取值']],
        header_merges=[dict(start_row=0,end_row=1,start_col=0,end_col=0),
                       dict(start_row=0,end_row=0,start_col=1,end_col=2)],
        rows=[['地质', '0–50', '75'], ['地质', '51–100', '75']],
        merges=[dict(start_row=0,end_row=1,start_col=0,end_col=0)])


def test_two_header_rows_keep_body_anchors_merges_and_sheet_offsets(ws):
    from docx.oxml.ns import qn
    body = double_header_body()
    annotation = issue()
    annotation['anchor']['column'] = 2
    body['material_issues'] = [annotation]
    cs, actor, snapshot, added = fixture(ws, body, qualifiers={'source_note':'页码说明'})
    word, excel = exports(ws, cs, actor, snapshot, added)
    doc = Document(BytesIO(word)); table = doc.tables[0]
    assert table.cell(0, 1).text == '基本分值（Rᵢⱼ）'
    assert table.cell(0, 1)._tc is table.cell(0, 2)._tc
    assert table.cell(0, 0)._tc is table.cell(1, 0)._tc
    assert table.cell(1, 1).text == '分值范围' and table.cell(1, 2).text == '取值'
    assert table.cell(2, 0)._tc is table.cell(3, 0)._tc
    assert table.cell(2, 0).text == '地质'
    assert abs(table.cell(0, 1).width - sum(c.width for c in list(table.columns)[1:])) < 1300
    for row in table.rows[:2]:
        assert row._tr.trPr.find(qn('w:tblHeader')) is not None
        assert all(run.bold for cell in row.cells for p in cell.paragraphs for run in p.runs if run.text)
    assert len(doc.comments) == 1
    assert table.cell(2, 2)._tc.find('.//' + qn('w:commentRangeStart')) is not None
    assert table.cell(1, 2)._tc.find('.//' + qn('w:commentRangeStart')) is None
    book = load_workbook(BytesIO(excel)); sheet = book['评估']
    assert sheet['B2'].value == '基本分值（Rᵢⱼ）' and sheet['C3'].value == '取值'
    assert {str(r) for r in sheet.merged_cells.ranges} == {'A2:A3','B2:C2','A4:A5'}
    assert sheet.freeze_panes == 'A4' and sheet.print_title_rows == '$2:$3'
    assert sheet.auto_filter.ref == 'A3:C5'
    assert sheet['B3'].font.bold and sheet['C4'].value == '75'
    assert len(list(book['资料澄清清单'].values)) == 2


@pytest.mark.parametrize('mutation', ['ragged','bounds','overlap','loss'])
@pytest.mark.parametrize('format', ['word','excel'])
def test_bad_header_projection_refuses_before_artifact(ws, mutation, format):
    body=double_header_body()
    # Insert malformed historical payload directly: export must defend frozen records too.
    cs,actor,snapshot,added=fixture(ws, body)
    if mutation=='ragged': body['header_rows'][1].pop()
    elif mutation=='bounds': body['header_merges'][0]['end_row']=2
    elif mutation=='overlap': body['header_merges'].append(dict(body['header_merges'][0]))
    else: body['header_rows'][0][2]='被覆盖的值'
    with cs.store.connect() as db:
        record=cs._read(db,added['table'])
        bad=cs._insert(db,actor,'ContentNode',{**record['payload'],'body':body})
        frozen=cs._read(db,snapshot)['payload']
        edge=cs._insert(db,actor,'Relation',{'subject_ref':frozen['root_ref'],'object_ref':bad,
            'predicate':'contains','position':9,'provenance_kind':'adopted_during_generation'})
        snapshot=cs._insert(db,actor,'DocumentSnapshot',{**frozen,'refs':[*frozen['refs'],bad,edge]})
    with pytest.raises(ActionRejected,match='TABLE_HEADER'):
        if format=='word': export_snapshot(cs,actor,'invalid-header',snapshot,{'toc':False})
        else: export_workbook(cs,actor,'invalid-header',snapshot,[{'name':'评估','table_ref':bad}])
    assert not cs.list_objects('ExportArtifact')


def test_historical_rank_reason_stays_in_audit_not_customer_files(ws):
    body=dict(columns=['序号','评估指标','权重系数'],rows=[['1','边坡高度 X11','0.2']],
        cell_comments=[{'text':'高度是本坡主要控制因素。','value':'边坡高度 X11','anchor':{'row':0,'column':1}}])
    cs,actor,snapshot,added=fixture(ws,body)
    word,excel=exports(ws,cs,actor,snapshot,added)
    doc=Document(BytesIO(word))
    assert len(doc.comments)==0
    assert cs.read(added['table'])['payload']['body']['cell_comments']==body['cell_comments']
    with ZipFile(BytesIO(word)) as archive:
        assert all('高度是本坡主要控制因素。' not in archive.read(name).decode('utf-8')
                   for name in archive.namelist() if name.startswith('word/') and name.endswith('.xml'))
    assert load_workbook(BytesIO(excel)).sheetnames==['评估']
    from docx.oxml.ns import qn
    assert doc.tables[0].cell(1,1)._tc.find('.//'+qn('w:commentRangeStart')) is None


def test_customer_comments_match_all_material_issue_rows_despite_saved_rank_comments(ws):
    kinds = ['conflict', 'unclear', 'missing', 'indirect_assumption', 'no_evidence_assumption']
    annotations, audit = [], []
    for index, kind in enumerate(kinds):
        annotation = issue('material-' + kind, kind, index)
        annotation.update(object_label='坡' + str(index), basis='依据' + str(index),
                          question='确认问题' + str(index), adopted_value=str(71 + index),
                          affects_level=index % 2 == 0)
        annotations.append(annotation)
        audit.append({'text': '仅审计排序理由' + str(index), 'value': '指标' + str(index),
                      'anchor': {'row': index, 'column': 0}})
    body = dict(columns=['指标', '采用值'], rows=[['指标' + str(i), str(71 + i)] for i in range(5)],
                material_issues=annotations, cell_comments=audit)
    cs, actor, snapshot, added = fixture(ws, body)
    before = deepcopy(cs.read(added['table']))
    word, excel = exports(ws, cs, actor, snapshot, added)
    doc = Document(BytesIO(word))
    book = load_workbook(BytesIO(excel))
    clarification = list(book['资料澄清清单'].values)[1:]
    assert len(doc.comments) == len(clarification) == 5
    # Compare actual customer workbook fields, independently of the comment formatter.
    expected = []
    for _, kind, label, sources, basis, value, question, reply, impact in clarification:
        assert reply is None
        if kind in {'间接证据假设', '无证据假设'}:
            suffix = '影响等级：' + ('是，补充资料后需复核。' if impact == '是' else '否')
        else:
            assert impact in {'待复核（不能排除）', '本次评分未计入该事项；不评价实际工程风险'}
            suffix = '等级影响：' + impact
        expected.append(f'待核：{kind}｜{label}\n依据：{basis}\n资料：{sources}\n采用值：{value}\n待确认：{question}\n{suffix}')
    assert sorted(comment.text for comment in doc.comments) == sorted(expected)
    assert {row[2] for row in clarification} == {'坡' + str(i) for i in range(5)}
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(BytesIO(word)) as archive:
        document = ET.fromstring(archive.read('word/document.xml'))
        assert all('仅审计排序理由' not in archive.read(name).decode('utf-8')
                   for name in archive.namelist() if name.startswith('word/') and name.endswith('.xml'))
    anchors = []
    for paragraph in document.findall('.//w:p', ns):
        children = list(paragraph)
        for start in paragraph.findall('w:commentRangeStart', ns):
            end = next(child for child in children if child.tag.endswith('commentRangeEnd') and child.attrib == start.attrib)
            anchors.append(''.join(t.text or '' for child in children[children.index(start)+1:children.index(end)] for t in child.findall('.//w:t', ns)))
    assert sorted(anchors) == sorted(row[5] for row in clarification)
    assert all('仅审计排序理由' not in str(cell) for sheet in book for row in sheet.values for cell in row)
    assert cs.read(added['table']) == before


@pytest.mark.parametrize('mutation',['value','bounds','merged'])
def test_rank_comment_invalid_anchor_refuses_export(ws,mutation):
    body=double_header_body()
    body['cell_comments']=[{'text':'排序理由','value':'地质','anchor':{'row':0,'column':0}}]
    if mutation=='value': body['cell_comments'][0]['value']='other'
    elif mutation=='bounds': body['cell_comments'][0]['anchor']['row']=10
    else: body['cell_comments'][0]['anchor']['row']=1
    cs,actor,snapshot,_=fixture(ws,body)
    with pytest.raises(ActionRejected,match='CELL_COMMENT'):
        export_snapshot(cs,actor,'invalid-cell-comment',snapshot,{'toc':False})
    assert not cs.list_objects('ExportArtifact')


def required_fixture(ws, *, mutation=None):
    from report_agent.content_store import Actor
    canonical=issue('required-conflict','conflict')
    body=dict(columns=['指标','采用值'],rows=[['地下水','75']],material_issues=[deepcopy(canonical)])
    if mutation=='missing': body['material_issues']=[]
    elif mutation=='tampered': body['material_issues'][0]['basis']='无关解释'
    cs,actor,snapshot,added=fixture(ws,body,detached=mutation=='detached')
    required={key:canonical[key] for key in ('id','kind','object_label','basis','sources','question')}
    with cs.store.connect() as db:
        # Boundary fixture only: approval generation is tested independently in commission tests.
        plan=cs._insert(db,actor,'CommissionPlan',{'objects':[],'sections':[],'reconciliations':[]})
        decision=cs._insert(db,Actor('operator','operator','fixture'),'CommissionDecision',
            {'plan_ref':plan,'approved':True,'required_material_issues':[required]})
        if mutation=='owner':
            decision=cs._insert(db,actor,'CommissionDecision',{'plan_ref':plan,'approved':True,'required_material_issues':[required]})
        if mutation=='stale':
            decision=cs._insert(db,Actor('operator','operator','fixture'),'CommissionDecision',
                {'plan_ref':{**plan,'version':2},'approved':True,'required_material_issues':[required]})
        if mutation=='denied':
            decision=cs._insert(db,Actor('operator','operator','fixture'),'CommissionDecision',
                {'plan_ref':plan,'approved':False,'required_material_issues':[required]})
        frozen=cs._read(db,snapshot)['payload']
        snapshot=cs._insert(db,actor,'DocumentSnapshot',{**frozen,'commission_plan_ref':plan,
            'commission_confirmation_ref':decision,'refs':[*frozen['refs'],plan,decision]})
    return cs,actor,snapshot,added


@pytest.mark.parametrize('mutation',['missing','tampered','detached','owner','stale','denied'])
@pytest.mark.parametrize('format',['word','excel'])
def test_required_plan_issue_must_match_frozen_approval_and_rendered_anchor(ws,mutation,format):
    cs,actor,snapshot,added=required_fixture(ws,mutation=mutation)
    with pytest.raises(ActionRejected,match='REQUIRED_MATERIAL_ISSUE|MATERIAL_ISSUE_CONFIRMATION'):
        if format=='word': export_snapshot(cs,actor,'required-invalid',snapshot,{'toc':False})
        else: export_workbook(cs,actor,'required-invalid',snapshot,[{'name':'评估','table_ref':added['table']}])
    assert not cs.list_objects('ExportArtifact')


def test_required_plan_issue_exports_from_frozen_approval_without_live_state(ws):
    cs,actor,snapshot,added=required_fixture(ws)
    word,excel=exports(ws,cs,actor,snapshot,added)
    assert len(Document(BytesIO(word)).comments)==1
    assert len(list(load_workbook(BytesIO(excel))['资料澄清清单'].values))==2


@pytest.mark.parametrize('format',['word','excel'])
def test_legacy_snapshot_cannot_skip_known_required_conflicts(ws,format):
    cs,actor,snapshot,added=fixture(ws,dict(columns=['指标'],rows=[['地下水']]))
    with cs.store.connect() as db:
        plan=cs._insert(db,actor,'CommissionPlan',{'objects':[],'sections':[],
            'reconciliations':[{'differences':['桩号存在差异'],'sources':[]}]})
        frozen=cs._read(db,snapshot)['payload']
        snapshot=cs._insert(db,actor,'DocumentSnapshot',{**frozen,'commission_plan_ref':plan,
            'refs':[*frozen['refs'],plan]})
    with pytest.raises(ActionRejected,match='MATERIAL_ISSUE_CONFIRMATION'):
        if format=='word': export_snapshot(cs,actor,'legacy-conflict',snapshot,{'toc':False})
        else: export_workbook(cs,actor,'legacy-conflict',snapshot,[{'name':'评估','table_ref':added['table']}])
    assert not cs.list_objects('ExportArtifact')


def test_horizontal_body_merge_retains_grid_width_text_and_comment_anchor(ws):
    from docx.oxml.ns import qn
    annotation=issue()
    annotation.update(adopted_value='共同说明',anchor={'row':0,'column':0})
    body=dict(columns=['分级','条件','取值'],rows=[['共同说明','共同说明','75']],
        merges=[dict(start_row=0,end_row=0,start_col=0,end_col=1)],material_issues=[annotation])
    cs,actor,snapshot,added=fixture(ws,body)
    word,_=exports(ws,cs,actor,snapshot,added)
    doc=Document(BytesIO(word));table=doc.tables[0];cell=table.cell(1,0)
    assert cell._tc is table.cell(1,1)._tc and cell.text=='共同说明'
    assert abs(cell.width-sum(c.width for c in list(table.columns)[:2]))<1300
    assert cell._tc.find('.//'+qn('w:commentRangeStart')) is not None
    assert len(doc.comments)==1
