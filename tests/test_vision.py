"""Bounded visual-tool mechanics; fake responses do not prove visual correctness."""

from report_agent import issue_state
from types import SimpleNamespace
import json
import logging

import httpx
from langchain_core.utils.function_calling import convert_to_openai_tool
import pytest

from report_agent.deep_models import configured_model, configured_vision_client
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.vision import observe_source_image
from test_document_tools import workspace


class VisionModel:
    base_url = 'https://unit.invalid/v1'
    max_retries = 2

    def __init__(self, content='Visible value: 28.9 m; interpretation unconfirmed.', finish='stop', error=None):
        self.content, self.finish, self.error = content, finish, error
        self.calls = []
        self.chat = self.completions = self
        self.returned_model = 'deepseek-v4.1-flash'
        self.refusal = None
        self.tool_calls = None
        self.closed = False

    async def close(self):
        self.closed = True

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(id='synthetic-response', model=self.returned_model, usage=None,
            choices=[SimpleNamespace(finish_reason=self.finish,
                message=SimpleNamespace(content=self.content, refusal=self.refusal, tool_calls=self.tool_calls))])


def source_snapshot(ws):
    return ws.store.manifest, ws.results(), issue_state.get_report_issues(ws.store), ws.store.get('report_delivery')


@pytest.mark.asyncio
async def test_actual_image_payload_provenance_cache_and_no_source_mutation(tmp_path):
    ws, model = workspace(tmp_path), VisionModel()
    ws.initialize()
    before = source_snapshot(ws)
    first = await observe_source_image(ws, 'original', 'Read the visible text.', client=model)
    second = await observe_source_image(ws, 'original', 'Read the visible text.', client=model)
    assert first['status'] == 'observed' and not first['reused']
    assert second['reused'] and len(model.calls) == 1
    blocks = model.calls[0]['messages'][1]['content']
    assert blocks[0]['text'] == 'Read the visible text.'
    assert blocks[1]['image_url']['url'].startswith('data:image/png;base64,')
    assert first['source']['source_id'] == 'original'
    assert len(first['image_sha256']) == 64
    assert source_snapshot(ws) == before
    serialized = json.dumps(ws.store.events())
    assert 'data:image/' not in serialized and 'base64' not in serialized
    assert 'https://unit.invalid' not in serialized


