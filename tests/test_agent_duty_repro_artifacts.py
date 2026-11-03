"""A01/A02: native fake Layout, real Office artifacts, independent oracles.

No application repair, production report mutation, or paid model invocation.
The fake model chooses explicit parameters: these tests do not establish that a
real Layout agent interprets the standard or makes the same decisions.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from langchain_core.messages import AIMessage, messages_to_dict

from report_agent import content_export
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_task_supervision import ws, offline


ROOT = Path(__file__).resolve().parents[1]
STANDARD = Path(__file__).parent / 'fixtures/format-standard-layout-20261019.json'


def save_evidence(request, ws, value, driver=None):
    """Archive before asserting, so a failing oracle retains its actual bytes."""
    value = deepcopy(value)
    value.update(workspace=str(ws.store.root), paid_calls=0,
                 visual_acceptance=False, model_chose_parameters=False)
    output = os.environ.get('REPORT_ARTIFACT_REPRO_OUT')
    if output:
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', request.node.name)
        target = Path(output) / name
        target.mkdir(parents=True, exist_ok=True)
        copied = []
        for item in value.get('assets', []):
            data = (ws.store.root / item['file_ref']).read_bytes()
            filename = Path(item['file_ref']).name
            (target / filename).write_bytes(data)
            copied.append({'path': filename, 'sha256': hashlib.sha256(data).hexdigest()})
        value['retained_assets'] = copied
        (target / 'evidence.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        if driver is not None:
            (target / 'native-model-inputs.json').write_text(json.dumps([
                {'role': role, 'step': step, 'messages': messages_to_dict(messages)}
                for role, step, messages in driver.calls], ensure_ascii=False, indent=2), encoding='utf-8')
        value['evidence_directory'] = str(target)
    request.node.user_properties.append(('artifact_reproduction', json.dumps(value, ensure_ascii=False)))


def structural_snapshot(ws, child_count=3, with_format_content=False):
    """Only structural synthetic text; no real engineering claim or source."""
    cs, owner = ContentStore(ws.store), actor_for('coordinator')
    root_text = 'Synthetic cover project' if with_format_content else 'Synthetic root report'
    objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': {
        'kind': 'report', 'body': {'text': root_text}, 'qualifiers': {}, 'claim_kind': 'structure'}}]
    contents = {'root': {'text': root_text}}

    def add(key, kind, body, parent, position):
        objects.append({'client_key': key, 'type': 'ContentNode', 'payload': {
            'kind': kind, 'body': body, 'qualifiers': {}, 'claim_kind': 'structure'}})
        objects.append({'client_key': key + '_edge', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': parent}, 'object_ref': {'client_key': key},
            'predicate': 'contains', 'position': position, 'provenance_kind': 'adopted_during_generation'}})
        contents[key] = body

    if with_format_content:
        add('h1', 'chapter', {'text': '第一章 测试标题 H1'}, 'root', 0)
        add('h2', 'chapter', {'text': '1.1 测试标题 H2'}, 'h1', 0)
        add('h3', 'chapter', {'text': '1.1.1 测试标题 H3'}, 'h2', 0)
        add('body', 'block', {'text': '合成正文 SAMPLE 2026，原文保持不变。'}, 'h3', 0)
        add('table', 'table', {'columns': ['项目 Item', '值 Value'], 'rows': [['类别 B', '75 分']]}, 'h3', 1)
    else:
        # Give the zero-child-report control a valid ordinary heading so that
        # actual Office TOC refresh has an index entry and isn't an empty fixture.
        add('ordinary_chapter', 'chapter', {'text': 'Ordinary heading\nROOT-BODY-MARKER'}, 'root', 0)
        for index in range(child_count):
            key = f'child_{index}'
            add(key, 'report', {'text': f'Nested report {index}\nEXACT-CHILD-BODY-{index}'}, 'root', index + 1)
            add(key + '_heading', 'chapter', {'text': f'Child heading {index}\nEXACT-NESTED-TEXT-{index}'}, key, 0)
    refs = cs.commit(owner, 'synthetic-nodes', objects)['result']['refs']
    snapshot = cs.freeze(owner, 'synthetic-snapshot', refs['root'], list(refs.values()))['result']['snapshot_ref']
    before = {key: cs.read(ref) for key, ref in refs.items()}
    return cs, refs, snapshot, before, contents


async def native_export_and_render(ws, cs, snapshot, layout, instruction):
    activate(ws)
    observed = {'layout': deepcopy(layout), 'instruction': instruction, 'assets': []}

    def render(messages):
        value = result_value(tool_reply(messages, 'native-export'))
        observed['export_return'] = value
        assert value.get('ok') is True, value
        exported = value['result']
        observed['export'] = exported
        observed['assets'].append({'file_ref': exported['file_ref'], 'kind': 'docx'})
        observed['export_record'] = cs.read(exported['export_ref'])
        return action('render_content_export', 'native-render', operation_id='native-render', export_ref=exported['export_ref'])

    def finish(messages):
        value = result_value(tool_reply(messages, 'native-render'))
        observed['render_return'] = value
        assert value.get('ok') is True, value
        rendered = value['result']
        assert rendered.get('execution_state') == 'completed', {'environment_or_render_failure': rendered}
        payload = cs.read(rendered['render_ref'])['payload']
        observed['render'] = payload
        observed['assets'].append({'file_ref': payload['pdf_ref'], 'kind': 'pdf'})
        for page in payload['page_assets']:
            data = (ws.store.root / page['asset_ref']).read_bytes()
            assert data.startswith(b'\x89PNG')
            assert hashlib.sha256(data).hexdigest() == page['sha256']
            observed['assets'].append({'file_ref': page['asset_ref'], 'kind': 'png', 'page': page['page']})
        return AIMessage(content='Synthetic export and real rendering complete; no visual or engineering acceptance.')

    driver = Driver(coordinator=[invoke('task', subagent_type='layout', layout_snapshot_ref=snapshot,
        description=instruction), AIMessage(content='Artifact received; independent acceptance remains open.')],
        layout=[action('export_content_snapshot', 'native-export', operation_id='native-export',
                       snapshot_ref=snapshot, layout=layout), render, finish])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    if result['last_error'] is not None:
        return observed, driver
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(ws.store.root / observed['render']['pdf_ref']) as pdf:
        texts = []
        for page in pdf:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
    observed['pdf_page_text'] = texts
    observed['renderer_identity'] = observed['render']['renderer_identity']
    return observed, driver


def toc_fields(doc):
    return [n.text for n in doc.element.iter(qn('w:instrText')) if re.match(r'\s*TOC\b', n.text or '')]


def assert_one_directory(observed, expected):
    assert observed['toc_count'] == expected, ('A01_LOGICAL_TOC_COUNT', observed['toc_count'], expected)


@pytest.mark.parametrize('child_count,toc', [(0, True), (1, True), (3, True), (3, False)])
async def test_a01_native_nested_reports_refresh_render_one_directory(ws, request, child_count, toc):
    cs, refs, snapshot, before, contents = structural_snapshot(ws, child_count)
    layout = {'toc': toc, 'refresh_toc': toc, 'toc_depth': 3}
    observed, driver = await native_export_and_render(ws, cs, snapshot, layout,
        'Preserve root and all nested reports. Export one automatic contents index when requested, then render.')
    observed.update(case='A01', child_report_count=child_count)
    if observed['runtime_result']['last_error'] is None:
        doc = Document(ws.store.root / observed['export']['file_ref'])
        observed.update(toc_count=len(toc_fields(doc)), docx_paragraphs=[p.text for p in doc.paragraphs],
                        snapshot_nodes_unchanged=before == {key: cs.read(ref) for key, ref in refs.items()})
    save_evidence(request, ws, observed, driver)
    assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
    assert_one_directory(observed, int(toc))
    assert observed['snapshot_nodes_unchanged']
    text = '\n'.join(observed['docx_paragraphs'])
    for body in contents.values():
        for line in body['text'].splitlines():
            assert line in text, line
            assert line in '\n'.join(observed['pdf_page_text']), ('PDF_BODY_MISSING', line)
    finalization = observed['export_record']['payload']['export_config']['finalization']
    assert (bool(finalization) == toc)
    if toc:
        assert len(finalization['toc']) == 1
    assert observed['render']['page_assets'] and observed['renderer_identity']['binary_digest']


async def test_a01_historical_insertion_fault_is_detected_by_same_oracle(ws, request, monkeypatch):
    """Restore only the documented old conditional, in test memory, never disk."""
    original = inspect.getsource(content_export.export_snapshot)
    old_condition = 'if kind == "report" and depth == 0:'
    assert original.count(old_condition) == 1, 'Historical mutation no longer matches implementation; review fixture.'
    # This fixture has no title pages; removing the root-only guard restores
    # repeated TOC insertion while preserving the actual four-versus-one oracle.
    mutated = original.replace(old_condition, 'if kind == "report":')
    namespace = dict(content_export.__dict__)
    exec(compile(mutated, '<A01-historical-toc-condition-test-only>', 'exec'), namespace)
    monkeypatch.setattr(content_export, 'export_snapshot', namespace['export_snapshot'])
    cs, refs, snapshot, before, _ = structural_snapshot(ws, 3)
    observed, driver = await native_export_and_render(ws, cs, snapshot,
        {'toc': True, 'refresh_toc': True, 'toc_depth': 3},
        'Test-only historical condition reproduction; preserve all content.')
    observed.update(case='A01-sensitivity', mutation='Remove only depth == 0 from TOC insertion conditional',
                    source_file_unchanged=True)
    if observed['runtime_result']['last_error'] is None:
        observed['toc_count'] = len(toc_fields(Document(ws.store.root / observed['export']['file_ref'])))
    save_evidence(request, ws, observed, driver)
    assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
    assert observed['toc_count'] == 4
    with pytest.raises(AssertionError, match='A01_LOGICAL_TOC_COUNT'):
        assert_one_directory(observed, 1)
    assert before == {key: cs.read(ref) for key, ref in refs.items()}


def standards_fixture():
    standard = json.loads(STANDARD.read_text(encoding='utf-8'))
    source = ROOT / standard['source_path']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == standard['source_sha256']
    return standard, source.read_text(encoding='utf-8')


def selected_layout(refs, local_table):
    """A scripted legal request, independent from the oracle JSON."""
    layout = {'toc': True, 'refresh_toc': True, 'toc_depth': 3,
        'top_margin_mm': 25, 'bottom_margin_mm': 25, 'left_margin_mm': 25, 'right_margin_mm': 15,
        'line_spacing': 1.5, 'table_line_spacing': 1.15 if local_table else 1.5,
        'styles': [
            {'name': 'Normal', 'font_family': 'Times New Roman', 'east_asia_font': '宋体', 'font_size': 12, 'line_spacing': 1.5},
            *[{'name': 'Heading ' + str(level), 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
                'font_size': size, 'bold': True, 'line_spacing': 1.5} for level, size in [(1, 18), (2, 15), (3, 14)]],
            {'name': 'TOC Heading', 'font_family': 'Times New Roman', 'east_asia_font': '宋体', 'font_size': 16, 'bold': True, 'line_spacing': 1.5},
            *[{'name': 'TOC ' + str(level), 'font_family': 'Times New Roman', 'east_asia_font': '宋体',
                'font_size': 12, 'bold': level == 1, 'line_spacing': 1.5} for level in (1, 2, 3)]],
        'nodes': [{'node_ref': refs['root'], 'paragraphs': [{'text': 'Synthetic cover project',
            'font_family': 'Times New Roman', 'east_asia_font': '宋体', 'font_size': 22,
            'bold': True, 'alignment': 'center', 'line_spacing': 1.0}]},
            {'node_ref': refs['table'], 'table_font_size': 10.5,
             **({'table_line_spacing': 1.5} if local_table else {})}]}
    return layout


def style_chain(style):
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        yield style._element
        style = style.base_style


def effective_properties(doc, paragraph, run):
    """Resolve direct/character/paragraph inheritance; don't trust style names."""
    defaults = doc.styles.element.find(qn('w:docDefaults'))
    char_styles = list(style_chain(run.style)) if run.style is not None else []
    para_styles = list(style_chain(paragraph.style))
    rp = [run._r.find(qn('w:rPr'))]
    rp += [s.find(qn('w:rPr')) for s in char_styles + para_styles]
    if defaults is not None:
        default_r = defaults.find(qn('w:rPrDefault'))
        rp.append(default_r.find(qn('w:rPr')) if default_r is not None else None)
    pp = [paragraph._p.find(qn('w:pPr'))] + [s.find(qn('w:pPr')) for s in para_styles]
    if defaults is not None:
        default_p = defaults.find(qn('w:pPrDefault'))
        pp.append(default_p.find(qn('w:pPr')) if default_p is not None else None)

    def attribute(chain, tag, attr, default=None):
        for parent in chain:
            node = parent.find(qn('w:' + tag)) if parent is not None else None
            if node is not None and node.get(qn('w:' + attr)) is not None:
                return node.get(qn('w:' + attr))
        return default

    result = {name: attribute(rp, 'rFonts', attr) for name, attr in [('east_asia', 'eastAsia'), ('ascii', 'ascii')]}
    size = attribute(rp, 'sz', 'val')
    result['size_pt'] = float(size) / 2 if size is not None else None
    result['bold'] = False
    for parent in rp:
        node = parent.find(qn('w:b')) if parent is not None else None
        if node is not None:
            result['bold'] = node.get(qn('w:val'), '1') not in ('0', 'false', 'off')
            break
    line = attribute(pp, 'spacing', 'line')
    rule = attribute(pp, 'spacing', 'lineRule', 'auto')
    result['line_multiple'] = float(line) / 240 if line is not None and rule == 'auto' else None
    result['line_rule'] = rule
    return result


