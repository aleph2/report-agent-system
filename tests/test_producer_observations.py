"""Native delivery of producer limitations; no paid model or semantic acceptance."""
import json
from copy import deepcopy

from langchain_core.messages import AIMessage, ToolMessage
from report_agent.deep_runtime import run_report
from report_agent.task_context import TaskContext, read_observation
from report_agent.store import digest
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, observation
from test_task_supervision import ws, offline
from test_text_work import writer_call
import pytest


def output(qualifiers):
    return {'kind': 'block', 'body': {'text': 'Substantive body retained outside decision.' * 1000},
            'claim_kind': 'inference', 'qualifiers': qualifiers}


async def test_native_writer_sees_actual_producer_limits_without_bulk_body_or_receipt_change(ws):
    activate(ws)
    payload = output({'source_refs': 'A long source citation. ' * 700,
                      'claim_status': 'Partial evidence only; required table incomplete.',
                      'limitations': ['Missing source pages; do not infer absence.']})
    seen = []
    def inspect(messages):
        packet = observation(messages, 'process_report_content')
        seen.append(packet)
        return invoke('save_text_node', operation_id='adopt',
                      text_work_id=packet['metadata']['text_work_id'])
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]),
                                 AIMessage(content='Draft receipt saved, no acceptance.')],
                    writer=[invoke('process_report_content', operation_id='partial',
                        objective='Draft from actual selected evidence', object_type='ContentNode',
                        source_selections=[{'source_id': 's'}]), inspect,
                        AIMessage(content='Actual limitations retained; no semantic pass.')],
                    text_tool=[AIMessage(content=json.dumps(payload, ensure_ascii=False))])
    await run_report(ws, driver)
    assert seen
    packet = seen[0]
    entry = packet['metadata']['outputs']['entries'][0]
    assert entry['claim_kind'] == 'inference'
    assert entry['qualifiers'] == payload['qualifiers']
    assert payload['body']['text'] not in json.dumps(packet)
    assert packet['metadata']['semantic_correctness_verified'] is False
    assert entry['payload_digest'] == digest(payload)
    assert entry['body_deferred'] is True
    from report_agent.content_store import ContentStore
    nodes = ContentStore(ws.store).list_objects('ContentNode')
    assert any(n['payload'] == payload for n in nodes)
    saved = ws.store.get('tool_observation:' + seen[0]['observation_ref'])
    assert json.loads(saved['text'])['payload'] == payload
    assert len([r for r, _, _ in driver.calls if r == 'text_tool']) == 1


def test_32_indexes_limits_and_exact_recovery_remain_available(ws):
    activate(ws)
    payloads = [output({'sources': 'long provenance ' * 600, 'uncertainty': 'Not confirmed'}) for _ in range(32)]
    for payload in payloads:
        payload['claim_kind'] = 'recommendation'
    raw = {'text_work_id': 'a' * 64, 'actor_id': 'content:writer:' + 'b' * 36,
           'task_id': 'c' * 36, 'reused': False,
           'limitation': 'Received validated tool output for these selections; not review or engineering acceptance.',
           'object_type': 'ContentNode', 'payloads': payloads,
           'state': 'completed', 'semantic_correctness_verified': False}
    text = json.dumps(raw, ensure_ascii=False)
    msg = ToolMessage(content=text, name='process_report_content', tool_call_id='large')
    shown = TaskContext(ws, 'coordinator').bound_result(msg)
    packet = json.loads(shown.content)
    entries = packet['metadata']['outputs']['entries']
    assert [e['index'] for e in entries] == list(range(32))
    assert [e['payload_digest'] for e in entries] == [digest(p) for p in payloads]
    assert [e['qualifiers'] for e in entries] == [p['qualifiers'] for p in payloads]
    assert all(e['body_deferred'] and 'body' not in e for e in entries)
    assert packet['metadata']['outputs']['complete'] is True
    saved = ws.store.get('tool_observation:' + packet['observation_ref'])
    assert saved['text'] == text and msg.content == text
    recovered = read_observation(ws, 'coordinator', packet['observation_ref'], 0, 1000)
    assert recovered['text'] == text[:1000]


def test_empty_and_large_qualifiers_are_exact_and_no_acceptance_inferred(ws):
    activate(ws)
    payloads = [output({}), output({'very_large_key_' + 'x'*9000: 'Not confirmed',
                                   'pending': 'Remaining source needed'})]
    before = deepcopy(payloads)
    raw = {'text_work_id': 'receipt', 'object_type': 'ContentNode', 'payloads': payloads,
           'state': 'completed', 'semantic_correctness_verified': False}
    shown = TaskContext(ws, 'coordinator').bound_result(ToolMessage(content=json.dumps(raw),
        name='process_report_content', tool_call_id='mixed'))
    packet = json.loads(shown.content)
    entries = packet['metadata']['outputs']['entries']
    assert entries[0]['qualifiers'] == {}
    assert entries[1]['qualifiers'] == payloads[1]['qualifiers']
    assert entries[1]['qualifiers']['pending'] == 'Remaining source needed'
    assert payloads == before and not packet['metadata']['semantic_correctness_verified']


