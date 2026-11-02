import json
"""Actual production request binding, SDK/ToolNode/save and recovery."""
from contextlib import contextmanager
from copy import deepcopy
import asyncio

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent.content_tasks import delegated_task
from report_agent.content_store import ContentStore
from report_agent.operation_identity import write_id
from report_agent.review_message import bind_review_message
from report_agent.review_scope_selectors import CONTRACT
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call
from test_review_message import message
from test_selected_companion_reviews import pair, ws
from support.review_message_entry import ReviewEntryProbe


def setup(case, selector=True):
    cs = case[0]
    if selector:
        cs.store.set('manifest', {**cs.store.manifest, 'review_submission_contract': CONTRACT})
    cs, output, criteria, _ = prepared(case)
    return cs, output, criteria


def assignment(output, criteria, key='delegate-a', target='a-body', criterion_index=0):
    return review_call(criteria, identity=key, scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criteria[criterion_index], 'target_ref': output['refs'][target],
        'assessment_kind': 'content', 'extent': 'local_body'}]})


@contextmanager
def bound(cs, call):
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        task = cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        receipt = cs.read_context(actor, task['review_requirements'][0]['target_ref'])['receipt_id']
        yield ws, actor, receipt


@pytest.mark.parametrize('selector', [False, True], ids=['canonical', 'selector'])
@pytest.mark.parametrize('strict', [False, True], ids=['ordinary-wire', 'strict-wire'])
async def test_sdk_flat_call_reaches_native_save(case, monkeypatch, selector, strict):
    cs, output, criteria = setup(case, selector)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], message(), strict=strict)
        result = await bridge.graph().ainvoke({'messages': [answer]})
        assert result['messages'][-1].status == 'success'
        assert result['messages'][-1].tool_call_id == answer.tool_calls[0]['id']
        record, = cs.list_objects('ReviewRecord')
        assert record['payload']['items'][0]['reason'] == message()['assessment']
        assert record['payload']['items'][0]['observations'][0]['receipt_id'] == receipt
        operation = write_id(actor.id, 'submit_review', answer.tool_calls[0]['id'])
        assert cs.receipt(actor, operation)['state'] == 'known_success'
        assert bridge.final_checks and all(x['binding_present'] and x['transaction'] for x in bridge.final_checks)
        assert bridge.context_is_clear()
        assert len(bridge.requests) == 1
        assert bridge.requests[0]['tools'][0]['function'].get('strict', False) is strict
        import json
        from support.task_state_contract import moved_blocks
        part, = [p for p in moved_blocks(bridge.requests[0]['messages'])
                 if p['source'] == 'field_dictionary/current_request']
        packet = json.loads(part['text'])
        assert packet['assigned_scopes'][0]['criterion']['expected_outcome'] == cs.read(criteria[0])['payload']['expected_outcome']
        assert packet['actual_read_receipts'][0]['read']['objects'][0]['object_type'] == 'ContentNode'
        assert 'payload' not in packet['actual_read_receipts'][0]['read']['objects'][0]
        assert actor.id not in json.dumps(packet) and receipt not in json.dumps(packet)
        if strict:
            assert bridge.requests[0]['tools'][0]['function']['strict'] is True
        assert 'review' not in answer.tool_calls[0]['args']
        assert bridge.executed_identities == [operation]


async def test_shared_node_keeps_concurrent_tasks_separate(case, monkeypatch):
    cs, output, criteria = setup(case)
    bridge = ReviewEntryProbe(Workspace(cs.store), monkeypatch)
    graph = bridge.graph()
    async def run(key, target):
        with bound(cs, assignment(output, criteria, key, target, int(key == 'task-b'))) as (_, actor, receipt):
            value = message(assessment=key)
            answer = await bridge.request(actor, [receipt], value, call_id=key)
            await asyncio.sleep(0)
            result = await graph.ainvoke({'messages': [answer]})
            assert result['messages'][-1].status == 'success'
            return actor, receipt
    first, second = await asyncio.gather(run('task-a', 'a-body'), run('task-b', 'a-body'))
    records = cs.list_objects('ReviewRecord')
    assert len(records) == 2
    for actor, receipt in (first, second):
        record, = [r for r in records if r['task_id'] == actor.task_id]
        assert record['owner_id'] == actor.id
        assert record['payload']['items'][0]['observations'][0]['receipt_id'] == receipt
    assert bridge.context_is_clear()


