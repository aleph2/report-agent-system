"""P14/P15/P17/P18/P19: native learning boundaries, not learned quality."""
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.learning import LearningScope
from report_agent.learning_runtime import build_optimizer
from report_agent.store import digest, encode
from test_agent_result_delivery import packet, reply, run_role
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_learning_text_work import case
from test_task_supervision import ws, offline


def record(request, case, **values):
    request.node.user_properties.append((case, json.dumps(values, ensure_ascii=False, default=str)))


def last(messages, name):
    return next(m for m in reversed(messages)
                if isinstance(m, ToolMessage) and m.tool_call_id == name)


async def optimizer(ws, script, text_model=None, runner=None):
    driver = Driver(optimizer=script)
    result = await build_optimizer(ws, driver('optimizer'), experiment_runner=runner,
                                   text_model=text_model).ainvoke(
        {'messages': [('user', 'Inspect only this synthetic feedback; preserve uncertainty and do not publish.')]},
        config={'recursion_limit': 32})
    return driver, result


@pytest.mark.parametrize('field', ['correction', 'before', 'evidence'])
async def test_p15_native_pages_preserve_full_unicode_field_and_digest(case, field, request):
    ws, lib, scope, old = case
    text = '原文🙂' * 2800 + 'TAIL: unresolved conflict, no acceptance.'
    new = lib.feedback(scope, {}, {}, text, {'text': text}, [{'text': text}])
    ws.store.set('learning_active_feedback', {'id': 'current', 'feedback_ids': [new['id']]})
    expected = new[field] if isinstance(new[field], str) else encode(new[field])
    assert 8000 < len(expected) < 16000, 'FIXTURE_INVALID: must cross one real page boundary'
    pages = []

    def page(messages):
        value = packet(reply(messages, 'read_learning_feedback'))
        if not pages and 'feedback' in value:
            assert value['feedback'][0]['id'] == new['id']
            assert value['feedback'][0]['assigned']
            return invoke('read_learning_feedback', feedback_id=new['id'], field=field, limit=8000)
        pages.append(value)
        assert value['digest'] == digest(new[field])
        assert value['total_chars'] == len(expected)
        if value['next_offset'] is not None:
            return invoke('read_learning_feedback', feedback_id=new['id'], field=field,
                          offset=value['next_offset'], limit=8000)
        assert ''.join(p['text'] for p in pages) == expected
        assert 'TAIL: unresolved conflict, no acceptance.' in pages[-1]['text']
        return AIMessage(content='Full original read; judgment remains unverified.')

    driver, result = await optimizer(ws, [invoke('read_learning_feedback'), page, page, page])
    record(request, 'P15', field=field, expected_chars=len(expected), pages=pages,
           native_calls=len(driver.calls), final=result['messages'][-1].content)
    assert len(pages) == 2 and not lib.list_versions(scope)


@pytest.mark.parametrize('foreign', [False, True], ids=['historical-same-project', 'other-project'])
async def test_p15_history_read_scope_is_distinct_from_disposition_assignment(case, foreign, request):
    ws, lib, scope, assigned = case
    other_scope = LearningScope(scope.customer, 'other-project') if foreign else scope
    historical = lib.feedback(other_scope, {}, {}, 'Historical evidence', {}, ['Original context'])
    ws.store.set('learning_active_feedback', {'id': 'current', 'feedback_ids': [assigned['id']]})
    observations = []

    def after_read(messages):
        value = last(messages, 'read_learning_feedback')
        observations.append(value.model_dump())
        if foreign:
            assert value.status == 'error' and 'FEEDBACK_OUTSIDE_PROJECT' in value.content
        else:
            assert value.status == 'success'
            assert packet(value)['text'] == 'Historical evidence'
        return invoke('record_feedback_disposition', feedback_id=historical['id'],
                      outcome='no_change', rationale='Not in current assignment')

    def finish(messages):
        value = last(messages, 'record_feedback_disposition')
        observations.append(value.model_dump())
        assert value.status == 'error' and 'FEEDBACK_NOT_ASSIGNED' in value.content
        assert not ws.store.get('learning_job').get('feedback_dispositions')
        return AIMessage(content='Historical read and current write permissions kept separate.')

    await optimizer(ws, [invoke('read_learning_feedback', feedback_id=historical['id']), after_read, finish])
    record(request, 'P15', foreign=foreign, observations=observations)


