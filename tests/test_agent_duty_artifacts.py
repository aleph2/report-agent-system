"""Actual native Layout bytes, independently checked against declared controls."""
from io import BytesIO
import json

import pytest
from docx import Document
from docx.oxml.ns import qn
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.deep_runtime import run_report
from test_agent_result_delivery import packet, reply
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_layout_table_controls import table_snapshot
from test_task_supervision import ws, offline


@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('local_controls', [False, True])
async def test_native_layout_parameters_reach_docx_and_parent_without_changing_content(ws, managed, local_controls):
    cs, _, table_ref, snapshot, refs = table_snapshot(ws)
    before = cs.read(snapshot), cs.read(table_ref), cs.read(refs['claim'])
    if managed:
        activate(ws)
    controls = {'table_line_spacing': 1.5, 'outer_border_style': 'double', 'outer_border_width_pt': 0.5}
    layout = {'toc': False, 'top_margin_mm': 25, 'bottom_margin_mm': 25,
              'left_margin_mm': 25, 'right_margin_mm': 15, 'line_spacing': 1.5,
              'styles': [{'name': 'Normal', 'font_size': 12, 'east_asia_font': '宋体'}]}
    if local_controls:
        layout['nodes'] = [{'node_ref': table_ref, **controls}]
    else:
        layout.update(controls)
    returned = []

    def child_return(messages):
        result = packet(reply(messages, 'export_content_snapshot'))
        result = result.get('metadata', result)['result']
        returned.append(result)
        return AIMessage(content=json.dumps({'export_ref': result['export_ref'],
                                             'remaining': 'Independent review not performed.'}))

    def parent(messages):
        text = str(reply(messages, 'task').content)
        assert returned[0]['export_ref']['id'] in text
        assert 'Independent review not performed.' in text
        return AIMessage(content='Export available, with review pending.')

    driver = Driver(coordinator=[invoke('task', subagent_type='layout',
        description='Apply these explicit synthetic layout controls only: ' + json.dumps(layout),
        layout_snapshot_ref=snapshot), parent],
        layout=[invoke('export_content_snapshot', operation_id='synthetic-layout', snapshot_ref=snapshot,
                       layout=layout), child_return])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    doc = Document(BytesIO((ws.store.root / returned[0]['file_ref']).read_bytes()))
    for section in doc.sections:
        for name, mm in [('top', 25), ('bottom', 25), ('left', 25), ('right', 15)]:
            assert abs(getattr(section, name + '_margin').mm - mm) < .05
    assert doc.styles['Normal'].paragraph_format.line_spacing == 1.5
    assert doc.styles['Normal'].font.size.pt == 12
    assert doc.styles['Normal']._element.rPr.rFonts.get(qn('w:eastAsia')) == '宋体'
    table = doc.tables[0]
    assert [[cell.text for cell in row.cells] for row in table.rows] == [
        ['项目', '原文'], ['岩性', '强风化；未经确认条件保留']]
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                assert para.paragraph_format.line_spacing == 1.5
    for side in ('top', 'left', 'bottom', 'right'):
        border = table._tbl.tblPr.find(qn('w:tblBorders')).find(qn('w:' + side))
        assert border.get(qn('w:val')) == 'double' and border.get(qn('w:sz')) == '4'
    assert before == (cs.read(snapshot), cs.read(table_ref), cs.read(refs['claim']))
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('managed', [False, True])
async def test_real_layout_error_trace_reaches_agent_then_explicit_correction_exports(ws, managed, request):
    """Replay the observed GLM hierarchy error; the fake agent chooses correction."""
    cs, _, table_ref, snapshot, refs = table_snapshot(ws)
    before = cs.read(snapshot), cs.read(table_ref), cs.read(refs['claim'])
    if managed:
        activate(ws)
    operation_id = 'synthetic-layout-correction'
    valid = {'toc': False, 'top_margin_mm': 25, 'bottom_margin_mm': 25,
             'left_margin_mm': 25, 'right_margin_mm': 15, 'line_spacing': 1.5}
    invalid = {**valid, 'qualifier_placement': 'adjacent'}
    observed = {}

    def correct(messages):
        error = next(m for m in reversed(messages) if isinstance(m, ToolMessage)
                     and m.tool_call_id == 'layout-invalid')
        assert error.status == 'error'
        # Do not require optional tool-message name or a particular wrapper.
        diagnostic = str(error.content)
        assert 'qualifier_placement' in diagnostic
        assert 'extra_forbidden' in diagnostic or 'Extra inputs are not permitted' in diagnostic
        assert not cs.list_objects('ExportArtifact')
        assert not cs.list_objects('MappingArtifact')
        assert before == (cs.read(snapshot), cs.read(table_ref), cs.read(refs['claim']))
        with ws.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_operations WHERE operation_id=?',
                              (operation_id,)).fetchone()[0] == 0
        observed['error'] = {'status': error.status, 'tool_call_id': error.tool_call_id,
                             'content': error.content, 'export_count': 0,
                             'mapping_count': 0,
                             'operation_count': 0, 'content_unchanged': True}
        call = invoke('export_content_snapshot', operation_id=operation_id, snapshot_ref=snapshot,
                      layout={**valid, 'nodes': [{'node_ref': refs['claim'],
                                                 'qualifier_placement': 'adjacent'}]})
        call.tool_calls[0]['id'] = 'layout-corrected'
        return call

    def finished(messages):
        returned = next(m for m in reversed(messages) if isinstance(m, ToolMessage)
                        and m.tool_call_id == 'layout-corrected')
        assert returned.status == 'success', returned
        value = packet(returned)
        value = value.get('metadata', value)
        assert value['ok'] is True, value
        observed['export'] = value['result']
        return AIMessage(content='Synthetic export saved; independent review remains pending.')

    first = invoke('export_content_snapshot', operation_id=operation_id, snapshot_ref=snapshot,
                   layout=invalid)
    first.tool_calls[0]['id'] = 'layout-invalid'
    driver = Driver(coordinator=[invoke('task', subagent_type='layout',
        description='Apply explicit synthetic margins and preserve the class B condition.',
        layout_snapshot_ref=snapshot), AIMessage(content='Draft export received.')],
        layout=[first, correct, finished])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(cs.list_objects('ExportArtifact')) == 2
    doc = Document(BytesIO((ws.store.root / observed['export']['file_ref']).read_bytes()))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert 'For adopted class B use 70.' in text
    assert 'condition' in text and 'class B' in text
    for section in doc.sections:
        for side, mm in [('top', 25), ('bottom', 25), ('left', 25), ('right', 15)]:
            assert abs(getattr(section, side + '_margin').mm - mm) < .05
    assert doc.styles['Normal'].paragraph_format.line_spacing == 1.5
    assert before == (cs.read(snapshot), cs.read(table_ref), cs.read(refs['claim']))
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_derived_layout_correction', json.dumps({
        'inspiration': '.analysis/agent-duty-validation-20261018/roles-live-wave1/layout',
        'managed': managed, 'observed': observed,
        'model_chose_correction': False, 'scripted_agent_explicitly_chose_correction': True,
        'semantic_correctness_claimed': False}, ensure_ascii=False)))


