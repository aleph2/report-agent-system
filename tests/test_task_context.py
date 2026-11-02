"""Partial protocol validation, not proof of autonomous report quality."""
import json
from types import SimpleNamespace

import pytest
from support.task_state_contract import current_task
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from report_agent.task_context import TaskContext, exact_task_context, read_observation
from report_agent.working_summary import WorkingSummary, SummaryRepairRequired
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden
from test_task_supervision import ws, offline, review_call
from test_hierarchical_content import seed


async def test_exact_recovery_pages_use_existing_owner_ref_and_clear_old_checkpoint_ranges(ws):
    from report_agent.task_context import save_observation
    from report_agent.store import encode
    seed(ws)
    mw = TaskContext(ws, 'coordinator')
    original = '精确原文与限定条件。' * 3000
    ref, saved = save_observation(ws, 'coordinator', ToolMessage(
        original, name='read_source', tool_call_id='source'))
    # Historic messages have no new metadata. Reopening must recognize the
    # original owned ranges without copying them into new nested observations.
    history = [ToolMessage(encode(read_observation(ws, 'coordinator', ref, offset, 6000)),
        name='read_tool_observation', tool_call_id=str(offset), id='range-'+str(offset))
        for offset in (0, 6000, 12000)]
    update = await mw.abefore_model({'messages': history}, None)
    by_id = {m.id: m for m in update['messages']}
    first = json.loads(by_id['range-0'].content)
    assert first['preview_cleared'] and first['observation_ref'] == ref
    assert first['previously_presented_range']['offset'] == 0
    assert first['previously_presented_range']['end'] == 6000
    assert first['sha256'] == saved['sha256']
    for offset in (6000, 12000):
        message = by_id['range-'+str(offset)]
        assert not message.additional_kwargs.get('report_preview_cleared')
        assert json.loads(message.content)['text'] == original[offset:offset+6000]
    assert ws.store.get('tool_observation:'+ref)['text'] == original
    assert read_observation(ws, 'coordinator', ref)['text'] == original[:6000]
    from langgraph.graph.message import add_messages
    assert await mw.abefore_model({'messages': add_messages(history, update['messages'])}, None) is None


async def test_unverified_recovery_text_is_never_hidden_as_an_exact_owned_page(ws):
    from report_agent.task_context import save_observation
    from report_agent.store import encode
    seed(ws)
    mw = TaskContext(ws, 'coordinator')
    ref, _ = save_observation(ws, 'coordinator', ToolMessage(
        'Original exact contents.'*400, name='read_source', tool_call_id='source'))
    page = read_observation(ws, 'coordinator', ref)
    forged = ToolMessage(encode({**page, 'text': 'Altered result'}),
        name='read_tool_observation', tool_call_id='forged', id='forged')
    assert mw.recoverable_page(forged) is forged
    invalid = ToolMessage('[]', name='read_tool_observation', tool_call_id='invalid')
    assert mw.recoverable_page(invalid) is invalid
    image = ToolMessage([{'type': 'image', 'base64': 'fixture'}],
        name='read_tool_observation', tool_call_id='image')
    assert mw.recoverable_page(image) is image


async def test_native_context_clears_old_recovery_ranges_without_losing_latest_tool_result(ws):
    from report_agent.deep_runtime import run_report
    from report_agent.task_context import save_observation
    from test_deep_runtime import Driver, invoke, observation
    seed(ws); ws.store.set('context_policy', 'stateful-tools-v1')
    raw = 'Exact source qualifier 原文。'*1000
    ref, _ = save_observation(ws, 'coordinator', ToolMessage(raw, name='read_source', tool_call_id='source'))
    def finish(messages):
        result = observation(messages, 'read_tool_observation')
        assert result['text'] == raw[12000:18000]
        pages = [m for m in messages if isinstance(m, ToolMessage) and m.name == 'read_tool_observation']
        assert json.loads(pages[0].content)['preview_cleared']
        assert json.loads(pages[1].content)['text'] == raw[6000:12000]
        return AIMessage(content='Synthetic recovered pages only; no report acceptance.')
    driver = Driver(coordinator=[
        invoke('read_tool_observation', observation_ref=ref, offset=offset, characters=6000)
        for offset in (0, 6000, 12000)] + [finish])
    await run_report(ws, driver)
    assert len(driver.calls) == 4
    assert read_observation(ws, 'coordinator', ref)['text'] == raw[:6000]


