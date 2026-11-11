"""H3 synthetic access evidence and corrected planning mechanics; no paid models."""
from report_agent import issue_state
from copy import deepcopy
from importlib import import_module
import json

import pytest

from support.plan_fixture import enroll_planning_file

from report_agent import plan_authority
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.source_materials import issue, block_material
from report_agent.store import digest, encode
from test_ingestion import pdf_bytes
from test_m1_g3_integration import method_commission
from test_m1_g4_requirements import capture, anchored, required_case
from test_m1_g4_planning_steps import (
    entries, draft_case, planning, save_draft_parts, current_native_profiles,
)
from test_m1_commission_plan import api


def access():
    return import_module('report_agent.source_access')


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')

    def forbidden(*args, **kwargs):
        raise AssertionError('H3_OFFLINE_NETWORK_FORBIDDEN')

    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


@pytest.fixture
def access_case(method_commission):
    fixture = method_commission
    # Page 1 has two frozen blocks; trailing page 6 has no extracted text.
    data = pdf_bytes(('Alpha ' * 800, 'Page two candidate.', 'Page three drawing.',
        'Page four text.', 'Page five unused.', ''))
    fixture.access_ref = capture(fixture, 'access-evidence.pdf', data, 'h3-access-input')
    fixture.access_source = fixture.cs.read(fixture.access_ref)['payload']['source_id']
    enroll_planning_file(fixture, 'access-evidence.pdf', fixture.access_source, 'source_or_applicable_standard')
    fixture.access_plan = {'sections': [], 'objects': [], 'sources': [
        {'source_ref': fixture.access_ref, 'locator': 'page 2; chars 1-19', 'quote': 'Page two candidate.'}]}
    return fixture


def coverage_row(fixture, plan=None, source_id=None):
    report = access().coverage(fixture.cs, fixture.access_plan if plan is None else plan)
    row = next(r for r in report['sources'] if r['source_id'] == (source_id or fixture.access_source))
    return report, row


def returned_blocks(fixture, offset, limit):
    value = Catalog(fixture.ws.store).read(fixture.access_source, offset, limit)
    receipt = issue(fixture.ws, fixture.co, 'read_source_page', json.dumps(value, ensure_ascii=False), block_material(value))
    return receipt, value


def returned_snippet(fixture, page=2):
    value = Catalog(fixture.ws.store).search('Page two candidate.', source_id=fixture.access_source)
    match, = value['matches']
    materials = [{'source_id': fixture.access_source, 'kind': 'literal_source_search_match',
        'selection': {'units': 'zero-based text blocks', 'ordinals': match['ordinals'], 'locators': match['locators']},
        'selected_value_digest': digest(match), 'coverage': {'complete_source': False},
        'limitations': ['Literal search matches only.']}]
    return issue(fixture.ws, fixture.co, 'search_sources', json.dumps(value, ensure_ascii=False), materials)


def returned_image(fixture, page, crop=None, status='observed'):
    # A synthetic successful boundary receipt, not an actual vision invocation.
    value = {'status': status, 'observation': 'Synthetic visual response.',
        'source': {'source_id': fixture.access_source, 'page': page, 'crop': crop}}
    materials = [{'source_id': fixture.access_source, 'kind': 'model_image_interpretation',
        'selection': {'units': 'one-based physical page with normalized crop', 'page': page, 'crop': crop},
        'selected_value_digest': digest(value), 'coverage': {'complete_source': False, 'response_status': status},
        'limitations': ['Synthetic receipt; no semantic or whole-page claim.']}]
    return issue(fixture.ws, fixture.co, 'analyze_source_image', json.dumps(value), materials)


def test_captured_sources_citations_and_search_do_not_claim_opened_pages(access_case):
    fixture = access_case
    report, row = coverage_row(fixture)
    assert row['total_pages'] == 6 and row['current'] is True
    assert fixture.access_ref in row['source_version_refs']
    assert row['never_directly_returned_pages'] == [1, 2, 3, 4, 5, 6]
    assert row['text_returned_pages'] == row['snippet_pages'] == row['image_observations'] == []
    assert {s['id'] for s in Catalog(fixture.ws.store).sources() if s['current']} <= {r['source_id'] for r in report['sources']}
    returned_snippet(fixture)
    _, row = coverage_row(fixture)
    assert row['snippet_pages'] == [2]
    assert row['never_directly_returned_pages'] == [1, 2, 3, 4, 5, 6]
    note = report['note'].lower()
    assert 'defer' in note and ('comprehension' in note or 'read' in note)


