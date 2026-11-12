"""Default host owns its clients; injected factories retain caller ownership."""
import asyncio
from types import SimpleNamespace

import pytest

from report_agent import deep_runtime
from test_task_supervision import ws


@pytest.mark.parametrize('ending', ['normal', 'configuration_failure', 'build_failure', 'body_failure', 'cancelled'])
async def test_default_factory_caches_role_and_closes_shared_clients_once(ws, monkeypatch, ending):
    closed, built = [], []
    class SyncClient:
        def close(self):
            closed.append('sync')
    class AsyncClient:
        async def close(self):
            closed.append('async')
        aclose = close
    shared_sync, shared_async = SyncClient(), AsyncClient()
    def configure(store, role):
        from report_agent.deep_models import _CLIENT_OWNER
        client_owner = _CLIENT_OWNER.get()
        built.append(role)
        if ending == 'configuration_failure' and role == 'reviewer':
            raise ValueError('synthetic configuration failure after first owned model')
        client_owner(shared_sync, False)
        client_owner(shared_async, True)
        return SimpleNamespace(root_client=shared_sync, root_async_client=shared_async)
    def build(workspace, factory, *args, **kwargs):
        co = factory('coordinator')
        assert factory('coordinator') is co
        factory('reviewer')
        if ending == 'build_failure':
            raise ValueError('synthetic build failure')
        return 'synthetic graph'
    monkeypatch.setattr(deep_runtime, 'configured_model', configure)
    monkeypatch.setattr(deep_runtime, 'build_agent', build)
    async def invoke():
        async with deep_runtime.project_agent(ws) as graph:
            assert graph == 'synthetic graph'
            assert not closed
            if ending == 'body_failure':
                raise ValueError('synthetic body failure')
            if ending == 'cancelled':
                raise asyncio.CancelledError()
    if ending == 'normal':
        await invoke()
    else:
        with pytest.raises(asyncio.CancelledError if ending == 'cancelled' else ValueError):
            await invoke()
    assert built == ['coordinator', 'reviewer']
    assert sorted(closed) == ['async', 'sync']
    from report_agent.deep_models import _CLIENT_OWNER
    assert _CLIENT_OWNER.get() is None


async def test_injected_factory_clients_are_not_closed_by_host(ws, monkeypatch):
    class CallerModel:
        @property
        def root_client(self):
            pytest.fail('host must not take ownership of injected models')
    model = CallerModel()
    monkeypatch.setattr(deep_runtime, 'build_agent', lambda workspace, factory, *a, **kw: factory('reviewer'))
    async with deep_runtime.project_agent(ws, lambda role: model) as graph:
        assert graph is model


@pytest.mark.parametrize('provider', ['glm', 'official-deepseek'])
@pytest.mark.parametrize('failure', ['sync-client', 'model'])
async def test_default_owner_closes_raw_clients_if_model_construction_fails(ws, monkeypatch, provider, failure):
    from report_agent import deep_models
    closed = []
    class AsyncClient:
        async def aclose(self):
            closed.append('async')
    class SyncClient:
        def close(self):
            closed.append('sync')
    service = ('glm-5.3','https://fixture.invalid/v1','fake') if provider == 'glm' else (
        'deepseek-v4.1-flash-1017','https://api.deepseek.com','fake')
    monkeypatch.setattr('report_agent.model_config.role_service', lambda role: service)
    monkeypatch.setattr('report_agent.model_config.role_generation', lambda *args: {})
    monkeypatch.setattr('report_agent.input_capacity.profile_for_service', lambda *args: None)
    monkeypatch.setattr(deep_models, 'model_async_client', lambda *args, **kwargs: AsyncClient())
    def sync_client(*args, **kwargs):
        if failure == 'sync-client':
            raise ValueError('synthetic constructor failure')
        return SyncClient()
    def model(*args, **kwargs):
        raise ValueError('synthetic constructor failure')
    monkeypatch.setattr(deep_models, 'model_sync_client', sync_client)
    monkeypatch.setattr(deep_models, 'GLMChatOpenAI', model)
    monkeypatch.setattr(deep_runtime, 'build_agent', lambda workspace, factory, *a, **kw: factory('coordinator'))
    with pytest.raises(ValueError, match='synthetic constructor failure'):
        async with deep_runtime.project_agent(ws):
            pytest.fail('construction must not produce a graph')
    assert sorted(closed) == (['async'] if failure == 'sync-client' else ['async','sync'])
    assert deep_models._CLIENT_OWNER.get() is None


def test_client_owner_scope_restores_nested_callers():
    from report_agent.deep_models import _CLIENT_OWNER, model_client_ownership
    outer, inner = object(), object()
    with model_client_ownership(outer):
        with pytest.raises(ValueError):
            with model_client_ownership(inner):
                assert _CLIENT_OWNER.get() is inner
                raise ValueError('synthetic nested constructor failure')
        assert _CLIENT_OWNER.get() is outer
    assert _CLIENT_OWNER.get() is None


def test_direct_two_argument_factory_does_not_inherit_exited_owner(ws, monkeypatch):
    from report_agent import deep_models
    owned = []
    monkeypatch.setattr('report_agent.model_config.role_service', lambda role: ('glm-5.3','https://fixture.invalid/v1','fake'))
    monkeypatch.setattr('report_agent.model_config.role_generation', lambda *args: {})
    monkeypatch.setattr('report_agent.input_capacity.profile_for_service', lambda *args: None)
    monkeypatch.setattr(deep_models, 'model_async_client', lambda *args, **kwargs: object())
    monkeypatch.setattr(deep_models, 'model_sync_client', lambda *args, **kwargs: object())
    monkeypatch.setattr(deep_models, 'GLMChatOpenAI', lambda **kwargs: kwargs)
    with deep_models.model_client_ownership(lambda client, asynchronous: owned.append(client)):
        deep_models.configured_model(ws.store, 'coordinator')
    assert len(owned) == 2
    deep_models.configured_model(ws.store, 'reviewer')
    assert len(owned) == 2
