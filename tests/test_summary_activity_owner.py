"""A shared model service must not replace the summarizing actor's identity."""
import httpx
from langchain_core.callbacks import BaseCallbackHandler

from report_agent.deep_models import RuntimeStatus
from report_agent.working_summary import working_summary
from test_bounded_deadline import offline_model, close_model
from test_prompt_native_sdk_inputs import completion
from test_task_supervision import ws


async def test_summary_activity_belongs_to_actor_not_shared_model_service(ws, monkeypatch):
    model = offline_model(ws, monkeypatch)
    monkeypatch.setattr('report_agent.model_invocation.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    model.max_retries = model.root_async_client.max_retries = 0
    service_status = RuntimeStatus(ws.store, 'coordinator')
    unrelated = BaseCallbackHandler()
    model.callbacks = [service_status, unrelated]
    model.http_async_client._transport = httpx.MockTransport(
        lambda request: completion(request, 'Synthetic summary; limitations retained.'))
    model.http_async_client._mounts.clear()
    reviewer = working_summary(model, ws.store, role='reviewer')
    writer = working_summary(model, ws.store, role='writer')
    try:
        await reviewer.model.ainvoke('Summarize only the current reviewer history.')
        assert ws.store.get('report_activity') == 'reviewer'
        await writer.model.ainvoke('Summarize only the current writer history.')
        assert ws.store.get('report_activity') == 'writer'
        assert model.callbacks == [service_status, unrelated]
        assert service_status.role == 'coordinator'
        assert reviewer.model.callbacks[-1] is unrelated
        status = reviewer.model.callbacks[0]
        status.on_llm_error(ValueError('synthetic failure'), run_id='fake-summary')
        event = [e for e in ws.store.events() if e['kind'] == 'deep_model_error'][-1]
        assert event['data']['role'] == 'reviewer'
        assert event['data']['model_service_role'] == 'coordinator'
    finally:
        await close_model(model)
