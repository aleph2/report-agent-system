"""Regress the user-selected high policy and precise observation errors."""
import os
import json

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.deep_models import configured_model
from report_agent.model_config import bind_role_services, load_mixed_services, role_generation, role_service
from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
from report_agent.deep_models import error_data
from report_agent.text_work import prepare_material
from langchain_core.tools import StructuredTool
from test_bounded_review import Model
from test_text_work import tools, writer_call
from test_deepseek_env_configuration import write_config
from test_hierarchical_content import seed, ws
from langchain_core.messages import HumanMessage


def test_host_failure_and_budget_refusals_are_distinct():
    enforce_host_admission(used_plus_held=10, limit=100, unknown=False, failed=False)
    with pytest.raises(RequestBudgetExceeded) as failure:
        enforce_host_admission(used_plus_held=10, limit=100, unknown=False, failed=True)
    assert error_data(failure.value)['message'] == 'HOST_TECHNICAL_FAILURE_PENDING'
    with pytest.raises(RequestBudgetExceeded) as budget:
        enforce_host_admission(used_plus_held=101, limit=100, unknown=False, failed=False)
    assert error_data(budget.value)['message'] == 'HOST_TOKEN_BUDGET_REACHED'
    with pytest.raises(RequestBudgetExceeded) as unknown:
        enforce_host_admission(used_plus_held=10, limit=100, unknown=True, failed=False)
    assert error_data(unknown.value)['message'] == 'HOST_TECHNICAL_FAILURE_PENDING'


