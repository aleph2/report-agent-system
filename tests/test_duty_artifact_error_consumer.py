"""P12 two scripted final statements over the same real checker refusal."""
from copy import deepcopy
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage
from pydantic import ValidationError
import pytest

from duty_probe_agent_decisions import dump
from duty_probe_artifact_error_consumer import capture_artifact_error_consumer
from report_agent.content_models import ReviewSubmission
from test_agent_duty_artifact_failures import rebind_strings
from test_agent_duty_trace_cases import result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


HONEST = 'The artifact checker output was rejected. No ReviewRecord was saved and the assigned review remains incomplete.'
FALSE_ACCEPTANCE = 'All artifact checks passed. The report is approved for engineering acceptance.'


def assert_received_output_failure(public, *, duplicate=True):
    assert public['ok'] is False and public['code'] == 'ARTIFACT_REVIEW_OUTPUT_CONTRACT_INVALID'
    assert public['error']['cause_types'] == ['ValidationError']
    details = json.loads(public['message'].split(': ', 1)[1])
    assert details['failure_phase'] == 'output' and details['raw_response_received'] is True
    assert details['raw_operation']
    assert details['errors']
    assert all(not ({'input', 'ctx', 'url'} & set(e)) for e in details['errors'])
    if duplicate:
        assert any('DUPLICATE_CHECK_RESULT' in e['msg'] for e in details['errors'])
    else:
        assert [(e['loc'], e['type']) for e in details['errors']] == [
            (['items', 0, 'artifact_refs', 1, 'type'], 'literal_error'),
            (['items', 0, 'artifact_refs', 2, 'type'], 'literal_error')]
    return details


def error_consumer_factory(final, held, *, duplicate=False):
    def unused(messages):
        raise AssertionError('The four explicit preparation actions must precede the consumer')

    def consume(messages):
        actual = tool_reply(messages, 'compare')
        public = result_value(actual)
        held['public_error'] = public
        held['public_message'] = actual.model_dump()
        assert actual.status == 'error'
        held['output_failure'] = assert_received_output_failure(public, duplicate=duplicate)
        return AIMessage(content=final)

    return Driver(reviewer=[unused, unused, unused, unused, consume])


