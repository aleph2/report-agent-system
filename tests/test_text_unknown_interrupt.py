"""Real native child checkpoints: an unknown-admission denial is not a replan loop."""
import hashlib
import json
import pytest
from langchain_core.messages import AIMessage
from report_agent import deep_runtime
from report_agent.errors import ModelRequestDeadlineExceeded
from test_deep_runtime import Driver, invoke, snapshot, offline
from test_hierarchical_content import seed
from test_task_supervision import ws
from test_bounded_review import Model
from test_text_work import content


def grant(ws, event, tmp_path):
    from report_agent.content_store import Actor
    from report_agent.text_work_disposition import authorize_distinct_work
    actor = Actor(**event['actor'])
    details = event['details']
    path = tmp_path/'host-evidence.txt'
    path.write_text('Inspected genuinely new source applicability; old response remains unknown.')
    key = authorize_distinct_work(ws,actor,event['operation_id'],details['candidate_request_hash'],
        details['candidate_material_identity'],details['conflicts'],rationale='New factual basis inspected',
        evidence_path=path,evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_basis='Existing user scope and token budget')
    return key, path


def case(ws):
    _, _, refs, _, _ = seed(ws)
    service = Model(ModelRequestDeadlineExceeded(600))
    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description='Inspect and revise selected material.'),
        AIMessage(content='Child returned; no final report acceptance.')], writer=[
        invoke('process_report_content',operation_id='unknown',objective='Assess old selected material',
               object_type='ContentNode',input_refs=[refs['claim']]),
        invoke('process_report_content',operation_id='new-material',objective='Assess newly supplied factual evidence',
               object_type='ContentNode',input_refs=[refs['claim'],refs['evidence']]),
        AIMessage(content='Received candidate; not engineering acceptance.')])
    factory = lambda role: service if role == 'text_tool' else driver(role)
    return driver, service, factory


async def test_native_denial_pauses_before_another_decision_and_resumes_exact_grant(ws, tmp_path):
    from report_agent.content_store import Actor
    from report_agent.text_work_disposition import authorize_distinct_work
    driver, service, factory = case(ws)
    first = await deep_runtime.run_report(ws, factory)
    pending = await snapshot(ws, factory)
    assert pending.interrupts, first
    event = pending.interrupts[0].value
    assert event['kind'] == 'text_work_unknown_admission'
    assert not event['producer_invoked']
    assert len(service.calls) == 1
    assert [(r,n) for r,n,_ in driver.calls] == [('coordinator',0),('writer',0),('writer',1)]
    before_calls = len(driver.calls)
    await deep_runtime.run_report(ws, factory)
    assert len(driver.calls) == before_calls and len(service.calls) == 1
    actor = Actor(**event['actor'])
    details = event['details']
    path = tmp_path/'host-evidence.txt'
    path.write_text('Independent inspection confirms actual new source applicability; old response remains unknown.')
    authorize_distinct_work(ws,actor,event['operation_id'],details['candidate_request_hash'],
        details['candidate_material_identity'],details['conflicts'],rationale='New factual basis inspected',
        evidence_path=path,evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_basis='Existing user scope and token budget')
    service.response=json.dumps(content())
    await deep_runtime.run_report(ws, factory)
    complete = await snapshot(ws, factory)
    assert not complete.interrupts and not complete.next
    assert len(service.calls) == 2
    assert ws.store.get('text_work:'+actor.id+':unknown')['state']=='reserved'
    assert ws.store.get('text_work:'+actor.id+':new-material')['state']=='completed'
    assert ws.store.get('decision_observation') is None


@pytest.mark.parametrize('answer', [True, {'decision':'approved', 'decision_origin':'operator'}])
async def test_native_arbitrary_resume_cannot_release_unknown(ws, answer):
    from langgraph.types import Command
    driver, service, factory = case(ws)
    await deep_runtime.run_report(ws, factory)
    calls = len(driver.calls)
    ws.store.set('report_issues', [{'id':None, 'decision':'approved', 'decision_origin':'operator'}])
    await deep_runtime.run_report(ws, factory)
    # Even direct native misuse must re-pause, not return an error to the Writer.
    async with deep_runtime.project_agent(ws, factory) as agent:
        config = {'configurable': {'thread_id':'report'}}
        await agent.ainvoke(Command(resume=answer), config)
        pending = await agent.aget_state(config)
    assert pending.interrupts and len(service.calls)==1 and len(driver.calls)==calls


@pytest.mark.parametrize('tamper', ['evidence_file','authority','conflicts'])
async def test_native_stale_grant_never_dispatches_or_replans(ws, tmp_path, monkeypatch, tamper):
    from report_agent import text_work
    driver, service, factory = case(ws)
    await deep_runtime.run_report(ws, factory)
    pending = await snapshot(ws, factory)
    event = pending.interrupts[0].value
    key, path = grant(ws, event, tmp_path)
    calls = len(driver.calls)
    if tamper == 'evidence_file':
        path.write_text('Changed after registration')
    elif tamper == 'authority':
        old = text_work.authority
        monkeypatch.setattr(text_work, 'authority', lambda w,a: {**old(w,a), 'scope_instruction':'Changed scope'})
    else:
        actor_id = event['actor']['id']
        prior = ws.store.get('text_work:'+actor_id+':unknown')
        ws.store.set('text_work:'+actor_id+':another-unknown', prior)
    service.response=json.dumps(content())
    await deep_runtime.run_report(ws, factory)
    pending = await snapshot(ws, factory)
    assert pending.interrupts and len(service.calls)==1 and len(driver.calls)==calls
    assert ws.store.get(key)['state']=='authorized'
    await deep_runtime.run_report(ws, factory)
    assert len(service.calls)==1 and len(driver.calls)==calls


async def test_completed_receipt_before_checkpoint_is_reused_without_provider(ws, tmp_path, monkeypatch):
    driver, service, factory = case(ws)
    await deep_runtime.run_report(ws, factory)
    pending = await snapshot(ws, factory)
    event = pending.interrupts[0].value
    grant(ws, event, tmp_path)
    service.response=json.dumps(content())
    original = deep_runtime.BusinessBoundary.awrap_tool_call
    async def fail_after_production(self, request, handler):
        result = await original(self, request, handler)
        if request.tool_call['args'].get('operation_id') == 'new-material':
            raise RuntimeError('synthetic checkpoint-boundary crash after saved receipt')
        return result
    monkeypatch.setattr(deep_runtime.BusinessBoundary, 'awrap_tool_call', fail_after_production)
    failed = await deep_runtime.run_report(ws, factory)
    assert failed['status']=='failed' and len(service.calls)==2
    actor_id = event['actor']['id']
    completed = ws.store.get('text_work:'+actor_id+':new-material')
    assert completed['state']=='completed'
    monkeypatch.setattr(deep_runtime.BusinessBoundary, 'awrap_tool_call', original)
    await deep_runtime.run_report(ws, factory)
    complete = await snapshot(ws, factory)
    assert not complete.next and not complete.interrupts
    assert len(service.calls)==2
    assert ws.store.get('text_work:'+actor_id+':new-material')==completed
