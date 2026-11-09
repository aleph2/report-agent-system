"""H3.3 terminal planning waits: native scripted mechanics, not model autonomy."""
from report_agent import issue_state
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from report_agent import plan_authority
from report_agent.commission_requirements import requirements_ref
from report_agent import commission_plan, commission_planning, deep_runtime
from report_agent.errors import ActionRejected
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, call, run, snapshot
from test_m1_g4_planning_steps import (
    method_commission, anchored, required_case, entries, draft_case, offline_only,
    current_native_profiles, save_draft_parts,
)

WAIT = 'commission_planning_completion_wait'


def question(identity='real-owner-pause', *, pause=True):
    return AIMessage(content='', tool_calls=[call('ask_human', {
        'category': 'requirement', 'description': 'Synthetic owner decision is required.',
        'source_ids': [], 'pause': pause,
    }, identity)])


def final(identity='planning-final'):
    return AIMessage(id=identity, content='Planning is over, but the owner has not approved it.')


def approval(fixture):
    view = save_draft_parts(fixture)
    assert not view['gaps'], view['gaps']
    commission_planning.submit_plan(fixture.cs, fixture.co, 'h33-submit-ready')
    checkpoint = commission_plan.request_checkpoint(fixture.ws)
    # Existing trusted approval boundary; never fabricate a confirmation record.
    commission_plan.reply(fixture.ws, checkpoint['issue_id'], {
        'plan_ref': plan_authority.plan_ref(fixture.ws.store),
        'requirements_ref': requirements_ref(fixture.ws.store),
        'approved': True, 'corrections': '', 'reductions': [],
    })
    return checkpoint


