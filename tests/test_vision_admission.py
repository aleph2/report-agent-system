"""Admission and native checkpoint witnesses; no visual correctness claim."""
import asyncio
import json
import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command
from report_agent import deep_runtime
from report_agent.content_store import Actor
from report_agent.errors import ActionRejected
from report_agent.vision import observe_source_image
from report_agent.bounded_operations import reserve_once
from test_vision import VisionModel
from test_document_tools import workspace
from test_deep_runtime import Driver, invoke, snapshot
from test_task_supervision import ws, offline

_HTTPX_ASYNC_SEND = httpx.AsyncClient.send


async def test_unknown_exact_request_and_same_actor_material_cannot_be_reworded(tmp_path):
    work = workspace(tmp_path)
    actor=Actor('writer-A','writer','task-A')
    client=VisionModel(error=httpx.ReadTimeout('synthetic'))
    first=await observe_source_image(work,'original','read',client=client,actor=actor)
    assert first['provider_outcome']=='unknown'
    for question in ('read','read this more carefully'):
        with pytest.raises(ActionRejected,match='VISION_OUTCOME_UNRESOLVED'):
            await observe_source_image(work,'original',question,client=client,actor=actor)
    client.base_url='https://other.invalid/v1'
    with pytest.raises(ActionRejected,match='VISION_OUTCOME_UNRESOLVED'):
        await observe_source_image(work,'original','different prompt',client=client,actor=actor)
    assert len(client.calls)==1
    client.error=None
    assert (await observe_source_image(work,'original','read',page=2,client=client,actor=actor))['status']=='observed'
    client.base_url='https://unit.invalid/v1'  # Restore the exact first request.
    with pytest.raises(ActionRejected,match='VISION_OUTCOME_UNRESOLVED'):
        await observe_source_image(work,'original','read',client=client,
                                   actor=Actor('writer-B','writer','task-B'))
    assert len(client.calls)==2
    assert (await observe_source_image(work,'original','Inspect the table heading',client=client,
                                      actor=Actor('writer-B','writer','task-B')))['status']=='observed'
    assert len(client.calls)==3


