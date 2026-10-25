"""Native planning state and inputs; scripted choices do not prove planning quality."""
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.prompt_provenance import CurrentReviewPlan
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.working_summary import WorkingSummary
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission, candidate
from test_deep_runtime import Driver, invoke, observation, call


def plan(text, status='pending'):
    return [{'content':text,'status':status}]


async def test_current_child_plan_updates_without_becoming_a_save_or_new_task(ws):
    """R01/R02/R03/R11: optional native todos can merge/reorder logical work."""
    native(ws); cs,_,refs,snap,_=seed(ws)
    first=plan('criterion → saved claim → source → inverse check → remaining')
    second=plan('Merged fact and arithmetic checks; retain unresolved source conflict','in_progress')
    def update(messages):
        assert first[0]['content'] in messages[0].text
        assert not cs.list_objects('ReviewRecord')
        return invoke('write_todos',todos=second)
    def read(messages):
        system=messages[0].text
        assert second[0]['content'] in system and first[0]['content'] not in system
        assert 'working intentions only' in system
        assert not cs.list_objects('ReviewRecord')
        return invoke('read_context',target_ref=refs['claim'])
    def submit(messages):
        return invoke('submit_review',operation_id='after-plan',review=candidate(snap,refs,
            [observation(messages,'read_context')['receipt_id']]))
    driver=Driver(coordinator=[invoke('task',**commission(snap,refs)),AIMessage(content='Retained scoped evidence.')],
        reviewer=[invoke('write_todos',todos=first),update,read,submit,AIMessage(content='Saved scoped conclusion.')])
    result=await deep_runtime.run_report(ws,driver)
    assert result['last_error'] is None,result
    assert len(cs.list_objects('ReviewRecord'))==len(cs.list_objects('DelegatedTask'))==1


async def test_native_child_plan_is_in_effective_input_after_checkpoint_reopen(ws):
    """R04: inspect resumed LLM input, not merely stored root todos."""
    native(ws); _,_,refs,snap,_=seed(ws)
    issue=ws.issue('requirement','Synthetic scoped interruption',[])
    current=plan('Resume this child: verify saved claim against assigned criterion','in_progress')
    seen=[]
    def after_plan(messages):
        seen.append(messages[0].text)
        assert current[0]['content'] in messages[0].text
        answer=interrupt({'issue_id':issue['id'],'kind':'synthetic_plan_checkpoint'})
        assert answer=='Continue fixture'
        return AIMessage(content='Plan retained; no semantic acceptance claimed.')
    scripts={'coordinator':[invoke('task',**commission(snap,refs)),AIMessage(content='Retained unfinished check.')],
        'reviewer':[invoke('write_todos',todos=current),after_plan]}
    first=await deep_runtime.run_report(ws,Driver(**scripts))
    assert first['status']=='needs_human',first
    reopened=Workspace(Store(ws.store.root)); reopened.decide_issue(issue['id'],'Continue fixture',resolved=True)
    result=await deep_runtime.run_report(reopened,Driver(**scripts))
    assert result['last_error'] is None,result
    assert len(seen)==2 and all(current[0]['content'] in s for s in seen)
    from report_agent.content_store import ContentStore
    assert not ContentStore(reopened.store).list_objects('ReviewRecord')


async def test_current_plan_survives_real_compaction_and_is_not_a_previous_task_summary(ws):
    """R04/R10: actual SummarizationMiddleware message update plus current child state."""
    native(ws); _,_,refs,snap,_=seed(ws)
    history=[HumanMessage(content='Older task and superseded plan.'),AIMessage(content='Old plan completed.'),
        HumanMessage(content='Latest authorized verification remains unfinished.')]
    summary=WorkingSummary(model=RunnableLambda(lambda _:AIMessage(content='Stale summary says old plan completed.')),
        trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m),trim_tokens_to_summarize=None)
    update=await summary.abefore_model({'messages':history},None)
    compressed=add_messages(history,update['messages'])
    assert len(compressed)<len(history)
    def request_for(state):
        request=SimpleNamespace(state=state,messages=compressed,system_message=SystemMessage(content='Fixture role.'))
        request.override=lambda **changes:SimpleNamespace(**{**request.__dict__,**changes})
        return request
    captured=[]
    async def handler(request):
        captured.append(request);return 'fixture-result'
    with delegated_task(ws,'coordinator',call('task',commission(snap,refs),'compaction-task')) as (_,actor):
        todo=plan('Current criterion and exact deliverable version; evidence still missing','in_progress')
        await CurrentReviewPlan(ws).awrap_model_call(request_for({'messages':compressed,'todos':todo}),handler)
        assert todo[0]['content'] in captured[-1].system_message.text
        assert actor.id in captured[-1].system_message.text
        assert 'Stale summary' not in captured[-1].system_message.text
    with delegated_task(ws,'coordinator',call('task',commission(snap,refs),'different-task')):
        await CurrentReviewPlan(ws).awrap_model_call(request_for({'messages':compressed}),handler)
        assert todo[0]['content'] not in captured[-1].system_message.text
