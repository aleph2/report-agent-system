"""P22 current-vs-historical tuple choice through the retained complete fake chain.

Historical files are a legal, explicitly dated fixture, re-exported after the
current producer/reviewer chain. Only the final selection's three references
differ. The negative case calibrates the independent current-version oracle;
it is not a claim that the program should infer the desired draft from prose.
"""
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
import pytest

from duty_probe_completion_chain import run_completion_chain
from report_agent.content_export import export_snapshot
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.content_workbook import export_workbook
from report_agent.hierarchical_tools import actor_for
from test_agent_duty_repro_artifacts import save_evidence
from test_task_supervision import ws, offline


ORACLE = 'P22_SELECTED_CURRENT_REPORT_PAIR'
HISTORY_BODY = 'HISTORICAL FIXTURE: this old draft covered A only; it is not the current A and B draft.'
HISTORY_NOTE = 'Historical archive only. A issue remains unresolved; no B coverage or current acceptance.'


def prepare_history(ws):
    cs, owner = ContentStore(ws.store), actor_for('coordinator')
    def node(kind, body):
        return {'kind': kind, 'body': body, 'qualifiers': {}, 'claim_kind': 'structure'}
    call = {'id': 'p22-history-fixture-task', 'args': {'subagent_type': 'writer',
        'description': 'Prepare synthetic historical A-only fixture for archive comparison; not the current commission.'}}
    with delegated_task(ws, 'coordinator', call) as (_, writer):
        refs = cs.commit(writer, 'p22-history-fixture-content', [
            {'client_key': 'root', 'type': 'ContentNode', 'payload': node('report', {'text': 'Historical A-only report'})},
            {'client_key': 'body', 'type': 'ContentNode', 'payload': node('block', {'text': HISTORY_BODY})},
            {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
                'object_ref': {'client_key': 'body'}, 'predicate': 'contains', 'position': 0,
                'provenance_kind': 'adopted_during_generation'}},
            {'client_key': 'issues', 'type': 'ContentNode', 'payload': node('table',
                {'columns': ['Object', 'Issue', 'Source'], 'rows': [['A', 'Historical unresolved issue', 'Historical fixture']]})},
            {'client_key': 'note', 'type': 'ContentNode', 'payload': node('block', {'text': HISTORY_NOTE})},
        ])['result']['refs']
    snapshot = cs.freeze(owner, 'p22-history-fixture-snapshot', refs['root'], list(refs.values()),
                         [refs['issues'], refs['note']])['result']['snapshot_ref']
    history = {'label': 'host-built historical fixture, not current agent output', 'refs': refs,
               'snapshot_ref': snapshot, 'writer_actor': writer.__dict__,
               'protected_records': [deepcopy(cs.read(r)) for r in [snapshot, *refs.values()]]}
    history['first_pair'] = history_pair(ws, cs, history, 'first')
    return history


def history_pair(ws, cs, history, suffix):
    owner = actor_for('coordinator')
    snapshot, refs = history['snapshot_ref'], history['refs']
    # Keep layout identical to the existing current chain: this fixture varies
    # content/snapshot and export recency, not the project's layout allowance.
    layout = {'toc': True, 'top_margin_mm': 25, 'bottom_margin_mm': 25, 'left_margin_mm': 25,
        'right_margin_mm': 15, 'line_spacing': 1.5, 'table_line_spacing': 1.5,
        'styles': [{'name': 'Normal', 'font_size': 12, 'east_asia_font': '宋体', 'line_spacing': 1.5},
                   {'name': 'Heading 1', 'font_size': 18, 'line_spacing': 1.5},
                   {'name': 'TOC 1', 'font_size': 12, 'line_spacing': 1.5}]}
    word = export_snapshot(cs, owner, 'p22-history-' + suffix + '-word', snapshot, layout)['result']
    xlsx = export_workbook(cs, owner, 'p22-history-' + suffix + '-xlsx', snapshot,
        [{'name': 'Issues', 'table_ref': refs['issues'], 'note_refs': [refs['note']]}], word['export_ref'])['result']
    word_record, xlsx_record = cs.read(word['export_ref']), cs.read(xlsx['export_ref'])
    assert word_record['payload']['snapshot_ref'] == xlsx_record['payload']['snapshot_ref'] == snapshot
    assert xlsx_record['payload']['export_config']['report_export_ref'] == word['export_ref']
    assert HISTORY_BODY in [p.text for p in Document(ws.store.root / word['file_ref']).paragraphs]
    book = load_workbook(ws.store.root / xlsx['file_ref'])
    rows = [list(row) for row in book['Issues'].values]
    book.close()
    assert rows[:2] == [['Object', 'Issue', 'Source'], ['A', 'Historical unresolved issue', 'Historical fixture']]
    assert HISTORY_NOTE in [v for row in rows for v in row]
    for item in (word, xlsx):
        assert hashlib.sha256((ws.store.root / item['file_ref']).read_bytes()).hexdigest() == item['file_digest']
    return {'tuple': {'snapshot_ref': snapshot, 'export_ref': word['export_ref'], 'workbook_export_ref': xlsx['export_ref']},
            'word': word, 'xlsx': xlsx, 'word_record': word_record, 'xlsx_record': xlsx_record,
            'actual_issue_rows': rows}


