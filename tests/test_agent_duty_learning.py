"""Optimizer decisions stay distinct from analysis, adoption and publication."""
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.learning_runtime import build_optimizer
from test_agent_result_delivery import packet, reply
from test_bounded_review import Model
from test_deep_runtime import Driver, invoke
from test_learning_text_work import case
from test_task_supervision import ws, offline


@pytest.mark.parametrize('category', ['project_fact', 'general_skill', 'customer_preference'])
async def test_native_analysis_candidate_disposition_preserves_scope_and_inactive_status(case, category):
    ws, library, scope, feedback = case
    ws.store.set('learning_active_feedback', {'id': 'test-claim', 'feedback_ids': [feedback['id']]})
    fact = {'title': 'Synthetic class table', 'strategy': 'B permits 75–100.',
            'conditions': 'Only this synthetic supplied table.'}
    model = Model(json.dumps({'findings': 'B,70 disagrees with the supplied table.', 'project_fact': fact}))
    chosen = fact if category == 'project_fact' else {
        'title': 'Compare actual table', 'strategy': 'Choose the described class before its score.',
        'conditions': 'When the supplied guide defines classes.'}
    observed = []

    def propose(messages):
        value = packet(reply(messages, 'analyze_learning_material'))
        assert value['fact_correctness_verified'] is False
        assert value['payload']['project_fact'] == fact
        kwargs = {'analysis_id': value['analysis_id']} if category == 'project_fact' else {}
        return invoke('propose_experience', feedback_ids=[feedback['id']], kind=category,
                      **chosen, verification='Compare against supplied evidence', **kwargs)

    def disposition(messages):
        value = packet(reply(messages, 'propose_experience'))
        # Inspect saved data too, rather than assuming the model return is a release.
        candidates = library.list_versions(scope)
        assert len(candidates) == 1, value
        candidate = candidates[0]
        assert candidate['kind'] == category
        assert not library.search(scope)
        observed.append(candidate)
        return invoke('record_feedback_disposition', feedback_id=feedback['id'], outcome='candidate',
                      rationale='Inactive candidate for later validation', experience_id=candidate['id'],
                      experience_version=candidate['version'])

    def finish(messages):
        value = packet(reply(messages, 'record_feedback_disposition'))
        assert value['outcome'] == 'candidate' and value['quality_verified'] is False
        return AIMessage(content='Candidate saved; neither published nor validated.')

    driver = Driver(optimizer=[invoke('analyze_learning_material', question='Compare class and interval',
        feedback_selections=[{'feedback_id': feedback['id'], 'field': 'before'},
                             {'feedback_id': feedback['id'], 'field': 'evidence'}]), propose, disposition, finish])
    await build_optimizer(ws, driver('optimizer'), text_model=model).ainvoke(
        {'messages': [('user', 'Investigate only the assigned synthetic feedback; do not publish.')]},
        config={'recursion_limit': 16})
    assert len(model.calls) == 1 and len(observed) == 1
    wire = json.dumps(json.loads(model.calls[0][1][1]), ensure_ascii=False)
    assert 'B,70' in wire and 'B permits 75–100' in wire
    assert not library.search(scope)
    assert feedback['id'] in ws.store.get('learning_job')['feedback_dispositions']


@pytest.mark.parametrize('failure', ['received_invalid', 'unknown_transport'])
async def test_learning_analysis_repetition_does_not_reissue_failed_request(case, failure):
    import httpx
    from pydantic import ValidationError
    from report_agent.errors import ActionRejected
    from report_agent.learning_runtime import optimizer_tools
    from report_agent.learning_text_work import FeedbackSelection
    ws, library, scope, feedback = case
    model = Model('not valid JSON' if failure == 'received_invalid' else httpx.ReadTimeout('Unknown response'))
    tool = {f.__name__: f for f in optimizer_tools(ws, text_model=model)}['analyze_learning_material']
    selection = [FeedbackSelection(feedback_id=feedback['id'], field='evidence')]
    diagnostics = []
    for attempt in range(2):
        error = (ActionRejected if failure == 'received_invalid' else
                 httpx.ReadTimeout if attempt == 0 else ActionRejected)
        with pytest.raises(error) as caught:
            await tool('Compare the selected rule', selection)
        if failure == 'received_invalid':
            code, detail = str(caught.value).split(': ', 1)
            assert code == 'LEARNING_OUTPUT_CONTRACT_INVALID'
            detail = json.loads(detail)
            assert detail['failure_phase'] == 'output'
            assert detail['raw_response_received'] is True
            assert isinstance(caught.value.__cause__, ValidationError)
            assert detail['errors'][0]['type'] == 'json_invalid'
            assert all('input' not in error and 'ctx' not in error for error in detail['errors'])
            raw = ws.store.analysis(detail['raw_operation'])
            assert raw['operation'] == detail['raw_operation']
            assert raw['analysis'] == 'not valid JSON'
            diagnostics.append(detail)
        elif attempt == 1:
            assert str(caught.value).startswith('REVIEW_ANALYSIS_PREVIOUS_ATTEMPT_UNRESOLVED:')
    if failure == 'received_invalid':
        assert diagnostics[0] == diagnostics[1]
        with ws.store.connect() as db:
            assert db.execute("SELECT count(*) FROM state WHERE key LIKE 'learning_analysis:%'").fetchone()[0] == 0
    assert len(model.calls) == 1
    assert not library.list_versions(scope)
    assert not ws.store.get('learning_job').get('feedback_dispositions')


