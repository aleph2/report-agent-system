"""Synthetic refusal/success timeline: native compaction and SDK, not semantic proof."""
import json
from copy import deepcopy
import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph.message import add_messages
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.working_summary import WorkingSummary, PROMPT
from report_agent.task_context import TaskContext
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission, candidate
from test_deep_runtime import call
from test_prompt_native_sdk_inputs import completion


@pytest.mark.parametrize('later_success', [False, True])
async def test_old_refusal_and_later_state_have_separate_time_scopes(ws, later_success):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, 'coordinator', call('task', commission(snapshot,refs), 'summary-task')) as (_, actor):
        root_receipt = cs.read_context(actor, refs['root'])['receipt_id']
        with pytest.raises(ActionRejected) as rejected:
            cs.submit_review(actor, 'old-call-A', candidate(snapshot,refs,[root_receipt]), {})
        result = {'ok':False,'code':str(rejected.value)}
        record_id = None
        if later_success:
            receipt = cs.read_context(actor, refs['claim'])['receipt_id']
            result = cs.submit_review(actor, 'later-call-B', candidate(snapshot,refs,[receipt]), {})
            record_id = cs.list_objects('ReviewRecord')[0]['ref']['id']
        old_ai = AIMessage('', id='old-ai', tool_calls=[call('submit_review',{},'A')])
        old_tool = ToolMessage(str(rejected.value), id='old-result', tool_call_id='A')
        new_ai = AIMessage('', id='later-ai', tool_calls=[call('submit_review',{},'B')],
                           additional_kwargs={'reasoning_content':'synthetic opaque protocol'})
        new_tool = ToolMessage(json.dumps(result), id='later-result', tool_call_id='B')
        history = [HumanMessage('Synthetic review',id='start'),old_ai,old_tool,
                   HumanMessage('Correction follows',id='between'),new_ai,new_tool,HumanMessage('Continue',id='last')]
        before = deepcopy(history)
        before_objects = cs.list_objects()
        summary_inputs=[]
        async def summarize(prompt):
            summary_inputs.append(str(prompt))
            return AIMessage('Historical rejection remains distinct from current state.')
        mw = WorkingSummary(model=RunnableLambda(summarize),store=ws.store,role='reviewer',
            trigger=('messages',3),keep=('messages',3),token_counter=lambda messages:len(messages),
            trim_tokens_to_summarize=None,summary_prompt=PROMPT)
        update = await mw.abefore_model({'messages':history},None)
        assert len(summary_inputs)==1
        text=summary_inputs[0]
        assert 'Historical subset being compacted' in text
        historical,current=text.split('Current application context captured at',1)
        assert 'later events' in current and 'not proof that an earlier rejected call committed' in current
        assert str(rejected.value) in historical
        assert 'later-call-B' not in historical and 'later-result' not in historical
        if record_id:
            assert record_id not in historical and record_id in current
        merged=add_messages(history,update['messages'])
        assert merged[-3:]==history[-3:]
        wires=[]
        client=model_async_client(ws.store,'reviewer')
        def transport(request):
            wires.append(json.loads(request.content)); return completion(request,'Synthetic end.')
        client._transport=httpx.MockTransport(transport);client._mounts.clear()
        model=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        try:
            graph=create_agent(model,tools=[],middleware=[TaskContext(ws,'reviewer')])
            await graph.ainvoke({'messages':merged})
            wire=wires[0]['messages']
            retained=next(m for m in wire if m.get('tool_call_id')=='B')
            assert retained['content']==new_tool.content
            if record_id: assert record_id in json.dumps(wire)
            assert cs.list_objects()==before_objects
            assert history==before
        finally:
            await model.root_async_client.close();model.root_client.close()
