"""Offline G3 presentation and visible-content boundary tests."""
from copy import deepcopy

import pytest

from report_agent.errors import ActionRejected
from test_m1_g3_integration import method_commission
from test_section_writing import reviewed_writing


def ref(kind, identifier):
    return {'type': kind, 'id': identifier, 'version': 1}


def fixture():
    source = ref('SourceArtifact', 'source')
    citation = {'source_ref': source, 'locator': 'page 96', 'quote': '项目甲\n风险报告\n机构甲\n2026年\n负责人甲\n原文旧值\n现场事实'}
    root = ref('ContentNode', 'root')
    title = ref('ContentNode', 'title')
    fixed = ref('ContentNode', 'fixed')
    extracted = ref('ContentNode', 'extracted')
    plan_ref = ref('CommissionPlan', 'plan')
    front = {'project_name': '项目甲', 'report_name': '风险报告', 'organization': '机构甲', 'date': '2026年'}
    def node(r, body, kind='block', citations=None):
        return {'ref': r, 'payload': {'kind': kind, 'body': body, 'qualifiers': {}, 'claim_kind': 'fact', 'citations': deepcopy(citations or [citation]), 'working_notes': ''}}
    records = [
        {'ref': source, 'payload': {'source_metadata': {'title': '设计文件'}, 'content': citation['quote'], 'file_digest': 'ca9fe227372741d7d81646dd66ee926bb7829d5fe2a1c2701a865036e3fda4cf'}},
        node(root, {'text': '\n'.join(front.values()), 'front_matter': front}, 'report'),
        node(title, {'text': '项目甲\n风险报告\n负责人甲\n机构甲\n2026年', 'page_role': 'title_page', 'front_matter': {**front, 'leader': '负责人甲'}}),
        node(fixed, {'text': '原文新值', 'section_id': '1.1'}),
        node(extracted, {'text': '现场事实', 'section_id': '2'}),
        {'ref': plan_ref, 'payload': {'objects': [], 'method_pack': {'method_id': 'fixture'}, 'format_source': citation, 'sections': [
            {'section_id': '1.1', 'kind': 'fixed', 'sources': [{**citation, 'quote': '原文旧值'}], 'replacements': [{'old': '旧值', 'new': '新值'}]},
            {'section_id': '2', 'kind': 'extracted', 'sources': [citation]},
        ]}},
    ]
    for i, child in enumerate((title, fixed, extracted)):
        records.append({'ref': ref('Relation', str(i)), 'payload': {'predicate': 'contains', 'subject_ref': root, 'object_ref': child, 'position': i}})
    records = {tuple(r['ref'][k] for k in ('type', 'id', 'version')): r for r in records}
    snapshot = {'payload': {'root_ref': root, 'commission_plan_ref': plan_ref}}
    keys = {k for k in records if k[0] == 'ContentNode'}
    return None, snapshot, records, keys


def test_legacy_layout_unchanged_and_inputs_not_mutated():
    from report_agent.g3_export import prepare_export
    cs, snap, records, keys = fixture()
    del snap['payload']['commission_plan_ref']
    raw = {'toc': False, 'line_spacing': 1.2}
    assert prepare_export(cs, snap, records, keys, raw) == raw


def test_g3_defaults_exact_selectors_and_three_level_toc():
    from report_agent.g3_export import prepare_export
    from report_agent.content_layout import LayoutOptions, validate_layout
    args = fixture()
    before = deepcopy(args[1:])
    layout = prepare_export(*args, None)
    assert layout['right_margin_mm'] == 15
    assert layout['line_spacing'] == layout['table_line_spacing'] == 1.5
    assert layout['toc_depth'] == 3 and layout['page_numbers']
    assert layout['outer_border_style'] == 'double' and layout['outer_border_width_pt'] == .5
    styles = {s['name']: s for s in layout['styles']}
    assert styles['Normal']['first_line_indent_chars'] == 2
    assert styles['Heading 1']['font_size'] == 18
    assert styles['Heading 2']['space_before_lines'] == .2
    assert [(h['position'], h['text']) for h in layout['header_parts']] == [('left', '项目甲'), ('right', '风险报告')]
    validate_layout(LayoutOptions.model_validate(layout), args[2], args[3])
    assert args[1:] == before