@pytest.mark.asyncio
async def test_cache_separates_question_region_page_and_endpoint(tmp_path):
    ws, model = workspace(tmp_path), VisionModel()
    for question, page, crop in [('read', 1, None), ('read labels', 1, None),
                                 ('read', 2, None), ('read', 1, [0, 0, .5, .5])]:
        await observe_source_image(ws, 'original', question, page, crop, client=model)
    model.base_url = 'https://different.invalid/v1'
    await observe_source_image(ws, 'original', 'read', client=model)
    assert len(model.calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize('content,finish', [('', 'stop'), ('Partial', 'length'),
                                           ('Unknown', None), ('Filtered', 'content_filter'),
                                           ([{'type': 'text', 'text': 'unsupported content shape'}], 'stop')])
async def test_incomplete_is_not_success_or_cached(tmp_path, content, finish):
    ws, model = workspace(tmp_path), VisionModel(content, finish)
    a = await observe_source_image(ws, 'original', 'read', client=model)
    b = await observe_source_image(ws, 'original', 'read', client=model)
    assert a['status'] == b['status'] == 'incomplete'
    assert b['reused'] and len(model.calls) == 1
    assert ws.store.analysis(a['operation']) is None


@pytest.mark.asyncio
async def test_transport_failure_is_safe_observation_not_missing_material(tmp_path):
    ws = workspace(tmp_path)
    model = VisionModel(error=httpx.ReadTimeout('secret provider text'))
    result = await observe_source_image(ws, 'original', 'read', client=model)
    assert result['status'] == 'failed'
    assert result['error']['message'] == 'MODEL_REQUEST_TIMEOUT'
    assert 'not evidence' in result['limitation']
    assert 'secret provider text' not in json.dumps(ws.store.events())
    assert len(model.calls) == 1
    assert ws.store.analysis(result['operation']) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('source,page,question', [('foreign', 1, 'read'), ('original', 0, 'read'),
                                                ('original', 99, 'read'), ('original', 1, ' ')])
async def test_invalid_request_makes_no_model_call(tmp_path, source, page, question):
    model = VisionModel()
    with pytest.raises(ActionRejected):
        await observe_source_image(workspace(tmp_path), source, question, page, client=model)
    assert not model.calls


@pytest.mark.parametrize('role', ['coordinator', 'knowledge', 'writer', 'reviewer'])
@pytest.mark.asyncio
async def test_each_role_can_observe_but_no_role_or_path_parameter(tmp_path, monkeypatch, role):
    ws, model = workspace(tmp_path), VisionModel()
    monkeypatch.setattr('report_agent.vision.configured_vision_client', lambda: model)
    tool = next(t for t in business_tools(ws, role, None, SimpleNamespace(model_name='unused'))
                if t.__name__ == 'analyze_source_image')
    from langchain_core.tools import StructuredTool
    # Exercise the actual registered interface: native runtime is injected,
    # not a model-facing argument of the plain Python callable.
    schema = convert_to_openai_tool(StructuredTool.from_function(coroutine=tool))['function']['parameters']['properties']
    assert set(schema) == {'source_id', 'question', 'page', 'crop'}
    result = await tool('original', 'read')
    assert result['status'] == 'observed'


@pytest.mark.asyncio
@pytest.mark.parametrize('sdk_retries', [None, 0, 5], ids=['default', 'explicit-zero', 'explicit-five'])
async def test_vision_model_uses_authorized_account_without_changing_agent_model(tmp_path, monkeypatch, sdk_retries):
    monkeypatch.setenv('REPORT_BASE_URL', 'https://unit.invalid/v1')
    monkeypatch.setenv('REPORT_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('REPORT_MODEL', 'glm-5.3')
    monkeypatch.delenv('REPORT_CONNECT_RETRIES', raising=False)
    if sdk_retries is None:
        monkeypatch.delenv('REPORT_SDK_RETRIES', raising=False)
    else:
        monkeypatch.setenv('REPORT_SDK_RETRIES', str(sdk_retries))
    vision = configured_vision_client()
    agent = None
    try:
        agent = configured_model(workspace(tmp_path).store, 'writer')
        assert agent.model_name == 'glm-5.3'
        assert str(vision.base_url).rstrip('/') == agent.openai_api_base
        expected = 0 if sdk_retries is None else sdk_retries
        assert vision.max_retries == agent.max_retries == expected
        assert not hasattr(vision, 'callbacks')
    finally:
        await vision.close()
        if agent is not None:
            await agent.root_async_client.close()
            agent.root_client.close()
    assert vision.is_closed()


def test_missing_config_fails_without_model_fallback(monkeypatch):
    monkeypatch.delenv('REPORT_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='VISION_SERVICE_CONFIGURATION_REQUIRED'):
        configured_vision_client()


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('refusal', 'refused'), ('tool_calls', ['unexpected']),
                                        ('returned_model', 'other-model')])
async def test_protocol_failures_not_cached(tmp_path, field, value):
    ws, client = workspace(tmp_path), VisionModel()
    setattr(client, field, value)
    a = await observe_source_image(ws, 'original', 'read', client=client)
    b = await observe_source_image(ws, 'original', 'read', client=client)
    assert a['status'] == b['status'] == 'incomplete'
    assert b['reused'] and len(client.calls) == 1
    assert ws.store.analysis(a['operation']) is None


@pytest.mark.asyncio
async def test_missing_config_becomes_observation(tmp_path, monkeypatch):
    monkeypatch.delenv('REPORT_API_KEY', raising=False)
    result = await observe_source_image(workspace(tmp_path), 'original', 'read')
    assert result['status'] == 'failed'
    assert result['error']['message'] == 'VISION_SERVICE_CONFIGURATION_REQUIRED'


@pytest.mark.asyncio
async def test_sdk_call_does_not_inherit_langchain_callbacks(tmp_path):
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.runnables.config import var_child_runnable_config

    class ForbiddenCallback(BaseCallbackHandler):
        def on_chat_model_start(self, *args, **kwargs):
            raise AssertionError('Image reached inherited callback')

    marker = var_child_runnable_config.set({'callbacks': [ForbiddenCallback()]})
    try:
        result = await observe_source_image(workspace(tmp_path), 'original', 'read', client=VisionModel())
        assert result['status'] == 'observed'
    finally:
        var_child_runnable_config.reset(marker)


@pytest.mark.asyncio
async def test_real_sdk_debug_payload_is_suppressed_only_inside_visual_call(tmp_path, caplog):
    from openai import AsyncOpenAI

    requests = []

    async def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={'id': 'test-vision', 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-v4.1-flash',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'Observed.'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        async with AsyncOpenAI(api_key='private-key', base_url='https://unit.invalid/v1',
                               http_client=transport, max_retries=0) as client:
            with caplog.at_level(logging.DEBUG, logger='openai._base_client'):
                result = await observe_source_image(workspace(tmp_path), 'original',
                                                    'private-image-question', client=client)
                logging.getLogger('openai._base_client').debug('outside-visual-call')
    assert result['status'] == 'observed'
    assert requests[0]['model'] == 'deepseek-v4.1-flash'
    assert requests[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert 'data:image/' not in caplog.text
    assert 'private-image-question' not in caplog.text
    assert 'private-key' not in caplog.text
    assert 'outside-visual-call' in caplog.text
