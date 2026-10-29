import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict, messages_from_dict
from langchain_core.runnables import RunnableLambda
from langgraph.graph.message import add_messages
from report_agent.task_context import TaskContext, read_observation
from report_agent.summary_recovery import capture, recovery_tool
from report_agent.working_summary import WorkingSummary, PROMPT
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden
from test_hierarchical_content import ws, seed
from test_task_supervision import offline


def test_large_summary_index_keeps_exact_snapshot_and_owner(ws):
    seed(ws)
    raw=json.dumps({'observations':[{'call_id':str(i),'note':'n'*500} for i in range(20)],'total':20,'next_offset':None})
    message=ToolMessage(content=raw,tool_call_id='summary-call',name='read_summary_observations')
    result=TaskContext(ws,'coordinator').bound_result(message)
    page=json.loads(result.content)
    assert page['tool']=='read_summary_observations' and page['complete_tool_result'] is False
    assert result.tool_call_id=='summary-call' and len(result.content)<len(raw)
    recovered=[]; offset=0
    while offset is not None:
        part=read_observation(ws,'coordinator',page['observation_ref'],offset,6000)
        recovered.append(part['text']); offset=part['next_offset']
    assert ''.join(recovered)==raw
    with delegated_task(ws,'coordinator',{'id':'other','args':{'subagent_type':'writer','description':'Other'}}):
        with pytest.raises(ActionForbidden):
            read_observation(ws,'writer',page['observation_ref'])


def test_summary_index_errors_remain_unchanged(ws):
    seed(ws)
    msg=ToolMessage(content='error'*2000,tool_call_id='bad',name='read_summary_observations',status='error')
    result=TaskContext(ws,'coordinator').bound_result(msg)
    assert result.content==msg.content and result.status=='error'


async def test_native_history_keeps_pair_and_original_snapshot(ws):
    seed(ws)
    middleware=TaskContext(ws,'coordinator')
    raw=json.dumps({'observations':[{'id':i,'note':'a'*500} for i in range(20)],'total':20})
    ai=AIMessage(content='',tool_calls=[{'id':'index','name':'read_summary_observations','args':{'offset':0}}])
    msg=middleware.bound_result(ToolMessage(content=raw,tool_call_id='index',name='read_summary_observations'))
    records=capture(ws,'coordinator',[ai,msg])
    assert records[0]['call_id']=='index' and records[0]['tool']=='read_summary_observations'
    assert read_observation(ws,'coordinator',records[0]['observation_ref'],6000,6000)['text']==raw[6000:12000]
    assert await middleware.abefore_model({'messages':[ai,msg]},None) is None


async def test_old_index_preview_clears_without_losing_original_tail(ws):
    seed(ws)
    middleware=TaskContext(ws,'coordinator')
    history=[]; originals=[]
    for i in range(3):
        raw=json.dumps({'observations':[{'id':j,'note':str(i)*500} for j in range(20)],'total':20})
        originals.append(raw)
        ai=AIMessage(content='',tool_calls=[{'id':str(i),'name':'read_summary_observations','args':{'offset':i*20}}])
        msg=middleware.bound_result(ToolMessage(content=raw,tool_call_id=str(i),name='read_summary_observations'))
        history.extend([ai,msg])
    update=await middleware.abefore_model({'messages':history},None)
    assert update is None
    original=history[1]
    assert not original.additional_kwargs.get('report_preview_cleared')
    ref=original.additional_kwargs['report_observation_ref']
    assert read_observation(ws,'coordinator',ref,6000,6000)['text']==originals[0][6000:12000]
    capture(ws,'coordinator',history+[AIMessage(content='',tool_calls=[{'id':'later','name':'project_status','args':{}}]),
        ToolMessage(content='new result',tool_call_id='later',name='project_status')])
    assert read_observation(ws,'coordinator',ref,6000,6000)['text']==originals[0][6000:12000]


