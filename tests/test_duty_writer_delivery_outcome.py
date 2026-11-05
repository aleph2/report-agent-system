"""Native Writer current/historical selection calibration; no provider calls."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import traceback

from docx import Document
from langchain_core.messages import AIMessage, messages_from_dict
from openpyxl import load_workbook
import pytest

from duty_probe_agent_decisions import dump, ref_key
from duty_probe_writer_delivery_outcome import (
    BODY_A, BODY_B, BOOK_NOTE, FOOTNOTE, GOAL, REPORT_TABLE, UNKNOWN, UNREVIEWED,
    capture_writer_delivery_outcome)
from report_agent.content_store import ContentStore
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def delivery_script(folder, variant, held):
    def choose(messages):
        turn = held.get('turn', 0)
        held['turn'] = turn + 1
        fixture = json.loads((Path(folder) / 'fixture.json').read_text())
        if turn == 0:
            held['first_writer_messages'] = [m.model_dump() for m in messages]
            selected = fixture['bundles']['historical' if variant == 'historical' else 'current']
            held['selected'] = deepcopy(selected)
            return action('freeze_snapshot', 'delivery-freeze', operation_id='delivery-freeze',
                root_ref=selected['root'], refs=[fixture['inputs']['requirement_ref'],
                    *fixture['inputs']['source_refs'], *selected.values()],
                workbook_refs=[selected['issues'], selected['note']])
        if turn == 1:
            held['freeze'] = result_value(tool_reply(messages, 'delivery-freeze'))
            assert held['freeze']['ok'] is True, held['freeze']
            return action('export_content_snapshot', 'delivery-word', operation_id='delivery-word',
                snapshot_ref=held['freeze']['result']['snapshot_ref'], layout={'toc': False})
        if turn == 2:
            held['word'] = result_value(tool_reply(messages, 'delivery-word'))
            assert held['word']['ok'] is True, held['word']
            return action('export_content_workbook', 'delivery-book', operation_id='delivery-book',
                snapshot_ref=held['freeze']['result']['snapshot_ref'],
                sheets=[{'name': 'Issues', 'table_ref': held['selected']['issues'],
                         'note_refs': [held['selected']['note']]}],
                report_export_ref=held['word']['result']['export_ref'])
        if turn == 3:
            held['book'] = result_value(tool_reply(messages, 'delivery-book'))
            assert held['book']['ok'] is True, held['book']
            return AIMessage(content='', tool_calls=[
                {'name': 'read_content_export', 'type': 'tool_call', 'id': 'delivery-read-' + name,
                 'args': {'export_ref': held[name]['result']['export_ref']}} for name in ['word', 'book']])
        assert turn == 4, 'Unexpected extra Writer choice must remain visible.'
        for name in ['word', 'book']:
            held[name + '_read'] = result_value(tool_reply(messages, 'delivery-read-' + name))
            assert held[name + '_read']['ok'] is True
        held['final_writer_messages'] = [m.model_dump() for m in messages]
        # The historical control keeps this same current-completion claim. It
        # must fail the independent current-version oracle despite a legal pair.
        held['final'] = {'requested_current_report_prepared': True, 'selected_revision': 'B',
            'snapshot_ref': held['freeze']['result']['snapshot_ref'],
            'export_ref': held['word']['result']['export_ref'],
            'workbook_export_ref': held['book']['result']['export_ref'],
            'independent_review_performed': False, 'engineering_accepted': False,
            'limits': [UNREVIEWED, UNKNOWN]}
        return AIMessage(content=json.dumps(held['final']))
    return [choose] * 10


def exact_final_inside(value, text):
    if isinstance(value, str):
        if value == text:
            return True
        try:
            return exact_final_inside(json.loads(value), text)
        except (ValueError, TypeError):
            return False
    if isinstance(value, dict):
        return any(exact_final_inside(v, text) for v in value.values())
    if isinstance(value, list):
        return any(exact_final_inside(v, text) for v in value)
    return False


def current_version_violations(snapshot, fixture, word_text, workbook_rows):
    """Independent current-goal expectations, not selected tool arguments."""
    expected = {ref_key(r) for r in [fixture['inputs']['requirement_ref'],
        *fixture['inputs']['source_refs'], *fixture['bundles']['current'].values()]}
    actual = {ref_key(r) for r in snapshot['payload']['refs']}
    violations = []
    if actual != expected:
        violations.append({'code': 'CURRENT_VERSION_MANIFEST_MISMATCH',
            'missing': sorted(expected - actual), 'unexpected': sorted(actual - expected)})
    if BODY_B not in word_text or BODY_A in word_text:
        violations.append({'code': 'CURRENT_WORD_REVISION_MISMATCH', 'expected': BODY_B, 'actual_text': word_text})
    if workbook_rows[1][0] != 'B':
        violations.append({'code': 'CURRENT_WORKBOOK_REVISION_MISMATCH',
            'expected': 'B', 'actual': workbook_rows[1][0]})
    return violations


@pytest.mark.parametrize('variant', ['current', 'historical'])
async def test_writer_owned_current_pair_and_historical_selection_sensitivity(ws, request, variant):
    held = {}
    base = Path(os.environ.get('REPORT_WRITER_DELIVERY_OUT', str(ws.store.root / 'captures')))
    folder = base / variant
    driver = Driver(writer=delivery_script(folder, variant, held))
    capture = await capture_writer_delivery_outcome(ws, folder, driver)
    request.node.user_properties.append(('writer_delivery_evidence', json.dumps({
        'folder': str(folder), 'variant': variant, 'paid_HTTP': 0,
        'semantic_or_engineering_acceptance': False})))
    assert capture['raised_error'] is None, capture
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['observer_errors'] == []
    assert capture['originals_unchanged'] is True
    assert capture['host_completion_actions'] is False
    assert capture['saved_reviews'] == [] and capture['saved_renders'] == []
    fixture, cs = capture['fixture'], ContentStore(ws.store)
    assert fixture['goal'] == GOAL
    assert not any(o['ref']['type'] in {'DocumentSnapshot', 'ExportArtifact'} for o in fixture['originals'])
    tasks = cs.list_objects('DelegatedTask')
    assert len(tasks) == 1
    task = tasks[0]
    actor = fixture['writer_actor']['id']
    assert fixture['writer_actor']['task_id'] == task['ref']['id']
    assert actor == 'content:writer:' + task['ref']['id']
    assert task['payload']['goal'] == fixture['task_call']['args']['description'] == GOAL
    assert task['payload']['role'] == 'writer'
    assert task['owner_id'] == 'content:coordinator'
    assert task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    for event in capture['phase_events']:
        assert event['server_context']['role'] == 'writer'
        assert event['server_context']['actor_id'] == actor
        assert event['server_context']['assignment'] == task['payload']
    assert len(capture['native_model_calls']) == 5
    assert {c['role'] for c in capture['native_model_calls']} == {'writer'}
    first = json.dumps(held['first_writer_messages'], ensure_ascii=False)
    prepared = next(e for e in capture['phase_events'] if e['phase'] == 'explicit_fake_original_reads')
    first_native = next(e for e in capture['phase_events'] if e['phase'] == 'unchanged_writer_handler')
    first_messages = messages_from_dict(first_native['messages'])
    originals_read = [o for o in fixture['originals'] if o['ref']['type'] != 'DelegatedTask']
    source_deliveries = []
    for index, original in enumerate(originals_read):
        call = prepared['response']['tool_calls'][index]
        assert call['name'] == 'read_context'
        assert call['id'] == 'delivery-original-' + str(index)
        assert call['args'] == {'target_ref': original['ref']}
        reply = tool_reply(first_messages, call['id'])
        delivered = result_value(reply)
        source_deliveries.append({'call': call, 'actual_reply': reply.model_dump(),
            'actual_value': delivered, 'expected_original': original})
    dump(folder / 'original-delivery-oracle.json', {'source_deliveries': source_deliveries,
        'host_recovers_or_backfills_model_input': False})
    assert len(prepared['response']['tool_calls']) == len(source_deliveries) == len(originals_read)
    for delivered in source_deliveries:
        original, value = delivered['expected_original'], delivered['actual_value']
        assert value['ok'] is True
        assert value['result']['target_ref'] == original['ref']
        assert value['result']['objects'] == [original]
        assert value['result']['loaded_refs'] == [original['ref']]
        assert value['result']['total'] == 1
        assert value['result']['next_offset'] is None and value['result']['unreturned_refs'] == []
        with ws.store.connect() as db:
            receipt = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                                 (value['receipt_id'],)).fetchone()
        assert receipt[0] == actor and json.loads(receipt[1]) == value['result']
    for original in fixture['originals']:
        if original['ref']['type'] == 'DelegatedTask':
            continue
        assert original['ref']['id'] in first
    assert BODY_A in first and BODY_B in first and UNKNOWN in first and BOOK_NOTE in first
    assert len(capture['saved_snapshots']) == 1 and len(capture['saved_exports']) == 3
    assert len(capture['saved_mappings']) == 3
    snapshot = capture['saved_snapshots'][0]
    assert snapshot['ref'] == held['freeze']['result']['snapshot_ref']
    assert snapshot['payload']['root_ref'] == held['selected']['root']
    assert {ref_key(r) for r in snapshot['payload']['workbook_refs']} == {
        ref_key(held['selected']['issues']), ref_key(held['selected']['note'])}
    assert len(snapshot['payload']['refs']) == len(set(ref_key(r) for r in snapshot['payload']['refs']))
    assert cs.read(held['selected']['body_edge'])['payload']['object_ref'] == held['selected']['body']
    old_keys = {ref_key(o['ref']) for o in fixture['originals']}
    added = [o for o in cs.list_objects() if ref_key(o['ref']) not in old_keys]
    assert {o['ref']['type'] for o in added} == {'DocumentSnapshot', 'ExportArtifact', 'MappingArtifact'}
    for original in fixture['originals']:
        assert cs.read(original['ref']) == original
    for obj in added:
        assert obj['owner_id'] == obj['created_by'] == actor
        assert obj['task_id'] == task['ref']['id']
    word, book = [cs.read(held[name]['result']['export_ref']) for name in ['word', 'book']]
    assert word['payload']['snapshot_ref'] == book['payload']['snapshot_ref'] == snapshot['ref']
    config = book['payload']['export_config']
    assert config['report_export_ref'] == word['ref']
    assert config['sheets'] == [{'name': 'Issues', 'table_ref': held['selected']['issues'],
                                'note_refs': [held['selected']['note']]}]
    automatic=cs.read(held['word']['result']['workbook']['export_ref'])
    assert automatic['payload']['snapshot_ref']==snapshot['ref']
    assert automatic['payload']['export_config']['report_export_ref']==word['ref']
    for mapping in capture['saved_mappings']:
        assert mapping['payload']['snapshot_ref'] == snapshot['ref']
        assert mapping['payload']['export_ref'] in [word['ref'], book['ref'], automatic['ref']]
    assert len(capture['assets']) == 3
    auto_asset=next(a for a in capture['assets'] if a['file_ref']==automatic['payload']['file_ref'])
    assert hashlib.sha256((folder/auto_asset['retained_path']).read_bytes()).hexdigest()==auto_asset['sha256']==automatic['payload']['file_digest']
    for name, obj in [('word', word), ('book', book)]:
        asset = next(a for a in capture['assets'] if a['file_ref'] == obj['payload']['file_ref'])
        data = (folder / asset['retained_path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == asset['sha256'] == obj['payload']['file_digest']
        actual_read = held[name + '_read']
        assert actual_read['result']['export_ref'] == obj['ref']
        assert actual_read['result']['file_digest'] == obj['payload']['file_digest']
        assert 'not visual observation' in actual_read['result']['limitation']
        with ws.store.connect() as db:
            receipt = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                                 (actual_read['receipt_id'],)).fetchone()
        assert receipt[0] == actor and json.loads(receipt[1]) == actual_read['result']
        final_input = json.dumps(held['final_writer_messages'], ensure_ascii=False)
        assert actual_read['receipt_id'] in final_input and obj['payload']['file_digest'] in final_input
    doc = Document(ws.store.root / word['payload']['file_ref'])
    word_text = '\n'.join(p.text for p in doc.paragraphs)
    assert (BODY_B if variant == 'current' else BODY_A) in word_text
    assert UNKNOWN in word_text and FOOTNOTE in word_text and UNREVIEWED in word_text
    assert BOOK_NOTE not in word_text and 'Issue: actual weathering class remains unresolved.' not in word_text
    assert len(doc.tables) == 1
    assert [[c.text for c in r.cells] for r in doc.tables[0].rows] == [REPORT_TABLE['columns'], *REPORT_TABLE['rows']]
    workbook = load_workbook(BytesIO((ws.store.root / book['payload']['file_ref']).read_bytes()), data_only=False)
    try:
        assert workbook.sheetnames == ['Issues']
        matrix = [list(row) for row in workbook.active.values]
        assert matrix == [['Revision', 'Object', 'Issue', 'Evidence status'],
            ['B' if variant == 'current' else 'A', 'Site S', 'Issue: actual weathering class remains unresolved.',
             'Original source requires verification'], ['Note', BOOK_NOTE, None, None],
            ['status', UNREVIEWED, None, None]]
        assert all(c.data_type == 's' for row in workbook.active for c in row if c.value is not None)
    finally:
        workbook.close()
    assert BODY_A not in held['book_read']['result']['text'] and BODY_B not in held['book_read']['result']['text']
    assert BOOK_NOTE in held['book_read']['result']['text'] and FOOTNOTE in held['word_read']['result']['text']
    assert capture['finals'] == [json.dumps(held['final'])]
    returned = [p['actual_child_return'] for p in capture['fake_parent_events'] if p.get('actual_child_return')]
    assert len(returned) == 1 and returned[0]['tool_call_id'] == fixture['task_call']['id']
    assert exact_final_inside(returned[0]['content'], capture['finals'][0])
    assert held['final']['selected_revision'] == 'B' and held['final']['requested_current_report_prepared'] is True
    assert held['final']['independent_review_performed'] is False and held['final']['engineering_accepted'] is False
    assert held['final']['limits'] == [UNREVIEWED, UNKNOWN]
    violations = current_version_violations(snapshot, fixture, word_text, matrix)
    failure, failure_frame = None, None
    try:
        assert violations == [], json.dumps(violations, ensure_ascii=False)
    except AssertionError as exc:
        failure = traceback.format_exc()
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        failure_frame = {'filename': frame.filename, 'lineno': frame.lineno,
                         'function': frame.name, 'expression': frame.line}
        assert Path(frame.filename).resolve() == Path(__file__).resolve()
        assert frame.name == 'test_writer_owned_current_pair_and_historical_selection_sensitivity'
        assert frame.line.strip() == 'assert violations == [], json.dumps(violations, ensure_ascii=False)'
        if variant == 'current':
            dump(folder / 'current-oracle-failure.json', {'violations': violations,
                'traceback': failure, 'failure_frame': failure_frame})
            raise
    expected_codes = [] if variant == 'current' else ['CURRENT_VERSION_MANIFEST_MISMATCH',
        'CURRENT_WORD_REVISION_MISMATCH', 'CURRENT_WORKBOOK_REVISION_MISMATCH']
    assert [v['code'] for v in violations] == expected_codes
    assert bool(failure) == (variant == 'historical')
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'current_goal_violations': violations,
        'fixed_current_oracle_failure_traceback': failure, 'failure_frame': failure_frame,
        'known_historical_selection_control': variant == 'historical',
        'actual_native_writer_responses': 5, 'paid_HTTP': 0, 'host_completion_actions': False,
        'semantic_or_engineering_acceptance': False})
