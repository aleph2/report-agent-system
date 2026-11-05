import pytest
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from openpyxl import load_workbook
from report_agent.material_issues import MaterialIssue
from report_agent.content_export import export_snapshot
from test_g5_offline_delivery import passage, ANCHOR
from test_m1_g3_exports import fixture
from test_hierarchical_content import ws

@pytest.mark.parametrize('affects,expected',[(True,'待复核（不能排除）'),(False,'本次评分未计入该事项；不评价实际工程风险')])
def test_unresolved_source_effect_is_scoped_and_word_excel_agree(ws,affects,expected):
    issue={**passage(),'affects_level':affects}
    typed=MaterialIssue.model_validate(issue)
    assert typed.impact_text()==expected
    assert '等级影响：'+expected in typed.comment()
    cs,actor,snapshot,_=fixture(ws,paragraph={'text':ANCHOR,'material_issues':[issue]})
    result=export_snapshot(cs,actor,'impact-pair',snapshot,{'toc':False})['result']
    with ZipFile(ws.store.root/result['file_ref']) as archive:
        comments=ET.fromstring(archive.read('word/comments.xml'))
        assert any(expected in ''.join(c.itertext()) for c in comments)
    mapping=cs.read(result['workbook']['mapping_ref'])['payload']['anchor_records']
    anchor=next(m for m in mapping if m.get('issue_id')==issue['id'])
    workbook=load_workbook(ws.store.root/result['workbook']['file_ref'])
    assert workbook[anchor['sheet']].cell(anchor['row_start'],9).value==expected
    workbook.close()

@pytest.mark.parametrize('kind,affects,expected',[('indirect_assumption',True,'是'),('indirect_assumption',False,'否'),('no_evidence_assumption',True,'是'),('no_evidence_assumption',False,'否')])
def test_calculated_assumption_effect_keeps_existing_yes_no(kind,affects,expected):
    issue={**passage(),'kind':kind,'affects_level':affects}
    if kind=='no_evidence_assumption':issue['sources']=[]
    typed=MaterialIssue.model_validate(issue)
    assert typed.impact_text()==expected
    assert '影响等级：'+expected in typed.comment()