def test_partial_and_union_of_returned_blocks_are_distinct_from_whole_page_reading(access_case):
    fixture = access_case
    first, _ = returned_blocks(fixture, 0, 1)
    _, row = coverage_row(fixture)
    assert row['text_returned_pages'] == row['partial_text_pages'] == [1]
    assert row['full_text_pages'] == []
    returned_blocks(fixture, 1, 1)
    _, row = coverage_row(fixture)
    assert row['full_text_pages'] == [1] and row['partial_text_pages'] == []
    assert row['never_directly_returned_pages'] == [2, 3, 4, 5, 6]
    # Reissued identical observations cannot inflate page coverage.
    repeated, _ = returned_blocks(fixture, 0, 1)
    assert repeated == first
    assert coverage_row(fixture)[1] == row


def test_text_helper_inputs_are_visible_without_direct_page_return_credit(access_case):
    from report_agent.source_materials import analysis_materials
    fixture = access_case
    # Source page 2 reaches the synthetic helper; its returned interpretation is not that page.
    value = Catalog(fixture.ws.store).read(fixture.access_source, 2, 1)
    assert value['blocks'][0]['locator'].startswith('page 2;')
    analysis = {'operation': 'synthetic-analysis', 'evidence': [
        {'kind': 'source_blocks', 'observation': value}]}
    issue(fixture.ws, fixture.co, 'analyze_text', json.dumps({'interpretation': 'Synthetic conclusion only.'}),
        analysis_materials(analysis))
    report, row = coverage_row(fixture)
    assert row['text_analysis_input_pages'] == [2]
    assert row['text_returned_pages'] == row['full_text_pages'] == row['partial_text_pages'] == []
    assert row['never_directly_returned_pages'] == [1, 2, 3, 4, 5, 6]
    assert any('2' in line and ('分析' in line or 'helper' in line.lower()) for line in access().lines(report))


def test_inspection_image_reference_is_text_only_and_crop_stays_partial(access_case):
    from report_agent.document_tools import source_page_info
    fixture = access_case
    value = source_page_info(fixture.ws, fixture.access_source, 4)
    material = {'source_id': fixture.access_source, 'kind': 'source_page_text_and_mechanical_tables',
        'selection': {'units': 'one-based physical PDF page', 'page': 4},
        'selected_value_digest': digest(value), 'coverage': {'complete_source': False}, 'limitations': value['limitations']}
    issue(fixture.ws, fixture.co, 'inspect_source_page', json.dumps(value, ensure_ascii=False), [material])
    _, row = coverage_row(fixture)
    assert row['inspected_text_pages'] == [4] and row['image_observations'] == []
    crop = [0.1, 0.2, 0.6, 0.8]
    returned_image(fixture, 3, crop, 'incomplete')
    _, row = coverage_row(fixture)
    assert row['image_observations'] == [{'page': 3, 'crop': crop, 'status': 'incomplete'}]
    assert row['never_directly_returned_pages'] == [1, 2, 5, 6]
    assert 3 not in row['full_text_pages']


def test_corrupt_receipt_and_changed_public_body_receive_no_access_credit(access_case):
    fixture = access_case
    first, _ = returned_blocks(fixture, 0, 1)
    record = fixture.ws.store.get('source_material:' + first['receipt'])
    record['public_sha256'] = '0' * 64
    fixture.ws.store.set('source_material:' + first['receipt'], record)
    second = returned_image(fixture, 3)
    body = fixture.ws.store.get('tool_observation:' + second['body_ref'])
    body['text'] = 'A replaced observation is not the original receipt.'
    fixture.ws.store.set('tool_observation:' + second['body_ref'], body)
    report, row = coverage_row(fixture)
    assert row['text_returned_pages'] == row['image_observations'] == []
    assert row['never_directly_returned_pages'] == list(range(1, 7))
    assert len(report['issues']) >= 2


