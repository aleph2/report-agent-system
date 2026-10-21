"""P06 tests: two indexes, complete recovery, full versus partial adoption."""
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage
import pytest

from duty_probe_writer_multi_consumer import GUIDE, SITE_B, OBJECTIVE, capture_writer_multi_consumer
from report_agent.store import digest
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def fake_batch():
    return {'payloads': [
        {'kind': 'table', 'claim_kind': 'fact', 'body': {
            'columns': ['Indicator', 'Category', 'Score', 'Explanation'],
            'rows': [['geology', 'B', '75-100', 'Apply only when weathering is strong.']],
            'footnote': GUIDE.split('\nFOOTNOTE:', 1)[1].strip()},
         'qualifiers': {'source': 'guide-a', 'applicability': 'Reference interval, not a selected Site B risk score.'}},
        {'kind': 'block', 'claim_kind': 'inference',
         'body': {'text': 'Site B has no established weathering category or selected category-specific risk score.'},
         'qualifiers': {'source': 'site-b', 'technical': SITE_B,
             'tail_condition': 'B_TAIL: the complete Site B limitation remains attached to candidate index 1.'}}],
        'generation_notes': [{'output_index': 0, 'text': 'Synthetic producer note for reference-table candidate A.'},
                             {'output_index': 1, 'text': 'Synthetic producer note for independent Site B candidate B.'}]}


def multi_consumer_factory(adopt_both, held):
    expected = fake_batch()

    def produce(messages):
        assert 'producer_packet' not in held, 'No duplicate producer dispatch in this finite fake control'
        packet = json.loads(messages[-1].content)
        held['producer_packet'] = packet
        assert packet['output_count'] == 2 and packet['objective'] == OBJECTIVE
        materials = [e['object'] for e in packet['evidence'] if e['kind'] == 'saved_object']
        assert [o['payload']['source_id'] for o in materials] == ['guide-a', 'site-b']
        assert [o['payload']['content'] for o in materials] == [GUIDE, SITE_B]
        Draft202012Validator(packet['output_schema']).validate(expected)
        return AIMessage(content=json.dumps(expected, ensure_ascii=False))

    def unused(messages):
        raise AssertionError('Initial request is the single explicit fixture action')

    def receive(messages):
        actual = tool_reply(messages, 'initial-batch')
        assert actual.status == 'success', actual
        public = result_value(actual)
        held['public'] = public
        assert public['state'] == 'completed' and public['semantic_correctness_verified'] is False
        assert public['outputs']['total'] == 2 and public['outputs']['complete']
        assert public['generation_notes'] == expected['generation_notes']
        for i, entry in enumerate(public['outputs']['entries']):
            assert entry['index'] == i and entry['body_deferred'] and 'body' not in entry
            assert entry['original_path'] == ['payloads', i]
            assert entry['payload_digest'] == digest(expected['payloads'][i])
            for field in ('kind', 'claim_kind', 'qualifiers'):
                assert entry[field] == expected['payloads'][i][field]
        held.update(observation_ref=json.loads(actual.content)['observation_ref'], pages=[], read_id='read-batch-0')
        return action('read_tool_observation', held['read_id'], observation_ref=held['observation_ref'],
                      offset=0, characters=6000)

    def read_or_adopt(messages):
        value = result_value(tool_reply(messages, held['read_id']))
        assert value['offset'] == sum(len(p) for p in held['pages'])
        held['pages'].append(value['text'])
        if value['next_offset'] is not None:
            held['read_id'] = 'read-batch-' + str(len(held['pages']))
            return action('read_tool_observation', held['read_id'], observation_ref=held['observation_ref'],
                          offset=value['next_offset'], characters=6000)
        recovered = json.loads(''.join(held['pages']))
        held['recovered'] = recovered
        assert recovered['payloads'] == expected['payloads']
        assert recovered['generation_notes'] == expected['generation_notes']
        assert recovered['text_work_id'] == held['public']['text_work_id']
        held['stage'] = 'finish'
        indexes = [0, 1] if adopt_both else [0]
        return action('commit_objects', 'adopt-batch', operation_id='fake-exact-batch-adoption', objects=[
            {'client_key': 'candidate-' + str(i), 'type': 'ContentNode',
             'text_work_id': held['public']['text_work_id'], 'text_work_index': i} for i in indexes])

    def finish(messages):
        value = result_value(tool_reply(messages, 'adopt-batch'))
        assert value['ok'], value
        held['adopted_refs'] = value['result']['refs']
        return AIMessage(content=json.dumps({'adopted_refs': held['adopted_refs'],
            'unadopted_indexes': [] if adopt_both else [1],
            'technical_limit': SITE_B,
            'scope': 'Stored working candidates only; no selected Site B score or engineering acceptance.'}))

    def continuation(messages):
        return finish(messages) if held.get('stage') == 'finish' else read_or_adopt(messages)

    return Driver(writer=[unused, receive, *([continuation] * 8)], text_tool=[produce])


