"""Synthetic native child recovery after a local checkpoint-adjacent interruption."""
import sqlite3
import hashlib
import json
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from langchain_core.messages import AIMessage, ToolMessage

from report_agent.deep_runtime import run_report
from report_agent.execution_progress import ExecutionProgress
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke
from test_deliverable_declaration_v4 import case


async def test_writer_checkpoint_resumes_same_native_task_after_local_busy(case, monkeypatch):
    cs, _, _, _, _ = case
    ws = Workspace(cs.store)
    manifest = ws.store.manifest
    cs.store.set('manifest', {**manifest, 'context_policy':'stateful-tools-v2',
        'execution_progress_policy':{'version':1, 'window':64, 'repeats':3, 'after_notice':2}})
    seen = []
    original = ExecutionProgress.save
    failures = []

    def local_failure(self, *args, **kwargs):
        if self.role == 'writer' and seen and not failures:
            failures.append('busy')
            reader = sqlite3.connect(self.workspace.store.path)
            try:
                reader.execute('BEGIN')
                reader.execute('SELECT value FROM state LIMIT 1').fetchone()
                return original(self, *args, **kwargs)
            finally:
                reader.close()
        return original(self, *args, **kwargs)

    def after_calculation(messages):
        seen.append('writer continued')
        return AIMessage(content='Synthetic writer work completed.')

    def first_tool(messages):
        seen.append('writer requested calculation')
        return invoke('calculate', terms=[['2','3']])

    monkeypatch.setattr(ExecutionProgress, 'save', local_failure)
    first = Driver(coordinator=[invoke('task', subagent_type='writer', description='Write from sources.'),
                                AIMessage(content='Synthetic coordinator complete.')],
                   writer=[first_tool, after_calculation])
    result = await run_report(ws, first)
    assert failures == ['busy']
    assert result['last_error'] is not None
    assert seen == ['writer requested calculation']
    monkeypatch.setattr(ExecutionProgress, 'save', original)
    resumed = Driver(coordinator=[AIMessage(content='unused'), AIMessage(content='Synthetic coordinator complete.')],
                     writer=[first_tool, after_calculation])
    from report_agent.supervision_plugins import local_busy_resume
    event = next(e['data'] for e in cs.store.events() if e['kind'] == 'native_delegation_reserved')
    diagnostic_id = result['last_error']['diagnostic_id']
    diagnostic = cs.store.root/'diagnostics'/'private'/(diagnostic_id+'.json')
    with local_busy_resume(cs.store, call_id=event['native_tool_call_id'], task_id=event['task_id'],
                           diagnostic_id=diagnostic_id, diagnostic_sha256=hashlib.sha256(diagnostic.read_bytes()).hexdigest()):
        final = await run_report(Workspace(Store(cs.store.root)), resumed)
    assert final['last_error'] is None
    assert seen == ['writer requested calculation', 'writer continued']
    events = [e['data'] for e in cs.store.events() if e['kind'] == 'native_delegation_reserved']
    assert len(events) == 1
    assert any(role == 'coordinator' and any(isinstance(m, ToolMessage) and m.name == 'task' and
               'Synthetic writer work completed.' in m.content for m in messages)
               for role, _, messages in resumed.calls)


def fake_diagnostic(store, *, exception_type='OperationalError', code=5):
    identifier = 'synthetic-local-busy'
    path = store.root/'diagnostics'/'private'/(identifier+'.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'id':identifier, 'phase':'native_graph', 'at':'2026-01-02T00:00:00+00:00',
        'exceptions':[{'type':exception_type, 'sqlite_errorcode':code, 'frames':[
            {'file':'/x/execution_progress.py','function':'abefore_model'},
            {'file':'/x/execution_progress.py','function':'save'},
            {'file':'/x/store.py','function':'connect'}]}]}
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    return identifier, hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('mutation', [
    'not_resuming', 'wrong_call', 'wrong_task', 'wrong_digest', 'already_returned',
    'missing_child', 'wrong_namespace', 'wrong_root_head', 'wrong_role', 'later_head',
    'model_node_busy', 'summary_node_busy', 'unknown_external', 'multiple_errors'])
