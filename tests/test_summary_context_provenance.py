"""Native compaction/input/wire regressions, not model semantic validation."""
import hashlib
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph.message import add_messages
from langchain.agents.middleware.types import ModelRequest

from report_agent.content_tasks import delegated_task
from report_agent.deep_models import GLMChatOpenAI, configured_model
from report_agent.decision_state import compact_context
from report_agent.store import encode
from report_agent.task_context import exact_task_context
from report_agent.working_summary import WorkingSummary, PROMPT
from test_hierarchical_content import ws, seed


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('Provider access forbidden in offline interface checks')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


def middleware(ws, model, role='coordinator', trigger=2):
    return WorkingSummary(model=RunnableLambda(model), store=ws.store, role=role,
        trigger=('messages', trigger), keep=('messages', 1),
        token_counter=lambda messages: len(messages), trim_tokens_to_summarize=None,
        summary_prompt=PROMPT)


async def effective_messages(mw, history):
    captured = []
    async def handler(request):
        captured.extend(request.messages)
        return AIMessage('Synthetic handler response')
    await mw.awrap_model_call(ModelRequest(model=mw.model,
        messages=history, state={'messages':history}), handler)
    return captured


async def test_actual_native_summary_input_includes_current_feedback_and_bound_assignment(ws):
    cs, _, _, _, _ = seed(ws)
    feedback = ('Current evidence contradicts the old conclusion. ' + 'Preserve this qualifier. ' * 45).strip()
    ws.store.add_feedback(feedback)
    history = [HumanMessage('Initial task', id='a'),
        AIMessage('Old unsupported claim: all work complete.', id='b'),
        HumanMessage('Continue', id='c')]
    before = deepcopy(history)
    calls = []
    async def model(prompt):
        calls.append(str(prompt))
        return AIMessage('Conflicting conclusion remains unresolved.')
    with delegated_task(ws, 'coordinator', {'id':'writer-assignment',
            'args':{'subagent_type':'writer','description':'Check actual source conditions.'}}):
        expected = compact_context(exact_task_context(ws, 'writer'))
        objects_before = cs.list_objects()
        mw = middleware(ws, model, 'writer')
        result = await mw.abefore_model({'messages':history}, None)
        assert len(calls) == 1
        assert feedback in calls[0]
        assert encode(expected) in calls[0]
        assert 'Old unsupported claim' in calls[0]
        assert 'current application context' in calls[0].lower()
        # Source catalogs are references, not an automatic new full-source read.
        assert 'Class B permits 75 to 100.' not in calls[0]
        assert cs.list_objects() == objects_before
        merged = add_messages(history, result['messages'])
        assert 'report_summary_provenance' not in merged[0].additional_kwargs
        effective = await effective_messages(mw, merged)
        assert 'not a new user' in effective[0].content.lower()
        assert 'Conflicting conclusion remains unresolved.' in effective[0].content
    assert history == before