@pytest.mark.parametrize('variant', ['exact', 'changed-fact', 'old-job'])
async def test_p17_native_fact_adoption_binds_exact_analysis_and_job(case, variant, request):
    ws, lib, scope, feedback = case
    fact = {'title': 'Synthetic rule', 'strategy': 'B permits 75–100.', 'conditions': 'This supplied table only.'}
    text_model = Model(json.dumps({'findings': 'B,70 conflicts with the supplied rule.', 'project_fact': fact}))
    observed = []

    def propose(messages):
        value = packet(reply(messages, 'analyze_learning_material'))
        assert value['payload']['project_fact'] == fact and not value['fact_correctness_verified']
        observed.append(value)
        if variant == 'old-job':
            ws.store.set('learning_job', {'id': 'different-job', 'state': 'running'})
        chosen = {**fact, 'strategy': 'B permits 70.'} if variant == 'changed-fact' else fact
        return invoke('propose_experience', feedback_ids=[feedback['id']], kind='project_fact',
                      **chosen, verification='Check original table', analysis_id=value['analysis_id'])

    def finish(messages):
        value = last(messages, 'propose_experience')
        observed.append(value.model_dump())
        if variant == 'exact':
            assert value.status == 'success'
            assert len(lib.list_versions(scope)) == 1
        else:
            assert value.status == 'error'
            expected = 'OUTPUT_CHANGED' if variant == 'changed-fact' else 'REQUIRES_CURRENT_SCOPED_ANALYSIS'
            assert expected in value.content and not lib.list_versions(scope)
        assert not lib.search(scope)
        return AIMessage(content='No active release or quality verdict.')

    await optimizer(ws, [invoke('analyze_learning_material', question='Compare the original rule',
        feedback_selections=[{'feedback_id': feedback['id'], 'field': 'evidence'}]), propose, finish], text_model)
    record(request, 'P17', variant=variant, observed=observed, independent_text_calls=len(text_model.calls))
    assert len(text_model.calls) == 1


@pytest.mark.parametrize('variant', ['next-version', 'stale-version', 'change-kind'])
async def test_p17_native_strategy_candidate_cas_and_kind_are_host_checked(case, variant, request):
    ws, lib, scope, feedback = case
    original = lib.propose(scope, [feedback['id']], 'general_skill', 'Read actual table',
                           'Select described class before score', 'When supplied', 'Compare original')
    seen = []

    def finish(messages):
        value = last(messages, 'propose_experience')
        seen.append(value.model_dump())
        if variant == 'next-version':
            assert value.status == 'success' and packet(value)['version'] == 2
        else:
            assert value.status == 'error'
            code = 'VERSION_CONFLICT' if variant == 'stale-version' else 'SCOPE_IMMUTABLE'
            assert code in value.content
        assert not lib.search(scope)
        return AIMessage(content='Candidate remains inactive.')

    await optimizer(ws, [invoke('propose_experience', feedback_ids=[feedback['id']],
        kind='customer_preference' if variant == 'change-kind' else 'general_skill',
        title='Check actual rule', strategy='Keep uncertainty when source is missing',
        conditions='When source is missing', verification='Inspect the rule',
        experience_id=original['id'], expected_version=0 if variant == 'stale-version' else 1), finish])
    versions = lib.list_versions(scope)
    record(request, 'P17', variant=variant, observed=seen, versions=versions)
    assert len(versions) == (2 if variant == 'next-version' else 1)
    assert next(v for v in versions if v['version'] == 1)['strategy'] == original['strategy']


@pytest.mark.parametrize('outcome', ['no_change', 'insufficient_evidence'])
async def test_p18_native_all_dispositions_can_complete_without_candidate(case, outcome, request):
    from report_agent.learning_worker import consume_pending
    ws, lib, scope, first = case
    second = lib.feedback(scope, {}, {}, 'Second uncertainty', {}, ['The source supplies no comparison value.'])
    calls = [{'name': 'record_feedback_disposition', 'id': f'disposition-{i}', 'type': 'tool_call',
              'args': {'feedback_id': f['id'], 'outcome': outcome, 'rationale': 'No verified improvement supported'}}
             for i, f in enumerate((first, second))]
    driver = Driver(optimizer=[AIMessage(content='', tool_calls=calls),
                               AIMessage(content='Both feedback items accounted for; no publication.')])
    result = await consume_pending(ws, lambda: driver('optimizer'))
    job = ws.store.get('learning_job')
    record(request, 'P18', outcome=outcome, job=job, queue=lib.queue_status(scope), result=result)
    assert job['state'] == 'completed' and set(job['feedback_dispositions']) == {first['id'], second['id']}
    assert all(v['outcome'] == outcome and not v['quality_verified'] for v in job['feedback_dispositions'].values())
    assert not lib.list_versions(scope)


