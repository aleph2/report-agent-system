from copy import deepcopy

import pytest
from report_agent import commission_assertions, commission_plan, commission_planning, commission_requirements, deliverables, plan_authority
from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden, ActionRejected
from test_m1_g3_integration import method_commission
from test_m1_g4_requirements import anchored
from test_m1_g4_planning_steps import resolution_case

def test_writer_cannot_change_owner_scope_or_read_sources_by_claiming_planning(resolution_case):
    f = resolution_case
    writer = Actor('content:writer:assigned-writer', 'writer', 'assigned-writer')
    with pytest.raises(ActionForbidden, match='planning belongs to coordinator'):
        commission_planning.set_requirement_status(f.cs, writer, 'change-requirement', f.parse_anchor['id'], 'required', 'Retain the section.')
    with pytest.raises(ActionForbidden, match='planning belongs to coordinator'):
        commission_planning.read_draft(f.cs, writer)
    with pytest.raises(ActionForbidden, match='checkpoint belongs to coordinator'):
        commission_planning.request_requirements_checkpoint(f.ws, actor=writer)
    with f.cs.store.connect() as db, pytest.raises(ActionForbidden, match='planning source selection belongs to coordinator'):
        deliverables.source_authority(f.cs, db, writer, [f.cs.read(f.scope_ref)], planning=True)
    assert commission_requirements.read_requirements(f.cs)['ref'] == f.before_resolution['ref']
    assert commission_assertions.checkpoint_answer(f.ws.store, 'requirements', f.checkpoint['issue_id']) is None
    issue = commission_plan.reply(f.ws, f.checkpoint['issue_id'], f.resolution)
    record = commission_requirements.read_requirements(f.cs)
    with f.cs.store.connect() as db:
        brief = commission_planning.requirement_lines(f.cs, db, record)
    assert any(f.resolution['resolutions'][0]['note'] in line for line in brief)
    assert record['ref'] == issue['requirements_result_ref']
    assert plan_authority.decision_ref(f.ws.store) is None

def test_reclassification_cannot_rewrite_import_or_apply_owner_answer_to_a_new_version(resolution_case):
    f = resolution_case
    original = f.before_resolution
    reviewed = original['payload']['classifications'][f.parse_anchor['id']]
    classification = {k: reviewed[k] for k in ('anchor_id', 'entry_ids', 'capabilities', 'table_roles')}
    assert commission_planning.install_classifications(f.cs, [classification], reviewed['note']) == original['ref']
    with pytest.raises(ActionRejected, match='REQUIREMENT_CLASSIFICATION_IMMUTABLE'):
        commission_planning.install_classifications(f.cs, [classification], 'Reinterpret the existing source anchor.')
    source_anchor = next(a for a in original['payload']['anchors'] if a['id'] not in original['payload']['classifications'])
    newer = commission_planning.install_classifications(f.cs, [{'anchor_id':source_anchor['id'], 'capabilities':['source_priority']}], 'Resolve source precedence in the supplied scope.')
    assert newer != original['ref']
    with pytest.raises(ActionRejected, match='REQUIREMENTS_CHECKPOINT_REPLY_STALE'):
        commission_plan.reply(f.ws, f.checkpoint['issue_id'], f.resolution)
    assert commission_requirements.read_requirements(f.cs, original['ref'])['payload'] == original['payload']
    assert commission_requirements.read_requirements(f.cs)['ref'] == newer
    assert commission_assertions.checkpoint_answer(f.ws.store, 'requirements', f.checkpoint['issue_id']) is None
    assert plan_authority.decision_ref(f.ws.store) is None

def test_owner_may_resolve_source_precedence_but_cannot_implicitly_approve_a_calculation(resolution_case):
    f = resolution_case
    original = f.before_resolution
    subject = next(a['id'] for a in original['payload']['anchors'] if a['id'] not in original['payload']['classifications'])
    decision = deepcopy(f.resolution)
    row = {'anchor_id':subject, 'note':'Apply the supplied source precedence.'}
    decision['resolutions'] = [row]
    for fields, reason in [
        ({'entry_ids':['named-guideline'], 'capabilities':['source_priority']}, 'REQUIREMENT_CLASSIFICATION_EXCLUSIVE'),
        ({'capabilities':['method_pack']}, 'COMPUTATION_CLASSIFICATION_REQUIRES_REVIEWED_ENTRY'),
    ]:
        row['classification'] = {'anchor_id':subject, **fields}
        with pytest.raises(ActionRejected, match=reason):
            commission_plan.reply(f.ws, f.checkpoint['issue_id'], decision)
        assert commission_requirements.read_requirements(f.cs)['ref'] == original['ref']
        assert commission_assertions.checkpoint_answer(f.ws.store, 'requirements', f.checkpoint['issue_id']) is None
    row['classification'] = {'anchor_id':subject, 'capabilities':['source_priority']}
    issue = commission_plan.reply(f.ws, f.checkpoint['issue_id'], decision)
    assert commission_plan.reply(f.ws, f.checkpoint['issue_id'], decision) == issue
    saved = commission_requirements.read_requirements(f.cs)
    assert saved['ref'] == issue['requirements_result_ref']
    assert saved['payload']['classifications'][subject]['origin'] == 'operator'
    assert plan_authority.decision_ref(f.ws.store) is None
