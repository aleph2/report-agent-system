"""Exact saved-work assembly and authority; no provider, authored-content oracle or old-case writes."""
from copy import deepcopy

import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.store import Store, digest
from report_agent.workspace import Workspace


@pytest.fixture
def saved(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic saved work', 'scope_instruction': 'Retain all seven obligations.',
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': 'delegated-reviewer-v1',
        'review_execution_mode': 'native-reviewer-v2', 'delegation_prompt_profile': 'separate-description-v1',
        'sources': [{'id': str(i), 'title': 'Source ' + str(i), 'content': 'Fixture facts.',
                     'coverage': 'complete'} for i in range(3)]})
    cs, co = ContentStore(store), actor_for('coordinator')
    inputs = cs.import_inputs(co, 'inputs', ['0', '1', '2'])['result']
    criteria = cs.commit(co, 'criteria', [{'client_key': 'c'+str(i), 'type': 'Criterion', 'payload': {
        'requirement_refs': inputs['requirement_refs'], 'purpose': 'Obligation '+str(i), 'scope': 'report',
        'expected_outcome': 'Faithful facts.', 'evidence_expectation': 'Check actual source.',
        'allowed_limits': 'Keep unknowns.'}} for i in range(7)])
    task = cs.operation(co, 'delegation', {}, lambda db: {'task_ref': cs._insert(db, co, 'DelegatedTask', {
        'role': 'writer', 'goal': 'Create saved content.', 'delegated_by': co.id,
        'write_scope': 'Own work only.'})})['result']['task_ref']
    writer = Actor('content:writer:'+task['id'], 'writer', task['id'])
    objects = [{'client_key': 'root', 'type': 'ContentNode', 'payload': {
        'kind': 'report', 'body': {'text': 'Report'}, 'qualifiers': {}, 'claim_kind': 'structure'}}]
    objects += [{'client_key': 'n'+str(i), 'type': 'ContentNode', 'payload': {
        'kind': 'block', 'body': {'text': 'Fact '+str(i)}, 'qualifiers': {}, 'claim_kind': 'fact'}} for i in range(7)]
    objects += [{'client_key': 'e'+str(i), 'type': 'Evidence', 'payload': {
        'source_refs': [inputs['source_refs'][i % 3]], 'locator': 'source', 'excerpt': 'Fixture facts.'}} for i in range(10)]
    objects += [{'client_key': 'contains'+str(i), 'type': 'Relation', 'payload': {
        'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': 'n'+str(i)},
        'predicate': 'contains', 'position': i, 'provenance_kind': 'adopted_during_generation'}} for i in range(7)]
    objects += [{'client_key': 'support'+str(i), 'type': 'Relation', 'payload': {
        'subject_ref': {'client_key': 'n'+str(i % 7)}, 'object_ref': {'client_key': 'e'+str(i % 10)},
        'predicate': 'supported_by', 'provenance_kind': 'adopted_during_generation'}} for i in range(21)]
    work = cs.commit(writer, 'opaque-work', objects)
    refs = work['result']['refs']
    all_refs = [*inputs['requirement_refs'], *inputs['source_refs'],
                *criteria['result']['refs'].values(), *refs.values()]
    assert len(all_refs) == 58
    return Workspace(store), cs, co, writer, task, refs, all_refs


def test_two_receipts_assemble_exact_58_without_body_navigation(saved, monkeypatch):
    _, cs, co, _, _, refs, all_refs = saved
    baseline = cs.freeze(co, 'explicit', refs['root'], all_refs)['result']
    monkeypatch.setattr(cs, 'read_context', lambda *a, **k: pytest.fail('No model/body navigation needed'))
    result = cs.freeze(co, 'from-receipts', refs['root'], [], saved_receipt_ids=['criteria', 'opaque-work'])['result']
    assert result['manifest_digest'] == baseline['manifest_digest']
    assert cs.read(result['snapshot_ref'])['payload']['refs'] == cs.read(baseline['snapshot_ref'])['payload']['refs']


def test_parent_summary_is_program_data_not_writer_claims_and_keeps_owner_receipt_private(saved):
    _, cs, co, writer, task, refs, _ = saved
    with pytest.raises(ActionForbidden, match='operation owner'):
        cs.receipt(co, 'opaque-work')
    summary = cs.saved_reference_summary(co, task)
    record, = summary['receipts']
    assert record['receipt_id'] == 'opaque-work'
    assert record['counts'] == {'ContentNode': 8, 'Evidence': 10, 'Relation': 28}
    assert record['refs_digest'] == digest(cs.receipt(writer, 'opaque-work')['response']['result']['refs'])
    assert refs['root'] in [x['ref'] for x in record['content_nodes']]
    assert 'request_digest' not in record and 'response' not in record
    assert summary['semantic_acceptance'] is False


@pytest.mark.parametrize('which', ['missing', 'failed', 'unresolved', 'unsupported', 'forged-owner', 'false-prefix'])
def test_bad_receipts_never_make_partial_snapshot_or_relax_receipt_permissions(saved, which):
    _, cs, co, writer, _, refs, _ = saved
    identity = 'bad'
    if which == 'failed':
        with pytest.raises(ActionRejected):
            cs.operation(writer, identity, {}, lambda db: (_ for _ in ()).throw(ActionRejected('FAILED')))
    elif which == 'unresolved':
        with cs.store.connect() as db:
            from report_agent.store import encode
            db.execute('INSERT INTO content_operations VALUES (?,?,?,?)', (identity, writer.id, 'opaque',
                encode({'ok': False, 'code': 'OPERATION_OUTCOME_UNRESOLVED', 'receipt_id': identity})))
    elif which in {'unsupported', 'false-prefix'}:
        identity = 'native:commit_objects:looks-legitimate' if which == 'false-prefix' else identity
        cs.operation(writer, identity, {}, lambda db: {'snapshot_ref': refs['root']})
    elif which == 'forged-owner':
        other = Actor('other', 'coordinator', 'other')
        cs.operation(other, identity, {}, lambda db: {'refs': {'root': refs['root']}})
    before = cs.list_objects('DocumentSnapshot')
    with pytest.raises((ActionRejected, ActionForbidden)):
        cs.freeze(co, 'reject-'+which, refs['root'], [], saved_receipt_ids=[identity])
    assert cs.list_objects('DocumentSnapshot') == before