@pytest.mark.parametrize('raw', [
    {'toc': False}, {'right_margin_mm': 25}, {'styles': [{'name': 'Normal', 'font_family': 'Arial'}]},
    {'nodes': [{'node_ref': ref('ContentNode', 'extracted'), 'paragraphs': [{'text': '现场事实', 'font_size': 14}]}]},
])
def test_conflicting_overrides_rejected(raw):
    from report_agent.g3_export import prepare_export
    with pytest.raises(ActionRejected, match='G3_'):
        prepare_export(*fixture(), raw)


def test_fixed_text_drift_and_wrong_extracted_citation_aggregate():
    from report_agent.g3_export import validate_export
    args = fixture()
    args[2][('ContentNode', 'fixed', 1)]['payload']['body']['text'] = '改写原文'
    args[2][('ContentNode', 'extracted', 1)]['payload']['citations'] = []
    with pytest.raises(ActionRejected) as exc:
        validate_export(*args)
    assert '1.1' in str(exc.value) and 'extracted' in str(exc.value)


@pytest.mark.parametrize('value', ['source_id: hidden', 'current_limits', '["内部", "列表"]', '下一步撰写该章节', 'identifier: 123e4567-e89b-12d3-a456-426614174000'])
def test_visible_internal_material_rejected_but_working_notes_excluded(value):
    from report_agent.g3_export import validate_export
    args = fixture()
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    node['working_notes'] = value
    validate_export(*args)
    node['body']['text'] = value
    with pytest.raises(ActionRejected, match='extracted'):
        validate_export(*args)


def test_unrendered_dependency_does_not_leak_into_validation():
    from report_agent.g3_export import validate_export
    args = fixture()
    args[2][('ContentNode', 'unrendered', 1)] = {'ref': ref('ContentNode', 'unrendered'), 'payload': {'kind': 'block', 'body': {'text': 'source_id: unsafe'}, 'qualifiers': {}}}
    validate_export(args[0], args[1], args[2], None)


def test_front_selectors_require_unique_source_cited_lines_and_title_page():
    from report_agent.g3_export import prepare_export
    args = fixture()
    args[2][('ContentNode', 'root', 1)]['payload']['body']['front_matter']['project_name'] = '伪造项目'
    with pytest.raises(ActionRejected, match='front'):
        prepare_export(*args, None)


def test_title_page_cannot_hide_report_sections_before_toc():
    from report_agent.g3_export import prepare_export
    args = fixture()
    args[2][('Relation', '1', 1)]['payload']['subject_ref'] = ref('ContentNode', 'title')
    with pytest.raises(ActionRejected, match='TITLE_PAGE_MUST_BE_LEAF'):
        prepare_export(*args, None)


def test_readable_citations_do_not_fallback_to_private_ids():
    from report_agent.g3_export import citation_text
    _, _, records, _ = fixture()
    node = records[('ContentNode', 'extracted', 1)]['payload']
    assert citation_text(node, records) == '《设计文件》第96页'
    records[('SourceArtifact', 'source', 1)]['payload']['source_metadata'] = {}
    with pytest.raises(ActionRejected):
        citation_text(node, records)


def test_genuine_markdown_source_line_is_rendered_as_chinese_location():
    from report_agent.g3_export import citation_text
    _, _, records, _ = fixture()
    node = records[('ContentNode', 'extracted', 1)]['payload']
    node['citations'][0]['locator'] = 'line 23'
    records[('SourceArtifact', 'source', 1)]['payload']['source_metadata']['title'] = '报告编写范围说明'
    assert citation_text(node, records) == '《报告编写范围说明》第23行'
    node['citations'][0]['locator'] = 'line 0'
    with pytest.raises(ActionRejected, match='LOCATION_NOT_READABLE'):
        citation_text(node, records)


def test_fixed_section_citations_not_appended_and_same_source_version_required():
    from report_agent.g3_export import citation_text, validate_export
    args = fixture()
    plan = args[2][('CommissionPlan', 'plan', 1)]['payload']
    assert citation_text(args[2][('ContentNode', 'fixed', 1)]['payload'], args[2], plan) == '《设计文件》第96页'
    assert citation_text(args[2][('ContentNode', 'root', 1)]['payload'], args[2], plan) == ''
    assert citation_text(args[2][('ContentNode', 'title', 1)]['payload'], args[2], plan) == ''
    args[2][('ContentNode', 'extracted', 1)]['payload']['citations'][0]['source_ref']['version'] = 2
    with pytest.raises(ActionRejected):
        validate_export(*args)


def test_missing_fixed_section_rejected():
    from report_agent.g3_export import validate_export
    args = fixture()
    args[3].remove(('ContentNode', 'fixed', 1))
    with pytest.raises(ActionRejected, match='1.1'):
        validate_export(*args)


