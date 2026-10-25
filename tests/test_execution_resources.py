"""Live host observations, not tests of autonomous task planning."""
import asyncio
import pytest
from report_agent import request_budget as module
from report_agent.request_budget import RequestBudget, request_budget, current_budget_observation
from report_agent.task_context import exact_task_context
from test_task_supervision import ws
from test_hierarchical_content import seed


def test_observation_is_current_shared_and_restored_without_authorizing_calls():
    budget=RequestBudget(3)
    assert current_budget_observation() is None
    with request_budget(budget):
        assert current_budget_observation()['remaining_http_attempts']==3
        budget.reserve()
        async def independent_tool():
            budget.reserve()
            return current_budget_observation()
        observed=asyncio.run(independent_tool())
        assert observed['reserved_http_attempts']==2
        assert observed['remaining_http_attempts']==1
        assert observed['remaining_seconds'] is None
        observed['remaining_http_attempts']=99
        assert current_budget_observation()['remaining_http_attempts']==1
        with request_budget(RequestBudget(1)):
            assert current_budget_observation()['maximum_http_attempts']==1
        assert current_budget_observation()['maximum_http_attempts']==3
    assert current_budget_observation() is None


def test_deadline_is_host_observation_not_new_reservation_rule(monkeypatch):
    monkeypatch.setattr(module,'monotonic',lambda:100.0)
    budget=RequestBudget(2,deadline_monotonic=150.0)
    assert budget.snapshot()['remaining_seconds']==50.0
    monkeypatch.setattr(module,'monotonic',lambda:160.0)
    assert budget.snapshot()['remaining_seconds']==0.0
    # Expired time is enforced by the existing host, not a second admission policy.
    budget.reserve()
    assert budget.count==1


@pytest.mark.parametrize('value',[True,'150',float('nan'),float('inf')])
def test_invalid_host_deadline_is_rejected(value):
    with pytest.raises(ValueError,match='FINITE_HOST_DEADLINE_REQUIRED'):
        RequestBudget(2,deadline_monotonic=value)


def test_exact_task_context_does_not_infer_resources_from_manifest_or_history(ws):
    seed(ws)
    assert 'execution_resources' not in exact_task_context(ws,'coordinator')
    budget=RequestBudget(4)
    with request_budget(budget):
        before=exact_task_context(ws,'coordinator')
        budget.reserve()
        after=exact_task_context(ws,'coordinator')
        assert before['execution_resources']['remaining_http_attempts']==4
        assert after['execution_resources']['remaining_http_attempts']==3
        assert before['state_digest']==after['state_digest']
    assert 'execution_resources' not in exact_task_context(ws,'coordinator')
