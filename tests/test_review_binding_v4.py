"""Three business choices bind a complete original basis inside the task transaction."""
from copy import deepcopy

import pytest

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_deliverable_recovery_v4 import declaration


def prepared(case):
    cs, co, _, _, _ = case
    declared = declaration(case)
    original = [r['ref'] for r in cs.list_objects('Requirement')]
    criteria = cs.commit(co, 'criteria', [{'client_key': 'c'+str(i), 'type': 'Criterion', 'payload': {
        'requirement_refs': original, 'purpose': 'Independent check '+str(i), 'scope': 'original commission',
        'expected_outcome': '  Exact outcome '+str(i)+'\nPreserve this condition.  ',
        'evidence_expectation': 'Verify the original fact.', 'allowed_limits': 'Missing evidence stays missing.'}}
        for i in range(7)])['result']['refs']
    return cs, declared, list(criteria.values()), original


def review_call(criteria, *, identity='review-one', scope=None, standards=None):
    return {'name': 'task', 'id': identity, 'args': {'subagent_type': 'reviewer',
        'description': 'Independently verify the saved report, retain unfinished original requirements.',
        'review': {'deliverable': {'kind': 'deliverable', 'operation_id': 'published'},
                   'standards': standards or {'kind': 'criteria', 'criterion_refs': criteria},
                   'scope': scope or {'kind': 'whole_content'}}}}


def task_record(cs, actor):
    return cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})


def test_partial_assignment_retains_full_original_basis_and_verbatim_outcome(case):
    cs, output, criteria, original = prepared(case)
    scope = {'kind': 'mapped', 'items': [{'criterion_ref': criteria[0],
        'target_ref': output['refs']['a'], 'assessment_kind': 'content'}]}
    with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria, scope=scope)) as (call, actor):
        record = task_record(cs, actor)['payload']
        basis = record['review_commission_basis']
        assert {frozenset(r.items()) for r in basis['criterion_refs']} == {frozenset(r.items()) for r in criteria}
        assert basis['original_requirement_refs'] == original
        assert basis['commission_origin']['goal'] == cs.store.manifest['goal']
        assigned, = record['review_requirements']
        assert assigned['criterion_ref'] == criteria[0]
        assert assigned['required_checks'] == [cs.read(criteria[0])['payload']['expected_outcome']]
        assert assigned['require_check_evidence'] is True and assigned['scope_id'].startswith('v4:')
        snap = cs.read(record['review_snapshot_ref'])['payload']
        assert criteria[0] not in snap['refs']
        assert 'review' not in call['args'] and 'review_snapshot_ref' not in call['args']
        from report_agent.decision_state import read_state
        assert read_state(Workspace(cs.store), 'reviewer', ['assignment', 'review_commission_basis'])['value'] == basis


def test_same_native_intent_keeps_original_basis_when_current_heads_and_goal_change(case):
    cs, output, criteria, original = prepared(case)
    call = review_call(criteria)
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        first = task_record(cs, actor)
    cs.store.set('manifest', {**cs.store.manifest, 'goal': 'A later distinct commission.'})
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        assert task_record(cs, actor) == first
    changed = deepcopy(call)
    changed['args']['review']['standards']['criterion_refs'] = criteria[:1]
    with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
        with delegated_task(Workspace(cs.store), 'coordinator', changed):
            pytest.fail('Changed original intent cannot dispatch')


def test_independent_new_intent_gets_new_scope_not_old_review_identity(case):
    cs, output, criteria, _ = prepared(case)
    ids = []
    for name in ['first-review', 'independent-review']:
        with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1], identity=name)) as (_, actor):
            ids.append(task_record(cs, actor)['payload']['review_requirements'][0]['scope_id'])
    assert ids[0] != ids[1]
    assert len(cs.list_objects('DocumentSnapshot')) == 1


def test_invalid_target_rolls_back_snapshot_task_and_persists_known_failure(case):
    cs, output, criteria, _ = prepared(case)
    before = deepcopy(cs.list_objects())
    bad = review_call(criteria, scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criteria[0], 'target_ref': output['refs']['b'], 'assessment_kind': 'content'}]})
    with pytest.raises(ActionRejected, match='REVIEW_TARGET_OUTSIDE_SNAPSHOT'):
        with delegated_task(Workspace(cs.store), 'coordinator', bad):
            pytest.fail('Invalid assignment never dispatches')
    assert cs.list_objects() == before
    assert cs.receipt(case[1], 'delegate:review-one')['state'] == 'known_failure'


def test_inherited_basis_and_exact_saved_scope_copy_are_separate_choices(case):
    cs, output, criteria, _ = prepared(case)
    with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])) as (_, actor):
        prior = task_record(cs, actor)
    call = review_call(criteria, identity='copy-scope',
        standards={'kind': 'assignment_basis', 'assignment_ref': prior['ref']},
        scope={'kind': 'saved_assignment', 'assignment_ref': prior['ref']})
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        payload = task_record(cs, actor)['payload']
        old = prior['payload']['review_requirements'][0]
        new = payload['review_requirements'][0]
        assert new['scope_id'] != old['scope_id']
        assert {k:v for k,v in old.items() if k!='scope_id'} == {k:v for k,v in new.items() if k!='scope_id'}
        assert payload['review_commission_basis'] == prior['payload']['review_commission_basis']


def test_binding_identity_failure_rolls_back_new_effects_and_preserves_legacy_identity(case):
    from report_agent.store import digest
    cs, co, _, _, _ = case
    def register(db):
        return {'ref': cs._insert(db, co, 'DelegatedTask', {'role': 'reviewer', 'goal': 'Synthetic'})}
    def refuse(db, result):
        raise ActionRejected('BINDING_INVALID')
    before = deepcopy(cs.list_objects())
    with pytest.raises(ActionRejected, match='BINDING_INVALID'):
        cs.operation(co, 'identity-failure', {'native': 'intent'}, register, binding_identity=refuse)
    assert cs.list_objects() == before
    assert cs.receipt(co, 'identity-failure')['state'] == 'known_failure'
    cs.operation(co, 'legacy-control', {'old': True}, lambda db: {'old': True})
    assert cs.receipt(co, 'legacy-control')['request_digest'] == digest({
        'actor': co.__dict__, 'request': {'old': True}})
