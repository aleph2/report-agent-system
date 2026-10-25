"""P02: distinguish error feedback, real interruption, and valid follow-up.

Original R01/R02/R03 evidence remains unchanged.  These fixtures establish the
actual native preconditions before checking current-instruction preservation.
"""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import interrupt

from report_agent.deep_runtime import project_agent, run_report
from report_agent.task_context import exact_task_context
from test_agent_duty_repro_resume import goals, wire
from test_bounded_review import review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def evidence(request, **values):
    request.node.user_properties.append(('P02', json.dumps(values, ensure_ascii=False, default=str)))


async def checkpoint(ws, driver):
    async with project_agent(ws, driver) as agent:
        state = await agent.aget_state({'configurable': {'thread_id': 'report'}}, subgraphs=True)
        return {
            'next': list(state.next),
            'interrupts': [{'id': i.id, 'value': i.value} for i in state.interrupts],
            'tasks': [{'name': t.name, 'error': t.error,
                       'interrupts': [{'id': i.id, 'value': i.value} for i in t.interrupts],
                       'state': str(t.state)} for t in state.tasks],
            'messages': wire(state.values.get('messages', [])),
        }


@pytest.mark.parametrize('role', ['writer', 'layout'])
@pytest.mark.parametrize('failed', [False, True], ids=['normal', 'child-timeout'])
async def test_p02_child_error_feedback_is_not_a_root_checkpoint(ws, role, failed, request):
    cs, _, _, snapshot, _ = seed(ws)
    activate(ws)
    _, current = goals(role)
    args = {'subagent_type': role, 'description': current}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    seen = []

    def parent(messages):
        result = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'task')
        seen.append({'status': result.status, 'content': result.content})
        if failed:
            assert result.status == 'error'
            assert 'DELEGATED_EXECUTION_FAILED' in result.content
        else:
            assert result.status == 'success'
            assert 'Child observation complete' in result.content
        return AIMessage(content='Failure/observation retained; no report acceptance.')

    driver = Driver(coordinator=[invoke('task', **args), parent],
                    **{role: [invoke('read_decision_state', path=[]), AIMessage(content='Child observation complete')]})
    if failed:
        driver.fail_once = (role, 1)
    result = await run_report(ws, driver)
    saved = await checkpoint(ws, driver)
    evidence(request, variant={'role': role, 'failed': failed}, result=result,
             checkpoint=saved, parent=seen, calls=[(r, n) for r, n, _ in driver.calls])
    assert len(seen) == 1 and len(cs.list_objects('DelegatedTask')) == 1
    assert result['last_error'] is None
    assert not saved['next'] and not saved['interrupts']
    assert driver.failed is failed


@pytest.mark.parametrize('role', ['writer', 'layout'])
async def test_p02_real_child_interrupt_reenters_with_same_instruction_and_owner(ws, role, request):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    originals = {k: cs.read(v) for k, v in refs.items()}
    _, current = goals(role)
    issue = ws.issue('requirement', 'Synthetic checkpoint fixture: continue this invocation?', [])
    captures = []
    args = {'subagent_type': role, 'description': current}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot

    def suspended(messages):
        before = exact_task_context(ws, role)
        captures.append({'state': deepcopy(before), 'wire': wire(messages)})
        assert current in json.dumps(wire(messages), ensure_ascii=False)
        assert before['current_invocation']['description'] == current
        answer = interrupt({'issue_id': issue['id'], 'kind': 'synthetic_test_checkpoint'})
        captures[-1]['resume_answer'] = answer
        assert answer == 'Continue this synthetic invocation.'
        return AIMessage(content='Resumed same instruction and owner; no file changed.')

    driver = Driver(coordinator=[invoke('task', **args), AIMessage(content='Observation only.')],
                    **{role: [invoke('read_decision_state', path=[]), suspended]})
    first = await run_report(ws, driver)
    pending = await checkpoint(ws, driver)
    evidence(request, phase='before-resume', role=role, result=first,
             checkpoint=pending, captures=captures)
    assert pending['next'] and len(pending['interrupts']) == 1, 'FIXTURE_INVALID: no actual resumable native interrupt'
    assert pending['interrupts'][0]['value']['issue_id'] == issue['id']
    assert pending['tasks'], 'FIXTURE_INVALID: no pending native graph task'
    retained = cs.list_objects('DelegatedTask')
    assert len(retained) == 1 and len(captures) == 1
    ws.decide_issue(issue['id'], 'Continue this synthetic invocation.')
    second = await run_report(ws, driver)
    after = await checkpoint(ws, driver)
    evidence(request, phase='after-resume', role=role, first=first, second=second,
             before=pending, after=after, captures=captures,
             calls=[(r, n) for r, n, _ in driver.calls])
    assert second['last_error'] is None and not after['next'] and not after['interrupts']
    assert len(captures) == 2 and 'resume_answer' in captures[1]
    a, b = [c['state'] for c in captures]
    assert a['actor_id'] == b['actor_id']
    assert a['assignment'] == b['assignment']
    assert a['current_invocation'] == b['current_invocation']
    assert cs.list_objects('DelegatedTask') == retained
    assert {k: cs.read(v) for k, v in refs.items()} == originals


@pytest.mark.parametrize('declared', [False, True], ids=['undeclared-control', 'valid-materials'])
async def test_p02_reviewer_followup_requires_valid_native_material_contract(ws, declared, request):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    call = review_call(snapshot, refs)
    if not declared:
        del call['args']['review_requirements'][0]['required_materials']
    captures, parent_seen = [], []

    def reviewer(messages):
        state = exact_task_context(ws, 'reviewer')
        invocation = state['current_invocation']
        current = invocation['description']
        # Compare actual message text, not Python/JSON representations whose
        # quote escaping changes the observed string (run1 fixture defect).
        texts = [m.content if isinstance(m.content, str) else ''.join(
            block.get('text', '') for block in m.content if isinstance(block, dict)
        ) for m in messages]
        assert current in texts
        if not any(isinstance(m, ToolMessage) and m.name == 'read_task_assignment' for m in messages):
            captures.append({'state': deepcopy(state), 'wire': wire(messages)})
            return invoke('read_task_assignment')
        captures[-1]['reader_response'] = wire(messages)
        return AIMessage(content='Assigned comparison not performed; evidence remains unresolved.')

    def parent(messages):
        m = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'task')
        parent_seen.append({'status': m.status, 'content': m.content})
        return AIMessage(content='Partial or rejected assignment retained.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), parent], reviewer=[reviewer] * 8)
    result = await run_report(ws, driver)
    evidence(request, declared=declared, result=result, captures=captures,
             parent=parent_seen, events=ws.store.events())
    assert result['last_error'] is None and len(parent_seen) == 1
    if not declared:
        assert not captures
        assert parent_seen[0]['status'] == 'error'
        assert 'REQUIRED_REVIEW_MATERIAL_UNRESOLVED' in parent_seen[0]['content']
        return
    assert len(captures) == 2, 'Valid assignment must enter both actual initial and completion-followup calls'
    first, second = [c['state'] for c in captures]
    assert first['assignment'] == second['assignment'] and first['actor_id'] == second['actor_id']
    a, b = first['current_invocation'], second['current_invocation']
    assert a['delegate_operation_id'] == b['delegate_operation_id']
    assert a['description_sha256'] != b['description_sha256']
    assert 'Completion follow-up' in b['description']
    assert cs.list_objects('DelegatedTask')[0]['payload']['goal'] == call['args']['description']
    assert not cs.list_objects('ReviewRecord')