async def test_resume_permit_rejects_unproven_boundaries(case, mutation):
    from report_agent.store import digest
    from report_agent.supervision_plugins import local_busy_resume, _resume_original_checkpoint
    cs, _, actor, task, _ = case
    call = {'id':'same-call', 'args':{'description':'fixture'}}
    previous = {'task_id':actor.task_id, 'native_tool_call_id':call['id'],
        'request_digest':digest({'actor':actor.__dict__, 'call':call}), 'state':'reserved'}
    checkpoint = {'ts':'2026-01-01T00:00:00+00:00', 'channel_versions':{'a':1},
        'channel_values':{'branch:to:ExecutionProgress.before_model':None}}
    saved = SimpleNamespace(config={'configurable':{'thread_id':'report','checkpoint_ns':'tools:graph-task'}},
        metadata={'parents':{'':'root-head'},'lc_agent_name':'writer'}, checkpoint=checkpoint,
        pending_writes=[('node','__error__',"OperationalError('database is locked')")])
    class Saver:
        async def aget_tuple(self, config):
            await asyncio.sleep(0)
            return saved
    cfg = {'thread_id':'report','checkpoint_ns':'tools:graph-task','__pregel_task_id':'graph-task',
        '__pregel_resuming':True,'checkpoint_map':{'':'root-head'},'__pregel_checkpointer':Saver()}
    runtime = SimpleNamespace(config={'configurable':cfg})
    if mutation == 'not_resuming': cfg['__pregel_resuming'] = False
    if mutation == 'wrong_call': call['id'] = 'different-call'
    if mutation == 'wrong_task': previous['task_id'] = 'different-task'
    if mutation == 'wrong_digest': previous['request_digest'] = '0'*64
    if mutation == 'already_returned': previous['state'] = 'returned'
    if mutation == 'missing_child': saved = None
    if mutation == 'wrong_namespace': cfg['checkpoint_ns'] = 'tools:other'
    if mutation == 'wrong_root_head': saved.metadata['parents'] = {'':'other'}
    if mutation == 'wrong_role': saved.metadata['lc_agent_name'] = 'reviewer'
    if mutation == 'later_head': saved.checkpoint['ts'] = '2026-01-03T00:00:00+00:00'
    if mutation == 'model_node_busy': saved.checkpoint['channel_values'] = {'branch:to:model':None}
    if mutation == 'summary_node_busy': saved.checkpoint['channel_values'] = {'branch:to:WorkingSummary.before_model':None}
    if mutation == 'unknown_external': saved.pending_writes = [('node','__error__',"APIConnectionError('outcome unknown')")]
    if mutation == 'multiple_errors': saved.pending_writes.append(('other','__error__',"OperationalError('database is locked')"))
    identifier, sha = fake_diagnostic(cs.store)
    with local_busy_resume(cs.store,call_id='same-call',task_id=actor.task_id,
                           diagnostic_id=identifier,diagnostic_sha256=sha):
        assert not await _resume_original_checkpoint(cs, actor, call, previous, runtime)


async def test_resume_permit_is_consumed_once_with_concurrent_attempts(case):
    from report_agent.store import digest
    from report_agent.supervision_plugins import local_busy_resume, _resume_original_checkpoint
    cs, _, actor, _, _ = case
    call={'id':'same-call','args':{'description':'fixture'}}
    previous={'task_id':actor.task_id,'native_tool_call_id':call['id'],
              'request_digest':digest({'actor':actor.__dict__,'call':call}),'state':'reserved'}
    class Saver:
        async def aget_tuple(self,config):
            await asyncio.sleep(0)
            return SimpleNamespace(config={'configurable':{'thread_id':'report','checkpoint_ns':'tools:graph-task','checkpoint_id':'child-head'}},
                metadata={'parents':{'':'root-head'},'lc_agent_name':'writer'},
                checkpoint={'ts':'2026-01-01T00:00:00+00:00','channel_versions':{'a':1},
                            'channel_values':{'branch:to:ExecutionProgress.before_model':None}},
                pending_writes=[('node','__error__',"OperationalError('database is locked')")])
    runtime=SimpleNamespace(config={'configurable':{'thread_id':'report','checkpoint_ns':'tools:graph-task',
        '__pregel_task_id':'graph-task','__pregel_resuming':True,'checkpoint_map':{'':'root-head'},'__pregel_checkpointer':Saver()}})
    identifier,sha=fake_diagnostic(cs.store)
    receipts=[]
    with local_busy_resume(cs.store,call_id=call['id'],task_id=actor.task_id,
                           diagnostic_id=identifier,diagnostic_sha256=sha,on_verified=receipts.append):
        result=await asyncio.gather(*[_resume_original_checkpoint(cs,actor,call,deepcopy(previous),runtime) for _ in range(2)])
    assert sorted(result)==[False,True]
    assert len(receipts)==1 and receipts[0]['checkpoint_id']=='child-head'
    assert receipts[0]['node']=='ExecutionProgress.before_model'


@pytest.mark.parametrize('exception_type,code', [('APIConnectionError',5),('OperationalError',10)])
def test_resume_rejects_nonlocal_or_nonbusy_diagnostic(case, exception_type, code):
    from report_agent.errors import ActionRejected
    from report_agent.supervision_plugins import local_busy_resume
    cs, _, actor, _, _ = case
    identifier,sha=fake_diagnostic(cs.store,exception_type=exception_type,code=code)
    with pytest.raises(ActionRejected,match='NATIVE_RESUME_DIAGNOSTIC_INVALID'):
        with local_busy_resume(cs.store,call_id='same-call',task_id=actor.task_id,
                               diagnostic_id=identifier,diagnostic_sha256=sha):
            pass
