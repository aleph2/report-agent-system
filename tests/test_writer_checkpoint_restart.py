"""Synthetic native child recovery after a local checkpoint-adjacent interruption."""
import hashlib
import json
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from langchain_core.messages import AIMessage, ToolMessage

from report_agent.deep_runtime import run_report
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke
from test_deliverable_declaration_v4 import case


async def test_legacy_raw_busy_checkpoint_resumes_same_native_writer_task(case, monkeypatch):
    """Resume a real accepted-e raw-busy checkpoint; typed busy stays covered in G1."""
    from pathlib import Path
    import subprocess,sys
    from report_agent.content_store import ContentStore
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'tests/fixtures/e_busy_checkpoint.json').read_text())
    generator=root/manifest['generator'];accepted=root.parent/'stage1-main'
    if not generator.is_file() or not accepted.is_dir():
        pytest.skip('Private accepted-e fixture generator required for qualification')
    assert hashlib.sha256(generator.read_bytes()).hexdigest()==manifest['generator_sha256']
    target=case[0].store.root
    proof_path=target/'accepted-e-busy-proof.json'
    # Request ownership includes the absolute case path; generate e and resume here.
    generated=subprocess.run([sys.executable,'-B',str(generator),str(accepted),str(target),str(proof_path)],
        cwd=accepted,capture_output=True,text=True)
    assert generated.returncode==0,(generated.stdout,generated.stderr)
    proof=json.loads(proof_path.read_text())
    assert proof['source_commit']==manifest['source_commit'] and proof['source_sha256']==manifest['source_sha256']
    assert proof['case_path']==str(target.resolve())
    ws=Workspace(Store(target));cs=ContentStore(ws.store)
    tasks=cs.list_objects('DelegatedTask')
    result=proof['result'];assert result['last_error']['type']=='OperationalError'
    diagnostic_id=result['last_error']['diagnostic_id']
    diagnostic=target/'diagnostics/private'/(diagnostic_id+'.json')
    assert hashlib.sha256(diagnostic.read_bytes()).hexdigest()==proof['diagnostic_sha256']
    assert any(row.get('sqlite_errorcode')==5 for row in json.loads(diagnostic.read_text())['exceptions'])
    seen=[]
    def first_tool(messages):
        seen.append('writer requested calculation')
        return invoke('calculate',terms=[['2','3']])
    def after_calculation(messages):
        seen.append('writer continued')
        return AIMessage(content='Synthetic writer work completed.')
    resumed=Driver(coordinator=[AIMessage(content='unused'),AIMessage(content='Synthetic coordinator complete.')],
        writer=[first_tool,after_calculation])
    from report_agent import run_authority
    event=proof['reservation']
    authority={'continuations':{'resume':{'checkpoint_id':proof['root_head']}}}
    admission=run_authority._native_continuation_heads(ws,authority,'resume')
    limits={scope:run_authority.OFFLINE_GRAPH_STEP_LIMIT for scope in ('root','assessment')}
    active=run_authority._active.set({'_native_continuation':admission,'graph_limits':limits})
    try:
        final=await run_report(ws,resumed,continue_from_checkpoint=proof['root_head'])
    finally:
        run_authority._active.reset(active)
    assert len(admission['used'])==1
    assert final['last_error'] is None,final
    assert seen==['writer continued'] and resumed.calls[0][:2]==('writer',1)
    assert cs.list_objects('DelegatedTask')==tasks
    events=[e['data'] for e in cs.store.events() if e['kind']=='native_delegation_reserved']
    assert events==[event]
    assert any(role=='coordinator' and any(isinstance(m,ToolMessage) and m.name=='task' and
        'Synthetic writer work completed.' in m.content for m in messages) for role,_,messages in resumed.calls)


