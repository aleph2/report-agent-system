"""Filtered pagination consistency with actual stores and native tool plumbing."""
import json

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_store import Actor
from report_agent.deep_runtime import run_report
from report_agent.errors import ActionRejected
from report_agent.object_index import object_index
from report_agent.store import digest, encode
from test_hierarchical_content import ws
from test_object_index import populate
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, observation


def add_relation(cs, actor, root, target):
    with cs.store.connect() as db:
        return cs._insert(db, actor, 'Relation', {'subject_ref':root, 'object_ref':target,
            'predicate':'contains', 'position':999, 'provenance_kind':'adopted_during_generation'})


def test_relation_addition_preserves_filtered_cursor_but_changes_auxiliary_count(ws):
    cs, actor, root, refs = populate(ws, 30)
    filters = {'object_type':'ContentNode', 'owner_id':actor.id}
    first = object_index(cs, **filters)
    continuation_before = object_index(cs, first['next_offset'], inventory_digest=first['inventory_digest'], **filters)
    add_relation(cs, actor, root, refs[1])
    after = object_index(cs, first['next_offset'], inventory_digest=first['inventory_digest'], **filters)
    assert after['objects'] == continuation_before['objects']
    assert after['inventory_digest'] == first['inventory_digest']
    assert after['available_types']['Relation'] == first['available_types']['Relation'] + 1
    assert 'may change independently' in after['scope_note']
    assert len(encode(after)) <= 5800


def test_other_owner_addition_does_not_change_owner_filtered_cursor(ws):
    cs, actor, root, refs = populate(ws, 30)
    first = object_index(cs, object_type='ContentNode', owner_id=actor.id)
    with cs.store.connect() as db:
        cs._insert(db, Actor('another-author','writer','another-task'), 'ContentNode', cs.read(root)['payload'])
    after = object_index(cs, first['next_offset'], object_type='ContentNode', owner_id=actor.id,
                         inventory_digest=first['inventory_digest'])
    assert after['inventory_digest'] == first['inventory_digest'] and after['total'] == first['total']


@pytest.mark.parametrize('current_only', [False, True])
def test_selected_new_version_still_invalidates_cursor(ws, current_only):
    cs, actor, root, refs = populate(ws, 30)
    first = object_index(cs, object_type='ContentNode', current_only=current_only)
    cs.commit(actor, 'revise', [{'client_key':'changed', 'type':'ContentNode', 'previous_ref':refs[1],
        'payload':{**cs.read(refs[1])['payload'], 'body':{'text':'Revised selected node'}}}])
    with pytest.raises(ActionRejected, match='OBJECT_INDEX_CHANGED'):
        object_index(cs, first['next_offset'], object_type='ContentNode', current_only=current_only,
                     inventory_digest=first['inventory_digest'])


def test_unfiltered_cursor_still_binds_added_relation(ws):
    cs, actor, root, refs = populate(ws, 30)
    first = object_index(cs)
    add_relation(cs, actor, root, refs[1])
    with pytest.raises(ActionRejected, match='OBJECT_INDEX_CHANGED'):
        object_index(cs, first['next_offset'], inventory_digest=first['inventory_digest'])


@pytest.mark.parametrize('field,value', [('owner_id','different-owner'), ('task_id','different-task'),
                                         ('payload_digest','changed-digest')])
def test_selected_record_metadata_remains_in_cursor(ws, field, value):
    cs, actor, root, refs = populate(ws, 30)
    first = object_index(cs, object_type='ContentNode')
    # Fault-injected persisted metadata change; not an authorized content edit API.
    with cs.store.connect() as db:
        rowid, raw = db.execute("SELECT rowid,data FROM content_versions WHERE type='ContentNode' LIMIT 1").fetchone()
        record = json.loads(raw)
        record[field] = value
        db.execute('UPDATE content_versions SET data=? WHERE rowid=?', (encode(record), rowid))
    with pytest.raises(ActionRejected, match='OBJECT_INDEX_CHANGED'):
        object_index(cs, first['next_offset'], object_type='ContentNode', inventory_digest=first['inventory_digest'])


def test_legacy_cursor_rejected_once_instead_of_accepted_without_equivalence(ws):
    cs, actor, root, refs = populate(ws, 30)
    first = object_index(cs, object_type='ContentNode')
    selected = cs.list_objects('ContentNode')
    old_digest = digest({'filters':first['filters'], 'available_types':first['available_types'], 'objects':[
        {'ref':r['ref'], 'payload_digest':r['payload_digest'], 'owner_id':r['owner_id'],
         'task_id':r['task_id'], 'head_version':1} for r in selected]})
    assert old_digest != first['inventory_digest']
    with pytest.raises(ActionRejected, match='OBJECT_INDEX_CHANGED'):
        object_index(cs, first['next_offset'], object_type='ContentNode', inventory_digest=old_digest)
    assert object_index(cs, object_type='ContentNode')['inventory_digest'] == first['inventory_digest']


async def test_actual_native_filtered_paging_survives_unrelated_relation_write(ws):
    cs, actor, root, refs = populate(ws, 30)
    activate(ws)
    pages = []
    def next_page(messages):
        page = observation(messages, 'read_object_index')
        pages.append(page)
        add_relation(cs, actor, root, refs[1])
        return invoke('read_object_index', object_type='ContentNode', owner_id=actor.id,
                      offset=page['next_offset'], inventory_digest=page['inventory_digest'])
    def done(messages):
        pages.append(observation(messages, 'read_object_index'))
        return AIMessage(content='Metadata navigation checked; no semantic acceptance.')
    driver = Driver(coordinator=[invoke('read_object_index', object_type='ContentNode', owner_id=actor.id), next_page, done])
    await run_report(ws, driver)
    assert len(pages) == 2 and pages[0]['inventory_digest'] == pages[1]['inventory_digest']
    assert not ({encode(r['ref']) for r in pages[0]['objects']} & {encode(r['ref']) for r in pages[1]['objects']})
    schema = next(t for t in driver.bindings['coordinator'][0] if t['name']=='read_object_index')
    assert 'changed filtered inventory' in schema['description']
