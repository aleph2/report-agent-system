"""Independent review counterexamples: valid hashes do not replace authority."""
from copy import deepcopy

import pytest

from report_agent.errors import ActionRejected
from test_deliverable_declaration_v4 import case, work


@pytest.mark.parametrize('changed_commission', [False, True])
def test_source_policy_must_belong_to_the_actual_commission(case, changed_commission):
    from report_agent.source_use import configure_source_use
    cs, co, writer, _, source = case
    policy = configure_source_use(cs.store, ['s'], 'direct fixture authority')
    cs.store.set('source_use_task_binding:'+writer.task_id, policy)
    if changed_commission:
        cs.store.set('manifest', {**cs.store.manifest, 'goal': 'A different commission.'})
    selection = {'kind': 'saved_work', 'root_ref': {'client_key': 'a'},
                 'include_current_save': True, 'members_from': []}
    if changed_commission:
        before = deepcopy(cs.list_objects())
        with pytest.raises(ActionRejected, match='SOURCE_USE_AUTHORITY_INVALID'):
            cs.commit(writer, 'source-check', work(source), deliverable_selection=selection)
        assert cs.list_objects() == before
        assert cs.receipt(writer, 'source-check')['state'] == 'known_failure'
    else:
        assert cs.commit(writer, 'source-check', work(source),
                         deliverable_selection=selection)['result']['deliverable']['root_ref']


@pytest.mark.parametrize('corrupt', [{}, {'root_ref': None, 'member_refs': None, 'workbook_refs': None}])
def test_unsupported_published_shape_is_a_known_failure_not_an_unhandled_error(case, corrupt):
    cs, _, writer, _, source = case
    refs = cs.commit(writer, 'draft', work(source))['result']['refs']
    # Stored unsupported output, not an agent-authorized arbitrary receipt writer.
    forged = cs.operation(writer, 'unsupported', {}, lambda db: {'deliverable': {
        'contract': 'deliverable-declaration-v1', 'operation_id': 'unsupported',
        'producer_actor_id': writer.id, **corrupt}})
    before = deepcopy(cs.list_objects())
    with pytest.raises(ActionRejected, match='DELIVERABLE_DECLARATION_INVALID'):
        cs.commit(writer, 'select-unsupported', [], deliverable_selection={
            'kind': 'saved_work', 'root_ref': refs['a'],
            'members_from': [{'kind': 'deliverable', 'operation_id': 'unsupported'}]})
    assert cs.receipt(writer, 'select-unsupported')['state'] == 'known_failure'
    assert cs.receipt(writer, 'unsupported')['response'] == forged
    assert cs.list_objects() == before


def test_digest_valid_but_missing_selection_and_producer_provenance_is_rejected(case):
    from report_agent.store import digest
    cs, _, writer, _, source = case
    refs = cs.commit(writer, 'draft', work(source))['result']['refs']
    identity = {'root_ref': refs['a'], 'member_refs': [refs['a']], 'workbook_refs': []}
    cs.operation(writer, 'shape-valid-hash', {}, lambda db: {'deliverable': {
        'contract': 'deliverable-declaration-v1', 'operation_id': 'shape-valid-hash',
        'producer_actor_id': writer.id, **identity, 'member_digest': digest(identity)}})
    from report_agent.deliverables import resolve_snapshot
    with pytest.raises(ActionRejected, match='DELIVERABLE_DECLARATION_INVALID'):
        cs.operation(writer, 'consumer', {}, lambda db: {'snapshot': resolve_snapshot(cs, db, writer,
            {'kind': 'deliverable', 'operation_id': 'shape-valid-hash'})})
    assert cs.receipt(writer, 'consumer')['state'] == 'known_failure'
    assert cs.list_objects('DocumentSnapshot') == []