def formatting_observations(doc, standard):
    """Checks effective runs in actual body, table and refreshed TOC paragraphs."""
    expected_text = {'Synthetic cover project': 'cover_project', '第一章 测试标题 H1': 'heading1',
        '1.1 测试标题 H2': 'heading2', '1.1.1 测试标题 H3': 'heading3',
        '合成正文 SAMPLE 2026，原文保持不变。': 'body', '目录': 'toc_heading'}
    observations, violations = [], []
    found = set()
    in_toc = False
    toc_level = {'第一章 测试标题 H1': 1, '1.1 测试标题 H2': 2, '1.1.1 测试标题 H3': 3}
    for node in doc.element.body.iter(qn('w:p')):
        paragraph = Paragraph(node, doc._body)
        # Field result runs may be nested inside hyperlinks, unlike p.runs.
        raw_text = ''.join(t.text or '' for t in node.iter(qn('w:t')))
        if any(re.match(r'\s*TOC\b', i.text or '') for i in node.iter(qn('w:instrText'))):
            in_toc = True
        key = None
        if in_toc:
            for heading, level in toc_level.items():
                if heading in raw_text:
                    key = f'toc{level}'
                    break
        if key is None:
            key = expected_text.get(raw_text)
        if key is None and node.getparent().tag == qn('w:tc'):
            key = 'table'
        if key:
            found.add(key)
            for run_node in node.iter(qn('w:r')):
                if not any(t.text for t in run_node.iter(qn('w:t'))):
                    continue
                props = effective_properties(doc, paragraph, Run(run_node, paragraph))
                observations.append({'kind': key, 'text': raw_text, 'effective': props})
                for name, expected in standard['rules'][key].items():
                    if props[name] != expected:
                        violations.append({'kind': key, 'text': raw_text, 'property': name,
                                           'expected': expected, 'actual': props[name]})
        if in_toc and any(f.get(qn('w:fldCharType')) == 'end' for f in node.iter(qn('w:fldChar'))):
            in_toc = False
    for section_index, section in enumerate(doc.sections):
        for side, expected in standard['margins_mm'].items():
            value = section.gutter if side == 'gutter' else getattr(section, side + '_margin')
            actual = value.mm if value is not None else 0.0
            if abs(actual - expected) >= .05:
                violations.append({'kind': 'page', 'section': section_index, 'property': side + '_mm',
                                   'expected': expected, 'actual': actual})
    missing = set(standard['rules']) - found
    violations.extend({'kind': key, 'property': 'actual_content', 'expected': 'present', 'actual': 'absent'} for key in sorted(missing))
    return observations, violations


