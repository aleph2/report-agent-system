"""Offline delivery-wait mechanics in fresh cases; no model or export calls."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from report_agent import delivery_guard as guard, plan_authority
from support.plan_fixture import install_confirmed_plan
from test_m1_commission_plan import commission
from report_agent.errors import ActionRejected
from report_agent.store import Store


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path / 'case')
    store.set('manifest', {'assembly_contract': 'system-assembler-v1'})
    store.set('report_status', 'running')
    return SimpleNamespace(store=store)


def result(workspace, identity, *, role='coordinator', actor_id=None, rejected=True,
           tool='export_content_snapshot', changed=False, error_code='EXPORT_TEST_REJECTED'):
    return guard.record_export_result(workspace, role, tool, identity, rejected=rejected,
        error_code=error_code, changed=changed, actor_id=actor_id)


def wait(workspace):
    for i in range(3):
        state = result(workspace, 'failed-' + str(i))
    return state


@pytest.fixture
def approved_workspace(commission):
    install_confirmed_plan(commission)
    ws = commission.ws
    ws.store.set('manifest', {**ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    ws.store.set('report_status', 'running')
    return ws


def test_three_export_failures_pause_once_and_preserve_approval(approved_workspace):
    workspace = approved_workspace
    original = plan_authority.decision_ref(workspace.store)
    assert original
    previous_issues = workspace.store.get('report_issues', [])
    assert result(workspace, 'one')['consecutive_rejections'] == 1
    assert result(workspace, 'two')['waiting'] is False
    state = result(workspace, 'three')
    assert state['waiting'] and state['consecutive_rejections'] == 3
    assert workspace.store.get('report_status') == 'waiting_for_human'
    issues = workspace.store.get('report_issues')
    assert issues[:-1] == previous_issues
    assert issues[-1]['category'] == 'system_failure' and issues[-1]['id'] == state['issue_id']
    assert plan_authority.decision_ref(workspace.store) == original
    assert result(workspace, 'four')['issue_id'] == state['issue_id']
    assert workspace.store.get('report_issues') == issues


def test_actor_and_native_call_identity_deduplicate_across_reopen(workspace):
    assert result(workspace, 'same', actor_id='writer-A')['consecutive_rejections'] == 1
    workspace.store = Store(workspace.store.root)
    assert result(workspace, 'same', actor_id='writer-A')['consecutive_rejections'] == 1
    state = result(workspace, 'same', actor_id='writer-B', role='writer')
    assert state['consecutive_rejections'] == 2
    assert state['failures'][-1] == {'actor_id': 'writer-B', 'role': 'writer',
        'native_call_id': 'same', 'error_code': 'EXPORT_TEST_REJECTED'}


def test_only_a_new_successful_export_resets_the_count(workspace):
    result(workspace, 'one')
    for tool in ['read_context', 'save_section_prose', 'export_content_workbook']:
        assert result(workspace, tool, tool=tool, rejected=False, changed=True)['consecutive_rejections'] == 1
    assert result(workspace, 'cached', rejected=False)['consecutive_rejections'] == 1
    assert result(workspace, 'new', rejected=False, changed=True)['consecutive_rejections'] == 0
    assert result(workspace, 'two')['consecutive_rejections'] == 1
    assert result(workspace, 'new', rejected=False, changed=True)['consecutive_rejections'] == 1


def test_system_delivery_counts_and_success_cannot_clear_latched_wait(workspace):
    for i in range(3):
        state = result(workspace, str(i), tool='request_system_delivery')
    again = result(workspace, 'sibling-success', rejected=False, changed=True)
    assert again['waiting'] and again['issue_id'] == state['issue_id']
    assert again['consecutive_rejections'] == 3


@pytest.mark.parametrize('contract', [None, 'legacy', 'system-assembler-v2'])
def test_other_contracts_are_unchanged(workspace, contract):
    workspace.store.set('manifest', {'assembly_contract': contract})
    for i in range(4):
        state = result(workspace, str(i))
    assert state == {'consecutive_rejections': 0, 'waiting': False}
    assert workspace.store.get(guard.KEY) is None
    assert workspace.store.get('report_status') == 'running'
    guard.require_resumed(workspace)


@pytest.mark.parametrize('identity', [None, '', '  ', 7])
def test_missing_native_call_identity_is_rejected(workspace, identity):
    with pytest.raises(ActionRejected, match='DELIVERY_NATIVE_CALL_ID_REQUIRED'):
        result(workspace, identity)
    assert workspace.store.get(guard.KEY) is None


def test_invalid_json_is_preserved_as_an_export_rejection_code(workspace):
    state = result(workspace, 'bad-json', error_code='INVALID_TOOL_ARGUMENT_JSON')
    assert state['failures'][-1]['error_code'] == 'INVALID_TOOL_ARGUMENT_JSON'
    state = result(workspace, 'unsafe-message', error_code='Private source paragraph. Do not persist.')
    assert state['failures'][-1]['error_code'] == 'EXPORT_REJECTED'


@pytest.mark.parametrize('decision', [None, [], {}, {'decision': 'approve_plan', 'note': 'x'},
    {'decision': 'resume_delivery', 'note': ' '}, {'decision': 'resume_delivery', 'note': 5},
    {'decision': 'resume_delivery', 'note': 'x', 'extra': True}])
def test_resume_requires_exact_typed_decision(workspace, decision):
    state = wait(workspace)
    with pytest.raises(ActionRejected, match='DELIVERY_RESUME_NOTE_REQUIRED'):
        guard.resume_delivery(workspace, state['issue_id'], decision)
    assert workspace.store.get(guard.KEY)['waiting']


def test_exact_resume_is_idempotent_and_does_not_approve_or_erase_failures(approved_workspace):
    workspace = approved_workspace
    original = plan_authority.decision_ref(workspace.store)
    assert original
    state = wait(workspace)
    decision = {'decision': 'resume_delivery', 'note': 'Reviewed export failures and corrected the cause.'}
    with pytest.raises(ActionRejected, match='DELIVERY_RESUME_ISSUE_MISMATCH'):
        guard.resume_delivery(workspace, 'other-issue', decision)
    resolved = guard.resume_delivery(workspace, state['issue_id'], decision)
    assert resolved['resolved'] and resolved['decision_origin'] == 'operator'
    assert guard.resume_delivery(workspace, state['issue_id'], decision) == resolved
    state = workspace.store.get(guard.KEY)
    assert not state['waiting'] and state['consecutive_rejections'] == 0
    assert len(state['failures']) == 3
    assert plan_authority.decision_ref(workspace.store) == original
    assert result(workspace, 'next')['consecutive_rejections'] == 1
    with pytest.raises(ActionRejected, match='DELIVERY_WAIT_NOT_ACTIVE'):
        guard.resume_delivery(workspace, resolved['id'], {**decision, 'note': 'Different reply'})


def test_raw_resume_does_not_clear_wait_and_template_names_typed_action(workspace, monkeypatch):
    state = wait(workspace)
    payloads = []
    monkeypatch.setattr(guard, 'interrupt', lambda value: payloads.append(value))
    with pytest.raises(ActionRejected, match='DELIVERY_OPERATOR_RESUME_REQUIRED'):
        guard.require_resumed(workspace)
    template = json.loads((workspace.store.root / payloads[0]['reply_template']).read_text())
    assert template['decision_shape'] == {'decision': 'resume_delivery', 'note': ''}
    assert template['issue_id'] == state['issue_id']
    assert template['consecutive_rejections'] == 3
    assert 'commission-reply' in template['reply_command']
    assert state['issue_id'] in template['reply_command']
    assert payloads[0]['kind'] == 'delivery_export_failures'


def test_middleware_stops_before_model_handler(workspace, monkeypatch):
    wait(workspace)
    monkeypatch.setattr(guard, 'interrupt', lambda value: None)
    invoked = []
    async def handler(request):
        invoked.append(request)
    middleware = guard.DeliveryGuard(workspace)
    with pytest.raises(ActionRejected, match='DELIVERY_OPERATOR_RESUME_REQUIRED'):
        asyncio.run(middleware.abefore_model({}, None))
    with pytest.raises(ActionRejected, match='DELIVERY_OPERATOR_RESUME_REQUIRED'):
        asyncio.run(middleware.awrap_model_call('request', handler))
    assert invoked == []


def test_native_checkpoint_requires_persisted_operator_resume(workspace):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import Command
    state = wait(workspace)
    visited = []
    def proceed(value):
        guard.require_resumed(workspace)
        visited.append('model boundary reached')
        return {'passed': True}
    graph = StateGraph(dict)
    graph.add_node('delivery', proceed)
    graph.add_edge(START, 'delivery')
    graph.add_edge('delivery', END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'offline-delivery-guard'}}
    interrupted = app.invoke({}, config)
    assert interrupted['__interrupt__'][0].value['issue_id'] == state['issue_id']
    assert visited == []
    with pytest.raises(ActionRejected, match='DELIVERY_OPERATOR_RESUME_REQUIRED'):
        app.invoke(Command(resume={'decision': 'resume_delivery'}), config)
    assert visited == [] and workspace.store.get(guard.KEY)['waiting']
    guard.resume_delivery(workspace, state['issue_id'], {'decision': 'resume_delivery', 'note': 'Reviewed the failure cause.'})
    completed = app.invoke(None, config)
    assert completed['passed'] and visited == ['model boundary reached']
