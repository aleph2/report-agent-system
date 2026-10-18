"""Native compaction recovery and exact consumption; no paid provider."""
import json
from collections import defaultdict

import pytest
from langchain_core.messages import AIMessage,HumanMessage,ToolMessage,messages_to_dict,messages_from_dict
from langchain_core.runnables import RunnableLambda
from langgraph.graph.message import add_messages
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from report_agent.summary_recovery import capture,continuation_index,recovery_tool,key
from report_agent.task_context import observation_tool,read_observation
from report_agent.working_summary import WorkingSummary,PROMPT
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.errors import ActionRejected
from report_agent.catalog import Catalog
from report_agent.source_tables import with_source_tables
from test_summary_recovery import pair
from test_hierarchical_content import seed
from test_task_supervision import ws,offline
from test_text_work import writer_call,content
from test_deep_runtime import Driver,invoke,observation


async def test_two_native_compactions_old_ref_beyond_recent_twenty_exactly_recovered(ws):
    seed(ws)
    calls=[]
    async def summarize(prompt):
        calls.append(prompt)
        return AIMessage(content='Historical working hypothesis only; older reference a1b2c3d4...')
    def middleware():
        return WorkingSummary(model=RunnableLambda(summarize),store=ws.store,role='coordinator',
            trigger=('messages',3),keep=('messages',1),token_counter=lambda m:len(m),trim_tokens_to_summarize=None,summary_prompt=PROMPT)
    history=[HumanMessage('Original task')]
    for n in range(26):history+=pair('first-'+str(n),'Original public value '+str(n),'read_source_page')
    history.append(HumanMessage('Continue'))
    result=await middleware().abefore_model({'messages':history},None)
    assert result and len(calls)==1
    history=add_messages(history,result['messages'])
    first=ws.store.get(key(ws,'coordinator'))[0]
    for n in range(26):history+=pair('second-'+str(n),'Later public value '+str(n),'read_source_page')
    history.append(HumanMessage('Continue after second compaction'))
    result=await middleware().abefore_model({'messages':history},None)
    assert result and len(calls)==2
    resumed=messages_from_dict(messages_to_dict(add_messages(history,result['messages'])))
    assert any(m.additional_kwargs.get('lc_source')=='summarization' for m in resumed)
    records=ws.store.get(key(ws,'coordinator'))
    assert len(records)==52 and first['observation_ref'] not in continuation_index(records)
    reopened=Workspace(Store(ws.store.root))
    found=recovery_tool(reopened,'coordinator')(observation_ref_prefix=first['observation_ref'][:8])
    assert found['total']==1 and found['lookup']['status']=='unique'
    full=found['observations'][0]['observation_ref']
    assert full==first['observation_ref']
    assert read_observation(reopened,'coordinator',full)['text']=='Original public value 0'


def test_lookup_empty_ambiguous_pagination_and_old_default_unchanged(ws):
    seed(ws)
    messages=[]
    for n in range(50):messages+=pair(str(n),'Distinct owned text '+str(n))
    records=capture(ws,'coordinator',messages)
    tool=recovery_tool(ws,'coordinator')
    assert tool(offset=2,limit=3)=={'observations':records[2:5],'total':50,'next_offset':5}
    buckets=defaultdict(list)
    for r in records:buckets[r['observation_ref'][0]].append(r)
    prefix,expected=next((k,v) for k,v in buckets.items() if len(v)>1)
    first=tool(limit=1,observation_ref_prefix=prefix)
    assert first['lookup']['status']=='ambiguous' and first['total']==len(expected)
    assert first['lookup']['distinct_reference_count']==len(expected)
    assert first['observations']==expected[:1] and first['next_offset']==1
    second=tool(offset=1,limit=20,observation_ref_prefix=prefix)
    assert second['observations']==expected[1:21]
    none=tool(observation_ref_prefix='0'*64)
    assert none['observations']==[] and none['total']==0 and none['lookup']['status']=='no_match'
    assert ws.store.get(key(ws,'coordinator'))==records