async def test_legacy_summary_gets_visible_provenance_without_rewriting_notes_or_protocol(ws, monkeypatch):
    seed(ws)
    raw = 'Here is a summary of the conversation to date:\n\nOld hypothesis, not yet tested.'
    summary = HumanMessage(raw, id='saved-summary', additional_kwargs={'lc_source':'summarization'})
    ordinary = HumanMessage(raw, id='real-user')
    retained = AIMessage('', id='ai', additional_kwargs={'reasoning_content':'opaque unchanged value'},
        tool_calls=[{'id':'call','name':'read_source','args':{},'type':'tool_call'}])
    tool = ToolMessage('Exact source observation.', id='tool', tool_call_id='call')
    history = [summary, ordinary, retained, tool]
    before = deepcopy(history)
    calls = []
    async def model(prompt):
        calls.append(prompt)
        raise AssertionError('No compaction needed')
    mw = middleware(ws, model, trigger=100)
    result = await mw.abefore_model({'messages':history}, None)
    assert result is None
    updated = await effective_messages(mw, history)
    assert [m.id for m in updated] == [m.id for m in history]
    assert updated[0].content.endswith(raw)
    assert 'not a new user' in updated[0].content.lower()
    assert updated[0].additional_kwargs['report_summary_provenance']['original_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert updated[1:] == history[1:]
    assert history == before and calls == []
    assert await mw.abefore_model({'messages':history}, None) is None
    assert await effective_messages(mw, updated) == updated
    for key, value in [('MODEL','deepseek-v4.1-flash-1017'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','synthetic')]:
        monkeypatch.setenv('REPORT_'+key, value)
    adapters = [configured_model(ws.store, 'coordinator'),
        GLMChatOpenAI(model='glm-5.3', api_key='synthetic', base_url='https://offline.invalid/v1',
            use_responses_api=False, disable_streaming=True)]
    try:
        for adapter in adapters:
            wire = adapter._get_request_payload(updated)['messages']
            assert wire[0]['role'] == 'user'  # Keep the pinned native protocol.
            assert 'not a new user' in wire[0]['content'].lower()
            assert wire[0]['content'].endswith(raw)
            assert wire[1]['content'] == raw
            assert wire[2]['reasoning_content'] == 'opaque unchanged value'
            assert wire[2]['tool_calls'][0]['id'] == wire[3]['tool_call_id']
            assert 'reasoning_content' not in wire[0]
    finally:
        for adapter in adapters:
            await adapter.root_async_client.close()
            adapter.root_client.close()


async def test_summary_relabel_preserves_original_record_and_does_not_upgrade_claim(ws):
    seed(ws)
    raw = 'A model asserted completion without evidence.'
    async def model(prompt):
        return AIMessage(raw)
    mw = middleware(ws, model)
    result = await mw.abefore_model({'messages':[
        HumanMessage('Task', id='task'), AIMessage('Unverified', id='old'),
        HumanMessage('Continue', id='new')]}, None)
    persisted_note = result['messages'][1]
    assert 'report_summary_provenance' not in persisted_note.additional_kwargs
    note = (await effective_messages(mw, [persisted_note]))[0]
    provenance = note.additional_kwargs['report_summary_provenance']
    record = ws.store.get(provenance['preserved_original_key'])
    assert record['original_content'].endswith(raw)
    assert record['original_sha256'] == hashlib.sha256(record['original_content'].encode()).hexdigest()
    assert 'not source evidence' in note.content.lower()
    assert 'A model asserted completion without evidence.' in note.content
    assert provenance['generation_time'] == 'unknown'


async def test_wire_label_does_not_accumulate_into_next_native_compaction_trigger(ws):
    seed(ws)
    calls = []
    async def model(prompt):
        calls.append(prompt)
        return AIMessage('Unexpected summary')
    history = [HumanMessage('Short old notes.', id='old',
        additional_kwargs={'lc_source':'summarization'}), HumanMessage('Continue', id='new')]
    original = deepcopy(history)
    counter = lambda messages: sum(len(m.content) for m in messages)
    mw = WorkingSummary(model=RunnableLambda(model), store=ws.store, role='coordinator',
        trigger=('tokens',200), keep=('messages',1), token_counter=counter,
        trim_tokens_to_summarize=None, summary_prompt=PROMPT)
    for _ in range(3):
        assert await mw.abefore_model({'messages':history}, None) is None
        effective = await effective_messages(mw, history)
        assert counter(effective) > 200  # Wire overhead is real, not hidden.
        assert history == original and counter(history) < 200
    assert calls == []


async def test_new_feedback_or_clock_does_not_clear_unknown_summary_failure(ws):
    from report_agent.working_summary import SummaryRepairRequired
    seed(ws)
    calls = []
    async def model(prompt):
        calls.append(prompt)
        raise TimeoutError('Synthetic unknown outcome')
    mw = middleware(ws, model)
    history = [HumanMessage('Task'), AIMessage('Pending assumption'), HumanMessage('Continue')]
    with pytest.raises(TimeoutError):
        await mw.abefore_model({'messages':history}, None)
    key = mw._failure_key()
    original = ws.store.get(key)
    ws.store.add_feedback('A new factual observation does not authorize retrying the unknown summary.')
    ws.store.set('content_execution_decision', {'origin':'operator','instruction':'Preserve unknown result.'})
    assert mw._failure_key() == key
    with pytest.raises(SummaryRepairRequired):
        await mw.abefore_model({'messages':history}, None)
    assert len(calls) == 1 and ws.store.get(key) == original
