"""Durable published selection and exact snapshots, using real local transactions."""
import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case, node, work


def declaration(case):
    cs, co, writer, task, source = case
    result = cs.commit(writer, 'published', work(source), deliverable_selection={
        'kind': 'saved_work', 'root_ref': {'client_key': 'a'},
        'include_current_save': True, 'members_from': []})['result']
    return result


def test_selection_only_declaration_is_discoverable_by_parent_after_reopen(case):
    cs, co, writer, task, source = case
    refs = cs.commit(writer, 'saved', work(source))['result']['refs']
    cs.commit(writer, 'published', [], deliverable_selection={'kind': 'saved_work',
        'root_ref': refs['a'], 'members_from': [{'kind': 'saved_result', 'operation_id': 'saved'}]})
    from report_agent.store import Store
    reopened = ContentStore(Store(cs.store.root))
    value, = reopened.saved_reference_summary(co, task)['declared_deliverables']
    assert value['operation_id'] == 'published' and value['selection_only'] is True
    assert value['root_ref'] == refs['a'] and value['semantic_acceptance'] is False
    assert 'request_digest' not in value


def test_read_state_pages_the_full_declaration_after_native_return_is_lost(case):
    cs, co, writer, task, source = case
    declaration(case)
    from report_agent.decision_state import read_state
    value = read_state(Workspace(cs.store), 'coordinator', ['declared_deliverables'], limit=1)
    assert value['value'][0]['operation_id'] == 'published'
    assert value['total'] == 1


def resolve(cs, actor, op, selector):
    from report_agent.deliverables import resolve_snapshot
    return cs.operation(actor, op, {'selector': selector}, lambda db: {
        'snapshot_ref': resolve_snapshot(cs, db, actor, selector)})['result']['snapshot_ref']


def test_declared_handle_creates_one_snapshot_and_never_substitutes_by_content(case):
    cs, co, writer, task, source = case
    result = declaration(case)
    first = resolve(cs, co, 'bind1', {'kind': 'deliverable', 'operation_id': 'published'})
    again = resolve(cs, co, 'bind2', {'kind': 'deliverable', 'operation_id': 'published'})
    assert first == again and len(cs.list_objects('DocumentSnapshot')) == 1
    payload = cs.read(first)['payload']
    assert payload['deliverable_provenance'] == {
        'operation_id': 'published', 'member_digest': result['deliverable']['member_digest']}
    assert payload['refs'] == result['deliverable']['member_refs']
    cs.commit(writer, 'same-content-new-intent', [], deliverable_selection={
        'kind': 'saved_work', 'root_ref': result['refs']['a'],
        'members_from': [{'kind': 'deliverable', 'operation_id': 'published'}]})
    second = resolve(cs, co, 'bind3', {'kind': 'deliverable', 'operation_id': 'same-content-new-intent'})
    assert second != first  # Distinct explicit selection, no global equivalent/latest lookup.


def test_exact_existing_snapshot_and_historical_standard_members_are_unchanged(case):
    cs, co, writer, task, source = case
    declared = declaration(case)
    existing = cs.freeze(co, 'old-snapshot', declared['refs']['a'],
                         declared['deliverable']['member_refs'])['result']['snapshot_ref']
    before = cs.read(existing)
    assert resolve(cs, writer, 'explicit', {'kind': 'snapshot', 'snapshot_ref': existing}) == existing
    assert cs.read(existing) == before and len(cs.list_objects('DocumentSnapshot')) == 1


def test_other_parent_cannot_resolve_a_published_writer_selection(case):
    cs, co, writer, task, source = case
    declaration(case)
    with pytest.raises(ActionForbidden):
        resolve(cs, Actor('other-co', 'coordinator', 'other-root'), 'forbidden',
                {'kind': 'deliverable', 'operation_id': 'published'})
    assert cs.list_objects('DocumentSnapshot') == []


def test_public_foreign_members_keep_their_owner_and_need_no_copy(case):
    cs, co, writer, task, source = case
    result = declaration(case)
    other_task = cs.operation(co, 'second-writer', {}, lambda db: {'task': cs._insert(db, co,
        'DelegatedTask', {'role': 'writer', 'goal': 'Select saved output.', 'delegated_by': co.id})})['result']['task']
    other = Actor('content:writer:'+other_task['id'], 'writer', other_task['id'])
    before = cs.list_objects('ContentNode')
    selected = cs.commit(other, 'foreign-published', [], deliverable_selection={
        'kind': 'saved_work', 'root_ref': result['refs']['a'],
        'members_from': [{'kind': 'deliverable', 'operation_id': 'published'}]})['result']['deliverable']
    assert selected['root_ref'] == result['refs']['a']
    assert cs.list_objects('ContentNode') == before
    assert cs.read(selected['root_ref'])['owner_id'] == writer.id


def test_v4_save_input_is_not_added_to_legacy_tool_schemas(case):
    from langchain_core.tools import StructuredTool
    from report_agent.hierarchical_tools import content_tools
    cs = case[0]
    workspace = Workspace(cs.store)
    def schema(profile):
        cs.store.set('manifest', {**cs.store.manifest, 'review_interface_profile': profile})
        tools = content_tools(workspace, 'coordinator')
        selected = next(t for t in tools if getattr(t, 'name', getattr(t, '__name__', None)) == 'commit_objects')
        tool = selected if isinstance(selected, StructuredTool) else StructuredTool.from_function(selected)
        return tool.tool_call_schema.model_json_schema()['properties']
    assert 'deliverable_selection' in schema('review-interfaces-v4')
    assert 'deliverable_selection' not in schema('review-interfaces-v3')


def test_changed_selection_on_original_operation_is_a_conflict(case):
    cs, _, writer, _, source = case
    result = declaration(case)
    with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
        cs.commit(writer, 'published', [], deliverable_selection={'kind': 'saved_work',
            'root_ref': result['refs']['b'],
            'members_from': [{'kind': 'saved_result', 'operation_id': 'published'}]})
