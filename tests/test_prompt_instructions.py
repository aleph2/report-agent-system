"""Offline runtime/protocol tests, not semantic or engineering acceptance."""
import json
from types import SimpleNamespace

import pytest
from support.task_state_contract import current_task
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from report_agent.content_tasks import bound_actor, delegated_task
from report_agent.errors import ActionRejected
from report_agent.prompt_instructions import (
    configure_report, instruction_context, release_instruction, save_instruction,
)
from report_agent.store import Store, digest
from report_agent.task_context import TaskContext
from report_agent.workspace import Workspace
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.fixture
def configured(ws):
    seed(ws)
    ws.store.set('context_policy', 'stateful-tools-v1')
    configure_report(ws.store, 'report-a')
    return ws


def candidate(ws, id='policy', **changes):
    payload = {'id': id, 'scope': 'system', 'topic': 'report-voice',
               'text': 'Fixture policy: retain source uncertainty.',
               'source_decision': 'Offline test only', **changes}
    return save_instruction(ws.store, payload)


def release(ws, record, expected=None):
    return release_instruction(ws.store, record['ref']['id'], record['ref']['version'],
                               expected_active=expected, reason='Offline fixture release')


def packet(ws, role='coordinator', task_id=None):
    return instruction_context(ws.store, role, task_id=task_id)


async def receive(ws, role='coordinator', history=None, failure=False):
    seen = []
    async def handler(request):
        seen.append(request)
        if failure:
            raise TimeoutError('Offline unknown response')
        return AIMessage(content='Offline response only')
    request = SimpleNamespace(messages=history or [HumanMessage(content='Ordinary goal')],
                              system_message=SystemMessage(content='Existing role responsibilities'))
    request.state = {'messages': request.messages}
    request.override = lambda **kw: SimpleNamespace(**{**request.__dict__, **kw})
    await TaskContext(ws, role).awrap_model_call(request, handler)
    context = current_task(seen[0])
    return context, seen[0]


async def test_system_inheritance_in_actual_coordinator_and_writer_inputs(configured):
    record = candidate(configured, text='Exact policy; '+('unchanged wording; '*200)+'TAIL')
    assert packet(configured)['effective'] == []  # Saving is not release.
    release(configured, record)
    before = digest(configured.store.manifest)
    coordinator, request = await receive(configured)
    assert coordinator['scoped_instructions']['effective'] == [record]
    assert request.system_message.content[0]['text'] == 'Existing role responsibilities'
    with delegated_task(configured, 'coordinator', {'id': 'writer-a', 'args': {
            'subagent_type': 'writer', 'description': 'Write this assigned paragraph'}}):
        writer, _ = await receive(configured, 'writer')
        assert writer['scoped_instructions']['effective'] == [record]
    assert digest(configured.store.manifest) == before
    events = [e for e in configured.store.events() if e['kind'] == 'prompt_context_offered']
    assert len(events) == 2
    snap = configured.store.get('prompt_context_snapshot:'+events[-1]['data']['snapshot_id'])
    assert snap['scoped_instructions']['effective'][0]['payload']['text'].endswith('TAIL')
    assert snap['system_blocks'][-1]['text'].endswith('}')


def test_report_and_role_isolation_and_private_system_registry(configured, tmp_path):
    a = candidate(configured, 'a', scope='report', report_id='report-a', roles=['writer'])
    b = candidate(configured, 'b', scope='report', report_id='report-b', roles=['writer'])
    for r in (a, b): release(configured, r)
    assert packet(configured)['effective'] == []
    assert packet(configured, 'writer')['effective'] == [a]
    other = Store(tmp_path/'other-project')
    other.initialize(configured.store.manifest)
    other.set('context_policy', 'stateful-tools-v1')
    configure_report(other, 'report-b')
    assert instruction_context(other, 'writer')['effective'] == []
    with pytest.raises(ActionRejected, match='REPORT_BINDING_IMMUTABLE'):
        configure_report(configured.store, 'report-b')


async def test_assignment_identity_is_server_bound(configured):
    with delegated_task(configured, 'coordinator', {'id': 'writer-a', 'args': {
            'subagent_type': 'writer', 'description': 'First assignment'}}):
        actor = bound_actor(configured, 'writer', None)
        r = candidate(configured, 'task-rule', scope='assignment', report_id='report-a',
                      task_id=actor.task_id, roles=['writer'])
        release(configured, r)
        assert (await receive(configured, 'writer'))[0]['scoped_instructions']['effective'] == [r]
    with delegated_task(configured, 'coordinator', {'id': 'writer-b', 'args': {
            'subagent_type': 'writer', 'description': 'Independent assignment'}}):
        assert (await receive(configured, 'writer'))[0]['scoped_instructions']['effective'] == []