def test_extracted_allows_guideline_support_beside_named_design_source():
    from report_agent.g3_export import validate_export
    args = fixture()
    extra = ref('SourceArtifact', 'guideline')
    args[2][('SourceArtifact', 'guideline', 1)] = {'ref': extra, 'payload': {'source_metadata': {'title': '指南'}}}
    args[2][('ContentNode', 'extracted', 1)]['payload']['citations'].append({'source_ref': extra, 'locator': 'page 17'})
    validate_export(*args)


def test_valid_engineering_labels_and_ordinary_english_are_not_internal_keys():
    from report_agent.g3_export import validate_export
    args = fixture()
    args[2][('ContentNode', 'extracted', 1)]['payload']['body']['text'] = 'E: 30 MPa；Note: calculation based on design evidence.'
    validate_export(*args)


def test_unreviewed_format_source_does_not_receive_hardcoded_layout():
    from report_agent.g3_export import prepare_export
    args = fixture()
    args[2][('SourceArtifact', 'source', 1)]['payload']['file_digest'] = 'b' * 64
    with pytest.raises(ActionRejected, match='format capability unavailable'):
        prepare_export(*args, None)


def test_method_pack_without_format_selection_does_not_impose_customer_layout():
    from report_agent.g3_export import prepare_export
    args = fixture()
    del args[2][('CommissionPlan', 'plan', 1)]['payload']['format_source']
    raw = {'toc': False, 'right_margin_mm': 30}
    assert prepare_export(*args, raw) == raw


def test_markdown_tables_request_typed_conversion_instead_of_wrong_format():
    from report_agent.g3_export import validate_export
    args = fixture()
    args[2][('ContentNode', 'extracted', 1)]['payload']['body']['text'] = '| 指标 | 值 |\n| --- | --- |\n| 地层 | 75 |'
    with pytest.raises(ActionRejected, match='convert Markdown tables'):
        validate_export(*args)


def test_comment_text_is_visible_but_issue_identity_is_not():
    from report_agent.g3_export import validate_export
    args = fixture()
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    issue = {'id': '123e4567-e89b-12d3-a456-426614174000', 'kind': 'no_evidence_assumption',
             'object_label': '坡甲', 'basis': '无间接资料', 'sources': [], 'adopted_value': '现场事实',
             'question': '请确认事实', 'anchor': {'text': '现场事实'}, 'affects_level': False}
    node['body']['material_issues'] = [issue]
    validate_export(*args)
    issue['basis'] = 'source_id: internal'
    with pytest.raises(ActionRejected, match='extracted'):
        validate_export(*args)


@pytest.mark.parametrize('surface', ['cell_comment', 'header'])
def test_new_table_visible_surfaces_receive_internal_text_preflight(surface):
    from report_agent.g3_export import validate_export
    args = fixture()
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    node['kind'] = 'table'
    node['body'] = {'section_id': '2', 'columns': ['指标', '值'], 'rows': [['坡高', '100']],
                    'caption': '4.2.1-1 坡甲评价表', 'header_rows': [['指标', '值']],
                    'cell_comments': [{'anchor': {'row': 0, 'column': 1}, 'value': '100', 'text': '依据设计资料排序。'}]}
    validate_export(*args)
    if surface == 'cell_comment':
        node['body']['cell_comments'][0]['text'] = 'source_id: private'
        validate_export(*args)
        assert node['body']['cell_comments'][0]['text'] == 'source_id: private'
    else:
        node['body']['header_rows'][0][0] = 'source_id: private'
        with pytest.raises(ActionRejected, match='extracted'):
            validate_export(*args)


def test_serialized_layout_roundtrip_preserves_same_mandatory_format():
    from report_agent.content_layout import LayoutOptions
    from report_agent.g3_export import prepare_export
    args = fixture()
    selected = LayoutOptions.model_validate(prepare_export(*args, None)).model_dump()
    assert LayoutOptions.model_validate(prepare_export(*args, selected)).model_dump() == selected


