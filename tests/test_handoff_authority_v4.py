"""Independent review findings become bounded positive and negative regressions."""
from copy import deepcopy

import pytest
from langchain_core.runnables.config import var_child_runnable_config

from report_agent.content_tasks import delegated_task
from report_agent.content_models import Ref
from report_agent.errors import ActionRejected
from report_agent.prompt_instructions import configure_report, save_instruction, release_instruction
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call, task_record
from test_review_results_v4 import save_case
from test_reviewer_native_profile import candidate


def instructions(store, text='Retain actual source uncertainty.'):
    store.set('context_policy', 'stateful-tools-v2')
    configure_report(store, 'fixture-report')
    value = save_instruction(store, {'id':'policy','scope':'system','topic':'uncertainty',
        'text':text,'source_decision':'Synthetic authorized instruction.'})
    release_instruction(store, value['ref']['id'], value['ref']['version'],
        expected_active=None, reason='Synthetic release')


def test_unchanged_effective_instructions_share_basis_but_keep_task_provenance(case):
    cs, _, criteria, _ = prepared(case)
    instructions(cs.store)
    tasks = []
    for name in ['first', 'second']:
        with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1], identity=name)) as (_, actor):
            tasks.append(task_record(cs, actor)['payload'])
    assert tasks[0]['review_commission_basis']['digest'] == tasks[1]['review_commission_basis']['digest']
    assert tasks[0]['scoped_instructions']['task_id'] != tasks[1]['scoped_instructions']['task_id']
    assert tasks[0]['handoff_release_digest'] == tasks[1]['handoff_release_digest']


def test_v4_native_item_must_supply_assigned_scope_id_not_free_prose_fallback(case):
    cs, output, criteria, _ = prepared(case)
    with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])) as (_, actor):
        task = task_record(cs, actor)['payload']
        receipt = cs.observe(actor, {'objects':[cs.read(output['refs']['a-body'])]})['receipt_id']
        raw = candidate(task['review_snapshot_ref'], {'root':output['refs']['a'], 'k':criteria[0],
            'support':output['refs']['support']}, [receipt], verdict='satisfied')
        raw['items'][0]['scope'] = task['review_requirements'][0]['scope_id']
        raw['items'][0].pop('scope_id', None)
        with pytest.raises(ActionRejected, match='V4_ASSIGNED_SCOPE_ID_REQUIRED'):
            cs.submit_review(actor, 'missing-scope', raw, {})
        assert cs.list_objects('ReviewRecord') == []


@pytest.mark.parametrize('bound', [None, {}])
def test_native_v4_metadata_cannot_fall_back_to_mutable_store(case, bound):
    from report_agent.handoff_release import manifest
    metadata = {'report_review_interface_profile':'review-interfaces-v4'}
    if bound is not None:
        metadata['report_handoff_release'] = bound
    marker = var_child_runnable_config.set({'metadata':metadata})
    try:
        with pytest.raises(ActionRejected, match='HANDOFF_RELEASE_REQUIRED'):
            manifest(case[0].store)
    finally:
        var_child_runnable_config.reset(marker)


def test_mapped_export_extent_preserves_actual_artifact_and_rejects_invalid_pages(case):
    from report_agent.content_export import export_snapshot
    from test_deliverable_recovery_v4 import resolve
    cs, output, criteria, _ = prepared(case)
    snapshot = resolve(cs, case[1], 'bind-first', {'kind':'deliverable','operation_id':'published'})
    exported = export_snapshot(cs, case[1], 'export', snapshot)['result']['export_ref']
    extent = {'kind':'export_structure','artifact_ref':exported,'pages':[]}
    call = review_call(criteria[:1], scope={'kind':'mapped', 'items':[{'criterion_ref':criteria[0],
        'target_ref':output['refs']['a'], 'assessment_kind':'export','artifact_refs':[exported], 'extent':extent}]})
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        assert task_record(cs, actor)['payload']['review_requirements'][0]['artifact_check_scopes'] == [{'requirement_index':0, **extent}]
    bad = deepcopy(call)
    bad['id'] = 'invalid-page'
    bad['args']['review']['scope']['items'][0]['extent']['pages'] = [0]
    with pytest.raises(ActionRejected, match='INVALID_CONTRACT'):
        with delegated_task(Workspace(cs.store), 'coordinator', bad):
            pytest.fail('Export extent cannot silently acquire page scope')