def test_replacement_version_never_inherits_access_and_cited_history_remains_visible(access_case):
    fixture = access_case
    returned_blocks(fixture, 0, 2)
    new = Catalog(fixture.ws.store).import_file('access-revision.pdf', pdf_bytes(('New page one.', 'New page two.')),
        replaces_id=fixture.access_source)['source']['id']
    report, old = coverage_row(fixture)
    revised = next(r for r in report['sources'] if r['source_id'] == new)
    assert old['current'] is False and old['full_text_pages'] == [1]
    assert fixture.access_ref in old['source_version_refs']
    assert revised['current'] is True and revised['text_returned_pages'] == []
    assert revised['never_directly_returned_pages'] == [1, 2]
    assert old['file_digest'] != revised['file_digest']


def test_non_pdf_total_is_unknown_and_missing_original_is_visible_without_failing_brief(access_case):
    fixture = access_case
    manifest = deepcopy(fixture.ws.store.manifest)
    manifest['sources'].append({'id': 'missing-original', 'title': 'Missing original PDF',
        'filename': 'missing.pdf', 'sha256': 'a' * 64, 'copied_path': 'sources/missing.pdf',
        'content': 'Known extraction does not restore a missing original.', 'coverage': 'partial'})
    fixture.ws.store.set('manifest', manifest)
    report, _ = coverage_row(fixture)
    plain = next(r for r in report['sources'] if r['source_id'] == 'scope')
    missing = next(r for r in report['sources'] if r['source_id'] == 'missing-original')
    assert plain['total_pages'] is None and missing['total_pages'] is None
    assert report['issues']
    assert access().lines(report)


def test_access_summary_compacts_page_ranges_and_never_calls_them_comprehension(access_case):
    fixture = access_case
    report, _ = coverage_row(fixture)
    rendered = '\n'.join(access().lines(report))
    assert '1–6' in rendered or '1-6' in rendered
    assert 'access-evidence' in rendered
    assert '理解' in rendered or '阅读' in rendered or 'comprehension' in rendered.lower()


def test_checkpoint_lists_every_proposed_candidate_and_evidence_locations(draft_case):
    fixture = draft_case
    texts = ['Unrelated cover.', 'Disputed candidate evidence.', 'Height observation.',
        'Reconciliation design statement.', 'Reconciliation survey statement.']
    ref = capture(fixture, 'candidate-locations.pdf', pdf_bytes(texts), 'candidate-locations')
    enroll_planning_file(fixture, 'candidate-locations.pdf', fixture.cs.read(ref)['payload']['source_id'],
                         'source_or_applicable_standard')
    def cited(page):
        text = texts[page - 1]
        return {'source_ref': ref, 'locator': f'page {page}; chars 1-{len(text)}', 'quote': text}
    extra = deepcopy(fixture.plan['objects'][0])
    extra.update(object_id='DISPUTED-CANDIDATE', label='Unresolved boundary candidate', included=False,
        reason='Proposed exclusion; classification must remain visible for owner review.', origin='interpretation',
        sources=[cited(2)])
    extra['attributes'][0]['values'][0]['source'] = cited(3)
    extra['attributes'][0]['values'].append({'value': None, 'source': None,
        'reason': 'Synthetic missing measurement: source evidence is unavailable; ask the owner.'})
    fixture.plan['objects'].append(extra)
    fixture.plan['reconciliations'].append({'sources': [cited(4), cited(5)],
        'result': 'The two source accounts remain available for owner review.', 'differences': []})
    # H3.1 requires a verified direct return before an agent proposes this exclusion.
    source_id = fixture.cs.read(ref)['payload']['source_id']
    returned = Catalog(fixture.ws.store).read(source_id, 1, 1)
    assert returned['blocks'][0]['locator'] == cited(2)['locator']
    issue(fixture.ws, fixture.co, 'read_source_page', json.dumps(returned), block_material(returned))
    save_draft_parts(fixture)
    saved = planning().submit_plan(fixture.cs, fixture.co, 'h3-proposed-inventory')
    checkpoint = api().request_checkpoint(fixture.ws)
    brief = (fixture.ws.store.root / checkpoint['brief_path']).read_text(encoding='utf-8')
    assert 'DISPUTED-CANDIDATE' in brief and extra['reason'] in brief
    for citation in extra['sources']:
        assert citation['locator'] in brief
    assert cited(3)['locator'] in brief
    assert extra['attributes'][0]['values'][1]['reason'] in brief and '未知' in brief
    assert any(label in brief for label in ('无来源', '无依据', '未提供来源'))
    for item in fixture.plan['reconciliations']:
        for citation in item['sources']:
            assert citation['locator'] in brief
    assert plan_authority.decision_ref(fixture.ws.store) is None
    assert saved['result']['plan_ref']


