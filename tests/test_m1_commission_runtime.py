"""The commission checkpoint must survive native tool and delegation boundaries."""
from report_agent import report_state
from report_agent import issue_state
from copy import deepcopy
import json

import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from test_bounded_review import Model
from test_m1_commission_plan import api, approve, commission, save, unapproved_writer, writer
from test_m1_commission_coverage import completed_objects, content


def configure(fixture, **fields):
    if fields.get('review_interface_profile') == 'review-interfaces-v4':
        fields = {'review_execution_mode': 'native-reviewer-v2',
            'review_entrypoint': 'delegated-reviewer-v1',
            'delegation_prompt_profile': 'separate-description-v1',
            'operation_identity_profile': 'native-tool-runtime-v1', **fields}
    fixture.ws.store.set('manifest', {**fixture.ws.store.manifest, **fields})


def task(identifier='native-writer', **fields):
    return {'id': identifier, 'name': 'task', 'args': {
        'description': 'Write the confirmed chapter 4.', 'subagent_type': 'writer', **fields}}


def registered(fixture, role):
    from report_agent.deep_runtime import business_tools
    tools = business_tools(fixture.ws, role, None, Model('{}'))
    return {getattr(tool, 'name', None) or tool.__name__: tool for tool in tools}


def native_tool(value):
    return value if isinstance(value, StructuredTool) else StructuredTool.from_function(value)


@pytest.mark.parametrize('role', ['coordinator', 'writer'])
def test_direct_content_commit_cannot_bypass_unanswered_checkpoint(commission, role):
    saved = save(commission)
    actor = commission.co
    if role == 'writer':
        with pytest.raises(ActionRejected, match='COMMISSION_CHECKPOINT_CONFIRMATION_REQUIRED'):
            writer(commission, saved)
        actor = unapproved_writer(commission, saved)
    with pytest.raises((ActionForbidden, ActionRejected), match='(?i)(commission|checkpoint)'):
        commission.cs.commit(actor, 'premature-commit', [
            {'client_key': 'body', 'type': 'ContentNode', 'payload': content('Premature report body.')}])
    assert not commission.cs.list_objects('ContentNode')


def test_generic_operator_prose_is_not_structured_commission_approval(commission):
    saved = save(commission)
    checkpoint = api().request_checkpoint(commission.ws)
    from report_agent import legacy_state
    with pytest.raises(ActionRejected, match='TYPED_CHECKPOINT_REQUIRES_COMMISSION_REPLY'):
        commission.ws.decide_issue(checkpoint['issue_id'], 'approved', resolved=True)
    generic = commission.ws.issue('requirement', 'Clarify an unrelated label.', [])
    commission.ws.decide_issue(generic['id'], 'approved', resolved=True)
    issues = {issue['id']: issue for issue in issue_state.get_report_issues(commission.ws.store)}
    assert issues[generic['id']]['decision'] == 'approved' and issues[generic['id']]['resolved']
    assert not issues[checkpoint['issue_id']]['resolved']
    actor = unapproved_writer(commission, saved)
    with commission.ws.store.connect() as db, pytest.raises(ActionRejected, match='COMMISSION_CHECKPOINT_CONFIRMATION_REQUIRED'):
        api().assert_writing_allowed(commission.cs, db, actor)


def test_writer_section_schema_and_request_assembly_preserve_selection(commission):
    from report_agent.co_review_message import CoTaskMessage
    from report_agent.live_messages import _assemble_task
    request = task(section_ids=['4', '5'])
    value = CoTaskMessage.model_validate(request['args'])
    assert value.section_ids == ['4', '5']
    assert CoTaskMessage.model_validate(task()['args'])
    assembled = _assemble_task(commission.ws, commission.co, {'resources': []}, request)
    assert assembled['args']['section_ids'] == ['4', '5']


@pytest.mark.parametrize('fields', [
    {'subagent_type': 'layout', 'snapshot_scope': 'snapshot', 'section_ids': ['4']},
    {'subagent_type': 'reviewer', 'snapshot_scope': 'snapshot', 'commission_criterion_scopes': ['basis'],
     'review_scope': 'whole_content', 'section_ids': ['4']},
    {'resume_task_scope': 'prior-task', 'section_ids': ['4']}])
def test_section_selection_is_writer_only_and_cannot_change_continuation(fields):
    from report_agent.co_review_message import CoTaskMessage
    with pytest.raises(ValidationError):
        CoTaskMessage.model_validate(task(**fields)['args'])


@pytest.mark.parametrize('state', ['unconfirmed', 'missing-sections', 'unknown-section'])
def test_native_writer_delegation_requires_confirmed_valid_sections(commission, state):
    configure(commission, review_interface_profile='review-interfaces-v4')
    saved = save(commission)
    if state != 'unconfirmed':
        approve(commission, saved)
    fields = {} if state == 'missing-sections' else {'section_ids': ['not-in-plan'] if state == 'unknown-section' else ['4']}
    with pytest.raises((ActionForbidden, ActionRejected), match='(?i)(commission|checkpoint|section)'):
        with delegated_task(commission.ws, 'coordinator', task(**fields)):
            pytest.fail('Invalid assignment reached the native executor.')


