"""Delivery selection semantics, historical reads and case transaction ownership."""
import pytest

from report_agent import legacy_state as legacy, report_state
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden
from report_agent.store import Store


def case(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic delivery selection',
        'content_contract': 'hierarchical-review-v1',
        'sources': [{'id': 'source', 'content': 'Supplied material', 'coverage': 'complete'}]})
    return store, ContentStore(store)


@pytest.mark.parametrize('family', ['content_delivery', 'content_final_review'])
def test_native_clear_does_not_revive_a_historical_selection(tmp_path, family):
    store, contents = case(tmp_path)
    old = {'snapshot_ref': {'type': 'DocumentSnapshot', 'id': 'old', 'version': 1},
           'export_ref': {'type': 'ExportArtifact', 'id': 'old-word', 'version': 1}}
    store.set(family, old)
    read = getattr(legacy, 'get_' + family)
    write = getattr(report_state, 'set_' + family)
    assert read(store) == old
    cleared = write(store, None)
    assert read(store) is None
    assert write(store, None) == cleared
    assert store.get(family) == old
    if family == 'content_delivery':
        from report_agent.content_delivery import current_delivery
        assert current_delivery(store)['status'] == 'not_assessed'


@pytest.mark.parametrize('family', ['content_delivery', 'content_final_review'])
def test_changed_selection_preserves_previous_version_and_context_privacy(tmp_path, family):
    store, contents = case(tmp_path)
    read = getattr(legacy, 'get_' + family)
    write = getattr(report_state, 'set_' + family)
    first = {'snapshot_ref': {'type': 'DocumentSnapshot', 'id': 'first', 'version': 1}}
    second = {'snapshot_ref': {'type': 'DocumentSnapshot', 'id': 'second', 'version': 1}}
    saved = write(store, first)
    changed = write(store, second)
    assert read(store) == second
    assert contents.read(saved)['payload'] == first
    assert contents.read(changed)['previous_ref'] == saved
    assert write(store, second) == changed
    assert store.get(family) is None
    with pytest.raises(ActionForbidden):
        contents.read_context(Actor('writer', 'writer', 'scope'), saved)


def test_delivery_and_output_rollback_together(tmp_path):
    store, contents = case(tmp_path)
    actor = Actor('content:coordinator', 'coordinator', 'delivery')
    def save(db):
        ref = contents._insert(db, actor, 'ContentNode', {
            'kind': 'block', 'body': {'text': 'Uncommitted output'},
            'claim_kind': 'structure', 'qualifiers': {}})
        report_state.set_content_delivery(db, {'snapshot_ref': ref}, actor=actor)
        raise RuntimeError('failed before commit')
    with pytest.raises(RuntimeError, match='before commit'):
        contents.operation(actor, 'failed-delivery', {}, save)
    assert contents.list_objects() == []
    assert legacy.get_content_delivery(store) is None


def test_selection_write_is_not_new_review_evidence(tmp_path):
    from types import SimpleNamespace
    from report_agent.hierarchical_review import HierarchicalRubric
    store, contents = case(tmp_path)
    rubric = object.__new__(HierarchicalRubric)
    rubric.workspace = SimpleNamespace(store=store)
    before = rubric.evidence_revision()
    report_state.set_content_final_review(store, {'evidence_revision': before})
    report_state.set_content_delivery(store, {'snapshot_ref': {'type': 'DocumentSnapshot', 'id': 's', 'version': 1}})
    assert rubric.evidence_revision() == before
    with store.connect() as db:
        contents._insert(db, Actor('writer', 'writer', 'scope'), 'ContentNode', {
            'kind': 'block', 'body': {'text': 'New substantive evidence'},
            'claim_kind': 'structure', 'qualifiers': {}})
    assert rubric.evidence_revision() != before