@pytest.mark.parametrize('nonpausing_question', [False, True])
async def test_unapproved_terminal_becomes_real_wait_without_extra_model_call(draft_case, nonpausing_question):
    f = draft_case
    current_native_profiles(f)
    scripts = [question('record-only', pause=False)] if nonpausing_question else []
    scripts.append(final())
    driver = Driver(coordinator=scripts)
    result = await run(f.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == len(scripts), 'No automatic extra model request may repair a terminal decision.'
    wait = f.ws.store.get(WAIT)
    assert wait and wait['issue_id']
    state = await snapshot(f.ws, driver)
    assert state.interrupts and state.interrupts[0].value['issue_id'] == wait['issue_id']
    issue = next(i for i in issue_state.get_report_issues(f.ws.store) if i['id'] == wait['issue_id'])
    assert not issue.get('decision_origin') and not issue['resolved']
    diagnostic = encode(state.interrupts[0].value)
    assert 'gap' in diagnostic.lower() and ('section' in diagnostic.lower() or 'object' in diagnostic.lower()), diagnostic
    assert plan_authority.decision_ref(f.ws.store) is None
    assert not f.cs.list_objects('CommissionDecision')
    assert any(isinstance(m, AIMessage) and m.content == final().content for m in state.values['messages'])
    reopened = Workspace(Store(f.ws.store.root))
    fresh = Driver(coordinator=[])
    again = await run(reopened, fresh)
    assert again['status'] == 'needs_human' and not fresh.calls, again
    assert reopened.store.get(WAIT)['issue_id'] == wait['issue_id']


async def test_trusted_note_resumes_into_model_not_stale_final_or_approval(draft_case):
    f = draft_case
    current_native_profiles(f)
    driver = Driver(coordinator=[final()])
    assert (await run(f.ws, driver))['status'] == 'needs_human'
    wait = f.ws.store.get(WAIT)
    root_task = deepcopy((await snapshot(f.ws, driver)).values['report_current_user_task'])
    assert root_task and root_task['text']
    cap_before = deepcopy(f.ws.store.get('commission_planning_rejections'))
    note = 'Synthetic operator guidance: continue planning only; do not approve the report.'
    f.ws.decide_issue(wait['issue_id'], note, resolved=False)
    def resumed(messages):
        assert any(note in str(m.content) for m in messages), 'Saved operator note must reach actual resumed model input.'
        return question('after-guidance')
    fresh = Driver(coordinator=[final(), resumed])
    result = await run(Workspace(Store(f.ws.store.root)), fresh)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(fresh.calls) == 1
    assert plan_authority.decision_ref(f.ws.store) is None
    assert not f.cs.list_objects('CommissionDecision')
    assert f.ws.store.get('commission_planning_rejections') == cap_before
    state = await snapshot(f.ws, fresh)
    assert state.values['report_current_user_task'] == root_task, 'Operator continuation must not replace the original report goal.'
    assert state.interrupts[0].value['issue_id'] != wait['issue_id']


async def test_raw_resume_cannot_authorize_terminal_planning_wait(draft_case):
    f = draft_case
    current_native_profiles(f)
    assert (await run(f.ws, Driver(coordinator=[final()])))['status'] == 'needs_human'
    wait = f.ws.store.get(WAIT)
    fresh = Driver(coordinator=[])
    async with deep_runtime.project_agent(f.ws, fresh) as agent:
        with pytest.raises(ActionRejected, match='(?i)(operator|resume|decision)'):
            await agent.ainvoke(Command(resume='Untrusted raw resume text.'),
                                {'configurable': {'thread_id': 'report'}})
    assert not fresh.calls
    assert f.ws.store.get(WAIT)['issue_id'] == wait['issue_id']
    issue = next(i for i in issue_state.get_report_issues(f.ws.store) if i['id'] == wait['issue_id'])
    assert not issue.get('decision_origin')


async def test_new_terminal_same_words_after_guidance_requires_new_wait(draft_case):
    f = draft_case
    current_native_profiles(f)
    assert (await run(f.ws, Driver(coordinator=[final('final-first')])))['status'] == 'needs_human'
    first = f.ws.store.get(WAIT)['issue_id']
    f.ws.decide_issue(first, 'Continue investigating; no plan approval.', resolved=False)
    fresh = Driver(coordinator=[final('final-first'), final('final-second')])
    result = await run(f.ws, fresh)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(fresh.calls) == 1
    assert f.ws.store.get(WAIT)['issue_id'] != first
    assert plan_authority.decision_ref(f.ws.store) is None


async def test_explicit_pausing_question_uses_existing_wait(draft_case):
    f = draft_case
    current_native_profiles(f)
    driver = Driver(coordinator=[question()])
    result = await run(f.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == 1 and f.ws.store.get(WAIT) is None
    state = await snapshot(f.ws, driver)
    assert state.interrupts and len(issue_state.get_report_issues(f.ws.store)) == 1


async def test_invalid_tool_call_is_feedback_not_a_terminal_completion(draft_case):
    f = draft_case
    current_native_profiles(f)
    malformed = AIMessage(content='', invalid_tool_calls=[{
        'name': 'add_section', 'id': 'malformed-planning', 'args': '{', 'error': 'Incomplete JSON'}])
    driver = Driver(coordinator=[malformed, question()])
    result = await run(f.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == 2 and f.ws.store.get(WAIT) is None
    assert f.ws.store.get('commission_planning_rejections')['consecutive_rejections'] == 1
    state = await snapshot(f.ws, driver)
    feedback = next(m for m in state.values['messages'] if isinstance(m, ToolMessage) and m.tool_call_id == 'malformed-planning')
    assert feedback.status == 'error' and 'INVALID_TOOL_ARGUMENT_JSON' in feedback.content


async def test_current_owner_confirmed_plan_does_not_enter_planning_wait(draft_case):
    f = draft_case
    current_native_profiles(f)
    approval(f)
    with f.cs.store.connect() as db:
        commission_plan._confirmed(f.cs, db)
    driver = Driver(coordinator=[final()])
    result = await run(f.ws, driver)
    assert result['last_error'] is None, result
    assert result['status'] != 'needs_human' and f.ws.store.get(WAIT) is None
    assert len(driver.calls) == 1


async def test_disabled_planning_contract_keeps_existing_terminal_behavior(draft_case):
    f = draft_case
    current_native_profiles(f)
    manifest = dict(f.ws.store.manifest)
    manifest.pop('commission_planning_contract')
    f.ws.store.set('manifest', manifest)
    driver = Driver(coordinator=[final()])
    result = await run(f.ws, driver)
    assert result['last_error'] is None, result
    assert result['status'] != 'needs_human' and f.ws.store.get(WAIT) is None
    assert len(driver.calls) == 1

@pytest.mark.parametrize('changed', ['plan', 'requirements'])
async def test_old_owner_confirmation_cannot_finish_after_current_version_changes(draft_case, changed):
    from report_agent import commission_requirements
    f = draft_case
    current_native_profiles(f)
    approval(f)
    old_confirmation = plan_authority.decision_ref(f.ws.store)
    old_plan = plan_authority.plan_ref(f.ws.store)
    old_requirements = requirements_ref(f.ws.store)
    if changed == 'plan':
        revised = deepcopy(commission_planning.read_draft(f.cs, f.co)['plan'])
        revised['open_questions'].append('A newly recorded factual question requires owner review.')
        commission_plan.save_plan(f.cs, f.co, 'h33-revised-plan', revised)
        assert plan_authority.plan_ref(f.ws.store) != old_plan
    else:
        record = commission_requirements.read_requirements(f.cs)
        items = deepcopy(record['payload']['items'])
        items[0]['interpretation'] += ' A revised interpretation awaits owner review.'
        commission_requirements.propose_requirements(f.cs, f.co, 'h33-revised-requirements', record['ref'], items)
        assert requirements_ref(f.ws.store) != old_requirements
    assert f.cs.read(old_confirmation)['payload']['approved'] is True
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            commission_plan._confirmed(f.cs, db)
    driver = Driver(coordinator=[final()])
    result = await run(f.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == 1
    state = await snapshot(f.ws, driver)
    assert state.interrupts[0].value['issue_id'] == f.ws.store.get(WAIT)['issue_id']
    assert plan_authority.decision_ref(f.ws.store) == old_confirmation


async def test_planning_terminal_guard_is_registered_only_once_for_coordinator(draft_case, monkeypatch):
    from report_agent import planning_guard
    f = draft_case
    current_native_profiles(f)
    original = planning_guard.PlanningGuard
    registrations = []
    class ObservedGuard(original):
        def __init__(self, workspace):
            registrations.append(workspace.store.root)
            super().__init__(workspace)
    monkeypatch.setattr(planning_guard, 'PlanningGuard', ObservedGuard)
    driver = Driver(coordinator=[])
    async with deep_runtime.project_agent(f.ws, driver):
        assert len(registrations) == 1
    assert {'coordinator', 'writer', 'reviewer', 'layout'} <= set(driver.created)
    assert not driver.calls
