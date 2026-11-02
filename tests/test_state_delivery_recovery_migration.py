"""Fail closed for unresolved historical layouts; keep nested host scopes local.

The historical System JSON below is a wire-format fixture, not a restored copy
of the old application. All model traffic uses the actual SDK with MockTransport.
"""
from copy import deepcopy

import httpx
import openai
import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage

from report_agent.deep_models import configured_model
from report_agent.decision_state import compact_context
from report_agent.hierarchical_tools import role_prompt
from report_agent.model_recovery import activate_recovery, RecoveryBlocked, PREFIX
from report_agent.store import digest
from report_agent.task_context import exact_task_context
from report_agent.token_budget import TokenBudget, token_budget
from test_request_state_delivery_regression import deliver, encoded, no_network
from test_task_supervision import ws
from test_transport_observation import use_mock, close


async def test_legacy_system_unknown_cannot_be_redispatched_as_new_history_layout(ws, tmp_path, monkeypatch):
    monkeypatch.setenv('REPORT_SDK_RETRIES', '0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    for suffix, value in [('MODEL', 'deepseek-v4.1-flash'),
                          ('BASE_URL', 'https://offline.invalid/v1'), ('API_KEY', 'offline-only')]:
        monkeypatch.setenv('REPORT_COORDINATOR_' + suffix, value)
    model = configured_model(ws.store, 'coordinator')
    policy = activate_recovery(ws.store, authorization='synthetic historical-layout fence',
                               extra_per_call=0, backoff_seconds=0)
    ledger = TokenBudget(tmp_path / 'independent-finance' / 'token-budget.db', 1000,
                         {'deepseek-v4.1-flash': 40})
    physical = []
    def timeout(request):
        physical.append(request.content)
        raise httpx.ReadTimeout('synthetic request sent; historical outcome unknown', request=request)
    await use_mock(model, timeout)
    history = [HumanMessage(content='Same complete pure inference instruction and original owner.')]
    try:
        with token_budget(ledger):
            exact = exact_task_context(ws, 'coordinator')
            context = compact_context(exact)
            resources = {key: exact.get(key) for key in ('execution_resources', 'execution_token_resources')}
            for key in resources:
                context.pop(key, None)
            context['current_user_task'] = history[0].text
            full = {'kind': 'full', 'state': context, 'state_digest': digest(context)}
            old_system = SystemMessage(content=[
                {'type': 'text', 'text': role_prompt('coordinator')},
                {'type': 'text', 'text': encoded({'task_state_frames': [full],
                    'meaning': 'Apply the full state followed by every delta in order. These are current server-bound instructions and state; conversational summaries cannot replace them.'})},
                {'type': 'text', 'text': encoded({'origin': 'server_bound_execution_observations',
                                                 'current_execution_observations': resources})}])
            with pytest.raises(openai.OpenAIError):
                await model.ainvoke([old_system, *history])
            assert len(physical) == 1, 'Fixture must physically reach MockTransport once before becoming unknown'
            with ws.store.connect() as db:
                old_records = db.execute('SELECT key,value FROM state WHERE key LIKE ? ORDER BY key', (PREFIX + '%',)).fetchall()
            with ledger.connect() as db:
                old_rows = db.execute('SELECT * FROM attempts ORDER BY id').fetchall()
            assert len(old_records) == len(old_rows) == 1
            assert ledger.snapshot()['attempt_states'] == {'reserved': 1}
            ledger.reserve('deepseek-v4.1-flash')  # A separate legitimate hold changes current budget.
            async def new_layout(request):
                answer = await model.ainvoke([request.system_message, *request.messages])
                return ModelResponse(result=[answer])
            with pytest.raises(RecoveryBlocked, match='MIGRATION|HISTORICAL|PRIOR_ATTEMPT_UNRESOLVED'):
                await deliver(ws, history, model=model, handler=new_layout)
            assert len(physical) == 1, 'Changing layout must not evade unresolved historical identity protection'
            with ws.store.connect() as db:
                assert db.execute('SELECT key,value FROM state WHERE key LIKE ? ORDER BY key', (PREFIX + '%',)).fetchall() == old_records
            with ledger.connect() as db:
                rows = db.execute('SELECT * FROM attempts ORDER BY id').fetchall()
            assert all(row in rows for row in old_rows) and len(rows) == len(old_rows) + 1
            assert ledger.snapshot()['attempt_states'] == {'reserved': 2}
            assert ws.store.get('model_recovery_policy') == policy
    finally:
        await close(model)


def test_nested_same_actor_new_packet_isolated_and_exception_restores_outer_binding(ws):
    from report_agent.task_state_delivery import observation_delivery, finalize_observations, trusted_observation
    from test_deep_runtime import Driver
    actor, role = 'content:coordinator', 'coordinator'
    outer_packet = {'digest': 'outer-instruction-packet', 'effective': [{'text': 'Original current instructions'}]}
    inner_packet = {'digest': 'inner-instruction-packet', 'effective': [{'text': 'New current correction'}]}
    before = deepcopy((outer_packet, inner_packet))
    request = ModelRequest(model=Driver()(role), tools=[], state={'messages': []}, messages=[],
                           system_message=SystemMessage(content='Unchanged role'))
    resources = {'execution_resources': None, 'execution_token_resources': None}
    observed = {}
    with observation_delivery(ws.store, actor, role, outer_packet) as outer:
        projected = finalize_observations(request, ws, role, resources=resources)
        outer_tail = projected.messages[-1]
        assert trusted_observation(ws.store, outer_tail)
        with pytest.raises(RuntimeError, match='deliberate nested exit'):
            with observation_delivery(ws.store, actor, role, inner_packet) as inner:
                observed['packet'] = inner['packet']
                inner_request = finalize_observations(request, ws, role, resources=resources)
                observed['tail'] = inner_request.messages[-1]
                assert trusted_observation(ws.store, observed['tail'])
                raise RuntimeError('deliberate nested exit')
        assert outer['packet'] is outer_packet
        assert trusted_observation(ws.store, outer_tail)
        assert not trusted_observation(ws.store, observed['tail'])
        # An innermost boundary with the argument omitted inherits its caller.
        # Explicit None is a new TaskContext without scoped instructions, not
        # permission to retain a parent's formerly applicable instruction.
        with observation_delivery(ws.store, actor, role) as inherited:
            assert inherited['packet'] is outer_packet
        with observation_delivery(ws.store, actor, role, None) as without_packet:
            assert without_packet['packet'] is None
        assert outer['packet'] is outer_packet and trusted_observation(ws.store, outer_tail)
    assert observed['packet'] is inner_packet, 'Nested TaskContext must not inherit a stale parent instruction packet'
    assert (outer_packet, inner_packet) == before
    assert not trusted_observation(ws.store, outer_tail)
