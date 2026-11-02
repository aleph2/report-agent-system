"""Model-facing delivery tests, not evidence of semantic application."""
import copy
import json
from types import SimpleNamespace

import pytest
from support.task_state_contract import current_task
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from report_agent.decision_state import compact_context, read_state
from report_agent.store import encode, digest
from report_agent.task_context import TaskContext
from test_task_supervision import ws
from test_hierarchical_content import seed


def feedback_body():
    return 'Developer observation, not an engineering verdict.\n' + '原文、适用范围和未决条件。'*180 + '\nTAIL: do not use pile length as slope height.'


@pytest.mark.asyncio
async def test_actual_model_middleware_delivers_whole_moderate_feedback_after_stale_summary(ws):
    seed(ws)
    body = feedback_body()
    assert 600 < len(body) < 6000
    item = {'id':'exact-feedback-id', 'origin':'operator', 'message':body}
    ws.store.set('feedback', [item])
    stale = HumanMessage(content='Old summary says no feedback and task already complete.')
    request = SimpleNamespace(messages=[stale], system_message=SystemMessage(content='Existing role.'))
    request.state = {'messages': request.messages}
    request.override = lambda **kw: SimpleNamespace(**{**request.__dict__, **kw})
    seen=[];business=[]
    async def handler(value):
        from report_agent.task_state_delivery import business_messages
        seen.append(value)
        business.append(business_messages(ws.store,value.messages))
        return AIMessage(content='Input capture only, not semantic acceptance.')
    await TaskContext(ws, 'coordinator').awrap_model_call(request, handler)
    packet = current_task(seen[0])
    assert packet['operator_feedback'][0] == item
    assert business == [[stale]] and business[0][0] is stale
    assert ws.store.get('feedback') == [item]


def test_all_operator_feedback_remains_exact_without_rewriting_origin_or_old_paths():
    body = feedback_body()
    records = [{'id':str(i), 'origin':'operator', 'message':body+str(i)} for i in range(25)]
    original = {'goal':'goal', 'operator_feedback':records}
    before = copy.deepcopy(original)
    packet = compact_context(original)['operator_feedback']
    assert packet == records
    assert len(packet) == 25
    assert packet[-1]['message'] == records[-1]['message']
    assert original == before


def test_long_operator_instruction_is_whole_and_structured_read_still_recovers_exact_text(ws):
    seed(ws)
    huge = feedback_body()*30
    small = feedback_body()
    ws.store.set('feedback',[{'id':'large','message':huge}, {'id':'recent','message':small}])
    from report_agent.task_context import exact_task_context
    packet = compact_context(exact_task_context(ws,'coordinator'))['operator_feedback']
    assert packet[0] == {'id': 'large', 'message': huge}
    assert packet[1]['message'] == small
    pieces=[]; offset=0
    while True:
        page=read_state(ws,'coordinator',['operator_feedback',0,'message'],offset,characters=6000)
        pieces.append(page['value'])
        if page['next_offset'] is None: break
        offset=page['next_offset']
    assert ''.join(pieces) == huge


@pytest.mark.parametrize('body',['short', '', 'line1\nline2\n'+'中'*750, '\\"\n'*1500])
def test_exact_text_and_origin_no_rewrite(body):
    record={'id':'feedback','origin':'operator','message':body}
    assert compact_context({'goal':'g','operator_feedback':[record]})['operator_feedback'] == [record]
