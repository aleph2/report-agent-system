from support.flat_task_fixture import task_arguments
from support.task_state_contract import moved_blocks
import json
from langchain_core.messages import AIMessage
from langgraph.types import interrupt
from report_agent.deep_runtime import run_report
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_review_work_units import configured, unit_todo
from test_deliverable_declaration_v4 import case
from test_deep_runtime import Driver, invoke, observation


async def test_v4_root_reentry_preserves_unresolved_reservation_without_replay(case):
    cs, output, ws, request = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    issue = ws.issue('requirement', 'Synthetic recovery checkpoint', [])
    seen = []
    def checkpoint(messages):
        part, = [p for p in moved_blocks(messages) if p['source'] == 'native_todos/current_child_state']
        text = part['text']
        assert todo['review_unit']['method'] in text
        assert '"_binding"' in text
        seen.append(text)
        assert interrupt({'issue_id':issue['id'],'kind':'synthetic_work_unit'}) == 'Continue fixture'
        return invoke('calculate', terms=[['9','120'],['6','180']])
    results = []
    def done(messages):
        results.append(observation(messages, 'calculate'))
        return AIMessage('Synthetic verification; no review acceptance claimed.')
    scripts = {'coordinator':[AIMessage('',tool_calls=[{**request,'args': task_arguments(cs, case[1], request['args']), 'type':'tool_call'}]),AIMessage('End.')],
               'reviewer':[invoke('write_todos',todos=[todo]),checkpoint,done]}
    initial = await run_report(ws, Driver(**scripts))
    assert initial['status'] == 'needs_human', initial
    reopened = Workspace(Store(ws.store.root))
    reopened.decide_issue(issue['id'], 'Continue fixture', resolved=True)
    resumed_driver = Driver(**scripts)
    reservation = reopened.store.get('native_delegation:' + request['id'])
    with cs.store.connect() as db:
        observations = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
    final = await run_report(reopened, resumed_driver)
    assert final['last_error'] is None, final
    assert len(seen) == 1 and results == []
    assert all(role != 'reviewer' for role, _, _ in resumed_driver.calls)
    feedback = [json.loads(m.content) for _,_,messages in resumed_driver.calls
                for m in messages if m.type == 'tool']
    assert any('NATIVE_DELEGATION_OUTCOME_UNRESOLVED' in m.get('message','') for m in feedback)
    assert reopened.store.get('native_delegation:' + request['id']) == reservation
    with cs.store.connect() as db:
        assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == observations
    assert reopened.store.get('review_plan_contract_binding') == 'work-units-v1'
    assert not cs.list_objects('ReviewRecord')


async def test_same_reviewer_child_checkpoint_keeps_units_without_parent_redispatch(case):
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command
    from report_agent.deep_runtime import business_tools, BusinessBoundary
    from report_agent.review_work_units import ReviewPlanning, bind_contract
    from report_agent.prompt_provenance import CurrentReviewPlan, AgentPromptBoundary
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.content_tasks import delegated_task
    cs, output, ws, request = configured(case)
    bind_contract(ws, ws.store.manifest)
    todo = unit_todo(output['refs']['a-body'])
    seen, results = [], []
    def checkpoint(messages):
        part, = [p for p in moved_blocks(messages) if p['source'] == 'native_todos/current_child_state']
        text = part['text']
        assert todo['review_unit']['method'] in text
        assert '"_binding"' in text
        seen.append(text)
        assert interrupt({'kind':'synthetic_child_checkpoint'}) == 'continue'
        return invoke('calculate',terms=[['9','120']])
    def finish(messages):
        results.append(observation(messages,'calculate'))
        return AIMessage('Synthetic child state retained, no complete review claimed.')
    config={'configurable':{'thread_id':'synthetic-child'}}
    path=str(ws.store.root/'child-checkpoint.db')
    for resumed in (False,True):
        current = Workspace(Store(ws.store.root))
        bind_contract(current,current.store.manifest)
        driver=Driver(reviewer=[invoke('write_todos',todos=[todo]),checkpoint,finish])
        with delegated_task(current,'coordinator',request):
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph=create_agent(driver('reviewer'),system_prompt=SystemMessage(content=[
                    {'type':'text','text':role_prompt('reviewer')},
                    {'type':'text','text':'Synthetic bound Reviewer.'}]),
                    tools=business_tools(current,'reviewer',None,None),
                    middleware=[ReviewPlanning(current),CurrentReviewPlan(current),BusinessBoundary(current,'reviewer'),
                                AgentPromptBoundary(current,'reviewer')],
                    checkpointer=saver)
                await graph.ainvoke(Command(resume='continue') if resumed else
                    {'messages':[HumanMessage('Synthetic direct child retention.')]},config)
                state=await graph.aget_state(config)
                assert bool(state.interrupts) is (not resumed)
                assert state.values['todos'][0]['review_unit']['method'] == todo['review_unit']['method']
    assert len(seen)==2
    assert len(results)==1 and results[0]['ok'], results
    assert not cs.list_objects('ReviewRecord')
