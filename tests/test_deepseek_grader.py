"""Grader-only provider protocol and isolated-trial identity; no real inference."""
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from openai import AsyncOpenAI

from report_agent.deep_models import configured_model, bind_grader_trial
from report_agent.store import Store


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv('REPORT_MODEL', 'glm-5.3')
    monkeypatch.setenv('REPORT_GRADER_MODEL', 'deepseek-v4.1-flash')
    monkeypatch.setenv('REPORT_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('REPORT_BASE_URL', 'https://model.invalid/v1')
    return Store(tmp_path)


def test_only_explicit_grader_roles_change(configured, monkeypatch):
    for role in ('coordinator', 'writer', 'knowledge', 'reviewer'):
        model = configured_model(configured, role)
        assert model.model_name == 'glm-5.3'
        assert model.extra_body == {'thinking': {'type': 'enabled', 'clear_thinking': False}}
    for role in ('rubric_grader', 'grader_diagnostic'):
        model = configured_model(configured, role)
        wire = model._get_request_payload([HumanMessage('synthetic')])
        assert wire['model'] == 'deepseek-v4.1-flash'
        assert wire['extra_body'] == {'enable_thinking': True}
        assert wire['max_tokens'] == 65536 and 'max_completion_tokens' not in wire
        assert wire['reasoning_effort'] == 'high' and wire['parallel_tool_calls'] is False
    monkeypatch.setenv('REPORT_GRADER_MODEL', 'deepseek-v4-pro')
    with pytest.raises(RuntimeError, match='AUTHORIZED_GRADER_MODEL_REQUIRED'):
        configured_model(configured, 'rubric_grader')
    monkeypatch.delenv('REPORT_GRADER_MODEL')
    assert configured_model(configured, 'rubric_grader').model_name == 'glm-5.3'


async def test_deepseek_tool_turn_preserves_opaque_field_and_redacts_audit(configured):
    requests = []
    marker = 'synthetic-opaque-reasoning-only'
    async def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        message = ({'role': 'assistant', 'content': '', 'reasoning_content': marker,
                    'tool_calls': [{'id':'t1','type':'function','function':{'name':'observe','arguments':'{}'}}]}
                   if len(requests) == 1 else {'role':'assistant','content':'OK','reasoning_content':marker})
        return httpx.Response(200,json={'id':'response','object':'chat.completion','created':1,
            'model':'deepseek-v4.1-flash','choices':[{'index':0,'finish_reason':'tool_calls' if len(requests)==1 else 'stop','message':message}],
            'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = configured_model(configured,'rubric_grader')
        sdk = AsyncOpenAI(api_key='synthetic-secret',base_url='https://model.invalid/v1',http_client=client,max_retries=0)
        model.async_client = sdk.chat.completions
        first = await model.ainvoke([HumanMessage('Observe')])
        second = await model.ainvoke([HumanMessage('Observe'),first,ToolMessage('observed',tool_call_id='t1')])
    assert second.content == 'OK'
    assert requests[1]['messages'][1]['reasoning_content'] == marker
    assert requests[0]['enable_thinking'] is True and 'thinking' not in requests[0]
    assert requests[0]['max_tokens'] == 65536
    audit = json.dumps(configured.events())
    assert marker not in audit and 'synthetic-secret' not in audit


def test_switch_cannot_reuse_old_approval_and_resume_cannot_change_model(configured, monkeypatch):
    configured.set('rubric_reviews',[{'result':'satisfied'}])
    with pytest.raises(RuntimeError,match='FRESH_REVIEW_FORK'):
        bind_grader_trial(configured)
    assert configured.get('rubric_reviews') == [{'result':'satisfied'}]
    assert configured.get('grader_model_trial') is None
    configured.set('review_import017',{'next':['FeedbackRubric.after_agent'],'attempt_id':'isolated'})
    configured.set('checkpoint_resume',True)
    configured.set('rubric_reviews',[])
    bind_grader_trial(configured)
    assert configured.get('grader_model_trial')['model'] == 'deepseek-v4.1-flash'
    configured.set('rubric_reviews',[{'result':'needs_revision'}])
    bind_grader_trial(configured)
    monkeypatch.delenv('REPORT_GRADER_MODEL')
    with pytest.raises(RuntimeError,match='FRESH_REVIEW_FORK'):
        bind_grader_trial(configured)
    assert configured.get('rubric_reviews') == [{'result':'needs_revision'}]
