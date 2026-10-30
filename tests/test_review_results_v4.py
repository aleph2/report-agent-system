"""Version binding must survive formal saving and independent task accounting."""
from copy import deepcopy

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.content_delivery import current_delivery
from report_agent.content_models import Ref
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.task_supervision import reconcile
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call, task_record
from test_reviewer_native_profile import candidate


def save_case(cs, actor, task, output, criterion, op='review-result', verdict='satisfied'):
    receipt = cs.observe(actor, {'objects': [cs.read(output['refs']['a-body'])]})['receipt_id']
    raw = candidate(task['review_snapshot_ref'], {'root': output['refs']['a'], 'k': criterion,
        'support':output['refs']['support']}, [receipt], verdict=verdict)
    raw['items'][0]['scope_id'] = task['review_requirements'][0]['scope_id']
    return cs.submit_review(actor, op, raw, {})['result']['review_ref']


def test_native_result_is_saved_against_separate_standard_basis(case):
    cs, output, criteria, _ = prepared(case)
    with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])) as (_, actor):
        task = task_record(cs, actor)['payload']
        saved = save_case(cs, actor, task, output, criteria[0])
        assert cs.read(saved)['task_id'] == actor.task_id
        assert reconcile(cs, actor.task_id)['execution_complete'] is True


def test_new_task_does_not_inherit_prior_positive_without_explicit_mapping(case):
    cs, output, criteria, _ = prepared(case)
    with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])) as (_, first):
        old_task = task_record(cs, first)
        saved = save_case(cs, first, old_task['payload'], output, criteria[0])
    copied = review_call(criteria[:1], identity='second',
        standards={'kind': 'assignment_basis', 'assignment_ref': old_task['ref']},
        scope={'kind': 'saved_assignment', 'assignment_ref': old_task['ref']})
    with delegated_task(Workspace(cs.store), 'coordinator', copied) as (_, second):
        task = task_record(cs, second)['payload']
        assert reconcile(cs, second.task_id)['execution_complete'] is False
        cs.confirm_reuse(second, 'adopt-result', saved, task['review_snapshot_ref'],
            'Explicitly rechecked compatibility of this exact fixture.', item_mappings=[{
                'old_item_index': 0, 'new_scope_id': task['review_requirements'][0]['scope_id']}])
        assert reconcile(cs, second.task_id)['execution_complete'] is True
        reuse, = cs.list_objects('ReviewReuse')
        assert reuse['payload']['target_task_ref']['id'] == second.task_id


def test_delivery_adopts_explicit_compatible_tasks_and_keeps_unassigned_basis(case):
    from report_agent.content_export import export_snapshot
    cs, output, criteria, original = prepared(case)
    ws = Workspace(cs.store)
    call = review_call(criteria, scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criteria[0], 'target_ref': output['refs']['a'], 'assessment_kind': 'content'}]})
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        task = task_record(cs, actor)
        save_case(cs, actor, task['payload'], output, criteria[0])
    snapshot = task['payload']['review_snapshot_ref']
    exported = export_snapshot(cs, case[1], 'delivery-export', snapshot)['result']['export_ref']
    select = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'select_content_delivery')
    for operation, adopted in [('draft', []), ('adopted', [task['ref']])]:
        select(operation, Ref(**snapshot), Ref(**exported),
            review_basis_assignment_ref=Ref(**task['ref']), review_assignment_refs=[Ref(**r) for r in adopted])
        result = current_delivery(cs.store)
        assert result['overall_verdict'] is None and result['semantic_coverage_verified'] is False
        assert result['original_requirement_refs'] == original
        assert len(result['unassigned_criterion_refs']) == 6
        assert len(result['items']) == len(adopted)
    assert len(cs.list_objects('DocumentSnapshot')) == 1


def test_draft_selection_without_basis_or_adopted_tasks_is_allowed_but_unassessed(case):
    from report_agent.content_export import export_snapshot
    from test_deliverable_recovery_v4 import declaration, resolve
    cs, co = case[:2]
    declaration(case)
    snapshot = resolve(cs, co, 'draft-bind', {'kind':'deliverable','operation_id':'published'})
    exported = export_snapshot(cs, co, 'unassessed-export', snapshot)['result']['export_ref']
    select = next(t for t in content_tools(Workspace(cs.store),'coordinator') if t.__name__=='select_content_delivery')
    assert select('plain-draft', Ref(**snapshot), Ref(**exported))['ok']
    current = current_delivery(cs.store)
    assert current['review_commission_basis'] is None
    assert current['items'] == [] and current['overall_verdict'] is None
    assert current['semantic_coverage_verified'] is False


def test_model_tool_descriptions_match_v4_reuse_scope_and_delivery_fields(case):
    from report_agent.prompt_sources import load_prompt
    ws = Workspace(case[0].store)
    for role, names in [('coordinator',{'select_content_delivery'}),('reviewer',{'submit_review','confirm_review_reuse'})]:
        tools = {t.__name__:t for t in content_tools(ws,role)}
        for name in names:
            assert load_prompt({'select_content_delivery':'select-content-delivery-v4',
                'submit_review':'native-submit-review-v4','confirm_review_reuse':'native-review-reuse-v4'}[name]).strip() == tools[name].__doc__.strip()

