"""Live callback tests use real LangChain dispatch and native tool-call IDs."""
import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, InjectedToolCallId
from typing import Annotated
from report_agent.content_store import Actor
from report_agent.errors import ActionRejected
from report_agent.tool_trace import ToolTrace, capture_tools, summarize_trace
from report_agent.workspace import Workspace
from report_agent.store import Store
from test_deep_runtime import Driver


@pytest.mark.parametrize('kind',['exception','returned_error','validation'])
async def test_real_callbacks_capture_each_refusal_with_native_id_and_role(tmp_path,kind):
    ws=Workspace(Store(tmp_path/'case'));path=tmp_path/'trace.jsonl'
    actor=Actor('test-coordinator','coordinator','test-planning')
    def refuse(value:int,tool_call_id:Annotated[str,InjectedToolCallId]):
        """Synthetic refusing tool."""
        if kind=='exception':raise ActionRejected('QUOTE_NOT_FOUND')
        return ToolMessage(content=json.dumps({'code':'EVIDENCE_SCOPE_MISMATCH','diagnostic':{'field':'value'}}),status='error',tool_call_id=tool_call_id)
    tool=StructuredTool.from_function(refuse)
    call={'id':'native-01','name':'refuse','args':{'value':'wrong' if kind=='validation' else 1},'type':'tool_call'}
    driver=Driver(coordinator=[AIMessage('',tool_calls=[call])]);model=driver('coordinator')
    with capture_tools(ToolTrace(ws,'probe',path,actor)):
        answer=await model.ainvoke([HumanMessage('synthetic request')])
        if kind=='returned_error':await tool.ainvoke(answer.tool_calls[0])
        else:
            with pytest.raises(Exception):await tool.ainvoke(answer.tool_calls[0])
    records=[json.loads(line) for line in path.read_text().splitlines()]
    outcomes=[r for r in records if r['kind']=='tool_outcome']
    assert len(outcomes)==1 and outcomes[0]['rejected']
    assert outcomes[0]['native_call_id']=='native-01' and outcomes[0]['actor']=='test-coordinator'
    assert outcomes[0]['role']=='coordinator' and outcomes[0]['codes']
    if kind=='validation':assert outcomes[0]['validation_errors'][0]['loc']==['value']
    if kind=='returned_error':assert outcomes[0]['diagnostic']['field']=='value'
    summary=summarize_trace(path)
    assert summary['roles']['coordinator']['tool_rejections']==1
    assert summary['roles']['coordinator']['model_calls']==1
    assert summary['roles']['coordinator']['tokens'] is None


def test_restart_deduplicates_native_calls_and_retains_unattributed_rows(tmp_path):
    path=tmp_path/'trace.jsonl'
    common={'kind':'tool_outcome','run_id':'probe','actor':'a','role':'writer','native_call_id':'n','rejected':True,'codes':['QUOTE_NOT_FOUND']}
    path.write_text(''.join(json.dumps(row)+'\n' for row in [common,common,{**common,'actor':'b'},
        {**common,'actor':None,'native_call_id':None,'callback_id':'unattributed'}]))
    result=summarize_trace(path)
    assert result['roles']['writer']['tool_rejections']==2
    assert result['unattributed_tool_outcomes']==1


def test_provider_failures_are_separate_from_tool_refusals(tmp_path):
    ws=Workspace(Store(tmp_path/'case'));path=tmp_path/'trace.jsonl'
    trace=ToolTrace(ws,'probe',path,Actor('a','coordinator','t'))
    trace.on_chat_model_start({},[[HumanMessage('synthetic')]],run_id='model-01')
    trace.on_llm_error(RuntimeError('provider failure'),run_id='model-01')
    result=summarize_trace(path)['roles']['coordinator']
    assert result['model_failures']==1 and result['tool_rejections']==0


def test_unfinished_calls_and_partial_lines_remain_visible(tmp_path):
    ws=Workspace(Store(tmp_path/'case'));path=tmp_path/'trace.jsonl'
    trace=ToolTrace(ws,'probe',path,Actor('a','coordinator','t'))
    trace.on_chat_model_start({},[[HumanMessage('synthetic')]],run_id='pending')
    with path.open('a') as f:f.write('{partial')
    result=summarize_trace(path)
    assert result['malformed_lines']==1 and result['inflight'][0]['callback_id']=='pending'
    assert result['inflight'][0]['elapsed_seconds']>=0
    assert result['coverage']=='partial'


def test_owner_checkpoint_is_control_flow_not_a_tool_refusal(tmp_path):
    from langgraph.errors import GraphInterrupt
    ws=Workspace(Store(tmp_path/'case'));path=tmp_path/'trace.jsonl'
    trace=ToolTrace(ws,'probe',path,Actor('a','coordinator','t'))
    trace.on_tool_start({'name':'submit_plan'},'{}',run_id='callback',tool_call_id='native-checkpoint')
    trace.on_tool_error(GraphInterrupt(()),run_id='callback')
    assert summarize_trace(path)['roles']['coordinator']['tool_rejections']==0


async def test_unknown_tool_refusal_is_captured_even_without_a_tool_callback(tmp_path):
    from langchain.agents import create_agent
    ws=Workspace(Store(tmp_path/'case'));path=tmp_path/'trace.jsonl'
    def available():
        """One available tool."""
        return 'ok'
    call={'id':'bad-tool','name':'not_available','args':{},'type':'tool_call'}
    model=Driver(coordinator=[AIMessage('',tool_calls=[call]),AIMessage('已记录问题。')])('coordinator')
    with capture_tools(ToolTrace(ws,'probe',path,Actor('a','coordinator','t'))):
        await create_agent(model,[available]).ainvoke({'messages':[HumanMessage('synthetic')]})
    result=summarize_trace(path)
    assert result['roles']['coordinator']['tool_rejections']==1


def test_local_budget_denial_is_not_a_provider_failure(tmp_path):
    from report_agent.request_budget import RequestBudgetExceeded
    ws=Workspace(Store(tmp_path/'case'));path=tmp_path/'trace.jsonl'
    trace=ToolTrace(ws,'probe',path,Actor('a','coordinator','t'))
    trace.on_chat_model_start({},[[HumanMessage('synthetic')]],run_id='denied')
    trace.on_llm_error(RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED'),run_id='denied')
    result=summarize_trace(path)['roles']['coordinator']
    assert result['model_failures']==0 and result['admission_denials']==1