@pytest.mark.parametrize('new_process', [False, True], ids=['same-process-reopen', 'fresh-process-resume'])
@pytest.mark.parametrize('missing_link', [False, True], ids=['binding-retained', 'binding-missing'])
async def test_checkpoint_and_binding_survive_complete_reopen(case, monkeypatch, tmp_path, new_process, missing_link):
    cs, output, criteria = setup(case)
    call = assignment(output, criteria)
    checkpoint = tmp_path / 'entry-checkpoints.db'
    config = {'configurable': {'thread_id': 'saved-entry'}}
    with bound(cs, call) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], message(), strict=True)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint)) as saver:
            graph = bridge.graph(checkpointer=saver, interrupt_before=['tools'])
            await graph.ainvoke({'messages': [answer]}, config)
            assert (await graph.aget_state(config)).next == ('tools',)
        assert not cs.list_objects('ReviewRecord')
        if missing_link:
            bridge.remove_link(actor, answer)
    if new_process:
        import json
        import os
        from pathlib import Path
        import subprocess
        import sys
        intent = tmp_path / 'original-delegation.json'
        intent.write_text(json.dumps(call))
        child = subprocess.run([sys.executable, '-B', str(Path(__file__).parent / 'support/resume_review_message_entry.py'),
            str(cs.store.root), str(checkpoint), str(intent)], check=True, capture_output=True, text=True, timeout=45)
        receipt = json.loads(child.stdout)
        assert receipt['pid'] != os.getpid()
        assert receipt['status'] == ('error' if missing_link else 'success')
        assert receipt['actor_id'] == actor.id and receipt['task_id'] == actor.task_id
        assert receipt['review_count'] == int(not missing_link) and receipt['model_requests'] == 0
        return
    reopened = ContentStore(Store(cs.store.root))
    with bound(reopened, call) as (ws, same_actor, _):
        assert same_actor == actor
        bridge = ReviewEntryProbe(ws, monkeypatch)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint)) as saver:
            graph = bridge.graph(checkpointer=saver, interrupt_before=['tools'])
            pending = await graph.aget_state(config)
            assert pending.values['messages'][-1].tool_calls == answer.tool_calls
            result = await graph.ainvoke(None, config)
            assert result['messages'][-1].status == ('error' if missing_link else 'success')
        assert len(reopened.list_objects('ReviewRecord')) == int(not missing_link)
        assert not bridge.requests  # Reopening tools never replays the model request.
        assert bridge.context_is_clear()


@pytest.mark.parametrize('fault', ['missing-link', 'missing-operation', 'forged-offer',
    'offer-drift', 'receipt-drift', 'save-race'])
async def test_binding_faults_cannot_create_review(case, monkeypatch, fault):
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], message())
        if fault == 'missing-link':
            bridge.remove_link(actor, answer)
        elif fault == 'missing-operation':
            from report_agent.store import digest
            owner = [str(ws.store.root.resolve()), actor.id, actor.task_id]
            key = 'message_call:' + digest([owner, answer.tool_calls[0]['id']])
            link = cs.store.get(key); link['call_id'] = 'another-operation'
            cs.store.set(key, link)
        elif fault == 'forged-offer':
            answer.additional_kwargs['message_contract_offer'] = 'forged'
        elif fault == 'offer-drift':
            ref = answer.additional_kwargs['message_contract_offer']
            value = cs.store.get(ref)
            value['nonce'] = 'changed-after-response'
            cs.store.set(ref, value)
        else:
            def change_receipt():
                with cs.store.connect() as db:
                    db.execute('UPDATE content_observations SET data=data || ? WHERE id=?', (' ', receipt))
            if fault == 'save-race':
                bridge.before_save = change_receipt
            else:
                change_receipt()
        result = await bridge.graph().ainvoke({'messages': [answer]})
        assert result['messages'][-1].status == 'error'
        assert not cs.list_objects('ReviewRecord')
        assert len(bridge.requests) == 1
        assert bridge.context_is_clear()


@pytest.mark.parametrize('index,accepted', [(0, True), (1, False)])
async def test_late_call_uses_its_original_directory(case, monkeypatch, index, accepted):
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], message(evidence_indexes=[index]))
        extra = cs.read_context(actor, output['refs']['b-body'])['receipt_id']
        bind_review_message(cs, actor, [receipt, extra])
        result = await bridge.graph().ainvoke({'messages': [answer]})
        assert (result['messages'][-1].status == 'success') is accepted
        records = cs.list_objects('ReviewRecord')
        assert len(records) == int(accepted)
        if accepted:
            assert records[0]['payload']['items'][0]['observations'][0]['receipt_id'] == receipt


async def test_replay_is_idempotent_and_changed_arguments_are_rejected(case, monkeypatch):
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], message())
        graph = bridge.graph()
        for _ in range(2):
            result = await graph.ainvoke({'messages': [answer]})
            assert result['messages'][-1].status == 'success'
        changed = deepcopy(answer)
        changed.tool_calls[0]['args']['assessment'] = 'Different judgment under the same call ID.'
        result = await graph.ainvoke({'messages': [changed]})
        assert result['messages'][-1].status == 'error'
        assert len(cs.list_objects('ReviewRecord')) == 1
        assert len(bridge.requests) == 1