def test_repeated_receipt_not_false_ambiguity_and_foreign_prefix_has_no_match(ws):
    seed(ws)
    records=capture(ws,'coordinator',pair('a','Same text')+pair('b','Same text'))
    ref=records[0]['observation_ref']
    got=recovery_tool(ws,'coordinator')(observation_ref_prefix=ref[:8])
    assert got['total']==2 and got['lookup']['status']=='unique'
    assert got['lookup']['distinct_reference_count']==1
    with delegated_task(ws,'coordinator',writer_call()):
        found=recovery_tool(ws,'writer')(observation_ref_prefix=ref[:8])
        assert found['total']==0 and found['lookup']['status']=='no_match'


@pytest.mark.parametrize('bad',['','ABCD','abc…','not-hex','a'*65])
def test_lookup_never_guesses_invalid_prefix(ws,bad):
    seed(ws)
    with pytest.raises(ActionRejected,match='INVALID_OBSERVATION_LOOKUP_PREFIX'):
        recovery_tool(ws,'coordinator')(observation_ref_prefix=bad)
    tool=StructuredTool.from_function(recovery_tool(ws,'coordinator'))
    with pytest.raises(ValidationError):tool.invoke({'observation_ref_prefix':bad})


async def test_native_lookup_then_full_observation_producer_and_adoption(ws):
    seed(ws)
    manifest=ws.store.manifest;manifest['decision_data_policy']='reference-data-v1';ws.store.set('manifest',manifest)
    ws.store.set('context_policy','stateful-tools-v1')
    refs=[]
    def start(messages):
        raw=with_source_tables(ws,Catalog(ws.store).read('s',0,1))
        target=capture(ws,'writer',pair('old-source',json.dumps(raw,ensure_ascii=False),'read_source_page'))[0]
        later=[]
        for n in range(22):later+=pair('new-'+str(n),'New unrelated public navigation '+str(n))
        capture(ws,'writer',later)
        refs.append(target['observation_ref'])
        return invoke('read_summary_observations',observation_ref_prefix=refs[0][:8])
    def read(messages):
        result=observation(messages,'read_summary_observations')
        assert result['lookup']['status']=='unique'
        assert result['observations'][0]['observation_ref']==refs[0]
        return invoke('read_tool_observation',observation_ref=refs[0])
    def produce(messages):
        result=observation(messages,'read_tool_observation')
        assert 'Class B permits' in result['text']
        return invoke('process_report_content',operation_id='full-ref-work',objective='Use the actual selected rule',
            object_type='ContentNode',observation_refs=[refs[0]])
    def adopt(messages):
        result=observation(messages,'process_report_content')['metadata']
        return invoke('commit_objects',operation_id='adopt-full-ref',objects=[{'client_key':'body','type':'ContentNode','text_work_id':result['text_work_id']}])
    def done(messages):
        assert observation(messages,'commit_objects')['ok']
        return AIMessage('Committed exact producer result.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage('Done')],
        writer=[start,read,produce,adopt,done],text_tool=[AIMessage(json.dumps(content()))])
    result=await run_report(ws,driver)
    assert result['last_error'] is None
    assert len([r for r,_,_ in driver.calls if r=='text_tool'])==1
    for bound in driver.bindings['writer']:
        tools={t['name']:t for t in bound}
        assert tools['read_tool_observation']['parameters']['properties']['observation_ref']['pattern']=='^[0-9a-f]{64}$'
        assert tools['process_report_content']['parameters']['properties']['observation_refs']['items']['pattern']=='^[0-9a-f]{64}$'
        assert 'observation_ref_prefix' in tools['read_summary_observations']['parameters']['properties']


async def test_short_identity_rejected_by_real_registered_tools_before_producer(ws):
    seed(ws)
    ws.store.set('context_policy','stateful-tools-v1')
    def check(messages):
        errors=[m for m in messages if isinstance(m,ToolMessage) and m.name in {'read_tool_observation','process_report_content'}]
        assert len(errors)==2 and all(m.status=='error' for m in errors)
        assert all('64' in m.content for m in errors)
        return AIMessage('Use lookup to recover the full identity.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage('Done')],writer=[
        invoke('read_tool_observation',observation_ref='166025f5'),
        invoke('process_report_content',operation_id='bad-short-ref',objective='Use owned evidence',object_type='ContentNode',observation_refs=['166025f5']),check])
    await run_report(ws,driver)
    assert not any(r=='text_tool' for r,_,_ in driver.calls)