@pytest.mark.parametrize('enabled', [False, True], ids=['host-absent', 'host-present'])
async def test_p19_native_registration_and_terminal_experiment_no_replay(case, enabled, request):
    ws, lib, scope, feedback = case
    candidate = lib.propose(scope, [feedback['id']], 'general_skill', 'Candidate', 'Read rule', 'Supplied rule', 'Compare')
    observed, executions = [], []

    async def runner(saved):
        executions.append(saved)
        return {'synthetic_callback': True, 'real_gepa_executed': False}

    def invoke_again(messages):
        value = last(messages, 'optimize_saved_guidance')
        observed.append(value.model_dump())
        assert value.status == 'success' and packet(value)['state'] == 'completed'
        return invoke('optimize_saved_guidance', experience_id=candidate['id'], version=1)

    def finish(messages):
        if enabled:
            value = last(messages, 'optimize_saved_guidance')
            observed.append(value.model_dump())
            assert value.status == 'error' and 'GUIDANCE_EXPERIMENT_EXISTS' in value.content
        return AIMessage(content='Capability boundary checked; no GEPA quality or release claim.')

    script = ([invoke('optimize_saved_guidance', experience_id=candidate['id'], version=1), invoke_again, finish]
              if enabled else [finish])
    driver, _ = await optimizer(ws, script, runner=runner if enabled else None)
    registered = {t['name'] for t in driver.bindings['optimizer'][-1]}
    record(request, 'P19', enabled=enabled, registered=sorted(registered), observed=observed,
           executions=len(executions), experiment=ws.store.get('guidance_experiment'))
    assert ('optimize_saved_guidance' in registered) is enabled
    assert len(executions) == int(enabled) and not lib.search(scope)
    assert not {'task', 'release', 'commit_objects'} & registered


@pytest.mark.parametrize('role', ['coordinator', 'reviewer', 'layout'])
@pytest.mark.parametrize('revoked', [False, True])
async def test_p14_sibling_agent_experience_use_checks_current_release(ws, tmp_path, role, revoked, request):
    from report_agent.learning import binding
    from test_learning import proposal
    cs, _, refs, snapshot, _ = seed(ws)
    before = cs.read(refs['claim'])
    ws.store.set('learning_config', {'library_path': str(tmp_path / 'lib'), 'customer_id': 'synthetic'})
    lib, scope = binding(ws)
    origin = LearningScope(scope.customer, 'another-project')
    candidate = proposal(lib, origin)
    lib.release(origin, candidate['id'], 1, 'Synthetic host-authorized release')
    activate(ws)
    observed = []

    def use(messages):
        values = packet(reply(messages, 'search_experience'))['items']
        assert len(values) == 1 and values[0]['strategy'] == candidate['strategy']
        if revoked:
            lib.release(origin, candidate['id'], None, 'Synthetic host withdrawal')
        return invoke('record_experience_use', experience_id=candidate['id'], version=1,
                      target_ref=refs['claim'], reason='Synthetic scoped use')

    def finish(messages):
        value = last(messages, 'record_experience_use')
        observed.append(value.model_dump())
        assert value.status == ('error' if revoked else 'success')
        if revoked:
            assert 'EXPERIENCE_NOT_ACTIVE' in value.content
        assert cs.read(refs['claim']) == before
        return AIMessage(content='Release status observed; ordinary work and uncertainty remain.')

    await run_role(ws, role, [invoke('search_experience'), use, finish], refs, snapshot)
    record(request, 'P14', role=role, revoked=revoked, observed=observed, content_unchanged=True)


