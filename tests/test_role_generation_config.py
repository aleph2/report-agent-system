"""Role generation opt-in uses real serializers and offline transports."""
import json
import os
import sqlite3
import asyncio

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent.model_config import load_mixed_services, bind_role_services
from report_agent.deep_models import configured_model
from report_agent.store import Store
from test_deepseek_env_configuration import write_config
from test_prompt_native_sdk_inputs import completion


SETTING = 'REPORT_COORDINATOR_REASONING_EFFORT'


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    # Preserve these historical max-specific compatibility checks explicitly.
    monkeypatch.setenv('REPORT_REASONING_EFFORT', 'max')
    monkeypatch.delenv(SETTING, raising=False)
    path = tmp_path / 'model.env'
    write_config(path)
    load_mixed_services(path)
    store = Store(tmp_path / 'case')
    store.initialize({'goal': 'Offline generation contract', 'sources': [
        {'id': 's', 'content': 'Synthetic source.', 'coverage': 'complete'}]})
    return store, path


def close_sync(model):
    model.http_client.close()


async def test_explicit_co_high_reaches_wire_without_changing_other_roles(configured):
    store, path = configured
    path.write_text(path.read_text() + SETTING + '=high\n')
    load_mixed_services(path)
    bind_role_services(store)
    sent = {}
    for role in ('coordinator', 'reviewer', 'text_tool', 'writer', 'layout'):
        model = configured_model(store, role)
        async def receive(request, role=role):
            sent[role] = json.loads(request.content)
            return completion(request)
        model.http_async_client._transport = httpx.MockTransport(receive)
        model.http_async_client._mounts.clear()
        try:
            await model.ainvoke([HumanMessage('Offline contract check.')])
            assert model.root_client.max_retries == model.root_async_client.max_retries == 0
        finally:
            await model.http_async_client.aclose()
            close_sync(model)
    assert sent['coordinator']['reasoning_effort'] == 'high'
    assert sent['reviewer']['reasoning_effort'] == sent['text_tool']['reasoning_effort'] == 'max'
    assert sent['writer']['reasoning_effort'] == sent['layout']['reasoning_effort'] == 'high'
    for role in ('coordinator', 'reviewer', 'text_tool'):
        assert sent[role]['max_tokens'] == 65536 and sent[role]['enable_thinking'] is True
        assert sent[role]['stream'] is False
    assert sent['writer']['max_completion_tokens'] == 65536
    assert os.environ['REPORT_REASONING_EFFORT'] == 'max'
    assert store.get('role_model_services')['coordinator'].keys() == {'model', 'base_url'}
    assert store.get('role_generation')['coordinator']['reasoning_effort'] == 'high'


def test_invalid_file_effort_does_not_partially_change_environment(configured):
    store, path = configured
    path.write_text(path.read_text() + SETTING + '=maximum\n')
    before = dict(os.environ)
    with pytest.raises(ValueError, match='REASONING_EFFORT_INVALID'):
        load_mixed_services(path)
    assert dict(os.environ) == before
    assert store.get('role_generation') is None


@pytest.mark.parametrize('history', ['model-event', 'checkpoint-row'])
def test_legacy_with_execution_rejects_new_override_before_binding(configured, monkeypatch, history):
    store, _ = configured
    bind_role_services(store)
    if history == 'model-event':
        store.event('deep_model_request', {'role': 'coordinator'})
    else:
        with sqlite3.connect(store.root / 'checkpoints.db') as db:
            db.execute('CREATE TABLE checkpoints (id TEXT)')
            db.execute("INSERT INTO checkpoints VALUES ('old-execution')")
    before = store.get('role_model_services')
    monkeypatch.setenv(SETTING, 'high')
    with pytest.raises(RuntimeError, match='GENERATION.*FRESH'):
        bind_role_services(store)
    assert store.get('role_model_services') == before
    assert store.get('role_generation') is None


def test_prebound_services_and_empty_checkpoint_database_are_still_fresh(configured, monkeypatch):
    store, _ = configured
    bind_role_services(store)
    with sqlite3.connect(store.root / 'checkpoints.db') as db:
        db.execute('CREATE TABLE checkpoints (id TEXT)')
    monkeypatch.setenv(SETTING, 'high')
    bind_role_services(store)
    assert store.get('role_generation')['coordinator']['reasoning_effort'] == 'high'