@pytest.mark.parametrize('adopt_both', [True, False], ids=['two-index-exact-adoption', 'a-only-b-unadopted'])
async def test_fresh_two_candidate_native_writer_consumption(ws, request, adopt_both):
    held = {}
    driver = multi_consumer_factory(adopt_both, held)
    folder = Path(os.environ.get('REPORT_WRITER_MULTI_CONSUMER_OUT', str(ws.store.root / 'captures'))) / request.node.name
    capture = await capture_writer_multi_consumer(ws, folder, driver)
    request.node.user_properties.append(('multi_consumer', json.dumps({'capture_dir': str(folder),
        'adopt_both': adopt_both, 'status': capture['oracle']['status'], 'paid_calls': 0, 'app_changes': 0})))
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime_result']['last_error'] is None, capture['runtime_result']
    assert [r for r, _, _ in driver.calls].count('text_tool') == 1
    assert [r for r, _, _ in driver.calls].count('writer') == 2 + len(held['pages'])
    assert len([e for e in capture['phase_events'] if e['phase'] == 'explicit_fake_initial_action']) == 1
    assert [c['role'] for c in capture['native_model_calls']].count('text_tool') == 1
    assert capture['initial_producer_is_recorded_fixture'] is False
    assert capture['host_completion_actions'] is False
    oracle = capture['oracle']
    expected = fake_batch()
    receipt = oracle['initial_receipt']
    assert receipt['state'] == 'completed'
    assert receipt['result']['payloads'] == expected['payloads']
    assert receipt['result']['generation_notes'] == expected['generation_notes']
    assert receipt['result']['text_work_id'] == held['public']['text_work_id']
    assert receipt['result']['actor_id'] == held['producer_packet']['actor']['id']
    assert receipt['result']['task_id'] == held['producer_packet']['actor']['task_id']
    assert oracle['originals_unchanged'] and oracle['no_review_or_export']
    assert oracle['initial_receipt_unchanged']
    assert len(oracle['all_content_nodes']) == (2 if adopt_both else 1)
    assert oracle['other_successful_content_actions'] == []
    assert oracle['semantic_status'] == 'needs_semantic_review'
    assert oracle['adopted_indexes'] == ([0, 1] if adopt_both else [0])
    assert oracle['unadopted_indexes'] == ([] if adopt_both else [1])
    assert oracle['status'] == ('exact_initial_batch_adopted' if adopt_both else 'partial_initial_batch_adoption')
    assert len(oracle['adoptions']) == (2 if adopt_both else 1)
    for adoption in oracle['adoptions']:
        i, node = adoption['index'], adoption['saved_node']
        assert adoption['exact'] and adoption['text_work_id'] == held['public']['text_work_id']
        assert node['payload'] == expected['payloads'][i]
        assert node['owner_id'] == held['public']['actor_id'] and node['task_id'] == held['public']['task_id']
        assert node['ref'] == held['adopted_refs']['candidate-' + str(i)]
    a = next(a['saved_node']['payload'] for a in oracle['adoptions'] if a['index'] == 0)
    assert a['body']['columns'] == capture['fixture']['table_columns']
    assert a['body']['rows'] == capture['fixture']['table_rows']
    assert a['body']['footnote'] == capture['fixture']['original_footnote']
    assert held['recovered']['payloads'][1]['qualifiers'] == expected['payloads'][1]['qualifiers']
    parent = json.loads(capture['parent']['task_return']['content'])
    assert parent['adopted_refs'] == held['adopted_refs']
    assert parent['unadopted_indexes'] == oracle['unadopted_indexes']
    assert parent['technical_limit'] == SITE_B
