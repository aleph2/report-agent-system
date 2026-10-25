"""Full raw recovery and native protocol integration; scripted, not autonomy."""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from report_agent.content_tasks import delegated_task
from report_agent.decision_state import read_state, compact_context
from report_agent.errors import ActionRejected
from report_agent.task_context import exact_task_context
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call, task_record


def test_co_can_page_all_basis_tasks_beyond_twenty_with_exact_state_digest(case):
    cs, _, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    for index in range(21):
        with delegated_task(ws, 'coordinator', review_call(criteria[:1], identity='review-'+str(index))):
            pass
    context = exact_task_context(ws, 'coordinator')
    assert context['review_tasks']['total'] == 21
    page = read_state(ws, 'coordinator', ['review_tasks','tasks'], offset=20, limit=1,
                      expected_state_digest=context['state_digest'])
    task, = page['value']
    basis = read_state(ws, 'coordinator', ['review_tasks','tasks',20,'review_commission_basis'],
                       expected_state_digest=page['state_digest'])
    assert basis['value'] == task['review_commission_basis']
    assert basis['value']['criterion_refs'] == criteria[:1]
    projected = compact_context(context)['review_tasks']
    assert len(projected['tasks']) == 20 and projected['next_offset'] == 20
    summary = projected['tasks'][0]['review_commission_basis']
    assert summary['complete'] is False and 'criteria' not in summary
    assert summary['read_state_path'] == ['review_tasks','tasks',0,'review_commission_basis']


def test_v4_runtime_review_identity_uses_its_effective_role_prompt(case):
    from report_agent.hierarchical_tools import content_tools, role_prompt
    from report_agent.content_models import ReviewSubmission
    from report_agent.store import digest
    from test_reviewer_native_profile import candidate
    cs, output, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria[:1])) as (_, actor):
        task = task_record(cs, actor)['payload']
        receipt = cs.observe(actor, {'objects':[cs.read(output['refs']['a-body'])]})['receipt_id']
        raw = candidate(task['review_snapshot_ref'], {'root':output['refs']['a'], 'k':criteria[0],
            'support':output['refs']['support']}, [receipt], verdict='satisfied')
        raw['items'][0]['scope_id'] = task['review_requirements'][0]['scope_id']
        submit = next(t for t in content_tools(ws, 'reviewer') if t.__name__ == 'submit_review')
        result = submit('effective-prompt-identity', ReviewSubmission(**raw))
        record = cs.read(result['result']['review_ref'])
        assert record['payload']['runtime_identity']['prompt_hash'] == digest(role_prompt(
            'reviewer', interface_profile='review-interfaces-v4'))