async def test_bound_generation_rejects_switch_but_existing_instance_remains_fixed(configured, monkeypatch):
    store, _ = configured
    monkeypatch.setenv(SETTING, 'high')
    bind_role_services(store)
    model = configured_model(store, 'coordinator')
    previous = store.get('role_generation')
    try:
        monkeypatch.setenv(SETTING, 'low')
        with pytest.raises(RuntimeError, match='GENERATION.*FRESH'):
            bind_role_services(store)
        with pytest.raises(RuntimeError, match='GENERATION.*FRESH'):
            configured_model(store, 'coordinator')
        assert model._get_request_payload([HumanMessage('Still fixed.')])['reasoning_effort'] == 'high'
        assert store.get('role_generation') == previous
    finally:
        await model.http_async_client.aclose()
        close_sync(model)


async def test_legacy_without_override_keeps_original_unbound_generation(configured):
    store, _ = configured
    store.event('deep_model_request', {'role': 'coordinator'})
    bind_role_services(store)
    model = configured_model(store, 'coordinator')
    try:
        assert model._get_request_payload([HumanMessage('Legacy.')])['reasoning_effort'] == 'max'
        assert store.get('role_generation') is None
    finally:
        await model.http_async_client.aclose()
        close_sync(model)


def test_invalid_role_setting_rejects_without_partial_store_write(configured, monkeypatch):
    store, _ = configured
    monkeypatch.setenv(SETTING, 'unknown')
    with pytest.raises(RuntimeError, match='REASONING_EFFORT_INVALID'):
        bind_role_services(store)
    assert store.get('role_model_services') is None
    assert store.get('role_generation') is None


async def test_sync_sdk_and_official_legacy_path_preserve_protocol(configured, monkeypatch):
    store, _ = configured
    monkeypatch.setenv(SETTING, 'high')
    bind_role_services(store)
    model = configured_model(store, 'coordinator')
    sent = []
    def receive(request):
        sent.append(json.loads(request.content))
        return completion(request)
    model.http_client._transport = httpx.MockTransport(receive)
    model.http_client._mounts.clear()
    try:
        model.invoke([HumanMessage('Synchronous offline contract.')])
        assert sent[0]['reasoning_effort'] == 'high' and sent[0]['max_tokens'] == 65536
    finally:
        await model.http_async_client.aclose()
        close_sync(model)
    monkeypatch.delenv(SETTING)
    monkeypatch.setenv('REPORT_COORDINATOR_BASE_URL', 'https://api.deepseek.com')
    official = configured_model(Store(store.root / 'official'), 'coordinator')
    try:
        payload = official._get_request_payload([HumanMessage('Official legacy.')])
        assert payload['reasoning_effort'] == 'max' and payload['max_tokens'] == 131072
    finally:
        await official.http_async_client.aclose()
        close_sync(official)


async def test_concurrent_role_requests_keep_own_options_without_environment_switch(configured, monkeypatch):
    store, _ = configured
    monkeypatch.setenv(SETTING, 'high')
    bind_role_services(store)
    before = dict(os.environ)
    sent = {}
    async def request_role(role):
        model = configured_model(store, role)
        async def receive(request):
            sent[role] = json.loads(request.content)
            await asyncio.sleep(0)
            return completion(request)
        model.http_async_client._transport = httpx.MockTransport(receive)
        model.http_async_client._mounts.clear()
        try:
            await model.ainvoke([HumanMessage('Concurrent offline request.')])
        finally:
            await model.http_async_client.aclose()
            close_sync(model)
    await asyncio.gather(*(request_role(role) for role in ('coordinator', 'reviewer', 'text_tool')))
    assert {role: value['reasoning_effort'] for role, value in sent.items()} == {
        'coordinator': 'high', 'reviewer': 'max', 'text_tool': 'max'}
    assert dict(os.environ) == before


def test_changed_recorded_output_cap_is_not_silently_consumed(configured, monkeypatch):
    store, _ = configured
    monkeypatch.setenv(SETTING, 'high')
    bind_role_services(store)
    changed = store.get('role_generation')
    changed['coordinator']['max_tokens'] = 16384
    store.set('role_generation', changed)
    with pytest.raises(RuntimeError, match='GENERATION.*FRESH'):
        configured_model(store, 'coordinator')
    assert store.get('role_generation') == changed
