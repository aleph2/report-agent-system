"""Native public result boundary and exact tool-side adoption, no paid models."""
import json
import pytest
from langchain_core.messages import ToolMessage,AIMessage
from report_agent.task_context import TaskContext,read_observation,exact_task_context
from report_agent.decision_data import bind
from report_agent.errors import ActionRejected,ActionForbidden
from report_agent.content_tasks import delegated_task
from report_agent.hierarchical_tools import actor_for
from report_agent.text_work import produce,adopt,AdoptionObject
from report_agent.deep_runtime import business_tools,run_report
from test_hierarchical_content import ws,seed
from test_bounded_review import Model
from test_deep_runtime import Driver,invoke

def activate(ws):
    ws.store.set('context_policy','stateful-tools-v1')
    ws.store.set('manifest',{**ws.store.manifest,'review_entrypoint':'delegated-reviewer-v1',
        'review_execution_mode':'bounded-tool-v1','decision_data_policy':'reference-data-v1'})
    bind(ws)

def test_explicit_source_read_is_complete_located_and_exact_original_recoverable(ws):
    seed(ws);activate(ws)
    text='完整限定条件；'*12000
    raw={'source':{'id':'s','title':'Actual original'},'offset':0,'next_offset':1,
        'total_blocks':2,'blocks':[{'ordinal':0,'locator':{'page':1},'text':text}]}
    msg=ToolMessage(content=json.dumps(raw,ensure_ascii=False),name='read_source_page',tool_call_id='source')
    bounded=TaskContext(ws,'coordinator').bound_result(msg)
    packet=json.loads(bounded.content)
    assert packet['metadata']==raw
    assert packet['metadata']['blocks'][0]['ordinal']==0
    assert packet['metadata']['blocks'][0]['text']==text
    assert packet['complete_original_in_decision'] is True
    assert bounded.additional_kwargs['report_observation_delivery']['representation']=='exact-public-result-v2'
    assert read_observation(ws,'coordinator',packet['observation_ref'],0,6000)['text']==msg.content[:6000]
    assert exact_task_context(ws,'coordinator')['decision_data']['policy']=='reference-data-v1'

async def test_independent_tool_consumes_owned_image_data_and_exact_adoption_without_copy(ws):
    cs,_,refs,snap,_=seed(ws);activate(ws)
    with delegated_task(ws,'coordinator',{'id':'writer','args':{'subagent_type':'writer','description':'Scoped writing'}}) as (_,actor):
        middleware=TaskContext(ws,'writer')
        observed={'source_id':'s','page':1,'observation':'实际图像观测：限定条件必须保留。','status':'observed','limitations':['Not source completeness.']}
        source=middleware.bound_result(ToolMessage(content=json.dumps(observed,ensure_ascii=False),name='analyze_source_image',tool_call_id='image'))
        image_ref=json.loads(source.content)['observation_ref']
        payload={'kind':'block','body':{'text':'完整原文内容；'*500},'qualifiers':{'condition':'Observed image limited to page1'},'claim_kind':'fact'}
        model=Model(json.dumps(payload))
        work=await produce(ws,actor,model,'work','Use supplied located observations','ContentNode',
            input_refs=[refs['claim']],observation_refs=[image_ref])
        assert observed['observation'] in str(model.calls)
        shown=middleware.bound_result(ToolMessage(content=json.dumps(work,ensure_ascii=False),name='process_report_content',tool_call_id='produce'))
        packet=json.loads(shown.content)
        assert 'payloads' not in packet['metadata'] and 'payload' not in packet['metadata']
        assert packet['metadata']['text_work_id']==work['text_work_id']
        assert packet['metadata']['outputs']['entries'][0]['index']==0
        assert adopt(ws,actor,work['text_work_id'],'ContentNode')==payload
        t={t.__name__:t for t in business_tools(ws,'writer',None,model)}
        saved=t['commit_objects']('save',[AdoptionObject(client_key='x',type='ContentNode',text_work_id=work['text_work_id'])])
        assert cs.read(saved['result']['refs']['x'])['payload']==payload
    with delegated_task(ws,'coordinator',{'id':'other','args':{'subagent_type':'writer','description':'Another task'}}) as (_,other):
        with pytest.raises(ActionForbidden,match='observation owner'):
            await produce(ws,other,model,'steal','Read foreign return','ContentNode',input_refs=[refs['claim']],observation_refs=[image_ref])

def test_restore_exact_criterion_contract_and_discover_requirement_namespace(ws):
    seed(ws);activate(ws)
    t={t.__name__:t for t in business_tools(ws,'coordinator',None,Model('{}'))}
    for field in ('requirement_refs','purpose','scope','expected_outcome','evidence_expectation','allowed_limits','client_key'):
        assert field in t['commit_objects'].__doc__
    inputs=exact_task_context(ws,'coordinator')['input_refs']
    requirement=next(r['ref'] for r in inputs if r['ref']['type']=='Requirement')
    result=t['commit_objects']('criterion',[AdoptionObject(client_key='c',type='Criterion',payload={
        'requirement_refs':[requirement],'purpose':'Actual useful draft','scope':'selected scope',
        'expected_outcome':'Retain actual conditions','evidence_expectation':'Actual sources','allowed_limits':'Unresolved scope retained'})])
    assert result['result']['refs']['c']['type']=='Criterion'

