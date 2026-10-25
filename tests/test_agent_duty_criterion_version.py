"""Exact task-bound Criterion versions through native bounded review, offline.

Sibling hypothesis inspired by dependency/reuse findings. These scripted native
paths test version transport and persistence, not a real model's judgments.
"""
from copy import deepcopy
import json

from langchain_core.messages import AIMessage
import pytest

from report_agent.bounded_review import perform_review
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.task_supervision import reconcile
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


FIELDS = {'requirement_refs', 'purpose', 'scope', 'expected_outcome',
          'evidence_expectation', 'allowed_limits'}


@pytest.mark.parametrize('head_version,task_version', [(1, 1), (2, 1), (2, 2)],
                         ids=['head-v1-task-v1', 'head-v2-task-v1', 'head-v2-task-v2'])
async def test_native_review_keeps_exact_assigned_criterion_version(
        ws, request, head_version, task_version):
    cs, owner, refs, snapshot_v1, members = seed(ws)
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    criterion_v1 = deepcopy(cs.read(refs['k']))
    assert set(criterion_v1['payload']) == FIELDS
    original_sources = deepcopy(ws.store.manifest['sources'])
    protected = {json.dumps(ref, sort_keys=True): deepcopy(cs.read(ref)) for ref in [snapshot_v1, *members]}
    historical_call = review_call(snapshot_v1, refs, 'criterion-history', reads=[source])
    historical_model = Model()
    with delegated_task(ws, 'coordinator', historical_call) as (_, historical_actor):
        historical_ref = (await perform_review(ws, historical_actor, historical_model,
            'criterion-history-check', ['rule-comparison']))['review_ref']
        assert reconcile(cs, historical_actor.task_id)['execution_complete'] is True
    historical_review = deepcopy(cs.read(historical_ref))
    assert historical_review['payload']['criteria_refs'] == [refs['k']]
    assert historical_review['payload']['items'][0]['criterion_ref'] == refs['k']
    assert len(historical_model.calls) == 1

    criterion_v2 = None
    if head_version == 2:
        payload_v2 = deepcopy(criterion_v1['payload'])
        payload_v2['allowed_limits'] = (
            'CRITERION-V2-ONLY: preserve unresolved actual class and explicitly distinguish scoped judgment from engineering acceptance.')
        created = cs.commit(owner, 'criterion-version-two', [{'client_key': 'criterion', 'type': 'Criterion',
            'previous_ref': refs['k'], 'payload': payload_v2}])['result']['refs']['criterion']
        assert created == {**refs['k'], 'version': 2}
        criterion_v2 = deepcopy(cs.read(created))
        assert criterion_v2['owner_id'] == criterion_v1['owner_id'] == owner.id
        assert criterion_v2['previous_ref'] == refs['k']
        assert criterion_v2['payload'] == payload_v2
    with ws.store.connect() as db:
        actual_head = db.execute('SELECT version FROM content_heads WHERE type=? AND id=?',
                                ('Criterion', refs['k']['id'])).fetchone()[0]
    assert actual_head == head_version
    selected = criterion_v1 if task_version == 1 else criterion_v2
    selected_ref = selected['ref']
    snapshot = snapshot_v1
    if task_version == 2:
        snapshot = cs.freeze(owner, 'criterion-version-two-snapshot', refs['root'],
            [selected_ref if ref == refs['k'] else ref for ref in members])['result']['snapshot_ref']
    assert cs.read(snapshot)['payload']['criteria_refs'] == [selected_ref]
    current_refs = {**refs, 'k': selected_ref}
    current_call = review_call(snapshot, current_refs, 'criterion-current', reads=[source])
    current_call['args'].pop('supervision_plugin', None)
    bound_requirement = deepcopy(current_call['args']['review_requirements'][0])
    assert bound_requirement['criterion_ref'] == selected_ref
    observed = {'case': 'exact-assigned-criterion-version', 'head_version': head_version,
        'task_version': task_version, 'current_call': deepcopy(current_call),
        'criterion_v1': criterion_v1, 'criterion_v2': criterion_v2,
        'expected_selected_criterion': deepcopy(selected), 'historical_review': historical_review,
        'historical_checker_inputs': historical_model.calls, 'current_snapshot': snapshot,
        'limits': 'Exact version transport and saved outcomes only; fake decisions do not prove semantic correctness.',
        'assets': []}
    activate(ws)

    def checker(messages):
        packet = json.loads(messages[-1].content)
        observed['checker_input'] = packet
        assert packet['assignment']['review_snapshot_ref'] == snapshot
        assigned = packet['assignment']['review_requirements'][0]
        assert assigned['criterion_ref'] == selected_ref
        assert assigned['required_checks'] == bound_requirement['required_checks']
        assert len(packet['criteria']) == 1
        actual = packet['criteria'][0]
        assert actual['ref'] == selected_ref
        assert set(actual['payload']) == FIELDS
        for field in sorted(FIELDS):
            assert actual['payload'][field] == selected['payload'][field], field
        assert actual == selected
        if head_version == 2 and task_version == 1:
            assert actual['payload']['allowed_limits'] != criterion_v2['payload']['allowed_limits']
            assert 'CRITERION-V2-ONLY' not in actual['payload']['allowed_limits']
        elif task_version == 2:
            assert 'CRITERION-V2-ONLY' in actual['payload']['allowed_limits']
        evidence = packet['evidence']
        indexes = []
        for ref in (refs['claim'], source):
            matches = [i for i, entry in enumerate(evidence)
                       if entry.get('object', {}).get('ref') == ref]
            assert len(matches) == 1
            assert evidence[matches[0]]['object'] == cs.read(ref)
            indexes.extend(matches)
        raw = {'items': [{'scope_id': 'rule-comparison', 'checked_requirement_indexes': [0],
            'execution_state': 'completed', 'verdict': 'not_satisfied',
            'observations': [
                {'evidence_index': indexes[0], 'locator': 'claim', 'observation': 'The exact saved claim adopts class B and value 70.'},
                {'evidence_index': indexes[1], 'locator': 'original rule', 'observation': 'The original class B interval is 75 to 100.'}],
            'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
                'result': '70 is outside the supplied interval; applied explicitly assigned Criterion v' + str(task_version) + '.',
                'observation_indexes': [0, 1], 'remaining': ''}],
            'coverage': {'checked': ['Compare the saved claim with the original rule.'], 'unchecked': [],
                         'blocked': [], 'basis': 'Exact task criterion and source versions.'},
            'reason': 'Scoped fake check preserves the conflict and assigned criterion version.', 'findings': []}]}
        observed['checker_raw'] = raw
        return AIMessage(content=json.dumps(raw))

    def reviewer_return(messages):
        public = result_value(tool_reply(messages, 'criterion-check'))
        observed['reviewer_public'] = public
        record = cs.read(public['review_ref'])
        observed['current_review'] = record
        assert record['payload']['snapshot_ref'] == snapshot
        assert record['payload']['criteria_refs'] == [selected_ref]
        assert record['payload']['items'][0]['criterion_ref'] == selected_ref
        assert public['items'] == record['payload']['items']
        item = public['items'][0]
        for field in ('execution_state', 'verdict', 'check_results', 'coverage', 'reason', 'findings'):
            assert item[field] == observed['checker_raw']['items'][0][field]
        assert [entry['observation'] for entry in item['observations']] == [
            entry['observation'] for entry in observed['checker_raw']['items'][0]['observations']]
        task_id = record['task_id']
        assert task_id != historical_actor.task_id
        assert record['owner_id'] == 'content:reviewer:' + task_id
        status = reconcile(cs, task_id)
        observed['current_status'] = status
        assert status['execution_complete'] is True and status['remaining'] == []
        assert status['requirements'][0]['requirement']['criterion_ref'] == selected_ref
        assert status['requirements'][0]['verdict'] == 'not_satisfied'
        return AIMessage(content=json.dumps({'review': public, 'current_task_status': status}))

    def parent(messages):
        public = result_value(tool_reply(messages, 'criterion-current'))
        observed['parent_public'] = public
        assert public['review'] == observed['reviewer_public']
        assert public['current_task_status'] == observed['current_status']
        assert public['review']['items'][0]['criterion_ref'] == selected_ref
        assert public['current_task_status']['requirements'][0]['requirement']['criterion_ref'] == selected_ref
        return action('read_task_supervision', 'criterion-parent-status')

    def parent_finish(messages):
        public = result_value(tool_reply(messages, 'criterion-parent-status'))
        observed['parent_supervision'] = public
        assert public['ok'] is True
        task = next(t for t in public['result']['tasks'] if t['task_id'] == observed['current_review']['task_id'])
        assert task['execution_complete'] is True and task['semantic_coverage_verified'] is False
        assert task['requirements'][0]['requirement']['criterion_ref'] == selected_ref
        assert task['requirements'][0]['review_ref'] == observed['current_review']['ref']
        return AIMessage(content='Exact assigned Criterion version retained; no engineering acceptance.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[current_call]), parent, parent_finish],
        reviewer=[action('perform_assigned_review', 'criterion-check', operation_id='criterion-current-check',
            scope_ids=['rule-comparison'], source_selections=[], content_selections=[]), reviewer_return],
        text_tool=[checker])
    try:
        observed['runtime_result'] = await run_report(ws, driver)
        assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
        assert 'parent_supervision' in observed
        assert sum(role == 'text_tool' for role, _, _ in driver.calls) == 1
        assert len(cs.list_objects('ReviewRecord')) == 2
        assert cs.read(historical_ref) == historical_review
        assert protected == {key: cs.read(json.loads(key)) for key in protected}
        assert criterion_v2 is None or cs.read(criterion_v2['ref']) == criterion_v2
        assert ws.store.manifest['sources'] == original_sources
        observed['historical_records_and_source_unchanged'] = True
    finally:
        observed['records_after'] = cs.list_objects('ReviewRecord')
        with ws.store.connect() as db:
            observed['actual_receipts'] = [{'id': row[0], 'actor_id': row[1], 'data': json.loads(row[2])}
                for row in db.execute('SELECT id, actor_id, data FROM content_observations')]
        save_evidence(request, ws, observed, driver)