def test_other_coordinator_cannot_adopt_a_writer_receipt(saved):
    _, cs, _, _, _, refs, _ = saved
    with pytest.raises(ActionForbidden):
        cs.freeze(Actor('other', 'coordinator', 'other'), 'foreign', refs['root'], [],
                  saved_receipt_ids=['opaque-work'])


def test_explicit_old_version_allowed_mixed_version_refused_and_replay_unchanged(saved):
    _, cs, co, writer, _, refs, _ = saved
    original = cs.freeze(co, 'stable', refs['root'], [], saved_receipt_ids=['criteria', 'opaque-work'])
    cs.commit(writer, 'revision', [{'client_key': 'new', 'type': 'ContentNode', 'previous_ref': refs['n0'],
        'payload': {'kind': 'block', 'body': {'text': 'Revised'}, 'qualifiers': {}, 'claim_kind': 'fact'}}])
    assert cs.freeze(co, 'stable', refs['root'], [], saved_receipt_ids=['criteria', 'opaque-work']) == original
    old = cs.freeze(co, 'explicit-old', refs['root'], [], saved_receipt_ids=['criteria', 'opaque-work'])
    assert old['result']['manifest_digest'] == original['result']['manifest_digest']
    with pytest.raises(ActionRejected, match='MIXED_LOGICAL_VERSIONS'):
        cs.freeze(co, 'mixed', refs['root'], [], saved_receipt_ids=['criteria', 'opaque-work', 'revision'])
    with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
        cs.freeze(co, 'stable', refs['root'], [], saved_receipt_ids=['opaque-work'])


def test_no_incoming_relations_inferred_and_old_incomplete_api_stays_strict(saved):
    _, cs, co, _, _, refs, all_refs = saved
    without_edges = [r for r in all_refs if r['type'] != 'Relation']
    # Claim-only detached content is legal; dropping non-claim tree nodes is not silently repaired.
    with pytest.raises(ActionRejected, match='DETACHED_PRESENTATION_NODE'):
        cs.freeze(co, 'old-structure', refs['root'], without_edges)
    with pytest.raises(ActionRejected, match='INCOMPLETE_REFERENCE_CLOSURE'):
        cs.freeze(co, 'old-incomplete', refs['root'], list(refs.values()))
    result = cs.freeze(co, 'root-only', refs['root'], [refs['root']], saved_receipt_ids=['criteria'])
    assert not [r for r in cs.read(result['result']['snapshot_ref'])['payload']['refs'] if r['type']=='Relation']


def test_receipt_pointer_survives_store_reopen_and_summary_no_auto_latest(saved):
    ws, cs, co, writer, task, refs, _ = saved
    first = cs.saved_reference_summary(co, task)
    cs.commit(writer, 'another', [{'client_key': 'separate', 'type': 'ContentNode', 'payload': {
        'kind': 'claim', 'body': {'text': 'Optional claim'}, 'qualifiers': {}, 'claim_kind': 'fact'}}])
    reopened = ContentStore(Store(ws.store.root))
    records = reopened.saved_reference_summary(co, task)['receipts']
    assert len(records) == 2 and first['receipts'][0] in records
    assert {r['receipt_id'] for r in records} == {'opaque-work', 'another'}


@pytest.mark.parametrize('result', [[1], 'unsupported', 1, {'refs':{}}])
def test_non_reference_success_does_not_hide_valid_saved_work(saved, result):
    _, cs, co, writer, task, refs, _ = saved
    cs.operation(writer, 'non-reference-success', {}, lambda db: result)
    with pytest.raises(ActionRejected, match='SAVED_REFERENCE_RECEIPT_UNSUPPORTED'):
        cs.freeze(co, 'unsupported-shape', refs['root'], [], saved_receipt_ids=['non-reference-success'])
    summary = cs.saved_reference_summary(co, task)
    assert [r['receipt_id'] for r in summary['receipts']] == ['opaque-work']


@pytest.mark.parametrize('selection', [None, []])
def test_empty_selection_preserves_original_request_and_strict_closure(saved, selection):
    _, cs, co, _, _, refs, all_refs = saved
    with pytest.raises(ActionRejected, match='INCOMPLETE_REFERENCE_CLOSURE'):
        cs.freeze(co, 'empty-incomplete', refs['root'], list(refs.values()), saved_receipt_ids=selection)
    original = cs.freeze(co, 'empty-replay', refs['root'], all_refs)
    assert cs.freeze(co, 'empty-replay', refs['root'], all_refs, saved_receipt_ids=selection) == original


@pytest.mark.parametrize('invalid', ['', {}, False, [1], [' ']])
def test_invalid_receipt_selection_rejected_even_on_existing_success(saved, invalid):
    _, cs, co, _, _, refs, all_refs = saved
    cs.freeze(co, 'prior-success', refs['root'], all_refs)
    with pytest.raises(ActionRejected, match='INVALID_SAVED_REFERENCE_RECEIPTS'):
        cs.freeze(co, 'prior-success', refs['root'], all_refs, saved_receipt_ids=invalid)