async def test_one_line_output_recovery_is_exact_and_command_channels_survive(ws):
    seed(ws)
    middleware=TaskContext(ws,'coordinator')
    original='{"long":"'+('精确值与单位；'*12000)+'"}'
    message=ToolMessage(original,name='read_file',tool_call_id='read',id='read-result')
    result=middleware.bound_result(Command(update={'messages':[message],'files':{'/scratch':{'content':['kept']}}}))
    assert result.update['files']=={'/scratch':{'content':['kept']}}
    bounded=result.update['messages'][0]
    ref=bounded.additional_kwargs['report_observation_ref']
    assert bounded.tool_call_id=='read' and bounded.id=='read-result'
    assert len(bounded.content)<8000 and json.loads(bounded.content)['complete_tool_result'] is False
    pieces=[]; offset=0
    while True:
        page=read_observation(ws,'coordinator',ref,offset,4096)
        pieces.append(page['text'])
        if page['next_offset'] is None: break
        offset=page['next_offset']
    assert ''.join(pieces)==original
    reopened=TaskContext(type(ws)(ws.store),'coordinator')
    assert reopened.bound_result(message).additional_kwargs['report_observation_ref']==ref


async def test_masked_history_keeps_pairs_and_does_not_change_business_evidence(ws):
    seed(ws)
    mw=TaskContext(ws,'coordinator')
    history=[]
    for i in range(4):
        history.extend([AIMessage(content='',tool_calls=[{'id':str(i),'name':'read_file','args':{},'type':'tool_call'}]),
            mw.bound_result(ToolMessage('x'*9000,name='read_file',tool_call_id=str(i),id='result'+str(i)))])
    update=await mw.abefore_model({'messages':history},None)
    assert len(update['messages'])==2
    assert {m.tool_call_id for m in update['messages']}=={'0','1'}
    assert all(m.additional_kwargs['report_preview_cleared'] for m in update['messages'])
    # Bodies that can establish a business read, and actual images, are untouched.
    evidence=ToolMessage('x'*9000,name='read_context',tool_call_id='body')
    assert mw.bound_result(evidence) is evidence
    image=ToolMessage([{'type':'image','base64':'image-data'}],name='read_file',tool_call_id='image')
    assert mw.bound_result(image) is image


async def test_large_history_pages_offload_with_exact_actor_scoped_recovery(ws):
    seed(ws)
    mw=TaskContext(ws,'coordinator')
    raw=json.dumps({'entries':[{'text':'Synthetic history; '*2000}]},ensure_ascii=False)
    history=[]
    for i in range(3):
        result=mw.bound_result(ToolMessage(raw,name='read_execution_trace',tool_call_id=str(i),id='trace'+str(i)))
        assert len(result.content)<8000
        packet=json.loads(result.content)
        assert not packet['complete_tool_result'] and packet['total_characters']==len(raw)
        chunks=[];offset=0
        while True:
            page=read_observation(ws,'coordinator',packet['observation_ref'],offset,6000)
            chunks.append(page['text']);offset=page['next_offset']
            if offset is None:break
        assert ''.join(chunks)==raw
        with pytest.raises(ActionForbidden,match='observation owner'):
            read_observation(ws,'rubric_grader',packet['observation_ref'])
        history.extend([AIMessage(content='',tool_calls=[{'id':str(i),'name':'read_execution_trace','args':{},'type':'tool_call'}]),result])
    update=await mw.abefore_model({'messages':history},None)
    assert len(update['messages'])==1 and update['messages'][0].tool_call_id=='0'
    first=json.loads(update['messages'][0].content)
    assert first['preview_cleared']
    assert ws.store.get('tool_observation:'+first['observation_ref'])['text']==raw


