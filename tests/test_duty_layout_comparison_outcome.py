"""Paired-page identity and legitimate wrong-old cache sensitivity, no provider."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import traceback

from docx import Document
from langchain_core.messages import AIMessage
import pytest
import pypdfium2 as pdfium

from duty_probe_agent_decisions import dump
from duty_probe_layout_comparison_outcome import (
    BODY, FOOTNOTE, GOAL, LIMIT, QUESTION, STANDARD, capture_layout_comparison)
from report_agent.content_store import ContentStore
from report_agent.layout_revision import status as revision_status
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline
from test_vision import VisionModel


VISION_TEXT = ('Synthetic observation of this supplied physical page only. '
               'It is not an exact point-size measurement, content review or engineering acceptance.')


def comparison_script(folder, wrong_current, held):
    def choose(messages):
        turn = held.get('turn', 0); held['turn'] = turn + 1
        fixture = json.loads((Path(folder) / 'fixture.json').read_text(encoding='utf-8'))
        pair = fixture['prepared_pair']
        if turn == 0:
            held['first_messages'] = [m.model_dump() for m in messages]
            return action('read_layout_capabilities', 'comparison-capabilities')
        if turn == 1:
            held['capabilities'] = result_value(tool_reply(messages, 'comparison-capabilities'))
            return action('inspect_rendered_page', 'comparison-before', render_ref=pair['before']['render_ref'],
                          page=1, question=QUESTION)
        if turn == 2:
            held['before'] = result_value(tool_reply(messages, 'comparison-before'))
            return action('inspect_rendered_page', 'comparison-after',
                          render_ref=pair['before' if wrong_current else 'after']['render_ref'],
                          page=1, question=QUESTION)
        assert turn == 3, 'Extra actual choices must remain visible, not silently skipped.'
        held['after'] = result_value(tool_reply(messages, 'comparison-after'))
        held['final_packet'] = {'before_export_ref': pair['before']['export_ref'],
            'current_export_ref': pair['after']['export_ref'], 'current_render_ref': pair['after']['render_ref'],
            'comparison_complete': True, 'observations': [held['before']['result'], held['after']['result']],
            'scope': LIMIT, 'all_report_accepted': False, 'engineering_accepted': False}
        return AIMessage(content=json.dumps(held['final_packet'], ensure_ascii=False))
    return choose


def current_page_identity_violations(pair, observations):
    """Fixed expected current artifact, independent of the model's selection/claim."""
    observed = observations[-1]
    issues = []
    if observed['source']['render_ref'] != pair['after']['render_ref']:
        issues.append('SECOND_OBSERVATION_IS_NOT_CURRENT_RENDER')
    if observed['image_sha256'] != pair['after']['image']['sha256']:
        issues.append('SECOND_OBSERVATION_IS_NOT_CURRENT_PNG')
    return issues


def assert_current_page_identity(pair, observations):
    violations = current_page_identity_violations(pair, observations)
    assert not violations, violations


