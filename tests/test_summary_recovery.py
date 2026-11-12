import asyncio
import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from report_agent.summary_recovery import capture, continuation_index, recovery_tool
from report_agent.task_context import TaskContext, read_observation
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden
from report_agent.working_summary import WorkingSummary, SummaryRepairRequired
from test_hierarchical_content import ws, seed

def pair(ident,text,name='project_status'):
    return [AIMessage(content='',tool_calls=[{'id':ident,'name':name,'args':{'offset':0}}]),
            ToolMessage(content=text,tool_call_id=ident,name=name)]

async def test_compacted_preview_ranges_are_not_full_reading(ws):
    seed(ws)
    middleware=TaskContext(ws,'coordinator')
    history=[]
    for i in range(3):
        ai,msg=pair(str(i),'A'*13000)
        history.extend([ai,middleware.bound_result(msg)])
    assert await middleware.abefore_model({'messages':history},None) is None
    records=capture(ws,'coordinator',history)
    assert records[0]['recoverable_characters']==13000
    assert records[0]['delivery']['preview_cleared'] is False
    assert records[0]['delivery']['original_delivery']['end']==6000
    assert records[0]['delivery']['compacted_message_range']['end']==6000
    assert records[1]['delivery']['compacted_message_range']['complete_tool_result'] is False
    assert 'provided_preview' in continuation_index(records)
    assert read_observation(ws,'coordinator',records[0]['observation_ref'],12000,1000)['text']=='A'*1000
    capture(ws,'coordinator',pair('new','Actual later return','read_source'))
    assert recovery_tool(ws,'coordinator')(offset=3)['total']==4
    assert len(capture(ws,'coordinator',history))==4

def test_public_pair_capture_is_actor_owned_not_all_store_events(ws):
    seed(ws)
    record=capture(ws,'coordinator',pair('own','Own returned text'))[0]
    with delegated_task(ws,'coordinator',{'id':'writer-task','args':{'subagent_type':'writer','description':'Assigned writing'}}):
        assert recovery_tool(ws,'writer')()['total']==0
        with pytest.raises(ActionForbidden):read_observation(ws,'writer',record['observation_ref'])
    assert capture(ws,'coordinator',[ToolMessage(content='Unpaired old text',tool_call_id='foreign')])==[record]

@pytest.mark.parametrize('failure',[TimeoutError,asyncio.CancelledError])
async def test_unknown_summary_cannot_be_reissued_after_restart(ws,failure):
    calls=[]
    async def model(prompt): calls.append(prompt);raise failure()
    def summary():return WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m))
    with pytest.raises(failure):await summary()._acreate_summary(pair('a','Public returned fact'))
    with pytest.raises(SummaryRepairRequired):await summary()._acreate_summary(pair('a','Public returned fact'))
    assert len(calls)==1
    assert any(e['kind']=='working_summary_outcome_unknown' for e in ws.store.events())

async def test_accepted_compaction_retains_exact_return_across_new_summaries(ws):
    async def model(prompt):return AIMessage(content='Hypothesis pending; inspect original return.')
    summary=WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m))
    first=await summary._acreate_summary(pair('first','Exact qualifier: condition unverified.','read_source'))
    second=await summary._acreate_summary(pair('second','Later public result.','read_source'))
    records=recovery_tool(ws,'coordinator')()['observations']
    assert len(records)==2 and records[0]['observation_ref'] in second
    assert read_observation(ws,'coordinator',records[0]['observation_ref'])['text']=='Exact qualifier: condition unverified.'