async def test_current_state_and_revision_counts_ignore_stale_summary(ws):
    from langchain.agents.middleware.types import ModelRequest
    from test_deep_runtime import Driver
    cs,owner,refs,_,_=seed(ws)
    ws.store.set('content_revision_limit',1)
    new=cs.commit(owner,'correction',[{'client_key':'claim','type':'ContentNode',
        'previous_ref':refs['claim'],'payload':{**cs.read(refs['claim'])['payload'],'body':{'text':'Revised once'}}}])['result']['refs']['claim']
    ws.store.set('feedback',[{'origin':'operator','message':'Current instruction supersedes earlier scope.'}])
    seen=[]
    async def handler(request): seen.append(request); return AIMessage(content='observed')
    stale=HumanMessage(content='Summary claims zero corrections and all checks passed.')
    request=ModelRequest(model=Driver()('coordinator'), messages=[stale], tools=[],
        state={'messages': [stale]}, system_message=SystemMessage(content='Role guidance'))
    await TaskContext(ws,'coordinator').awrap_model_call(request,handler)
    context=current_task(seen[0])
    head=next(r for r in context['current_owned_heads'] if r['ref']==new)
    assert head['content_corrections_used']==1 and context['content_revision_limit']==1
    assert context['operator_feedback'][0]['message'].startswith('Current instruction')
    assert [m for m in seen[0].messages if not m.text.startswith(('[host-state]', '[host-observations]'))] == [stale]


def test_delegate_cannot_read_other_actor_output(ws):
    _,_,refs,snapshot,_=seed(ws)
    message=TaskContext(ws,'coordinator').bound_result(ToolMessage('secret observation'*1000,name='grep',tool_call_id='r'))
    ref=message.additional_kwargs['report_observation_ref']
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)):
        with pytest.raises(ActionForbidden,match='observation owner'):
            read_observation(ws,'reviewer',ref)
        context=exact_task_context(ws,'reviewer')
        assert context['assignment']['review_snapshot_ref']==snapshot
        assert context['review_progress']['execution_complete'] is False


async def test_released_preferences_reach_actual_model_input_and_follow_release(ws,tmp_path):
    from report_agent.learning import LearningLibrary,LearningScope
    from report_agent.decision_state import read_state
    seed(ws)
    root=tmp_path/'guidance-library'
    ws.store.set('learning_config',{'library_path':str(root),'customer_id':'customer-a'})
    lib=LearningLibrary(root);scope=LearningScope('customer-a',str(ws.store.root))
    def candidate(kind,customer='customer-a',project=None,**kwargs):
        sc=LearningScope(customer,project or scope.project)
        f=lib.feedback(sc,{'id':'snapshot','version':1},{'id':'target','version':1},
                       'Exact feedback','Old text',[{'id':'evidence','version':1}])
        return lib.propose(sc,[f['id']],kind,'Released lesson',
            'Exact learner guidance; '+('long unchanged wording; '*200)+'UNIQUE-TAIL',
            'Only for this customer and the stated assignment','Inspect actual output',**kwargs)
    pref=candidate('customer_preference')
    inactive=candidate('customer_preference')
    method=candidate('general_skill');fact=candidate('project_fact')
    foreign=candidate('customer_preference',customer='customer-b')
    other_fact=candidate('project_fact',project='another-project')
    for item in (pref,method,fact):lib.release(scope,item['id'],1,'Offline fixture approval')
    lib.release(LearningScope('customer-b',scope.project),foreign['id'],1,'Other customer')
    lib.release(LearningScope('customer-a','another-project'),other_fact['id'],1,'Other project')
    seen=[]
    async def handler(request):seen.append(request);return AIMessage(content='offline only')
    from langchain.agents.middleware.types import ModelRequest
    from test_deep_runtime import Driver
    messages = [HumanMessage(content='ordinary goal')]
    request=ModelRequest(model=Driver()('coordinator'), messages=messages, tools=[], state={'messages': messages},
        system_message=SystemMessage(content='Role'))
    async def packet():
        await TaskContext(ws,'coordinator').awrap_model_call(request,handler)
        return current_task(seen[-1])
    first=await packet();g=first['learned_guidance']
    assert g['customer_preferences']==[{k:pref[k] for k in ('id','version','kind','title','conditions','customer','project','strategy')}]
    assert g['customer_preferences'][0]['strategy'].endswith('UNIQUE-TAIL')
    assert {r['id'] for r in g['available_experience']}=={method['id'],fact['id']}
    assert all('strategy' not in r for r in g['available_experience'])
    assert inactive['id'] not in json.dumps(g) and foreign['id'] not in json.dumps(g) and other_fact['id'] not in json.dumps(g)
    with delegated_task(ws,'coordinator',{'id':'offline-writer-delegation','args':{'subagent_type':'writer','description':'Write the commissioned paragraph'}}):
        await TaskContext(ws,'writer').awrap_model_call(request,handler)
        writer_context=current_task(seen[-1])
        assert writer_context['learned_guidance']==g
        assert writer_context['assignment']['goal']=='Write the commissioned paragraph'
    assert read_state(ws,'coordinator',['learned_guidance','customer_preferences',0,'strategy'])['value']==pref['strategy']
    second=candidate('customer_preference',experience_id=pref['id'],expected_version=1)
    assert (await packet())['learned_guidance']['customer_preferences'][0]['version']==1
    lib.release(scope,pref['id'],2,'Offline fixture version change')
    assert (await packet())['learned_guidance']['customer_preferences'][0]['version']==2
    lib.release(scope,pref['id'],None,'Revoked')
    assert not (await packet())['learned_guidance']['customer_preferences']
    ws.store.set('learning_config',None)
    assert 'learned_guidance' not in await packet()


