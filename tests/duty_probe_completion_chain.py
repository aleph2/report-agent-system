"""P22: one native all-fake route with real first-draft Office artifacts.

The script is an I/O oracle, not a required system workflow or model decision test.
A conflict remains in both variants; 'complete' only means B material is present.
"""
import hashlib
import json
from copy import deepcopy

import pytest
from docx import Document
from docx.oxml.ns import qn
from langchain_core.messages import AIMessage
from openpyxl import load_workbook

from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.task_supervision import reconcile
from test_agent_duty_repro_artifacts import save_evidence, toc_fields
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


async def run_completion_chain(ws, request, b_available, *, delivery_selector=None):
    # Independently declared inputs/oracles precede every agent and checker call.
    standard = {'margins_mm': {'top': 25, 'bottom': 25, 'left': 25, 'right': 15},
                'font_pt': 12, 'line_multiple': 1.5, 'toc_count': 1,
                'columns': ['Object', 'Observed', 'Rule', 'Status']}
    original_sources = [
        {'id': 's', 'title': 'Synthetic comparison rule', 'content': 'For class B use 75. Do not infer class from score.', 'coverage': 'complete'},
        {'id': 'a', 'title': 'Object A', 'content': 'A is class B. The proposed score is 70; this is a known conflict.', 'coverage': 'complete'},
        {'id': 'b', 'title': 'Object B', 'content': 'B is class B. The proposed score is 75.' if b_available else 'B exists in the scope. Its classification evidence is not supplied.', 'coverage': 'complete'},
        {'id': 'format', 'title': 'Small independent format standard', 'content': json.dumps(standard), 'coverage': 'complete'}]
    goal = ('Prepare a synthetic report for BOTH A and B. Preserve source conflict and missing classification evidence. '
            'Use the four-column source comparison table, one logical TOC, 25/25/25/15 mm margins, 12 pt body, '
            '1.5 line spacing, and separate issues XLSX with notes. Already explicit at first draft. '
            'Scoped checks are not engineering or whole-report acceptance.')
    ws.store.set('manifest', {**ws.store.manifest, 'goal': goal, 'sources': deepcopy(original_sources)})
    activate(ws)
    cs = ContentStore(ws.store)
    a_text = 'Object A: class B calls for 75; proposed 70 conflicts with the supplied rule.'
    b_text = ('Object B: supplied class B and proposed 75 agree with the supplied rule.' if b_available else
              'Object B remains in scope. Its classification is unresolved because the supporting evidence is not supplied.')
    matrix = [standard['columns'], ['A', 'B / 70', 'B / 75', 'Conflict'],
              ['B', 'B / 75' if b_available else 'Evidence missing', 'B / 75', 'Agrees' if b_available else 'Unresolved']]
    issues = [['A', 'Proposed 70 conflicts with 75', 'a + s']]
    if not b_available:
        issues.append(['B', 'Classification evidence not supplied', 'b'])
    note = ('A conflict needs technical resolution; no engineering acceptance.' if b_available else
            'A conflict needs technical resolution; B classification evidence remains missing. No engineering acceptance.')
    def node(kind, body, claim='inference'):
        return {'kind': kind, 'body': body, 'qualifiers': {}, 'claim_kind': claim}
    candidates = [node('block', {'text': a_text}), node('block', {'text': b_text}),
        node('table', {'columns': matrix[0], 'rows': matrix[1:], 'title': 'Source comparison'}),
        node('table', {'columns': ['Object', 'Issue', 'Source'], 'rows': issues, 'title': 'Issues only'}),
        node('block', {'text': note}, 'recommendation')]
    observed = {'case': 'P22', 'b_available': b_available, 'standard': standard,
                'input_sources': deepcopy(original_sources), 'expected_report_matrix': matrix,
                'expected_issues': issues, 'assets': [], 'visual_acceptance': False}
    def value(messages, call_id):
        reply = result_value(tool_reply(messages, call_id))
        assert reply.get('ok', True), reply
        return reply

    def coordinator_write(messages):
        observed['inputs'] = value(messages, 'import')['result']
        return action('commit_objects', 'criterion', operation_id='p22-criterion', objects=[
            {'client_key': 'criterion', 'type': 'Criterion', 'payload': {'requirement_refs': [observed['inputs']['requirement_ref']],
                'purpose': 'Compare each scoped object against its supplied evidence', 'scope': 'A and B separately',
                'expected_outcome': 'Preserve A conflict and B evidence limitations, never omit B.',
                'evidence_expectation': 'Exact object text and supplied source versions.',
                'allowed_limits': 'Unresolved classification remains explicitly partial.'}}])

    def coordinator_writer_after_criterion(messages):
        observed['criterion'] = value(messages, 'criterion')['result']['refs']['criterion']
        return action('task', 'writer-task', subagent_type='writer', description=goal)

    def produce(messages):
        text = '\n'.join(str(m.content) for m in messages)
        assert 'BOTH A and B' in text and '1.5 line spacing' in text
        return action('process_report_content', 'produce', operation_id='p22-produce', objective=goal,
            object_type='ContentNode', source_selections=[{'source_id': s['id']} for s in original_sources], output_count=5)

    def text_model(messages):
        packet = json.loads(messages[-1].content)
        observed['writer_tool_input'] = packet
        text = json.dumps(packet, ensure_ascii=False)
        assert all(s['content'] in text or s['content'] in str(messages[-1].content) for s in original_sources[:3])
        return AIMessage(content=json.dumps(candidates))

    def commit(messages):
        work = value(messages, 'produce')
        observed['text_work'] = work
        objects = [
            {'client_key': 'root', 'type': 'ContentNode', 'payload': node('report', {'text': 'Synthetic A and B report'}, 'structure')},
            {'client_key': 'chapter', 'type': 'ContentNode', 'payload': node('chapter', {'text': 'Assessment of A and B'}, 'structure')},
            *[{'client_key': str(i), 'type': 'ContentNode', 'text_work_id': work['text_work_id'], 'text_work_index': i} for i in range(5)],
            {'client_key': 'chapter_edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
                'object_ref': {'client_key': 'chapter'}, 'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'}},
            *[{'client_key': 'edge' + str(i), 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'chapter'},
                'object_ref': {'client_key': str(i)}, 'predicate': 'contains', 'position': i, 'provenance_kind': 'adopted_during_generation'}} for i in range(3)]]
        return action('commit_objects', 'commit', operation_id='p22-commit', objects=objects)

    def freeze(messages):
        refs = value(messages, 'commit')['result']['refs']
        refs['criterion'] = observed['criterion']
        observed['refs'] = refs
        for i, payload in enumerate(candidates):
            assert cs.read(refs[str(i)])['payload'] == payload
        return AIMessage(content=json.dumps({'refs': refs, 'unresolved': note}))

    def coordinator_layout(messages):
        returned = value(messages, 'writer-task')
        assert observed['refs']['root']['id'] in json.dumps(returned) and note in json.dumps(returned)
        refs = observed['refs']
        return action('freeze_snapshot', 'freeze', operation_id='p22-freeze', root_ref=refs['root'],
            refs=[*refs.values(), observed['inputs']['requirement_ref'], *observed['inputs']['source_refs']],
            workbook_refs=[refs['3'], refs['4']])

    def coordinator_grant_layout(messages):
        observed['snapshot'] = value(messages, 'freeze')['result']['snapshot_ref']
        observed['content_before_layout'] = {k: cs.read(r) for k, r in observed['refs'].items()}
        return action('task', 'layout-task', subagent_type='layout', layout_snapshot_ref=observed['snapshot'],
                      description='Apply the original standard at first export: ' + json.dumps(standard))

    def layout_export(messages):
        text = '\n'.join(str(m.content) for m in messages)
        assert 'line_multiple' in text and 'margins_mm' in text
        layout = {'toc': True, 'top_margin_mm': 25, 'bottom_margin_mm': 25, 'left_margin_mm': 25,
            'right_margin_mm': 15, 'line_spacing': 1.5, 'table_line_spacing': 1.5,
            'styles': [{'name': 'Normal', 'font_size': 12, 'east_asia_font': '宋体', 'line_spacing': 1.5},
                       {'name': 'Heading 1', 'font_size': 18, 'line_spacing': 1.5},
                       {'name': 'TOC 1', 'font_size': 12, 'line_spacing': 1.5}]}
        return action('export_content_snapshot', 'word', operation_id='p22-word', snapshot_ref=observed['snapshot'], layout=layout)

    def render(messages):
        observed['word'] = value(messages, 'word')['result']
        return action('render_content_export', 'render', operation_id='p22-render', export_ref=observed['word']['export_ref'])

    def first_artifact_oracle(messages):
        rendered = value(messages, 'render')['result']
        assert rendered['execution_state'] == 'completed', rendered
        observed['render'] = rendered
        payload = cs.read(rendered['render_ref'])['payload']
        observed['assets'] += [{'file_ref': observed['word']['file_ref'], 'kind': 'docx'}, {'file_ref': payload['pdf_ref'], 'kind': 'pdf'}]
        observed['assets'] += [{'file_ref': p['asset_ref'], 'kind': 'png'} for p in payload['page_assets']]
        doc = Document(ws.store.root / observed['word']['file_ref'])
        assert len(toc_fields(doc)) == standard['toc_count']
        for section in doc.sections:
            for side, mm in standard['margins_mm'].items():
                assert abs(getattr(section, side + '_margin').mm - mm) < .05
        assert doc.styles['Normal'].font.size.pt == standard['font_pt']
        assert doc.styles['Normal'].paragraph_format.line_spacing == standard['line_multiple']
        for text in (a_text, b_text):
            paragraph = next(p for p in doc.paragraphs if p.text == text)
            actual = paragraph.paragraph_format.line_spacing
            assert (actual if actual is not None else paragraph.style.paragraph_format.line_spacing) == 1.5
        assert [[c.text for c in row.cells] for row in doc.tables[0].rows] == matrix
        for row in doc.tables[0].rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    assert paragraph.paragraph_format.line_spacing == 1.5
        assert note not in '\n'.join(p.text for p in doc.paragraphs)
        assert not cs.list_objects('ReviewRecord'), 'The first-draft oracle must execute before review.'
        observed['first_draft_oracle_before_review'] = {'passed': True, 'toc_count': len(toc_fields(doc)), 'matrix': matrix}
        return AIMessage(content=json.dumps({'export_ref': observed['word']['export_ref'], 'render_ref': rendered['render_ref']}))

    def coordinator_workbook(messages):
        value(messages, 'layout-task')
        return action('export_content_workbook', 'xlsx', operation_id='p22-xlsx', snapshot_ref=observed['snapshot'],
            sheets=[{'name': 'Issues', 'table_ref': observed['refs']['3'], 'note_refs': [observed['refs']['4']]}],
            report_export_ref=observed['word']['export_ref'])

    def coordinator_review(messages):
        observed['xlsx'] = value(messages, 'xlsx')['result']
        observed['assets'].append({'file_ref': observed['xlsx']['file_ref'], 'kind': 'xlsx'})
        book = load_workbook(ws.store.root / observed['xlsx']['file_ref'])
        actual = [list(row) for row in book['Issues'].values]
        assert actual[:1 + len(issues)] == [['Object', 'Issue', 'Source'], *issues]
        assert note in [v for row in actual for v in row]
        observed['actual_xlsx_matrix'] = actual
        sources = {cs.read(r)['payload']['source_id']: r for r in observed['inputs']['source_refs']}
        requirements = []
        for i, key in enumerate(('a', 'b')):
            materials = [observed['refs'][str(i)], sources['s'], sources[key]]
            requirements.append({'target_ref': observed['refs'][str(i)], 'criterion_ref': observed['refs']['criterion'],
                'scope_id': key, 'required_checks': ['Compare object ' + key.upper() + ' with its actual class and rule.'],
                'required_read_refs': materials[1:], 'required_materials': [{'requirement_index': 0,
                    'purpose': 'Read exact target and supplied original rule/classification evidence.', 'refs': materials}]})
        observed['review_requirements'] = requirements
        return action('task', 'review-task', subagent_type='reviewer', description='Independently assess A and B; preserve partial work and conflict.',
            review_snapshot_ref=observed['snapshot'], review_requirements=requirements)

    def review_model(messages):
        packet = json.loads(messages[-1].content)
        observed['checker_packet'] = packet
        items = []
        for i, key in enumerate(('a', 'b')):
            material = observed['review_requirements'][i]['required_materials'][0]['refs']
            indices = [j for j, entry in enumerate(packet['evidence']) if entry.get('object', {}).get('ref') in material]
            assert len(indices) == len(material), (indices, packet['evidence'])
            complete = key == 'a' or b_available
            items.append({'scope_id': key, 'checked_requirement_indexes': [0] if complete else [],
                'execution_state': 'completed' if complete else 'running',
                'verdict': ('not_satisfied' if key == 'a' else 'satisfied') if complete else None,
                'observations': [{'evidence_index': j, 'locator': key, 'observation': ('A conflict retained.' if key == 'a' else b_text)} for j in indices],
                'check_results': [{'requirement_index': 0, 'execution_state': 'completed' if complete else 'partial',
                    'result': 'A conflict retained.' if key == 'a' else b_text,
                    'observation_indexes': list(range(len(indices))), 'remaining': '' if complete else 'B classification evidence is required.'}],
                'coverage': {'checked': [key + ' supplied material'], 'unchecked': [] if complete else ['B classification'],
                    'blocked': [], 'basis': 'Exact source versions and report text.'},
                'reason': 'A conflict remains.' if key == 'a' else b_text, 'findings': []})
        observed['checker_output'] = {'items': items}
        return AIMessage(content=json.dumps({'items': items}))

    def reviewer_return(messages):
        result = value(messages, 'check')
        observed['review'] = result
        assert result['items'][0]['verdict'] == 'not_satisfied'
        assert result['items'][1]['verdict'] == ('satisfied' if b_available else None)
        review = cs.read(result['review_ref'])
        status = reconcile(cs, review['task_id'])
        observed['review_status'] = status
        assert status['execution_complete'] is b_available
        assert bool(status['remaining']) is (not b_available)
        return AIMessage(content=json.dumps(result))

    def coordinator_select(messages):
        result = value(messages, 'review-task')
        observed['parent_review'] = result
        text = json.dumps(result)
        assert 'A conflict' in text
        if not b_available:
            assert 'B classification evidence is required.' in text
        call = action('select_content_delivery', 'select', operation_id='p22-select', snapshot_ref=observed['snapshot'],
            export_ref=observed['word']['export_ref'], workbook_export_ref=observed['xlsx']['export_ref'], ending_reason='preserve_unresolved')
        if delivery_selector is not None:
            return delivery_selector(ws, cs, observed, call)
        return call

    def decision(messages):
        observed['selected'] = value(messages, 'select')
        return action('record_execution_decision', 'decision', operation_id='p22-decision', decision='handoff',
            reason='Synthetic draft available with genuine unresolved issues; no engineering acceptance.',
            evidence=['Exact first-draft standard and saved scoped review.'], unresolved=[note],
            claims_assigned_checks_complete=b_available)

    def finish(messages):
        observed['decision'] = value(messages, 'decision')
        return AIMessage(content='Scoped draft and issue workbook saved; ' + note)

    def independent_text_service(messages):
        packet = json.loads(messages[-1].content)
        return review_model(messages) if 'requested_scope_ids' in packet else text_model(messages)

    driver = Driver(coordinator=[action('import_source_versions', 'import', operation_id='p22-inputs', source_ids=[s['id'] for s in original_sources]),
            coordinator_write, coordinator_writer_after_criterion, coordinator_layout, coordinator_grant_layout, coordinator_workbook, coordinator_review, coordinator_select, decision, finish],
        writer=[produce, commit, freeze], layout=[layout_export, render, first_artifact_oracle],
        reviewer=[action('perform_assigned_review', 'check', operation_id='p22-review', scope_ids=['a', 'b'],
            source_selections=[], content_selections=[]), reviewer_return], text_tool=[independent_text_service])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    observed['final_selected_state'] = ws.store.get('content_delivery')
    observed['final_execution_decision'] = ws.store.get('content_execution_decision')
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    assert observed.get('first_draft_oracle_before_review', {}).get('passed') is True
    assert observed.get('review') and observed.get('decision')
    assert ws.store.manifest['sources'] == original_sources
    assert observed['content_before_layout'] == {k: cs.read(r) for k, r in observed['refs'].items()}
    selected = ws.store.get('content_delivery')
    assert selected['snapshot_ref'] == observed['snapshot'] and selected['export_ref'] == observed['word']['export_ref'], 'P22_SELECTED_CURRENT_REPORT_PAIR'
    assert selected['workbook_export_ref'] == observed['xlsx']['export_ref']
    assert cs.read(selected['workbook_export_ref'])['payload']['export_config']['report_export_ref'] == selected['export_ref']
    assert len([call for call in driver.calls if call[0] == 'text_tool']) == 2
    assert all(call[0] in {'coordinator', 'writer', 'layout', 'reviewer', 'text_tool'} for call in driver.calls)
    assert ws.store.get('content_final_review') is None
    return observed, driver
