"""Producer selection is exact saved data, not a model-written version manifest."""
from copy import deepcopy

import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import Store


def node(key, kind='block', previous=None):
    return {'client_key': key, 'type': 'ContentNode',
            'payload': {'kind': kind, 'body': {'text': key}, 'qualifiers': {},
                        'claim_kind': 'structure' if kind == 'report' else 'fact'},
            **({'previous_ref': previous} if previous else {})}


def contains(key, parent, child, position=0):
    return {'client_key': key, 'type': 'Relation', 'payload': {
        'subject_ref': parent, 'object_ref': child, 'predicate': 'contains',
        'position': position, 'provenance_kind': 'adopted_during_generation'}}


@pytest.fixture
def case(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Independently verify the selected saved report.',
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': 'delegated-reviewer-v1',
        'review_execution_mode': 'native-reviewer-v2',
        'review_interface_profile': 'review-interfaces-v4',
        'delegation_prompt_profile': 'separate-description-v1',
        'operation_identity_profile': 'native-tool-runtime-v1',
        'sources': [{'id': 's', 'title': 'Source', 'content': 'A verified fact.', 'coverage': 'complete'}]})
    cs = ContentStore(store)
    co = Actor('content:coordinator', 'coordinator', 'root')
    task = cs.operation(co, 'writer-task', {}, lambda db: {'task': cs._insert(db, co,
        'DelegatedTask', {'role': 'writer', 'goal': 'Save intended output.', 'delegated_by': co.id})})['result']['task']
    writer = Actor('content:writer:'+task['id'], 'writer', task['id'])
    source = cs.import_inputs(co, 'inputs', ['s'])['result']['source_refs'][0]
    return cs, co, writer, task, source


def work(source):
    return [node('a', 'report'), node('a-body'), node('b', 'report'), node('b-body'), node('sheet'),
        contains('a-edge', {'client_key': 'a'}, {'client_key': 'a-body'}),
        contains('b-edge', {'client_key': 'b'}, {'client_key': 'b-body'}),
        {'client_key': 'e', 'type': 'Evidence', 'payload': {
            'source_refs': [source], 'locator': 's', 'excerpt': 'A verified fact.'}},
        {'client_key': 'support', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'a-body'}, 'object_ref': {'client_key': 'e'},
            'predicate': 'supported_by', 'provenance_kind': 'adopted_during_generation'}}]


def test_last_save_selects_one_draft_and_preserves_the_exact_receipt(case):
    cs, co, writer, task, source = case
    selection = {'kind': 'saved_work', 'root_ref': {'client_key': 'a'},
                 'include_current_save': True, 'members_from': [],
                 'workbook_refs': [{'client_key': 'sheet'}]}
    result = cs.commit(writer, 'save', work(source), deliverable_selection=selection)
    refs = result['result']['refs']
    declared = result['result']['deliverable']
    expected = [refs[n] for n in ['a', 'a-body', 'a-edge', 'e', 'support', 'sheet']] + [source]
    assert {frozenset(r.items()) for r in declared['member_refs']} == {frozenset(r.items()) for r in expected}
    assert declared['root_ref'] == refs['a'] and declared['workbook_refs'] == [refs['sheet']]
    assert declared['operation_id'] == 'save' and declared['semantic_acceptance'] is False
    assert cs.list_objects('DocumentSnapshot') == []
    assert cs.commit(writer, 'save', work(source), deliverable_selection=selection) == result
    assert cs.receipt(writer, 'save')['response'] == result
    with pytest.raises(ActionForbidden):
        cs.receipt(co, 'save')


def test_selection_only_publishes_saved_work_without_a_content_revision(case):
    cs, _, writer, _, source = case
    refs = cs.commit(writer, 'draft', work(source))['result']['refs']
    before = deepcopy(cs.list_objects())
    selection = {'kind': 'saved_work', 'root_ref': refs['a'],
                 'members_from': [{'kind': 'saved_result', 'operation_id': 'draft'}]}
    result = cs.commit(writer, 'declare', [], deliverable_selection=selection)['result']
    assert result['refs'] == {} and result['selection_only'] is True
    assert result['deliverable']['root_ref'] == refs['a']
    assert cs.list_objects() == before


def test_excluded_dependency_rolls_back_this_save_but_keeps_prior_saved_output(case):
    cs, _, writer, _, source = case
    refs = cs.commit(writer, 'draft', work(source))['result']['refs']
    before = deepcopy(cs.list_objects())
    with pytest.raises(ActionRejected, match='DELIVERABLE_EXCLUDED_DEPENDENCY'):
        cs.commit(writer, 'bad-selection', [node('new')], deliverable_selection={
            'kind': 'saved_work', 'root_ref': refs['a'], 'include_current_save': True,
            'members_from': [{'kind': 'saved_result', 'operation_id': 'draft'}],
            'remove_refs': [refs['e']]})
    assert cs.list_objects() == before
    assert cs.receipt(writer, 'bad-selection')['state'] == 'known_failure'
    assert cs.receipt(writer, 'draft')['state'] == 'known_success'


def test_replacing_a_contains_edge_keeps_only_the_explicit_new_branch(case):
    cs, _, writer, _, source = case
    refs = cs.commit(writer, 'draft', work(source))['result']['refs']
    result = cs.commit(writer, 'replacement', [node('replacement'),
        contains('new-edge', refs['a'], {'client_key': 'replacement'})], deliverable_selection={
            'kind': 'saved_work', 'root_ref': refs['a'], 'include_current_save': True,
            'members_from': [{'kind': 'saved_result', 'operation_id': 'draft'}],
            'remove_refs': [refs['a-edge']]})['result']
    assert {frozenset(r.items()) for r in result['deliverable']['member_refs']} == {
        frozenset(r.items()) for r in [refs['a'], result['refs']['replacement'], result['refs']['new-edge']]}


def test_foreign_raw_receipt_is_not_a_published_declaration(case):
    cs, co, writer, _, source = case
    refs = cs.commit(writer, 'draft', work(source))['result']['refs']
    other_task = cs.operation(co, 'writer-two', {}, lambda db: {'task': cs._insert(db, co,
        'DelegatedTask', {'role': 'writer', 'goal': 'Other', 'delegated_by': co.id})})['result']['task']
    other = Actor('content:writer:'+other_task['id'], 'writer', other_task['id'])
    with pytest.raises(ActionForbidden):
        cs.commit(other, 'private-read', [], deliverable_selection={'kind': 'saved_work',
            'root_ref': refs['a'], 'members_from': [{'kind': 'saved_result', 'operation_id': 'draft'}]})


def test_legacy_empty_save_and_request_identity_are_unchanged(case):
    cs, _, writer, _, source = case
    before = cs.commit(writer, 'old-save', [node('r', 'report')])
    assert before['result'].keys() == {'refs'}
    assert cs.commit(writer, 'old-save', [node('r', 'report')]) == before
    with pytest.raises(ActionRejected, match='EMPTY_COMMIT'):
        cs.commit(writer, 'old-empty', [])