def test_full_basis_from_earlier_snapshot_can_select_a_new_draft_without_adopting_old_tasks(case):
    from report_agent.content_export import export_snapshot
    from report_agent.hierarchical_tools import content_tools
    from test_deliverable_recovery_v4 import declaration
    cs, output, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria[:1])) as (_, actor):
        prior = task_record(cs, actor)
    new_snapshot = cs.operation(case[1], 'another-snapshot', {}, lambda db: {'ref':cs._insert(db,
        case[1], 'DocumentSnapshot', cs.read(prior['payload']['review_snapshot_ref'])['payload'])})['result']['ref']
    exported = export_snapshot(cs, case[1], 'another-export', new_snapshot)['result']['export_ref']
    select = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'select_content_delivery')
    saved = select('draft-other-version', Ref(**new_snapshot), Ref(**exported),
        review_basis_assignment_ref=Ref(**prior['ref']), review_assignment_refs=[])
    assert saved['ok']


def test_selecting_narrower_basis_keeps_prior_stronger_tasks_and_negative_evidence(case):
    from report_agent.content_delivery import current_delivery
    from report_agent.content_export import export_snapshot
    from report_agent.hierarchical_tools import content_tools
    cs, output, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    first = review_call(criteria, scope={'kind':'mapped','items':[{
        'criterion_ref':criteria[0], 'target_ref':output['refs']['a'], 'assessment_kind':'content'}]})
    with delegated_task(ws, 'coordinator', first) as (_, actor):
        old_task = task_record(cs, actor)
        negative = save_case(cs, actor, old_task['payload'], output, criteria[0], verdict='not_satisfied')
    with delegated_task(ws, 'coordinator', review_call(criteria[1:2], identity='narrower')) as (_, actor):
        narrow = task_record(cs, actor)
    snapshot = narrow['payload']['review_snapshot_ref']
    exported = export_snapshot(cs, case[1], 'export-narrower', snapshot)['result']['export_ref']
    select = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'select_content_delivery')
    select('narrower-draft', Ref(**snapshot), Ref(**exported),
        review_basis_assignment_ref=Ref(**narrow['ref']), review_assignment_refs=[])
    result = current_delivery(cs.store)
    assert old_task['ref'] in [t['task_ref'] for t in result['prior_basis_tasks']]
    assert negative in [f['review_ref'] for f in result['prior_basis_findings']]
    assert result['items'] == [] and result['overall_verdict'] is None


def test_criterion_set_order_does_not_change_same_intent_or_full_basis(case):
    cs, _, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria)) as (_, actor):
        first = task_record(cs, actor)
    with delegated_task(ws, 'coordinator', review_call(list(reversed(criteria)))) as (_, actor):
        assert task_record(cs, actor) == first
    with delegated_task(ws, 'coordinator', review_call(list(reversed(criteria)), identity='other-intent')) as (_, actor):
        assert task_record(cs, actor)['payload']['review_commission_basis']['digest'] == first['payload']['review_commission_basis']['digest']


def test_changed_effective_instruction_cannot_inherit_old_basis(case):
    cs, _, criteria, _ = prepared(case)
    instructions(cs.store)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria[:1])) as (_, actor):
        first = task_record(cs, actor)
    updated = save_instruction(cs.store, {'id':'policy','scope':'system','topic':'uncertainty',
        'text':'Retain uncertainty and the newly authorized restriction.', 'source_decision':'Synthetic newer decision.'}, expected_version=1)
    release_instruction(cs.store, 'policy', updated['ref']['version'], expected_active=1, reason='New fixture policy')
    inherit = review_call(criteria[:1], identity='new-instruction-intent',
        standards={'kind':'assignment_basis','assignment_ref':first['ref']})
    with pytest.raises(ActionRejected, match='REVIEW_INSTRUCTION_BASIS_CHANGED'):
        with delegated_task(ws, 'coordinator', inherit):
            pytest.fail('New applicable authority cannot masquerade as the old basis')
    with delegated_task(ws, 'coordinator', review_call(criteria[:1], identity='explicit-new-basis')) as (_, actor):
        assert task_record(cs, actor)['payload']['review_commission_basis']['digest'] != first['payload']['review_commission_basis']['digest']


def test_incomplete_saved_basis_is_rejected_even_when_task_marker_is_v4(case):
    cs, _, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria[:1])) as (_, actor):
        payload = deepcopy(task_record(cs, actor)['payload'])
    payload['review_commission_basis']['criteria'] = []
    malformed = cs.operation(case[1], 'host-malformed-fixture', {}, lambda db: {
        'ref':cs._insert(db, case[1], 'DelegatedTask', payload)})['result']['ref']
    with pytest.raises(ActionRejected, match='COMPLETE_REVIEW_BASIS_REQUIRED'):
        with delegated_task(ws, 'coordinator', review_call(criteria[:1], identity='inherit-malformed',
                standards={'kind':'assignment_basis','assignment_ref':malformed})):
            pytest.fail('A marker is not complete original commissioning evidence')


