"""The native agent receives original operator input through its existing tool."""
import json

from langchain_core.messages import AIMessage

from test_hierarchical_content import ws
from test_deep_runtime import Driver, invoke, observation
from report_agent.deep_runtime import business_tools, project_view, run_report


def test_raw_operator_feedback_visible_in_workspace_and_bound_status_tool(ws):
    raw = 'I suggest the layout should be revised only once too'
    saved = ws.store.add_feedback(raw)
    assert saved in ws.status()['feedback']
    assert saved in project_view(ws)['feedback']
    status = next(t for t in business_tools(ws, 'coordinator', None, None)
                  if t.__name__ == 'project_status')
    assert saved in status()['feedback']
    assert saved['message'] == raw and saved['origin'] == 'operator'


async def test_original_operator_message_reaches_native_tool_return(ws, monkeypatch):
    import httpx
    def denied(*args, **kwargs):
        raise AssertionError('No network in native feedback delivery test')
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    ws.store.set('manifest', {**ws.store.manifest, 'review_entrypoint': 'delegated-reviewer-v1'})
    raw = 'The first priority of this project is fast. Fast to release to market.'
    saved = ws.store.add_feedback(raw)
    driver = Driver(coordinator=[invoke('project_status'), AIMessage(content='Feedback observed; no report rewritten.')])
    await run_report(ws, driver)
    returned = observation(driver.calls[-1][2], 'project_status')
    assert saved in returned['feedback']
    assert raw in json.dumps(returned)