@pytest.mark.parametrize('fault', ['old_word_snapshot', 'omitted_workbook_note', 'same_snapshot_other_word'])
async def test_p10_native_exact_pair_rejects_one_changed_binding_then_saves_correct_pair(ws, request, fault):
    """One changed argument per negative attempt; genuine Word/XLSX bytes."""
    from copy import deepcopy
    from openpyxl import load_workbook
    from report_agent.content_export import export_snapshot
    from test_hierarchical_content import seed
    from test_agent_duty_trace_cases import action, result_value, tool_reply
    cs, owner, refs, base, members = seed(ws)
    added = cs.commit(owner, 'p10-channel', [
        {'client_key': 'table', 'type': 'ContentNode', 'payload': {'kind': 'table',
         'body': {'columns': ['Issue', 'Source'], 'rows': [['=1+1', 'A source conflict']]},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'note', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': 'B evidence remains unavailable.\n=Literal note, not formula.'},
         'qualifiers': {}, 'claim_kind': 'structure'}}])['result']['refs']
    first = cs.derive_snapshot(owner, 'p10-first', base, list(added.values()),
                               workbook_refs=list(added.values()))['result']['snapshot_ref']
    old_word = export_snapshot(cs, owner, 'p10-old-word', first, {'toc': False})['result']
    original_bytes = (ws.store.root / old_word['file_ref']).read_bytes()
    original_snapshot = deepcopy(cs.read(first))
    new_table = cs.commit(owner, 'p10-revise-only-table', [{'client_key': 'table', 'type': 'ContentNode',
        'previous_ref': added['table'], 'payload': {**cs.read(added['table'])['payload'],
        'body': {'columns': ['Issue', 'Source'], 'rows': [['=2+2', 'A corrected source conflict']]}}}])['result']['refs']['table']
    saved = {'old_word': old_word, 'first_snapshot': first, 'fault': fault}
    activate(ws)

    def export_word(messages):
        value = result_value(tool_reply(messages, 'derive'))
        assert value['ok'], value
        saved['snapshot'] = value['result']['snapshot_ref']
        return action('export_content_snapshot', 'word', operation_id='p10-word', snapshot_ref=saved['snapshot'], layout={'toc': False})

    def workbook(messages):
        value = result_value(tool_reply(messages, 'word'))
        assert value['ok'], value
        saved['word'] = value['result']
        saved['xlsx_before_attempt'] = sorted(str(p) for p in (ws.store.root / 'content-assets').glob('*.xlsx'))
        saved['sheets'] = [{'name': 'Issues', 'table_ref': new_table, 'note_refs': [added['note']]}]
        sheets = deepcopy(saved['sheets'])
        link = saved['word']['export_ref']
        if fault == 'old_word_snapshot':
            link = old_word['export_ref']
        elif fault == 'omitted_workbook_note':
            sheets[0]['note_refs'] = []
        return action('export_content_workbook', 'first-xlsx', operation_id='p10-first-xlsx',
                      snapshot_ref=saved['snapshot'], sheets=sheets, report_export_ref=link)

    def correct_or_export_other(messages):
        value = result_value(tool_reply(messages, 'first-xlsx'))
        if fault != 'same_snapshot_other_word':
            assert value['ok'] is False, value
            expected = 'WORD_WORKBOOK_SNAPSHOT_MISMATCH' if fault == 'old_word_snapshot' else 'WORKBOOK_CHANNEL_SELECTION_MISMATCH'
            assert value['code'] == expected, value
            assert sorted(str(p) for p in (ws.store.root / 'content-assets').glob('*.xlsx')) == saved['xlsx_before_attempt']
            assert ws.store.get('content_delivery') is None
            saved['rejection'] = value
            return action('export_content_workbook', 'correct-xlsx', operation_id='p10-correct-xlsx',
                snapshot_ref=saved['snapshot'], sheets=saved['sheets'], report_export_ref=saved['word']['export_ref'])
        assert value['ok'], value
        saved['xlsx'] = value['result']
        return action('export_content_snapshot', 'other-word', operation_id='p10-other-word',
                      snapshot_ref=saved['snapshot'], layout={'toc': False, 'right_margin_mm': 20})

    def choose(messages):
        call_id = 'other-word' if fault == 'same_snapshot_other_word' else 'correct-xlsx'
        value = result_value(tool_reply(messages, call_id))
        assert value['ok'], value
        if fault == 'same_snapshot_other_word':
            saved['other_word'] = value['result']
            word = value['result']['export_ref']
        else:
            saved['xlsx'] = value['result']
            word = saved['word']['export_ref']
        return action('select_content_delivery', 'select', operation_id='p10-select', snapshot_ref=saved['snapshot'],
                      export_ref=word, workbook_export_ref=saved['xlsx']['export_ref'], ending_reason='preserve_unresolved')

    def selected_or_correct(messages):
        value = result_value(tool_reply(messages, 'select'))
        if fault == 'same_snapshot_other_word':
            assert value['ok'] is False and value['code'] == 'COMPANION_EXPORT_VERSION_MISMATCH', value
            assert ws.store.get('content_delivery') is None
            saved['rejection'] = value
            return action('select_content_delivery', 'select-correct', operation_id='p10-select-correct',
                snapshot_ref=saved['snapshot'], export_ref=saved['word']['export_ref'],
                workbook_export_ref=saved['xlsx']['export_ref'], ending_reason='preserve_unresolved')
        assert value['ok'], value
        saved['selection'] = value
        return action('read_content_export', 'read-word', export_ref=saved['word']['export_ref'])

    def read_next(messages):
        if fault == 'same_snapshot_other_word':
            selected = result_value(tool_reply(messages, 'select-correct'))
            assert selected['ok'], selected
            saved['selection'] = selected
            return action('read_content_export', 'read-word', export_ref=saved['word']['export_ref'])
        saved['word_read'] = result_value(tool_reply(messages, 'read-word'))
        return action('read_content_export', 'read-xlsx', export_ref=saved['xlsx']['export_ref'])

    def read_xlsx(messages):
        saved['word_read'] = result_value(tool_reply(messages, 'read-word'))
        return action('read_content_export', 'read-xlsx', export_ref=saved['xlsx']['export_ref'])

    def finish(messages):
        saved['xlsx_read'] = result_value(tool_reply(messages, 'read-xlsx'))
        return AIMessage(content='Paired draft selected; B evidence remains unavailable; no semantic acceptance.')

    steps = [action('derive_snapshot', 'derive', operation_id='p10-derive', base_snapshot_ref=first,
                    additional_refs=[], replacements=[{'previous_ref': added['table'], 'new_ref': new_table}]),
             export_word, workbook, correct_or_export_other, choose, selected_or_correct, read_next]
    if fault == 'same_snapshot_other_word':
        steps.append(read_xlsx)
    steps.append(finish)
    driver = Driver(coordinator=steps)
    result = await run_report(ws, driver)
    from test_agent_duty_repro_artifacts import save_evidence
    saved['runtime_result'] = result
    saved['assets'] = [{'file_ref': item['file_ref'], 'kind': key} for key in ('old_word', 'word', 'xlsx', 'other_word')
                       if (item := saved.get(key)) is not None]
    save_evidence(request, ws, saved, driver)
    assert result['last_error'] is None, result
    actual = ws.store.get('content_delivery')
    assert actual['snapshot_ref'] == saved['snapshot'] and actual['export_ref'] == saved['word']['export_ref']
    assert actual['workbook_export_ref'] == saved['xlsx']['export_ref']
    assert actual['ending_reason'] == 'preserve_unresolved'
    doc = Document(ws.store.root / saved['word']['file_ref'])
    assert 'B evidence remains unavailable.' not in '\n'.join(p.text for p in doc.paragraphs)
    book = load_workbook(ws.store.root / saved['xlsx']['file_ref'])
    matrix = list(book.active.values)
    assert matrix[:2] == [('Issue', 'Source'), ('=2+2', 'A corrected source conflict')], matrix
    assert book.active['A2'].data_type == 's'
    assert 'B evidence remains unavailable.' in str(matrix) and '=Literal note, not formula.' in str(matrix)
    book.close()
    assert cs.read(first) == original_snapshot and (ws.store.root / old_word['file_ref']).read_bytes() == original_bytes
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('completion_case', json.dumps({'case': 'P10', 'variant': fault,
        'observed': saved, 'workbook_cells': matrix, 'native_roles': ['coordinator'],
        'paid_calls': 0, 'agent_choice_semantics_proven': False}, ensure_ascii=False)))