def test_native_writer_task_binds_current_plan_and_refuses_stale_resume(commission):
    configure(commission, review_interface_profile='review-interfaces-v4')
    saved = save(commission)
    approve(commission, saved)
    with delegated_task(commission.ws, 'coordinator', task(section_ids=['4'])) as (native, actor):
        assert 'section_ids' not in native['args'], 'Business selection is not an SDK task argument.'
        record = commission.cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
        assert record['payload']['commission_plan_ref'] == saved['plan_ref']
        assert record['payload']['section_ids'] == ['4']
    with delegated_task(commission.ws, 'coordinator', task('resume-current', resume_content_task_id=actor.task_id)) as (_, resumed):
        assert resumed == actor
    revised = deepcopy(commission.plan)
    revised['open_questions'] = ['Confirm the revised source interpretation.']
    current = save(commission, revised, operation='new-plan-version')
    approve(commission, current)
    with pytest.raises((ActionForbidden, ActionRejected), match='(?i)(commission|plan|task)'):
        with delegated_task(commission.ws, 'coordinator', task('resume-stale', resume_content_task_id=actor.task_id)):
            pytest.fail('A stale assignment reached the native executor.')


def test_actual_agent_registry_exposes_commission_actions_but_not_operator_reply(commission):
    expected = {'save_commission_plan', 'read_commission_plan', 'request_commission_confirmation'}
    coordinator = registered(commission, 'coordinator')
    assert expected <= coordinator.keys()
    assert {'read_commission_plan', 'record_assessment_outcome'} <= registered(commission, 'writer').keys()
    for role in ('coordinator', 'writer', 'reviewer', 'layout'):
        names = registered(commission, role)
        assert not any('reply' in name or 'approve_commission' in name or 'decide_issue' in name for name in names)
    configure(commission, commission_checkpoint_required=False)
    assert not expected.intersection(registered(commission, 'coordinator'))
    assert 'record_assessment_outcome' not in registered(commission, 'writer')


def test_commission_save_and_read_work_through_actual_tool_schema(commission):
    tools = registered(commission, 'coordinator')
    saved = native_tool(tools['save_commission_plan']).invoke({'operation_id': 'tool-save', 'plan': commission.plan})
    assert saved['result']['plan_ref'] == api().read_plan(commission.ws.store)['ref']
    result = native_tool(tools['read_commission_plan']).invoke({})
    assert result['ref'] == saved['result']['plan_ref']
    assert result['payload']['objects'] == commission.plan['objects']


def test_native_commission_tool_injects_call_identity_and_replays_exact_receipt(commission):
    from report_agent.operation_identity import write_id
    configure(commission, review_interface_profile='review-interfaces-v4')
    tools = registered(commission, 'coordinator')
    tool = tools['save_commission_plan']
    assert isinstance(tool, StructuredTool)
    schema = tool.tool_call_schema.model_json_schema()
    assert 'operation_id' not in schema['properties']
    assert not any('reply' in name or 'approve_commission' in name for name in tools)
    call = {'name': 'save_commission_plan', 'id': 'native-plan-call', 'type': 'tool_call',
            'args': {'plan': commission.plan}}
    first = json.loads(tool.invoke(call).content)
    expected = write_id(commission.co.id, 'save_commission_plan', 'native-plan-call')
    assert first['operation_id'] == expected
    receipt = commission.cs.receipt(commission.co, expected)
    assert receipt['response']['result']['plan_ref'] == first['result']['plan_ref']
    count = len(commission.cs.list_objects())
    again = json.loads(tool.invoke(call).content)
    assert again['result']['plan_ref'] == first['result']['plan_ref']
    assert len(commission.cs.list_objects()) == count
    assert api().read_plan(commission.ws.store)['ref'] == first['result']['plan_ref']


def test_confirmation_tool_reuses_native_human_interrupt_and_same_issue(commission, monkeypatch):
    from report_agent import deep_runtime
    save(commission)
    checkpoint = api().request_checkpoint(commission.ws)
    seen = []
    class ReachedInterrupt(BaseException):
        pass
    def interrupt(value):
        seen.append(value)
        raise ReachedInterrupt
    monkeypatch.setattr(deep_runtime, 'interrupt', interrupt)
    tool = native_tool(registered(commission, 'coordinator')['request_commission_confirmation'])
    with pytest.raises(ReachedInterrupt):
        tool.invoke({})
    assert len(seen) == 1 and seen[0]['issue_id'] == checkpoint['issue_id']


def test_project_state_cannot_project_four_of_five_objects_as_completed(commission):
    from report_agent.knowledge_state import project_state
    saved = save(commission)
    approve(commission, saved)
    _, _, snapshot = completed_objects(commission, saved)
    commission.ws.store.set('report_status', 'completed')
    report_state.set_content_delivery(commission.ws.store, {'snapshot_ref': snapshot['ref'],
        'export_ref': {'type': 'ExportArtifact', 'id': 'unreviewed-export', 'version': 1}})
    projected = project_state(commission.ws)
    assert projected['status'] == projected['execution_status'] == 'incomplete'
    coverage = projected['content_current_review']['commission_coverage']
    assert coverage['complete'] is False
    assert {item['object_id'] for item in coverage['missing_objects']} == {'S5'}