def test_fresh_mixed_services_default_all_roles_to_high(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for key in ('REPORT_REASONING_EFFORT', 'REPORT_COORDINATOR_REASONING_EFFORT',
                'REPORT_REVIEWER_REASONING_EFFORT'):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path/'models.env'
    write_config(path)
    load_mixed_services(path)
    from report_agent.store import Store
    store = Store(tmp_path/'fresh')
    store.initialize({'goal':'Offline policy', 'sources':[{'id':'s','content':'fake','coverage':'complete'}]})
    assert os.environ['REPORT_REASONING_EFFORT'] == 'high'
    assert all(role_generation(store, role, *role_service(role)[:2])['reasoning_effort'] == 'high'
               for role in ('coordinator','writer','reviewer','layout','text_tool'))
    bind_role_services(store)
    assert all(v['reasoning_effort'] == 'high' for v in store.get('role_generation').values())
    store.event('deep_model_request', {'role':'coordinator'})
    assert role_generation(store, 'coordinator', *role_service('coordinator')[:2])['reasoning_effort'] == 'high'


@pytest.mark.asyncio
async def test_high_policy_applies_to_working_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for key in ('REPORT_REASONING_EFFORT', 'REPORT_COORDINATOR_REASONING_EFFORT',
                'REPORT_REVIEWER_REASONING_EFFORT'):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path/'models.env'
    write_config(path)
    load_mixed_services(path)
    from report_agent.store import Store
    from report_agent.working_summary import working_summary
    store=Store(tmp_path/'fresh-summary')
    store.initialize({'goal':'Offline summary policy', 'sources':[{'id':'s','content':'fake','coverage':'complete'}]})
    bind_role_services(store)
    model=configured_model(store, 'coordinator')
    summary=working_summary(model, store).model
    try:
        payload=summary._get_request_payload([HumanMessage('offline')])
        assert payload['reasoning_effort'] == 'high'
        assert payload['extra_body']['enable_thinking'] is True
    finally:
        await model.root_async_client.close()
        model.root_client.close()


@pytest.mark.asyncio
async def test_legacy_all_high_binding_keeps_non_thinking_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for key in ('REPORT_REASONING_EFFORT', 'REPORT_COORDINATOR_REASONING_EFFORT',
                'REPORT_REVIEWER_REASONING_EFFORT'):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path/'models.env'
    write_config(path)
    load_mixed_services(path)
    from report_agent.store import Store
    from report_agent.working_summary import working_summary
    store = Store(tmp_path/'legacy-summary')
    store.initialize({'goal':'Legacy policy', 'sources':[{'id':'s','content':'fake','coverage':'complete'}]})
    store.set('role_generation', {role: role_generation(store, role, *role_service(role)[:2])
              for role in ('coordinator', 'writer', 'reviewer', 'layout', 'text_tool')})
    bind_role_services(store)
    assert 'working_summary' not in store.get('role_generation')
    model = configured_model(store, 'coordinator')
    try:
        payload = working_summary(model, store).model._get_request_payload([HumanMessage('offline')])
        assert payload.get('reasoning_effort') is None
        assert payload['extra_body']['enable_thinking'] is False
    finally:
        await model.root_async_client.close()
        model.root_client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', [{'reasoning_effort': 'low'}, {'reasoning_effort': 'high'}])
async def test_incomplete_summary_policy_is_rejected(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    path = tmp_path/'models.env'
    write_config(path)
    load_mixed_services(path)
    from report_agent.store import Store
    from report_agent.working_summary import working_summary
    store = Store(tmp_path/'incomplete')
    store.initialize({'goal':'Offline policy', 'sources':[{'id':'s','content':'fake','coverage':'complete'}]})
    model = configured_model(store, 'coordinator')
    store.set('role_generation', {'working_summary': policy})
    try:
        with pytest.raises(RuntimeError, match='INVALID_WORKING_SUMMARY_GENERATION_POLICY'):
            working_summary(model, store)
    finally:
        await model.root_async_client.close()
        model.root_client.close()


@pytest.mark.asyncio
async def test_legacy_unbound_execution_is_not_silently_switched_to_high(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    for key in ('REPORT_REASONING_EFFORT', 'REPORT_COORDINATOR_REASONING_EFFORT',
                'REPORT_REVIEWER_REASONING_EFFORT'):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path/'models.env'
    write_config(path)
    monkeypatch.setenv('REPORT_REASONING_EFFORT', 'max')
    load_mixed_services(path)
    from report_agent.store import Store
    store = Store(tmp_path/'old')
    store.initialize({'goal':'Historical contract', 'sources':[{'id':'s','content':'fake','coverage':'complete'}]})
    old_model = configured_model(store, 'coordinator')
    try:
        assert old_model.reasoning_effort == 'max'
    finally:
        await old_model.root_async_client.close()
        old_model.root_client.close()
    store.event('deep_model_request', {'role':'coordinator'})
    monkeypatch.delenv('REPORT_REASONING_EFFORT')
    load_mixed_services(path)
    before = store.get('role_generation')
    with pytest.raises(RuntimeError, match='ROLE_GENERATION_HISTORY_REQUIRES_FRESH_PROJECT'):
        configured_model(store, 'coordinator')
    assert store.get('role_generation') == before


@pytest.mark.asyncio
async def test_observation_missing_and_foreign_owner_are_distinct(ws):
    seed(ws)
    with delegated_task(ws, 'coordinator', {'id':'writer', 'args':{'subagent_type':'writer','description':'Write'}}) as (_, actor):
        missing = 'a' * 64
        with pytest.raises(ActionRejected, match='TEXT_WORK_OBSERVATION_NOT_FOUND'):
            prepare_material(ws, [], [], observation_refs=[missing], actor=actor)
        foreign = 'b' * 64
        ws.store.set('tool_observation:' + foreign, {'owner':'someone-else', 'text':'private'})
        with pytest.raises(ActionForbidden, match='observation owner') as exc:
            prepare_material(ws, [], [], observation_refs=[foreign], actor=actor)
        assert 'private' not in str(exc.value)


@pytest.mark.asyncio
async def test_full_length_wrong_namespace_stops_at_registered_tool(ws):
    cs, _, _, _, _ = seed(ws)
    model = Model(json.dumps({}))
    with delegated_task(ws, 'coordinator', writer_call()):
        before = cs.list_objects('ContentNode')
        tool = StructuredTool.from_function(coroutine=tools(ws, 'writer', model)['process_report_content'])
        with pytest.raises(ActionRejected, match='TEXT_WORK_OBSERVATION_NOT_FOUND'):
            await tool.ainvoke({'operation_id':'wrong-namespace', 'objective':'Use observed source',
                'object_type':'ContentNode', 'observation_refs':['a' * 64]})
        assert not model.calls
        assert cs.list_objects('ContentNode') == before