async def test_real_v2_index_snapshot_survives_clear_compaction_and_reopen(ws):
    seed(ws)
    ws.store.set('context_policy','stateful-tools-v2')
    history=[]
    for i in range(20):
        ident='origin-'+str(i)
        history.extend([AIMessage(content='',id='a-'+ident,tool_calls=[{'id':ident,'name':'project_status','args':{'offset':i}}]),
            ToolMessage(content='Synthetic result '+str(i),id='t-'+ident,tool_call_id=ident,name='project_status')])
    capture(ws,'coordinator',history)
    raw=encode(recovery_tool(ws,'coordinator')(offset=0,limit=20))
    assert len(raw)>6000
    middleware=TaskContext(ws,'coordinator'); calls=[]
    for i in range(3):
        ident='index-'+str(i)
        ai=AIMessage(content='',id='a-'+ident,tool_calls=[{'id':ident,'name':'read_summary_observations','args':{'offset':0,'limit':20}}])
        msg=middleware.bound_result(ToolMessage(content=raw,id='t-'+ident,tool_call_id=ident,name='read_summary_observations'))
        calls.extend([ai,msg])
    updates=await middleware.abefore_model({'messages':calls},None)
    if updates: calls=add_messages(calls,updates['messages'])
    first=next(m for m in calls if m.id=='t-index-0')
    assert not first.additional_kwargs.get('report_preview_cleared')
    ref=first.additional_kwargs['report_observation_ref']
    assert capture(ws,'coordinator',calls)
    summary=WorkingSummary(model=RunnableLambda(lambda _:AIMessage('Synthetic continuation.')),
        store=ws.store,role='coordinator',trigger=('messages',3),keep=('messages',1),
        token_counter=lambda m:len(m),trim_tokens_to_summarize=None,summary_prompt=PROMPT)
    calls.append(HumanMessage('Continue'))
    update=await summary.abefore_model({'messages':calls},None)
    resumed=messages_from_dict(messages_to_dict(add_messages(calls,update['messages'])))
    assert any(m.additional_kwargs.get('lc_source')=='summarization' for m in resumed)
    reopened=Workspace(Store(ws.store.root))
    assert read_observation(reopened,'coordinator',ref,6000,6000)['text']==raw[6000:12000]
    tail=read_observation(reopened,'coordinator',ref,len(raw)-1000,1000)
    assert tail['text']==raw[-1000:] and tail['next_offset'] is None


async def test_actual_native_recovery_index_keeps_exact_tail(ws):
    from test_decision_data import activate
    from test_deep_runtime import Driver, invoke
    from report_agent.deep_runtime import run_report
    seed(ws); activate(ws); ws.store.set('context_policy','stateful-tools-v2')
    history=[]
    for i in range(20):
        ident='origin-'+str(i)
        history.extend([AIMessage(content='',tool_calls=[{'id':ident,'name':'project_status','args':{'offset':i}}]),
            ToolMessage(content='Synthetic result '+str(i),tool_call_id=ident,name='project_status')])
    capture(ws,'coordinator',history)
    expected=encode(recovery_tool(ws,'coordinator')(offset=0,limit=20))
    assert len(expected)>6000
    def retrieve(messages):
        indices=[m for m in messages if isinstance(m,ToolMessage) and m.name=='read_summary_observations']
        assert not indices[0].additional_kwargs.get('report_preview_cleared')
        ref=indices[0].additional_kwargs['report_observation_ref']
        return invoke('read_tool_observation',observation_ref=ref,offset=6000,characters=6000)
    def finish(messages):
        page=next(json.loads(m.content) for m in reversed(messages) if isinstance(m,ToolMessage) and m.name=='read_tool_observation')
        assert page['text']==expected[6000:12000]
        return AIMessage(content='Synthetic interface verification only.')
    actions=[AIMessage(content='',tool_calls=[{'id':f'index-{i}','name':'read_summary_observations',
        'args':{'offset':0,'limit':20}}]) for i in range(3)]
    driver=Driver(coordinator=actions+[retrieve,finish])
    await run_report(ws,driver)
    assert len(driver.calls)==5