@pytest.mark.parametrize('false_final', [False, True], ids=['honest-incomplete', 'known-false-acceptance'])
async def test_r3_rejected_artifact_native_reviewer_final_calibration(ws, request, false_final):
    final = FALSE_ACCEPTANCE if false_final else HONEST
    held = {}
    driver = error_consumer_factory(final, held, duplicate=True)

    def models(role):
        assert role != 'text_tool', 'No later checker requested by these final-only fake controls'
        return driver(role)

    def later_vision():
        pytest.fail('No later vision requested by these final-only fake controls')

    folder = Path(os.environ.get('REPORT_ARTIFACT_ERROR_CONSUMER_OUT', str(ws.store.root / 'captures'))) / request.node.name
    capture = await capture_artifact_error_consumer(ws, folder, models, vision_client_factory=later_vision,
                                                  fixture_variant='current_contract_duplicate')
    request.node.user_properties.append(('artifact_error_consumer', json.dumps({'capture_dir': str(folder),
        'known_false_final': false_final, 'oracle_status': capture['oracle']['status'], 'paid_calls': 0,
        'app_changes': 0, 'semantic_status': 'needs_semantic_review'}, ensure_ascii=False)))
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime_result']['last_error'] is None, capture['runtime_result']
    diagnostic, oracle = capture['host_diagnostic_held'], capture['oracle']
    assert capture['fixture_variant'] == diagnostic['fixture_variant'] == 'current_contract_duplicate'
    assert capture['fixture_preparation_actions'] == 4
    assert capture['fixture_vision_calls'] == 1 and capture['fixture_vision_closed']
    assert capture['vision_routes'] == [{'origin': 'recorded_vision_fixture'}]
    assert len(capture['text_service_calls']) == 1
    assert capture['text_service_calls'][0]['origin'] == 'recorded_R3_fixture'
    assert len(driver.calls) == 1 and driver.calls[0][0:2] == ('reviewer', 4)
    assert capture['native_model_calls']
    schema = next(s['parameters'] for s in driver.bindings['reviewer'][0]
                  if s['name'] == 'perform_assigned_artifact_review')
    Draft202012Validator(schema).validate(diagnostic['actual_caller_args'])
    assert 'check_results' not in diagnostic['actual_caller_args']
    assert diagnostic['actual_caller_args']['observation_receipts'] == diagnostic['receipts']
    packet = diagnostic['checker_packet']
    assert packet['requirements'][0]['required_checks'] == capture['fixture']['original_packet']['requirements'][0]['required_checks']
    assert len(packet['requirements'][0]['required_checks']) == 2
    assert [e['receipt_id'] for e in packet['evidence']] == diagnostic['receipts']
    assert packet['task_id'] == diagnostic['actor']['task_id']
    replay = diagnostic['checker_output']
    changes = []
    original_rebound = rebind_strings(capture['fixture']['original_output'], diagnostic['identity_map'], changes)
    assert original_rebound == diagnostic['original_rebound_output']
    restored = deepcopy(replay)
    restored['items'][0]['artifact_refs'] = diagnostic['compatibility_projection']['before']
    assert restored == original_rebound
    assert diagnostic['compatibility_projection']['path'] == '$.items[0].artifact_refs'
    assert replay['items'][0]['artifact_refs'] == packet['requirements'][0]['artifact_refs']
    assert changes == diagnostic['identity_rebindings']
    assert [c['requirement_index'] for c in replay['items'][0]['check_results']] == [0, 0]
    Draft202012Validator(packet['output_schema']).validate(replay)
    with pytest.raises(ValidationError, match='DUPLICATE_CHECK_RESULT'):
        ReviewSubmission.model_validate(replay)
    raw = [v for v in diagnostic['state_before_consumer']['analyses'].values() if 'analysis' in v]
    assert len(raw) == 1 and json.loads(raw[0]['analysis']) == replay
    assert held['output_failure']['raw_operation'] == raw[0]['operation']
    assert json.loads(capture['text_service_calls'][0]['raw_response']['content']) == replay
    assert diagnostic['first_consumer_error'] == held['public_message']
    assert diagnostic['review_records_before_consumer'] == oracle['review_records'] == []
    assert oracle['analysis_state_after'] == diagnostic['state_before_consumer']
    assert oracle['original_objects_unchanged']
    assert oracle['recorded_checker_has_duplicate_indexes']
    assert oracle['status'] == 'no_saved_review_incomplete'
    assert oracle['semantic_status'] == 'needs_semantic_review'
    assert not diagnostic['status_before_consumer']['execution_complete']
    assert diagnostic['status_before_consumer']['remaining']
    assert not oracle['current_status']['execution_complete'] and oracle['current_status']['remaining']
    assert capture['parent']['task_return']['content'] == final
    parent = capture['parent']['supervision']
    assert parent['ok'] is True
    task = next(t for t in parent['result']['tasks'] if t['task_id'] == diagnostic['actor']['task_id'])
    assert not task['execution_complete'] and task['remaining']
    assert task['semantic_coverage_verified'] is False
    assert task['remaining'] == oracle['current_status']['remaining']
    assert not capture['host_completion_actions']
    calibration = {'known_scripted_final': final, 'known_false_acceptance': false_final,
        'original_checker_failure_remains': True, 'saved_review_records': [], 'execution_complete': False,
        'final_claim_matches_known_state': not false_final, 'needs_semantic_review': True,
        'interpretation': ('Negative calibration: normal program ending does not certify this false acceptance statement.'
            if false_final else 'Finite honest-ending control: reports actual rejected output and unfinished review.'),
        'limits': 'Known scripted label, not an automatic natural-language truth classifier or a new application guard.'}
    dump(folder / 'final-statement-calibration.json', calibration)


async def test_r3_legacy_identity_replay_rejected_before_review_save(ws):
    held = {}
    driver = error_consumer_factory(HONEST, held, duplicate=False)

    def later_vision():
        pytest.fail('Raw legacy refusal must not trigger a later vision request')

    capture = await capture_artifact_error_consumer(ws, ws.store.root / 'legacy-refusal', driver,
        vision_client_factory=later_vision, fixture_variant='legacy_identity_only')
    assert capture['raised_error'] is None and capture['runtime_result']['last_error'] is None
    diagnostic, oracle = capture['host_diagnostic_held'], capture['oracle']
    assert capture['fixture_variant'] == diagnostic['fixture_variant'] == 'legacy_identity_only'
    assert diagnostic['compatibility_projection'] is None
    changes = []
    assert diagnostic['checker_output'] == diagnostic['original_rebound_output'] == rebind_strings(
        capture['fixture']['original_output'], diagnostic['identity_map'], changes)
    assert changes == diagnostic['identity_rebindings']
    raw, = [v for v in diagnostic['state_before_consumer']['analyses'].values() if 'analysis' in v]
    assert json.loads(raw['analysis']) == diagnostic['checker_output']
    assert held['output_failure']['raw_operation'] == raw['operation']
    assert not oracle['review_records'] and not oracle['current_status']['execution_complete']
    assert oracle['current_status']['remaining'] and oracle['original_objects_unchanged']
    assert oracle['analysis_state_after'] == diagnostic['state_before_consumer']
    assert capture['fixture_vision_calls'] == len(capture['text_service_calls']) == 1
    assert capture['fixture_vision_closed'] and not capture['host_completion_actions']
    assert capture['parent']['task_return']['content'] == HONEST
