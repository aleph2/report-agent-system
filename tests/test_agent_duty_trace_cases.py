"""Trace-derived decisions through native runtime; scripted actions, real I/O.

Historical I01/I02/I03 motivate the contrasts. Current model path error comes
from contract-live-wave2/coordinator. No claim of model-chosen recovery.
"""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.deep_runtime import run_report
from test_agent_result_delivery import packet
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def tool_reply(messages, call_id):
    return next(m for m in reversed(messages)
                if isinstance(m, ToolMessage) and m.tool_call_id == call_id)


def result_value(message):
    value = packet(message)
    return value.get('metadata', value)


def action(name, call_id, **args):
    message = invoke(name, **args)
    message.tool_calls[0]['id'] = call_id
    return message


@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('misuse', ['missing_field', 'source_as_requirement'])
async def test_coordinator_criterion_error_is_visible_and_no_partial_batch_is_saved(ws, managed, misuse, request):
    cs, _, refs, snapshot, members = seed(ws)
    if managed:
        activate(ws)
    requirement = next(ref for ref in members if ref['type'] == 'Requirement')
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    before = cs.list_objects('Criterion')
    payload = {'requirement_refs': [requirement], 'purpose': 'Compare selected original table',
               'scope': 'Synthetic class B', 'expected_outcome': 'Retain both columns and the condition.',
               'evidence_expectation': 'The complete selected source table and its footnote.',
               'allowed_limits': 'Actual weathering class remains unresolved.'}
    valid = {'client_key': 'new', 'type': 'Criterion', 'payload': payload}
    invalid = deepcopy(valid)
    invalid['client_key'] = 'invalid'
    if misuse == 'missing_field':
        del invalid['payload']['evidence_expectation']
    else:
        invalid['payload']['requirement_refs'] = [source]
    observed = {}

    def correct(messages):
        error = tool_reply(messages, 'criterion-invalid')
        assert error.status == 'error'
        expected = 'evidence_expectation' if misuse == 'missing_field' else 'requirement_refs'
        assert expected in str(error.content)
        assert cs.list_objects('Criterion') == before
        with ws.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_operations WHERE operation_id=?',
                              ('criterion-trace',)).fetchone()[0] == 0
        observed['rejection'] = error.content
        # Input validation occurred before the business operation was registered.
        return action('commit_objects', 'criterion-corrected', operation_id='criterion-trace', objects=[valid])

    def finish(messages):
        value = result_value(tool_reply(messages, 'criterion-corrected'))
        assert value['ok'] is True, value
        stored = cs.read(value['result']['refs']['new'])
        assert stored['payload'] == payload
        observed['saved_ref'] = stored['ref']
        return AIMessage(content='Criterion saved. No report acceptance claimed.')

    driver = Driver(coordinator=[action('commit_objects', 'criterion-invalid',
                    operation_id='criterion-trace', objects=[valid, invalid]), correct, finish])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    schema = next(t['parameters'] for t in driver.bindings['coordinator'][0] if t['name'] == 'commit_objects')
    branch = next(b for b in schema['properties']['objects']['items']['oneOf']
                  if b['properties']['type']['const'] == 'Criterion')
    shape = branch['properties']['payload']
    assert set(shape['required']) == set(payload)
    assert shape['properties']['requirement_refs']['items']['properties']['type']['const'] == 'Requirement'
    assert len(cs.list_objects('Criterion')) == len(before) + 1
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'TC01', 'misuse': misuse, 'managed': managed, 'observed': observed,
        'scripted_correction': True, 'paid_calls': 0})))