@pytest.mark.parametrize('text,finish',[('',None),(' ','stop'),('Cut off','length'),('Working hypothesis and evidence refs.','stop')])
async def test_native_summary_preserves_history_when_unusable(ws,text,finish):
    calls=[]
    async def model(prompt):
        calls.append(prompt)
        return AIMessage(content=text,response_metadata={'finish_reason':finish})
    original=[HumanMessage(content='Task'),AIMessage(content='Investigation'),HumanMessage(content='Continue')]
    mw=WorkingSummary(model=RunnableLambda(model),store=ws.store,trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m),trim_tokens_to_summarize=None)
    result=await mw.abefore_model({'messages':original},None)
    assert len(calls)==1
    assert (result is not None)==bool(text.strip() and finish!='length')
    assert [m.content for m in original]==['Task','Investigation','Continue']


async def test_unusable_summary_policy_cannot_repeat_paid_calls_after_reopen(ws):
    calls=[]
    async def model(prompt):
        calls.append(prompt)
        return AIMessage(content='Incomplete notes',response_metadata={'finish_reason':'length'})
    def middleware(prompt='Notes: {messages}'):
        return WorkingSummary(model=RunnableLambda(model),store=ws.store,
            trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m),
            trim_tokens_to_summarize=None,summary_prompt=prompt)
    history=[HumanMessage(content='Task'),AIMessage(content='Investigation'),HumanMessage(content='Continue')]
    assert await middleware().abefore_model({'messages':history},None) is None
    history.append(HumanMessage(content='New observation does not repair the failed policy'))
    with pytest.raises(SummaryRepairRequired,match='SUMMARY_POLICY_REPAIR_REQUIRED'):
        await middleware().abefore_model({'messages':history},None)
    assert len(calls)==1
    assert len(history)==4
    assert any(e['kind']=='context_summary_retry_blocked' for e in ws.store.events())


def test_native_observation_schema_exposes_and_enforces_range_bounds(ws):
    from langchain_core.tools import StructuredTool
    from pydantic import ValidationError
    from report_agent.task_context import observation_tool
    tool=StructuredTool.from_function(observation_tool(ws,'coordinator'))
    schema=tool.args_schema.model_json_schema()['properties']
    assert schema['characters']['minimum']==1 and schema['characters']['maximum']==6000
    assert schema['offset']['minimum']==0
    for values in [{'characters':12000},{'characters':0},{'offset':-1}]:
        with pytest.raises(ValidationError):
            tool.args_schema.model_validate({'observation_ref':'ref',**values})