@pytest.mark.parametrize('part', ['ranking','evaluation'])
def test_assessment_tables_do_not_infer_legacy_widths(part):
    import json
    from importlib.resources import files
    from report_agent.content_layout import LayoutOptions
    from report_agent.g3_export import prepare_export
    from report_agent.table_spec import compile_header
    args = fixture()
    plan = args[2][('CommissionPlan', 'plan', 1)]['payload']
    specs = json.loads(files('report_agent').joinpath('methods/high_slope_tables.json').read_text())['table_specs']
    for spec in specs.values():
        spec.pop('source_pages')
        spec['sources'] = [plan['format_source']]
    plan['table_specs'] = specs
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    columns = compile_header(specs[part])['columns']
    node['kind'] = 'table'
    node['body'] = dict(section_id='2', assessment_ref=ref('Assessment','score'),assessment_part=part,
                        columns=columns,rows=[['值']*len(columns)],caption='表4.1-1 坡甲评价表')
    def selected(raw=None):
        return next(n for n in prepare_export(*args,raw)['nodes'] if n['node_ref']['id']=='extracted')
    assert not selected().get('column_weights')
    custom = [2]*len(columns)
    assert selected({'nodes':[dict(node_ref=ref('ContentNode','extracted'),column_weights=custom)]})['column_weights']==custom
    serialized = LayoutOptions.model_validate(prepare_export(*args,None)).model_dump()
    assert LayoutOptions.model_validate(prepare_export(*args,serialized)).model_dump()==serialized


def test_historical_generated_ranking_requires_regeneration_without_mutating_saved_body():
    from copy import deepcopy
    from report_agent.g3_export import validate_export
    args = fixture()
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    node['kind'] = 'table'
    node['body'] = {'section_id': '2', 'assessment_ref': ref('Assessment', 'score'),
                    'assessment_part': 'ranking', 'columns': ['指标', '重要性排序', '权重', '排序理由'],
                    'rows': [['坡高', '1', '0.2', '设计控制因素']], 'caption': '排序表'}
    before = deepcopy(node['body'])
    with pytest.raises(ActionRejected, match='assessment table spec required'):
        validate_export(*args)
    assert node['body'] == before


def test_fixed_source_views_require_exact_materialized_receipt(monkeypatch):
    from types import SimpleNamespace
    from report_agent.g3_export import validate_export
    from report_agent.store import digest
    from report_agent import report_state
    args = list(fixture())
    record = args[2][('ContentNode', 'fixed', 1)]
    source_record = args[2][('SourceArtifact', 'source', 1)]
    source_record['payload']['source_id'] = 'native-pdf'
    body = record['payload']['body']
    body['source_views'] = [{'text': '原文新值', 'source_ref': ref('SourceArtifact', 'source'),
                            'source_id': 'native-pdf', 'page': 96, 'crop': [.1, .1, .9, .9]}]
    receipt = {'node_ref': record['ref'], 'commission_plan_ref': args[1]['payload']['commission_plan_ref'],
               'section_id': '1.1', 'text_digest': digest(body['text']),
               'source_views_digest': digest(body['source_views'])}
    args[0] = SimpleNamespace(store=SimpleNamespace(get=lambda key: receipt if key == 'planned_section_receipt:' + digest(record['ref']) else None))
    monkeypatch.setattr(report_state, 'native', lambda *args: False)
    monkeypatch.setattr(report_state, 'planned_section',
                        lambda storage, target: receipt if target == record['ref'] else None)
    validate_export(*args)
    source_record['payload']['source_id'] = 'different-pdf'
    with pytest.raises(ActionRejected, match='source view pinned source'):
        validate_export(*args)
    source_record['payload']['source_id'] = 'native-pdf'
    for field, wrong in [('node_ref', ref('ContentNode', 'forged')), ('commission_plan_ref', ref('CommissionPlan', 'stale')),
                         ('section_id', '2'), ('text_digest', 'stale'), ('source_views_digest', 'stale')]:
        original = receipt[field]
        receipt[field] = wrong
        with pytest.raises(ActionRejected, match='source view receipt'):
            validate_export(*args)
        receipt[field] = original
    body['source_views'][0]['crop'][0] = .2
    with pytest.raises(ActionRejected, match='source view receipt'):
        validate_export(*args)
    body['source_views'][0]['crop'][0] = .1
    args[0] = None
    with pytest.raises(ActionRejected, match='source view receipt'):
        validate_export(*args)


def test_source_views_cannot_hide_nonfixed_content_or_frontmatter():
    from report_agent.g3_export import validate_export
    for identifier in ('extracted', 'root', 'title'):
        args = fixture()
        args[2][('ContentNode', identifier, 1)]['payload']['body']['source_views'] = [{'text': '隐藏文字'}]
        with pytest.raises(ActionRejected, match='source view receipt'):
            validate_export(*args)