async def test_foreign_task_cannot_consume_another_response(case, monkeypatch):
    cs, output, criteria = setup(case)
    bridge = ReviewEntryProbe(Workspace(cs.store), monkeypatch)
    with bound(cs, assignment(output, criteria, 'owner-a')) as (_, actor, receipt):
        answer = await bridge.request(actor, [receipt], message())
    with bound(cs, assignment(output, criteria, 'owner-b')):
        result = await bridge.graph().ainvoke({'messages': [answer]})
        assert result['messages'][-1].status == 'error'
    assert not cs.list_objects('ReviewRecord')


async def test_association_write_failure_does_not_replay_model(case, monkeypatch):
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        from report_agent import live_messages
        original = live_messages._once
        def fail_link(store, key, value):
            if key.startswith('message_call:'):
                raise OSError('Synthetic association write failure')
            return original(store, key, value)
        monkeypatch.setattr(live_messages, '_once', fail_link)
        with pytest.raises(OSError, match='association write'):
            await bridge.request(actor, [receipt], message())
        assert len(bridge.requests) == 1
        assert not cs.list_objects('ReviewRecord')


async def test_reused_call_id_cannot_replace_original_association(case, monkeypatch):
    from report_agent.errors import ActionRejected
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        first = await bridge.request(actor, [receipt], message())
        with pytest.raises(ActionRejected, match='BINDING_CONFLICT'):
            await bridge.request(actor, [receipt], message(assessment='New intent with old ID.'))
        result = await bridge.graph().ainvoke({'messages': [first]})
        assert result['messages'][-1].status == 'success'
        assert len(cs.list_objects('ReviewRecord')) == 1
        assert len(bridge.requests) == 2  # Two explicit probes, no automatic retries.


async def test_cancellation_does_not_leak_hidden_context(case, monkeypatch):
    from langgraph.errors import NodeCancelledError
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], message(), call_id='cancelled-save')
        def cancel():
            raise asyncio.CancelledError('Synthetic cancellation before the save transaction.')
        bridge.before_save = cancel
        with pytest.raises(NodeCancelledError) as cancelled:
            await bridge.graph().ainvoke({'messages': [answer]})
        assert isinstance(cancelled.value.__cause__, asyncio.CancelledError)
        assert bridge.context_is_clear()
        assert not cs.list_objects('ReviewRecord')
        next_answer = await bridge.request(actor, [receipt], message(), call_id='next-save')
        result = await bridge.graph().ainvoke({'messages': [next_answer]})
        assert result['messages'][-1].status == 'success'
        assert len(cs.list_objects('ReviewRecord')) == 1


