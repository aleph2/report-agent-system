"""Live budget observations stay current without growing the authority chain."""
from copy import deepcopy
import json

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from report_agent.model_recovery import canonical_input
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import digest, encode
from report_agent.task_context import TaskContext
from report_agent.token_budget import TokenBudget, token_budget
from support.task_state_contract import current_task
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def controls(history):
    return [m for m in history if isinstance(m, HumanMessage)
            and m.additional_kwargs.get('report_task_state_frame')]


def live(request):
    values = []
    for block in request.system_message.content_blocks:
        if block.get('type') == 'text':
            try:
                values.append(json.loads(block['text']))
            except json.JSONDecodeError:
                pass
    matches = [v for v in values if isinstance(v, dict)
               and v.get('origin') == 'server_bound_execution_observations']
    assert len(matches) == 1, 'Current live resources need one explicit program System contribution'
    return matches[0]['current_execution_observations']


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
        assert len(controls(history)) == 1
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
    assert len(controls(history)) == 1
    for request in captured:
        state = current_task(request)
        assert state['goal'] == ws.store.manifest['goal']
        assert 'execution_resources' not in state and 'execution_token_resources' not in state
        assert not controls(request.messages)
    with budget.connect() as db:
        assert db.execute('SELECT * FROM attempts WHERE id=?', (old,)).fetchone() == old_row
    assert budget.snapshot()['recorded_tokens'] == 10


async def actual_payload(ws, tmp_path):
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'fixture': 50})
    requests = RequestBudget(20)
    with token_budget(budget), request_budget(requests):
        _, request = await present(ws, [HumanMessage(content='Same pure inference input.')])
    live(request)  # The normalization fixture must use the actual emitted envelope.
    return {'model': 'fixture', 'messages': [
        {'role': 'system', 'content': deepcopy(request.system_message.content_blocks)},
        {'role': 'user', 'content': 'Same pure inference input.'}], 'tools': []}, budget, requests


def resource_block(payload):
    for block in payload['messages'][0]['content']:
        try:
            value = json.loads(block.get('text', ''))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get('origin') == 'server_bound_execution_observations':
            return block, value
    raise AssertionError('Missing known program live-resource envelope')


@pytest.mark.parametrize('resource_key', ['execution_resources', 'execution_token_resources'])
async def test_recovery_fingerprint_ignores_only_current_program_resource_values(ws, tmp_path, resource_key):
    original, budget, requests = await actual_payload(ws, tmp_path)
    before = deepcopy(original)
    changed = deepcopy(original)
    block, value = resource_block(changed)
    if resource_key == 'execution_token_resources':
        held = budget.reserve('fixture')
        budget.settle(held, {'total_tokens': 10})
        current = budget.snapshot()
    else:
        requests.reserve()
        current = requests.snapshot()
    value['current_execution_observations'][resource_key] = current
    block['text'] = encode(value)
    assert original != changed
    assert canonical_input(original) == canonical_input(changed)
    assert original == before


@pytest.mark.parametrize('change,resource_key', [
    ('authority_goal', None), ('authority_delta', None), ('instruction_in_program_envelope', None),
    *[(change, key) for change in ('user', 'tool', 'unidentified_system')
      for key in ('execution_resources', 'execution_token_resources')],
])
async def test_recovery_fingerprint_keeps_real_instructions_and_unidentified_resource_json(ws, tmp_path, change, resource_key):
    original, budget, requests = await actual_payload(ws, tmp_path)
    changed = deepcopy(original)
    if change in {'authority_goal', 'authority_delta'}:
        block = next(b for b in changed['messages'][0]['content'] if 'task_state_frames' in b.get('text', ''))
        value = json.loads(block['text'])
        full = value['task_state_frames'][0]
        altered = {**full['state'], 'goal': 'A materially different commissioned instruction.'}
        if change == 'authority_goal':
            full.update(state=altered, state_digest=digest(altered))
        else:
            value['task_state_frames'].append({'kind': 'delta', 'base_digest': full['state_digest'],
                'changes': {'goal': altered['goal']}, 'removed_paths': [], 'state_digest': digest(altered)})
        block['text'] = encode(value)
    else:
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
            before_block, before_value = resource_block(original)
            after_block, after_value = resource_block(changed)
            before_value['instruction'] = 'Keep this actual instruction.'
            after_value['instruction'] = 'A different actual instruction.'
            before_block['text'], after_block['text'] = encode(before_value), encode(after_value)
        elif change == 'unidentified_system':
            value['origin'] = altered['origin'] = 'quoted_example_not_program_resource_observation'
            original['messages'][0]['content'].append({'type': 'text', 'text': encode(value)})
            changed['messages'][0]['content'].append({'type': 'text', 'text': encode(altered)})
        elif change == 'user':
            original['messages'].append({'role': 'user', 'content': encode(value)})
            changed['messages'].append({'role': 'user', 'content': encode(altered)})
        else:
            original['messages'].append({'role': 'tool', 'tool_call_id': 'preserve-tool-id', 'content': encode(value)})
            changed['messages'].append({'role': 'tool', 'tool_call_id': 'preserve-tool-id', 'content': encode(altered)})
    assert canonical_input(original) != canonical_input(changed)