def test_assessment_receipt_requires_all_three_exact_selected_nodes(tmp_path):
    from types import SimpleNamespace
    from report_agent.g3_export import validate_export
    from report_agent.store import digest
    args = list(fixture())
    assessment = ref('Assessment', 'score')
    outcome = ref('AssessmentOutcome', 'outcome')
    args[1]['payload']['commission_outcome_refs'] = [outcome]
    args[2][('AssessmentOutcome', 'outcome', 1)] = {'ref': outcome, 'payload': {'assessment_ref': assessment}}
    receipt = {'ranking_ref': ref('ContentNode', 'ranking'), 'evaluation_ref': ref('ContentNode', 'evaluation'), 'level_ref': ref('ContentNode', 'extracted')}
    from report_agent.store import Store
    store = Store(tmp_path)
    from report_agent.content_store import Actor, ContentStore
    cs = ContentStore(store)
    result = dict(adopted=dict(total='40', level='II'))
    with store.connect() as db:
        cs._insert(db, Actor('archived-writer','writer','old-task'), 'Assessment',
            dict(commission_plan_ref=ref('CommissionPlan','plan'), object_id='S1', result=result), id=assessment['id'])
    receipt.update(assessment_ref=assessment, result=result, evidence_ref=ref('Evidence','old-calculation'))
    store.set('assessment_receipt:' + digest(assessment), receipt)
    args[0] = SimpleNamespace(store=store)
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    node['body'].update(assessment_ref=assessment, assessment_part='level')
    with pytest.raises(ActionRejected, match='three generated'):
        validate_export(*args)
    args[3].update({('ContentNode', 'ranking', 1), ('ContentNode', 'evaluation', 1)})
    validate_export(*args)
    receipt['level_ref'] = {**receipt['level_ref'], 'version': 2}
    store.set('assessment_receipt:' + digest(assessment), receipt)
    with pytest.raises(ActionRejected, match='receipt mismatch'):
        validate_export(*args)


def test_derived_receipt_cannot_be_reused_for_rewritten_text(monkeypatch):
    from types import SimpleNamespace
    from report_agent.g3_export import validate_export
    from report_agent.store import digest
    from report_agent import report_state
    args = list(fixture())
    args[2][('CommissionPlan', 'plan', 1)]['payload']['sections'][1]['kind'] = 'derived'
    node_ref = ref('ContentNode', 'extracted')
    receipt = {'node_ref': node_ref, 'commission_plan_ref': ref('CommissionPlan', 'plan'), 'section_id': '2', 'assessment_refs': [], 'text_digest': digest('现场事实')}
    args[0] = SimpleNamespace(store=SimpleNamespace(get=lambda key: receipt))
    monkeypatch.setattr(report_state, 'native', lambda *args: False)
    monkeypatch.setattr(report_state, 'planned_section', lambda storage, target: receipt)
    validate_export(*args)
    args[2][('ContentNode', 'extracted', 1)]['payload']['body']['text'] = '另一个结论'
    with pytest.raises(ActionRejected, match='derived section receipt mismatch'):
        validate_export(*args)


def test_format_controls_written_into_actual_docx_bytes():
    from io import BytesIO
    from docx import Document
    from docx.oxml.ns import qn
    from report_agent import content_layout
    from report_agent.g3_export import prepare_export
    args = fixture()
    options = content_layout.LayoutOptions.model_validate(prepare_export(*args, None))
    doc = Document()
    content_layout.setup(doc, options)
    for item in options.nodes:
        for control in item.paragraphs:
            p = doc.add_paragraph(control.text)
            content_layout.apply_paragraph(p, control)
    content_layout.add_toc(doc, [('第一章 概述', 1), ('1.1 编制', 2), ('1.1.1 范围', 3)], 3, options=options)
    stream = BytesIO()
    doc.save(stream)
    result = Document(BytesIO(stream.getvalue()))
    assert round(result.sections[0].right_margin.mm) == 15
    assert result.styles['Heading 1'].font.size.pt == 18
    assert result.styles['Normal'].element.rPr.rFonts.get(qn('w:eastAsia')) == '宋体'
    assert result.styles['Normal'].element.rPr.rFonts.get(qn('w:ascii')) == 'Times New Roman'
    cover_report = next(p for p in result.paragraphs if p.text == '风险报告')
    assert cover_report.runs[0].font.size.pt == 36
    title_reports = [p for p in result.paragraphs if p.text == '风险报告']
    assert title_reports[1].runs[0].font.size.pt == 26
    assert '项目甲' in result.sections[0].header.paragraphs[0].text
    assert '风险报告' in result.sections[0].header.paragraphs[0].text
    assert 'TOC \\o "1-3"' in result.element.xml