async def test_incomplete_plan_is_corrected_through_native_steps_then_calculated_and_exported(entries):
    from io import BytesIO
    from docx import Document
    from openpyxl import load_workbook
    from langchain_core.messages import AIMessage, ToolMessage
    from test_deep_runtime import Driver, call, observation, run
    from test_m1_g3_integration import persistence_input
    from test_m1_g4_requirements import requirements
    from test_m1_g4_planning_steps import classifications, source_pins
    fixture = entries
    ws, cs, co = fixture.ws, fixture.cs, fixture.co
    fixture.entries[2]['table_specs'] = deepcopy(fixture.plan['table_specs'])
    fixture.entries[2]['source_pins'] = source_pins(fixture, fixture.entries[2]['table_specs'])
    initial = requirements().read_requirements(cs)
    unresolved = deepcopy(initial['payload']['items'])
    for item in unresolved:
        item['status'] = 'unresolved'
    requirements().propose_requirements(cs, co, 'h3-initial-unresolved', initial['ref'], unresolved)
    current_native_profiles(fixture)
    ws.store.set('manifest', {**ws.store.manifest, 'assessment_presentation': 'table-spec-v1'})
    planning().install_reviewed_entries(cs, fixture.entries)
    rows = classifications(fixture)
    planning().install_classifications(cs, rows, 'Synthetic reviewed classification preceding every planning choice.')
    plan = deepcopy(fixture.plan)
    summary = next(s for s in plan['sections'] if s['section_id'] == '5')
    summary['sources'] = [fixture.cite('template', 'Summary: {SUMMARY}')]
    summary['result_bindings'] = [{'old': '{SUMMARY}', 'object_id': 'S1', 'field': 'assessment_text'}]
    seen = {}
    sequence = 0

    def invoke(name, **arguments):
        nonlocal sequence
        sequence += 1
        return AIMessage(content='', tool_calls=[call(name, arguments, 'h3-native-' + str(sequence))])

    def result(messages, name):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == name)
        assert message.status != 'error', message.content
        value = observation(messages, name)
        assert value.get('ok', True), value
        return value.get('result', value)

    steps = [invoke('submit_plan')]
    first_anchor = fixture.anchors[0]

    def after_incomplete(messages):
        failed = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'submit_plan')
        assert failed.status == 'error'
        value = json.loads(failed.content)
        seen['initial_gap_list'] = value['diagnostic']['gaps']
        paths = ' '.join(g['path'] for g in seen['initial_gap_list'])
        assert all(key in paths for key in ('requirements.', 'sections', 'objects'))
        assert not cs.list_objects('CommissionPlan') and plan_authority.decision_ref(ws.store) is None
        return invoke('set_requirement_status', anchor_id=first_anchor['id'], status='required',
            interpretation='Resolve the exact source requirement without changing its classification.')

    steps.append(after_incomplete)
    for anchor in fixture.anchors[1:]:
        steps.append(invoke('set_requirement_status', anchor_id=anchor['id'], status='required',
            interpretation='Retain this independently extracted source requirement.'))
    for row in rows:
        if row['entry_ids']:
            steps.append(invoke('link_convention', anchor_id=row['anchor_id'], entry_id=row['entry_ids'][0],
                interpretation='Use the exact reviewed entry; attach its records server-side.'))
    linked_submit = invoke('submit_plan')
    linked_submit_id = linked_submit.tool_calls[0]['id']
    steps.append(linked_submit)

    def after_linked_incomplete(messages):
        failed = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'submit_plan')
        assert failed.status == 'error', failed.content
        value = json.loads(failed.content)
        seen['classified_gap_list'] = value['diagnostic']['gaps']
        paths = ' '.join(g['path'] for g in seen['classified_gap_list'])
        assert all(key in paths for key in ('sections', 'objects', 'scope_boundary')), seen['classified_gap_list']
        assert not cs.list_objects('CommissionPlan') and plan_authority.decision_ref(ws.store) is None
        return invoke('read_planning_draft')

    steps.append(after_linked_incomplete)
    # Free action ordering: section 5 and objects precede section 4 and details.
    for section in reversed(plan['sections']):
        values = {key: deepcopy(value) for key, value in section.items() if key in {
            'section_id', 'title', 'kind', 'sources', 'pending_sources', 'derived_from', 'rule',
            'result_bindings', 'replacements', 'source_views', 'examples'}}
        values['outline_anchor_id'] = next(a['id'] for a in fixture.anchors
            if a['kind'] == 'section' and a['section_id'] == section['section_id'])
        steps.append(invoke('add_section', **values))
    steps.extend(invoke('add_object', object=obj) for obj in plan['objects'])
    boundary = deepcopy(plan['scope_boundary'])
    basis = boundary.pop('customer_basis', boundary['source'])
    anchor = next(a for a in fixture.anchors if a['kind'] == 'scope' and a['source'] == basis)
    assert anchor['source'] == plan['scope_boundary'].get('customer_basis', plan['scope_boundary']['source'])
    boundary['customer_basis_anchor_id'] = anchor['id']
    steps.append(invoke('set_scope_boundary', boundary=boundary))
    steps.extend(invoke('add_reconciliation', reconciliation={'reconciliation_id': 'source-pair-' + str(i), **row})
        for i, row in enumerate(plan['reconciliations']))
    steps.append(invoke('set_planning_details', details={key: plan[key] for key in ('inventory_attributes', 'deliverables')}))
    steps.append(invoke('submit_plan'))
    proposal = Driver(coordinator=steps)
    paused = await run(ws, proposal)
    planning_errors = {m.tool_call_id: m.content for _, _, messages in proposal.calls for m in messages
        if isinstance(m, ToolMessage) and m.status == 'error'}
    assert paused['status'] == 'needs_human' and paused['last_error'] is None, json.dumps({
        'status': paused['status'], 'last_error': paused['last_error'],
        'planning_errors': planning_errors}, ensure_ascii=False)
    record = api().read_plan(ws.store)
    assert record and record['payload']['method_pack'] and set(record['payload']['table_specs']) == {'ranking', 'evaluation'}
    assert plan_authority.decision_ref(ws.store) is None and not cs.list_objects('Assessment')
    issue = next(i for i in issue_state.get_report_issues(ws.store) if not i['resolved'])
    api().reply(ws, issue['id'], {'plan_ref': record['ref'], 'requirements_ref': record['payload']['requirements_ref'],
        'approved': True, 'corrections': '', 'reductions': []})

    assessment = persistence_input(fixture)
    assessment['method_version'] = 2

    def writer_start(messages):
        tasks = [r for r in cs.list_objects('DelegatedTask') if r['payload']['role'] == 'writer']
        assert len(tasks) == 1
        seen['writer_task'] = tasks[0]['ref']
        return invoke('calculate_assessment', operation_id='h3-scripted-assessment', assessment=assessment)

    def create_summary(messages):
        seen['assessment'] = result(messages, 'calculate_assessment')
        return invoke('materialize_planned_section', operation_id='h3-scripted-summary', section_id='5',
            assessment_refs=[seen['assessment']['assessment_ref']])

    def chapter_text(messages):
        seen['summary'] = result(messages, 'materialize_planned_section')['node_ref']
        return invoke('process_report_content', object_type='ContentNode', output_count=1,
            objective='Write the synthetic assessment chapter heading for assigned section 4.',
            input_refs=[fixture.sources['design']], source_selections=[{'source_id': 'design'}])

    def text_payload(messages):
        packet = json.loads(messages[-1].content)
        assert packet['actor']['role'] == 'writer'
        return AIMessage(content=json.dumps({'payloads': [{'kind': 'chapter',
            'body': {'text': 'Synthetic assessment', 'section_id': '4'}, 'qualifiers': {},
            'claim_kind': 'structure', 'citations': [fixture.cite('design')]}]}))

    def assemble(messages):
        work = result(messages, 'process_report_content')
        objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': {'kind': 'report',
            'body': {'text': 'SYNTHETIC H3 — NOT ENGINEERING ACCEPTANCE'}, 'qualifiers': {},
            'claim_kind': 'structure', 'citations': []}},
            {'client_key': 'section4', 'type': 'ContentNode', 'text_work_id': work['text_work_id'], 'text_work_index': 0}]
        pairs = [({'client_key': 'root'}, {'client_key': 'section4'}, 0),
            ({'client_key': 'root'}, seen['summary'], 1)]
        pairs += [({'client_key': 'section4'}, seen['assessment'][key], index)
            for index, key in enumerate(('ranking_ref', 'evaluation_ref', 'level_ref'))]
        objects += [{'client_key': 'edge-' + str(index), 'type': 'Relation', 'payload': {
            'subject_ref': parent, 'object_ref': child, 'predicate': 'contains', 'position': position,
            'provenance_kind': 'adopted_during_generation'}} for index, (parent, child, position) in enumerate(pairs)]
        return invoke('commit_objects', objects=objects)

    def outcome(messages):
        seen['written'] = result(messages, 'commit_objects')['refs']
        assessed = seen['assessment']
        return invoke('record_assessment_outcome', object_id='S1', section_ref=seen['written']['section4'],
            score_ref=assessed['evaluation_ref'], level_ref=assessed['level_ref'], basis_refs=[assessed['evidence_ref']], unresolved=[])

    def publish_written(messages):
        result(messages, 'record_assessment_outcome')
        return invoke('commit_objects', objects=[], deliverable_selection={'kind': 'saved_work',
            'root_ref': seen['written']['root'], 'members_from': [{'kind': 'saved_result', 'operation_id': row['receipt_id']}
                for row in cs.saved_reference_summary(co, seen['writer_task'])['receipts']]})

    def writer_done(messages):
        seen['published'] = result(messages, 'commit_objects')['deliverable']['operation_id']
        return AIMessage(content='Saved synthetic calculation and summary.')

    def word(messages):
        return invoke('export_content_snapshot', deliverable={'kind': 'deliverable', 'operation_id': seen['published']})

    def excel(messages):
        seen['word'] = result(messages, 'export_content_snapshot')
        seen['snapshot'] = cs.read(seen['word']['export_ref'])['payload']['snapshot_ref']
        return invoke('export_content_workbook', snapshot_ref=seen['snapshot'], report_export_ref=seen['word']['export_ref'],
            sheets=[{'name': 'Ranking', 'table_ref': seen['assessment']['ranking_ref']},
                {'name': 'Evaluation', 'table_ref': seen['assessment']['evaluation_ref']}])

    def complete(messages):
        seen['excel'] = result(messages, 'export_content_workbook')
        return AIMessage(content='Paired synthetic artifacts complete; no semantic or engineering approval.')

    continuation = Driver(coordinator=[None] * len(steps) + [invoke('task', subagent_type='writer', section_ids=['4', '5'],
        description='Calculate the approved synthetic object and save its assessment tables and bound summary.'), word, excel, complete],
        writer=[writer_start, create_summary, chapter_text, assemble, outcome, publish_written, writer_done], text_tool=[text_payload])
    finished = await run(ws, continuation)
    errors = {m.tool_call_id: m for _, _, messages in continuation.calls for m in messages
        if isinstance(m, ToolMessage) and m.status == 'error'}
    assert finished['last_error'] is None, json.dumps({'status': finished['status'],
        'last_error': finished['last_error'], 'tool_errors': {key: value.content for key, value in errors.items()},
        'script_calls': [(role, step) for role, step, _ in continuation.calls]}, ensure_ascii=False)
    assert set(errors) == {'h3-native-1', linked_submit_id}, errors
    document = Document(BytesIO((ws.store.root / seen['word']['file_ref']).read_bytes()))
    workbook = load_workbook(BytesIO((ws.store.root / seen['excel']['file_ref']).read_bytes()))
    assert len([c for c in document.comments if c.author == '待核']) == 2 and workbook['资料澄清清单'].max_row == 3
    assert {'Ranking', 'Evaluation'} <= set(workbook.sheetnames)
    stored = cs.read(seen['assessment']['assessment_ref'])['payload']
    assert len(stored['indicators']) == 4 and stored['table_records']
    summary_text = cs.read(seen['summary'])['payload']['body']['text']
    assert '{SUMMARY}' not in summary_text and 'Summary:' in summary_text
    assert cs.read(seen['excel']['export_ref'])['payload']['snapshot_ref'] == seen['snapshot']
    evidence = {'mode': 'scripted_h2_steps_to_calculation_and_exports', 'semantic_acceptance': False,
        'initial_gap_list': seen['initial_gap_list'], 'classified_gap_list': seen['classified_gap_list'],
        'plan_ref': record['ref'], 'snapshot_ref': seen['snapshot'],
        'word': seen['word'], 'excel': seen['excel'], 'comment_count': len([c for c in document.comments if c.author == '待核']),
        'provider_calls': 0, 'initial_rejection_count': 2}
    (ws.store.root / 'h3-scripted-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
