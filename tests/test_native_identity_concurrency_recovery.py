"""Registered native IDs against real temporary SQLite; no provider or Office calls."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from threading import Barrier

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.operation_identity import write_id
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_native_operation_identity import activate, graph_for
from test_native_write_identity import dispatch, heading, native_tools
from test_task_supervision import ws, offline
from test_text_work import writer_call


def rows(contents, identities):
    with contents.store.connect() as db:
        return [db.execute('SELECT * FROM content_operations WHERE operation_id=?', (identity,)).fetchone()
                for identity in identities]


def simultaneous(function, calls):
    barrier = Barrier(len(calls))
    def invoke(call_id, args):
        barrier.wait(timeout=15)
        try:
            result = function.invoke({'type': 'tool_call', 'name': 'commit_objects', 'id': call_id, 'args': args})
            return json.loads(result.content)
        except ActionRejected as error:
            return error
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(copy_context().run, invoke, call_id, args) for call_id, args in calls]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_same_native_call_has_one_atomic_effect_and_receipt(ws):
    activate(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        function = native_tools(ws, 'writer')['commit_objects']
        results = simultaneous(function, [('same-call', heading()), ('same-call', heading())])
        assert results[0] == results[1]
        identity = write_id(actor.id, 'commit_objects', 'same-call')
        assert results[0]['operation_id'] == results[0]['receipt_id'] == identity
        contents = ContentStore(ws.store)
        assert len(contents.list_objects('ContentNode')) == 1
        assert len([row for row in rows(contents, [identity]) if row]) == 1
        assert contents.receipt(actor, identity)['response']['result'] == results[0]['result']


def test_concurrent_same_native_call_with_different_arguments_conflicts_without_extra_effect(ws):
    activate(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        function = native_tools(ws, 'writer')['commit_objects']
        results = simultaneous(function, [('same-call', heading('First')), ('same-call', heading('Second'))])
        successes = [result for result in results if isinstance(result, dict)]
        errors = [result for result in results if isinstance(result, ActionRejected)]
        assert len(successes) == len(errors) == 1
        assert 'OPERATION_CONFLICT' in str(errors[0])
        contents = ContentStore(ws.store)
        identity = write_id(actor.id, 'commit_objects', 'same-call')
        assert len(contents.list_objects('ContentNode')) == 1
        assert contents.receipt(actor, identity)['response']['result'] == successes[0]['result']


def test_concurrent_distinct_native_calls_are_not_deduplicated_by_equal_arguments(ws):
    activate(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        function = native_tools(ws, 'writer')['commit_objects']
        results = simultaneous(function, [('call-one', heading()), ('call-two', heading())])
        identities = [write_id(actor.id, 'commit_objects', call_id) for call_id in ('call-one', 'call-two')]
        assert {result['operation_id'] for result in results} == set(identities)
        assert len(set(identities)) == 2
        contents = ContentStore(ws.store)
        assert all(rows(contents, identities))
        assert len(contents.list_objects('ContentNode')) == 2
        assert results[0]['result']['refs'] != results[1]['result']['refs']


async def test_native_atomic_receipt_survives_store_and_checkpoint_reopening(ws, tmp_path):
    activate(ws)
    checkpoint = str(tmp_path / 'atomic-checkpoint.db')
    config = {'configurable': {'thread_id': 'native-atomic-recovery'}}
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        function = native_tools(ws, 'writer')['commit_objects']
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            graph = graph_for(function, saver)
            result = await graph.ainvoke({'messages': [AIMessage('', tool_calls=[{
                'name': 'commit_objects', 'id': 'persisted-atomic-call', 'type': 'tool_call', 'args': heading()}])]}, config)
            first = json.loads(result['messages'][-1].content)
            history = [state async for state in graph.aget_state_history(config)]
            pending = next(state for state in history if state.next == ('tools',))
        identity = write_id(actor.id, 'commit_objects', 'persisted-atomic-call')
        original = rows(ContentStore(ws.store), [identity])
        task_id = actor.task_id
    reopened = Workspace(Store(ws.store.root))
    resume = writer_call('resume-saved-owner')
    resume['args']['resume_content_task_id'] = task_id
    with delegated_task(reopened, 'coordinator', resume) as (_, recovered_actor):
        assert recovered_actor.id == actor.id
        function = native_tools(reopened, 'writer')['commit_objects']
        async with AsyncSqliteSaver.from_conn_string(checkpoint) as saver:
            replay = await graph_for(function, saver).ainvoke(None, pending.config)
        assert json.loads(replay['messages'][-1].content) == first
        contents = ContentStore(reopened.store)
        assert rows(contents, [identity]) == original
        assert len(contents.list_objects('ContentNode')) == 1
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await dispatch(function, 'persisted-atomic-call', heading('Different recovered request'))
        assert rows(contents, [identity]) == original


def test_legacy_atomic_interface_still_uses_explicit_id_after_reopening(ws):
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        function = native_tools(ws, 'writer')['commit_objects']
        first = function('caller-selected-id', heading()['objects'])
        task_id = actor.task_id
    reopened = Workspace(Store(ws.store.root))
    resume = writer_call('legacy-resume')
    resume['args']['resume_content_task_id'] = task_id
    with delegated_task(reopened, 'coordinator', resume) as (_, recovered_actor):
        function = native_tools(reopened, 'writer')['commit_objects']
        assert function('caller-selected-id', heading()['objects']) == first
        assert ContentStore(reopened.store).receipt(recovered_actor, 'caller-selected-id')['state'] == 'known_success'
        assert len(ContentStore(reopened.store).list_objects('ContentNode')) == 1
