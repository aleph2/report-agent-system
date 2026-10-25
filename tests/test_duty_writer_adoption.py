"""Fake W06 controls after a genuine native producer-result delivery; no paid calls."""
import json
import os
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.deep_models import configured_model
from report_agent.store import digest
from duty_probe_writer_adoption import CASES, capture_writer_adoption, load_recorded_fixture, dump, OneRecordedProducer
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_deadline import close_model
from test_deep_runtime import Driver
from test_task_supervision import ws


def consumer_scripts(case, held):
    expected = load_recorded_fixture(case)
    payload = expected['expected_payloads'][0]

    def receive(messages):
        actual = tool_reply(messages, 'process_report_content')
        public = result_value(actual)
        held['public'] = public
        view = json.loads(actual.content)
        held['observation_ref'] = view['observation_ref']
        assert actual.status == 'success'
        assert public['state'] == 'completed' and public['semantic_correctness_verified'] is False
        assert public['generation_notes'] == expected['expected_generation_notes']
        entry = public['outputs']['entries'][0]
        assert entry['qualifiers'] == payload['qualifiers']
        assert entry['payload_digest'] == digest(payload) and entry['body_deferred']
        assert 'body' not in entry
        for message in messages:
            content = message.content
            for block in content if isinstance(content, list) else [{'text': content}]:
                text = block.get('text', '')
                prefix = 'Current task bindings and navigation previews. Incomplete fields expose read_decision_state paths; previews do not establish complete instruction or evidence coverage:\n'
                if text.startswith(prefix):
                    state = json.loads(text[len(prefix):])
                    held['source_ref'] = next(i['ref'] for i in state['input_refs'] if i['source_id'] == 's')
        if case == 'missing-incomplete':
            return AIMessage(content='Candidate requires inspection; no action or adoption has been completed.')
        held.update(stage='reading', pages=[], read_id='read-candidate-0')
        return action('read_tool_observation', held['read_id'], observation_ref=held['observation_ref'],
                      offset=0, characters=6000)

    def after_read(messages):
        actual = result_value(tool_reply(messages, held['read_id']))
        held['recovered'] = actual
        assert actual['offset'] == sum(len(p) for p in held['pages'])
        held['pages'].append(actual['text'])
        if actual['next_offset'] is not None:
            held['read_id'] = 'read-candidate-' + str(len(held['pages']))
            return action('read_tool_observation', held['read_id'], observation_ref=held['observation_ref'],
                          offset=actual['next_offset'], characters=6000)
        recovered = json.loads(''.join(held['pages']))
        assert recovered['payloads'] == expected['expected_payloads']
        assert recovered['generation_notes'] == expected['expected_generation_notes']
        held['stage'] = 'action'
        if case == 'missing-read-handoff':
            return action('read_source_page', 'reread-source', source_id='s', offset=0, limit=10)
        return action('commit_objects', 'adopt-candidate', operation_id='fake-exact-adoption', objects=[
            {'client_key': 'candidate', 'type': 'ContentNode', 'text_work_id': held['public']['text_work_id'],
             'text_work_index': 0}])

    def after_action(messages):
        if case == 'missing-read-handoff':
            source = result_value(tool_reply(messages, 'reread-source'))
            held['source_read'] = source
            assert expected['source']['content'] in json.dumps(source, ensure_ascii=False)
            held['stage'] = 'handoff'
            return action('record_handoff', 'save-issue', operation_id='fake-missing-table-handoff',
                target_ref=held['source_ref'], problem='The supplied source has no class value table.',
                evidence=[expected['source']['content']], impact='The complete table and footnote remain unresolved.',
                handling_state='open')
        adopted = result_value(tool_reply(messages, 'adopt-candidate'))
        assert adopted['ok'], adopted
        held['adopted'] = adopted
        return AIMessage(content='The exact qualified working candidate is saved; no independent review or engineering acceptance.')

    def after_issue(messages):
        actual = result_value(tool_reply(messages, 'save-issue'))
        held['issue'] = actual
        assert actual['ok'] and actual['result']['handling_ref']['type'] == 'HandlingRecord'
        return AIMessage(content='The source was re-read; the table remains missing. An unresolved issue was saved, with no adoption.')

    def continue_script(messages):
        return {'reading': after_read, 'action': after_action, 'handoff': after_issue}[held['stage']](messages)
    # Fixed fake responses, including advertised recovery pages; the native graph
    # remains the only execution loop. No host reads fill any of these messages.
    return [AIMessage(content='UNUSED_FIXTURE_INDEX'), receive, *([continue_script] * 8)]