@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('misuse', ['paragraph_in_heading', 'table_as_structure', 'empty_body'])
async def test_writer_structure_decision_and_substantive_body_remain_separate(ws, managed, misuse, request):
    cs, _, _, _, _ = seed(ws)
    if managed:
        activate(ws)
    initial = cs.list_objects('ContentNode')
    heading = {'kind': 'chapter', 'body': {'text': 'Source evidence'}, 'qualifiers': {}, 'claim_kind': 'structure'}
    invalid = deepcopy(heading)
    if misuse == 'paragraph_in_heading':
        invalid['body']['text'] += '\nThe synthetic rock class has been established.'
    elif misuse == 'table_as_structure':
        invalid.update(kind='table', body={'columns': ['Class'], 'rows': [['Established']]})
    else:
        invalid['body'] = {}
    observed = {}

    def reject_then_read(messages):
        error = tool_reply(messages, 'structure-invalid')
        value = result_value(error)
        assert value['ok'] is False, value
        assert value['code'] == 'SUBSTANTIVE_CONTENT_REQUIRES_TEXT_WORK', value
        assert cs.list_objects('ContentNode') == initial
        observed['rejection'] = value
        # Known refusal is retained. This is a distinct, explicitly valid action.
        return action('commit_objects', 'structure-valid', operation_id='valid-heading', objects=[
            {'client_key': 'heading', 'type': 'ContentNode', 'payload': heading}])

    def finish(messages):
        value = result_value(tool_reply(messages, 'structure-valid'))
        assert value['ok'] is True, value
        node = cs.read(value['result']['refs']['heading'])
        assert node['payload'] == heading
        assert node['owner_id'].startswith('content:writer:')
        observed['saved'] = node
        return AIMessage(content='Structural heading saved; no substantive report generated.')

    driver = Driver(coordinator=[invoke('task', subagent_type='writer',
                    description='Organize the selected source evidence. Preserve unresolved conditions.'),
                    AIMessage(content='Structure-only outcome received.')],
                    writer=[action('commit_objects', 'structure-invalid', operation_id='invalid-structure', objects=[
                        {'client_key': 'would_be_valid', 'type': 'ContentNode', 'payload': heading},
                        {'client_key': 'invalid', 'type': 'ContentNode', 'payload': invalid}]),
                        reject_then_read, finish])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(cs.list_objects('ContentNode')) == len(initial) + 1
    # Native assembly constructs tool clients eagerly; only an invocation would
    # violate this structure-only scenario's zero-text-work expectation.
    assert not any(role == 'text_tool' for role, _, _ in driver.calls)
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'TC02', 'misuse': misuse, 'managed': managed, 'observed': observed,
        'scripted_correction': True, 'paid_calls': 0})))


async def test_real_coordinator_missing_path_error_then_explicit_current_state_read(ws, request):
    from report_agent.content_tasks import delegated_task
    from report_agent.decision_state import read_state
    from report_agent.task_context import exact_task_context
    from test_bounded_review import review_call

    cs, _, refs, snapshot, _ = seed(ws)
    # This observed call belongs to the active stateful-tools-v1 configuration.
    # The unmanaged configuration does not register read_decision_state.
    managed = True
    activate(ws)
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)):
        pass  # Assigned scope exists and is genuinely unfinished.
    expected = read_state(ws, 'coordinator', ['review_tasks'])['value']
    observed = {}

    def choose_current(messages):
        value = result_value(tool_reply(messages, 'real-returned-action'))
        assert value['ok'] is False and value['code'] == 'STATE_PATH_NOT_FOUND', value
        current = exact_task_context(ws, 'coordinator')
        assert 'assignment' not in current and current['review_tasks']['tasks']
        if managed:
            system = str([m.content for m in messages if m.type == 'system'])
            assert 'review_tasks' in system
        observed['rejection'] = value
        return action('read_decision_state', 'explicit-current-read', path=['review_tasks'])

    def finish(messages):
        value = result_value(tool_reply(messages, 'explicit-current-read'))
        assert value['value'] == expected, value
        assert value['semantic_acceptance'] is False
        assert value['value']['tasks'][0]['execution_complete'] is False
        assert value['value']['tasks'][0]['remaining']
        observed['recovered'] = value
        return AIMessage(content='Assigned checks remain unfinished.')

    driver = Driver(coordinator=[action('read_decision_state', 'real-returned-action', path=['assignment']),
                                 choose_current, finish])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'real-coordinator-state-path', 'managed': managed, 'observed': observed,
        'source': '.analysis/agent-duty-validation-20261018/contract-live-wave2/coordinator/result.json',
        'scripted_correction': True, 'paid_calls': 0})))


