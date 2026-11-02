"""A commissioned object cannot disappear through snapshot or reviewer selection."""
from copy import deepcopy

import pytest

from report_agent.content_delivery import current_delivery
from report_agent.errors import ActionForbidden, ActionRejected
from test_m1_commission_plan import api, approve, commission, save, writer


def content(text, kind='block'):
    return {'kind': kind, 'body': {'text': text}, 'qualifiers': {}, 'claim_kind': 'structure'}


def completed_objects(fixture, saved, count=4, *, unresolved=()):
    actor = writer(fixture, saved)
    objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': content('Commission report', 'report')}]
    for number in range(1, count + 1):
        key = 'S' + str(number)
        objects.extend([
            {'client_key': key, 'type': 'ContentNode', 'payload': content(
                'Assessed ' + key + ('. Height remains unknown; supported adopted outcome stated.' if number == 1 else ''), 'chapter')},
            {'client_key': key + '-score', 'type': 'ContentNode', 'payload': content('Adopted score 50; fixture outcome only.')},
            {'client_key': key + '-level', 'type': 'ContentNode', 'payload': content('Adopted level III; fixture outcome only.')},
            {'client_key': key + '-basis', 'type': 'Evidence', 'payload': {
                'source_refs': [fixture.sources['design']], 'locator': 'manifest text',
                'excerpt': 'S1 S2 S3 S4 S5 are design objects.'}},
            {'client_key': key + '-edge', 'type': 'Relation', 'payload': {
                'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': key},
                'predicate': 'contains', 'position': number - 1, 'provenance_kind': 'adopted_during_generation'}},
            *[{'client_key': key + '-' + part + '-edge', 'type': 'Relation', 'payload': {
                'subject_ref': {'client_key': key}, 'object_ref': {'client_key': key + '-' + part},
                'predicate': 'contains', 'position': position, 'provenance_kind': 'adopted_during_generation'}}
              for position, part in enumerate(('score', 'level'))]])
    refs = fixture.cs.commit(actor, 'outcome-content', objects)['result']['refs']
    for number in range(1, count + 1):
        key = 'S' + str(number)
        api().record_outcome(fixture.cs, actor, 'outcome-' + key, key,
            refs[key], refs[key + '-score'], refs[key + '-level'], [refs[key + '-basis']],
            list(unresolved) if number == 1 else [])
    # Deliberately omit every inventory Requirement; freeze must restore expected coverage.
    snapshot_ref = fixture.cs.freeze(fixture.co, 'delivery-snapshot', refs['root'],
        [*refs.values(), fixture.sources['design']])['result']['snapshot_ref']
    return actor, refs, fixture.cs.read(snapshot_ref)


@pytest.mark.parametrize('case,expected_complete,missing', [
    ('four-assessed', False, {'S5'}),
    ('unknown-parameter', True, set()),
    ('approved-reduction', True, set()),
    ('unapproved-reduction', False, {'S5'}),
    ('agent-exclusion', False, {'S5'})])
def test_five_agreed_commission_delivery_cases(commission, case, expected_complete, missing):
    from report_agent.review_coverage import commission_completion
    plan = deepcopy(commission.plan)
    if case in {'unapproved-reduction', 'agent-exclusion'}:
        plan['objects'][-1].update(included=False, origin='interpretation',
            reason='Agent proposes exclusion because the survey omitted S5.')
    saved = save(commission, plan)
    approve(commission, saved, reductions=[{'object_id': 'S5', 'reason': 'Owner explicitly reduces this commissioned scope.'}]
            if case == 'approved-reduction' else [])
    actor, refs, snapshot = completed_objects(commission, saved, count=5 if case == 'unknown-parameter' else 4)
    summary = commission_completion(commission.cs, snapshot)
    assert summary['required'] is True and summary['complete'] is expected_complete
    assert {item['object_id'] for item in summary['missing_objects']} == missing
    assert all(item['label'] and item['reason'] for item in summary['missing_objects'])
    assert snapshot['payload']['commission_plan_ref'] == saved['plan_ref']
    assert all(ref in snapshot['payload']['refs'] for ref in saved['inventory_refs'])
    reduced = {item['object_id'] for item in summary['reduced_objects']}
    assert reduced == ({'S5'} if case == 'approved-reduction' else set())


def test_unresolved_outcome_is_incomplete_even_with_section_score_level(commission):
    from report_agent.review_coverage import commission_completion
    saved = save(commission)
    approve(commission, saved)
    _, _, snapshot = completed_objects(commission, saved, count=5, unresolved=['Required indicator basis unresolved'])
    summary = commission_completion(commission.cs, snapshot)
    assert summary['complete'] is False
    assert {item['object_id'] for item in summary['missing_objects']} == {'S1'}


def test_outcomes_cannot_be_forged_by_other_writer_or_missing_saved_basis(commission):
    saved = save(commission)
    approve(commission, saved)
    actor, refs, _ = completed_objects(commission, saved)
    foreign = writer(commission, saved, operation='other-writer-task')
    with pytest.raises((ActionRejected, ActionForbidden)):
        api().record_outcome(commission.cs, foreign, 'foreign-outcome', 'S5', refs['S1'],
            refs['S1-score'], refs['S1-level'], [refs['S1-basis']], [])
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        api().record_outcome(commission.cs, actor, 'no-basis', 'S5', refs['S1'],
            refs['S1-score'], refs['S1-level'], [], [])