@pytest.mark.parametrize('with_relations', [True, False])
async def test_p10_native_derivation_requires_explicit_updated_relations(ws, request, with_relations):
    from copy import deepcopy
    from test_hierarchical_content import seed
    from test_agent_duty_trace_cases import action, result_value, tool_reply
    cs, owner, refs, base, members = seed(ws)
    original = deepcopy(cs.read(base))
    changed = cs.commit(owner, 'p10-body-v2', [{'client_key': 'claim', 'type': 'ContentNode', 'previous_ref': refs['claim'],
        'payload': {**cs.read(refs['claim'])['payload'], 'body': {'text': 'Corrected synthetic body.'}}}])['result']['refs']['claim']
    replacements = [{'previous_ref': refs['claim'], 'new_ref': changed}]
    for key in ('edge', 'support'):
        value = deepcopy(cs.read(refs[key])['payload'])
        for field in ('subject_ref', 'object_ref'):
            if value[field] == refs['claim']:
                value[field] = changed
        new = cs.commit(owner, 'p10-' + key, [{'client_key': key, 'type': 'Relation', 'previous_ref': refs[key],
                                             'payload': value}])['result']['refs'][key]
        replacements.append({'previous_ref': refs[key], 'new_ref': new})
    observed = {}
    def finish(messages):
        value = result_value(tool_reply(messages, 'derive'))
        observed.update(value)
        assert value['ok'] is with_relations, value
        if with_relations:
            new = cs.read(value['result']['snapshot_ref'])['payload']['refs']
            assert changed in new and refs['claim'] not in new
        else:
            assert value['code'] == 'INCOMPLETE_REFERENCE_CLOSURE', value
            assert len(cs.list_objects('DocumentSnapshot')) == 1
        return AIMessage(content='Explicit derivation result retained without inferred replacement.')
    driver = Driver(coordinator=[action('derive_snapshot', 'derive', operation_id='p10-relations', base_snapshot_ref=base,
        additional_refs=[], replacements=replacements if with_relations else replacements[:1]), finish])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert cs.read(base) == original
    request.node.user_properties.append(('completion_case', json.dumps({'case': 'P10.C2',
        'variant': 'explicit_relations' if with_relations else 'only_node_replaced', 'observed': observed})))


