"""Offline provider routing and wire checks; never contact a real model endpoint."""
import os
import pytest
from langchain_core.messages import HumanMessage
from report_agent.model_config import load_mixed_services, role_service
from report_agent.deep_models import configured_model, configured_vision_client
from report_agent.store import Store


def write_config(path, endpoint='https://workspace.maas.aliyuncs.com/compatible-mode/v1'):
    path.write_text('HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash-1017\n'
                    f'HIGHWAY_MODEL_DEEPSEEK_BASE_URL={endpoint}\n'
                    'HIGHWAY_MODEL_DEEPSEEK_API_KEY=synthetic-deep-key\n'
                    'HIGHWAY_MODEL_NAME=glm-5.3\n'
                    'HIGHWAY_MODEL_BASE_URL=https://glm.example/v1\n'
                    'HIGHWAY_MODEL_API_KEY=synthetic-glm-key\n')


async def test_custom_deepseek_bundle_routes_all_deep_services_without_official_rewrite(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    path = tmp_path/'test.env'; write_config(path)
    safe = load_mixed_services(path)
    assert 'synthetic-deep-key' not in str(safe)
    assert os.environ['REPORT_DEEPSEEK_STRICT'] == '0'
    endpoint = 'https://workspace.maas.aliyuncs.com/compatible-mode/v1'
    for role in ['coordinator', 'reviewer', 'text_tool', 'vision', 'rubric_grader', 'grader_diagnostic']:
        assert role_service(role) == ('deepseek-v4.1-flash-1017', endpoint, 'synthetic-deep-key')
        model = configured_model(Store(tmp_path/role), role)
        assert model.model_name == 'deepseek-v4.1-flash-1017'
        assert model.openai_api_base == endpoint
        assert model.openai_api_key.get_secret_value() == 'synthetic-deep-key'
        payload = model._get_request_payload([HumanMessage(content='offline')])
        assert payload['model'] == 'deepseek-v4.1-flash-1017'
        assert payload['extra_body'] == {'enable_thinking': True}
        assert not model.deepseek_strict and 'max_completion_tokens' not in payload
        assert model.max_retries == 0
        assert model.root_async_client.max_retries == 0
        assert model.root_client.max_retries == 0
        await model.http_async_client.aclose()
    vision = configured_vision_client()
    assert str(vision.base_url).rstrip('/') == endpoint
    assert vision.api_key == 'synthetic-deep-key'
    assert vision.max_retries == 0
    await vision.close()
    assert role_service('writer') == ('glm-5.3', 'https://glm.example/v1', 'synthetic-glm-key')
    assert role_service('layout') == role_service('writer')


def test_invalid_custom_endpoint_does_not_partially_mutate_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    path=tmp_path/'bad.env'; write_config(path, 'http://invalid.example/v1')
    before = dict(os.environ)
    with pytest.raises(ValueError, match='DEEPSEEK_HTTPS'):
        load_mixed_services(path)
    assert dict(os.environ) == before


async def test_vision_request_uses_configured_model_instead_of_historical_alias(tmp_path, monkeypatch):
    from report_agent.vision import _observe
    from test_vision import VisionModel
    monkeypatch.setenv('REPORT_VISION_MODEL', 'deepseek-env-selected-model')
    fake = VisionModel()
    fake.returned_model = 'deepseek-env-selected-model'
    result = await _observe(Store(tmp_path), b'fake-image', {'source_id':'offline'}, 'read', fake)
    assert result['status'] == 'observed'
    assert fake.calls[0]['model'] == 'deepseek-env-selected-model'


async def test_configured_vision_transport_failure_is_not_automatically_retried(monkeypatch):
    import httpx
    import openai
    from report_agent import model_config, deep_models
    requests = []
    async def fail(request):
        import json
        assert json.loads(request.content)['model'] == model_config.role_service('vision')[0].removeprefix('openai/')
        requests.append(request)
        return httpx.Response(503, json={'error': {'message': 'offline transient failure', 'type': 'server_error'}})
    from report_agent import transport_observation
    client_type = transport_observation.ObservedAsyncClient
    monkeypatch.setattr(model_config, 'role_service', lambda role: ('deepseek-v4.1-flash-1017', 'https://offline.invalid/v1', 'synthetic'))
    class OfflineClient(client_type):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(transport_observation, 'ObservedAsyncClient', OfflineClient)
    client = configured_vision_client()
    try:
        with pytest.raises(openai.InternalServerError):
            await client.chat.completions.create(model=model_config.role_service('vision')[0].removeprefix('openai/'), messages=[{'role': 'user', 'content': 'offline'}])
        assert len(requests) == 1
    finally:
        await client.close()


@pytest.mark.parametrize('model_name', ['deepseek-v4.1-flash-1017', 'glm-5.3'])
async def test_configured_chat_sdk_failure_is_not_retried(tmp_path, monkeypatch, model_name):
    import httpx
    import openai
    from report_agent import model_config, deep_models
    requests = []
    async def fail(request):
        requests.append(request)
        return httpx.Response(503, json={'error': {'message': 'offline transient failure', 'type': 'server_error'}})
    from report_agent import transport_observation
    client_type = transport_observation.ObservedAsyncClient
    class OfflineClient(client_type):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(model_config, 'role_service', lambda role: (model_name, 'https://offline.invalid/v1', 'synthetic'))
    monkeypatch.setattr(transport_observation, 'ObservedAsyncClient', OfflineClient)
    model = configured_model(Store(tmp_path), 'coordinator')
    try:
        assert model.root_async_client.max_retries == model.root_client.max_retries == 0
        with pytest.raises(openai.InternalServerError):
            await model.ainvoke([HumanMessage(content='offline')])
        assert len(requests) == 1
    finally:
        await model.http_async_client.aclose()