async def test_p15_native_evidence_pages_read_requested_old_version_not_head(ws, tmp_path, request):
    ws.store.set('learning_config', {'library_path': str(tmp_path / 'lib'), 'customer_id': 'synthetic'})
    cs, owner, refs, _, _ = seed(ws)
    payload = {'kind': 'block', 'body': {'text': '依据🙂' * 2800 + 'OLD_TAIL: unresolved.'},
               'qualifiers': {}, 'claim_kind': 'fact'}
    old_ref = cs.commit(owner, 'learning-readable-old', [
        {'client_key': 'old', 'type': 'ContentNode', 'payload': payload}])['result']['refs']['old']
    old = cs.read(old_ref)
    new_ref = cs.commit(owner, 'learning-readable-new', [
        {'client_key': 'new', 'type': 'ContentNode', 'previous_ref': old_ref,
         'payload': {**payload, 'body': {'text': 'NEW_HEAD: does not replace the requested old version.'}}}])['result']['refs']['new']
    expected, pages = encode(old), []
    assert 8000 < len(expected) < 16000

    def read_next(messages):
        value = packet(reply(messages, 'read_learning_evidence'))
        pages.append(value)
        assert value['ref'] == old_ref and value['digest'] == digest(old)
        if value['next_offset'] is not None:
            return invoke('read_learning_evidence', ref=old_ref, offset=value['next_offset'], limit=8000)
        assert ''.join(p['text'] for p in pages) == expected
        assert 'OLD_TAIL: unresolved.' in pages[-1]['text']
        return AIMessage(content='Exact old object read; no factual or engineering verdict.')

    await optimizer(ws, [invoke('read_learning_evidence', ref=old_ref, limit=8000), read_next, read_next])
    assert len(pages) == 2 and cs.read(old_ref) == old and cs.read(new_ref)['ref']['version'] == 2
    record(request, 'P15', old_ref=old_ref, head_ref=new_ref, pages=pages, source_unchanged=True)


async def test_p17_native_candidate_index_and_exact_version_pages_are_complete(case, request):
    ws, lib, scope, feedback = case
    candidates = [lib.propose(scope, [feedback['id']], 'general_skill', f'Candidate {i}',
        '策略🙂' * 2800 + 'OLD_STRATEGY_TAIL: retain uncertainty.' if i == 0 else f'Strategy {i}',
        'Synthetic only', 'No quality claim') for i in range(7)]
    chosen = candidates[0]
    lib.propose(scope, [feedback['id']], 'general_skill', 'Candidate 0 revised',
                'NEW_STRATEGY_HEAD', 'Synthetic only', 'No quality claim', chosen['id'], 1)
    before = lib.list_versions(scope)
    exact = next(v for v in before if v['id'] == chosen['id'] and v['version'] == 1)
    expected = encode(exact)
    assert 8000 < len(expected) < 16000
    indexes, pages = [], []

    def read_next(messages):
        value = packet(reply(messages, 'read_experience_candidates'))
        if 'items' in value:
            indexes.append(value)
            if value['next_offset'] is not None:
                return invoke('read_experience_candidates', offset=value['next_offset'])
            found = [(x['id'], x['version']) for p in indexes for x in p['items']]
            assert found == [(x['id'], x['version']) for x in before]
            assert len(found) == len(set(found)) == 8
            return invoke('read_experience_candidates', experience_id=chosen['id'], version=1, limit=8000)
        pages.append(value)
        assert value['id'] == chosen['id'] and value['version'] == 1 and value['digest'] == digest(exact)
        if value['next_offset'] is not None:
            return invoke('read_experience_candidates', experience_id=chosen['id'], version=1,
                          offset=value['next_offset'], limit=8000)
        assert ''.join(p['text'] for p in pages) == expected
        assert 'OLD_STRATEGY_TAIL: retain uncertainty.' in pages[-1]['text']
        return AIMessage(content='Exact inactive candidate version read; no publication.')

    await optimizer(ws, [invoke('read_experience_candidates'), *([read_next] * 4)])
    assert len(indexes) == len(pages) == 2 and lib.list_versions(scope) == before and not lib.search(scope)
    record(request, 'P17', indexes=indexes, pages=pages, candidate_versions_unchanged=True)


