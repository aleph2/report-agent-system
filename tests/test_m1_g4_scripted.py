"""A complete deterministic current-tool report path; not model/engineering acceptance."""
from report_agent import report_state
from io import BytesIO
import json
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent import plan_authority
from report_agent.deep_runtime import build_agent
from report_agent.content_delivery import current_delivery
from test_deep_runtime import Driver, invoke as scripted_invoke, observation
from test_m1_commission_plan import api
from test_m1_g3_integration import method_commission, persistence_input, section_plan
from test_m1_g3_followup import synthetic_pilot_plan
from support.flat_task_fixture import task_arguments


async def test_complete_current_scripted_report_checkpoint_calculation_exports_review_delivery(method_commission):
    fixture = method_commission
    ws, cs, co = fixture.ws, fixture.cs, fixture.co
    profiles = json.loads((Path(__file__).resolve().parents[1] / 'config/current.json').read_text())['manifest_profiles']
    ws.store.set('manifest', {**ws.store.manifest, **profiles,
        'assessment_presentation': 'table-spec-v1', 'synthetic': True})
    fixture.plan = synthetic_pilot_plan(fixture)
    plan = section_plan(fixture)
    plan['reconciliations'][0]['differences'] = ['Synthetic source naming disagreement requires confirmation.']
    fixture.plan = plan
    seen = {}
    call_sequence = 0

    def invoke(name, **arguments):
        nonlocal call_sequence
        call_sequence += 1
        action = scripted_invoke(name, **arguments)
        action.tool_calls[0]['id'] = f'g4-scripted-{call_sequence}-{name}'
        return action

    # A scripted coordinator proposes; only the separate operator entry confirms.
    proposal = Driver(coordinator=[invoke('save_commission_plan', plan=plan), AIMessage('Proposal ready for operator review.')])
    await build_agent(ws, proposal, None).ainvoke({'messages': [HumanMessage('Synthetic offline plan only.')]})
    saved = api().read_plan(ws.store)
    assert saved and plan_authority.decision_ref(ws.store) is None
    checkpoint = api().request_checkpoint(ws)
    brief = Path(checkpoint['brief_path'])
    if not brief.is_absolute():
        brief = ws.store.root / brief
    assert '基本分值（Rᵢⱼ）' in brief.read_text(encoding='utf-8')
    api().reply(ws, checkpoint['issue_id'], {'plan_ref': saved['ref'], 'approved': True,
        'corrections': '', 'reductions': []})
    confirmed = api().read_plan(ws.store)
    required, = confirmed['required_material_issues']
    assessment = persistence_input(fixture)
    assessment['method_version'] = 2

    def result(messages, tool):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == tool)
        assert message.status != 'error', message.content
        if tool == 'task':
            # Native subagent success returns the child's final text; refusals
            # are structured JSON and must still fail the usual ok assertion.
            try:
                value = json.loads(message.content)
            except json.JSONDecodeError:
                return message.content
            assert value.get('ok', True), value
            return value
        value = observation(messages, tool)
        assert value.get('ok', True), value
        return value.get('result', value)

    def calculated(messages):
        if 'assessment' not in seen:
            seen['assessment'] = result(messages, 'calculate_assessment')
        return seen['assessment']

    def fixed(messages):
        calculated(messages)
        return invoke('materialize_planned_section', operation_id='scripted-fixed', section_id='1.1', assessment_refs=[])

    def summary(messages):
        seen['fixed'] = result(messages, 'materialize_planned_section')['node_ref']
        return invoke('materialize_planned_section', operation_id='scripted-summary', section_id='5',
            assessment_refs=[seen['assessment']['assessment_ref']])

    def draft_section(messages):
        seen['summary'] = result(messages, 'materialize_planned_section')['node_ref']
        return invoke('process_report_content', object_type='ContentNode', output_count=2,
            objective='Draft the assigned section 4 heading and a short paragraph carrying the confirmed synthetic conflict: '
                + json.dumps(required),
            input_refs=[fixture.sources['design'], fixture.sources['scope']],
            source_selections=[{'source_id': 'design'}, {'source_id': 'scope'}])

    def bounded_text(messages):
        packet = json.loads(messages[-1].content)
        assert packet['actor']['role'] == 'writer'
        assert any(e.get('object', {}).get('ref') == fixture.sources['design'] for e in packet['evidence'])
        return AIMessage(json.dumps({'payloads': [
            {'kind': 'chapter', 'body': {'text': 'S1 synthetic assessment', 'section_id': '4'},
             'qualifiers': {}, 'claim_kind': 'structure', 'citations': [fixture.cite('design')]},
            {'kind': 'block', 'body': {'text': 'Synthetic conflict pending.', 'section_id': '4',
                'material_issues': [{**required, 'adopted_value': 'pending', 'anchor': {'text': 'pending'},
                                     'affects_level': False}]},
             'qualifiers': {}, 'claim_kind': 'structure', 'citations': [fixture.cite('design')]}
        ]}))

    def produce(messages):
        work = result(messages, 'process_report_content')
        objects = []
        def node(key, kind, body, citations=()):
            objects.append({'client_key': key, 'type': 'ContentNode', 'payload': {
                'kind': kind, 'body': body, 'qualifiers': {}, 'claim_kind': 'structure',
                'citations': list(citations)}})
        def edge(key, parent, child, position):
            objects.append({'client_key': key, 'type': 'Relation', 'payload': {
                'subject_ref': parent, 'object_ref': child, 'predicate': 'contains',
                'position': position, 'provenance_kind': 'adopted_during_generation'}})
        node('root', 'report', {'text': 'SYNTHETIC OFFLINE VALIDATION — NOT FOR ENGINEERING'})
        objects.extend({'client_key': key, 'type': 'ContentNode', 'text_work_id': work['text_work_id'],
                        'text_work_index': index} for index, key in enumerate(('section4', 'conflict')))
        edge('fixed-edge', {'client_key': 'root'}, seen['fixed'], 0)
        edge('section-edge', {'client_key': 'root'}, {'client_key': 'section4'}, 1)
        for index, key in enumerate(('ranking_ref', 'evaluation_ref', 'level_ref')):
            edge(key + '-edge', {'client_key': 'section4'}, seen['assessment'][key], index)
        edge('conflict-edge', {'client_key': 'section4'}, {'client_key': 'conflict'}, 3)
        edge('summary-edge', {'client_key': 'root'}, seen['summary'], 2)
        return invoke('commit_objects', objects=objects)

    def outcome(messages):
        seen['written'] = result(messages, 'commit_objects')['refs']
        a = seen['assessment']
        return invoke('record_assessment_outcome', object_id='S1', section_ref=seen['written']['section4'],
            score_ref=a['evaluation_ref'], level_ref=a['level_ref'], basis_refs=[a['evidence_ref']], unresolved=[])

    def declare(messages):
        result(messages, 'record_assessment_outcome')
        # Exact saved selections include every source/assessment dependency through closure.
        return invoke('commit_objects', objects=[],
            deliverable_selection={'kind': 'saved_work', 'root_ref': seen['written']['root'],
                'members_from': [{'kind': 'saved_result', 'operation_id': row['receipt_id']}
                    for row in cs.saved_reference_summary(co, seen['writer_task'])['receipts']]})

    def writer_finished(messages):
        seen['published'] = result(messages, 'commit_objects')['deliverable']['operation_id']
        return AIMessage('Synthetic report published.')

    def writer_start(messages):
        tasks = [r for r in cs.list_objects('DelegatedTask') if r['payload']['role'] == 'writer']
        assert len(tasks) == 1
        seen['writer_task'] = tasks[0]['ref']
        return invoke('calculate_assessment', operation_id='scripted-assessment', assessment=assessment)

    def word(messages):
        return invoke('export_content_snapshot', deliverable={'kind': 'deliverable', 'operation_id': seen['published']})

    def workbook(messages):
        seen['word'] = result(messages, 'export_content_snapshot')
        word_record = cs.read(seen['word']['export_ref'])
        seen['snapshot'] = word_record['payload']['snapshot_ref']
        return invoke('export_content_workbook', snapshot_ref=seen['snapshot'], report_export_ref=seen['word']['export_ref'],
            sheets=[{'name': '排序', 'table_ref': seen['assessment']['ranking_ref']},
                    {'name': '评估', 'table_ref': seen['assessment']['evaluation_ref']}])

    def criteria(messages):
        seen['excel'] = result(messages, 'export_content_workbook')
        return invoke('commit_objects', objects=[{'client_key': 'criterion', 'type': 'Criterion', 'payload': {
            'requirement_refs': [r['ref'] for r in cs.list_objects('Requirement')],
            'purpose': 'Check synthetic calculation and paired comments.', 'scope': 'Complete synthetic report',
            'expected_outcome': 'Saved calculation tables, material comments and paired Excel are present.',
            'evidence_expectation': 'Inspect the complete saved report and both actual artifacts.',
            'allowed_limits': 'Scripted protocol check only; not engineering or model judgment.'}}])

    def review(messages):
        criterion = result(messages, 'commit_objects')['refs']['criterion']
        seen['criterion'] = criterion
        seen['review_mode'] = 'content'
        args = {'subagent_type': 'reviewer', 'description': 'Inspect complete synthetic report content.',
            'review': {'deliverable': {'kind': 'snapshot', 'snapshot_ref': seen['snapshot']},
                'standards': {'kind': 'criteria', 'criterion_refs': [criterion]},
                'scope': {'kind': 'whole_content'}}}
        return invoke('task', **task_arguments(cs, co, args))

    def review_artifacts(messages):
        result(messages, 'task')
        assert len(cs.list_objects('ReviewRecord')) == 1
        criterion = seen['criterion']
        seen['review_mode'] = 'export'
        args = {'subagent_type': 'reviewer', 'description': 'Inspect the full synthetic report and paired artifacts.',
            'review': {'deliverable': {'kind': 'snapshot', 'snapshot_ref': seen['snapshot']},
                'standards': {'kind': 'criteria', 'criterion_refs': [criterion]},
                'scope': {'kind': 'mapped', 'items': [{'criterion_ref': criterion,
                    'target_ref': seen['snapshot'], 'assessment_kind': 'export',
                    'artifact_refs': [seen['word']['export_ref'], seen['excel']['export_ref']]}]}}}
        return invoke('task', **task_arguments(cs, co, args))

    def read_report(messages):
        return invoke('read_context', target_ref=seen['snapshot'], limit=100)

    def review_word(messages):
        packet = result(messages, 'read_context')
        assert packet['next_offset'] is None
        assert len(packet['objects']) == packet['total']
        if seen['review_mode'] == 'content':
            return invoke('submit_review', assigned_scope_index=0, execution_state='completed', verdict='satisfied',
                assessment='Complete synthetic snapshot read: fixed text, calculation records, assumptions and conclusion present. '
                    'Scripted mechanical check; not engineering or model acceptance.', evidence_indexes=[0])
        return invoke('read_content_export', export_ref=seen['word']['export_ref'])

    def review_excel(messages):
        if seen['review_mode'] == 'content':
            return review_finished(messages)
        result(messages, 'read_content_export')
        return invoke('read_content_export', export_ref=seen['excel']['export_ref'])

    def judged(messages):
        result(messages, 'read_content_export')
        return invoke('submit_review', assigned_scope_index=0, execution_state='completed', verdict='satisfied',
            assessment='Scripted inspection completed; synthetic mechanics only, not engineering acceptance.',
            evidence_indexes=[0, 1, 2])

    def review_finished(messages):
        result(messages, 'submit_review')
        return AIMessage('Synthetic review saved.')

    def selected(messages):
        result(messages, 'task')
        tasks = [r for r in cs.list_objects('DelegatedTask') if r['payload']['role'] == 'reviewer']
        assert len(tasks) == 2 and len(cs.list_objects('ReviewRecord')) == 2
        seen['review_tasks'] = [task['ref'] for task in tasks]
        return invoke('select_content_delivery', snapshot_ref=seen['snapshot'], export_ref=seen['word']['export_ref'],
            workbook_export_ref=seen['excel']['export_ref'], review_basis_assignment_ref=tasks[0]['ref'],
            review_assignment_refs=seen['review_tasks'])

    driver = Driver(coordinator=[invoke('task', subagent_type='writer', section_ids=['1.1', '4', '5'],
        description='Save complete synthetic report with calculation, comments and exact fixed text.'),
        word, workbook, criteria, review, review_artifacts, selected, AIMessage('Synthetic paired delivery saved.')],
        writer=[writer_start, fixed, summary, draft_section, produce, outcome, declare, writer_finished],
        reviewer=[read_report, review_word, review_excel, judged, review_finished],
        text_tool=[bounded_text])
    await build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage('Complete the synthetic offline tool scenario.')]})
    errors = [m.content for _, _, batch in driver.calls for m in batch if isinstance(m, ToolMessage) and m.status == 'error']
    assert not errors, errors
    delivery = current_delivery(ws.store)
    assert delivery['commission_coverage']['complete'] is True
    assert report_state.selected_delivery(ws.store)['workbook_export_ref'] == seen['excel']['export_ref']
    word_bytes = (ws.store.root / seen['word']['file_ref']).read_bytes()
    excel_bytes = (ws.store.root / seen['excel']['file_ref']).read_bytes()
    doc, book = Document(BytesIO(word_bytes)), load_workbook(BytesIO(excel_bytes))
    assert len([c for c in doc.comments if c.author == '待核']) == 3 and book['资料澄清清单'].max_row == 4
    texts = '\n'.join(p.text for p in doc.paragraphs)
    assert 'Project NEW.' in texts and 'Exact method sentence.' in texts
    assert cs.read(seen['assessment']['assessment_ref'])['payload']['table_records']
    evidence = {'mode': 'scripted_current_deepagents_tools', 'semantic_acceptance': False,
        'plan_ref': saved['ref'], 'snapshot_ref': seen['snapshot'], 'review_tasks': seen['review_tasks'],
        'word': seen['word'], 'excel': seen['excel'], 'comments': len([c for c in doc.comments if c.author == '待核']),
        'excel_clarification_rows': book['资料澄清清单'].max_row - 1,
        'delivery': delivery, 'tool_errors': errors,
        'tools_called': sorted({c['name'] for _, _, batch in driver.calls for m in batch
            if isinstance(m, AIMessage) for c in m.tool_calls}),
        'provider_calls': 0}
    (ws.store.root / 'g4-scripted-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
