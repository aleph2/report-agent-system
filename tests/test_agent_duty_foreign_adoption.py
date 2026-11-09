"""Native Writer receipt ownership: same candidate body, different task owner.

Only B's selected text_work_id changes at the adoption boundary. Honest scripted
child/parent messages test delivery, not automatic detection of false claims.
"""
from report_agent import report_state
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from report_agent.store import digest
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


EXPECTED = {'kind': 'block', 'body': {'text': 'The selected synthetic rule permits class B values from 75 to 100.'},
            'qualifiers': {'scope': 'Selected synthetic source only; actual site classification is unresolved.'},
            'claim_kind': 'fact'}
FORBIDDEN = 'FORBIDDEN: text work belongs to another task'


@pytest.mark.parametrize('foreign', [False, True], ids=['own-receipt', 'other-task-receipt'])
async def test_writer_adopts_only_own_receipt_and_parent_observes_real_refs(ws, request, foreign):
    folder = Path(os.environ.get('REPORT_FOREIGN_ADOPTION_OUT', str(ws.store.root / 'captures'))) / (
        'foreign' if foreign else 'owned')
    folder.mkdir(parents=True, exist_ok=True)
    cs = ContentStore(ws.store)
    imported = cs.import_inputs(actor_for('coordinator'), 'original-inputs', ['s'])['result']
    originals = deepcopy(cs.list_objects())
    source_ref = imported['source_refs'][0]
    activate(ws)
    producer = Model(json.dumps(EXPECTED))
    held = {'current_writer': 'A', 'receipts': {}, 'receipt_originals': {}, 'public_producer_returns': {},
            'parent_returns': {}, 'adopted_refs': [], 'unresolved': []}
    process_args = {'operation_id': 'produce-identical', 'object_type': 'ContentNode',
                    'objective': 'Describe the selected synthetic rule with its original scope and uncertainty.',
                    'input_refs': [source_ref]}
    dump(folder / 'fixture.json', {'originals': originals, 'process_arguments_for_both': process_args,
                                  'expected_payload': EXPECTED, 'foreign': foreign})

    def start_writer(messages):
        label = held['current_writer']
        from support.task_state_contract import current_task
        description = current_task(messages)['current_invocation']['description']
        assert 'TASK-' + label + ':' in description
        if label == 'B':
            assert 'REFERENCE_RECEIPT=' + held['a_parent_receipt'] in description
        return action('process_report_content', 'produce', **deepcopy(process_args))

    def select_adoption(messages):
        label = held['current_writer']
        raw = tool_reply(messages, 'produce')
        value = result_value(raw)
        held['public_producer_returns'][label] = raw.model_dump()
        assert raw.status == 'success' and value['state'] == 'completed'
        assert value['semantic_correctness_verified'] is False
        assert value['outputs']['entries'][0]['payload_digest'] == digest(EXPECTED)
        assert value['outputs']['entries'][0]['qualifiers'] == EXPECTED['qualifiers']
        assert value['outputs']['entries'][0]['body_deferred']
        receipt = value['text_work_id']
        original = deepcopy(ws.store.get('text_work_receipt:' + receipt))
        assert original['state'] == 'completed' and original['result']['payloads'] == [EXPECTED]
        held['receipts'][label] = receipt
        held['receipt_originals'][label] = original  # Oracle only, never model input.
        assert cs.list_objects('ContentNode') == []
        if label == 'A':
            return AIMessage(content=json.dumps({'candidate_text_work_id': receipt,
                'saved_refs': [], 'unresolved': ['Candidate was produced but not adopted or reviewed.']}))
        assert held['receipts']['A'] != receipt
        a_result = held['receipt_originals']['A']['result']
        assert original['result']['actor_id'] != a_result['actor_id']
        assert original['result']['task_id'] != a_result['task_id']
        assert original['result']['payloads'] == a_result['payloads']
        choices = {name: {'operation_id': 'adopt-selected', 'text_work_id': selected,
                         'text_work_index': 0} for name, selected in (
            ('owned', receipt), ('foreign', held['a_parent_receipt']))}
        assert {k: v for k, v in choices['owned'].items() if k != 'text_work_id'} == {
            k: v for k, v in choices['foreign'].items() if k != 'text_work_id'}
        held['adoption_choices'] = choices
        held['objects_before_adoption'] = deepcopy(cs.list_objects())
        return action('save_text_node', 'adopt', **choices['foreign' if foreign else 'owned'])

    def inspect_adoption(messages):
        raw = tool_reply(messages, 'adopt')
        value = result_value(raw)
        held['writer_after_adoption'] = {'actual_tool_message': raw.model_dump(),
                                        'actual_next_model_input': messages_to_dict(messages)}
        for label, receipt in held['receipts'].items():
            assert ws.store.get('text_work_receipt:' + receipt) == held['receipt_originals'][label]
        if foreign:
            assert raw.status == 'error' and value['ok'] is False
            assert value['code'] == 'FORBIDDEN' and value['message'] == FORBIDDEN
            assert value['retryable'] is False
            assert cs.list_objects() == held['objects_before_adoption']
            assert cs.list_objects('ContentNode') == []
            with ws.store.connect() as db:
                assert db.execute('SELECT count(*) FROM content_operations WHERE operation_id=?',
                                  ('adopt-selected',)).fetchone()[0] == 0
            held['unresolved'] = [value['message']]
        else:
            assert raw.status == 'success' and value['ok'] is True
            ref = value['result']['refs']['text']
            saved = cs.read(ref)
            assert saved['payload'] == EXPECTED
            assert saved['owner_id'] == held['receipt_originals']['B']['result']['actor_id']
            assert saved['task_id'] == held['receipt_originals']['B']['result']['task_id']
            assert cs.list_objects('ContentNode') == [saved]
            held['adopted_refs'] = [ref]
        return AIMessage(content=json.dumps({'saved_refs': held['adopted_refs'],
            'unresolved': held['unresolved'], 'review_or_engineering_acceptance': False}))

    def parent_after_a(messages):
        raw = tool_reply(messages, 'delegate-a')
        held['parent_returns']['A'] = raw.model_dump()
        assert raw.status == 'success'
        report = json.loads(raw.content)
        assert report['saved_refs'] == [] and report['unresolved']
        assert report['candidate_text_work_id'] == held['receipts']['A']
        held['a_parent_receipt'] = report['candidate_text_work_id']
        held['current_writer'] = 'B'
        # Both variants receive this same declared candidate identity. Receiving
        # the identity does not transfer A's task ownership or adoption authority.
        return action('task', 'delegate-b', subagent_type='writer',
            description='TASK-B: Produce your own qualified candidate and inspect adoption. '
                        'Report actual saved refs or unresolved tool rejection, without review claims. '
                        'REFERENCE_RECEIPT=' + report['candidate_text_work_id'])

    def parent_after_b(messages):
        raw = tool_reply(messages, 'delegate-b')
        held['parent_returns']['B'] = raw.model_dump()
        assert raw.status == 'success'  # Child returned; this is not adoption success.
        report = json.loads(raw.content)
        assert report['saved_refs'] == held['adopted_refs']
        assert report['unresolved'] == ([FORBIDDEN] if foreign else [])
        assert report['review_or_engineering_acceptance'] is False
        held['parent_b_input'] = messages_to_dict(messages)
        return action('read_object_index', 'parent-index', object_type='ContentNode', current_only=True)

    def parent_finish(messages):
        raw = tool_reply(messages, 'parent-index')
        value = result_value(raw)
        assert raw.status == 'success' and value['next_offset'] is None
        assert value['total'] == (0 if foreign else 1)
        assert [obj['ref'] for obj in value['objects']] == held['adopted_refs']
        for obj in value['objects']:
            assert obj['owner_id'] == held['receipt_originals']['B']['result']['actor_id']
            assert obj['payload_digest'] == digest(EXPECTED)
        held['actual_parent_index'] = raw.model_dump()
        held['parent_final_input'] = messages_to_dict(messages)
        return AIMessage(content='Actual saved refs and returned unresolved work observed; no report acceptance claimed.')

    driver = Driver(coordinator=[action('task', 'delegate-a', subagent_type='writer',
        description='TASK-A: Produce a qualified candidate, retain it unadopted and report its receipt identity.'),
        parent_after_a, parent_after_b, parent_finish], writer=[start_writer, select_adoption, inspect_adoption])
    models, calls = {}, []
    def factory(role):
        if role == 'text_tool':
            return producer
        if role not in models:
            models[role] = traced_model(driver(role), role, calls)
        return models[role]
    runtime, error = None, None
    try:
        runtime = await run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        with ws.store.connect() as db:
            receipts = {key: json.loads(value) for key, value in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'text_work_receipt:%'")}
        dump(folder / 'capture.json', {'foreign': foreign, 'runtime': runtime, 'raised_error': error,
             'held': held, 'native_model_calls': calls, 'producer_inputs': producer.calls,
             'producer_response': producer.response, 'saved_receipts': receipts,
             'saved_objects': cs.list_objects(), 'events': ws.store.events(),
             'test_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'limits': ['Fake choices are not autonomous model behavior.',
                        'Parent unresolved status is the honest child return, not a persistent handling record.',
                        'No automatic lie detection or semantic acceptance is asserted.',
                        'Reading another project object and adopting another task receipt are different permissions.']})
    request.node.user_properties.append(('foreign_adoption_capture', str(folder)))
    assert error is None, error
    assert runtime['last_error'] is None
    assert len(producer.calls) == 2
    assert len(driver.calls) == len(calls) == 9
    assert len(receipts) == 2 and all(v['state'] == 'completed' for v in receipts.values())
    assert all(cs.read(item['ref']) == item for item in originals)
    assert len(cs.list_objects('DelegatedTask')) == 2
    assert not cs.list_objects('ReviewRecord') and not cs.list_objects('ExportArtifact')
    assert not report_state.selected_delivery(ws.store)