async def format_case(ws, request, *, local_table, old_parameters=False):
    standard, original = standards_fixture()
    cs, refs, snapshot, before, _ = structural_snapshot(ws, with_format_content=True)
    layout = selected_layout(refs, local_table)
    if old_parameters:
        layout['right_margin_mm'] = 25
        layout['line_spacing'] = 1.3
        layout['table_line_spacing'] = 1.15
        next(s for s in layout['styles'] if s['name'] == 'Normal')['line_spacing'] = 1.3
        layout['nodes'][1].pop('table_line_spacing', None)
    observed, driver = await native_export_and_render(ws, cs, snapshot, layout,
        'Apply the selected customer formatting clauses, retaining legal cover exceptions. Exact standard follows:\n' + original)
    observed.update(case='A02', standard_fixture_sha256=hashlib.sha256(STANDARD.read_bytes()).hexdigest(),
                    format_source_sha256=standard['source_sha256'], old_parameters=old_parameters)
    if observed['runtime_result']['last_error'] is None:
        doc = Document(ws.store.root / observed['export']['file_ref'])
        props, violations = formatting_observations(doc, standard)
        observed.update(effective_properties=props, violations=violations,
                        snapshot_nodes_unchanged=before == {key: cs.read(ref) for key, ref in refs.items()},
                        actual_table_matrices=[[[cell.text for cell in row.cells] for row in table.rows]
                                               for table in doc.tables],
                        expected_table_matrix=standard['synthetic_content']['table_matrix'])
        fonts = subprocess.run(['fc-match', '宋体'], capture_output=True, text=True, check=False)
        observed['font_environment'] = {'query': '宋体', 'returncode': fonts.returncode,
                                      'actual_fontconfig_match': fonts.stdout.strip(),
                                      'not_visual_acceptance': True}
    save_evidence(request, ws, observed, driver)
    assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
    assert observed['snapshot_nodes_unchanged']
    assert observed['actual_table_matrices'] == [standard['synthetic_content']['table_matrix']], (
        'A02_EXPORTED_TABLE_CONTENT_CHANGED', observed['actual_table_matrices'])
    return observed


