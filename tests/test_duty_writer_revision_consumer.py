"""P16 fake controls: actual exact adoption versus received-but-unadopted."""
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from duty_probe_writer_revision_consumer import capture_writer_revision_consumer, load_revision_fixture
from report_agent.content_store import ContentStore
from report_agent.store import digest
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


UNADOPTED = 'The revision candidate was received but has not been adopted; the original v1 remains current.'


def revision_consumer_factory(adopt, held):
    expected = load_revision_fixture()

    def unused(messages):
        raise AssertionError('The three explicit fixture actions must precede the consumer')

    def receive(messages):
        actual = tool_reply(messages, 'revision-producer')
        assert actual.status == 'success', actual
        public = result_value(actual)
        held['public'] = public
        assert public['state'] == 'completed' and public['semantic_correctness_verified'] is False
        assert public['details_deferred'] and public['outputs']['complete']
        assert public['outputs']['total'] == 1
        entry = public['outputs']['entries'][0]
        assert entry['index'] == 0 and entry['body_deferred'] and 'body' not in entry
        assert entry['original_path'] == ['payloads', 0]
        assert entry['payload_digest'] == digest(expected['expected_payload'])
        for field in ('kind', 'claim_kind', 'qualifiers'):
            assert entry[field] == expected['expected_payload'][field]
        held['target'] = public['revision']['targets'][0]['ref']
        assert public['revision']['scope'] == 'qualifiers'
        assert public['revision']['targets'][0]['payload_digest'] == digest(expected['initial_payload'])
        held['observation_ref'] = json.loads(actual.content)['observation_ref']
        if not adopt:
            return AIMessage(content=UNADOPTED)
        held.update(pages=[], read_id='read-revision-0')
        return action('read_tool_observation', held['read_id'], observation_ref=held['observation_ref'],
                      offset=0, characters=6000)

    def read_or_adopt(messages):
        actual = result_value(tool_reply(messages, held['read_id']))
        assert actual['offset'] == sum(len(p) for p in held['pages'])
        held['pages'].append(actual['text'])
        if actual['next_offset'] is not None:
            held['read_id'] = 'read-revision-' + str(len(held['pages']))
            return action('read_tool_observation', held['read_id'], observation_ref=held['observation_ref'],
                          offset=actual['next_offset'], characters=6000)
        recovered = json.loads(''.join(held['pages']))
        held['recovered'] = recovered
        assert recovered['payloads'] == [expected['expected_payload']]
        assert recovered['text_work_id'] == held['public']['text_work_id']
        assert recovered['revision']['targets'][0]['ref'] == held['target']
        held['stage'] = 'finish'
        return action('save_text_node', 'adopt-revision', operation_id='fake-exact-revision-adoption',
            text_work_id=held['public']['text_work_id'], text_work_index=0, previous_ref=held['target'])

    def finish(messages):
        actual = result_value(tool_reply(messages, 'adopt-revision'))
        assert actual['ok'], actual
        held['adopted_ref'] = actual['result']['refs']['text']
        assert held['adopted_ref'] == {**held['target'], 'version': 2}
        return AIMessage(content=json.dumps({'adopted_ref': held['adopted_ref'],
            'limitations': 'The geological class remains unresolved; no engineering acceptance.'}))

    def continuation(messages):
        return finish(messages) if held.get('stage') == 'finish' else read_or_adopt(messages)

    return Driver(writer=[unused, unused, unused, receive, *([continuation] * 8)])


