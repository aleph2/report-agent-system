"""Actual native task/tool channels with scripted decisions; no autonomy claim."""
from report_agent import report_state
import json
from support.task_state_contract import current_task

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.content_delivery import current_delivery
from report_agent.deep_runtime import build_agent
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call
from test_deep_runtime import Driver, call, invoke, observation
from test_reviewer_native_profile import candidate


async def test_native_review_feedback_correction_save_return_and_explicit_adoption(case):
    cs, output, criteria, original = prepared(case)
    cs.store.set('context_policy', 'stateful-tools-v2')
    ws = Workspace(cs.store)
    assigned = {}
    saved = []
    def public_state(messages):
        return current_task(messages)
    def read_body(messages):
        assigned.update(public_state(messages)['assignment'])
        assigned['review_requirements'] = assigned['review_scope_inventory']['scopes']
        basis = assigned['review_commission_basis']
        assert basis['original_requirement_refs'] == original and len(basis['criterion_refs']) == 7
        assert assigned['review_requirements'][0]['required_checks'] == [cs.read(criteria[0])['payload']['expected_outcome']]
        return invoke('read_context', target_ref=output['refs']['a-body'])
    def submission(messages, *, valid):
        from test_review_message import message
        if valid:
            failed = observation(messages, 'submit_review')
            assert not failed['ok'] and failed['code'] == 'REVIEW_SCOPE_SELECTOR_INVALID'
        return AIMessage('', tool_calls=[call('submit_review', message(assigned_scope_index=0 if valid else 99),
            'corrected-submit' if valid else 'first-submit')])
    def returned(messages):
        result = observation(messages, 'submit_review')
        assert result['ok']
        saved.append(result)
        return AIMessage(json.dumps(result))
    def choose_delivery(messages):
        tasks = public_state(messages)['review_tasks']['tasks']
        task = tasks[0]
        assert task['review_commission_basis']['criterion_count'] == 7
        exported = observation(messages, 'export_content_snapshot')['result']['export_ref']
        return invoke('select_content_delivery', snapshot_ref=task['snapshot_ref'], export_ref=exported,
            review_basis_assignment_ref=task['task_ref'], review_assignment_refs=[task['task_ref']])
    def finish(messages):
        assert observation(messages, 'select_content_delivery')['ok']
        return AIMessage('Preserved scoped fixture result; not engineering acceptance.')
    request = review_call(criteria, scope={'kind':'mapped','items':[{'criterion_ref':criteria[0],
        'target_ref':output['refs']['a'], 'assessment_kind':'content'}]})
    from support.flat_task_fixture import task_arguments
    request['args'] = task_arguments(cs, case[1], request['args'])
    driver = Driver(coordinator=[AIMessage('', tool_calls=[{**request, 'type':'tool_call'}]),
        invoke('export_content_snapshot', deliverable={
            'kind':'deliverable','operation_id':'published'}), choose_delivery, finish],
        reviewer=[read_body, lambda m:submission(m,valid=False),
            lambda m:submission(m,valid=True), returned])
    graph = build_agent(ws, driver, None)
    result = await graph.ainvoke({'messages':[HumanMessage('Synthetic scoped verification only.')]})
    assert saved and result['messages'][-1].content.startswith('Preserved scoped')
    assert len(cs.list_objects('ReviewRecord')) == 1
    delivery = current_delivery(cs.store)
    assert len(delivery['items']) == 1 and delivery['overall_verdict'] is None
    assert len(delivery['unassigned_criterion_refs']) == 6
    attempts = [e['data'] for e in cs.store.events() if e['kind']=='native_delegation_reserved']
    assert len(attempts) == 1 and attempts[0]['native_tool_call_id'] == request['id']
    messages = [m for role, _, batch in driver.calls if role=='reviewer' for m in batch if isinstance(m,ToolMessage)]
    assert any(m.status=='error' and 'REVIEW_SCOPE_SELECTOR_INVALID' in m.content for m in messages)
    from pathlib import Path
    destination = case[0].store.root / 'native-protocol-evidence.json'
    record, = cs.list_objects('ReviewRecord')
    destination.write_text(json.dumps({'synthetic_scripted_protocol_only':True,
        'native_intent':request['id'], 'review_ref':record['ref'], 'task_id':record['task_id'],
        'snapshot_ref':record['payload']['snapshot_ref'], 'basis_digest':assigned['review_commission_basis']['digest'],
        'scope_id':assigned['review_requirements'][0]['scope_id'], 'delivery':report_state.selected_delivery(cs.store),
        'reviewer_public_frames':[[{'type':m.type, 'content':m.content,
            **({'tool_calls':m.tool_calls} if isinstance(m,AIMessage) else {})} for m in batch]
            for role, _, batch in driver.calls if role=='reviewer'],
        'semantic_acceptance':False},ensure_ascii=False,indent=2),encoding='utf-8')
