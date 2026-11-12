"""Actual exposed projection/recovery/compaction boundary, no paid provider."""
import hashlib
import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict, messages_from_dict
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from report_agent.task_context import TaskContext, save_observation, read_observation, observation_tool
from report_agent.summary_recovery import capture, recovery_tool
from report_agent.working_summary import WorkingSummary, PROMPT
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from report_agent.content_tasks import delegated_task
from test_task_supervision import ws, offline
from test_hierarchical_content import seed
from test_decision_data import activate
from test_text_work import writer_call
from test_deep_runtime import Driver, invoke, observation
from report_agent.deep_runtime import run_report


def saved(ws, value, name='analyze_source_image'):
    raw=json.dumps(value,ensure_ascii=True)
    ref,record=save_observation(ws,'coordinator',ToolMessage(raw,name=name,tool_call_id='original'))
    return ref,record


def test_exact_public_field_and_explicit_tail_recovery_are_not_raw_json(ws):
    seed(ws);activate(ws)
    body='前缀"\\\n😀'*300+'关键完整结尾'
    original={'metadata':'padding'*350,'observation':body}
    message=ToolMessage(json.dumps(original,ensure_ascii=True),name='analyze_source_image',tool_call_id='vision')
    packet=json.loads(TaskContext(ws,'coordinator').bound_result(message).content)
    assert packet['metadata']['observation']==body
    args={'observation_ref':packet['observation_ref'],'field_path':['observation'],
          'offset':1200,'characters':6000}
    actual=StructuredTool.from_function(observation_tool(ws,'coordinator')).invoke(args)
    assert body[:1200]+actual['text']==body
    assert actual['sha256']==hashlib.sha256(message.content.encode()).hexdigest()
    assert actual['field_sha256']==hashlib.sha256(body.encode()).hexdigest()
    assert actual['sha256']!=actual['field_sha256']
    assert actual['complete_tool_result'] is False and actual['complete_field'] is False
    assert read_observation(ws,'coordinator',args['observation_ref'],1200)['text']!=actual['text']


def test_search_return_is_exact_and_nested_array_paths_remain_recoverable(ws):
    seed(ws);activate(ws)
    raw={'padding':['large'*300]*50,'matches':[{'source_id':'s','ordinal':i,'locator':{'page':i+1},
        'text':f'Header {i} '*100+'needle exact condition '+('保留后文'*400)} for i in range(30)]}
    packet=json.loads(TaskContext(ws,'coordinator').bound_result(ToolMessage(encode(raw),
        name='search_sources',tool_call_id='search'),{'query':'needle'}).content)
    entries=packet['metadata']['matches']
    assert entries==raw['matches']
    for i,entry in enumerate(entries):
        args={'observation_ref':packet['observation_ref'],'field_path':['matches',i,'text'],
              'offset':240,'characters':6000}
        page=observation_tool(ws,'coordinator')(**args)
        assert page['text']==raw['matches'][i]['text'][240:240+args['characters']]
        assert 'needle' in entry['text']


def test_raw_default_exact_shape_and_empty_path_json_root_string(ws):
    seed(ws)
    ref,record=saved(ws,'字😀"\\\n'*100)
    raw=read_observation(ws,'coordinator',ref,3,17)
    assert raw=={'observation_ref':ref,'tool':record['tool'],'sha256':record['sha256'],
        'exact_data_tool':'read_tool_observation','cursor_unit':'unicode_characters',
        'text':record['text'][3:20],'offset':3,'end':20,'total_characters':len(record['text']),
        'next_offset':20,'complete_tool_result':False,
        'note':'Exact returned tool text; not complete source coverage, a business read receipt or a completed review.'}
    field=read_observation(ws,'coordinator',ref,field_path=[])
    assert field['text']==json.loads(record['text']) and field['complete_field'] is True
    assert field['complete_tool_result'] is False and field['field_path']==[]


def test_query_at_tail_does_not_remove_prefix_and_field_recovery_stays_exact(ws):
    seed(ws);activate(ws)
    original={'observation':'earlier material '*100+'needle at the very end'}
    packet=json.loads(TaskContext(ws,'coordinator').bound_result(ToolMessage(encode(original),
        name='analyze_source_image',tool_call_id='tail'),{'query':'needle'}).content)
    assert packet['metadata']['observation']==original['observation']
    args={'observation_ref':packet['observation_ref'],'field_path':['observation'],'offset':0}
    assert observation_tool(ws,'coordinator')(**args)['text']==original['observation']


@pytest.mark.parametrize('path',[['absent'],['items',-1],['items','0'],['items',2],['items'],['count'],['items',True], 'items', [1.0], [None], ['x']*65])
def test_invalid_paths_never_fall_back_to_raw_or_convert_indexes(ws,path):
    seed(ws);ref,_=saved(ws,{'items':['first','second'],'count':3})
    with pytest.raises(ActionRejected):read_observation(ws,'coordinator',ref,field_path=path)


