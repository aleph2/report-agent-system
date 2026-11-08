"""Offline final-wire checks for native Writer context editing and durable inputs."""
import json

import httpx
import pytest

from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudgetExceeded
from report_agent.writer_runtime import writer_session
from test_writer_assignments import assigned, method_commission
from report_agent.errors import ActionRejected
from test_transport_observation import close


def reply(actions=()):
    message={'role':'assistant','content':'Synthetic offline stop; no engineering acceptance.'}
    if actions:
        message={'role':'assistant','content':None,'tool_calls':[
            {'id':identity,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
            for identity,name,args in actions]}
    return {'id':'offline-replay','object':'chat.completion','created':1,'model':'glm-5.3',
        'choices':[{'index':0,'finish_reason':'tool_calls' if actions else 'stop','message':message}],
        'usage':{'prompt_tokens':6,'completion_tokens':4,'total_tokens':10}}


def glm_model(f, monkeypatch, decide, *, stop_at=None):
    for key,value in {'REPORT_WRITER_MODEL':'glm-5.3',
        'REPORT_WRITER_BASE_URL':'https://synthetic.invalid/v1','REPORT_WRITER_API_KEY':'synthetic',
        'REPORT_REASONING_EFFORT':'high','REPORT_SDK_RETRIES':'0','REPORT_CONNECT_RETRIES':'0',
        'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}.items():
        monkeypatch.setenv(key,value)
    model=configured_model(f.ws.store,'writer')
    wires=[]
    async def capture(request):
        body=json.loads(request.content);wires.append(body)
        if len(wires)==stop_at:
            raise RequestBudgetExceeded('SYNTHETIC_OFFLINE_STOP')
    model.http_async_client.event_hooks['request'].append(capture)
    def respond(request):
        return httpx.Response(200,json=decide(len(wires),json.loads(request.content)))
    model.http_async_client._transport=httpx.MockTransport(respond)
    model.http_async_client._mounts={}
    return model,wires


def tool_content(body, identity):
    value=next(m['content'] for m in body['messages'] if m['role']=='tool' and m['tool_call_id']==identity)
    return value if isinstance(value,str) else ''.join(p.get('text','') for p in value)


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_final_sdk_keeps_the_current_indicators_page_batch_and_refusal(assigned,monkeypatch):
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    actions={
        1:[('bad','read_assigned_page',{'source_handle':'foreign','page':1})],
        2:[('first','read_assigned_page',{'source_handle':'source-1','page':3}),
           ('second','read_assigned_page',{'source_handle':'source-1','page':4})],
    }
    model,wires=glm_model(f,monkeypatch,lambda turn,body:reply(actions.get(turn,())))
    try:
        with writer_session(f.ws,f.plan['objects'][0]['label'],model,assessment_only=True,indicator_steps=True) as session:
            with pytest.raises(ActionRejected,match='PROBE_INDICATOR_STEP_INTERRUPTED'):
                await session.run()
        assert 'WRITER_SOURCE_HANDLE_UNKNOWN' in tool_content(wires[-1],'bad')
        assert 'Drawing K1p250' in tool_content(wires[-1],'first')
        assert 'Drawing K1 + 350' in tool_content(wires[-1],'second')
        assert not f.cs.list_objects('Assessment')
    finally:
        await close(model)


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_final_sdk_offers_alternate_views_and_tables_omit_page_text_and_geometry(assigned,monkeypatch):
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    actions={
        1:[('native','read_assigned_page',{'source_handle':'source-1','page':3,'view':'native_text'})],
        2:[('table','read_assigned_page',{'source_handle':'source-1','page':3,'view':'tables'})],
    }
    model,wires=glm_model(f,monkeypatch,lambda turn,body:reply(actions.get(turn,())))
    try:
        with writer_session(f.ws,f.plan['objects'][0]['label'],model,assessment_only=True,indicator_steps=True) as session:
            with pytest.raises(ActionRejected,match='PROBE_INDICATOR_STEP_INTERRUPTED'):
                await session.run()
        native=json.loads(tool_content(wires[1],'native'))
        assert native['native_text']=='Drawing K1p250' and 'frozen_text_blocks' not in native
        table=json.loads(tool_content(wires[2],'table'))
        assert table['view']=='tables'
        assert 'native_text' not in table and 'frozen_text_blocks' not in table
        assert not {'coordinate_system','page_bbox','source_id','source_sha256'} & table['table_view'].keys()
        assert all(set(t)=={'table','rows'} for t in table['table_view']['tables'])
    finally:
        await close(model)
