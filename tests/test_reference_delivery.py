import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import openai
import pytest

from report_agent.request_budget import RequestBudget, RequestBudgetExceeded, request_budget, account_request
from report_agent.deep_models import error_data
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.deep_runtime import project_view


def test_shared_transport_budget_blocks_before_send_and_resets():
    async def run():
        sent = []
        def respond(request):
            sent.append(request.url.path)
            return httpx.Response(200, json={})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), event_hooks={'request':[account_request]}) as agent, httpx.AsyncClient(transport=httpx.MockTransport(respond), event_hooks={'request':[account_request]}) as vision:
            budget = RequestBudget(2)
            with request_budget(budget):
                await asyncio.gather(agent.post('https://test/agent'), vision.post('https://test/vision'))
                with pytest.raises(RequestBudgetExceeded):
                    await vision.post('https://test/retry')
            await agent.post('https://test/unlimited')
        assert budget.count == 2
        assert len(sent) == 3
    asyncio.run(run())


def test_reservation_is_atomic():
    b = RequestBudget(7)
    def claim(_):
        try:
            b.reserve()
            return 1
        except RequestBudgetExceeded:
            return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(40))) == 7


def test_wrapped_budget_error_is_not_provider_outage():
    exc = openai.APIConnectionError(request=httpx.Request('POST','https://test'))
    exc.__cause__ = RequestBudgetExceeded('MODEL_REQUEST_BUDGET_REACHED')
    assert error_data(exc)['message'] == 'MODEL_REQUEST_BUDGET_REACHED'


def test_sdk_retries_cannot_send_past_budget():
    async def run():
        sent = []
        def respond(request):
            sent.append(request)
            return httpx.Response(429, json={'error':{'message':'retry','type':'rate_limit'}}, headers={'retry-after-ms':'1'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), event_hooks={'request':[account_request]}) as http:
            client = openai.AsyncOpenAI(api_key='synthetic',base_url='https://test',http_client=http,max_retries=2)
            with request_budget(RequestBudget(1)):
                with pytest.raises(RequestBudgetExceeded) as err:
                    await client.chat.completions.create(model='test',messages=[{'role':'user','content':'test'}])
            assert error_data(err.value)['message'] == 'MODEL_REQUEST_BUDGET_REACHED'
            assert len(sent) == 1
    asyncio.run(run())


def test_configured_clients_install_budget_hook(monkeypatch,tmp_path):
    from report_agent.deep_models import configured_model, configured_vision_client
    from report_agent import model_config
    monkeypatch.setattr(model_config,'role_service',lambda role:('deepseek-flash','https://api.deepseek.com','synthetic'))
    monkeypatch.setenv('REPORT_BASE_URL','https://api.deepseek.com')
    monkeypatch.setenv('REPORT_API_KEY','synthetic')
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT','0')
    model = configured_model(Store(tmp_path),'coordinator')
    client = configured_vision_client()
    assert account_request in model.http_async_client.event_hooks['request']
    assert account_request in client._client.event_hooks['request']
    asyncio.run(model.http_async_client.aclose())
    asyncio.run(client.close())


def test_reference_is_bound_and_visible_without_becoming_a_task_plan(tmp_path):
    store = Store(tmp_path)
    manifest = {'goal':'Use reference style for new project', 'sources':[
        {'id':'ref','title':'Reference','content':'Reference facts are not new project facts','coverage':'complete'}],
        'presentation_references':[{'source_id':'ref','instruction':'Match presentation, adapt to new content'}]}
    store.initialize(manifest)
    ws = Workspace(store)
    ws.initialize()
    assert project_view(ws)['presentation_references'] == manifest['presentation_references']
    with pytest.raises(ValueError, match='INVALID_PRESENTATION_REFERENCE'):
        Store(tmp_path/'bad').initialize({**manifest,'presentation_references':[{'source_id':'missing'}]})
