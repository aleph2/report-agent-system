"""Live budget observations stay current without growing the authority chain."""
from copy import deepcopy
import json

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from report_agent.model_recovery import canonical_input
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import encode
from report_agent.task_context import TaskContext
from report_agent.token_budget import TokenBudget, token_budget
from support.task_state_contract import current_task
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def controls(history):
    return [m for m in history if isinstance(m, HumanMessage)
            and m.additional_kwargs.get('report_task_state_frame')]


def live(request):
    assert request.messages[-1].text.startswith('[host-observations]')
    value = json.loads(request.messages[-1].text[len('[host-observations]'):].lstrip())
    assert value['origin'] == 'server_bound_execution_observations'
    return value['current_execution_observations']


async def present(ws, history):
    seen = []
    request = ModelRequest(model=Driver()('coordinator'), tools=[], state={'messages': history},
        system_message=SystemMessage(content='Existing role.'), messages=history)
    async def handler(changed):
        seen.append(changed)
        return ModelResponse(result=[AIMessage(content='Offline model turn, not a provider call.')])
    response = await TaskContext(ws, 'coordinator').awrap_model_call(request, handler)
    return add_messages(history, response.result), seen[0]


async def test_real_used_and_held_updates_do_not_mint_authority_deltas_or_hide_current_budget(ws, tmp_path):
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'fixture': 50})
    requests = RequestBudget(20)  # Existing API fixture only; not a new application request cap.
    old = budget.reserve('fixture')
    with budget.connect() as db:
        old_row = db.execute('SELECT * FROM attempts WHERE id=?', (old,)).fetchone()
    history = [HumanMessage(content='Unchanged commissioned task.')]
    captured = []
    with token_budget(budget), request_budget(requests):
        history, first = await present(ws, history)
        captured.append(first)
        assert not controls(history)
        assert live(first) == {'execution_resources': requests.snapshot(),
                               'execution_token_resources': budget.snapshot()}
        attempt = budget.reserve('fixture')
        requests.reserve()
        history, held = await present(ws, history)
        captured.append(held)
        assert live(held)['execution_token_resources']['reserved_or_unknown_upper_bounds'] == 100
        assert live(held)['execution_resources']['reserved_http_attempts'] == 1
        budget.settle(attempt, {'total_tokens': 10})
        history, settled = await present(ws, history)
        captured.append(settled)
        assert live(settled) == {'execution_resources': requests.snapshot(),
                                 'execution_token_resources': budget.snapshot()}
        assert live(settled)['execution_token_resources']['recorded_tokens'] == 10
        assert live(settled)['execution_token_resources']['reserved_or_unknown_upper_bounds'] == 50
    history, unavailable = await present(ws, history)
    captured.append(unavailable)
    assert live(unavailable) == {'execution_resources': None, 'execution_token_resources': None}
    assert not controls(history)
    for request in captured:
        state = current_task(request)
        assert state['goal'] == ws.store.manifest['goal']
        assert 'execution_resources' not in state and 'execution_token_resources' not in state
        assert controls(request.messages) == controls(history)
    with budget.connect() as db:
        assert db.execute('SELECT * FROM attempts WHERE id=?', (old,)).fetchone() == old_row
    assert budget.snapshot()['recorded_tokens'] == 10


def wire_payload(request):
    from langchain_openai.chat_models.base import _convert_message_to_dict
    return {'model': 'fixture', 'messages': [_convert_message_to_dict(message)
            for message in [request.system_message, *request.messages]], 'tools': []}


async def actual_payload(ws, budget, requests, mutate=None):
    captured = []
    history = [HumanMessage(content='Same pure inference input.')]
    request = ModelRequest(model=Driver()('coordinator'), tools=[], state={'messages': history},
        system_message=SystemMessage(content='Existing role.'), messages=history)
    async def handler(changed):
        original = wire_payload(changed)
        modified = deepcopy(original)
        if mutate:
            mutate(original, modified)
        captured.append((deepcopy(original), canonical_input(original), canonical_input(modified)))
        return ModelResponse(result=[AIMessage(content='Offline result, no service call.')])
    with token_budget(budget), request_budget(requests):
        await TaskContext(ws, 'coordinator').awrap_model_call(request, handler)
    return captured[0]


