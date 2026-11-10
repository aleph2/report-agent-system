from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from docx import Document
from report_agent.content_export import export_snapshot
from report_agent.errors import ActionRejected
from report_agent.material_issues import MaterialIssue, comment_passage, validate_node
from test_m1_g3_exports import fixture
from test_hierarchical_content import ws

NODE = {"type": "ContentNode", "id": "a963fa86-d534-4631-8be6-e98b0790cae7", "version": 5}
ANCHOR = "经核对《指南》原文，指标体系及评估表格式为《指南》表3-2（p18～23）"

def passage():
    return dict(id="MI-3-2-01", kind="conflict", object_label="3.2 总体风险评估方法",
        basis="按指南实际表号引用", sources=[dict(document="指南", page=18)],
        adopted_value="本报告表3-1按指南表3-2编制；风险分级对应指南表3-3。",
        question="确认引用口径", anchor=dict(text=ANCHOR), affects_level=False)

def test_mi_3_2_01_anchor_is_passage_not_adopted_summary():
    issues, _ = validate_node(dict(kind="block", body=dict(text=ANCHOR, material_issues=[passage()])), NODE)
    doc = Document()
    unrelated = doc.add_paragraph(ANCHOR)
    own = doc.add_paragraph("前文 " + ANCHOR + " 后文")
    comment_passage(doc, [own], issues[0], NODE)
    assert not unrelated._p.xpath(".//w:commentRangeStart")
    assert len(own._p.xpath(".//w:commentRangeStart")) == 1
    assert len(doc.comments) == 1

@pytest.mark.parametrize("text", ["absent", ANCHOR + ANCHOR])
def test_anchor_refusal_names_issue_and_own_node(text):
    with pytest.raises(ActionRejected) as error:
        validate_node(dict(kind="block", body=dict(text=text, material_issues=[passage()])), NODE)
    assert "MI-3-2-01" in str(error.value) and NODE["id"] in str(error.value)
    doc = Document()
    with pytest.raises(ActionRejected) as error:
        comment_passage(doc, [doc.add_paragraph(text)], MaterialIssue.model_validate(passage()), NODE)
    assert "MI-3-2-01" in str(error.value) and NODE["id"] in str(error.value)

def test_word_automatically_exports_same_snapshot_excel(ws):
    cs, actor, snapshot, added = fixture(ws)
    result = export_snapshot(cs, actor, "paired-word", snapshot, {"toc": False})["result"]
    word = cs.read(result["export_ref"])["payload"]
    excel = cs.read(result["workbook"]["export_ref"])["payload"]
    assert excel["snapshot_ref"] == word["snapshot_ref"] == snapshot
    assert excel["export_config"]["report_export_ref"] == result["export_ref"]
    assert excel["export_config"]["material_issue_ids"] == word["export_config"]["material_issue_ids"]
    assert len(cs.list_objects("ExportArtifact")) == 2
    assert export_snapshot(cs, actor, "paired-word", snapshot, {"toc": False})["result"] == result

def test_failed_excel_does_not_commit_word_pair(ws, monkeypatch):
    import report_agent.content_workbook as workbook
    cs, actor, snapshot, _ = fixture(ws)
    def fail(*args, **kwargs):
        raise ActionRejected("EXCEL_TEST_FAILURE")
    monkeypatch.setattr(workbook, "_export_workbook", fail)
    with pytest.raises(ActionRejected, match="EXCEL_TEST_FAILURE"):
        export_snapshot(cs, actor, "failed-pair", snapshot)
    assert not cs.list_objects("ExportArtifact")


@pytest.fixture
def offline_case(ws, tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    store = Store(tmp_path / 'source')
    store.initialize(ws.store.manifest)
    return Workspace(store)


def test_offline_export_preserves_original_and_creates_pair(offline_case, tmp_path, monkeypatch):
    import socket
    from report_agent.offline_export import export_offline, hashes
    ws = offline_case
    cs, actor, snapshot, _ = fixture(ws)
    before = hashes(ws.store.root)
    def forbidden(*args, **kwargs):
        raise AssertionError("network not permitted")
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    output = tmp_path / 'offline'
    receipt = export_offline(ws.store.root, output)
    assert receipt['status'] == 'exported; verification pending', receipt.get('error')
    assert receipt['snapshot_ref'] == snapshot
    assert hashes(ws.store.root) == before and receipt['source_unchanged']
    assert (output / 'G5-report.docx').is_file()
    assert (output / 'G5-clarifications.xlsx').is_file()

def test_offline_export_reports_content_failure_without_patching(offline_case, tmp_path):
    from report_agent.offline_export import export_offline, hashes
    ws = offline_case
    cs, actor, snapshot, _ = fixture(ws, paragraph=dict(text='absent', material_issues=[passage()]))
    before = hashes(ws.store.root)
    output = tmp_path / 'offline'
    receipt = export_offline(ws.store.root, output)
    assert receipt['status'] == 'blocked'
    assert 'MI-3-2-01' in receipt['error']
    assert hashes(ws.store.root) == before and receipt['source_unchanged']
    assert not (output / 'G5-report.docx').exists()


@pytest.mark.parametrize('raw', [None, 7])
def test_malformed_issue_list_preserves_typed_refusal(raw):
    with pytest.raises(ActionRejected, match='MATERIAL_ISSUE_LIST_REQUIRED'):
        validate_node(dict(kind='block', body=dict(text='x', material_issues=raw)), NODE)

def test_full_export_scopes_duplicate_passage_to_its_node(ws):
    from test_hierarchical_content import seed
    cs, actor, refs, _, members = seed(ws)
    objects = []
    for index in range(2):
        key = f'paragraph-{index}'
        body = {'text': ANCHOR}
        if index == 1:
            body['material_issues'] = [passage()]
        objects.extend([{'client_key': key, 'type': 'ContentNode', 'payload': {
            'kind': 'block', 'body': body, 'qualifiers': {}, 'claim_kind': 'structure'}},
            {'client_key': f'edge-{index}', 'type': 'Relation', 'payload': {
                'subject_ref': refs['root'], 'object_ref': {'client_key': key}, 'predicate': 'contains',
                'position': index + 1, 'provenance_kind': 'adopted_during_generation'}}])
    added = cs.commit(actor, 'duplicate-passages', objects)['result']['refs']
    snapshot = cs.freeze(actor, 'duplicate-snapshot', refs['root'], members + list(added.values()))['result']['snapshot_ref']
    result = export_snapshot(cs, actor, 'duplicate-export', snapshot, {'toc': False})['result']
    doc = Document(ws.store.root / result['file_ref'])
    matches = [p for p in doc.paragraphs if p.text == ANCHOR]
    assert len(matches) == 2
    assert not matches[0]._p.xpath('.//w:commentRangeStart')
    assert len(matches[1]._p.xpath('.//w:commentRangeStart')) == 1


@pytest.mark.parametrize("locator,expected", [("page 1; chars 1-78", "PDF第1页"), ("line 9; chars 1-21", "第9行"), ("body/paragraph 2; chars 1-12", "第2段")])
def test_issue_citations_use_reader_locations_and_deduplicate(locator, expected):
    issue = MaterialIssue.model_validate({**passage(), "sources": [
        dict(document="资料", page=locator), dict(document="资料", page=locator)]})
    assert issue.source_text() == f"资料（{expected}）"
    assert "chars" not in issue.comment()