async def test_unresolved_conflict_retains_alternatives_and_independent_topics(configured):
    broad = candidate(configured, allow_override_scopes=['report'])
    local = candidate(configured, 'local', scope='report', report_id='report-a',
                      text='Fixture report instruction: different wording.')
    unrelated = candidate(configured, 'units', topic='units', text='Fixture: preserve supplied units.')
    for r in (broad, local, unrelated): release(configured, r)
    context, _ = await receive(configured)
    value = context['scoped_instructions']
    assert value['effective'] == [unrelated]
    assert value['conflicts'][0]['instructions'] == [broad, local]
    assert value['conflicts'][0]['state'] == 'needs_explicit_resolution'
    # Explicit permitted override; not a later-text-wins rule.
    revised = save_instruction(configured.store, {
        **local['payload'], 'overrides': [broad['ref']],
        'source_decision': 'Offline fixture explicit scope decision'}, expected_version=1)
    release(configured, revised, expected=1)
    assert not packet(configured)['conflicts']
    assert packet(configured)['overridden_refs'] == [broad['ref']]
    assert {r['ref']['id'] for r in packet(configured)['effective']} == {'local', 'units'}


def test_locked_policy_cannot_be_overridden(configured):
    broad = candidate(configured)
    with pytest.raises(ActionRejected, match='OVERRIDE_NOT_PERMITTED'):
        candidate(configured, 'local', scope='report', report_id='report-a', overrides=[broad['ref']])


def test_new_parent_version_invalidates_old_override(configured):
    broad = candidate(configured, allow_override_scopes=['report'])
    local = candidate(configured, 'local', scope='report', report_id='report-a',
                      overrides=[broad['ref']], text='Different local fixture instruction')
    release(configured, broad); release(configured, local)
    assert not packet(configured)['conflicts']
    new = save_instruction(configured.store, {**broad['payload'], 'text': 'New parent policy'}, expected_version=1)
    release(configured, new, expected=1)
    assert packet(configured)['conflicts'][0]['instructions'] == [new, local]


async def test_supersession_live_refresh_restart_and_compacted_history(configured):
    first = candidate(configured); release(configured, first)
    stale = [HumanMessage(content='Compacted recollection says the old policy still applies')]
    assert (await receive(configured, history=stale))[0]['scoped_instructions']['effective'] == [first]
    revised = save_instruction(configured.store, {**first['payload'], 'text': 'New exact instruction'}, expected_version=1)
    assert packet(configured)['effective'] == [first]
    release(configured, revised, expected=1)
    reopened = Workspace(Store(configured.store.root))
    context, request = await receive(reopened, history=stale)
    assert context['scoped_instructions']['effective'] == [revised]
    assert request.messages == stale
    release_instruction(reopened.store, 'policy', None, expected_active=2, reason='Withdraw fixture')
    assert (await receive(reopened))[0]['scoped_instructions']['effective'] == []
    assert save_instruction(reopened.store, revised['payload']) == revised
    with pytest.raises(ActionRejected, match='VERSION_CONFLICT'):
        save_instruction(reopened.store, {**revised['payload'], 'text': 'Stale changed instruction'}, expected_version=1)
    with pytest.raises(ActionRejected, match='RELEASE_CONFLICT'):
        release(reopened, first, expected=2)


async def test_handler_failure_saved_as_unknown_without_retry(configured):
    with pytest.raises(TimeoutError): await receive(configured, failure=True)
    events = configured.store.events()
    assert len([e for e in events if e['kind'] == 'prompt_context_offered']) == 1
    assert len([e for e in events if e['kind'] == 'prompt_context_outcome_unknown']) == 1
    assert not any(e['kind'] == 'prompt_context_response_received' for e in events)


@pytest.mark.parametrize('changes', [
    {'scope': 'report'}, {'scope': 'system', 'report_id': 'r'},
    {'scope': 'report', 'report_id': 'r', 'task_id': 't'},
    {'source_decision': ' '}, {'text': ' '}, {'roles': ['writer', 'writer']},
    {'allow_override_scopes': ['system']}, {'tool_permissions': ['write_everything']},
])
def test_malformed_scope_or_permission_fields_rejected(configured, changes):
    with pytest.raises(ValidationError): candidate(configured, **changes)


def test_scope_migration_needs_new_identity(configured):
    first = candidate(configured)
    with pytest.raises(ActionRejected, match='SCOPE_CHANGE_REQUIRES_NEW_ID'):
        save_instruction(configured.store, {**first['payload'], 'scope': 'project'}, expected_version=1)


async def test_unconfigured_workspace_keeps_previous_context_behavior(ws):
    seed(ws)
    assert packet(ws) is None
    # Historical grader paths must not acquire a new opt-in role restriction.
    assert instruction_context(ws.store, 'rubric_grader') is None
    context, _ = await receive(ws)
    assert 'scoped_instructions' not in context
    assert not any(e['kind'].startswith('prompt_context_') for e in ws.store.events())
    with pytest.raises(ActionRejected, match='REQUIRE_TASK_CONTEXT'):
        configure_report(ws.store, 'r')


async def test_native_graph_uses_same_delivery_boundary(configured):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    record = candidate(configured); release(configured, record)
    driver = Driver(coordinator=[AIMessage(content='Offline harness completion, no report acceptance')])
    result = await run_report(configured, driver)
    assert result['last_error'] is None
    assert record['payload']['text'] in str(driver.calls[0][2][0].content)
    assert any(e['kind'] == 'prompt_context_response_received' for e in configured.store.events())