@pytest.mark.parametrize('mutation', [
    'not_resuming', 'wrong_call', 'wrong_task', 'wrong_digest', 'already_returned',
    'missing_child', 'wrong_namespace', 'wrong_root_head', 'wrong_role', 'later_head',
    'model_node_busy', 'summary_node_busy', 'unknown_external', 'multiple_errors'])
async def test_resume_permit_rejects_unproven_boundaries(case, mutation):
    from report_agent.store import digest
    from report_agent.supervision_plugins import _resume_original_checkpoint
    from report_agent import run_authority
    cs, _, actor, task, _ = case
    call = {'id':'same-call', 'args':{'description':'fixture'}}
    previous = {'task_id':actor.task_id, 'native_tool_call_id':call['id'],
        'request_digest':digest({'actor':actor.__dict__, 'call':call}), 'state':'reserved'}
    checkpoint = {'ts':'2026-01-01T00:00:00+00:00', 'channel_versions':{'a':1},
        'channel_values':{'branch:to:ExecutionProgress.before_model':None}}
    saved = SimpleNamespace(config={'configurable':{'thread_id':'report','checkpoint_ns':'tools:graph-task','checkpoint_id':'child-head'}},
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
    if mutation == 'later_head': saved.config['configurable']['checkpoint_id']='later-head'
    if mutation == 'model_node_busy': saved.checkpoint['channel_values'] = {'branch:to:model':None}
    if mutation == 'summary_node_busy': saved.checkpoint['channel_values'] = {'branch:to:WorkingSummary.before_model':None}
    if mutation == 'unknown_external': saved.pending_writes = [('node','__error__',"APIConnectionError('outcome unknown')")]
    if mutation == 'multiple_errors': saved.pending_writes.append(('other','__error__',"OperationalError('database is locked')"))
    admission={'case_path':str(cs.store.root.resolve()),'root_checkpoint_id':'root-head',
               'heads':{'tools:graph-task':'child-head'},'used':set()}
    active=run_authority._active.set({'_native_continuation':admission})
    try:
        allowed=await _resume_original_checkpoint(cs,actor,call,previous,runtime)
    finally:
        run_authority._active.reset(active)
    # Error text and node choice do not grant or revoke a verified identity-bound admission.
    assert allowed==(mutation in {'model_node_busy','summary_node_busy','unknown_external','multiple_errors'})
    assert len(admission['used'])==int(allowed)


async def test_resume_permit_is_consumed_once_with_concurrent_attempts(case):
    from report_agent.store import digest
    from report_agent.supervision_plugins import _resume_original_checkpoint
    from report_agent import run_authority
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
    admission={'case_path':str(cs.store.root.resolve()),'root_checkpoint_id':'root-head',
               'heads':{'tools:graph-task':'child-head'},'used':set()}
    active=run_authority._active.set({'_native_continuation':admission})
    try:
        result=await asyncio.gather(*[_resume_original_checkpoint(cs,actor,call,deepcopy(previous),runtime) for _ in range(2)])
    finally:
        run_authority._active.reset(active)
    assert sorted(result)==[False,True]
    assert admission['used']=={('tools:graph-task','child-head',actor.task_id,call['id'],previous['request_digest'])}


@pytest.mark.parametrize('admission_kind',['missing','different_case'])
async def test_resume_requires_matching_admitted_case(case,admission_kind):
    from report_agent import run_authority
    from report_agent.store import digest
    from report_agent.supervision_plugins import _resume_original_checkpoint
    cs,_,actor,_,_=case
    call={'id':'same-call','args':{'description':'fixture'}}
    previous={'task_id':actor.task_id,'native_tool_call_id':call['id'],
        'request_digest':digest({'actor':actor.__dict__,'call':call}),'state':'reserved'}
    admission=None if admission_kind=='missing' else {'case_path':str(cs.store.root/'different-case')}
    active=run_authority._active.set({'_native_continuation':admission})
    try:
        assert not await _resume_original_checkpoint(cs,actor,call,previous,SimpleNamespace(config={}))
    finally:
        run_authority._active.reset(active)