def check_capture(capture, case):
    assert capture['raised_error'] is None, capture
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['fixture_producer_calls'] == 1 and capture['later_text_calls'] == 0
    expected = ('incomplete' if case == 'missing-incomplete' else
                'unresolved_issue_saved' if case == 'missing-read-handoff' else 'exact_qualified_candidate_saved')
    assert capture['oracle']['status'] == expected, capture['oracle']
    assert capture['oracle']['originals_unchanged'] and capture['oracle']['no_review_or_export']
    assert capture['native_model_calls']
    assert capture['phase_events'][0]['phase'] == 'fixture_action'
    assert all(e['phase'] == 'unchanged_consumer_handler' for e in capture['phase_events'][1:])
    assert len(capture['host_diagnostic_receipts']) == 1
    saved = capture['host_diagnostic_receipts'][0]['value']['result']
    fixture = load_recorded_fixture(case)
    assert saved['payloads'] == fixture['expected_payloads']
    assert saved['generation_notes'] == fixture['expected_generation_notes']
    assert saved['state'] == 'completed' and saved['semantic_correctness_verified'] is False
    original_packet = json.loads(capture['text_service_calls'][0]['input'][-1][1])
    assert original_packet['objective'] == fixture['objective']
    assert original_packet['evidence'][0]['observation']['blocks'][0]['text'] == fixture['source']['content']
    assert original_packet['actor']['id'] == saved['actor_id']
    assert original_packet['actor']['task_id'] == saved['task_id']
    assert saved['model']['model_name'] == 'recorded-R2-producer-fixture-not-live'
    if case == 'missing-read-handoff':
        assert len(capture['oracle']['handoffs']) == 1
        handoff = capture['oracle']['handoffs'][0]
        assert handoff['owner_id'] == saved['actor_id']
        assert handoff['payload']['handling_state'] == 'open'
        assert handoff['payload']['target_ref']['type'] == 'SourceArtifact'
        assert handoff['payload']['problem'] == 'The supplied source has no class value table.'
        assert handoff['payload']['evidence'] == [fixture['source']['content']]
        assert handoff['payload']['impact'] == 'The complete table and footnote remain unresolved.'
        assert not capture['oracle']['nodes']
    else:
        assert not capture['oracle']['handoffs']


@pytest.mark.parametrize('case', CASES)
async def test_native_writer_adoption_fake_controls(ws, monkeypatch, request, case):
    def denied(*args, **kwargs):
        pytest.fail('Network forbidden in fake adoption controls')
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setattr(httpx.Client, 'send', denied)
    held = {}
    driver = Driver(writer=consumer_scripts(case, held))
    folder = Path(os.environ.get('REPORT_WRITER_ADOPTION_OUT', str(ws.store.root / 'captures'))) / case
    capture = await capture_writer_adoption(ws, case, folder, driver)
    request.node.user_properties.append(('writer_adoption_capture', str(folder)))
    check_capture(capture, case)
    assert all(step >= 1 for role, step, _ in driver.calls if role == 'writer')
    assert len(driver.calls) == (1 if case == 'missing-incomplete' else
                                2 + len(held['pages']) + (1 if case == 'missing-read-handoff' else 0))
    schemas = driver.bindings['writer'][-1]
    assert {'process_report_content', 'read_tool_observation', 'commit_objects', 'record_handoff'} <= {s['name'] for s in schemas}


