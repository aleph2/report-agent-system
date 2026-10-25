"""Default-list equivalence through the current bounded Reviewer save path.

Fake agents select the real task/checker tools. They never call internal review
save APIs, change the execution mode or submit a fabricated host acceptance.
"""
from copy import deepcopy
import json

from langchain_core.messages import AIMessage
import pytest

from duty_probe_agent_decisions import dump
from report_agent.bounded_review import Assessments
from report_agent.deep_runtime import run_report
from report_agent.task_context import exact_task_context
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import action
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_duty_contract_default_siblings import evidence_folder, finish_capture, retain, schema_errors
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('presence', ['explicit-empty', 'omit-default-empty'])
async def test_native_bounded_reviewer_default_survives_typed_submission(ws, tmp_path, request, presence):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    source = next(r for r in members if r['type'] == 'SourceArtifact')
    task_args = deepcopy(review_call(snapshot, refs, reads=[source])['args'])
    output = {'items': [{
        'scope_id': 'rule-comparison', 'checked_requirement_indexes': [0],
        'execution_state': 'completed', 'verdict': 'not_satisfied',
        'observations': [
            {'evidence_index': 0, 'locator': 'claim', 'observation': 'Adopted B, value 70.'},
            {'evidence_index': 1, 'locator': 'source', 'observation': 'B permits 75–100.'}],
        'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
            'result': '70 is outside 75–100.', 'observation_indexes': [0, 1], 'remaining': ''}],
        'coverage': {'checked': ['Compared the original interval and adopted value.'],
            'unchecked': [], 'blocked': [], 'basis': 'Original source and claim.'},
        'reason': '70 outside the supplied interval.', 'findings': []}]}
    if presence == 'omit-default-empty':
        del output['items'][0]['findings']
    raw_response = json.dumps(output)
    model, folder = Model(raw_response), evidence_folder(tmp_path, request)
    check_args = {'operation_id': 'review-default', 'scope_ids': ['rule-comparison'],
                  'source_selections': [], 'content_selections': []}
    capture = {'presence': presence, 'raw_fake_response': raw_response,
               'task_arguments': task_args, 'checker_arguments': check_args}
    final_text = 'The assigned comparison is complete and not satisfied; no whole-report acceptance claimed.'

    def after_check(messages):
        value = retain(folder, capture, messages, 'review-default')
        capture['public_review'] = deepcopy(value)
        capture['server_context'] = exact_task_context(ws, 'reviewer')
        return AIMessage(content=final_text)

    def parent_finish(messages):
        retain(folder, capture, messages, 'review-task', structured=False)
        return AIMessage(content='Preserve the scoped adverse judgment; no report acceptance.')

    driver = Driver(coordinator=[action('task', 'review-task', **task_args), parent_finish],
                    reviewer=[action('perform_assigned_review', 'review-default', **check_args), after_check])
    try:
        result = await run_report(ws, lambda role: model if role == 'text_tool' else driver(role))
        capture['run_result'] = result
        packet = json.loads(model.calls[0][1][1])
        task_schema = next(t['parameters'] for t in driver.bindings['coordinator'][-1] if t['name'] == 'task')
        check_schema = next(t['parameters'] for t in driver.bindings['reviewer'][-1]
                            if t['name'] == 'perform_assigned_review')
        capture.update(independent_packet=packet, task_schema=task_schema, checker_schema=check_schema,
            task_schema_errors=schema_errors(task_schema, task_args),
            checker_schema_errors=schema_errors(check_schema, check_args),
            output_schema_errors=schema_errors(packet['output_schema'], output),
            normalized_output=Assessments.model_validate(output).model_dump())
        task, = cs.list_objects('DelegatedTask')
        capture['supervision'] = reconcile(cs, task['ref']['id'])
    except Exception as exc:
        capture['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture['independent_calls'] = model.calls
        finish_capture(folder, capture, driver, cs, originals, ws)
        try:
            with ws.store.connect() as db:
                capture['observation_receipts'] = {
                    identity: {'actor_id': actor, 'data': json.loads(data)}
                    for identity, actor, data in db.execute('SELECT id,actor_id,data FROM content_observations')}
        except Exception as exc:
            capture['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            dump(folder / 'capture.json', capture)

    assert capture['run_result']['last_error'] is None
    assert capture['originals_unchanged'] and len(model.calls) == 1
    assert len([c for c in driver.calls if c[0] == 'reviewer']) == 2
    assert len([c for c in driver.calls if c[0] == 'coordinator']) == 2
    assert capture['task_schema_errors'] == capture['checker_schema_errors'] == capture['output_schema_errors'] == []
    assert ws.store.manifest['review_execution_mode'] == 'bounded-tool-v1'
    task, = cs.list_objects('DelegatedTask')
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'reviewer' and task['payload']['review_snapshot_ref'] == snapshot
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    context = capture['server_context']
    assert context['role'] == 'reviewer' and context['actor_id'] == 'content:reviewer:' + task['ref']['id']
    assert context['assignment'] == task['payload']
    packet = capture['independent_packet']
    assert packet['assignment'] == {'review_snapshot_ref': snapshot,
                                    'review_requirements': task['payload']['review_requirements']}
    assert packet['task_id'] == task['ref']['id']
    assert packet['criteria'] == [cs.read(refs['k'])]
    assert packet['evidence'][0]['object']['ref'] == refs['claim']
    assert packet['evidence'][0]['object']['payload'] == cs.read(refs['claim'])['payload']
    assert packet['evidence'][1]['object']['ref'] == source
    assert packet['evidence'][1]['object']['payload'] == cs.read(source)['payload']
    required = packet['assignment']['review_requirements'][0]['required_materials'][0]['refs']
    assert required == [refs['claim'], source]
    record, = cs.list_objects('ReviewRecord')
    public = capture['public_review']
    assert public['review_ref'] == record['ref']
    assert record['owner_id'] == record['created_by'] == context['actor_id']
    assert record['task_id'] == task['ref']['id'] and record['payload']['snapshot_ref'] == snapshot
    assert record['payload']['items'] == public['items']
    saved, = record['payload']['items']
    parsed, = capture['normalized_output']['items']
    for field in ['scope_id', 'checked_requirement_indexes', 'execution_state', 'verdict',
                  'check_results', 'outside_assignment_notes', 'coverage', 'reason', 'findings']:
        assert saved[field] == parsed[field]
    assert saved['findings'] == [] and saved['verdict'] == 'not_satisfied'
    assert saved['target_ref'] == refs['claim'] and saved['criterion_ref'] == refs['k']
    assert len(saved['observations']) == len(parsed['observations']) == 2
    for actual, raw in zip(saved['observations'], parsed['observations'], strict=True):
        for field in ['locator', 'observation', 'limitations']:
            assert actual[field] == raw[field]
        assert actual['receipt_id']
        receipt = capture['observation_receipts'][actual['receipt_id']]
        assert receipt['actor_id'] == context['actor_id']
        assert receipt['data']['evidence_index'] == raw['evidence_index']
        assert receipt['data']['analysis_operation'] == public['analysis_operation']
        assert receipt['data']['objects'] == [packet['evidence'][raw['evidence_index']]['object']]
    assert capture['supervision']['execution_complete'] is True and capture['supervision']['remaining'] == []
    parent = capture['observed']['review-task']['message']
    assert parent['status'] == 'success' and parent['content'].startswith(final_text)
    assert cs.list_objects('ExportArtifact') == []