@pytest.mark.parametrize('lose_conditions', [False, True], ids=['intact', 'injected-loss-sensitive'])
async def test_p17_candidate_conditions_survive_native_analysis_and_adoption(case, monkeypatch, request, lose_conditions):
    from copy import deepcopy
    from report_agent import learning_text_work
    ws, lib, scope, feedback = case
    conditions = '适用范围🙂' * 100 + 'TAIL: unknown classification stays unresolved.'
    findings = 'Original comparison. ' * 40 + 'FINDINGS_TAIL: not engineering acceptance.'
    fact = {'title': 'Synthetic scoped fact', 'strategy': 'B permits 75–100.', 'conditions': conditions}
    model = Model(json.dumps({'findings': findings, 'project_fact': fact}))
    saved, visible = [], []
    original_factory = learning_text_work.learning_analysis_tool

    def instrumented_factory(workspace, selected_model):
        actual = original_factory(workspace, selected_model)

        async def analyze_learning_material(question, feedback_selections, object_selections=[]):
            result = await actual(question, feedback_selections, object_selections)
            saved.append(deepcopy(result))
            if lose_conditions:
                result = deepcopy(result)
                result['payload']['project_fact']['conditions'] = conditions[:240]
            return result
        # Preserve the original public input schema and docs; inject only output data.
        analyze_learning_material.__annotations__ = actual.__annotations__
        analyze_learning_material.__doc__ = actual.__doc__
        return analyze_learning_material

    monkeypatch.setattr(learning_text_work, 'learning_analysis_tool', instrumented_factory)

    def adopt(messages):
        value = packet(reply(messages, 'analyze_learning_material'))
        visible.append(value)
        assert value['payload']['findings'] == findings, 'LEARNING_FINDINGS_LOST'
        assert value['payload']['project_fact']['conditions'] == conditions, 'LEARNING_CONDITIONS_LOST'
        return invoke('propose_experience', feedback_ids=[feedback['id']], kind='project_fact',
                      **value['payload']['project_fact'], verification='Exact source comparison', analysis_id=value['analysis_id'])

    def finish(messages):
        value = last(messages, 'propose_experience')
        assert value.status == 'success'
        versions = lib.list_versions(scope)
        assert len(versions) == 1 and versions[0]['conditions'] == conditions and not versions[0]['active']
        return AIMessage(content='Exact scoped conditions preserved; no release.')

    script = [invoke('analyze_learning_material', question='Compare original sources',
                     feedback_selections=[{'feedback_id': feedback['id'], 'field': 'evidence'}]), adopt, finish]
    if lose_conditions:
        with pytest.raises(AssertionError, match='LEARNING_CONDITIONS_LOST'):
            await optimizer(ws, script, model)
        assert not lib.list_versions(scope)
    else:
        await optimizer(ws, script, model)
    assert len(model.calls) == 1 and saved[0]['payload']['project_fact'] == fact
    record(request, 'P17', injected_fault=lose_conditions, original=saved, visible=visible,
           proves='Only the intact finite path and original oracle sensitivity; no new product failure from injection.')


async def test_p19_native_failed_experiment_is_not_reentered_after_host_timeout(case, request):
    ws, lib, scope, feedback = case
    candidate = lib.propose(scope, [feedback['id']], 'general_skill', 'Candidate', 'Read source', 'Scoped', 'Pending')
    executions, observed = [], []

    async def unknown_runner(saved):
        executions.append(saved)
        raise TimeoutError('SYNTHETIC_HOST_CALLBACK_UNKNOWN')

    args = {'experience_id': candidate['id'], 'version': 1}
    with pytest.raises(TimeoutError, match='SYNTHETIC_HOST_CALLBACK_UNKNOWN'):
        await optimizer(ws, [invoke('optimize_saved_guidance', **args)], runner=unknown_runner)
    terminal = ws.store.get('guidance_experiment')
    assert terminal['state'] == 'failed' and terminal['error_type'] == 'TimeoutError'

    def rejected(messages):
        value = last(messages, 'optimize_saved_guidance')
        observed.append(value.model_dump())
        assert value.status == 'error' and 'GUIDANCE_EXPERIMENT_EXISTS' in value.content
        return AIMessage(content='Existing failed host experiment retained; no replay or release.')

    await optimizer(ws, [invoke('optimize_saved_guidance', **args), rejected], runner=unknown_runner)
    assert len(executions) == 1 and ws.store.get('guidance_experiment') == terminal and not lib.search(scope)
    record(request, 'P19', terminal=terminal, observed=observed, callback_invocations=len(executions),
           limitation='Fake host callback timeout; no GEPA execution or real provider unknown created.')
