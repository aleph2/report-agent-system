"""Native local-review reuse followed by current subtree checking, fake models.

The scripted omission is a test input, not evidence that a real Reviewer omits
material. Historical reading/reuse is legal. No product repair or paid calls.
"""
from copy import deepcopy
import hashlib
import json

from langchain_core.messages import AIMessage, ToolMessage
import pytest

from report_agent.bounded_review import perform_review
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.task_supervision import reconcile
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import review_call, ws, offline


@pytest.mark.parametrize('include_child_body', [True, False], ids=['complete-body', 'missing-body'])
async def test_native_local_reuse_then_subtree_check_keeps_current_material_gap(
        ws, request, include_child_body):
    cs, owner, refs, old_snapshot, members = seed(ws)
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    original_sources = deepcopy(ws.store.manifest['sources'])
    old_call = review_call(old_snapshot, refs, 'continuation-old', reads=[source])
    old_requirement = old_call['args']['review_requirements'][0]
    old_requirement.update(target_ref=refs['root'], material_refs=[refs['claim']],
        required_materials=[{'requirement_index': 0, 'purpose': 'Exact local body, claim and original rule.',
                             'refs': [refs['root'], refs['claim'], source]}],
        content_check_scopes=[{'requirement_index': 0, 'node_ref': refs['root'], 'kind': 'local_body'}])
    historical_raw = {'items': [{'scope_id': 'rule-comparison',
        'checked_requirement_indexes': [0], 'execution_state': 'completed', 'verdict': 'undetermined',
        'observations': [
            {'evidence_index': 0, 'locator': 'root local body', 'observation': 'Synthetic root local body read.'},
            {'evidence_index': 1, 'locator': 'original rule', 'observation': 'Class B permits 75 to 100.'},
            {'evidence_index': 2, 'locator': 'associated claim', 'observation': 'The saved claim says 70.'}],
        'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
            'result': 'Historical synthetic local-body assessment; no descendant completeness.',
            'observation_indexes': [0, 1, 2], 'remaining': ''}],
        'coverage': {'checked': ['Local body and associated comparison material.'], 'unchecked': [],
                     'blocked': [], 'basis': 'Historical synthetic local extent only.'},
        'reason': 'Fixture of completed work with undetermined judgment; not report acceptance.', 'findings': []}]}
    historical_model = Model(json.dumps(historical_raw))
    observed = {'case': 'P13-current-review-continuation', 'include_child_body': include_child_body,
        'single_changed_call_argument': 'perform_assigned_review.content_selections',
        'historical_raw': historical_raw, 'old_call': deepcopy(old_call), 'assets': [],
        'limits': 'Scripted fake choices through the native runtime; no real strategy or engineering acceptance.'}
    driver = None
    try:
        with delegated_task(ws, 'coordinator', old_call) as (_, old_actor):
            old_result = await perform_review(ws, old_actor, historical_model,
                'continuation-historical-check', ['rule-comparison'])
            old_review = old_result['review_ref']
            observed['historical_checker_input'] = historical_model.calls
            old_status = reconcile(cs, old_actor.task_id)
            assert old_status['execution_complete'] is True, old_status
        assert len(historical_model.calls) == 1
        observed['old_review'] = deepcopy(cs.read(old_review))
        additions = cs.commit(owner, 'continuation-new-child', [
            {'client_key': 'child', 'type': 'ContentNode', 'payload': {'kind': 'block',
                'body': {'text': 'NEW-CHILD-BODY: the expanded report retains the unresolved class condition.'},
                'qualifiers': {}, 'claim_kind': 'structure'}},
            {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
                'object_ref': {'client_key': 'child'}, 'predicate': 'contains', 'position': 1,
                'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
        child = additions['child']
        new_snapshot = cs.freeze(owner, 'continuation-current-snapshot', refs['root'],
            members + list(additions.values()))['result']['snapshot_ref']
        current_call = review_call(new_snapshot, refs, 'continuation-current', reads=[source])
        current = current_call['args']['review_requirements'][0]
        current.update(deepcopy(old_requirement))
        current['material_refs'].append(child)
        current['content_check_scopes'][0]['kind'] = 'subtree_bodies'
        current_call['args'].pop('supervision_plugin', None)
        current_call['args']['description'] = (
            'Assess applicability of the historical local judgment, then the current assigned subtree. '
            'Keep unavailable input distinct from absent project evidence and from a content verdict.')
        mandatory = [current['target_ref'], *current['required_read_refs'],
            *[ref for material in current['required_materials'] for ref in material['refs']]]
        assert child in current['material_refs'] and child not in mandatory
        assert current['required_checks'] == old_requirement['required_checks']
        assert current['criterion_ref'] == old_requirement['criterion_ref']
        frozen_before = {json.dumps(ref, sort_keys=True): deepcopy(cs.read(ref))
                         for ref in [old_snapshot, new_snapshot, *members, *additions.values()]}
        observed.update(current_call=deepcopy(current_call), child_ref=child,
                        old_snapshot=old_snapshot, new_snapshot=new_snapshot, mandatory_refs=mandatory)
        activate(ws)

        def current_task():
            return next(t for t in cs.list_objects('DelegatedTask')
                        if t['ref']['id'] != old_actor.task_id)

        def after_reuse(messages):
            value = result_value(tool_reply(messages, 'reuse'))
            observed['reuse_public'] = value
            assert value['ok'] is True, value
            status = reconcile(cs, current_task()['ref']['id'])
            observed['status_after_reuse'] = status
            assert status['execution_complete'] is False and status['remaining'], status
            observed['review_records_before_current_check'] = deepcopy(cs.list_objects('ReviewRecord'))
            assert len(observed['review_records_before_current_check']) == 1
            selection = [{'ref': child, 'unit': 'text', 'offset': 0,
                          'limit': len(cs.read(child)['payload']['body']['text'])}]
            return action('perform_assigned_review', 'check-current',
                operation_id='continuation-current-check', scope_ids=['rule-comparison'],
                source_selections=[], content_selections=selection if include_child_body else [])

        def checker(messages):
            packet = json.loads(messages[-1].content)
            observed['current_checker_input'] = packet
            assert include_child_body, 'Missing-body fixture must stop before independent checker dispatch.'
            assert packet['assignment']['review_snapshot_ref'] == new_snapshot
            assert packet['criteria'][0] == cs.read(refs['k'])
            evidence = packet['evidence']
            selections = [entry for entry in evidence if entry['kind'] == 'content_node_selection']
            assert len(selections) == 1
            selected = selections[0]
            assert selected['selection']['ref'] == child
            assert selected['body'] == cs.read(child)['payload']['body']
            assert selected['complete_body_selection'] is True
            saved = [entry['object'] for entry in evidence if entry['kind'] == 'saved_object']
            assert {json.dumps(obj['ref'], sort_keys=True) for obj in saved} == {
                json.dumps(ref, sort_keys=True) for ref in [refs['root'], source, refs['claim']]}
            assert all(obj == cs.read(obj['ref']) for obj in saved)
            structure = next(entry['structure'] for entry in evidence if entry['kind'] == 'snapshot_structure')
            assert structure['missing_body_extents'] == []
            assert set(map(lambda ref: json.dumps(ref, sort_keys=True),
                structure['body_extents'][0]['required_body_refs'])) == {
                    json.dumps(ref, sort_keys=True) for ref in [refs['root'], refs['claim'], child]}
            indexes = [index for index, entry in enumerate(evidence)
                       if entry['kind'] in ('saved_object', 'content_node_selection')]
            observations = [{'evidence_index': index, 'locator': 'exact material ' + str(index),
                'observation': ('NEW-CHILD-BODY read with its unresolved condition.'
                                if evidence[index]['kind'] == 'content_node_selection'
                                else 'Original supplied material retained without changing its version.')}
                for index in indexes]
            raw = {'items': [{'scope_id': 'rule-comparison', 'checked_requirement_indexes': [0],
                'execution_state': 'completed', 'verdict': 'not_satisfied', 'observations': observations,
                'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
                    'result': '70 remains outside the original class B interval 75 to 100; expanded body was read.',
                    'observation_indexes': list(range(len(indexes))), 'remaining': ''}],
                'coverage': {'checked': ['Exact assigned subtree and comparison materials.'],
                             'unchecked': [], 'blocked': [], 'basis': 'Current snapshot bodies and original rule.'},
                'reason': 'Check execution completed; the retained score conflict is not satisfied.', 'findings': []}]}
            observed['current_checker_raw'] = raw
            return AIMessage(content=json.dumps(raw))

        def reviewer_after_check(messages):
            value = result_value(tool_reply(messages, 'check-current'))
            observed['current_check_public'] = value
            task_id = current_task()['ref']['id']
            status = reconcile(cs, task_id)
            observed['status_after_current_check'] = status
            current_records = cs.list_objects('ReviewRecord')
            if include_child_body:
                assert len(current_records) == 2, current_records
                record = cs.read(value['review_ref'])
                observed['current_review'] = record
                assert record['task_id'] == task_id
                assert record['owner_id'] == 'content:reviewer:' + task_id
                assert record['payload']['snapshot_ref'] == new_snapshot
                assert record['payload']['criteria_refs'] == [refs['k']]
                assert value['items'] == record['payload']['items']
                item = value['items'][0]
                for field in ('execution_state', 'verdict', 'check_results', 'coverage', 'reason', 'findings'):
                    assert item[field] == observed['current_checker_raw']['items'][0][field]
                assert [o['observation'] for o in item['observations']] == [
                    o['observation'] for o in observed['current_checker_raw']['items'][0]['observations']]
                assert status['execution_complete'] is True and status['remaining'] == [], status
                assert item['verdict'] == 'not_satisfied'
            else:
                assert value['ok'] is False and value['code'] == 'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED', value
                assert value['model_called'] is False and value['review_ref'] is None
                gaps = value['material_context']['missing_body_extents']
                assert len(gaps) == 1 and gaps[0]['missing_full_body_refs'] == [child], gaps
                assert gaps[0]['unbound_body_refs'] == [], gaps
                assert current_records == observed['review_records_before_current_check']
                assert 'current_checker_input' not in observed
                assert status['execution_complete'] is False and status['remaining'], status
            return AIMessage(content=json.dumps({'current_check': value, 'current_scope_status': status}))

        def coordinator_after_review(messages):
            value = result_value(tool_reply(messages, 'continuation-current'))
            observed['parent_task_return'] = value
            encoded = json.dumps(value)
            if include_child_body:
                assert observed['current_review']['ref']['id'] in encoded
                assert 'not_satisfied' in encoded
                assert observed['current_checker_raw']['items'][0]['check_results'][0]['result'] in encoded
            else:
                assert 'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED' in encoded and child['id'] in encoded
            return action('read_task_supervision', 'parent-status')

        def coordinator_finish(messages):
            last = next(message for message in reversed(messages) if isinstance(message, ToolMessage))
            observed.setdefault('parent_supervision_messages', []).append(last.model_dump())
            value = result_value(last)
            if value.get('exact_data_tool') == 'read_tool_observation':
                pages = observed.setdefault('parent_supervision_pages', [])
                assert value['cursor_unit'] == 'unicode_characters'
                assert value['offset'] == sum(len(page['text']) for page in pages)
                assert value['end'] == value['offset'] + len(value['text'])
                assert value['end'] > value['offset']
                if pages:
                    for field in ('observation_ref', 'sha256', 'total_characters'):
                        assert value[field] == pages[0][field]
                else:
                    assert last.name == 'read_task_supervision'
                pages.append(deepcopy(value))
                if value['next_offset'] is not None:
                    assert value['next_offset'] == value['end'] < value['total_characters']
                    driver.scripts['coordinator'].append(coordinator_finish)
                    return action('read_tool_observation', 'parent-status-page-' + str(value['next_offset']),
                        observation_ref=value['observation_ref'], offset=value['next_offset'], characters=6000)
                text = ''.join(page['text'] for page in pages)
                assert len(text) == value['total_characters']
                assert hashlib.sha256(text.encode('utf-8')).hexdigest() == value['sha256']
                value = json.loads(text)
            observed['parent_supervision_public'] = value
            # Locate this exact current task, not its completed historical sibling.
            def task_rows(value):
                if isinstance(value, dict):
                    if value.get('task_id') == current_task()['ref']['id'] and 'execution_complete' in value:
                        yield value
                    for nested in value.values():
                        yield from task_rows(nested)
                elif isinstance(value, list):
                    for nested in value:
                        yield from task_rows(nested)
            rows = list(task_rows(value))
            observed['parent_current_task_statuses'] = rows
            assert rows, value
            assert all(row['execution_complete'] is include_child_body for row in rows), rows
            assert all(bool(row['remaining']) is (not include_child_body) for row in rows), rows
            return AIMessage(content='Current assigned extent accounted for; no semantic or whole-report acceptance.')

        driver = Driver(coordinator=[AIMessage(content='', tool_calls=[current_call]),
                                     coordinator_after_review, coordinator_finish],
            reviewer=[action('confirm_review_reuse', 'reuse', operation_id='continuation-local-reuse',
                review_ref=old_review, new_snapshot=new_snapshot,
                reason='Preserve the unchanged local judgment without claiming subtree completeness.', item_indexes=[0]),
                after_reuse, reviewer_after_check], text_tool=[checker])
        observed['runtime_result'] = await run_report(ws, driver)
        assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
        assert observed.get('parent_current_task_statuses')
        current_dispatches = [call for call in driver.calls if call[0] == 'text_tool']
        observed['current_checker_dispatches'] = len(current_dispatches)
        assert len(current_dispatches) == int(include_child_body)
        assert cs.read(old_review) == observed['old_review']
        assert ws.store.manifest['sources'] == original_sources
        assert frozen_before == {key: cs.read(json.loads(key)) for key in frozen_before}
        observed['historical_record_and_frozen_inputs_unchanged'] = True
    finally:
        observed['review_records_after'] = cs.list_objects('ReviewRecord')
        with ws.store.connect() as db:
            observed['actual_receipts'] = [{'id': row[0], 'actor_id': row[1], 'data': json.loads(row[2])}
                for row in db.execute('SELECT id, actor_id, data FROM content_observations')]
        save_evidence(request, ws, observed, driver)


@pytest.mark.parametrize('include_child_body', [True, False], ids=['complete-body', 'missing-body'])
async def test_manual_historical_local_reuse_then_current_bounded_subtree_check(
        ws, request, include_child_body):
    """Compatibility history, explicitly distinct from current bounded production.

    The original bounded-history pair above remains unchanged, including its
    reuse-success oracle. This pair uses the existing P13 historical construction
    to reach and check the previously unexecuted continuation boundary.
    """
    from test_hierarchical_content import review_item, submission
    cs, owner, refs, old_snapshot, members = seed(ws)
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    old_call = review_call(old_snapshot, refs, 'manual-old', reads=[source])
    req = old_call['args']['review_requirements'][0]
    req.update(target_ref=refs['root'], material_refs=[refs['claim']],
        required_materials=[{'requirement_index': 0, 'purpose': 'Exact local body, claim and original rule.',
                             'refs': [refs['root'], refs['claim'], source]}],
        content_check_scopes=[{'requirement_index': 0, 'node_ref': refs['root'], 'kind': 'local_body'}])
    with delegated_task(ws, 'coordinator', old_call) as (_, old_actor):
        root_receipt = cs.read_context(old_actor, refs['root'])['receipt_id']
        claim_receipt = cs.read_context(old_actor, refs['claim'])['receipt_id']
        source_receipt = cs.read_context(old_actor, source)['receipt_id']
        item = review_item(refs['root'], refs['k'], root_receipt, 'undetermined')
        item.update(scope_id='rule-comparison', dependency_refs=[source], checked_requirement_indexes=[0])
        item['observations'] += [
            {'locator': 'claim', 'observation': 'Synthetic historical claim read.', 'receipt_id': claim_receipt},
            {'locator': 'source', 'observation': 'Original class B interval 75 to 100.', 'receipt_id': source_receipt}]
        item['check_results'] = [{'requirement_index': 0, 'execution_state': 'completed',
            'result': 'Historical local check only.', 'observation_indexes': [0, 1, 2], 'remaining': ''}]
        data = submission(old_snapshot, refs, item)
        data.update(target_ref=refs['root'], dependency_refs=[source])
        old_review = cs.submit_review(old_actor, 'manual-historical-review', data, {})['result']['review_ref']
        assert reconcile(cs, old_actor.task_id)['execution_complete'] is True
    additions = cs.commit(owner, 'manual-current-child', [
        {'client_key': 'child', 'type': 'ContentNode', 'payload': {'kind': 'block',
            'body': {'text': 'NEW-CHILD-BODY: the expanded report retains the unresolved class condition.'},
            'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'child'}, 'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    child = additions['child']
    current_snapshot = cs.freeze(owner, 'manual-current-snapshot', refs['root'],
        members + list(additions.values()))['result']['snapshot_ref']
    call = review_call(current_snapshot, refs, 'manual-current', reads=[source])
    current = call['args']['review_requirements'][0]
    current.update(deepcopy(req))
    current['material_refs'].append(child)
    current['content_check_scopes'][0]['kind'] = 'subtree_bodies'
    call['args'].pop('supervision_plugin', None)
    mandatory = [current['target_ref'], *current['required_read_refs'],
        *[ref for m in current['required_materials'] for ref in m['refs']]]
    assert child in current['material_refs'] and child not in mandatory
    assert current['required_checks'] == req['required_checks'] and current['criterion_ref'] == req['criterion_ref']
    protected = {json.dumps(ref, sort_keys=True): deepcopy(cs.read(ref))
                 for ref in [old_review, old_snapshot, current_snapshot, *members, *additions.values()]}
    original_sources = deepcopy(ws.store.manifest['sources'])
    observed = {'case': 'P13-manual-history-current-continuation', 'include_child_body': include_child_body,
        'historical_origin': 'Manually saved synthetic ReviewRecord using the preexisting P13 compatibility fixture; NOT a current bounded producer record.',
        'old_review': deepcopy(cs.read(old_review)), 'current_call': deepcopy(call),
        'old_snapshot': old_snapshot, 'new_snapshot': current_snapshot, 'child_ref': child,
        'single_changed_call_argument': 'perform_assigned_review.content_selections', 'mandatory_refs': mandatory,
        'limits': 'This does not establish cross-snapshot reuse of current bounded producer records.', 'assets': []}
    activate(ws)

    def task_id():
        return next(t['ref']['id'] for t in cs.list_objects('DelegatedTask') if t['ref']['id'] != old_actor.task_id)

    def after_reuse(messages):
        observed['reuse_public'] = result_value(tool_reply(messages, 'manual-reuse'))
        assert observed['reuse_public']['ok'] is True, observed['reuse_public']
        status = reconcile(cs, task_id())
        observed['status_after_reuse'] = status
        assert status['execution_complete'] is False and status['remaining'], status
        observed['before_check_reviews'] = deepcopy(cs.list_objects('ReviewRecord'))
        assert len(observed['before_check_reviews']) == 1
        selection = [{'ref': child, 'unit': 'text', 'offset': 0,
                      'limit': len(cs.read(child)['payload']['body']['text'])}]
        return action('perform_assigned_review', 'manual-check', operation_id='manual-current-check',
            scope_ids=['rule-comparison'], source_selections=[],
            content_selections=selection if include_child_body else [])

    def checker(messages):
        packet = json.loads(messages[-1].content)
        observed['checker_packet'] = packet
        assert include_child_body
        assert packet['assignment']['review_snapshot_ref'] == current_snapshot
        assert packet['criteria'][0] == cs.read(refs['k'])
        evidence = packet['evidence']
        saved = [entry['object'] for entry in evidence if entry['kind'] == 'saved_object']
        assert {json.dumps(obj['ref'], sort_keys=True) for obj in saved} == {
            json.dumps(ref, sort_keys=True) for ref in [refs['root'], refs['claim'], source]}
        assert all(obj == cs.read(obj['ref']) for obj in saved)
        selections = [entry for entry in evidence if entry['kind'] == 'content_node_selection']
        assert len(selections) == 1 and selections[0]['selection']['ref'] == child
        assert selections[0]['body'] == cs.read(child)['payload']['body']
        assert selections[0]['complete_body_selection'] is True
        structure = next(entry['structure'] for entry in evidence if entry['kind'] == 'snapshot_structure')
        assert structure['missing_body_extents'] == []
        assert {json.dumps(ref, sort_keys=True) for ref in structure['body_extents'][0]['required_body_refs']} == {
            json.dumps(ref, sort_keys=True) for ref in [refs['root'], refs['claim'], child]}
        indexes = [index for index, entry in enumerate(evidence)
                   if entry['kind'] in ('saved_object', 'content_node_selection')]
        raw = {'items': [{'scope_id': 'rule-comparison', 'checked_requirement_indexes': [0],
            'execution_state': 'completed', 'verdict': 'not_satisfied',
            'observations': [{'evidence_index': index, 'locator': 'actual material ' + str(index),
                'observation': 'Current required body or original source was supplied without changing its version.'}
                for index in indexes],
            'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
                'result': '70 is outside 75 to 100; the expanded subtree including NEW-CHILD-BODY was checked.',
                'observation_indexes': list(range(len(indexes))), 'remaining': ''}],
            'coverage': {'checked': ['Current subtree and original rule.'], 'unchecked': [], 'blocked': [],
                         'basis': 'Exact current bodies and source version.'},
            'reason': 'Completed check retains the original score conflict.', 'findings': []}]}
        observed['checker_raw'] = raw
        return AIMessage(content=json.dumps(raw))

    def after_check(messages):
        public = result_value(tool_reply(messages, 'manual-check'))
        observed['check_public'] = public
        records = cs.list_objects('ReviewRecord')
        status = reconcile(cs, task_id())
        observed['status_after_check'] = status
        if include_child_body:
            assert len(records) == 2
            record = cs.read(public['review_ref'])
            observed['new_review'] = record
            assert record['task_id'] == task_id() and record['owner_id'] == 'content:reviewer:' + task_id()
            assert record['payload']['snapshot_ref'] == current_snapshot
            assert record['payload']['criteria_refs'] == [refs['k']]
            assert public['items'] == record['payload']['items']
            item = public['items'][0]
            for field in ('execution_state', 'verdict', 'check_results', 'coverage', 'reason', 'findings'):
                assert item[field] == observed['checker_raw']['items'][0][field]
            assert [o['observation'] for o in item['observations']] == [
                o['observation'] for o in observed['checker_raw']['items'][0]['observations']]
            assert status['execution_complete'] is True and status['remaining'] == []
            assert item['verdict'] == 'not_satisfied'
        else:
            assert public['ok'] is False and public['code'] == 'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED', public
            assert public['model_called'] is False and public['review_ref'] is None
            gaps = public['material_context']['missing_body_extents']
            assert len(gaps) == 1 and gaps[0]['missing_full_body_refs'] == [child], gaps
            assert gaps[0]['unbound_body_refs'] == []
            assert records == observed['before_check_reviews'] and 'checker_packet' not in observed
            assert status['execution_complete'] is False and status['remaining']
        return AIMessage(content=json.dumps({'current_check': public, 'current_scope_status': status}))

    def parent(messages):
        public = result_value(tool_reply(messages, 'manual-current'))
        observed['parent_return'] = public
        text = json.dumps(public)
        if include_child_body:
            assert observed['new_review']['ref']['id'] in text and 'not_satisfied' in text
            assert observed['checker_raw']['items'][0]['check_results'][0]['result'] in text
        else:
            assert 'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED' in text and child['id'] in text
        return action('read_task_supervision', 'manual-parent-status')

    def finish(messages):
        public = result_value(tool_reply(messages, 'manual-parent-status'))
        observed['parent_supervision_public'] = public
        assert public['ok'] is True, public
        status = next(row for row in public['result']['tasks'] if row['task_id'] == task_id())
        observed['parent_current_status'] = status
        assert status['execution_complete'] is include_child_body
        assert bool(status['remaining']) is (not include_child_body)
        assert status['semantic_coverage_verified'] is False
        return AIMessage(content='Current assigned execution and material gap retained; no report acceptance.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), parent, finish],
        reviewer=[action('confirm_review_reuse', 'manual-reuse', operation_id='manual-local-reuse',
            review_ref=old_review, new_snapshot=current_snapshot,
            reason='Retain unchanged local history separately from the expanded current obligation.', item_indexes=[0]),
            after_reuse, after_check], text_tool=[checker])
    try:
        observed['runtime_result'] = await run_report(ws, driver)
        assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
        assert observed.get('parent_current_status')
        observed['checker_dispatches'] = sum(role == 'text_tool' for role, _, _ in driver.calls)
        assert observed['checker_dispatches'] == int(include_child_body)
        assert protected == {key: cs.read(json.loads(key)) for key in protected}
        assert ws.store.manifest['sources'] == original_sources
        observed['historical_record_and_frozen_inputs_unchanged'] = True
    finally:
        observed['records_after'] = cs.list_objects('ReviewRecord')
        with ws.store.connect() as db:
            observed['actual_receipts'] = [{'id': row[0], 'actor_id': row[1], 'data': json.loads(row[2])}
                for row in db.execute('SELECT id, actor_id, data FROM content_observations')]
        save_evidence(request, ws, observed, driver)


async def test_current_bounded_local_review_same_snapshot_reuse_control(ws, request):
    """Exact same-snapshot control; does not alter the cross-snapshot red cases."""
    from test_bounded_review import review_call as bounded_call
    cs, _, refs, snapshot, members = seed(ws)
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    old_call = bounded_call(snapshot, refs, 'same-snapshot-old', reads=[source])
    old_call['args']['review_requirements'][0]['content_check_scopes'] = [
        {'requirement_index': 0, 'node_ref': refs['claim'], 'kind': 'local_body'}]
    historical_model = Model()
    with delegated_task(ws, 'coordinator', old_call) as (_, old_actor):
        old_review = (await perform_review(ws, old_actor, historical_model,
            'same-snapshot-check', ['rule-comparison']))['review_ref']
        assert reconcile(cs, old_actor.task_id)['execution_complete'] is True
    original = deepcopy(cs.read(old_review))
    call = deepcopy(old_call)
    call['id'] = 'same-snapshot-current'
    call['args'].pop('supervision_plugin', None)
    observed = {'case': 'bounded-local-same-snapshot-control', 'old_review': original,
        'snapshot': snapshot, 'historical_checker_inputs': historical_model.calls, 'assets': []}
    activate(ws)

    def child(messages):
        value = result_value(tool_reply(messages, 'same-reuse'))
        observed['reuse_public'] = value
        assert value['ok'] is True, value
        assert len(cs.list_objects('ReviewRecord')) == 1
        return AIMessage(content=json.dumps(value))

    def parent(messages):
        observed['parent_return'] = result_value(tool_reply(messages, 'same-snapshot-current'))
        return AIMessage(content='Exact same-snapshot reuse observed; no new model judgment.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), parent],
        reviewer=[action('confirm_review_reuse', 'same-reuse', operation_id='same-snapshot-reuse',
            review_ref=old_review, new_snapshot=snapshot, reason='Exact same inputs and snapshot.', item_indexes=[0]), child])
    try:
        observed['runtime_result'] = await run_report(ws, driver)
        assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
        assert cs.read(old_review) == original and len(historical_model.calls) == 1
        assert not any(role == 'text_tool' for role, _, _ in driver.calls)
    finally:
        observed['records_after'] = cs.list_objects('ReviewRecord')
        save_evidence(request, ws, observed, driver)
