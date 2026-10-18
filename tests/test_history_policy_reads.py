"""History recovery cost and evidence boundaries through the real middleware."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.decision_data import (
    POLICY, refresh_history_observations, refresh_producer_observation,
    refresh_status_observation,
)
from report_agent.selection_observations import refresh as refresh_selection
from report_agent.hierarchical_tools import content_tools
from report_agent.store import encode
from report_agent.task_context import TaskContext
from test_decision_data import activate
from test_producer_observations import old_packet
from test_selection_observations import prepare, observe, as_old
from test_task_supervision import ws, offline


def legacy_messages(ws):
    _, refs, snap = prepare(ws, 2)
    producer = old_packet(ws)
    status = {t.__name__: t for t in content_tools(ws, 'coordinator')}['content_status']()
    shown_status = TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        content=encode(status), name='content_status', id='status-msg', tool_call_id='status-call'))
    _, selection = observe(ws, snap, [{'ref': refs['0'], 'offset': 4, 'limit': 7}])
    return [producer, as_old(shown_status), as_old(selection)]


def count_manifest_reads(ws, monkeypatch):
    original = ws.store.get
    reads = []
    def get(key, *args, **kwargs):
        if key == 'manifest':
            reads.append(key)
        return original(key, *args, **kwargs)
    monkeypatch.setattr(ws.store, 'get', get)
    return reads


async def test_non_target_history_avoids_manifest_reads_without_changing_messages(ws, monkeypatch):
    activate(ws)
    messages = []
    for i in range(80):
        messages.extend([
            HumanMessage(content='Use the actual source.', id=f'h-{i}'),
            AIMessage(content='Next independent decision.', id=f'a-{i}'),
            ToolMessage(content='{"objects": []}', name='read_object_index',
                        id=f't-{i}', tool_call_id=f'call-{i}'),
        ])
    before = [m.model_dump() for m in messages]
    reads = count_manifest_reads(ws, monkeypatch)
    assert await TaskContext(ws, 'coordinator').abefore_model({'messages': messages}, None) is None
    assert reads == []
    assert [m.model_dump() for m in messages] == before


async def test_mixed_real_receipts_use_one_policy_read_and_repair_once(ws, monkeypatch):
    messages = legacy_messages(ws)
    originals = {json.loads(m.content)['observation_ref']: deepcopy(ws.store.get(
        'tool_observation:' + json.loads(m.content)['observation_ref'])) for m in messages}
    reads = count_manifest_reads(ws, monkeypatch)
    update = await TaskContext(ws, 'coordinator').abefore_model({'messages': messages}, None)
    assert len(reads) == 1
    changed = update['messages']
    assert len(changed) == 3
    for old, new in zip(messages, changed):
        assert (new.id, new.tool_call_id, new.name, new.status) == (old.id, old.tool_call_id, old.name, old.status)
        old_value, new_value = json.loads(old.content), json.loads(new.content)
        assert (new_value['observation_ref'], new_value['sha256']) == (old_value['observation_ref'], old_value['sha256'])
    producer, status, selection = [json.loads(m.content)['metadata'] for m in changed]
    assert producer['outputs']['entries'][0]['qualifiers']['limitations'] == 'Original unresolved constraint.'
    assert status==json.loads(originals[json.loads(messages[1].content)['observation_ref']]['text'])
    assert selection['result']['selections'][0]['selected_range'] == [4, 11]
    for ref, original in originals.items():
        assert ws.store.get('tool_observation:' + ref) == original
    reads.clear()
    assert await TaskContext(ws, 'coordinator').abefore_model({'messages': changed}, None) is None
    assert reads == []
    for kind in ('producer', 'status', 'selection'):
        assert sum(e['kind'] == kind + '_observation_reprojected' for e in ws.store.events()) == 1


async def test_policy_is_current_for_each_pass_including_disabled_policy(ws, monkeypatch):
    messages = legacy_messages(ws)
    enabled_manifest = deepcopy(ws.store.manifest)
    ws.store.set('manifest', {**enabled_manifest, 'decision_data_policy': None})
    reads = count_manifest_reads(ws, monkeypatch)
    assert await TaskContext(ws, 'coordinator').abefore_model({'messages': messages}, None) is None
    assert len(reads) == 1
    ws.store.set('manifest', enabled_manifest)
    reads.clear()
    update = await TaskContext(ws, 'coordinator').abefore_model({'messages': messages}, None)
    assert len(reads) == 1 and len(update['messages']) == 3


@pytest.mark.parametrize('index,helper', list(enumerate([
    refresh_producer_observation, refresh_status_observation, refresh_selection])))
def test_standalone_recovery_retains_current_policy_check(ws, monkeypatch, index, helper):
    message = legacy_messages(ws)[index]
    active = deepcopy(ws.store.manifest)
    ws.store.set('manifest', {**active, 'decision_data_policy': None})
    reads = count_manifest_reads(ws, monkeypatch)
    assert helper(ws, 'coordinator', message) is message
    assert len(reads) == 1
    ws.store.set('manifest', active)
    assert helper(ws, 'coordinator', message) is not message
    assert len(reads) == 2


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('tamper', ['owner', 'sha', 'missing'])
def test_shared_policy_never_bypasses_per_message_original_checks(ws, monkeypatch, index, tamper):
    messages = legacy_messages(ws)
    target = messages[index]
    ref = json.loads(target.content)['observation_ref']
    key = 'tool_observation:' + ref
    saved = ws.store.get(key)
    if tamper == 'missing':
        ws.store.set(key, None)
    elif tamper == 'sha':
        ws.store.set(key, {**saved, 'text': saved['text'] + ' '})
    else:
        ws.store.set(key, {**saved, 'owner': 'foreign-task'})
    reads = count_manifest_reads(ws, monkeypatch)
    changed = refresh_history_observations(ws, 'coordinator', messages)
    assert len(reads) == 1
    assert changed[index] is target
    assert all(old is not new for i, (old, new) in enumerate(zip(messages, changed)) if i != index)


@pytest.mark.parametrize('index', [0, 2])
def test_shared_policy_still_requires_original_producer_or_selection_receipt(ws, index):
    messages = legacy_messages(ws)
    target = messages[index]
    saved = ws.store.get('tool_observation:' + json.loads(target.content)['observation_ref'])
    original = json.loads(saved['text'])
    if index == 0:
        ws.store.set('text_work_receipt:' + original['text_work_id'], {'state': 'reserved'})
    else:
        with ws.store.connect() as db:
            db.execute('UPDATE content_observations SET actor_id=? WHERE id=?',
                       ('foreign-task', original['receipt_id']))
    changed = refresh_history_observations(ws, 'coordinator', messages)
    assert changed[index] is target
    assert all(old is not new for i, (old, new) in enumerate(zip(messages, changed)) if i != index)
