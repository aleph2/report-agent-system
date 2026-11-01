"""Preserve the installed native response envelope; no report/provider calls."""
import json

from langchain.agents.middleware.types import ExtendedModelResponse, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from report_agent.store import digest
from report_agent.task_context import TaskContext
from test_task_supervision import ws, offline
from test_deep_runtime import Driver
from test_selector_experiment_contract import SelectionDriver, configure


def wrapped(answer):
    command = Command(update={'messages': [HumanMessage(content='Native command note, not a user instruction.')],
        'files': {'/fixture.txt': {'content': ['Synthetic command output.']}}})
    inner = ModelResponse(result=[answer], structured_response={'fixture': 'preserve structured result'})
    return ExtendedModelResponse(model_response=inner, command=command)


async def test_task_context_preserves_extended_command_and_structured_result_when_persisting_frame(ws):
    history = [HumanMessage(content='Maintain the current synthetic task.')]
    request = ModelRequest(model=Driver()('coordinator'), tools=[], state={'messages': history},
        system_message=SystemMessage(content='Existing coordinator role.'), messages=history)
    answer = AIMessage(content='Offline business answer.')
    original = wrapped(answer)
    seen = []
    async def handler(changed):
        seen.append(changed)
        return original
    response = await TaskContext(ws, 'coordinator').awrap_model_call(request, handler)
    assert isinstance(response, ExtendedModelResponse)
    assert response.command is original.command
    assert response.command.update['messages'][0].additional_kwargs.get('report_model_command_message')
    assert response.model_response.structured_response == original.model_response.structured_response
    assert len(response.model_response.result) == 2
    frame, actual_answer = response.model_response.result
    assert isinstance(frame, HumanMessage) and frame.additional_kwargs.get('report_task_state_frame')
    assert json.loads(frame.text)['kind'] == 'full'
    assert actual_answer is answer
    assert original.model_response.result == [answer]
    assert len(seen) == 1 and seen[0].messages == history


async def test_native_selector_preserves_extended_command_and_binds_inner_ai_offer_without_execution(ws):
    from report_agent.tool_selection import NativeToolSelection
    configure(ws, 'on')
    def read_fixture_state():
        """Read synthetic state within this test request's permitted catalog."""
        raise AssertionError('Wrapping a model response must not execute or replay a tool')
    tool = StructuredTool.from_function(read_fixture_state)
    driver = SelectionDriver(selections={'coordinator': [['read_fixture_state']]})
    history = [HumanMessage(content='Select from the supplied permitted catalog.')]
    request = ModelRequest(model=driver('coordinator'), tools=[tool], state={'messages': history},
        system_message=SystemMessage(content='Existing coordinator role.'), messages=history)
    answer = AIMessage(content='', tool_calls=[{'name': 'read_fixture_state', 'args': {},
        'id': 'wrapped-business-decision', 'type': 'tool_call'}])
    original = wrapped(answer)
    seen = []
    async def handler(changed):
        seen.append(changed)
        return original
    response = await NativeToolSelection(ws, 'coordinator').awrap_model_call(request, handler)
    assert isinstance(response, ExtendedModelResponse)
    assert response.command is original.command
    assert response.command.update['messages'][0].additional_kwargs.get('report_model_command_message')
    assert response.model_response.structured_response == original.model_response.structured_response
    assert response.model_response.result == [answer]
    assert len(seen) == len(driver.selections) == 1
    assert seen[0].messages == history and [t.name for t in seen[0].tools] == ['read_fixture_state']
    receipt = ws.store.get(answer.additional_kwargs['report_tool_selection_offer'])
    assert receipt['names'] == ['read_fixture_state']
    assert receipt['calls_digest'] == digest(answer.tool_calls)
    assert receipt['actor_id'] == 'content:coordinator'
    assert receipt['task_id'] == 'content-task:coordinator'
    assert driver.calls == []


async def test_program_command_human_is_preserved_but_not_promoted_to_direct_root_instruction(ws):
    from langgraph.graph.message import add_messages
    from support.task_state_contract import current_task
    original_user = 'The actual direct root instruction must remain authoritative.'
    history = [HumanMessage(content=original_user)]
    middleware = TaskContext(ws, 'coordinator')
    state = {'messages': history}
    update = await middleware.abefore_model(state, None)
    if update:
        state.update({key: value for key, value in update.items() if key != 'messages'})
        state['messages'] = add_messages(history, update.get('messages', []))
    response = wrapped(AIMessage(content='Program produced an answer and a native Command.'))
    note = response.command.update['messages'][0]
    note_text = note.text
    files = {'/fixture.txt': {'content': ['Synthetic command output.']}}
    request = ModelRequest(model=Driver()('coordinator'), tools=[], state=state,
        system_message=SystemMessage(content='Existing role.'), messages=state['messages'])
    async def first_handler(changed):
        return response
    first = await middleware.awrap_model_call(request, first_handler)
    assert isinstance(first, ExtendedModelResponse) and first.command is response.command
    assert first.command.update['messages'][0] is note
    assert first.command.update['messages'][0].text == note_text
    assert first.command.update['files'] == files
    history = add_messages(state['messages'], first.model_response.result)
    history = add_messages(history, first.command.update['messages'])
    state['messages'] = history
    update = await TaskContext(ws, 'coordinator').abefore_model(state, None)
    if update:
        state.update({key: value for key, value in update.items() if key != 'messages'})
        state['messages'] = add_messages(history, update.get('messages', []))
    seen = []
    async def next_handler(changed):
        seen.append(changed)
        return ModelResponse(result=[AIMessage(content='No tool or user replay.')])
    await TaskContext(ws, 'coordinator').awrap_model_call(request.override(
        state=state, messages=state['messages']), next_handler)
    assert len(seen) == 1
    assert current_task(seen[0])['current_user_task'] == original_user
    assert any(isinstance(m, HumanMessage) and m.text == note_text for m in seen[0].messages)