async def _p13_reuse_case(ws, request, variant, *, managed=False):
    from copy import deepcopy
    from report_agent.content_tasks import delegated_task
    from report_agent.task_supervision import reconcile
    from report_agent.catalog import Catalog
    from test_hierarchical_content import seed, review_item, submission
    from test_task_supervision import review_call
    from test_agent_duty_trace_cases import action, result_value, tool_reply
    cs, owner, refs, base, members = seed(ws)
    catalogue = Catalog(ws.store)
    sid = catalogue.import_file('p13-independent.txt', b'Independent local-body evidence.')['source']['id']
    first_call = review_call(base, refs, 'p13-original')
    req = first_call['args']['review_requirements'][0]
    req.update(target_ref=refs['root'], material_refs=[refs['claim']],
        content_check_scopes=[{'requirement_index': 0, 'node_ref': refs['root'], 'kind': 'local_body'}])
    if managed:
        req['required_materials'] = [{'requirement_index': 0, 'purpose': 'Exact local body and associated claim.',
                                      'refs': [refs['root'], refs['claim']]}]
    with delegated_task(ws, 'coordinator', first_call) as (_, previous_reviewer):
        source_ref = cs.capture_sources(previous_reviewer, 'p13-source', [sid])['result']['source_refs'][0]
        receipt = cs.read_context(previous_reviewer, refs['root'])['receipt_id']
        claim_receipt = cs.read_context(previous_reviewer, refs['claim'])['receipt_id']
        cs.read_context(previous_reviewer, source_ref)
        item = review_item(refs['root'], refs['k'], receipt, 'undetermined')
        item.update(scope_id='rule-comparison', dependency_refs=[source_ref])
        if managed:
            item['observations'].append({'locator': 'claim', 'observation': 'Synthetic exact claim read.', 'receipt_id': claim_receipt})
            item['checked_requirement_indexes'] = [0]
            item['check_results'] = [{'requirement_index': 0, 'execution_state': 'completed',
                'result': 'Historical synthetic local body check; not subtree.', 'observation_indexes': [0, 1], 'remaining': ''}]
        data = submission(base, refs, item)
        data.update(target_ref=refs['root'], dependency_refs=[source_ref])
        old_review = cs.submit_review(previous_reviewer, 'p13-original-review', data, {})['result']['review_ref']
        assert reconcile(cs, previous_reviewer.task_id)['execution_complete']
    original = deepcopy(cs.read(old_review))
    additions = cs.commit(owner, 'p13-new-child', [
        {'client_key': 'child', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': 'A new child was never covered by the old local-body judgment.'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'], 'object_ref': {'client_key': 'child'},
         'predicate': 'contains', 'position': 1, 'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    new_members = members + list(additions.values())
    criterion = refs['k']
    if variant == 'criterion_version':
        criterion = cs.commit(owner, 'p13-criterion-v2', [{'client_key': 'criterion', 'type': 'Criterion',
            'previous_ref': refs['k'], 'payload': {**cs.read(refs['k'])['payload'],
                                                 'expected_outcome': 'A new independently requested check.'}}])['result']['refs']['criterion']
        new_members = [r for r in new_members if r != refs['k']] + [criterion]
    elif variant == 'source_version':
        catalogue.import_file('p13-independent.txt', b'Revised independent local-body evidence.', sid)
    new = cs.freeze(owner, 'p13-new-snapshot', refs['root'], new_members)['result']['snapshot_ref']
    next_call = review_call(new, {**refs, 'k': criterion}, 'p13-next')
    next_req = next_call['args']['review_requirements'][0]
    next_req.update(target_ref=refs['root'], material_refs=[refs['claim']],
        content_check_scopes=[{'requirement_index': 0, 'node_ref': refs['root'],
                              'kind': 'subtree_bodies' if variant == 'subtree_extent' else 'local_body'}])
    if managed:
        next_req['required_materials'] = req['required_materials']
        from test_decision_data import activate
        activate(ws)
    next_call['args'].pop('supervision_plugin', None)  # No automatic followup masks the retained remaining work.
    observed = {'variant': variant, 'old_review': old_review, 'base': base, 'new_snapshot': new,
                'configuration': 'managed-bounded-tool-v1' if managed else 'legacy-unmanaged',
                'review_requirements': next_call['args']['review_requirements'],
                'historical_review_creation': 'manual recorded synthetic ReviewRecord; no checker model'}

    def reuse(messages):
        observed['impact'] = result_value(tool_reply(messages, 'impact'))
        return action('confirm_review_reuse', 'reuse', operation_id='p13-reuse', review_ref=old_review,
                      new_snapshot=new, reason='Synthetic explicit item applicability request.', item_indexes=[0])

    def child_finish(messages):
        value = result_value(tool_reply(messages, 'reuse'))
        observed['reuse'] = value
        if variant in {'criterion_version', 'source_version'}:
            assert value['ok'] is False, value
            expected = 'CHANGED_REVIEW_SOURCE_REQUIRES_RECHECK' if variant == 'source_version' else 'CHANGED_REVIEW_INPUT_REQUIRES_RECHECK'
            assert value['code'] == expected, value
        else:
            assert value['ok'] is True, value
        task = next(t for t in cs.list_objects('DelegatedTask') if t['ref']['id'] != previous_reviewer.task_id)
        status = reconcile(cs, task['ref']['id'])
        observed['reconcile'] = status
        assert status['execution_complete'] is (variant == 'same_local'), status
        return AIMessage(content=json.dumps({'review_ref': old_review, 'execution_complete': status['execution_complete'],
                                            'remaining': status['remaining']}))

    def parent_status(messages):
        observed['parent_task_return'] = result_value(tool_reply(messages, 'p13-next'))
        return action('read_task_supervision', 'status')

    def finish(messages):
        observed['parent_status'] = result_value(tool_reply(messages, 'status'))
        return AIMessage(content='Scope-specific reuse observed; no whole-report acceptance.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[next_call]), parent_status, finish],
        reviewer=[action('assess_change_impact', 'impact', old_snapshot=base, new_snapshot=new), reuse, child_finish])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    request.node.user_properties.append(('completion_case', json.dumps({'case': 'P13', 'observed': observed,
        'source_changed_only_in_source_variant': variant == 'source_version', 'agent_semantic_reuse_proven': False}, ensure_ascii=False)))
    assert result['last_error'] is None, result
    assert cs.read(old_review) == original


@pytest.mark.parametrize('variant', ['same_local', 'subtree_extent', 'criterion_version', 'source_version'])
async def test_p13_native_reviewer_reuse_preserves_extent_and_changed_dependencies(ws, request, variant):
    await _p13_reuse_case(ws, request, variant)


@pytest.mark.parametrize('variant', ['same_local', 'subtree_extent', 'criterion_version', 'source_version'])
async def test_p13_managed_reviewer_reuse_keeps_local_vs_subtree_boundary(ws, request, variant):
    await _p13_reuse_case(ws, request, variant, managed=True)


@pytest.mark.parametrize('selected_item', [0, 1])
async def test_p13_managed_native_item_reuse_keeps_unchanged_sibling(ws, request, selected_item):
    """Change root only; selection is the sole difference between the pair."""
    from copy import deepcopy
    from test_review_cleanup import items, save
    from test_hierarchical_content import seed
    from test_bounded_review import review_call
    from test_agent_duty_trace_cases import action, result_value, tool_reply
    cs, owner, refs, old, members = seed(ws)
    old_review = save(cs, old, refs, items(cs, old, refs), 'p13-item-original')
    original = deepcopy(cs.read(old_review))
    revised = cs.commit(owner, 'p13-item-root-v2', [
        {'client_key': 'root', 'type': 'ContentNode', 'previous_ref': refs['root'],
         'payload': {**cs.read(refs['root'])['payload'], 'body': {'text': 'Changed root only; claim unchanged.'}}},
        {'client_key': 'edge', 'type': 'Relation', 'previous_ref': refs['edge'],
         'payload': {**cs.read(refs['edge'])['payload'], 'subject_ref': {'client_key': 'root'}}}])['result']['refs']
    new = cs.freeze(owner, 'p13-item-new-snapshot', revised['root'],
        [r for r in members if r not in [refs['root'], refs['edge']]] + list(revised.values()))['result']['snapshot_ref']
    activate(ws)
    call = review_call(new, refs, 'p13-item-task')
    call['args'].pop('supervision_plugin', None)
    observed = {'selected_item': selected_item, 'old_review': old_review, 'snapshot': new}
    def finish_child(messages):
        value = result_value(tool_reply(messages, 'reuse-item'))
        observed['native_reuse_return'] = value
        assert value['ok'] is (selected_item == 0), value
        if selected_item:
            assert value['code'] == 'CHANGED_REVIEW_INPUT_REQUIRES_RECHECK'
        return action('read_review_status', 'item-status', snapshot_ref=new, target_ref=refs['claim'])
    def return_child(messages):
        observed['native_status'] = result_value(tool_reply(messages, 'item-status'))
        return AIMessage(content=json.dumps(observed))
    def parent(messages):
        observed['parent_return'] = result_value(tool_reply(messages, 'p13-item-task'))
        assert ('CHANGED_REVIEW_INPUT_REQUIRES_RECHECK' in json.dumps(observed['parent_return'])) is bool(selected_item)
        return AIMessage(content='Item reuse returned without converting old local review into whole-report acceptance.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), parent], reviewer=[
        action('confirm_review_reuse', 'reuse-item', operation_id='p13-item-reuse', review_ref=old_review,
            new_snapshot=new, reason='Explicitly select just this historical item.', item_indexes=[selected_item]),
        finish_child, return_child])
    result = await run_report(ws, driver)
    request.node.user_properties.append(('completion_case', json.dumps({'case': 'P13.C3', 'observed': observed})))
    assert result['last_error'] is None, result
    assert 'native_status' in observed
    assert cs.read(old_review) == original