async def test_native_platform_offload_keeps_source_control_and_exact_recovery(ws):
    from langchain.agents.middleware import ModelResponse
    seed(ws);activate(ws)
    literal='长原文限定事实。'*12000
    ws.store.set('manifest',{**ws.store.manifest,'sources':[{'id':'s','title':'Source','content':literal,'coverage':'complete'}]})
    # Existing frozen blocks are the native data input, not an injected model answer.
    from report_agent.catalog import Catalog
    catalog=Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.execute('insert into source_blocks values (?,?,?,?)',('s',0,json.dumps({'page':1}),literal))
    driver=Driver(coordinator=[invoke('read_source_page',source_id='s',offset=0,limit=1),AIMessage(content='Selected material available; no acceptance.')])
    await run_report(ws,driver)
    second=str(driver.calls[1][2])
    assert literal not in second and 'reference-data-v1' in second
    assert len(second)<len(literal)/2
    replies=[m for m in driver.calls[1][2] if isinstance(m,ToolMessage) and m.name=='read_source_page']
    assert replies[-1].additional_kwargs['report_controls_restored'] is True
    # Native filesystem eviction can defer a large body, but never claim it was read.
    blocks=replies[-1].content
    public=json.loads(next(b['text'] for b in reversed(blocks) if b.get('type')=='text'))
    assert public['complete_original_in_decision'] is False
    assert public['platform_offloaded_data_paths']
    assert public['metadata']['blocks']['total_returned']==1
    assert not any(e['kind']=='working_summary_intent' for e in ws.store.events())
    event=next(e for e in ws.store.events() if e['kind']=='decision_data_delivered' and e['data']['tool']=='read_source_page')
    original=ws.store.get('tool_observation:'+event['data']['observation_ref'])
    assert json.loads(original['text'])['blocks'][0]['text']==literal

def test_policy_immutable_after_binding_and_errors_are_not_hidden(ws):
    seed(ws);activate(ws)
    error=ToolMessage(content='INVALID_CONTRACT precise issue',name='read_source_page',tool_call_id='failed',status='error')
    shown=TaskContext(ws,'coordinator').bound_result(error)
    packet=json.loads(shown.content)
    assert (shown.name,shown.tool_call_id,shown.status)==(error.name,error.tool_call_id,'error')
    assert packet['status']=='error' and packet['metadata']['text']==error.content
    assert packet['complete_original_in_decision'] is True
    assert ws.store.get('tool_observation:'+packet['observation_ref'])['text']==error.content
    ws.store.set('manifest',{k:v for k,v in ws.store.manifest.items() if k!='decision_data_policy'})
    with pytest.raises(ActionRejected,match='BINDING_CHANGED'):bind(ws)

def test_search_retains_whole_return_and_all_32_output_qualifiers_survive(ws):
    seed(ws);activate(ws)
    prefix='Unrelated page header. '*100
    raw={'matches':[{'source_id':'s','ordinal':3,'locator':'page4','text':prefix+'K9020+380 actual matched condition.'+' remainder'*3000}]}
    message=ToolMessage(content=json.dumps(raw),name='search_sources',tool_call_id='search')
    bounded=TaskContext(ws,'coordinator').bound_result(message,{'query':'K9020+380'})
    actual=json.loads(bounded.content)['metadata']['matches'][0]['text']
    assert actual==raw['matches'][0]['text']
    payload={'kind':'block','body':{'text':'Exact unchanged output.'*100},'claim_kind':'fact',
        'qualifiers':{'uncertainty':'Long genuine condition; '*2000}}
    output={'text_work_id':'real-receipt','object_type':'ContentNode','payload':payload,
        'payloads':[payload for _ in range(32)],'state':'completed','semantic_correctness_verified':False}
    shown=TaskContext(ws,'coordinator').bound_result(ToolMessage(content=json.dumps(output),
        name='process_report_content',tool_call_id='producer'))
    meta=json.loads(shown.content)['metadata']
    assert [p['index'] for p in meta['outputs']['entries']]==list(range(32))
    assert meta['outputs']['complete'] is True
    assert all(p['qualifiers']==payload['qualifiers'] for p in meta['outputs']['entries'])
    assert all(p['body_deferred'] and 'body' not in p for p in meta['outputs']['entries'])
    assert meta['semantic_correctness_verified'] is False

async def test_reference_metadata_is_retained_instead_of_cleared_like_bulk_navigation(ws):
    seed(ws);activate(ws);middleware=TaskContext(ws,'coordinator')
    messages=[middleware.bound_result(ToolMessage(content=json.dumps({'source_id':'s','offset':i,
        'blocks':[{'ordinal':i,'locator':{'page':i+1},'text':'原文。'*2000}]}),
        name='read_source_page',tool_call_id=str(i))) for i in range(4)]
    assert await middleware.abefore_model({'messages':messages},None) is None
    assert all('metadata' in json.loads(m.content) for m in messages)