def test_explicit_section_and_literal_heading_lines_receive_four_levels():
    from report_agent.g3_export import prepare_export
    args = fixture()
    node = args[2][('ContentNode', 'extracted', 1)]['payload']
    node['body']['text'] = '第一章 概述\n1.1 编制\n1.1.1 范围\n（1）项目内容\n普通正文'
    prepared = prepare_export(*args, None)
    controls = next(n for n in prepared['nodes'] if n['node_ref']['id'] == 'extracted')['paragraphs']
    assert [p['heading_level'] for p in controls] == [1, 2, 3, 4]
    assert [p['font_size'] for p in controls] == [18, 15, 14, 12]
    section = args[2][('CommissionPlan', 'plan', 1)]['payload']['sections'][1]
    section.update(section_id='2.1', title='工程条件')
    node['body'].update(section_id='2.1', section_heading=True, text='2.1 工程条件')
    prepared = prepare_export(*args, None)
    control = next(n for n in prepared['nodes'] if n['node_ref']['id'] == 'extracted')
    assert control['heading_level'] == control['paragraphs'][0]['heading_level'] == 2


def test_real_export_single_newline_frontmatter_before_toc(tmp_path):
    """Renderer integration only: seeded records bypass commission/source authorization."""
    from io import BytesIO
    from docx import Document
    from report_agent.content_export import export_snapshot
    from report_agent.content_store import ContentStore
    from report_agent.hierarchical_tools import actor_for
    from report_agent.store import Store
    store = Store(tmp_path)
    store.initialize({'goal': 'Offline presentation fixture', 'sources': [{'id': 'synthetic-source', 'title': '资料', 'content': 'Synthetic source text', 'coverage': 'complete'}], 'review_entrypoint': 'native-rubric-v1'})
    cs, actor = ContentStore(store), actor_for('coordinator')
    _, snap, records, _ = fixture()
    records[('SourceArtifact', 'source', 1)]['payload']['source_id'] = 'synthetic-source'
    with store.connect() as db:
        for record in records.values():
            cs._insert(db, actor, record['ref']['type'], record['payload'], id=record['ref']['id'])
        snapshot = cs._insert(db, actor, 'DocumentSnapshot', {**snap['payload'], 'refs': [r['ref'] for r in records.values()]})
    result = export_snapshot(cs, actor, 'real-frontmatter-export', snapshot)['result']
    doc = Document(BytesIO((store.root/result['file_ref']).read_bytes()))
    texts = [n.text for n in doc.element.body.xpath('.//w:t') if n.text]
    assert texts.count('负责人甲') == 1
    assert texts.index('负责人甲') < texts.index('目录') < texts.index('原文新值')
    assert texts[:4] == ['项目甲', '风险报告', '机构甲', '2026年']
    assert not any('source_id' in text or 'working_notes' in text for text in texts)
    assert 'Source copy' not in '\n'.join(texts)


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_export_after_input_withdrawal_identifies_generated_and_derived_section_scores(reviewed_writing):
    from report_agent.assessment_projection import assessment_receipt, selected_assessment
    from report_agent.assertion_host import AssertionHost
    from report_agent.content_export import export_snapshot
    from report_agent.section_writing import save_section_prose
    from report_agent.system_assembler import assemble_current_report
    from test_assessment_refresh import act

    f = reviewed_writing
    save_section_prose(f.cs, f.writer, 'prose', '4', 'S1 design height is 30 metres.', [f.cite('design')])
    snapshot = assemble_current_report(f.cs, f.co, 'assemble')['result']['snapshot_ref']
    with f.cs.store.connect() as db:
        receipt = assessment_receipt(db, selected_assessment(db, f.plan_ref, 'S1'))
    host = AssertionHost(f.cs.store.root)
    old = host.recover_receipt(receipt['derive_operation_id'])['result']
    act(host, f.plan_ref, 'S1', old['claim']['inputs'][0], 'retract')
    with pytest.raises(ActionRejected, match='G3_EXPORT_PREFLIGHT') as error:
        export_snapshot(f.cs, f.co, 'export-after-withdrawal', snapshot, {'toc':False})
    assert receipt['level_ref']['id'] + ': assessment score unavailable: stale' in str(error.value)
    assert 'derived section assessment score unavailable: stale' in str(error.value)
    assert not f.cs.list_objects('ExportArtifact')