@pytest.mark.parametrize('selection', ['current', 'historical'])
async def test_complete_chain_current_selection_oracle_detects_coherent_old_tuple(ws, request, selection):
    history = prepare_history(ws)
    held = {'selection': selection, 'historical': history, 'sensitivity_only': selection == 'historical'}

    def select_delivery(workspace, cs, observed, original_call):
        assert observed['first_draft_oracle_before_review']['passed'] is True
        assert observed['review_status']['execution_complete'] is False
        assert observed['review_status']['remaining']
        assert observed['review']['items'][0]['verdict'] == 'not_satisfied'
        assert observed['review']['items'][1]['verdict'] is None
        assert history['snapshot_ref'] != observed['snapshot']
        assert cs.read(history['snapshot_ref'])['created_at'] < cs.read(observed['snapshot'])['created_at']
        late = history_pair(workspace, cs, history, 'late-reexport')
        assert late['word_record']['payload']['export_config']['layout'] == cs.read(
            observed['word']['export_ref'])['payload']['export_config']['layout']
        assert late['word']['export_ref'] != history['first_pair']['word']['export_ref']
        assert late['xlsx']['export_ref'] != history['first_pair']['xlsx']['export_ref']
        assert late['word_record']['created_at'] > cs.read(observed['word']['export_ref'])['created_at']
        assert late['xlsx_record']['created_at'] > cs.read(observed['xlsx']['export_ref'])['created_at']
        history['late_pair'] = late
        held['observed'] = observed
        before = deepcopy(original_call.tool_calls[0])
        after = deepcopy(before)
        if selection == 'historical':
            after['args'].update(late['tuple'])
        assert before['name'] == after['name'] == 'select_content_delivery'
        assert {k: v for k, v in before['args'].items() if k not in late['tuple']} == {
            k: v for k, v in after['args'].items() if k not in late['tuple']}
        changed = sorted(k for k in before['args'] if before['args'][k] != after['args'][k])
        assert changed == ([] if selection == 'current' else ['export_ref', 'snapshot_ref', 'workbook_export_ref'])
        held['selection_call_before'], held['selection_call_after'] = before, after
        observed['selection_counterfactual'] = {'selection': selection, 'before': before, 'after': after,
                                               'historical': deepcopy(history), 'changed_argument_names': changed}
        for pair in (history['first_pair'], late):
            observed['assets'] += [{'file_ref': pair['word']['file_ref'], 'kind': 'historical-docx'},
                                   {'file_ref': pair['xlsx']['file_ref'], 'kind': 'historical-xlsx'}]
        return original_call.model_copy(update={'tool_calls': [after]})

    failure = None
    if selection == 'historical':
        with pytest.raises(AssertionError, match='^' + ORACLE + '$') as caught:
            await run_completion_chain(ws, request, False, delivery_selector=select_delivery)
        helper_path = Path(inspect.getsourcefile(run_completion_chain)).resolve()
        tree = ast.parse(helper_path.read_text(encoding='utf-8'))
        expected_line = next(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert)
                             and isinstance(n.msg, ast.Constant) and n.msg.value == ORACLE)
        frames = []
        tb = caught.value.__traceback__
        while tb is not None:
            frames.append({'file': str(Path(tb.tb_frame.f_code.co_filename).resolve()),
                           'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
            tb = tb.tb_next
        assert frames[-1] == {'file': str(helper_path), 'function': 'run_completion_chain', 'line': expected_line}
        failure = {'message': str(caught.value), 'exact_assertion_frames': frames,
                   'expression': ast.unparse(next(n.test for n in ast.walk(tree)
                        if isinstance(n, ast.Assert) and n.lineno == expected_line))}
    else:
        await run_completion_chain(ws, request, False, delivery_selector=select_delivery)

    observed = held['observed']
    cs = ContentStore(ws.store)
    selected = ws.store.get('content_delivery')
    expected = history['late_pair']['tuple'] if selection == 'historical' else {
        'snapshot_ref': observed['snapshot'], 'export_ref': observed['word']['export_ref'],
        'workbook_export_ref': observed['xlsx']['export_ref']}
    assert all(selected[k] == ref for k, ref in expected.items())
    # The mechanical pairing guards accepted a coherent tuple in both cases.
    assert observed['selected']['ok'] is True and observed['decision']['ok'] is True
    assert observed['runtime_result']['last_error'] is None
    assert observed['final_execution_decision']['delivery'] == selected
    assert observed['final_execution_decision']['task_supervision_remaining']
    assert any('B classification evidence remains missing' in text
               for text in observed['final_execution_decision']['unresolved'])
    assert all(cs.read(record['ref']) == record for record in history['protected_records'])
    # Also preserve the post-selection original oracles that the deliberate
    # snapshot/Word assertion stops before reaching in the negative case.
    if selection == 'historical':
        assert selected['workbook_export_ref'] != observed['xlsx']['export_ref']
    else:
        assert selected['workbook_export_ref'] == observed['xlsx']['export_ref']
    assert cs.read(selected['workbook_export_ref'])['payload']['export_config']['report_export_ref'] == selected['export_ref']
    assert len(observed['checker_output']['items']) == 2
    assert ws.store.get('content_final_review') is None
    observed['selection_sensitivity_result'] = {'selection': selection, 'failure': failure,
        'selected': selected, 'coherent_pair_accepted': True,
        'historical_originals_unchanged': True, 'program_semantic_selection_guaranteed': False}
    # Persist the precisely caught oracle failure without replacing the helper's
    # already archived native trace or any source/provider response.
    save_evidence(request, ws, observed)
    request.node.user_properties.append(('chain_selection_sensitivity', json.dumps(observed['selection_sensitivity_result'])))