@pytest.mark.parametrize('adopt', [True, False], ids=['exact-adoption', 'received-not-adopted'])
async def test_r7_recorded_revision_native_writer_consumption(ws, request, adopt):
    held = {}
    driver = revision_consumer_factory(adopt, held)
    folder = Path(os.environ.get('REPORT_WRITER_REVISION_CONSUMER_OUT', str(ws.store.root / 'captures'))) / request.node.name
    capture = await capture_writer_revision_consumer(ws, folder, driver)
    request.node.user_properties.append(('revision_consumer', json.dumps({'capture_dir': str(folder),
        'adopt': adopt, 'oracle': capture['oracle'], 'paid_calls': 0, 'app_changes': 0}, ensure_ascii=False)))
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime_result']['last_error'] is None, capture['runtime_result']
    fixture = capture['fixture']
    diagnostic = capture['host_diagnostic_held']
    oracle = capture['oracle']
    assert [c['origin'] for c in capture['text_service_calls']] == ['initial', 'revision']
    assert capture['text_service_calls'][1]['raw_response']['content'] == fixture['recorded_raw_content']
    packet = json.loads(capture['text_service_calls'][1]['input'][-1][1])
    assert packet['objective'] == fixture['objective']
    assert packet['commission']['goal'] == fixture['goal']
    assert packet['revision']['targets'] == [{'ref': diagnostic['target'], 'payload_digest': digest(fixture['initial_payload'])}]
    evidence = [e['object'] for e in packet['evidence'] if e['kind'] == 'saved_object']
    target = next(e for e in evidence if e['ref'] == diagnostic['target'])
    assert target == diagnostic['original_node']
    assert target['payload'] == fixture['initial_payload']
    source_payloads = [e['payload'] for e in evidence if e['ref']['type'] == 'SourceArtifact']
    assert source_payloads == [o['payload'] for o in fixture['archived_sources']]
    assert packet['actor']['id'] == target['owner_id'] == held['public']['actor_id']
    assert packet['actor']['task_id'] == target['task_id'] == held['public']['task_id']
    assert held['public']['text_work_id'] == diagnostic['revision_public']['text_work_id']
    assert diagnostic['initial_public']['actor_id'] == packet['actor']['id']
    assert diagnostic['initial_public']['task_id'] == packet['actor']['task_id']
    assert len([e for e in capture['phase_events'] if e['phase'] == 'explicit_fake_preparation']) == 3
    assert capture['native_model_calls'] and all(step >= 3 for role, step, _ in driver.calls if role == 'writer')
    assert oracle['original_v1_unchanged'] and oracle['source_originals_unchanged']
    assert oracle['receipt_states'] == {'initial': {'unchanged': True}, 'revision': {'unchanged': True}}
    assert oracle['no_review_or_export'] and oracle['semantic_status'] == 'needs_semantic_review'
    assert not capture['host_completion_actions']
    cs = ContentStore(ws.store)
    assert cs.read(diagnostic['target']) == diagnostic['original_node']
    schemas = {s['name'] for s in driver.bindings['writer'][0]}
    assert {'process_report_content', 'read_tool_observation', 'save_text_node'} <= schemas
    if adopt:
        assert oracle['status'] == 'exact_revision_saved'
        saved = cs.read(held['adopted_ref'])
        assert saved['payload'] == fixture['expected_payload']
        for field in ('kind', 'claim_kind', 'body'):
            assert saved['payload'][field] == fixture['initial_payload'][field]
        assert saved['payload']['qualifiers'] == json.loads(fixture['recorded_raw_content'])['payloads'][0]['qualifiers']
        assert saved['previous_ref'] == diagnostic['target']
        assert saved['owner_id'] == target['owner_id'] and saved['task_id'] == target['task_id']
        assert held['recovered']['payloads'] == [fixture['expected_payload']]
        assert held['adopted_ref']['id'] in capture['parent']['task_return']['content']
        assert json.loads(capture['parent']['task_return']['content'])['adopted_ref'] == held['adopted_ref']
        assert len(driver.calls) == 2 + len(held['pages'])
    else:
        assert oracle['status'] == 'revision_not_adopted'
        assert oracle['current_node'] == diagnostic['original_node']
        assert len(oracle['nodes']) == 1 and oracle['nodes'][0]['ref']['version'] == 1
        assert 'pages' not in held and 'adopted_ref' not in held
        assert capture['parent']['task_return']['content'] == UNADOPTED
        assert len(driver.calls) == 1