async def test_native_writer_adoption_uses_configured_sdk_binding_without_network(ws, monkeypatch, request):
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_WRITER_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    model = configured_model(ws.store, 'writer')
    held, wires = {}, []
    case = 'missing-adopt'
    scripts = consumer_scripts(case, held)

    async def transport(request):
        wire = json.loads(request.content)
        wires.append(wire)
        # Provider-shaped scripted consumer, not a live model or alternate loop.
        # This is decoding the actual SDK request solely to select a mock
        # provider answer, never constructing input for the application model.
        messages = [ToolMessage(content=m['content'], tool_call_id=m['tool_call_id'],
                    name=m.get('name', '')) for m in wire['messages'] if m['role'] == 'tool']
        response = scripts[len(wires)](messages)
        message = {'role': 'assistant', 'content': response.content}
        if response.tool_calls:
            message['tool_calls'] = [{'id': t['id'], 'type': 'function',
                'function': {'name': t['name'], 'arguments': json.dumps(t['args'])}} for t in response.tool_calls]
        return httpx.Response(200, json={'id': 'offline-writer', 'object': 'chat.completion', 'created': 1,
            'model': wire['model'], 'choices': [{'index': 0, 'finish_reason': 'tool_calls' if response.tool_calls else 'stop',
            'message': message}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(transport)
    model.http_async_client._mounts = {}
    unused = Driver()
    folder = Path(os.environ.get('REPORT_WRITER_ADOPTION_OUT', str(ws.store.root / 'captures'))) / 'sdk-missing-adopt'
    try:
        capture = await capture_writer_adoption(ws, case, folder,
            lambda role: model if role == 'writer' else unused(role))
    finally:
        await close_model(model)
        folder.mkdir(parents=True, exist_ok=True)
        dump(folder / 'sdk-wire.json', wires)
    request.node.user_properties.append(('writer_adoption_sdk_capture', str(folder)))
    check_capture(capture, case)
    assert len(wires) == 2 + len(held['pages'])
    assert all(w['model'] == 'glm-5.3' for w in wires)
    for wire in wires:
        names = {t['function']['name'] for t in wire['tools']}
        assert {'process_report_content', 'read_tool_observation', 'commit_objects', 'record_handoff'} <= names


async def test_recorded_producer_routes_later_calls_and_identity_to_injected_service():
    """Helper plumbing only, not an Agent decision or live-provider test."""
    from report_agent.evidence_analysis import model_identity
    from test_bounded_review import Model
    backend = Model('injected second output')
    backend.model_name = 'synthetic-consumer-service'
    backend.max_tokens = 100
    backend.openai_api_base = 'https://offline.invalid/v1'
    selections = []
    def factory(role):
        selections.append(role)
        return backend
    service = OneRecordedProducer('recorded first output', factory)
    assert model_identity(service)['model_name'] == 'recorded-R2-producer-fixture-not-live'
    assert (await service.ainvoke([('user', 'first fixture')])).content == 'recorded first output'
    service.consumer_started = True
    assert model_identity(service) == model_identity(backend)
    assert (await service.ainvoke([('user', 'later selected work')])).content == 'injected second output'
    assert len(service.recorded.calls) == len(backend.calls) == 1
    assert selections == ['text_tool']
    assert [c['origin'] for c in service.calls] == ['recorded_R2_fixture', 'injected_consumer_text_service']


async def test_native_writer_replays_r10_recovery_paths_before_exact_adoption(ws, monkeypatch, request):
    """RF-RECOVERY-PATH-UX-01: existing legal rejections, recovery and adoption.

    The path choices come from actual R10 Writer calls. This is a characteristic
    regression of an easy-to-misuse interface, not a new bug or a product fix.
    New isolated observation/receipt identities replace the retired run's IDs.
    """
    from copy import deepcopy
    import hashlib
    from report_agent.content_store import ContentStore

    def denied(*args, **kwargs):
        pytest.fail('Network forbidden in recorded recovery-path replay')
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setattr(httpx.Client, 'send', denied)
    fixture = load_recorded_fixture('missing-adopt')
    expected = fixture['expected_payloads'][0]
    assert len(expected['body']['text']) == 303
    cs, held = ContentStore(ws.store), {}

    def unchanged_before_adoption():
        # Read-only business-state oracle; never adds data to model messages.
        assert cs.list_objects() == held['original_business_objects']
        assert ws.store.get('tool_observation:' + held['observation_ref']) == held['original_observation']
        assert ws.store.get('text_work_receipt:' + held['text_work_id']) == held['original_receipt']

    def receive_candidate(messages):
        actual = tool_reply(messages, 'process_report_content')
        view, public = json.loads(actual.content), result_value(actual)
        assert actual.status == 'success'
        assert public['state'] == 'completed' and public['semantic_correctness_verified'] is False
        assert public['outputs']['entries'][0]['qualifiers'] == expected['qualifiers']
        held.update(observation_ref=view['observation_ref'], text_work_id=public['text_work_id'],
                    original_business_objects=deepcopy(cs.list_objects()))
        held['original_observation'] = deepcopy(ws.store.get('tool_observation:' + held['observation_ref']))
        held['original_receipt'] = deepcopy(ws.store.get('text_work_receipt:' + held['text_work_id']))
        return action('read_tool_observation', 'wrong-projection-path',
            observation_ref=held['observation_ref'], field_path=['metadata', 'outputs', 'entries', 0])

    def receive_missing_path(messages):
        actual = tool_reply(messages, 'wrong-projection-path')
        public = result_value(actual)
        assert actual.status == 'error' and public['ok'] is False
        assert public['code'] == 'OBSERVATION_FIELD_PATH_NOT_FOUND'
        assert public['retryable'] is False and public['receipt_id'] is None
        unchanged_before_adoption()
        held['path_rejection'] = actual.model_dump()
        return action('read_tool_observation', 'wrong-object-path',
            observation_ref=held['observation_ref'], field_path=['payloads', 0])

    def receive_object_path(messages):
        actual = tool_reply(messages, 'wrong-object-path')
        public = result_value(actual)
        assert actual.status == 'error' and public['ok'] is False
        assert public['code'] == 'OBSERVATION_FIELD_NOT_STRING'
        assert public['retryable'] is False and public['receipt_id'] is None
        unchanged_before_adoption()
        held['object_rejection'] = actual.model_dump()
        return action('read_tool_observation', 'correct-text-path',
            observation_ref=held['observation_ref'], field_path=['payloads', 0, 'body', 'text'])

    def receive_leaf(messages):
        actual = tool_reply(messages, 'correct-text-path')
        public = result_value(actual)
        assert actual.status == 'success'
        assert public['text'] == expected['body']['text']
        assert public['field_path'] == ['payloads', 0, 'body', 'text']
        assert public['complete_field'] is True and public['next_offset'] is None
        assert public['total_characters'] == public['end'] == 303 and public['offset'] == 0
        assert public['complete_tool_result'] is False
        assert public['field_sha256'] == hashlib.sha256(expected['body']['text'].encode('utf-8')).hexdigest()
        unchanged_before_adoption()
        held['leaf_return'] = actual.model_dump()
        return action('save_text_node', 'adopt-limited-block', operation_id='replayed-adopt-limited-block',
            text_work_id=held['text_work_id'], text_work_index=0)

    def receive_adoption(messages):
        actual = tool_reply(messages, 'adopt-limited-block')
        public = result_value(actual)
        assert actual.status == 'success' and public['ok']
        saved = cs.read(public['result']['refs']['text'])
        assert saved['payload'] == expected
        assert saved['payload']['qualifiers'] == expected['qualifiers']
        assert saved['owner_id'] == held['original_receipt']['result']['actor_id']
        assert len(cs.list_objects('ContentNode')) == 1
        assert all(cs.read(original['ref']) == original for original in held['original_business_objects'])
        assert ws.store.get('text_work_receipt:' + held['text_work_id']) == held['original_receipt']
        held['adopt_return'], held['saved'] = actual.model_dump(), saved
        return AIMessage(content='The limited block is saved with its original qualifications. The missing table remains unresolved.')

    driver = Driver(writer=[AIMessage(content='UNUSED_FIXTURE_INDEX'), receive_candidate,
        receive_missing_path, receive_object_path, receive_leaf, receive_adoption])
    folder = Path(os.environ.get('REPORT_WRITER_RECOVERY_OUT', str(ws.store.root / 'captures')))
    capture = await capture_writer_adoption(ws, 'missing-adopt', folder, driver)
    request.node.user_properties.append(('writer_recovery_replay_capture', str(folder)))
    check_capture(capture, 'missing-adopt')
    assert len(driver.calls) == 5 and all(role == 'writer' for role, _, _ in driver.calls)
    assert len(capture['fixture_coordinator_calls']) == 2
    assert capture['fixture_producer_calls'] == 1 and capture['later_text_calls'] == 0
    assert not capture['oracle']['handoffs']
    original_trace = (Path(__file__).resolve().parents[1] /
        '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/live-r10/writer-candidate-missing/capture.json')
    dump(folder / 'recovery-path-evidence.json', {
        'classification': 'RF-RECOVERY-PATH-UX-01; P3 discoverability observation; not a new confirmed application bug',
        'original_trace': str(original_trace), 'original_trace_sha256': hashlib.sha256(original_trace.read_bytes()).hexdigest(),
        'new_isolated_identities': True, 'actual_returns_and_saved_state': held,
        'paid_calls': 0, 'consumer_fake_calls': 5, 'fixture_coordinator_calls': 2,
        'recorded_producer_calls': 1, 'product_source_changed': False})
