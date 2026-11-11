"""B2: shared spec layout, source/open comments and numbering through real export."""
import ast
import json
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from docx import Document
import pytest

from test_hierarchical_content import ws, seed
from test_m1_g3_integration import method_commission, save, approve, writer, persist
from test_m1_g3_followup import synthetic_pilot_plan

ROOT = Path(__file__).parents[1]
NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

def test_unscored_data_uses_the_same_spec_and_retains_all_grade_rows():
    from report_agent.risk_scoring import _table_records
    from report_agent.table_spec import compile_table
    pack = json.loads((ROOT/'src/report_agent/methods/high_slope_guideline.json').read_text())
    rule = pack['indicators'][0]
    result = dict(status='unscored', rows=[], open_rows=[
        dict(indicator_id=rule['id'], rank=1, weight='1', reason='待工程复核。',
             alternatives=[g['id'] for g in rule['grades'][:2]], sources=[], question='请确认条件。')])
    data = _table_records(pack, result, '坡段 A', '3.1')
    spec = json.loads((ROOT/'src/report_agent/methods/high_slope_tables.json').read_text())['table_specs']['evaluation']
    spec['sources'] = [dict(source_ref=dict(type='SourceArtifact',id='method',version=1),locator='page 1',quote='')]
    spec.pop('source_pages')
    table = compile_table(spec, data)
    assert table['caption'].startswith('表3.1-2 ')
    assert table['column_weights'] == spec['column_weights']
    assert table['column_weights'][-1] > table['column_weights'][0]*4
    assert len(data['evaluation']['rows']) == len(rule['presentation_rows'])
    assert all(row['value'] == row['score'] == '未评分' for row in data['evaluation']['rows'])
    assert all('待工程复核；条件分级' in row['explanation'] and '。；' not in row['explanation']
               for row in data['evaluation']['rows'])

def test_slope_subsection_and_captions_follow_the_skeleton(method_commission):
    f = method_commission
    saved = save(f, synthetic_pilot_plan(f))
    approve(f, saved)
    from test_m1_g3_integration import persistence_input
    assessment = persistence_input(f)
    assessment['method_version'] = 2
    receipt = persist(f, writer(f, saved), assessment)
    assert f.cs.read(receipt['ranking_ref'])['payload']['body']['caption'].startswith('表4.1-1 ')

def test_open_comments_use_the_agreed_author_and_prefix(ws):
    from report_agent.content_export import export_snapshot
    from test_m1_g3_exports import fixture
    cs, actor, snapshot, _ = fixture(ws)
    result = export_snapshot(cs, actor, 'b2-comments', snapshot, {'toc':False})['result']
    word = Document(ws.store.root/result['file_ref'])
    assert len(word.comments) == 2
    assert all(c.author == '待核' and c.text.startswith('待核：') for c in word.comments)

@pytest.mark.parametrize('purpose', ['commission','source_or_applicable_standard'])
def test_source_is_a_comment_and_commission_instructions_are_never_cited(ws, purpose):
    from report_agent.content_export import export_snapshot
    from report_agent.commission_imports import install_source_roles
    cs, actor, refs, _, members = seed(ws)
    from report_agent.catalog import Catalog
    from test_ingestion import pdf_bytes
    source_id = Catalog(ws.store).import_file('design.pdf', pdf_bytes(('Source statement.',)))['source']['id']
    imported = cs.import_inputs(actor, 'b2-source-input', [source_id])['result']
    source = imported['source_refs'][0]
    members += [source, imported['requirement_ref']]
    title = cs.read(source)['payload']['source_metadata']['title']
    install_source_roles(ws.store, {'input':dict(id=source_id,purpose=purpose)})
    added = cs.commit(actor,'b2-statement',[
        dict(client_key='statement',type='ContentNode',payload=dict(kind='block',body=dict(text='支持的陈述。', material_issues=[dict(id='b2-instruction-issue',kind='unclear',
                object_label='坡段 A',basis='资料待核',sources=[dict(document=title,page=1)],adopted_value='未评分',
                question='请核对。',anchor=dict(text='支持的陈述。'),affects_level=True)]),
            qualifiers={},claim_kind='fact',citations=[dict(source_ref=source,locator='page 1',quote='')])),
        dict(client_key='edge',type='Relation',payload=dict(subject_ref=refs['root'],object_ref=dict(client_key='statement'),
            predicate='contains',position=1,provenance_kind='adopted_during_generation'))])['result']['refs']
    snapshot = cs.freeze(actor,'b2-freeze',refs['root'],members+list(added.values()))['result']['snapshot_ref']
    saved_statement = cs.read(added['statement'])
    result = export_snapshot(cs,actor,'b2-source-export',snapshot,{'toc':False})['result']
    assert cs.read(added['statement']) == saved_statement
    word = Document(ws.store.root/result['file_ref'])
    assert all(title not in p.text for p in word.paragraphs)
    source_comments = [c for c in word.comments if c.author=='来源']
    assert len(source_comments) == (0 if purpose=='commission' else 1)
    if source_comments:
        assert source_comments[0].text == '来源：《'+title+'》第1页'
    opened = [c for c in word.comments if c.author == '待核']
    assert len(opened) == 1
    assert ('《'+title+'》第1页' in opened[0].text) == (purpose != 'commission')
    from openpyxl import load_workbook
    book = load_workbook(ws.store.root/result['workbook']['file_ref'])
    source_text = str(book['资料澄清清单'].cell(2,4).value or '')
    assert ('《'+title+'》第1页' in source_text) == (purpose != 'commission')
    book.close()

