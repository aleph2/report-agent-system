"""Exact chosen material and shared service controls, not model-quality evidence."""
from copy import deepcopy
import json

import pytest

from report_agent.bounded_review import perform_review
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.store import encode
from report_agent.text_work import prepare_material
from test_bounded_review import Model, review_call
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def partial_model():
    return Model(json.dumps({'items': [{
        'scope_id': 'rule-comparison', 'checked_requirement_indexes': [],
        'execution_state': 'blocked', 'verdict': None, 'observations': [],
        'check_results': [{'requirement_index': 0, 'execution_state': 'blocked',
            'result': 'Unperformed comparison.', 'observation_indexes': [],
            'remaining': 'Need substantive comparison.'}],
        'coverage': {'checked': [], 'unchecked': ['Comparison'],
            'blocked': ['Need comparison'], 'basis': 'Transport control only.'},
        'reason': 'Material delivery is not completed comparison.'}]}))


def original_objects(packet):
    return [e['object'] for e in packet['evidence']
        if e.get('object', {}).get('ref', {}).get('type') == 'Requirement']


async def test_choice_changes_exact_input_reuse_and_preserves_saved_assignment(ws, request):
    cs, _, refs, snapshot, members = seed(ws)
    original = cs.read(next(r for r in members if r['type'] == 'Requirement'))
    model = partial_model()
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        assignment_before = cs.read({'type': 'DelegatedTask', 'id': reviewer.task_id, 'version': 1})
        none = await perform_review(ws, reviewer, model, 'none', ['rule-comparison'])
        empty_packet = json.loads(model.calls[0][1][1])
        assert original_objects(empty_packet) == []
        assert empty_packet['selected_original_requirement_refs'] == []
        assert empty_packet['evidence'][-1]['kind'] == 'snapshot_structure'
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await perform_review(ws, reviewer, model, 'none', ['rule-comparison'],
                original_requirement_refs=[original['ref']])
        assert len(model.calls) == 1
        chosen = await perform_review(ws, reviewer, model, 'chosen', ['rule-comparison'],
            original_requirement_refs=[original['ref'], original['ref']])
        chosen_packet = json.loads(model.calls[1][1][1])
        assert original_objects(chosen_packet) == [original]
        assert chosen_packet['selected_original_requirement_refs'] == [original['ref']]
        assert chosen['review_ref'] != none['review_ref']
        again = await perform_review(ws, reviewer, model, 'chosen-new-id', ['rule-comparison'],
            original_requirement_refs=[original['ref']])
        assert again['reused'] and again['review_ref'] == chosen['review_ref']
        assert len(model.calls) == 2
        saved = cs.read(chosen['review_ref'])
        assert original['ref'] in saved['payload']['dependency_refs']
        assert cs.read({'type': 'DelegatedTask', 'id': reviewer.task_id, 'version': 1}) == assignment_before
        assert chosen_packet['assignment'] == empty_packet['assignment']
        assert chosen_packet['criteria'] == empty_packet['criteria']
        assert chosen_packet['commission'] == empty_packet['commission']
        request.node.user_properties.append(('material_choice', encode({
            'none': empty_packet, 'chosen': chosen_packet, 'saved': saved,
            'same_choice_reused': again['reused'], 'checker_calls': len(model.calls)})))


@pytest.mark.parametrize('invalid', ['wrong-type', 'foreign-id', 'wrong-version', 'unlinked-in-snapshot', 'unselected-scope'])
async def test_invalid_original_choice_rejects_before_checker_without_state_writes(ws, invalid, request):
    cs, actor, refs, snapshot, members = seed(ws)
    original_ref = next(r for r in members if r['type'] == 'Requirement')
    candidate = deepcopy(original_ref)
    call = review_call(snapshot, refs)
    if invalid == 'wrong-type':
        candidate = refs['claim']
    elif invalid == 'foreign-id':
        candidate['id'] = 'not-in-this-project'
    elif invalid == 'wrong-version':
        candidate['version'] += 1
    else:
        # Host fixture creates a second real original and a Criterion linked only
        # to it. The current scope must not acquire the other scope's original.
        from report_agent.content_models import Requirement
        payload = Requirement.model_validate({**cs.read(original_ref)['payload'],
            'text': 'Independent original for another scope.'}).model_dump()
        with ws.store.connect() as db:
            candidate = cs._insert(db, actor, 'Requirement', payload)
        criterion_payload = deepcopy(cs.read(refs['k'])['payload'])
        criterion_payload['requirement_refs'] = [candidate]
        criterion = cs.commit(actor, 'other-criterion', [{'client_key': 'k2', 'type': 'Criterion',
            'payload': criterion_payload}])['result']['refs']['k2']
        snapshot = cs.freeze(actor, 'two-original-snapshot', refs['root'],
            [*members, candidate, criterion])['result']['snapshot_ref']
        call['args']['review_snapshot_ref'] = snapshot
        if invalid == 'unselected-scope':
            other = deepcopy(call['args']['review_requirements'][0])
            other.update(scope_id='other-scope', criterion_ref=criterion)
            call['args']['review_requirements'].append(other)
    model = partial_model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        before_objects = cs.list_objects()
        with ws.store.connect() as db:
            before_observations = db.execute('select count(*) from content_observations').fetchone()[0]
        with pytest.raises(ActionRejected, match='REVIEW_ORIGINAL_REQUIREMENT_OUTSIDE_ASSIGNED_SNAPSHOT'):
            await perform_review(ws, reviewer, model, 'bad-choice', ['rule-comparison'],
                original_requirement_refs=[candidate])
        assert not model.calls and cs.list_objects() == before_objects
        with ws.store.connect() as db:
            assert db.execute('select count(*) from content_observations').fetchone()[0] == before_observations
        request.node.user_properties.append(('rejected_original', encode({
            'case': invalid, 'ref': candidate, 'checker_calls': 0, 'objects_unchanged': True,
            'observations_unchanged': True})))


async def test_unknown_choice_outcome_is_not_replayed_under_new_operation(ws):
    import httpx
    cs, _, refs, snapshot, members = seed(ws)
    original = next(r for r in members if r['type'] == 'Requirement')
    model = Model(httpx.ReadTimeout('unknown checker outcome'))
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(httpx.ReadTimeout):
            await perform_review(ws, reviewer, model, 'first', ['rule-comparison'],
                original_requirement_refs=[original])
        with pytest.raises(ActionRejected, match='PREVIOUS_ATTEMPT_UNRESOLVED'):
            await perform_review(ws, reviewer, model, 'second', ['rule-comparison'],
                original_requirement_refs=[original])
    assert len(model.calls) == 1 and not cs.list_objects('ReviewRecord')


def test_shared_producer_compiler_preserves_explicit_choice_and_does_not_follow_links(ws, request):
    cs, actor, refs, snapshot, members = seed(ws)
    original = cs.read(next(r for r in members if r['type'] == 'Requirement'))
    criterion = cs.read(refs['k'])
    criterion_only = prepare_material(ws, [refs['k']], [], actor=actor)
    explicit = prepare_material(ws, [refs['k'], original['ref']], [], actor=actor)
    assert criterion_only.evidence == [{'kind': 'saved_object', 'object': criterion}]
    assert explicit.evidence == [*criterion_only.evidence, {'kind': 'saved_object', 'object': original}]
    assert cs.read(original['ref']) == original
    request.node.user_properties.append(('shared_material_compiler', encode({
        'selected_criterion': criterion_only.evidence, 'selected_with_original': explicit.evidence,
        'original_unchanged': True})))