def test_schema_strict_paths_and_owner_original_hash_enforced(ws):
    seed(ws);ref,record=saved(ws,{'items':['value']})
    tool=StructuredTool.from_function(observation_tool(ws,'coordinator'))
    for path in ([True],[1.0],[None],'items'):
        with pytest.raises(ValidationError):tool.invoke({'observation_ref':ref,'field_path':path})
    with delegated_task(ws,'coordinator',writer_call()):
        with pytest.raises(ActionForbidden):read_observation(ws,'writer',ref,field_path=['items',0])
    ws.store.set('tool_observation:'+ref,{**record,'text':encode({'items':['changed']})})
    for path in (None,['items',0]):
        with pytest.raises(ActionRejected,match='INTEGRITY'):read_observation(ws,'coordinator',ref,field_path=path)


async def test_visible_field_coordinates_survive_native_compaction_serialization_and_reopen(ws):
    seed(ws);activate(ws)
    original={'first':'甲😀'*9000,'second':'乙'*9000}
    ref,_=saved(ws,original)
    mw=TaskContext(ws,'coordinator');history=[HumanMessage('Use owned observations')]
    for i,(path,offset) in enumerate([(['first'],1200),(['second'],1200),(['first'],7200)]):
        args={'observation_ref':ref,'offset':offset,'characters':4000,'field_path':path}
        history.extend([AIMessage('',id=f'a{i}',tool_calls=[{'name':'read_tool_observation','id':str(i),'args':args,'type':'tool_call'}]),
            mw.bound_result(ToolMessage(encode(observation_tool(ws,'coordinator')(**args)),id=f't{i}',name='read_tool_observation',tool_call_id=str(i)))])
    updates=await mw.abefore_model({'messages':history},None)
    history=add_messages(history,(updates or {}).get('messages',[]))
    first=next(m for m in history if m.id=='t0');cleared=json.loads(first.content)
    assert cleared['field_path']==['first'] and cleared['cursor_scope']=='json_string_value'
    assert cleared['offset']==1200 and cleared['end']==5200
    assert cleared['text']==original['first'][1200:5200]
    assert cleared['field_sha256']==hashlib.sha256(original['first'].encode()).hexdigest()
    assert not first.additional_kwargs.get('report_preview_cleared')
    history.append(HumanMessage('Continue'))
    summary=WorkingSummary(model=RunnableLambda(lambda _:AIMessage('Continue from recorded observations.')),
        store=ws.store,role='coordinator',trigger=('messages',3),keep=('messages',1),
        token_counter=lambda m:len(m),trim_tokens_to_summarize=None,summary_prompt=PROMPT)
    update=await summary.abefore_model({'messages':history},None)
    resumed=messages_from_dict(messages_to_dict(add_messages(history,update['messages'])))
    assert any(m.additional_kwargs.get('lc_source')=='summarization' for m in resumed)
    reopened=Workspace(Store(ws.store.root))
    records=recovery_tool(reopened,'coordinator')()['observations']
    assert len(records)==3
    assert records[0]['selection']['field_path']==['first']
    assert records[0]['delivery']['original_delivery']['field_path']==['first']
    assert records[1]['delivery']['compacted_message_range']['field_path']==['second']
    for r in records:
        result=observation_tool(reopened,'coordinator')(**r['selection'])
        path=r['selection']['field_path'];start=r['selection']['offset']
        assert result['text']==original[path[0]][start:start+4000]


async def test_actual_native_registered_tool_keeps_visible_field_address(ws):
    seed(ws);activate(ws);body='实际原文😀'*4000
    ref,_=saved(ws,{'padding':'x'*2000,'observation':body})
    def finish(messages):
        pages=[json.loads(m.content) for m in messages if isinstance(m,ToolMessage) and m.name=='read_tool_observation']
        assert pages[0]['text']==body[:6000] and pages[0]['field_path']==['observation']
        assert pages[-1]['text']==body[12000:18000] and pages[-1]['cursor_scope']=='json_string_value'
        return AIMessage('Synthetic interface verification only.')
    driver=Driver(coordinator=[invoke('read_tool_observation',observation_ref=ref,field_path=['observation'],offset=n,characters=6000)
        for n in (0,6000,12000)]+[finish])
    result = await run_report(ws,driver)
    assert result["last_error"] is None, result
    for binding in driver.bindings['coordinator']:
        schema=next(t for t in binding if t['name']=='read_tool_observation')['parameters']
        assert 'field_path' in schema['properties']
    assert len(driver.calls)==4


def test_tampered_field_cursor_or_digest_never_cleared_as_verified(ws):
    seed(ws);ref,_=saved(ws,{'a':'same','b':'different'})
    page=read_observation(ws,'coordinator',ref,field_path=['a'])
    for bad in ({**page,'field_path':['b']},{**page,'field_sha256':'0'*64},{**page,'complete_tool_result':True}):
        message=ToolMessage(encode(bad),name='read_tool_observation',tool_call_id='forged')
        assert TaskContext(ws,'coordinator').recoverable_page(message) is message
