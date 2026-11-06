"""Offline final-wire checks for native Writer context editing and durable inputs."""
from copy import deepcopy
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.content_store import ContentStore
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudgetExceeded
from report_agent.store import Store
from report_agent.writer_runtime import writer_session
from report_agent import writer_assessment
from test_writer_assignments import assigned, method_commission
from test_writer_assessment import input_row
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
async def test_final_sdk_clears_used_page_but_saved_exact_quote_and_partial_draft_survive_stop(assigned,monkeypatch):
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    row={}
    actions={
        1:[('assignment','read_assignment',{})],
        2:[('old','read_assigned_page',{'source_handle':'source-1','page':96})],
        3:[('save','set_indicator',row)],
        4:[('middle','read_assigned_page',{'source_handle':'source-1','page':3})],
        5:[('error','read_assigned_page',{'source_handle':'not-offered','page':1})],
        6:[('latest','read_assigned_page',{'source_handle':'source-1','page':4})],
    }
    model,wires=glm_model(f,monkeypatch,lambda turn,body:reply(actions[turn]),stop_at=7)
    try:
        with writer_session(f.ws,f.plan['objects'][0]['label'],model,assessment_only=True) as session:
            f.actor=session.actor
            row.update(input_row(f,writer_assessment))
            assert row['quotes']
            with pytest.raises(RequestBudgetExceeded,match='SYNTHETIC_OFFLINE_STOP'):
                await session.agent.ainvoke({'messages':[session.initial_message]},session.config)
            final=wires[-1]
            assert len(wires)==7
            assert 'Earlier page/window text cleared' in tool_content(final,'old')
            assert 'Earlier page/window text cleared' in tool_content(final,'middle')
            assert 'Drawing K1 + 350' in tool_content(final,'latest')
            assert 'WRITER_SOURCE_HANDLE_UNKNOWN' in tool_content(final,'error')
            assert 'object_label' in tool_content(final,'assignment')
            calls=[c for m in final['messages'] for c in m.get('tool_calls',[])]
            saved=next(c for c in calls if c['id']=='save')
            assert json.loads(saved['function']['arguments'])['quotes']==row['quotes']
            old=next(c for c in calls if c['id']=='old')
            assert json.loads(old['function']['arguments'])=={'source_handle':'source-1','page':96}
            draft=writer_assessment.read_assignment(f.cs,session.actor)['draft']
            assert len(draft)==1 and draft[0]['quotes']==row['quotes']
            with f.ws.store.connect() as db:
                durable=[json.loads(r[0]) for r in db.execute("SELECT value FROM state WHERE key LIKE 'writer_assessment_draft:%'")]
            assert len(durable)==1 and len(durable[0]['rows'])==1
            saved_row=next(iter(durable[0]['rows'].values()))
            assert saved_row['input']['quotes']==row['quotes']
            assert [c['quote'] for c in saved_row['judgment']['sources']]==row['quotes']
            assert not f.cs.list_objects('Assessment')
            schema=next(t['function']['parameters'] for t in final['tools'] if t['function']['name']=='read_assigned_page')
            assert schema['properties']['view']['enum']==['text','native_text','tables']
            assert 'view' not in schema['required']
            assert {t['function']['name'] for t in final['tools']}=={
                'read_assignment','set_indicator','submit_assessment','propose_material_issue','read_assigned_page','read_assigned_text'}
        reopened=ContentStore(Store(f.ws.store.root))
        assert reopened.read(f.pdf_ref)==f.cs.read(f.pdf_ref)
        assert writer_assessment.read_assignment(reopened,f.actor)['draft'][0]['quotes']==row['quotes']
    finally:
        await close(model)


@pytest.mark.asyncio
async def test_final_sdk_preserves_unseen_multiresult_batch_notice_and_error(assigned,monkeypatch):
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    model,wires=glm_model(f,monkeypatch,lambda turn,body:reply())
    old=AIMessage(content='',tool_calls=[{'name':'read_assigned_page','id':'old','args':{'source_handle':'source-1','page':96}}])
    failed=AIMessage(content='',tool_calls=[{'name':'read_assigned_page','id':'error','args':{'source_handle':'foreign','page':1}}])
    batch=AIMessage(content='',tool_calls=[
        {'name':'read_assigned_page','id':'new-one','args':{'source_handle':'source-1','page':3}},
        {'name':'read_assigned_page','id':'new-two','args':{'source_handle':'source-1','page':4}}])
    messages=[old,ToolMessage('OLD_RAW_PAGE_MUST_CLEAR',tool_call_id='old',name='read_assigned_page'),
        failed,ToolMessage('PRESERVED_ERROR',tool_call_id='error',name='read_assigned_page',status='error'),
        batch,ToolMessage('UNSEEN_PAGE_THREE',tool_call_id='new-one',name='read_assigned_page'),
        ToolMessage('UNSEEN_PAGE_FOUR',tool_call_id='new-two',name='read_assigned_page'),
        HumanMessage('APPENDED_HOST_NOTICE')]
    for index,message in enumerate(messages):
        message.id='seeded-message-'+str(index)
    before=deepcopy(messages)
    try:
        with writer_session(f.ws,f.plan['objects'][0]['label'],model,assessment_only=True) as session:
            await session.agent.ainvoke({'messages':[session.initial_message,*messages]},session.config)
        final=wires[0]
        assert 'OLD_RAW_PAGE_MUST_CLEAR' not in tool_content(final,'old')
        assert tool_content(final,'new-one')=='UNSEEN_PAGE_THREE'
        assert tool_content(final,'new-two')=='UNSEEN_PAGE_FOUR'
        assert tool_content(final,'error')=='PRESERVED_ERROR'
        assert any(m.get('content')=='APPENDED_HOST_NOTICE' for m in final['messages'])
        assert messages==before
    finally:
        await close(model)


@pytest.mark.asyncio
async def test_final_sdk_offers_alternate_views_and_tables_omit_page_text_and_geometry(assigned,monkeypatch):
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    actions={
        1:[('native','read_assigned_page',{'source_handle':'source-1','page':3,'view':'native_text'})],
        2:[('table','read_assigned_page',{'source_handle':'source-1','page':3,'view':'tables'})],
    }
    model,wires=glm_model(f,monkeypatch,lambda turn,body:reply(actions.get(turn,())))
    try:
        with writer_session(f.ws,f.plan['objects'][0]['label'],model,assessment_only=True) as session:
            await session.agent.ainvoke({'messages':[session.initial_message]},session.config)
        native=json.loads(tool_content(wires[1],'native'))
        assert native['native_text']=='Drawing K1p250' and 'frozen_text_blocks' not in native
        table=json.loads(tool_content(wires[2],'table'))
        assert table['view']=='tables'
        assert 'native_text' not in table and 'frozen_text_blocks' not in table
        assert not {'coordinate_system','page_bbox','source_id','source_sha256'} & table['table_view'].keys()
        assert all(set(t)=={'table','rows'} for t in table['table_view']['tables'])
    finally:
        await close(model)