def test_assessment_format_definitions_live_only_in_the_renderer():
    bad = []
    for path in (ROOT/'src/report_agent').rglob('*.py'):
        if path.name == 'table_spec.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            pairs = (list(zip(node.keys,node.values)) if isinstance(node,ast.Dict) else
                     [(ast.Constant(k.arg),k.value) for k in node.keywords if k.arg] if isinstance(node,ast.Call) else [])
            for key,value in pairs:
                if not isinstance(key,ast.Constant):
                    continue
                literals = {n.value for n in ast.walk(value) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
                if key.value=='columns' and (literals >= {'指标','重要性排序','权重'} or
                    literals >= {'序号','评估指标','权重系数'} or
                    literals >= {'分类','评估指标','分值范围','取值','说明'} or
                    literals >= {'指标','采用值','得分','取值依据或未评分原因'} or
                    literals >= {'因素','分级描述','采用值','得分'}):
                    bad.append(f'{path.name}:{node.lineno}')
                if key.value in {'caption','caption_pattern'} and any(
                    text in part for text in ('指标重要性排序表','施工安全风险评价表','权重系数排序','施工安全总体风险评估表')
                    for part in literals):
                    bad.append(f'{path.name}:{node.lineno}')
    assert not bad, bad


def test_exported_word_matches_spec_and_open_comments_match_excel(ws):
    from report_agent.risk_scoring import _table_records
    from report_agent.table_spec import compile_table, compile_header
    from report_agent.content_export import export_snapshot
    from test_m1_g3_exports import fixture
    from openpyxl import load_workbook
    pack = json.loads((ROOT/'src/report_agent/methods/high_slope_guideline.json').read_text())
    rule = pack['indicators'][0]
    data = _table_records(pack, dict(rows=[],open_rows=[dict(indicator_id=rule['id'],rank=1,weight='1',
        reason='尚无工程判断',alternatives=[],sources=[],question='请补充资料。')]), '坡段 A', '3.1')
    spec = json.loads((ROOT/'src/report_agent/methods/high_slope_tables.json').read_text())['table_specs']['evaluation']
    spec.pop('source_pages')
    spec['sources'] = [dict(source_ref=dict(type='SourceArtifact',id='method',version=1),locator='page 1',quote='')]
    body = compile_table(spec,data)
    body.pop('row_origins')
    body['material_issues'] = [dict(id='b2-open',kind='unclear',object_label='坡段 A',basis='尚无工程判断',sources=[],
        adopted_value='未评分',question='请补充资料。',anchor=dict(row=0,column=5),affects_level=True)]
    cs,actor,snapshot,_ = fixture(ws,body)
    result = export_snapshot(cs,actor,'b2-contract',snapshot,{'toc':False})['result']
    word = Document(ws.store.root/result['file_ref'])
    expected = compile_header(spec)
    rows = expected['header_rows']
    for merge in expected['header_merges']:
        value = rows[merge['start_row']][merge['start_col']]
        for r in range(merge['start_row'],merge['end_row']+1):
            for c in range(merge['start_col'],merge['end_col']+1): rows[r][c] = value
    assert [[c.text for c in row.cells] for row in word.tables[0].rows[:len(rows)]] == rows
    assert body['caption'] in [p.text for p in word.paragraphs]
    assert all(not p.text.startswith('（') for p in word.paragraphs)
    assert {c.author for c in word.comments} <= {'来源','待核'}
    opened = [c for c in word.comments if c.author=='待核']
    assert len(opened)==1 and opened[0].text.startswith('待核：')
    mapping = cs.read(result['workbook']['mapping_ref'])['payload']['anchor_records']
    issue_rows = [r for r in mapping if r.get('kind')=='material-issue']
    assert [r['issue_id'] for r in issue_rows] == ['b2-open']
    book = load_workbook(ws.store.root/result['workbook']['file_ref'])
    assert book[issue_rows[0]['sheet']].cell(issue_rows[0]['row_start'],6).value == '未评分'
    book.close()
    with ZipFile(ws.store.root/result['file_ref']) as archive:
        xml = etree.fromstring(archive.read('word/document.xml'))
        start = xml.find('.//w:commentRangeStart',NS)
        assert start is not None
        cell = next(parent for parent in start.iterancestors() if parent.tag.endswith('}tc'))
        assert ''.join(cell.itertext()) == '未评分'


def test_missing_assessment_spec_refuses_export():
    from report_agent.g3_export import validate_export
    from report_agent.errors import ActionRejected
    from test_m1_g3_presentation import fixture, ref
    cs, snapshot, records, keys = fixture()
    node = records[('ContentNode','extracted',1)]['payload']
    node['kind'] = 'table'
    node['body'] = dict(section_id='2', assessment_ref=ref('Assessment','score'), assessment_part='evaluation',
        columns=['value'],rows=[['40']])
    with pytest.raises(ActionRejected,match='assessment table spec required'):
        validate_export(cs,snapshot,records,keys)
