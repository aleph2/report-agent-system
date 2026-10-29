import json
import httpx
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.memory import InMemorySaver
from report_agent.token_budget import TokenBudget, token_budget
from test_transport_observation import setup_model, use_mock, close, body

@pytest.mark.asyncio
async def test_current_root_adds_facts_preserving_tool_pair_and_only_new_sdk_call(tmp_path,monkeypatch):
    store,model=setup_model(tmp_path,monkeypatch,role='coordinator')
    model.root_async_client.max_retries=0;model.root_client.max_retries=0
    sent=[]
    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200,json=body())
    await use_mock(model,respond)
    ledger=TokenBudget(tmp_path/'budget.db',200,{'deepseek-v4.1-flash':40})
    settled=ledger.reserve('deepseek-v4.1-flash');ledger.settle(settled,{'total_tokens':10})
    unknown=ledger.reserve('deepseek-v4.1-flash')
    async def node(state):
        return {'messages':[await model.ainvoke(state['messages'])]}
    builder=StateGraph(MessagesState);builder.add_node('model',node);builder.add_edge(START,'model');builder.add_edge('model',END)
    graph=builder.compile(checkpointer=InMemorySaver(),interrupt_before=['model'])
    config={'configurable':{'thread_id':'synthetic'}}
    old=[HumanMessage(content='original request',id='old-human'), AIMessage(content='',id='old-ai',tool_calls=[{'name':'task','args':{'subagent_type':'writer','description':'original'},'id':'old-task','type':'tool_call'}]), ToolMessage(name='task',tool_call_id='old-task',id='old-tool',content='NATIVE_DELEGATION_OUTCOME_UNRESOLVED')]
    try:
        await graph.ainvoke({'messages':old},config)
        before=await graph.aget_state(config)
        assert before.next==('model',)
        current=await graph.aupdate_state(before.config,{'messages':[HumanMessage(content='Recovery: original task is unresolved; preserve prior outputs.',id='recovery-fact')]},as_node=START)
        after=await graph.aget_state(current)
        assert after.next==('model',)
        assert [m.id for m in after.values['messages']]==['old-human','old-ai','old-tool','recovery-fact']
        assert after.values['messages'][2].tool_call_id=='old-task'
        with token_budget(ledger):
            await graph.ainvoke(None,current)
        assert len(sent)==1
        wire=sent[0]['messages'];assert any('Recovery: original task is unresolved' in str(m.get('content')) for m in wire)
        assert any(m.get('tool_call_id')=='old-task' and 'NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in str(m.get('content')) for m in wire)
        snap=ledger.snapshot();assert snap['recorded_tokens']==20 and snap['reserved_or_unknown_upper_bounds']==40
        with ledger.connect() as db:assert db.execute('select state,reserved from attempts where id=?',(unknown,)).fetchone()==('reserved',40)
    finally:
        await close(model)
