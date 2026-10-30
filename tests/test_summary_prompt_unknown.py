import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from report_agent.working_summary import WorkingSummary, SummaryRepairRequired
from test_hierarchical_content import ws


@pytest.mark.parametrize('change',['prompt','model','reopen'])
async def test_changed_summary_prompt_does_not_release_unknown_attempt(ws,change):
    calls=[]
    async def model(prompt):
        calls.append(prompt)
        raise TimeoutError('Synthetic sent request without outcome')
    runnable=RunnableLambda(model)
    history=[HumanMessage('Same unfinished historical request.')]
    old=WorkingSummary(model=runnable,store=ws.store,role='coordinator',token_counter=lambda messages:len(messages),summary_prompt='Old summary instructions: {messages}')
    with pytest.raises(TimeoutError):await old._acreate_summary(history)
    original=ws.store.get(old._failure_key())
    from report_agent.store import Store
    store=Store(ws.store.root) if change=='reopen' else ws.store
    revised=WorkingSummary(model=RunnableLambda(model,name='different-summary-model') if change=='model' else runnable,store=store,role='coordinator',token_counter=lambda messages:len(messages),summary_prompt='Revised temporal boundary: {messages}')
    with pytest.raises(SummaryRepairRequired):await revised._acreate_summary(history)
    assert len(calls)==1
    assert ws.store.get(old._failure_key())==original


async def test_unscoped_historical_failure_blocks_without_guessing_or_mutation(ws):
    from langchain_core.messages import AIMessage
    old={'reason':'SUMMARY_OUTCOME_UNKNOWN','original_history_retained':True}
    ws.store.set('summary_policy_failure:old-unattributed-key',old)
    calls=[]
    async def model(prompt):calls.append(prompt);return AIMessage('Unexpected retry')
    summary=WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        token_counter=lambda messages:len(messages),summary_prompt='Current: {messages}')
    with pytest.raises(SummaryRepairRequired,match='UNSCOPED_HISTORICAL'):
        await summary._acreate_summary([HumanMessage('Unfinished')])
    assert calls==[]
    assert ws.store.get('summary_policy_failure:old-unattributed-key')==old


async def test_success_allows_later_summary_with_new_template(ws):
    from langchain_core.messages import AIMessage
    calls=[]
    async def model(prompt):calls.append(prompt);return AIMessage('Useful working notes.')
    for template in ['First: {messages}','Next: {messages}']:
        summary=WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
            token_counter=lambda messages:len(messages),summary_prompt=template)
        await summary._acreate_summary([HumanMessage('Observed work')])
        assert ws.store.get(summary._failure_key()) is None
    assert len(calls)==2


async def test_failed_bound_scope_does_not_block_a_different_thread(ws):
    from langchain_core.messages import AIMessage
    calls=[]
    async def model(prompt):
        calls.append(prompt)
        if len(calls)==1:raise TimeoutError('Synthetic unknown')
        return AIMessage('Other scope working notes.')
    summary=WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        token_counter=lambda messages:len(messages),summary_prompt='Notes: {messages}')
    async def run(_):return await summary._acreate_summary([HumanMessage('Scoped work')])
    runner=RunnableLambda(run)
    with pytest.raises(TimeoutError):await runner.ainvoke({},config={'configurable':{'thread_id':'A'}})
    await runner.ainvoke({},config={'configurable':{'thread_id':'B'}})
    assert len(calls)==2


@pytest.mark.parametrize('damage',['missing-target','bad-pointer','empty-failure','wrong-failure-type'])
async def test_damaged_scope_records_fail_closed_without_model(ws,damage):
    import json
    calls=[]
    async def model(prompt):calls.append(prompt);raise TimeoutError('Synthetic unknown')
    summary=WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        token_counter=lambda messages:len(messages),summary_prompt='Notes: {messages}')
    with pytest.raises(TimeoutError):await summary._acreate_summary([HumanMessage('Original')])
    with ws.store.connect() as db:
        key,raw=db.execute("SELECT key,value FROM state WHERE key LIKE 'summary_failure_scope:%'").fetchone()
        binding=json.loads(raw)
        if damage=='missing-target':db.execute('DELETE FROM state WHERE key=?',(binding['failure_key'],))
        elif damage=='bad-pointer':db.execute('UPDATE state SET value=? WHERE key=?',('{}',key))
        else:db.execute('UPDATE state SET value=? WHERE key=?',('{}' if damage=='empty-failure' else '0',binding['failure_key']))
    with pytest.raises(SummaryRepairRequired,match='INVALID'):
        await summary._acreate_summary([HumanMessage('Must not auto-repair')])
    assert len(calls)==1


async def test_parallel_scope_request_cannot_overwrite_pending_unknown(ws):
    import asyncio,json
    from report_agent.store import Store
    entered=asyncio.Event();release=asyncio.Event();calls=[]
    async def model(prompt):
        calls.append(prompt);entered.set();await release.wait();raise TimeoutError('Unresolved first')
    first=WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        token_counter=lambda messages:len(messages),summary_prompt='First: {messages}')
    second=WorkingSummary(model=RunnableLambda(model),store=Store(ws.store.root),role='coordinator',
        token_counter=lambda messages:len(messages),summary_prompt='Changed: {messages}')
    pending=asyncio.create_task(first._acreate_summary([HumanMessage('Same scope')]))
    await entered.wait()
    before=ws.store.get(first._failure_key())
    try:
        with pytest.raises(SummaryRepairRequired):await second._acreate_summary([HumanMessage('Do not duplicate')])
        assert ws.store.get(first._failure_key())==before
        assert len(calls)==1
    finally:
        release.set()
        with pytest.raises(TimeoutError):await pending


async def test_completed_failure_key_cannot_be_reassigned_to_another_role(ws):
    from langchain_core.messages import AIMessage
    calls=[]
    async def model(prompt):calls.append(prompt);return AIMessage('Useful notes.')
    runnable=RunnableLambda(model)
    first=WorkingSummary(model=runnable,store=ws.store,role='coordinator',
        token_counter=lambda messages:len(messages),summary_prompt='Notes: {messages}')
    second=WorkingSummary(model=runnable,store=ws.store,role=None,
        token_counter=lambda messages:len(messages),summary_prompt='Notes: {messages}')
    assert first._failure_key()==second._failure_key()
    await first._acreate_summary([HumanMessage('First scope')])
    with ws.store.connect() as db:before=db.execute("SELECT key,value FROM state WHERE key LIKE 'summary_%' ORDER BY key").fetchall()
    with pytest.raises(SummaryRepairRequired,match='CONFLICT'):
        await second._acreate_summary([HumanMessage('Different role same key')])
    with ws.store.connect() as db:after=db.execute("SELECT key,value FROM state WHERE key LIKE 'summary_%' ORDER BY key").fetchall()
    assert after==before
    assert len(calls)==1
