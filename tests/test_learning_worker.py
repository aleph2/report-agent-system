import asyncio

import pytest
from langchain_core.messages import AIMessage

from report_agent.learning import binding
from report_agent.learning_worker import consume_pending, watch_feedback
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke


@pytest.fixture
def configured(tmp_path):
    ws = Workspace(Store(tmp_path / "project"))
    ws.store.set("learning_config", {"library_path": str(tmp_path / "library"), "customer_id": "a"})
    return ws


def feedback(ws, correction="Format preference"):
    library, scope = binding(ws)
    return library.feedback(scope, {}, {}, correction, {}, [{"id": "source"}])


@pytest.mark.asyncio
async def test_saved_candidate_experiment_is_callable_from_native_learning_and_never_replayed(configured):
    from report_agent.learning_runtime import optimizer_tools
    library, scope = binding(configured)
    item = feedback(configured)
    candidate = library.propose(scope, [item['id']], 'customer_preference', 'Title', 'Learner strategy', 'Fixed condition', 'Pending')
    calls = []
    async def runner(seed):
        calls.append(seed)
        return {'state': 'completed', 'framework': 'GEPA', 'automatic_release': False}
    assert 'optimize_saved_guidance' not in {t.__name__ for t in optimizer_tools(configured)}
    tool = next(t for t in optimizer_tools(configured, runner) if t.__name__ == 'optimize_saved_guidance')
    job = await tool(candidate['id'], 1)
    assert job['state'] == 'completed' and len(calls) == 1
    assert not job['quality_verified'] and not library.list_versions(scope)[0]['active']
    with pytest.raises(Exception, match='GUIDANCE_EXPERIMENT_EXISTS'):
        await tool(candidate['id'], 1)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_saved_candidate_unknown_failure_is_durable_and_no_retry(configured):
    from report_agent.learning_worker import optimize_saved_candidate
    library, scope = binding(configured)
    item = feedback(configured)
    candidate = library.propose(scope, [item['id']], 'customer_preference', 'Title', 'Strategy', 'Fixed', 'Pending')
    async def runner(seed):
        raise TimeoutError('unknown response')
    with pytest.raises(TimeoutError):
        await optimize_saved_candidate(configured, candidate['id'], 1, runner)
    assert configured.store.get('guidance_experiment')['state'] == 'failed'
    with pytest.raises(Exception, match='GUIDANCE_EXPERIMENT_EXISTS'):
        await optimize_saved_candidate(configured, candidate['id'], 1, runner)


@pytest.mark.asyncio
async def test_empty_and_duplicate_feedback_do_not_call_model_twice(configured):
    calls = []
    def factory():
        calls.append(1)
        return driver("optimizer")
    assert (await consume_pending(configured, factory))["state"] == "idle"
    assert not calls
    first = feedback(configured)
    driver = Driver(optimizer=[invoke('record_feedback_disposition', feedback_id=first['id'],
        outcome='insufficient_evidence', rationale='No located report evidence in this fixture.'),
        AIMessage(content="Insufficient evidence; no candidate.")])
    assert feedback(configured)["id"] == first["id"]
    result = await consume_pending(configured, factory)
    assert result["state"] == "completed"
    assert result["claim"]["feedback_ids"] == [first["id"]]
    assert (await consume_pending(configured, factory))["state"] == "idle"
    assert calls == [1]


@pytest.mark.asyncio
async def test_failure_stays_failed_until_explicit_retry(configured):
    item = feedback(configured)
    def fail():
        raise RuntimeError("provider failed")
    with pytest.raises(RuntimeError):
        await consume_pending(configured, fail)
    library, scope = binding(configured)
    assert library.queue_status(scope)[0]["status"] == "failed"
    assert (await consume_pending(configured, fail))["state"] == "idle"
    with configured.store.run_lock():
        library.retry_feedback(scope, item["id"], "Operator verified retry")
    assert library.queue_status(scope)[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_report_lock_prevents_claiming_feedback(configured):
    feedback(configured)
    with configured.store.run_lock():
        with pytest.raises(RuntimeError, match="PROJECT_ALREADY_RUNNING"):
            await consume_pending(configured, lambda: pytest.fail("must not construct model"))
    library, scope = binding(configured)
    assert library.queue_status(scope)[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_worker_stops_at_job_bound(configured):
    item = feedback(configured)
    driver = Driver(optimizer=[invoke('record_feedback_disposition', feedback_id=item['id'],
        outcome='no_change', rationale='Existing behavior covers this preference.'),
        AIMessage(content="No useful candidate.")])
    result = await watch_feedback(configured, lambda: driver("optimizer"), stop=asyncio.Event(), max_jobs=1)
    assert result == {"completed_jobs": 1}


@pytest.mark.asyncio
async def test_explicit_host_limits_reach_native_learner_without_extra_authority(configured):
    item = feedback(configured)
    configured.store.set('learning_execution_limits', {
        'max_http_attempts': 28, 'whole_job_seconds': 900,
        'graph_step_limit': 100, 'deadline_utc': '2026-10-12T08:00:00+00:00',
        'unrelated_private_configuration': 'DO_NOT_COPY_THIS'})
    driver = Driver(optimizer=[invoke('record_feedback_disposition', feedback_id=item['id'],
        outcome='no_change', rationale='Existing behavior covers this preference.'),
        AIMessage(content='No change; disposition saved.')])
    result = await consume_pending(configured, lambda: driver('optimizer'), max_steps=100)
    assert result['state'] == 'completed'
    first_input = '\n'.join(str(m.content) for m in driver.calls[0][2])
    assert '"max_http_attempts": 28' in first_input and '"graph_step_limit": 100' in first_input
    assert 'HTTP attempts include SDK retries' in first_input
    assert 'do not prescribe your investigation route or expand permissions' in first_input
    assert 'DO_NOT_COPY_THIS' not in first_input
    library, scope = binding(configured)
    assert library.queue_status(scope)[0]['status'] == 'completed'


@pytest.mark.asyncio
async def test_invalid_model_tool_call_cannot_mark_feedback_completed(configured):
    feedback(configured)
    driver = Driver(optimizer=[AIMessage(content='I will read more evidence.', invalid_tool_calls=[
        {'name': 'read_learning_evidence', 'args': '{bad', 'id': 'bad-call', 'error': 'invalid arguments', 'type': 'invalid_tool_call'}])])
    with pytest.raises(Exception, match='LEARNING_INVALID_TOOL_CALLS'):
        await consume_pending(configured, lambda: driver('optimizer'))
    library, scope = binding(configured)
    assert library.queue_status(scope)[0]['status'] == 'failed'
    assert configured.store.get('learning_job')['state'] == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('message', [AIMessage(content='', response_metadata={'finish_reason': 'length'}), AIMessage(content='')])
async def test_truncated_or_empty_response_cannot_complete_feedback(configured, message):
    feedback(configured)
    driver = Driver(optimizer=[message])
    with pytest.raises(Exception, match='LEARNING_(INCOMPLETE|EMPTY)_RESPONSE'):
        await consume_pending(configured, lambda: driver('optimizer'))
    library, scope = binding(configured)
    assert library.queue_status(scope)[0]['status'] == 'failed'