@pytest.mark.parametrize('wrong_current', [False, True], ids=['current-pair', 'wrong-current-legal-old'])
async def test_layout_comparison_preserves_actual_page_identity_and_cache(ws, request, monkeypatch, wrong_current):
    label = 'wrong-current' if wrong_current else 'normal'
    folder = Path(os.environ.get('REPORT_LAYOUT_COMPARISON_OUT', str(ws.store.root / 'captures'))) / label
    held, clients = {}, []
    choose = comparison_script(folder, wrong_current, held)
    driver = Driver(layout=[choose] * 12)
    monkeypatch.setenv('REPORT_VISION_MODEL', 'deepseek-v4.1-flash')
    def fresh_vision():
        service = VisionModel(content=VISION_TEXT); clients.append(service); return service
    capture = await capture_layout_comparison(ws, folder, driver, vision_client_factory=fresh_vision)
    dump(folder / 'scripted-choices.json', held)
    dump(folder / 'vision-mock-calls.json', [s.calls for s in clients])
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['observer_errors'] == []
    assert capture['originals_unchanged'] and not capture['host_completion_actions']
    assert len(driver.calls) == len(capture['native_model_calls']) == held['turn'] == 4
    assert all(role == 'layout' for role, _, _ in driver.calls)
    fixture, cs = capture['fixture'], ContentStore(ws.store)
    pair = fixture['prepared_pair']
    task, = cs.list_objects('DelegatedTask')
    actor = 'content:layout:' + task['ref']['id']
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'layout' and task['payload']['goal'] == fixture['task_call']['args']['description']
    assert task['payload']['layout_snapshot_ref'] == fixture['snapshot_ref']
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    for phase in capture['phase_events']:
        assert phase['server_context']['role'] == 'layout' and phase['server_context']['actor_id'] == actor
        assert phase['server_context']['assignment'] == task['payload']
    prepared = [p for p in capture['phase_events'] if p['phase'] == 'explicit_fake_pair_preparation']
    actual = [p for p in capture['phase_events'] if p['phase'] == 'unchanged_layout_handler']
    assert len(prepared) == len(actual) == 4
    assert [p['response']['tool_calls'][0]['name'] for p in prepared] == [
        'export_content_snapshot', 'render_content_export', 'export_content_snapshot', 'render_content_export']
    assert held['capabilities']['ok'] is True
    assert held['capabilities']['result']['revision_budget']['revisions_used'] == 1
    with ws.store.connect() as db:
        budget = revision_status(db)
    assert budget['max_revisions'] == budget['revisions_used'] == 1
    assert cs.read(fixture['inputs']['source_refs'][1])['payload']['content'] == STANDARD
    assert cs.read(fixture['inputs']['source_refs'][0])['payload']['content'] == 'Class B permits 75 to 100.'
    assert cs.read(fixture['refs']['claim'])['payload'] == {
        'kind': 'claim', 'body': {'text': 'For adopted class B use 70.'},
        'qualifiers': {'condition': 'class B'}, 'claim_kind': 'inference'}
    assert len(cs.list_objects('DocumentSnapshot')) == 1
    assert len(cs.list_objects('ExportArtifact')) == len(cs.list_objects('RenderArtifact')) == 2
    assert len(cs.list_objects('MappingArtifact')) == 2 and cs.list_objects('ReviewRecord') == []
    layouts = []
    for label, expected_size, receipt_index in [('before', 11, 0), ('after', 12, 2)]:
        export, render = cs.read(pair[label]['export_ref']), cs.read(pair[label]['render_ref'])
        export_receipt = capture['preparation_receipts'][receipt_index]
        assert export_receipt['ok'] is True
        assert export_receipt['result']['export_ref'] == export['ref']
        mapping = cs.read(export_receipt['result']['mapping_ref'])
        assert mapping['ref']['type'] == 'MappingArtifact'
        assert mapping['owner_id'] == actor and mapping['task_id'] == task['ref']['id']
        assert mapping['payload']['snapshot_ref'] == fixture['snapshot_ref']
        assert mapping['payload']['export_ref'] == export['ref']
        assert export['owner_id'] == render['owner_id'] == actor
        assert export['task_id'] == render['task_id'] == task['ref']['id']
        assert export['payload']['snapshot_ref'] == render['payload']['snapshot_ref'] == fixture['snapshot_ref']
        assert render['payload']['export_ref'] == export['ref']
        layouts.append(deepcopy(export['payload']['export_config']['layout']))
        word = Document(ws.store.root / export['payload']['file_ref'])
        paragraph, = [p for p in word.paragraphs if p.text == BODY]
        assert paragraph.style.name == 'Normal' and word.styles['Normal'].font.size.pt == expected_size
        assert all(run.font.size is None or run.font.size.pt == expected_size for run in paragraph.runs if run.text)
        assert [[cell.text for cell in row.cells] for row in word.tables[0].rows] == [
            fixture['expected_table']['columns'], *fixture['expected_table']['rows']]
        fixed_texts = ['Synthetic local comparison', 'For adopted class B use 70.', BODY, FOOTNOTE]
        word_text = '\n'.join(p.text for p in word.paragraphs)
        for original_text in fixed_texts:
            assert original_text in word_text, ('WORD_FIXED_TEXT_MISSING', original_text)
        assert 'condition：class B' in '\n'.join(p.text for p in word.paragraphs)
        assert len(render['payload']['page_assets']) == 1
        with pdfium.PdfDocument(ws.store.root / render['payload']['pdf_ref']) as pdf:
            assert len(pdf) == 1
            page = pdf[0]; text_page = page.get_textpage(); text = text_page.get_text_range()
            text_page.close(); page.close()
        normalized = ' '.join(text.split())
        for original_text in [*fixed_texts, *fixture['expected_table']['columns'],
                              *(cell for row in fixture['expected_table']['rows'] for cell in row)]:
            assert ' '.join(original_text.split()) in normalized, ('PDF_FIXED_TEXT_MISSING', original_text)
        assert pair[label]['page'] == 1 and pair[label]['image'] == render['payload']['page_assets'][0]
    assert [layout.pop('font_size') for layout in layouts] == [11, 12]
    assert layouts[0] == layouts[1]
    assert pair['before']['image']['sha256'] != pair['after']['image']['sha256']
    for asset in capture['assets']:
        assert hashlib.sha256((folder / asset['retained_path']).read_bytes()).hexdigest() == asset['sha256']
    assert len(clients) == 2 and all(service.closed for service in clients)
    provider_calls = [call for service in clients for call in service.calls]
    assert len(provider_calls) == (1 if wrong_current else 2)
    expected = [pair['before']['image']['sha256']] + ([] if wrong_current else [pair['after']['image']['sha256']])
    dispatched_images = []
    for call in provider_calls:
        content = call['messages'][1]['content']
        assert content[0] == {'type': 'text', 'text': QUESTION}
        image = base64.b64decode(content[1]['image_url']['url'].split(',', 1)[1])
        dispatched_images.append(hashlib.sha256(image).hexdigest())
    assert dispatched_images == expected
    first, second = held['before']['result'], held['after']['result']
    assert first['source']['render_ref'] == pair['before']['render_ref']
    assert first['image_sha256'] == pair['before']['image']['sha256'] and not first['reused']
    assert second['reused'] is wrong_current
    if wrong_current:
        for key in ['operation', 'response_id', 'source', 'image_sha256']:
            assert second[key] == first[key]
    else:
        assert second['operation'] != first['operation']
        assert second['source']['render_ref'] == pair['after']['render_ref']
    observation_rows = []
    for label, call_id, next_turn in [('before', 'comparison-before', 2), ('after', 'comparison-after', 3)]:
        actual_reply = tool_reply(driver.calls[next_turn][2], call_id)
        returned = result_value(actual_reply)
        assert returned == held[label]
        row, = [row for row in capture['native_observation_rows'] if row['id'] == returned['receipt_id']]
        with ws.store.connect() as db:
            saved_values = db.execute('SELECT id,actor_id,data FROM content_observations WHERE id=?',
                                      (returned['receipt_id'],)).fetchone()
            saved_row = {'id': saved_values[0], 'actor_id': saved_values[1], 'data': saved_values[2]}
        assert saved_row == row and row['actor_id'] == actor
        assert json.loads(row['data']) == returned['result']
        assert returned['result']['observation'] == VISION_TEXT
        assert returned['result']['limitations'] == [
            'Model observation is not a confirmed fact or engineering approval.',
            'Coverage is only the supplied page/region; no whole-document OCR claim.',
            'Original sources and existing OCR are unchanged.']
        observation_rows.append({'row': row, 'next_layout_tool_message': actual_reply.model_dump()})
    dump(folder / 'full-native-vision-handoffs.json', observation_rows)
    violations = current_page_identity_violations(pair, [first, second])
    assert violations == (['SECOND_OBSERVATION_IS_NOT_CURRENT_RENDER', 'SECOND_OBSERVATION_IS_NOT_CURRENT_PNG']
                           if wrong_current else [])
    fixed_assertion_failure = None
    try:
        assert_current_page_identity(pair, [first, second])
    except AssertionError as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        origin = frames[-1]
        assert wrong_current
        assert Path(origin.filename).resolve() == Path(__file__).resolve()
        assert origin.name == 'assert_current_page_identity'
        assert origin.line == 'assert not violations, violations'
        assert len(exc.args) == 1 and isinstance(exc.args[0], str)
        assert all(code in exc.args[0] for code in violations)
        fixed_assertion_failure = {'type': type(exc).__name__, 'message': str(exc), 'actual_args': list(exc.args),
            'frame': {'filename': origin.filename, 'lineno': origin.lineno,
                      'name': origin.name, 'expression': origin.line},
            'traceback': ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}
    else:
        assert not wrong_current
    dump(folder / 'independent-current-page-oracle.json', {'violations': violations,
        'expected_current_render': pair['after']['render_ref'], 'expected_current_png': pair['after']['image']['sha256'],
        'fixed_assertion_failure': fixed_assertion_failure,
        'deliberate_wrong_choice_control': wrong_current, 'application_bug_established': False})
    assert json.loads(capture['fake_parent_events'][-1]['actual_child_return']['content']) == held['final_packet']
    assert held['final_packet']['scope'] == LIMIT and not held['final_packet']['engineering_accepted']
    assert 'data:image/' not in json.dumps(capture['native_model_calls'])