@pytest.mark.parametrize('fault', ['missing-directory', 'changed-material'])
async def test_emitted_dictionary_must_match_the_bound_offer(case, monkeypatch, fault):
    from report_agent.prompt_provenance import PromptCompositionError
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        def corrupt(packet):
            if fault == 'missing-directory':
                packet.pop('actual_read_receipts')
            else:
                packet['actual_read_receipts'][0]['read']['objects'][0]['label_preview'] = 'Wrong material.'
        bridge.before_send = corrupt
        with pytest.raises(PromptCompositionError, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
            await bridge.request(actor, [receipt], message())
        assert not bridge.requests
        assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('strict', [False, True])
async def test_one_sdk_response_preserves_each_call_identity(case, monkeypatch, strict):
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        answer = await bridge.request(actor, [receipt], [message(assessment='First observed judgment.'),
            message(assessment='Second observed judgment.')], strict=strict, call_id='batch')
        assert len(answer.tool_calls) == 2
        result = await bridge.graph().ainvoke({'messages': [answer]})
        assert all(m.status == 'success' for m in result['messages'][-2:])
        assert {m.tool_call_id for m in result['messages'][-2:]} == {'batch-0', 'batch-1'}
        assert len(cs.list_objects('ReviewRecord')) == 2
        assert set(bridge.executed_identities) == {write_id(actor.id, 'submit_review', k) for k in ('batch-0', 'batch-1')}
        assert bridge.context_is_clear() and len(bridge.requests) == 1


async def test_unsupported_strict_schema_is_not_silently_relaxed(case, monkeypatch):
    from report_agent.deepseek_strict import WireError
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        bridge = ReviewEntryProbe(ws, monkeypatch)
        bridge.function['parameters']['properties']['evidence_indexes']['uniqueItems'] = True
        with pytest.raises(WireError, match='uniqueItems'):
            await bridge.request(actor, [receipt], message(), strict=True)
        assert not bridge.requests and not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('strict', [False, True])
async def test_sdk_co_flat_delegation_uses_original_native_task(case, strict):
    from langchain_core.messages import AIMessage
    from report_agent.content_tasks import bound_actor
    from support.review_message_entry import delegate
    from support.flat_task_fixture import task_arguments
    from test_co_review_message import setup_message
    cs, _, _, criteria, snapshot, word, excel = setup_message(case)
    ws, co = Workspace(cs.store), case[1]
    args = task_arguments(cs, co, {'description':'Compare the exact two exports.', 'subagent_type':'reviewer',
        'review': {'deliverable':{'kind':'snapshot','snapshot_ref':snapshot},
            'standards':{'kind':'criteria','criterion_refs':criteria}, 'scope':{'kind':'mapped','items':[
                {'criterion_ref':criteria[2], 'target_ref':snapshot, 'assessment_kind':'export','artifact_refs':[word,excel]}]}}})
    before = deepcopy(args)
    called = []
    def child(state):
        actor = bound_actor(ws, 'reviewer', None)
        called.append(cs.read({'type':'DelegatedTask','id':actor.task_id,'version':1})['payload'])
        return {'messages':[AIMessage('Assigned work remains unperformed; no acceptance.')]}
    requests = []
    result, answer = await delegate(ws, args, child, strict, requests)
    assert result['messages'][-1].status == 'success', result['messages'][-1].content
    assert answer.tool_calls[0]['args'] == args == before
    assert called[0]['review_requirements'][0]['criterion_ref'] == criteria[2]
    assert called[0]['review_requirements'][0]['artifact_refs'] == [word, excel]
    assert not cs.list_objects('ReviewRecord') and len(requests) == 1


async def test_strict_co_to_reviewer_saves_actual_word_excel_review(pair, monkeypatch):
    from langchain_core.messages import AIMessage
    from report_agent.content_tasks import bound_actor
    from report_agent.content_export import read_export
    from report_agent.content_delivery import current_delivery
    from support.review_message_entry import delegate
    from support.flat_task_fixture import task_arguments
    workspace, cs, co, snapshot, _, refs, word, excel, _ = pair
    workspace.store.set('manifest', {**workspace.store.manifest,
        'review_execution_mode':'native-reviewer-v2', 'review_interface_profile':'review-interfaces-v4',
        'delegation_prompt_profile':'separate-description-v1', 'operation_identity_profile':'native-tool-runtime-v1',
        'review_submission_contract':CONTRACT})
    args = task_arguments(cs, co, {'description':'Compare the actual Word and Excel exports; retain limitations.',
        'subagent_type':'reviewer','review':{'deliverable':{'kind':'snapshot','snapshot_ref':snapshot},
        'standards':{'kind':'criteria','criterion_refs':[refs['k']]}, 'scope':{'kind':'mapped','items':[
            {'criterion_ref':refs['k'],'target_ref':snapshot,'assessment_kind':'export','artifact_refs':[word,excel]}]}}})
    reviewer_requests = []
    async def child(state):
        reviewer = bound_actor(workspace, 'reviewer', None)
        receipts = [read_export(cs, reviewer, ref)['receipt_id'] for ref in (word, excel)]
        probe = ReviewEntryProbe(workspace, monkeypatch)
        response = await probe.request(reviewer, receipts,
            message(verdict='not_satisfied', assessment='Synthetic discrepancy retained.', evidence_indexes=[0,1]),
            strict=True, call_id='review-real-exports')
        result = await probe.graph().ainvoke({'messages':[response]})
        assert result['messages'][-1].status == 'success', result['messages'][-1].content
        from support.task_state_contract import moved_blocks
        part, = [p for p in moved_blocks(probe.requests[0]['messages'])
                 if p['source'] == 'field_dictionary/current_request']
        packet = json.loads(part['text'])
        reads = [v['read'] for v in packet['actual_read_receipts']]
        assert [v['export']['format'] for v in reads] == ['docx','xlsx']
        assert all(v['text_characters'] and v['limitation'] for v in reads)
        reviewer_requests.extend(probe.requests)
        assert probe.final_checks and probe.context_is_clear()
        return {'messages':[AIMessage('Saved scoped negative review; no whole-report acceptance.')]}
    requests = []
    result, _ = await delegate(workspace, args, child, True, requests, 'co-real-exports')
    assert result['messages'][-1].status == 'success', result['messages'][-1].content
    record, = cs.list_objects('ReviewRecord')
    assert record['payload']['items'][0]['artifact_refs'] == [word,excel]
    assert record['payload']['items'][0]['verdict'] == 'not_satisfied'
    assert current_delivery(workspace.store)['confirmed_violations']
    assert len(requests) == len(reviewer_requests) == 1
    assert requests[0]['tools'][0]['function']['strict'] is True
    assert reviewer_requests[0]['tools'][0]['function']['strict'] is True
