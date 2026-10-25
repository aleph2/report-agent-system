"""Cumulative report allowance is independent of native task/checkpoint identity."""
import pytest

from test_hierarchical_content import ws, seed
from report_agent.content_export import export_snapshot
from report_agent.content_tasks import delegated_task
from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected
from report_agent.layout_revision import status


def test_default_once_limit_survives_tasks_snapshots_roots_and_store_reopen(ws):
    cs, actor, refs, snap, all_refs = seed(ws)
    export_snapshot(cs, actor, 'initial', snap)
    with delegated_task(ws, 'coordinator', {'id': 'layout-one', 'args': {
        'subagent_type': 'layout', 'description': 'Format', 'layout_snapshot_ref': snap}}) as (_, layout):
        first = export_snapshot(cs, layout, 'revision', snap, {'toc': False})
        assert export_snapshot(cs, layout, 'revision', snap, {'toc': False}) == first
    added = cs.commit(actor, 'new-root', [{'client_key': 'root', 'type': 'ContentNode',
        'payload': cs.read(refs['root'])['payload']}])['result']['refs']['root']
    new_snap = cs.freeze(actor, 'new-snapshot', added, [added, *[r for r in all_refs
        if r['type'] in {'Requirement', 'Criterion', 'SourceArtifact'}]])['result']['snapshot_ref']
    reopened = ContentStore(ws.store)
    with delegated_task(ws, 'coordinator', {'id': 'layout-two', 'args': {
        'subagent_type': 'layout', 'description': 'Again', 'layout_snapshot_ref': new_snap}}) as (_, layout):
        export_snapshot(reopened, layout, 'same-layout', new_snap, {'toc': False})
        with pytest.raises(ActionRejected, match='LAYOUT_REVISION_LIMIT_REACHED'):
            export_snapshot(reopened, layout, 'second-revision', new_snap, {'toc': False, 'margin_mm': 30})
    with ws.store.connect() as db:
        assert status(db)['revisions_used'] == 1
    assert reopened.receipt(layout, 'second-revision')['state'] == 'known_failure'


def test_failed_export_does_not_consume_layout_revision(ws, monkeypatch):
    from report_agent import content_layout
    cs, actor, refs, snap, _ = seed(ws)
    export_snapshot(cs, actor, 'initial', snap)
    original = content_layout.setup
    def fail(*_):
        raise ActionRejected('SYNTHETIC_FORMAT_FAILURE')
    monkeypatch.setattr(content_layout, 'setup', fail)
    with pytest.raises(ActionRejected, match='SYNTHETIC_FORMAT_FAILURE'):
        export_snapshot(cs, actor, 'failed', snap, {'toc': False})
    monkeypatch.setattr(content_layout, 'setup', original)
    result = export_snapshot(cs, actor, 'actual-revision', snap, {'toc': False})['result']
    assert cs.read(result['export_ref'])['payload']['export_config']['layout_revision']['revisions_used'] == 1


def test_historical_changed_exports_are_counted_before_new_policy(ws):
    cs, actor, refs, snap, _ = seed(ws)
    ws.store.set('layout_revision_limit', None)  # Explicit historical fixture, not agent permission.
    for index, options in enumerate([{}, {'toc': False}, {'toc': False, 'margin_mm': 30}]):
        export_snapshot(cs, actor, str(index), snap, options)
    ws.store.set('layout_revision_limit', 1)
    export_snapshot(cs, actor, 'unchanged-export', snap, {'toc': False, 'margin_mm': 30})
    with pytest.raises(ActionRejected, match='LAYOUT_REVISION_LIMIT_REACHED'):
        export_snapshot(cs, actor, 'cannot-reset', snap, {'toc': False})
    with ws.store.connect() as db:
        assert status(db)['revisions_used'] == 2