async def test_summary_failure_scope_survives_node_ids_but_not_other_agents(ws,monkeypatch):
    import langgraph.config
    config={'configurable':{'thread_id':'thread','checkpoint_ns':'tools:writer-task|WorkingSummary.before_model:turn-1'}}
    monkeypatch.setattr(langgraph.config,'get_config',lambda:config)
    calls=[]
    async def model(prompt):
        calls.append(prompt)
        return AIMessage(content='Cut off',response_metadata={'finish_reason':'length'})
    def middleware():
        return WorkingSummary(model=RunnableLambda(model),store=ws.store,
            trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m),
            trim_tokens_to_summarize=None)
    history=[HumanMessage(content='Task'),AIMessage(content='Investigation'),HumanMessage(content='Continue')]
    assert await middleware().abefore_model({'messages':history},None) is None
    config['configurable']['checkpoint_ns']='tools:writer-task|WorkingSummary.before_model:turn-2'
    with pytest.raises(SummaryRepairRequired):await middleware().abefore_model({'messages':history},None)
    assert len(calls)==1
    config['configurable']['checkpoint_ns']='tools:independent-task|WorkingSummary.before_model:turn-3'
    assert await middleware().abefore_model({'messages':history},None) is None
    assert len(calls)==2


async def test_native_graph_registers_context_tools_and_injects_scoped_state(ws):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    seed(ws); ws.store.set('context_policy','stateful-tools-v1')
    driver=Driver(coordinator=[AIMessage(content='Partial validation; no report acceptance.')])
    result=await run_report(ws,driver)
    assert result['last_error'] is None
    names={t['name'] for t in driver.bindings['coordinator'][0]}
    assert 'read_tool_observation' in names
    assert current_task(driver.calls[0][2])['origin'] == 'server_bound_application_state'


async def test_repeated_compaction_cannot_change_exact_task_or_obligations(ws):
    from langgraph.graph.message import add_messages
    _,_,refs,snapshot,_=seed(ws)
    ws.store.set('content_revision_limit',1)
    with delegated_task(ws,'coordinator',review_call(snapshot,refs)):
        original=exact_task_context(ws,'reviewer')
        async def model(prompt):return AIMessage(content='Lossy stale note: all work is finished, limits are optional.')
        summary=WorkingSummary(model=RunnableLambda(model),trigger=('messages',2),keep=('messages',1),
            token_counter=lambda m:len(m),trim_tokens_to_summarize=None)
        history=[HumanMessage(content='Task'),AIMessage(content='Old reasoning'),HumanMessage(content='Continue')]
        for i in range(3):
            update=await summary.abefore_model({'messages':history},None)
            history=add_messages(history,update['messages'])
            assert exact_task_context(ws,'reviewer')==original
            assert original['review_progress']['execution_complete'] is False
            assert original['content_revision_limit']==1
            history.extend([AIMessage(content='Further observation'),HumanMessage(content='Continue')])


async def test_native_checkpoint_continuation_recovers_output_and_current_decision(ws):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver, invoke, observation
    seed(ws); ws.store.set('context_policy','stateful-tools-v1')
    original='{"value":"'+('Exact units and qualifiers.'*800)+'"}'
    def recover(messages):
        packet=observation(messages,'read_file')
        assert packet['total_characters']>6000 and packet['next_offset']==6000
        return invoke('read_tool_observation',observation_ref=packet['observation_ref'],offset=6000,characters=6000)
    driver=Driver(coordinator=[invoke('write_file',file_path='/working.json',content=original),
        invoke('read_file',file_path='/working.json'),recover,AIMessage(content='Continuation checked, no acceptance.')])
    driver.fail_once=('coordinator',2)
    await run_report(ws,driver)
    assert driver.failed
    ws.store.set('content_execution_decision',{'origin':'operator','instruction':'Preserve contradiction; do not resolve it.'})
    await run_report(ws,driver)
    final=driver.calls[-1][2]
    recovered=observation(final,'read_tool_observation')
    # Native read_file adds a status header; compare with its preserved exact text.
    ref=recovered['observation_ref']
    raw=ws.store.get('tool_observation:'+ref)['text']
    assert recovered['text']==raw[6000:12000] and original in raw
    assert current_task(final)['execution_decision']['instruction'] == 'Preserve contradiction; do not resolve it.'
    assert sum(m.name=='write_file' for m in final if isinstance(m,ToolMessage))==1
