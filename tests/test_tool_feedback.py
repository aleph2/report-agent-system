import pytest

from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.report_runtime import feedback_tool, worker_tools
from test_report_trunk import workspace


@pytest.mark.parametrize('error', [ValueError('decode failed'), PermissionError('file denied'), RuntimeError('unexpected')])
def test_unexpected_errors_are_not_converted_to_request_feedback(error):
    def broken():
        raise error
    with pytest.raises(type(error)) as caught:
        feedback_tool(broken)()
    assert caught.value is error


@pytest.mark.parametrize('error', [ActionRejected('INVALID_REQUEST'), ActionForbidden('RESULT_OWNER_MISMATCH')])
async def test_domain_errors_are_feedback_for_sync_and_async_tools(error):
    def broken():
        raise error
    async def async_broken():
        raise error
    assert feedback_tool(broken)()['accepted'] is False
    assert (await feedback_tool(async_broken)())['error']['message'] == str(error)


async def test_analysis_failure_does_not_record_successful_source_observation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from report_agent.models import TextAnalysis
    ws = workspace(tmp_path)
    task = ws.request_task('materials', 'Optional analysis', [])
    tools = {t.__name__: t for t in worker_tools(ws, task['id'], SimpleNamespace(model='offline-only'))}
    async def failed(*args):
        raise RuntimeError('SYNTHETIC_ANALYSIS_FAILURE')
    monkeypatch.setattr(TextAnalysis, 'analyze', failed)
    with pytest.raises(RuntimeError):
        await tools['analyze_sources'](['access'], 'Summarize')
    assert not ws.task(task['id'])['used_source_ids']
    assert not any(e['kind'] == 'source_observation' for e in ws.store.events())
    async def success(*args):
        return {'text': 'Synthetic analysis result'}
    monkeypatch.setattr(TextAnalysis, 'analyze', success)
    assert not (await tools['analyze_sources'](['access'], 'Summarize'))['reused']
    assert ws.store.events()[-1]['data']['extent'] == 'analysis_result'
    assert (await tools['analyze_sources'](['access'], 'Summarize'))['reused']
    assert ws.store.events()[-1]['data']['reused'] is True
