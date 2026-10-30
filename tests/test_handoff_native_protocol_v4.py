"""Actual native task/tool channels with scripted decisions; no autonomy claim."""
import json
import re

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
        for message in messages:
            if message.type != 'system':
                continue
            blocks = message.content if isinstance(message.content, list) else [message.content]
            for block in blocks:
                text = block.get('text','') if isinstance(block,dict) else block
                for marker in re.finditer(r'\{', text):
                    try:
                        value, _ = json.JSONDecoder().raw_decode(text[marker.start():])
                    except ValueError:
                        continue
                    if isinstance(value,dict) and value.get('origin') == 'server_bound_application_state':
                        return value
        raise AssertionError('No actual public task-state frame was supplied')
    def read_body(messages):
        assigned.update(public_state(messages)['assignment'])
        assigned['review_requirements'] = assigned['review_scope_inventory']['scopes']
        basis = assigned['review_commission_basis']
        assert basis['original_requirement_refs'] == original and len(basis['criterion_refs']) == 7
        assert assigned['review_requirements'][0]['required_checks'] == [cs.read(criteria[0])['payload']['expected_outcome']]
        return invoke('read_context', target_ref=output['refs']['a-body'])
    def submission(messages, *, valid):
        body = observation(messages, 'read_context')['receipt_id']
        raw = candidate(assigned['review_snapshot_ref'], {'root':output['refs']['a'], 'k':criteria[0],
            'support':output['refs']['support']}, [body], verdict='satisfied')
        scope_id = assigned['review_requirements'][0]['scope_id']
        if valid:
            failed = observation(messages, 'submit_review')
            assert not failed['ok'] and failed['code'] == 'REVIEW_ITEM_OUTSIDE_ASSIGNMENT'
            raw['items'][0]['scope_id'] = scope_id
        else:
            raw['items'][0]['scope_id'] = 'not-the-assigned-scope'
        return AIMessage('', tool_calls=[call('submit_review', {'review':raw}, 'corrected-submit' if valid else 'first-submit')])
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
    assert any(m.status=='error' and 'REVIEW_ITEM_OUTSIDE_ASSIGNMENT' in m.content for m in messages)
    from pathlib import Path
    destination = case[0].store.root / 'native-protocol-evidence.json'
    record, = cs.list_objects('ReviewRecord')
    destination.write_text(json.dumps({'synthetic_scripted_protocol_only':True,
        'native_intent':request['id'], 'review_ref':record['ref'], 'task_id':record['task_id'],
        'snapshot_ref':record['payload']['snapshot_ref'], 'basis_digest':assigned['review_commission_basis']['digest'],
        'scope_id':assigned['review_requirements'][0]['scope_id'], 'delivery':cs.store.get('content_delivery'),
        'reviewer_public_frames':[[{'type':m.type, 'content':m.content,
            **({'tool_calls':m.tool_calls} if isinstance(m,AIMessage) else {})} for m in batch]
            for role, _, batch in driver.calls if role=='reviewer'],
        'semantic_acceptance':False},ensure_ascii=False,indent=2),encoding='utf-8')