def test_favorable_delivery_metadata_cannot_hide_missing_commission_object(commission):
    saved = save(commission)
    approve(commission, saved)
    _, _, snapshot = completed_objects(commission, saved)
    # Default delivery projection is scoped evidence; an optimistic execution flag is not reduction authority.
    commission.ws.store.set('content_execution_decision', {'decision': 'complete', 'reason': 'Agent says all done.'})
    commission.ws.store.set('content_delivery', {'snapshot_ref': snapshot['ref'],
        'export_ref': {'type': 'ExportArtifact', 'id': 'unreviewed-export', 'version': 1}})
    result = current_delivery(commission.ws.store)
    assert result['status'] == 'incomplete'
    assert result['commission_coverage']['complete'] is False
    assert {item['object_id'] for item in result['commission_coverage']['missing_objects']} == {'S5'}


def second_writer_s1(fixture, saved, first_refs):
    actor = writer(fixture, saved, operation='second-writer-task')
    objects = [{'client_key': key, 'type': 'ContentNode', 'payload': content(text, kind)}
               for key, text, kind in [('section', 'A later independent S1 draft.', 'chapter'),
                                      ('score', 'Later S1 score 55.', 'block'),
                                      ('level', 'Later S1 level III.', 'block')]]
    objects.extend({'client_key': key + '-edge', 'type': 'Relation', 'payload': {
        'subject_ref': {'client_key': 'section'}, 'object_ref': {'client_key': key},
        'predicate': 'contains', 'position': position, 'provenance_kind': 'adopted_during_generation'}}
        for position, key in enumerate(('score', 'level')))
    refs = fixture.cs.commit(actor, 'second-writer-content', objects)['result']['refs']
    api().record_outcome(fixture.cs, actor, 'second-writer-outcome', 'S1', refs['section'],
        refs['score'], refs['level'], [first_refs['S1-basis']], [])
    return refs


def test_selected_snapshot_outcomes_do_not_change_when_another_writer_drafts_same_object(commission):
    from report_agent.review_coverage import commission_completion
    saved = save(commission)
    approve(commission, saved)
    _, refs, snapshot = completed_objects(commission, saved, count=5)
    before = commission_completion(commission.cs, snapshot)
    assert before['complete'] is True
    commission.ws.store.set('content_delivery', {'snapshot_ref': snapshot['ref'],
        'export_ref': {'type': 'ExportArtifact', 'id': 'selected-export', 'version': 1}})
    second_writer_s1(commission, saved, refs)
    unchanged = commission.cs.read(snapshot['ref'])
    assert unchanged == snapshot
    assert commission_completion(commission.cs, unchanged) == before
    assert current_delivery(commission.ws.store)['commission_coverage']['complete'] is True


def test_freeze_refuses_two_matching_writer_outcomes_for_the_same_object(commission):
    saved = save(commission)
    approve(commission, saved)
    _, refs, snapshot = completed_objects(commission, saved, count=5)
    later = second_writer_s1(commission, saved, refs)
    link = commission.cs.commit(commission.co, 'include-alternative-s1', [{
        'client_key': 'alternative', 'type': 'Relation', 'payload': {
            'subject_ref': refs['root'], 'object_ref': later['section'], 'predicate': 'contains',
            'position': 5, 'provenance_kind': 'adopted_during_generation'}}])['result']['refs']['alternative']
    with pytest.raises(ActionRejected, match='(?i)(ambiguous|multiple.*outcome)'):
        commission.cs.freeze(commission.co, 'ambiguous-assessment-snapshot', refs['root'],
            [*snapshot['payload']['refs'], *later.values(), link])


def test_automatic_inventory_closure_does_not_silently_deduplicate_snapshot_input(commission):
    saved = save(commission)
    approve(commission, saved)
    _, refs, snapshot = completed_objects(commission, saved, count=5)
    with pytest.raises(ActionRejected, match='INVALID_MANIFEST'):
        commission.cs.freeze(commission.co, 'duplicate-ref-snapshot', refs['root'],
            [*snapshot['payload']['refs'], refs['root']])


def test_reopened_same_writer_outcome_only_changes_a_new_snapshot(commission):
    from report_agent.review_coverage import commission_completion
    saved = save(commission)
    approve(commission, saved)
    actor, refs, snapshot = completed_objects(commission, saved, count=5)
    before = commission_completion(commission.cs, snapshot)
    assert before['complete'] is True
    api().record_outcome(commission.cs, actor, 'reopened-S1-outcome', 'S1', refs['S1'],
        refs['S1-score'], refs['S1-level'], [refs['S1-basis']], ['Required basis reopened by the owning writer.'])
    assert commission_completion(commission.cs, commission.cs.read(snapshot['ref'])) == before
    newer_ref = commission.cs.freeze(commission.co, 'reopened-assessment-snapshot', refs['root'],
        snapshot['payload']['refs'])['result']['snapshot_ref']
    newer = commission.cs.read(newer_ref)
    after = commission_completion(commission.cs, newer)
    assert after['complete'] is False
    assert {item['object_id'] for item in after['missing_objects']} == {'S1'}
    assert 'Required basis reopened' in after['missing_objects'][0]['reason']
    assert newer['payload']['manifest_digest'] != snapshot['payload']['manifest_digest']
    assert commission.cs.read(snapshot['ref']) == snapshot