def test_old_task_without_basis_remains_visible_as_unadopted_unfinished_work(case):
    from report_agent.content_delivery import current_delivery
    from report_agent.content_export import export_snapshot
    from report_agent.hierarchical_tools import content_tools
    cs, output, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria[:1])) as (_, actor):
        modern = task_record(cs, actor)
    old = deepcopy(modern['payload'])
    old.pop('review_commission_basis')
    old.pop('review_interface_profile')
    old['review_requirements'][0]['scope_id'] = 'old-unfinished-scope'
    legacy = cs.operation(case[1], 'legacy-task-fixture', {}, lambda db: {
        'ref':cs._insert(db, case[1], 'DelegatedTask', old)})['result']['ref']
    snapshot = modern['payload']['review_snapshot_ref']
    export = export_snapshot(cs, case[1], 'legacy-draft-export', snapshot)['result']['export_ref']
    select = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'select_content_delivery')
    select('select-draft', Ref(**snapshot), Ref(**export),
        review_basis_assignment_ref=Ref(**modern['ref']), review_assignment_refs=[])
    result = current_delivery(cs.store)
    entry = next(t for t in result['prior_basis_tasks'] if t['task_ref'] == legacy)
    assert entry['basis_state'] == 'not_recorded' and entry['adopted'] is False
    assert entry['accounting']['remaining'] and result['items'] == []


def test_review_header_cannot_claim_unassigned_criteria_from_complete_basis(case):
    from test_reviewer_native_profile import candidate
    cs, output, criteria, _ = prepared(case)
    call = review_call(criteria, scope={'kind':'mapped','items':[{
        'criterion_ref':criteria[0], 'target_ref':output['refs']['a'], 'assessment_kind':'content'}]})
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        task = task_record(cs, actor)['payload']
        receipt = cs.observe(actor, {'objects':[cs.read(output['refs']['a-body'])]})['receipt_id']
        raw = candidate(task['review_snapshot_ref'], {'root':output['refs']['a'], 'k':criteria[0],
            'support':output['refs']['support']}, [receipt], verdict='satisfied')
        raw['items'][0]['scope_id'] = task['review_requirements'][0]['scope_id']
        cs.submit_review(actor, 'assigned-only', raw, {})
        raw['criteria_refs'].append(criteria[-1])
        with pytest.raises(ActionRejected, match='REVIEW_CRITERION_OUTSIDE_ASSIGNED_SCOPE'):
            cs.submit_review(actor, 'unassigned-header', raw, {})
        assert len(cs.list_objects('ReviewRecord')) == 1


def test_bound_v4_native_save_ignores_another_graphs_mutable_bounded_mode(case):
    from report_agent.handoff_release import release
    cs, output, criteria, _ = prepared(case)
    marker = var_child_runnable_config.set({'metadata':{'report_review_interface_profile':'review-interfaces-v4',
        'report_handoff_release':release(cs.store.manifest)}})
    try:
        with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])) as (_, actor):
            task = task_record(cs, actor)['payload']
            cs.store.set('manifest', {**cs.store.manifest, 'review_execution_mode':'bounded-tool-v1'})
            saved = save_case(cs, actor, task, output, criteria[0])
            assert cs.read(saved)['payload']['runtime_identity']['review_profile'] == 'native-reviewer-v2'
    finally:
        var_child_runnable_config.reset(marker)


def test_legacy_scope_copy_requires_explicit_criteria_not_inherited_assignment_basis(case):
    cs, _, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    with delegated_task(ws, 'coordinator', review_call(criteria[:1])) as (_, actor):
        modern = task_record(cs, actor)
    old = deepcopy(modern['payload'])
    old.pop('review_commission_basis')
    old.pop('review_interface_profile')
    legacy = cs.operation(case[1], 'legacy-copy-fixture', {}, lambda db: {
        'ref':cs._insert(db, case[1], 'DelegatedTask', old)})['result']['ref']
    scope = {'kind':'saved_assignment','assignment_ref':legacy}
    forbidden = review_call(criteria[:1], identity='inherited-legacy', scope=scope,
        standards={'kind':'assignment_basis','assignment_ref':modern['ref']})
    with pytest.raises(ActionRejected, match='LEGACY_SCOPE_REQUIRES_EXPLICIT_CRITERIA_BASIS'):
        with delegated_task(ws,'coordinator',forbidden):
            pytest.fail('Legacy scopes cannot silently inherit a modern full-basis claim')
    with delegated_task(ws,'coordinator',review_call(criteria[:1], identity='explicit-legacy',scope=scope)) as (_, actor):
        copied = task_record(cs, actor)['payload']['review_requirements'][0]
        assert copied['scope_id'] != old['review_requirements'][0]['scope_id']
