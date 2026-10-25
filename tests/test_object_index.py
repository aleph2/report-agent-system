"""Native pre-snapshot discovery and provider delivery, not semantic acceptance."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.object_index import object_index
from report_agent.store import encode
from report_agent.task_context import TaskContext
from report_agent.deep_runtime import run_report
from test_hierarchical_content import ws
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, observation


def populate(ws, count=140):
    cs, actor = ContentStore(ws.store), actor_for('coordinator')
    refs = []
    with cs.store.connect() as db:
        root = cs._insert(db, actor, 'ContentNode', {'kind': 'report', 'body': {'text': 'Report'},
            'claim_kind': 'structure', 'qualifiers': {}})
        refs.append(root)
        for n in range(count):
            ref = cs._insert(db, actor, 'ContentNode', {'kind': 'block',
                'body': {'text': f'Original title {n}\n' + 'Unselected original body. ' * 1000},
                'claim_kind': 'fact', 'qualifiers': {'unverified': True}})
            refs.extend([ref, cs._insert(db, actor, 'Relation', {'subject_ref': root,
                'object_ref': ref, 'predicate': 'contains', 'position': n,
                'provenance_kind': 'adopted_during_generation'})])
    return cs, actor, root, refs


def test_complete_bounded_pages_have_whole_exact_identity_and_relation_records(ws):
    cs, actor, root, refs = populate(ws)
    pages, all_entries, offset, fingerprint = [], [], 0, ''
    while True:
        page = object_index(cs, offset, 20, inventory_digest=fingerprint)
        assert len(encode(page)) <= 5800
        all_entries.extend(page['objects'])
        pages.append(page)
        fingerprint = page['inventory_digest']
        if page['next_offset'] is None:
            break
        assert page['next_offset'] == offset + len(page['objects'])
        offset = page['next_offset']
    assert [e['ref'] for e in all_entries] == refs
    assert len(pages) > 2 and len({p['inventory_digest'] for p in pages}) == 1
    for entry in all_entries:
        original = cs.read(entry['ref'])
        assert entry['payload_digest'] == original['payload_digest']
        assert entry['owner_id'] == actor.id and entry['task_id'] == actor.task_id
        if entry['ref']['type'] == 'Relation':
            assert entry['subject_ref'] == root
            assert entry['object_ref'] == original['payload']['object_ref']
    assert 'Unselected original body.' not in encode(pages)
    assert not cs.list_objects('DocumentSnapshot')


def test_filters_heads_history_and_stale_digest_are_explicit(ws):
    cs, actor, _, refs = populate(ws, 4)
    first = object_index(cs)
    record = cs.read(refs[1])
    with cs.store.connect() as db:
        new = cs._insert(db, actor, 'ContentNode', record['payload'], id=refs[1]['id'],
                         version=2, previous_ref=refs[1])
    with pytest.raises(ActionRejected, match='OBJECT_INDEX_CHANGED'):
        object_index(cs, 1, inventory_digest=first['inventory_digest'])
    history = object_index(cs, object_type='ContentNode', owner_id=actor.id)
    current = object_index(cs, object_type='ContentNode', owner_id=actor.id, current_only=True)
    assert history['total'] == current['total'] + 1
    assert refs[1] in [e['ref'] for e in history['objects']]
    assert refs[1] not in [e['ref'] for e in current['objects']]
    assert new in [e['ref'] for e in current['objects']]
    with pytest.raises(ActionRejected, match='OBJECT_INDEX_CHANGED'):
        object_index(cs, owner_id='different', inventory_digest=history['inventory_digest'])
    empty = object_index(cs, owner_id='different')
    assert empty['total'] == 0 and empty['objects'] == [] and empty['next_offset'] is None
    for args in ({'offset': 1}, {'offset': -1}, {'limit': 21}, {'limit': True}):
        with pytest.raises(ActionRejected):
            object_index(cs, **args)


async def test_native_final_schema_and_pages_can_reach_real_freeze_without_body_reads(ws):
    cs, _, root, refs = populate(ws, 15)
    activate(ws)
    collected = []
    def advance(messages):
        page = observation(messages, 'read_object_index')
        assert 'objects' in page and 'metadata' not in page
        collected.extend(page['objects'])
        if page['next_offset'] is not None:
            return invoke('read_object_index', offset=page['next_offset'], inventory_digest=page['inventory_digest'])
        return invoke('freeze_snapshot', operation_id='freeze-index', root_ref=root,
                      refs=[e['ref'] for e in collected])
    def step(messages):
        if any(isinstance(m, ToolMessage) and m.name == 'freeze_snapshot' for m in messages):
            result = observation(messages, 'freeze_snapshot')
            assert result['ok'], result
            return AIMessage(content='Snapshot saved; no report or semantic acceptance.')
        return advance(messages)
    driver = Driver(coordinator=[invoke('read_object_index'), *[step] * 30])
    await run_report(ws, driver)
    assert [e['ref'] for e in collected] == refs
    assert len(cs.list_objects('DocumentSnapshot')) == 1
    schema = next(t for t in driver.bindings['coordinator'][0] if t['name'] == 'read_object_index')
    params = schema['parameters']['properties']
    assert params['limit']['minimum'] == 1 and params['limit']['maximum'] == 20
    assert params['offset']['minimum'] == 0
    assert {'object_type', 'owner_id', 'current_only', 'inventory_digest'} <= set(params)
    freeze_schema = next(t for t in driver.bindings['coordinator'][0] if t['name'] == 'freeze_snapshot')
    assert 'Tasks, snapshots, exports and review records are not manifest members' in freeze_schema['description']
    # Native middleware must retain multiple complete metadata pages, not clear
    # them like recoverable bulk original-text fragments.
    final_messages = driver.calls[-1][2]
    pages = [m for m in final_messages if isinstance(m, ToolMessage) and m.name == 'read_object_index']
    assert len(pages) > 2
    assert all('objects' in json.loads(m.content) and not m.additional_kwargs.get('report_preview_cleared') for m in pages)


async def test_large_status_and_historical_projection_keep_navigation_without_changing_original(ws):
    from report_agent.task_context import read_observation
    cs, actor, _, refs = populate(ws)
    activate(ws)
    status = {t.__name__: t for t in content_tools(ws, 'coordinator')}['content_status']()
    middleware = TaskContext(ws, 'coordinator')
    message = middleware.bound_result(ToolMessage(content=encode(status), name='content_status',
        tool_call_id='status-call', id='status-message'))
    packet = json.loads(message.content)
    assert packet['representation'] == 'exact-public-result-v2'
    assert packet['metadata'] == status and packet['complete_original_in_decision']
    assert [entry['ref'] for entry in packet['metadata']['objects']] == refs
    for entry in packet['metadata']['objects']:
        original = cs.read(entry['ref'])
        assert entry['payload_digest'] == original['payload_digest']
        assert entry['owner_id'] == actor.id and entry['task_id'] == actor.task_id
    indexed, offset, fingerprint = [], 0, ''
    tools = {t.__name__:t for t in content_tools(ws, 'coordinator')}
    while True:
        page = tools['read_object_index'](offset=offset, inventory_digest=fingerprint)
        indexed.extend(entry['ref'] for entry in page['objects'])
        fingerprint = page['inventory_digest']
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    assert indexed == refs
    key = 'tool_observation:' + packet['observation_ref']
    saved = deepcopy(ws.store.get(key))
    chunks, offset = [], 0
    while True:
        page = read_observation(ws, 'coordinator', packet['observation_ref'], offset, 6000)
        assert page['sha256'] == packet['sha256']
        chunks.append(page['text'])
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    assert ''.join(chunks) == encode(status)
    # Synthetic persisted pre-v2 frame: both wire and delivery markers are old,
    # and it has no new-format binding. The owned original is unchanged.
    legacy = deepcopy(packet)
    legacy.pop('representation')
    legacy['metadata'] = {}
    legacy_delivery = {**message.additional_kwargs['report_observation_delivery'],
                       'representation': 'metadata_and_literal_fragments'}
    old = message.model_copy(update={'content': encode(legacy), 'artifact': None,
        'additional_kwargs': {**message.additional_kwargs, 'report_observation_delivery': legacy_delivery}})
    update = await middleware.abefore_model({'messages': [old]}, None)
    changed = update['messages'][0]
    assert (changed.id, changed.tool_call_id) == ('status-message', 'status-call')
    assert json.loads(changed.content)['metadata'] == status
    assert ws.store.get(key) == saved
    assert await middleware.abefore_model({'messages': [changed]}, None) is None
    ws.store.set(key, {**saved, 'owner': 'another-task'})
    assert await middleware.abefore_model({'messages': [old]}, None) is None


def test_index_read_does_not_grant_writing_another_actors_node(ws):
    from report_agent.content_store import Actor
    cs, _, _, refs = populate(ws, 1)
    indexed = object_index(cs, object_type='ContentNode')
    assert indexed['objects']
    with pytest.raises(ActionForbidden):
        cs.commit(Actor('other-writer', 'writer', 'other-task'), 'unauthorized', [{
            'client_key': 'rewrite', 'type': 'ContentNode', 'previous_ref': refs[1],
            'payload': cs.read(refs[1])['payload']}])
