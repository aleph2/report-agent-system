"""Real native middleware, scripted model only; no paid calls."""
import pytest
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage,HumanMessage,RemoveMessage
from report_agent.deep_models import configured_model
from report_agent.store import Store
from report_agent.working_summary import WorkingSummary, working_summary, SUMMARY_OUTPUT_LIMIT

@pytest.mark.parametrize('answer',['','   ','Useful saved findings and next actions.'])
async def test_empty_summary_preserves_history_otherwise_native_compaction(tmp_path,answer):
    calls=[]
    async def model(prompt):calls.append(prompt);return AIMessage(content=answer)
    original=[HumanMessage(content='Authorized goal.'),AIMessage(content='Evidence read.'),HumanMessage(content='Next useful action.')]
    store=Store(tmp_path)
    mw=WorkingSummary(model=RunnableLambda(model),trigger=('messages',2),keep=('messages',1),token_counter=lambda messages:len(messages),store=store)
    result=await mw.abefore_model({'messages':original},None)
    assert len(calls)==1
    if not answer.strip():
        assert result is None
        assert [m.content for m in original]==['Authorized goal.','Evidence read.','Next useful action.']
        assert any(e['kind']=='context_summary_rejected' for e in store.events())
    else:
        assert isinstance(result['messages'][0],RemoveMessage)
        assert result['messages'][1].content.endswith(answer)
        assert result['messages'][-1].content=='Next useful action.'

async def test_summary_wrapper_does_not_multiply_failed_sdk_requests():
    calls=[]
    async def model(prompt):calls.append(prompt);raise TimeoutError('offline')
    mw=WorkingSummary(model=RunnableLambda(model),trigger=('messages',2),keep=('messages',1),token_counter=lambda messages:len(messages))
    with pytest.raises(TimeoutError):await mw.abefore_model({'messages':[HumanMessage(content='a'),AIMessage(content='b'),HumanMessage(content='c')]},None)
    assert len(calls)==1

async def test_summary_mode_changes_only_summary_instance(tmp_path,monkeypatch):
    for suffix,value in [('MODEL','deepseek-v4.1-flash-1017'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','offline-key')]:monkeypatch.setenv('REPORT_'+suffix,value)
    normal=configured_model(Store(tmp_path/'normal'),'coordinator')
    summary=working_summary(normal,Store(tmp_path/'summary')).model
    try:
        assert normal.extra_body=={'enable_thinking':True}
        request=summary._get_request_payload([HumanMessage(content='offline')])
        assert request['extra_body']=={'enable_thinking':False}
        assert request['max_tokens']==SUMMARY_OUTPUT_LIMIT==16384 and 'reasoning_effort' not in request
        assert summary.model_name==normal.model_name
        assert summary.root_async_client.max_retries==normal.root_async_client.max_retries
    finally:await normal.root_async_client.close();normal.root_client.close();await summary.root_async_client.close();summary.root_client.close()


async def test_changed_summary_output_policy_keeps_old_failure_and_does_not_replay_it(tmp_path, monkeypatch):
    from report_agent.working_summary import SummaryRepairRequired
    for suffix, value in [('MODEL','deepseek-v4.1-flash-1017'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','offline-key')]:
        monkeypatch.setenv('REPORT_'+suffix, value)
    store = Store(tmp_path/'summary')
    normal = configured_model(store, 'coordinator')
    revised = working_summary(normal, store)
    old = working_summary(normal, store)
    old.model.max_tokens = 4096
    try:
        old_key = old._failure_key()
        failure = {'reason': 'UNUSABLE_SUMMARY', 'finish_reason': 'length', 'original_history_retained': True}
        store.set(old_key, failure)
        assert revised._failure_key() != old_key
        with pytest.raises(SummaryRepairRequired):
            await old._acreate_summary([HumanMessage(content='No HTTP: old failure must block first.')])
        assert store.get(old_key) == failure
        assert store.get(revised._failure_key()) is None
    finally:
        await normal.root_async_client.close(); normal.root_client.close()