async def test_cancelled_attempt_remains_unknown_even_without_error_event(tmp_path):
    work=workspace(tmp_path)
    client=VisionModel(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await observe_source_image(work,'original','read',client=client)
    with pytest.raises(ActionRejected,match='VISION_OUTCOME_UNRESOLVED'):
        await observe_source_image(work,'original','read',client=client)
    assert len(client.calls)==1


async def test_historical_unknown_is_not_reinterpreted_as_unattempted(tmp_path):
    work=workspace(tmp_path)
    client=VisionModel(error=httpx.ReadTimeout('synthetic'))
    first=await observe_source_image(work,'original','read',client=client)
    # Emulate a historical pre-admission archive, preserving real request/error.
    with work.store.connect() as db:
        db.execute("DELETE FROM state WHERE key LIKE 'vision_attempt:%'")
        db.execute("UPDATE events SET data=json_remove(data,'$.actor') WHERE kind='vision_request'")
    with pytest.raises(ActionRejected,match='historical_unresolved'):
        await observe_source_image(work,'original','read',client=client)
    assert len(client.calls)==1 and work.store.analysis(first['operation']) is None


def test_shared_reservation_keeps_original_text_key_and_is_atomic(tmp_path):
    work=workspace(tmp_path)
    key='bounded_review_attempt:existing-operation'
    record={'state':'reserved','operation':'existing-operation'}
    assert reserve_once(work.store,key,record) is None
    assert reserve_once(work.store,key,record)==record
    assert work.store.get(key)==record


async def test_native_vision_denial_pauses_before_extra_decision_and_cannot_be_approved(ws, monkeypatch):
    client=VisionModel(error=httpx.ReadTimeout('synthetic'))
    monkeypatch.setattr('report_agent.vision.configured_vision_client',lambda:client)
    monkeypatch.setattr('report_agent.document_tools.vision_source_image',
        lambda workspace,source,page,crop,**limits:(b'synthetic-image',{'source_id':source,'sha256':'f'*64,'page':page,'crop':crop}))
    driver=Driver(coordinator=[invoke('analyze_source_image',source_id='s',question='read'),
        invoke('analyze_source_image',source_id='s',question='read again'),
        AIMessage(content='Must not reach another decision after denial')])
    await deep_runtime.run_report(ws,driver)
    pending=await snapshot(ws,driver)
    assert pending.interrupts
    event=pending.interrupts[0].value
    assert event['kind']=='vision_unknown_admission' and event['provider_invoked'] is False
    assert len(client.calls)==1 and len(driver.calls)==2
    calls=len(driver.calls)
    await deep_runtime.run_report(ws,driver)
    async with deep_runtime.project_agent(ws,driver) as agent:
        config={'configurable':{'thread_id':'report'}}
        await agent.ainvoke(Command(resume=True),config)
        pending=await agent.aget_state(config)
    assert pending.interrupts and len(driver.calls)==calls and len(client.calls)==1


async def test_rendered_page_uses_same_actor_bound_unknown_protection(tmp_path, monkeypatch):
    from report_agent.content_export import inspect_render
    from test_paired_render_inspection import Contents, RENDER, png
    from report_agent.store import Store
    contents=Contents()
    contents.store=Store(tmp_path/'render-store')
    monkeypatch.setattr('report_agent.content_export._bytes',lambda *args:png('blue'))
    actor=Actor('reviewer-A','reviewer','review-A')
    client=VisionModel(error=httpx.ReadTimeout('synthetic'))
    first=await inspect_render(contents,actor,RENDER,1,'Inspect title',client=client)
    assert first['result']['provider_outcome']=='unknown'
    with pytest.raises(ActionRejected,match='VISION_OUTCOME_UNRESOLVED'):
        await inspect_render(contents,actor,RENDER,1,'Inspect title again',client=client)
    assert len(client.calls)==1


async def test_real_sdk_budget_stop_propagates_without_dispatch_or_false_unknown_result(tmp_path, monkeypatch):
    from openai import AsyncOpenAI
    from report_agent.deep_models import model_async_client
    from report_agent.request_budget import RequestBudgetExceeded
    from report_agent.token_budget import TokenBudget, token_budget
    monkeypatch.setenv('REPORT_SDK_RETRIES','5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    work=workspace(tmp_path/'project')
    transport=model_async_client()
    await transport._transport.aclose()
    seen=[]
    def never_send(request):
        seen.append(request)
        raise AssertionError('Budget rejection must precede dispatch')
    transport._transport=httpx.MockTransport(never_send)
    transport._mounts={}
    # Only this MockTransport-backed instance uses the real SDK send path.
    monkeypatch.setattr(transport,'send',_HTTPX_ASYNC_SEND.__get__(transport))
    budget=TokenBudget(tmp_path/'budget.db',60,{'deepseek-v4.1-flash-1017':40})
    budget.reserve('deepseek-v4.1-flash-1017')  # Existing unknown remains held.
    before=budget.snapshot()
    async with AsyncOpenAI(api_key='synthetic',base_url='https://offline.invalid/v1',
                           http_client=transport,max_retries=5) as client:
        with token_budget(budget), pytest.raises(RequestBudgetExceeded,match='AUTHORIZED_TOKEN_BUDGET_REACHED'):
            await observe_source_image(work,'original','read',client=client)
    assert not seen and budget.snapshot()==before
    assert not [e for e in work.store.events() if e['kind']=='vision_error']


async def test_malformed_sdk_response_keeps_private_extras_out_of_native_observations(ws, monkeypatch):
    from openai import AsyncOpenAI
    from report_agent.deep_models import model_async_client
    sentinel='synthetic-private-protocol-never-public'
    transport=model_async_client()
    await transport._transport.aclose()
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json={'id':'malformed-synthetic','object':'chat.completion',
            'created':0,'model':'deepseek-v4.1-flash-1017',
            'reasoning_content':sentinel,
            'choices':[{'index':0,'finish_reason':'stop','message':None}],
            'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5,
                     'private_provider_field':sentinel}})
    transport._transport=httpx.MockTransport(respond)
    transport._mounts={}
    monkeypatch.setattr(transport,'send',_HTTPX_ASYNC_SEND.__get__(transport))
    client=AsyncOpenAI(api_key='synthetic',base_url='https://offline.invalid/v1',
                       http_client=transport,max_retries=0)
    monkeypatch.setattr('report_agent.vision.configured_vision_client',lambda:client)
    monkeypatch.setattr('report_agent.document_tools.vision_source_image',
        lambda workspace,source,page,crop,**limits:(b'synthetic-image',{'source_id':source,'page':page,'crop':crop}))
    ws.store.set('context_policy','stateful-tools-v1')
    def inspect(messages):
        from test_deep_runtime import observation
        envelope=observation(messages,'analyze_source_image')
        assert envelope['representation'] == 'exact-public-result-v2'
        assert envelope['status'] == 'success' and envelope['complete_original_in_decision'] is True
        saved = ws.store.get('tool_observation:' + envelope['observation_ref'])
        public=envelope['metadata']
        assert json.loads(saved['text']) == public
        assert public['status']=='failed' and public['provider_outcome']=='response_received'
        assert public['raw_response_received'] is True
        assert public['response_id']=='malformed-synthetic' and public['finish_reason']=='stop'
        assert public['usage']=={'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}
        assert 'raw_response' not in public
        assert sentinel not in json.dumps([m.model_dump() for m in messages])
        return AIMessage(content='Received malformed observation; no source absence claim.')
    driver=Driver(coordinator=[invoke('analyze_source_image',source_id='s',question='read'),inspect])
    try:
        result=await deep_runtime.run_report(ws,driver)
        assert result['last_error'] is None and len(seen)==1
        with ws.store.connect() as db:
            values=[row[0] for row in db.execute('SELECT value FROM state')]
        assert sentinel not in json.dumps(values)
        assert sentinel not in json.dumps(ws.store.events())
        records=[json.loads(value) for value in values]
        receipts=[value for value in records if isinstance(value,dict) and value.get('kind')=='vision']
        assert len(receipts)==1 and receipts[0]['state']=='received_invalid'
    finally:
        await client.close()