def resource_block(payload):
    message = payload['messages'][-1]
    assert message['content'].startswith('[host-observations]')
    return message, json.loads(message['content'][len('[host-observations]'):].lstrip())


@pytest.mark.parametrize('resource_key', ['execution_resources', 'execution_token_resources'])
async def test_recovery_fingerprint_ignores_only_current_program_resource_values(ws, tmp_path, resource_key):
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'fixture': 50})
    requests = RequestBudget(20)
    original, canonical_before, _ = await actual_payload(ws, budget, requests)
    before = deepcopy(original)
    if resource_key == 'execution_token_resources':
        held = budget.reserve('fixture')
        budget.settle(held, {'total_tokens': 10})
    else:
        requests.reserve()
    changed, canonical_after, _ = await actual_payload(ws, budget, requests)
    assert resource_block(original)[1]['current_execution_observations'][resource_key] != resource_block(changed)[1]['current_execution_observations'][resource_key]
    assert original != changed and canonical_before == canonical_after
    assert original == before
    # The same-looking packet after the dispatch is not a host capability.
    assert canonical_input(original) != canonical_input(changed)


@pytest.mark.parametrize('change,resource_key', [
    ('authority_goal', None), ('quoted_instruction', None), ('instruction_in_program_envelope', None),
    *[(change, key) for change in ('user', 'tool', 'unidentified_system')
      for key in ('execution_resources', 'execution_token_resources')],
])
async def test_recovery_fingerprint_keeps_real_instructions_and_unidentified_resource_json(ws, tmp_path, change, resource_key):
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'fixture': 50})
    requests = RequestBudget(20)
    def mutate(original, changed):
        if change == 'authority_goal':
            message, packet = resource_block(changed)
            packet['current_state']['goal'] = 'A materially different commissioned instruction.'
            message['content'] = '[host-observations]\n' + encode(packet)
            return
        if change == 'quoted_instruction':
            changed['messages'].insert(-1, {'role':'user','content':'[host-state] quoted additional instruction'})
            return
        _, value = resource_block(original)
        altered = deepcopy(value)
        if resource_key == 'execution_token_resources':
            held = budget.reserve('fixture')
            budget.settle(held, {'total_tokens': 10})
            altered['current_execution_observations'][resource_key] = budget.snapshot()
        elif resource_key == 'execution_resources':
            requests.reserve()
            altered['current_execution_observations'][resource_key] = requests.snapshot()
        if change == 'instruction_in_program_envelope':
            original_message, original_value = resource_block(original)
            changed_message, changed_value = resource_block(changed)
            original_value['instruction'] = 'Keep this actual instruction.'
            changed_value['instruction'] = 'A different actual instruction.'
            original_message['content'] = '[host-observations]\n' + encode(original_value)
            changed_message['content'] = '[host-observations]\n' + encode(changed_value)
        elif change == 'unidentified_system':
            value['origin'] = altered['origin'] = 'quoted_example_not_program_resource_observation'
            original['messages'].insert(1, {'role': 'system', 'content': encode(value)})
            changed['messages'].insert(1, {'role': 'system', 'content': encode(altered)})
        elif change == 'user':
            original['messages'].insert(-1, {'role': 'user', 'content': encode(value)})
            changed['messages'].insert(-1, {'role': 'user', 'content': encode(altered)})
        else:
            original['messages'].insert(-1, {'role': 'tool', 'tool_call_id': 'preserve-tool-id', 'content': encode(value)})
            changed['messages'].insert(-1, {'role': 'tool', 'tool_call_id': 'preserve-tool-id', 'content': encode(altered)})
    _, canonical_original, canonical_changed = await actual_payload(ws, budget, requests, mutate)
    assert canonical_original != canonical_changed