@pytest.mark.parametrize('managed', [False, True])
async def test_writer_evidence_source_pool_requires_version_binding_before_text_service(ws, managed, request):
    from test_bounded_review import Model

    cs, _, _, snapshot, members = seed(ws)
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    if managed:
        activate(ws)
    before = cs.list_objects('Evidence')
    expected = {'source_refs': [source], 'locator': 'selected block 0',
                'excerpt': 'Class B permits 75 to 100.'}
    service = Model(json.dumps(expected))
    observed = {}
    args = {'objective': 'Extract the selected original rule with its exact source version.',
            'object_type': 'Evidence', 'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 1}]}

    def bind_version(messages):
        value = result_value(tool_reply(messages, 'unbound-evidence'))
        assert value['ok'] is False and value['code'] == 'TEXT_WORK_EVIDENCE_SOURCE_POOL_EMPTY', value
        assert not service.calls
        assert cs.list_objects('Evidence') == before
        observed['unbound'] = value
        return action('process_report_content', 'bound-evidence', operation_id='bound-evidence',
                      source_version_refs=[source], **args)

    def adopt(messages):
        value = result_value(tool_reply(messages, 'bound-evidence'))
        assert value['semantic_correctness_verified'] is False
        assert len(service.calls) == 1
        wire = json.loads(service.calls[0][1][1])
        bindings = [item for item in wire['evidence'] if item['kind'] == 'source_version_binding']
        assert len(bindings) == 1 and bindings[0]['object']['ref'] == source
        selections = [item for item in wire['evidence'] if item['kind'] == 'source_blocks']
        assert len(selections) == 1
        assert selections[0]['selection'] == {'source_id': 's', 'offset': 0, 'limit': 1}
        assert selections[0]['observation']['source']['id'] == 's'
        assert selections[0]['observation']['blocks'] == [{
            'locator': 'manifest text; chars 1-26', 'ordinal': 0, 'text': expected['excerpt']}]
        if managed:
            assert value['outputs']['complete'] is True
            assert value['outputs']['total'] == 1
            delivered = value['outputs']['entries'][0]
            assert delivered['body_deferred'] is False
        else:
            delivered = value['payload']
        for key, expected_value in expected.items():
            assert delivered[key] == expected_value
        observed['candidate'] = value
        return action('commit_objects', 'adopt-evidence', operation_id='adopt-evidence', objects=[
            {'client_key': 'e', 'type': 'Evidence', 'text_work_id': value['text_work_id']}])

    def finish(messages):
        value = result_value(tool_reply(messages, 'adopt-evidence'))
        assert value['ok'] is True
        saved = cs.read(value['result']['refs']['e'])
        for key, expected_value in expected.items():
            assert saved['payload'][key] == expected_value
        assert saved['owner_id'].startswith('content:writer:')
        observed['saved_ref'] = saved['ref']
        return AIMessage(content='Literal evidence saved; no engineering judgment claimed.')

    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description=args['objective']),
                                 AIMessage(content='Selected literal evidence received.')],
                    writer=[action('process_report_content', 'unbound-evidence', operation_id='unbound-evidence', **args),
                            bind_version, adopt, finish])
    result = await run_report(ws, lambda role: service if role == 'text_tool' else driver(role))
    assert result['last_error'] is None, result
    assert len(service.calls) == 1 and len(cs.list_objects('Evidence')) == len(before) + 1
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'TC03', 'managed': managed, 'observed': observed,
        'scripted_correction': True, 'paid_calls': 0})))


def test_optional_optimizer_missing_dependency_has_terminal_evidence_without_execution(tmp_path, request):
    import importlib.util
    from report_agent.learning_evaluation import run_experiment
    from test_learning_evaluation import Program, data, metric

    if importlib.util.find_spec('dspy') is not None:
        pytest.skip('This environment has the optional engine; missing-dependency path not applicable.')
    root = tmp_path / 'optional-engine-diagnostic'

    class NoExecution(Program):
        def __call__(self, **inputs):
            pytest.fail('A missing optimizer dependency must not execute the student or holdout.')

    with pytest.raises(ModuleNotFoundError) as failure:
        run_experiment(NoExecution('Synthetic baseline'), *data(), metric, None,
                       output_directory=root, max_metric_calls=4,
                       evaluator_version='synthetic-contract-v1', model_identity='never-invoked')
    assert failure.value.name == 'dspy'
    saved = json.loads((root / 'experiment.json').read_text())
    assert saved['state'] == 'failed' and saved['error_type'] == 'ModuleNotFoundError'
    assert saved['automatic_release'] is False
    assert saved['baseline'] == {'answer': 'Synthetic baseline'}
    assert 'candidate' not in saved and 'holdout' not in saved
    before = (root / 'experiment.json').read_bytes()
    with pytest.raises(FileExistsError):
        run_experiment(NoExecution('Synthetic baseline'), *data(), metric, None,
                       output_directory=root, max_metric_calls=4,
                       evaluator_version='synthetic-contract-v1', model_identity='never-invoked')
    assert (root / 'experiment.json').read_bytes() == before
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'E7-dependency-negative', 'terminal_record': saved,
        'positive_gepa_path': 'environment-blocked', 'paid_calls': 0,
        'authorization_enforcement_tested': False})))
