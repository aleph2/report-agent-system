"""Replay a received R2 model answer unchanged through adoption and Word export.

The visible-content oracle comes from the archived input, never from exporter
implementation or a repaired candidate. No provider, application fix, or review.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from langchain_core.messages import AIMessage

from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/historical-duty/artifacts/r2-footnote-fixture'
HASHES = {'independent-input.json': '638e90d621c760e801404ba842c4f5e071f98727155b10414d0cbbdbf2aded62',
          'model-output.json': 'a028d1cee54cf55c427ec53be04eaf05897e6f018999e8460e1149bbeacd5d9c'}
CONTENT_SHA256 = '39433887895fb8ca1e29c99b981ac28913f4469896febdfa6e75c93c4ea4f02e'


def historical_fixture():
    saved = {}
    for name, expected in HASHES.items():
        raw = (FIXTURE / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected, 'Historical fixture bytes changed.'
        saved[name] = json.loads(raw)
    original = json.loads(saved['independent-input.json'][-1][1])
    raw_content = saved['model-output.json']['content']
    assert hashlib.sha256(raw_content.encode()).hexdigest() == CONTENT_SHA256
    source = original['evidence'][0]['observation']['blocks'][0]['text']
    lines = source.splitlines()
    footnote, = [line for line in lines if line.startswith('Footnote:')]
    matrix = [[cell.strip() for cell in line.split('|')] for line in lines if '|' in line]
    return original, source, footnote, matrix, raw_content


@pytest.mark.parametrize('representation', ['unchanged_real_table', 'explicit_block_control'])
async def test_r2_received_table_footnote_survives_native_adoption_and_word(ws, request, representation):
    original, source, footnote, matrix, raw_content = historical_fixture()
    real_output = json.loads(raw_content)
    assert real_output['payloads'][0]['body']['footnote'] == footnote
    # This is a separate supported-format control, not a repair of the red case.
    if representation == 'explicit_block_control':
        control = deepcopy(real_output)
        control['payloads'][0]['kind'] = 'block'
        control['payloads'][0]['body'] = {'text': source}
        fake_output = json.dumps(control, ensure_ascii=False)
    else:
        fake_output = raw_content
    expected_payload = json.loads(fake_output)['payloads'][0]
    goal = original['commission']['goal']
    ws.store.set('manifest', {**ws.store.manifest, 'goal': goal,
        'sources': [{'id': 's', 'title': 'Synthetic rule', 'content': source, 'coverage': 'complete'}]})
    activate(ws)
    cs = ContentStore(ws.store)
    observed = {'case': 'R2-footnote', 'representation': representation,
        'raw_fixture': str(FIXTURE), 'raw_fixture_sha256': HASHES,
        'historical_content_sha256': CONTENT_SHA256, 'replayed_content_sha256': hashlib.sha256(fake_output.encode()).hexdigest(),
        'original_input': original, 'independent_footnote': footnote, 'independent_matrix': matrix,
        'candidate_payload': expected_payload, 'assets': [], 'rendered_page_visual_acceptance': False}

    def value(messages, call_id):
        response = result_value(tool_reply(messages, call_id))
        assert response.get('ok', True), response
        return response

    def delegate(messages):
        observed['inputs'] = value(messages, 'import')['result']
        return action('task', 'writer-task', subagent_type='writer', description=goal)

    def text_model(messages):
        packet = json.loads(messages[-1].content)
        observed['actual_text_input'] = packet
        assert packet['objective'] == original['objective']
        assert packet['evidence'][0]['observation']['blocks'][0]['text'] == source
        return AIMessage(content=fake_output)

    def adopt(messages):
        response = value(messages, 'produce')
        observed['text_work'] = response
        return action('commit_objects', 'adopt', operation_id='r2-exact-adoption', objects=[
            {'client_key': 'root', 'type': 'ContentNode', 'payload': {'kind': 'report',
                'body': {'text': 'Synthetic retained R2 response'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
            {'client_key': 'candidate', 'type': 'ContentNode', 'text_work_id': response['text_work_id'], 'text_work_index': 0},
            {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
                'object_ref': {'client_key': 'candidate'}, 'predicate': 'contains', 'position': 0,
                'provenance_kind': 'adopted_during_generation'}}])

    def writer_finish(messages):
        refs = value(messages, 'adopt')['result']['refs']
        observed['refs'] = refs
        observed['saved_candidate'] = cs.read(refs['candidate'])
        assert observed['saved_candidate']['payload'] == expected_payload
        return AIMessage(content=json.dumps({'refs': refs, 'reviewed': False}))

    def freeze(messages):
        value(messages, 'writer-task')
        refs = observed['refs']
        return action('freeze_snapshot', 'freeze', operation_id='r2-freeze', root_ref=refs['root'],
            refs=[*refs.values(), observed['inputs']['requirement_ref'], *observed['inputs']['source_refs']])

    def layout_task(messages):
        observed['snapshot'] = value(messages, 'freeze')['result']['snapshot_ref']
        return action('task', 'layout-task', subagent_type='layout', layout_snapshot_ref=observed['snapshot'],
            description='Export the saved synthetic content without rewriting it; preserve complete visible source text.')

    def export(messages):
        return action('export_content_snapshot', 'word', operation_id='r2-word', snapshot_ref=observed['snapshot'],
            layout={'toc': False, 'styles': [{'name': 'Normal', 'font_family': 'DejaVu Sans', 'font_size': 12}]})

    def layout_finish(messages):
        observed['word'] = value(messages, 'word')['result']
        observed['assets'].append({'file_ref': observed['word']['file_ref'], 'kind': 'docx'})
        return AIMessage(content=json.dumps(observed['word']))

    driver = Driver(coordinator=[action('import_source_versions', 'import', operation_id='r2-inputs', source_ids=['s']),
            delegate, freeze, layout_task, AIMessage(content='Synthetic draft export available; no acceptance claim.')],
        writer=[action('process_report_content', 'produce', operation_id='r2-raw-response', objective=original['objective'],
            object_type='ContentNode', output_count=1, source_selections=[{'source_id': 's'}]), adopt, writer_finish],
        text_tool=[text_model], layout=[export, layout_finish])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    if observed.get('word'):
        doc = Document(ws.store.root / observed['word']['file_ref'])
        observed['visible_docx_text'] = '\n'.join(node.text or '' for node in doc.element.iter(qn('w:t')))
        observed['docx_tables'] = [[[cell.text for cell in row.cells] for row in table.rows] for table in doc.tables]
        observed['footnote_visible'] = footnote in observed['visible_docx_text']
        observed['payload_unchanged_after_export'] = cs.read(observed['refs']['candidate']) == observed['saved_candidate']
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    assert observed['payload_unchanged_after_export'] is True
    assert not cs.list_objects('ReviewRecord')
    assert len([entry for entry in driver.calls if entry[0] == 'text_tool']) == 1
    if representation == 'unchanged_real_table':
        assert observed['docx_tables'] == [matrix]
        assert observed['saved_candidate']['payload']['body']['footnote'] == footnote
    assert observed['footnote_visible'], ('Original input requires this complete visible footnote, '
        'but the exactly adopted and exported candidate loses it.', footnote, observed['visible_docx_text'])