@pytest.mark.parametrize('local_table', [False, True])
async def test_a02_standard_effective_properties_after_native_refresh_and_render(ws, request, local_table):
    observed = await format_case(ws, request, local_table=local_table)
    assert not observed['violations'], json.dumps(observed['violations'], ensure_ascii=False)


async def test_a02_old_layout_is_rejected_by_independent_standard_not_old_equivalence(ws, request):
    observed = await format_case(ws, request, local_table=False, old_parameters=True)
    failures = {(v['kind'], v['property']) for v in observed['violations']}
    assert ('page', 'right_mm') in failures
    assert ('body', 'line_multiple') in failures
    assert ('table', 'line_multiple') in failures
    assert not any(v['kind'] == 'cover_project' for v in observed['violations']), 'Legal single-spaced cover must remain allowed.'


@pytest.mark.parametrize('body_multiple', [1.5, 1.0])
async def test_p11_exact_body_selector_cannot_borrow_single_spaced_cover_exception(ws, request, body_multiple):
    """Change only a body override; cover and all three TOC levels stay fixed."""
    standard, original = standards_fixture()
    cs, refs, snapshot, before, _ = structural_snapshot(ws, with_format_content=True)
    layout = selected_layout(refs, False)
    body_text = cs.read(refs['body'])['payload']['body']['text']
    layout['nodes'].append({'node_ref': refs['body'], 'paragraphs': [
        {'text': body_text, 'line_spacing': body_multiple}]})
    observed, driver = await native_export_and_render(ws, cs, snapshot, layout,
        'Use the original format standard; cover single spacing applies only to cover.\n' + original)
    observed.update(case='P11.C3', single_changed_condition={'body_line_spacing': body_multiple})
    if observed['runtime_result']['last_error'] is None:
        doc = Document(ws.store.root / observed['export']['file_ref'])
        props, violations = formatting_observations(doc, standard)
        observed.update(effective_properties=props, violations=violations,
            actual_table_matrices=[[[cell.text for cell in row.cells] for row in table.rows] for table in doc.tables],
            toc_count=len(toc_fields(doc)))
    save_evidence(request, ws, observed, driver)
    assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
    assert observed['toc_count'] == 1
    assert before == {key: cs.read(ref) for key, ref in refs.items()}
    assert observed['actual_table_matrices'] == [standard['synthetic_content']['table_matrix']]
    if body_multiple == 1.5:
        assert observed['violations'] == []
    else:
        # Nonconforming requested body spacing must be visible; a legitimate
        # cover exception is not a blanket exemption for the document.
        assert observed['violations']
        assert {(v['kind'], v['property'], v['actual']) for v in observed['violations']} == {('body', 'line_multiple', 1.0)}