def as_legacy_producer(message):
    """Construct the persisted pre-refactor wire shape, independent of new projection."""
    from report_agent.store import encode
    view = json.loads(message.content)
    meta = view['metadata']
    view.pop('representation', None)
    view['complete_original_in_decision'] = False
    view['metadata'] = {key: meta[key] for key in
        ('text_work_id', 'object_type', 'actor_id', 'task_id', 'state',
         'semantic_correctness_verified', 'output_count') if key in meta}
    entries = [{key: entry[key] for key in ('index', 'kind', 'payload_digest')}
               for entry in meta['outputs']['entries']]
    view['metadata']['outputs'] = {'entries': entries, 'total': len(entries), 'complete': True}
    return message.model_copy(update={'content': encode(view), 'artifact': None,
        'additional_kwargs': {**message.additional_kwargs, 'report_observation_delivery': {
            'representation': 'metadata_and_literal_fragments',
            'complete_tool_result': False, 'characters': len(encode(view))}}})


def old_packet(ws):
    from report_agent.text_work import actor_for_tool
    from report_agent.store import encode
    actor = actor_for_tool(ws, 'coordinator')
    raw = {'text_work_id': 'owned-receipt', 'object_type': 'ContentNode', 'state': 'completed',
           'actor_id': actor.id, 'task_id': actor.task_id, 'semantic_correctness_verified': False,
           'payloads': [output({'limitations': 'Original unresolved constraint.'})]}
    ws.store.set('text_work_receipt:owned-receipt', {'state': 'completed', 'result': raw})
    message = TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        content=encode({**raw, 'reused': False}), name='process_report_content', tool_call_id='owned-call', id='owned-message'))
    return as_legacy_producer(message)


async def test_old_owned_message_refreshes_exactly_once_with_original_pairing(ws):
    from report_agent.store import encode
    activate(ws)
    message = old_packet(ws)
    old = json.loads(message.content)
    saved = deepcopy(ws.store.get('tool_observation:' + old['observation_ref']))
    update = await TaskContext(ws, 'coordinator').abefore_model({'messages': [message]}, None)
    changed = update['messages'][0]
    assert (changed.id, changed.tool_call_id, changed.status) == (message.id, message.tool_call_id, message.status)
    view = json.loads(changed.content)
    assert view['sha256'] == old['sha256'] and view['observation_ref'] == old['observation_ref']
    assert view['metadata']['outputs']['entries'][0]['qualifiers']['limitations'] == 'Original unresolved constraint.'
    assert ws.store.get('tool_observation:' + old['observation_ref']) == saved
    assert await TaskContext(ws, 'coordinator').abefore_model({'messages': [changed]}, None) is None
    assert len([e for e in ws.store.events() if e['kind'] == 'producer_observation_reprojected']) == 1


@pytest.mark.parametrize('tamper', ['owner', 'sha', 'ref', 'receipt', 'payload_digest', 'missing', 'failed_receipt'])
def test_foreign_or_changed_original_is_not_reprojected(ws, tamper):
    from report_agent.decision_data import refresh_producer_observation
    from report_agent.store import encode
    activate(ws)
    message = old_packet(ws)
    view = json.loads(message.content)
    key = 'tool_observation:' + view['observation_ref']
    saved = ws.store.get(key)
    if tamper == 'owner':
        ws.store.set(key, {**saved, 'owner': 'different-task'})
    elif tamper == 'sha':
        ws.store.set(key, {**saved, 'text': saved['text'] + ' '})
    elif tamper == 'missing':
        ws.store.set(key, None)
    elif tamper == 'failed_receipt':
        ws.store.set('text_work_receipt:owned-receipt', {'state': 'reserved'})
    else:
        if tamper == 'ref': view['observation_ref'] = 'forged'
        elif tamper == 'receipt': view['metadata']['text_work_id'] = 'different-receipt'
        else: view['metadata']['outputs']['entries'][0]['payload_digest'] = 'altered'
        message = message.model_copy(update={'content': encode(view)})
    assert refresh_producer_observation(ws, 'coordinator', message) is message
    assert not any(e['kind'] == 'producer_observation_reprojected' for e in ws.store.events())


async def test_native_graph_represents_old_producer_return_without_second_text_call(ws, monkeypatch):
    activate(ws)
    original = TaskContext.bound_result
    # Simulate one persisted legacy representation at the native tool boundary.
    def old_once(self, result, tool_args=None):
        shown = original(self, result, tool_args)
        if isinstance(shown, ToolMessage) and shown.name == 'process_report_content':
            monkeypatch.setattr(TaskContext, 'bound_result', original)
            return as_legacy_producer(shown)
        return shown
    monkeypatch.setattr(TaskContext, 'bound_result', old_once)
    captured = []
    def inspect(messages):
        captured.append(observation(messages, 'process_report_content'))
        return AIMessage(content='Unverified candidate retained.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]), AIMessage(content='No acceptance.')],
        writer=[invoke('process_report_content', operation_id='old-shape', objective='Use actual evidence',
            object_type='ContentNode', source_selections=[{'source_id':'s'}]), inspect],
        text_tool=[AIMessage(content=json.dumps(output({'limitations':'Still unverified.'})))])
    outcome = await run_report(ws, driver)
    assert outcome['last_error'] is None, outcome
    assert captured[0]['metadata']['outputs']['entries'][0]['qualifiers']['limitations'] == 'Still unverified.'
    assert sum(role == 'text_tool' for role, _, _ in driver.calls) == 1
    assert len([e for e in ws.store.events() if e['kind'] == 'producer_observation_reprojected']) == 1