async def test_saved_candidate_and_done_cannot_complete_other_feedback_or_replay(case):
    from report_agent.errors import ActionRejected
    from report_agent.learning_worker import consume_pending
    ws, library, scope, first = case
    second = library.feedback(scope, {}, {}, 'Missing rule still needs investigation', {}, ['Unresolved'])

    def disposition(messages):
        candidate = packet(reply(messages, 'propose_experience'))
        return invoke('record_feedback_disposition', feedback_id=first['id'], outcome='candidate',
                      rationale='Candidate awaits evaluation', experience_id=candidate['id'],
                      experience_version=candidate['version'])

    driver = Driver(optimizer=[invoke('propose_experience', feedback_ids=[first['id']],
        kind='general_skill', title='Check rule', strategy='Read the rule before selecting a score',
        conditions='When a rule is supplied', verification='Compare actual selected class'), disposition,
        AIMessage(content='Done. Everything is complete.')])
    with pytest.raises(ActionRejected, match='LEARNING_FEEDBACK_UNACCOUNTED'):
        await consume_pending(ws, lambda: driver('optimizer'))
    job = ws.store.get('learning_job')
    assert job['state'] == 'failed'
    assert set(job['feedback_dispositions']) == {first['id']}
    assert second['id'] not in job['feedback_dispositions']
    assert len(library.list_versions(scope)) == 1 and not library.search(scope)
    assert all(row['status'] == 'failed' for row in library.queue_status(scope))
    before = len(driver.calls)
    assert await consume_pending(ws, lambda: pytest.fail('Failed jobs must not automatically replay')) == {'state': 'idle'}
    assert len(driver.calls) == before


@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('revoked', [False, True])
async def test_native_writer_cached_experience_respects_current_host_release(ws, tmp_path, managed, revoked, request):
    from report_agent.deep_runtime import run_report
    from report_agent.learning import binding, LearningScope
    from test_decision_data import activate
    from test_hierarchical_content import seed
    from test_learning import proposal
    cs, _, refs, _, _ = seed(ws)
    before = cs.read(refs['claim'])
    ws.store.set('learning_config', {'library_path': str(tmp_path / 'shared-learning'),
                                     'customer_id': 'synthetic'})
    library, report_scope = binding(ws)
    origin = LearningScope(report_scope.customer, 'synthetic-origin-project')
    candidate = proposal(library, origin)
    library.release(origin, candidate['id'], 1, 'Synthetic host-authorized release')
    if managed:
        activate(ws)
    observed = {}

    def try_cached_use(messages):
        items = packet(reply(messages, 'search_experience'))['items']
        assert len(items) == 1 and items[0]['id'] == candidate['id']
        assert items[0]['version'] == 1 and items[0]['strategy'] == candidate['strategy']
        observed['retrieved'] = items[0]
        # An authorized host event between retrieval and use; never an agent
        # release tool or production library mutation.
        if revoked:
            library.release(origin, candidate['id'], None, 'Synthetic host withdrawal')
        return invoke('record_experience_use', experience_id=candidate['id'], version=1,
                      target_ref=refs['claim'], reason='Apply retrieved synthetic preference')

    def inspect_use(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage)
                       and m.tool_call_id == 'record_experience_use')
        with library.store.connect() as db:
            count = db.execute("SELECT count(*) FROM learning_audit WHERE kind='application_declared'").fetchone()[0]
        if revoked:
            assert message.status == 'error'
            assert 'EXPERIENCE_NOT_ACTIVE' in str(message.content)
            assert count == 0 and not library.search(report_scope)
            if managed:
                from report_agent.task_context import exact_task_context
                assert not exact_task_context(ws, 'writer')['learned_guidance']['customer_preferences']
        else:
            assert message.status == 'success'
            assert packet(message)['experience']['id'] == candidate['id']
            assert count == 1
        observed['use'] = {'status': message.status, 'content': message.content,
                           'declared_use_records': count}
        return invoke('read_context', target_ref=refs['claim'])

    def finish(messages):
        shown = packet(reply(messages, 'read_context'))
        value = shown.get('metadata', shown)
        assert value['ok'] is True
        assert value['result']['objects'][0]['payload'] == before['payload']
        return AIMessage(content='Experience status checked; ordinary source work remains available.')

    driver = Driver(coordinator=[invoke('task', subagent_type='writer',
        description='Check the active customer preference; preserve source content.'),
        AIMessage(content='Synthetic evidence received.')],
        writer=[invoke('search_experience'), try_cached_use, inspect_use, finish])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert cs.read(refs['claim']) == before
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('native_release_currentness', json.dumps({
        'managed': managed, 'revoked_between_retrieval_and_use': revoked,
        'observed': observed, 'current_content_unchanged': True,
        'real_model_strategy_quality_tested': False}, ensure_ascii=False)))
