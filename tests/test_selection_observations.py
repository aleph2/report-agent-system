"""Actual tool/middleware/native-input receipt preservation, not semantic review."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph.message import add_messages

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import business_tools, run_report
from report_agent.hierarchical_tools import actor_for
from report_agent.selection_observations import metadata, refresh, REPRESENTATION
from report_agent.store import encode
from report_agent.task_context import TaskContext, read_observation
from test_hierarchical_content import ws
from test_decision_data import activate
from test_deep_runtime import Driver, invoke


def prepare(ws, count=14):
    cs = ContentStore(ws.store)
    actor = actor_for('coordinator')
    objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': {
        'kind': 'report', 'body': {'text': 'Report'}, 'qualifiers': {}, 'claim_kind': 'structure'}}]
    for i in range(count):
        objects += [{'client_key': str(i), 'type': 'ContentNode', 'payload': {
            'kind': 'block', 'body': {'text': ('Distinct source-backed text %d. ' % i) * 100},
            'qualifiers': {'uncertainty': 'Actual groundwater remains disputed.'}, 'claim_kind': 'inference'}},
            {'client_key': 'edge'+str(i), 'type': 'Relation', 'payload': {
                'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': str(i)},
                'predicate': 'contains', 'position': i, 'provenance_kind': 'adopted_during_generation'}}]
    refs = cs.commit(actor, 'seed', objects)['result']['refs']
    snap = cs.freeze(actor, 'snapshot', refs['root'], list(refs.values()))['result']['snapshot_ref']
    activate(ws)
    return cs, refs, snap


def observe(ws, snap, selections, role='coordinator'):
    tools = {t.__name__: t for t in business_tools(ws, role, None, None)}
    result = StructuredTool.from_function(tools['read_content_selection']).invoke({
        'snapshot_ref': snap, 'selections': selections})
    return result, TaskContext(ws, role).bound_result(ToolMessage(
        encode(result), name='read_content_selection', id='message-exact', tool_call_id='selection-exact'))


def as_old(message):
    packet = json.loads(message.content)
    packet.pop('representation', None)
    packet['metadata'] = {}
    return message.model_copy(update={'content': encode(packet), 'artifact': None,
        'additional_kwargs': {**message.additional_kwargs, 'report_observation_delivery': {
            'representation': 'metadata_and_literal_fragments',
            'complete_tool_result': False, 'characters': len(encode(packet))}}})


def test_large_real_return_retains_exact_selected_bodies_qualifiers_and_receipt(ws):
    cs, refs, snap = prepare(ws)
    before = deepcopy(cs.list_objects())
    requested = [{'ref': refs[str(i)], 'offset': 2, 'limit': 16000} for i in range(14)]
    raw, shown = observe(ws, snap, requested)
    value = json.loads(shown.content)
    meta = value['metadata']
    assert len(encode(raw)) > 30000
    assert meta['receipt_id'] == raw['receipt_id'] and meta['result']['snapshot_ref'] == snap
    assert meta['result']==raw['result'] and value['complete_original_in_decision'] is True
    assert len(meta['result']['selections']) == 14
    for actual in meta['result']['selections']:
        assert actual['manifest_digest'] == cs.read(snap)['payload']['manifest_digest']
        assert actual['selection']['offset'] == 2 and actual['selection']['limit'] == 16000
        assert actual['qualifiers']=={'uncertainty':'Actual groundwater remains disputed.'}
    saved = ws.store.get('tool_observation:' + value['observation_ref'])
    assert saved['text'] == encode(raw)
    assert read_observation(ws, 'coordinator', value['observation_ref'], 0, 6000)['text'] == saved['text'][:6000]
    assert cs.list_objects() == before


def test_rows_retain_requested_and_actual_range_and_real_qualifier_presence(ws):
    cs, refs, snap = prepare(ws, 1)
    # Fixture setup uses direct store because this is not native semantic authorship.
    actor = actor_for('coordinator')
    table = cs.commit(actor, 'table', [{'client_key': 'table', 'type': 'ContentNode', 'payload': {
        'kind': 'table', 'body': {'columns': ['Issue'], 'rows': [['A'], ['B'], ['C']]},
        'qualifiers': {'limitation': 'Unresolved actual issue'}, 'claim_kind': 'fact'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'table'}, 'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    snap = cs.freeze(actor, 'table-snapshot', refs['root'], [*refs.values(), *table.values()])['result']['snapshot_ref']
    raw, shown = observe(ws, snap, [{'ref': table['table'], 'unit': 'rows', 'offset': 1, 'limit': 1}])
    meta = json.loads(shown.content)['metadata']
    item = meta['result']['selections'][0]
    assert meta['result']==raw['result']
    assert item['selection']['unit'] == 'rows' and item['selected_range'] == [1, 2] and item['next_offset'] == 2
    assert item['total_units'] == 3 and not item['complete_body_selection']
    assert item['qualifiers']=={'limitation':'Unresolved actual issue'}
    assert raw['result']['selections'][0]['body']['rows'] == [['B']]


async def test_old_owned_packet_reprojects_once_without_new_read_or_receipt(ws):
    cs, refs, snap = prepare(ws, 2)
    raw, shown = observe(ws, snap, [{'ref': refs['0']}])
    previous = as_old(shown)
    with ws.store.connect() as db:
        before_receipts = list(db.execute('SELECT * FROM content_observations'))
    before = deepcopy(cs.list_objects())
    history = [AIMessage(content='', id='ai-exact', tool_calls=[{'id': previous.tool_call_id,
        'name': 'read_content_selection', 'args': {'snapshot_ref': snap, 'selections': [{'ref': refs['0']}]}}]), previous]
    mw = TaskContext(ws, 'coordinator')
    updated = add_messages(history, (await mw.abefore_model({'messages': history}, None))['messages'])
    result = updated[-1]
    assert result.id == previous.id and result.tool_call_id == previous.tool_call_id
    assert json.loads(result.content)['metadata']['receipt_id'] == raw['receipt_id']
    assert result.additional_kwargs['report_observation_ref'] == previous.additional_kwargs['report_observation_ref']
    assert await mw.abefore_model({'messages': updated}, None) is None
    with ws.store.connect() as db:
        assert list(db.execute('SELECT * FROM content_observations')) == before_receipts
    assert cs.list_objects() == before
    assert len([e for e in ws.store.events() if e['kind'] == 'selection_observation_reprojected']) == 1


@pytest.mark.parametrize('tamper', ['owner', 'sha', 'message_sha', 'ref', 'receipt_owner', 'receipt_data', 'missing_receipt'])
def test_refresh_requires_exact_owner_hash_and_original_read_receipt(ws, tamper):
    _, refs, snap = prepare(ws, 1)
    raw, shown = observe(ws, snap, [{'ref': refs['0']}])
    old = as_old(shown)
    packet = json.loads(old.content)
    ref = packet['observation_ref']
    if tamper in {'owner', 'sha'}:
        saved = ws.store.get('tool_observation:' + ref)
        saved['owner' if tamper == 'owner' else 'sha256'] = 'wrong'
        ws.store.set('tool_observation:' + ref, saved)
    elif tamper in {'message_sha', 'ref'}:
        packet['sha256' if tamper == 'message_sha' else 'observation_ref'] = 'wrong'
        old = old.model_copy(update={'content': encode(packet)})
    else:
        with ws.store.connect() as db:
            if tamper == 'missing_receipt':
                db.execute('DELETE FROM content_observations WHERE id=?', (raw['receipt_id'],))
            else:
                column = 'actor_id' if tamper == 'receipt_owner' else 'data'
                db.execute('UPDATE content_observations SET '+column+'=? WHERE id=?', ('{}', raw['receipt_id']))
    assert refresh(ws, 'coordinator', old) is old


def test_large_identifiers_and_many_selections_are_never_silently_truncated(ws):
    _, refs, snap = prepare(ws, 1)
    raw, _ = observe(ws, snap, [{'ref': refs['0']}])
    many = deepcopy(raw)
    many['result']['selections'] *= 100
    result = metadata(many)
    assert len(encode(result)) <= 4700 and result['selection_count'] == 100
    assert result['next_selection_index'] == len(result['selections']) and not result['complete_selection_metadata']
    long = deepcopy(raw)
    long['result']['selections'][0]['selection']['ref']['id'] = 'long-id-' * 1000
    result = metadata(long)
    assert result['selections'] == [] and not result['complete_selection_metadata']
    long['result']['snapshot_ref']['id'] = 'long-snapshot-' * 1000
    result = metadata(long)
    assert result['identities_deferred'] and len(encode(result)) <= 4700


def test_final_completeness_markers_obey_the_actual_serialized_size_boundary(ws):
    _, refs, snap = prepare(ws, 1)
    raw, _ = observe(ws, snap, [{'ref': refs['0']}])
    full = metadata(raw)
    assert full['complete_selection_metadata']
    maximum = len(encode(full)) - 1
    result = metadata(raw, maximum=maximum)
    assert len(encode(result)) <= maximum
    assert not result['complete_selection_metadata'] and result['next_selection_index'] == 0
    assert result['selections'] == [] and result['receipt_id'] == raw['receipt_id']


async def test_actual_native_writer_next_input_retains_receipt_and_full_selection_identity(ws):
    cs, refs, snap = prepare(ws, 2)
    before = deepcopy(cs.list_objects())
    def inspect(messages):
        selected = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'read_content_selection')
        packet = json.loads(selected.content)
        meta = packet['metadata']
        assert packet['representation'] == 'exact-public-result-v2'
        data = meta['result']
        assert data['snapshot_ref'] == snap and data['selections'][0]['selection']['ref'] == refs['0']
        assert data['selections'][0]['selected_range'] == [4, 11]
        assert not data['selections'][0]['complete_body_selection']
        assert data['selections'][0]['qualifiers']=={'uncertainty':'Actual groundwater remains disputed.'}
        saved = ws.store.get('tool_observation:' + packet['observation_ref'])
        with ws.store.connect() as db:
            row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (meta['receipt_id'],)).fetchone()
        assert row[0] == saved['owner'] and json.loads(row[1]) == json.loads(saved['text'])['result'] == data
        return AIMessage(content='Selected saved range observed; no semantic review acceptance.')
    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description='Inspect selected content.'),
        AIMessage(content='Observation only.')], writer=[invoke('read_content_selection', snapshot_ref=snap,
        selections=[{'ref': refs['0'], 'offset': 4, 'limit': 7}]), inspect])
    outcome = await run_report(ws, driver)
    assert outcome['last_error'] is None, outcome
    assert [(r, step) for r, step, _ in driver.calls] == [('coordinator', 0), ('writer', 0), ('writer', 1), ('coordinator', 1)]
    assert all(cs.read(record['ref']) == record for record in before)
    assert not cs.list_objects('ReviewRecord')
