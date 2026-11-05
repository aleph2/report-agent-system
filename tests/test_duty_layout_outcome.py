"""Actual native Layout/files with fake decisions and one fake vision reply."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from langchain_core.messages import AIMessage
import pytest
import pypdfium2 as pdfium

from duty_probe_agent_decisions import dump
from duty_probe_layout_outcome import BODY, FOOTNOTE, FORMAT_STANDARD, capture_layout_outcome
from report_agent.content_store import ContentStore
from test_agent_duty_repro_artifacts import effective_properties, toc_fields
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline
from test_vision import VisionModel


VISION_TEXT = ('Synthetic observation for this one supplied physical page only. '
               'Other pages and engineering correctness are not assessed.')


def layout_outcome_script(folder, variant, held):
    """Only fake model choices; all business actions execute in native tools."""
    def choose(messages):
        turn = held.get('turn', 0)
        held['turn'] = turn + 1
        fixture = json.loads((Path(folder) / 'fixture.json').read_text())
        if turn == 0:
            held['first_layout_messages'] = [m.model_dump() for m in messages]
            return action('read_layout_capabilities', 'layout-capabilities')
        if turn == 1:
            held['capabilities'] = result_value(tool_reply(messages, 'layout-capabilities'))
            assert held['capabilities']['ok'] is True
            assert held['capabilities']['result']['directory_refresh']['available'] is True
            layout = {'toc': True, 'toc_depth': 3, 'refresh_toc': True,
                'top_margin_mm': 25, 'bottom_margin_mm': 25, 'left_margin_mm': 25, 'right_margin_mm': 15,
                'font_size': 12, 'line_spacing': 1.5, 'table_line_spacing': 1.5,
                'styles': [{'name': 'Normal', 'font_size': 12, 'line_spacing': 1.5},
                    *[{'name': 'Heading ' + str(level), 'font_size': size, 'line_spacing': 1.5}
                      for level, size in [(1, 18), (2, 15), (3, 14)]],
                    *[{'name': name, 'line_spacing': 1.5}
                      for name in ['Title', 'Caption', 'TOC Heading', 'TOC 1', 'TOC 2', 'TOC 3']]],
                'nodes': [{'node_ref': fixture['refs']['claim'], 'qualifier_font_size': 12}]}
            held['chosen_layout'] = deepcopy(layout)
            return action('export_content_snapshot', 'layout-export', operation_id='layout-outcome-export',
                          snapshot_ref=fixture['snapshot_ref'], layout=layout)
        if turn == 2:
            held['export'] = result_value(tool_reply(messages, 'layout-export'))
            assert held['export']['ok'] is True, held['export']
            return action('read_content_export', 'layout-read', export_ref=held['export']['result']['export_ref'])
        if turn == 3:
            held['actual_export_read'] = result_value(tool_reply(messages, 'layout-read'))
            assert held['actual_export_read']['ok'] is True
            return action('render_content_export', 'layout-render', operation_id='layout-outcome-render',
                          export_ref=held['export']['result']['export_ref'])
        if turn == 4:
            held['render'] = result_value(tool_reply(messages, 'layout-render'))
            assert held['render']['ok'] is True and held['render']['result']['execution_state'] == 'completed', held['render']
            return action('inspect_rendered_page', 'layout-observe',
                          render_ref=held['render']['result']['render_ref'], page=1,
                          question='Describe this physical page only. Preserve unseen-page and acceptance limits.')
        assert turn == 5, 'Unexpected extra model action; retain the actual trace rather than skip it.'
        held['actual_vision_return'] = result_value(tool_reply(messages, 'layout-observe'))
        assert held['actual_vision_return']['ok'] is True
        final = {'export_ref': held['export']['result']['export_ref'],
            'render_ref': held['render']['result']['render_ref'], 'observed_pages': [1],
            'unseen_pages': [p['page'] for p in held['render']['result']['pages'] if p['page'] != 1],
            'all_pages_visually_checked': False,
            'independent_content_review_performed': variant == 'false-final',
            'engineering_accepted': variant == 'false-final',
            'limits': ['Only physical page1 observed; no other page observation.',
                       'Formatting does not establish independent content review or engineering acceptance.']}
        held['final_packet'] = final
        return AIMessage(content=json.dumps(final))
    # Driver counts preparation AI messages too; each actual choice is indexed
    # by held.turn rather than silently skipping the first planned action.
    return [choose] * 12


def unsupported_layout_final_claims(final, saved_reviews):
    """Known semantic sensitivity control, not a production guard or reviewer."""
    return [key for key in ['independent_content_review_performed', 'engineering_accepted']
            if final[key] and not saved_reviews]


def contains_exact_final(value, text):
    """Native task returns may encode the exact child text inside an envelope."""
    if isinstance(value, str):
        if value == text:
            return True
        try:
            return contains_exact_final(json.loads(value), text)
        except (ValueError, TypeError):
            return False
    if isinstance(value, dict):
        return any(contains_exact_final(v, text) for v in value.values())
    if isinstance(value, list):
        return any(contains_exact_final(v, text) for v in value)
    return False


def inspect_layout_word(path, fixture):
    """Expectations come from saved originals/hierarchy, never chosen options."""
    doc = Document(path)
    observed, violations, headings_found, body_found = [], [], set(), set()
    expected_headings = fixture['expected_headings']
    expected_body = set(fixture['expected_body_lines'])
    for element in doc.element.body.iter(qn('w:p')):
        paragraph = Paragraph(element, doc._body)
        text = ''.join(t.text or '' for t in element.iter(qn('w:t')))
        if not text:
            continue
        style = paragraph.style.name
        is_table = any(a.tag == qn('w:tc') for a in element.iterancestors())
        is_toc = bool(re.match(r'^(TOC|Contents)( |[0-9])', style)) or text == '目录'
        expected_size = None
        if text in expected_headings and not is_toc and not is_table:
            level = expected_headings[text]
            expected_size = {1: 18, 2: 15, 3: 14}[level]
            headings_found.add(text)
            if paragraph.style.style_id.lower() != 'heading' + str(level):
                violations.append({'text': text, 'property': 'heading_level', 'actual': paragraph.style.style_id, 'expected': level})
        elif text in expected_body and not is_toc and not is_table:
            expected_size = 12
            body_found.add(text)
        for run_node in element.iter(qn('w:r')):
            if not any(t.text for t in run_node.iter(qn('w:t'))):
                continue
            props = effective_properties(doc, paragraph, Run(run_node, paragraph))
            observed.append({'text': text, 'style': style, 'effective': props})
            if props['line_multiple'] != 1.5:
                violations.append({'text': text, 'property': 'line_multiple', 'expected': 1.5, 'actual': props['line_multiple']})
            if expected_size is not None and props['size_pt'] != expected_size:
                violations.append({'text': text, 'property': 'size_pt', 'expected': expected_size, 'actual': props['size_pt']})
    for text in set(expected_headings) - headings_found:
        violations.append({'property': 'missing_heading', 'text': text})
    for text in expected_body - body_found:
        violations.append({'property': 'missing_body', 'text': text})
    for i, section in enumerate(doc.sections):
        for side, expected in [('top', 25), ('bottom', 25), ('left', 25), ('right', 15)]:
            actual = getattr(section, side + '_margin').mm
            if abs(actual - expected) >= .05:
                violations.append({'section': i, 'property': side + '_margin_mm', 'actual': actual, 'expected': expected})
    matrix = [[[cell.text for cell in row.cells] for row in t.rows] for t in doc.tables]
    expected_matrix = [fixture['expected_table']['columns'], *fixture['expected_table']['rows']]
    if expected_matrix not in matrix:
        violations.append({'property': 'missing_exact_four_column_table', 'actual': matrix, 'expected': expected_matrix})
    if len(toc_fields(doc)) != 1:
        violations.append({'property': 'logical_TOC_count', 'actual': len(toc_fields(doc)), 'expected': 1})
    all_text = '\n'.join(''.join(t.text or '' for t in p.iter(qn('w:t'))) for p in doc.element.body.iter(qn('w:p')))
    if 'condition：class B' not in all_text:
        violations.append({'property': 'original_technical_qualifier_missing'})
    return {'paragraph_observations': observed, 'violations': violations,
            'logical_TOC_count': len(toc_fields(doc)), 'table_matrices': matrix,
            'body_text': all_text, 'font_family_acceptance': False}


@pytest.mark.parametrize('variant', ['normal', 'false-final'])
async def test_native_layout_preserves_content_files_observations_and_final_limits(ws, tmp_path, monkeypatch, variant):
    folder = Path(os.environ.get('REPORT_LAYOUT_OUTCOME_OUT', tmp_path / 'evidence')) / variant
    held = {}
    driver = Driver(layout=layout_outcome_script(folder, variant, held))
    service = VisionModel(content=VISION_TEXT)
    monkeypatch.setenv('REPORT_VISION_MODEL', service.returned_model)
    capture = await capture_layout_outcome(ws, folder, driver, vision_client_factory=lambda: service)
    dump(folder / 'independent-observations.json', held)
    dump(folder / 'vision-mock-calls.json', service.calls)
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['observer_errors'] == []
    assert capture['originals_unchanged'] is True
    assert len(driver.calls) == len(capture['native_model_calls']) == 6
    assert all(role == 'layout' for role, _, _ in driver.calls)
    bound_names = {s['name'] for s in driver.bindings['layout'][-1]}
    assert {'read_context', 'read_layout_capabilities', 'export_content_snapshot',
            'read_content_export', 'render_content_export', 'inspect_rendered_page'} <= bound_names
    assert not bound_names & {'commit_objects', 'freeze_snapshot', 'select_content_delivery',
                              'export_content_workbook', 'submit_review', 'perform_assigned_review',
                              'perform_assigned_artifact_review', 'confirm_review_reuse'}
    assert capture['saved_reviews'] == []
    assert len(capture['saved_tasks']) == len(capture['saved_renders']) == 1
    assert len(capture['saved_exports']) == 2
    fixture, task = capture['fixture'], capture['saved_tasks'][0]
    prepared = capture['phase_events'][0]['response']['tool_calls']
    assert [c['name'] for c in prepared] == ['read_context', 'read_context']
    assert [c['args']['target_ref'] for c in prepared] == [fixture['format_ref'], fixture['snapshot_ref']]
    first_messages = held['first_layout_messages']
    actual_initial_returns = {m['tool_call_id']: m for m in first_messages if m['type'] == 'tool'}
    assert set(actual_initial_returns) == {c['id'] for c in prepared}
    first_serialized = json.dumps(first_messages, ensure_ascii=False)
    assert FORMAT_STANDARD in first_serialized and 'For adopted class B use 70.' in first_serialized
    actor_id = 'content:layout:' + task['ref']['id']
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'layout' and task['payload']['layout_snapshot_ref'] == fixture['snapshot_ref']
    assert task['payload']['goal'] == fixture['task_call']['args']['description']
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    for phase in capture['phase_events']:
        assert phase['server_context']['role'] == 'layout'
        assert phase['server_context']['actor_id'] == actor_id
        assert phase['server_context']['assignment'] == task['payload']
    cs = ContentStore(ws.store)
    original_keys = {(o['ref']['type'], o['ref']['id'], o['ref']['version']) for o in fixture['originals']}
    added_types = {o['ref']['type'] for o in cs.list_objects()
                   if (o['ref']['type'], o['ref']['id'], o['ref']['version']) not in original_keys}
    assert added_types <= {'DelegatedTask', 'ExportArtifact', 'RenderArtifact', 'MappingArtifact'}
    assert len(cs.list_objects('DocumentSnapshot')) == 1
    claim = cs.read(fixture['refs']['claim'])
    assert claim['owner_id'] == claim['created_by'] == 'content:coordinator'
    assert claim['payload'] == {'kind': 'claim', 'body': {'text': 'For adopted class B use 70.'},
                               'qualifiers': {'condition': 'class B'}, 'claim_kind': 'inference'}
    assert cs.read(fixture['inputs']['source_refs'][0])['payload']['content'] == 'Class B permits 75 to 100.'
    assert cs.read(fixture['format_ref'])['payload']['content'] == FORMAT_STANDARD
    exported,= [e for e in capture['saved_exports'] if e['payload']['file_ref'].endswith('.docx')]
    companion,= [e for e in capture['saved_exports'] if e['payload']['file_ref'].endswith('.xlsx')]
    assert companion['owner_id']==actor_id
    assert companion['payload']['snapshot_ref']==fixture['snapshot_ref']
    assert companion['payload']['export_config']['report_export_ref']==exported['ref']
    rendered = capture['saved_renders'][0]
    mappings = cs.list_objects('MappingArtifact')
    assert len(mappings) == 2
    mapping,= [m for m in mappings if m['ref']==held['export']['result']['mapping_ref']]
    assert mapping['ref'] == held['export']['result']['mapping_ref']
    assert mapping['owner_id'] == mapping['created_by'] == actor_id
    assert mapping['task_id'] == task['ref']['id']
    assert mapping['payload']['snapshot_ref'] == fixture['snapshot_ref']
    assert mapping['payload']['export_ref'] == exported['ref']
    assert exported['owner_id'] == rendered['owner_id'] == actor_id
    assert exported['payload']['snapshot_ref'] == rendered['payload']['snapshot_ref'] == fixture['snapshot_ref']
    assert rendered['payload']['export_ref'] == exported['ref'] == held['export']['result']['export_ref']
    assert rendered['payload']['export_digest'] == exported['payload']['file_digest']
    assert rendered['payload']['renderer_identity']['binary_digest']
    assert len(rendered['payload']['page_assets']) >= 1
    for asset in capture['assets']:
        assert hashlib.sha256((folder / asset['retained_path']).read_bytes()).hexdigest() == asset['sha256']
    word = next(a for a in capture['assets'] if a['file_ref'] == exported['payload']['file_ref'])
    assert word['sha256'] == exported['payload']['file_digest']
    actual_word = inspect_layout_word(folder / word['retained_path'], fixture)
    dump(folder / 'word-oracle.json', actual_word)
    assert actual_word['violations'] == [], actual_word['violations']
    assert BODY in actual_word['body_text'] and FOOTNOTE in actual_word['body_text']
    pdf_asset = next(a for a in capture['assets'] if a['file_ref'] == rendered['payload']['pdf_ref'])
    pdf_pages = []
    with pdfium.PdfDocument(folder / pdf_asset['retained_path']) as pdf:
        for i in range(len(pdf)):
            page = pdf[i]
            text_page = page.get_textpage()
            try:
                pdf_pages.append(text_page.get_text_range())
            finally:
                text_page.close()
                page.close()
    # Preserve raw extraction first. Only whitespace is normalized for matching;
    # no words, punctuation, units or numbers may be removed to obtain a pass.
    expected_pdf_texts = [*fixture['expected_headings'], *fixture['expected_body_lines'],
        'condition：class B', *fixture['expected_table']['columns'],
        *[cell for row in fixture['expected_table']['rows'] for cell in row]]
    normalized_pdf = ' '.join('\n'.join(pdf_pages).split())
    missing_pdf_texts = [s for s in expected_pdf_texts if ' '.join(s.split()) not in normalized_pdf]
    dump(folder / 'pdf-oracle.json', {'raw_page_texts': pdf_pages, 'page_count': len(pdf_pages),
        'render_page_count': len(rendered['payload']['page_assets']),
        'normalization': 'whitespace_only', 'expected_texts': expected_pdf_texts,
        'missing_texts': missing_pdf_texts, 'visual_or_engineering_acceptance': False})
    assert len(pdf_pages) == len(rendered['payload']['page_assets'])
    assert missing_pdf_texts == [], missing_pdf_texts
    read = held['actual_export_read']['result']
    assert read['export_ref'] == exported['ref'] and read['file_digest'] == exported['payload']['file_digest']
    assert BODY in read['text'] and FOOTNOTE in read['text'] and 'class B' in read['text']
    observation = held['actual_vision_return']['result']
    assert observation['status'] == 'observed' and observation['observation'] == VISION_TEXT
    assert observation['limitations']
    assert observation['source']['render_ref'] == rendered['ref']
    assert observation['source']['export_ref'] == exported['ref']
    assert observation['source']['page'] == 1 and observation['source']['coverage'] == 'full_page_image'
    assert observation['source']['crop'] is None
    assert len(service.calls) == 1 and service.closed is True
    url = next(b['image_url']['url'] for b in service.calls[0]['messages'][1]['content'] if b['type'] == 'image_url')
    image_sha = hashlib.sha256(base64.b64decode(url.split(',', 1)[1])).hexdigest()
    assert image_sha == observation['image_sha256'] == rendered['payload']['page_assets'][0]['sha256']
    with ws.store.connect() as db:
        for observed in [held['capabilities'], held['actual_export_read'], held['actual_vision_return']]:
            receipt = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                                 (observed['receipt_id'],)).fetchone()
            assert receipt and receipt[0] == actor_id and json.loads(receipt[1]) == observed['result']
    parent_returns = [e['actual_child_return'] for e in capture['fake_parent_events'] if e.get('actual_child_return')]
    assert len(parent_returns) == 1
    assert parent_returns[0]['tool_call_id'] == fixture['task_call']['id']
    assert capture['finals'] == [json.dumps(held['final_packet'])]
    assert contains_exact_final(parent_returns[0]['content'], capture['finals'][0])
    final = held['final_packet']
    assert final['export_ref'] == exported['ref'] and final['render_ref'] == rendered['ref']
    assert final['observed_pages'] == [1] and final['all_pages_visually_checked'] is False
    assert final['unseen_pages'] == list(range(2, len(rendered['payload']['page_assets']) + 1))
    unsupported = unsupported_layout_final_claims(final, capture['saved_reviews'])
    assert unsupported == ([] if variant == 'normal' else [
        'independent_content_review_performed', 'engineering_accepted'])
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'semantic_status':
        'known_false_final_needs_review' if unsupported else 'honest_finite_fake_control',
        'unsupported_claims': unsupported, 'paid_HTTP': 0, 'actual_native_layout_responses': 6,
        'fake_vision_responses': 1, 'independent_review_or_engineering_acceptance': False,
        'host_completes_work': False, 'font_family_acceptance': False})
