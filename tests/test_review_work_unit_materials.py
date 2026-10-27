"""Plan-reference authorization with synthetic renderer metadata, not pixel evidence."""
import pytest

from report_agent.content_export import export_snapshot, inspect_render, read_export, render_export
from report_agent.content_store import Actor
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.review_work_units import validate_todos
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import review_call
from test_review_work_units import configured, unit_todo


@pytest.mark.parametrize('variant', [
    'authorized', 'foreign_owner', 'foreign_creator', 'foreign_task',
    'other_export', 'wrong_snapshot', 'wrong_digest', 'missing_ref',
])
def test_only_current_task_render_of_exact_assigned_export_is_plan_material(case, variant):
    cs, output, ws, _ = configured(case)
    co = case[1]
    exported = export_snapshot(cs, co, 'assigned-word', None,
        deliverable={'kind': 'deliverable', 'operation_id': 'published'})['result']['export_ref']
    criterion = cs.list_objects('Criterion')[0]['ref']
    request = review_call([criterion], scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criterion, 'target_ref': output['refs']['a'], 'assessment_kind': 'export',
        'artifact_refs': [exported], 'extent': {'kind': 'export_structure', 'artifact_ref': exported}}]})
    second_export = export_snapshot(cs, co, 'unassigned-word', cs.read(exported)['payload']['snapshot_ref'])['result']['export_ref']
    with delegated_task(ws, 'coordinator', request) as (_, actor):
        task = cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        producer = actor
        if variant == 'foreign_owner':
            producer = Actor(actor.id + '-other', actor.role, actor.task_id)
        elif variant == 'foreign_task':
            producer = Actor(actor.id, actor.role, actor.task_id + '-other')
        payload = {'snapshot_ref': task['review_snapshot_ref'],
            'export_ref': second_export if variant == 'other_export' else exported,
            'export_digest': cs.read(exported)['payload']['file_digest'],
            'pdf_ref': 'synthetic.pdf', 'pdf_digest': '0' * 64,
            'page_assets': [], 'renderer_identity': {'executable': 'synthetic'}, 'config': {}}
        if variant == 'wrong_snapshot':
            payload['snapshot_ref'] = {**task['review_snapshot_ref'], 'id': 'not-the-assigned-snapshot'}
        elif variant == 'wrong_digest':
            payload['export_digest'] = 'f' * 64
        rendered = cs.operation(producer, 'synthetic-render-metadata', {},
            lambda db: {'ref': cs._insert(db, producer, 'RenderArtifact', payload)})['result']['ref']
        if variant == 'foreign_creator':
            # Fixture-only tampering tests a distinct stored creator mismatch.
            with cs.store.connect() as db:
                rowid, raw = db.execute('SELECT rowid,data FROM content_versions WHERE type=? AND id=? AND version=?',
                    (rendered['type'], rendered['id'], rendered['version'])).fetchone()
                import json
                record = json.loads(raw)
                record['created_by'] = 'another-creator'
                db.execute('UPDATE content_versions SET data=? WHERE rowid=?', (json.dumps(record), rowid))
        if variant == 'missing_ref':
            rendered = {**rendered, 'id': 'not-a-saved-render'}
        todo = unit_todo(rendered)
        if variant == 'authorized':
            assert validate_todos(ws, [todo], declaration=True)[0]['review_unit']['material_refs'] == [rendered]
        else:
            with pytest.raises(ActionRejected, match='REVIEW_PLAN_MATERIAL_OUTSIDE_ASSIGNMENT'):
                validate_todos(ws, [todo], declaration=True)
    assert not cs.list_objects('ReviewRecord')


def test_reviewer_export_read_is_limited_to_assigned_exact_artifacts(case, monkeypatch):
    cs, output, ws, _ = configured(case)
    co = case[1]
    assigned = export_snapshot(cs, co, 'assigned-read', None,
        deliverable={'kind': 'deliverable', 'operation_id': 'published'})['result']['export_ref']
    unassigned = export_snapshot(cs, co, 'unassigned-read',
        cs.read(assigned)['payload']['snapshot_ref'])['result']['export_ref']
    criterion = cs.list_objects('Criterion')[0]['ref']
    request = review_call([criterion], scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criterion, 'target_ref': output['refs']['a'], 'assessment_kind': 'export',
        'artifact_refs': [assigned], 'extent': {'kind': 'export_structure', 'artifact_ref': assigned}}]})
    from report_agent import content_export
    original_bytes = content_export._bytes
    opened = []
    def track_bytes(*args):
        opened.append(args[1])
        return original_bytes(*args)
    monkeypatch.setattr(content_export, '_bytes', track_bytes)
    with delegated_task(ws, 'coordinator', request) as (_, reviewer):
        assert read_export(cs, reviewer, assigned)['ok']
        before = list(opened)
        with pytest.raises(ActionForbidden):
            read_export(cs, reviewer, unassigned)
        assert opened == before
        with pytest.raises(ActionForbidden):
            read_export(cs, reviewer, {**assigned, 'version': assigned['version'] + 1})
        assert opened == before
        with pytest.raises(ActionForbidden):
            render_export(cs, reviewer, 'unassigned-render', unassigned)
        assert opened == before
        with pytest.raises(ActionForbidden):
            read_export(cs, Actor('content:reviewer:other', 'reviewer', 'other'), assigned)
        assert opened == before


async def test_reviewer_cannot_inspect_render_of_unassigned_export(case, monkeypatch):
    cs, output, ws, _ = configured(case)
    co = case[1]
    assigned = export_snapshot(cs, co, 'assigned-visual', None,
        deliverable={'kind': 'deliverable', 'operation_id': 'published'})['result']['export_ref']
    other = export_snapshot(cs, co, 'unassigned-visual',
        cs.read(assigned)['payload']['snapshot_ref'])['result']['export_ref']
    criterion = cs.list_objects('Criterion')[0]['ref']
    request = review_call([criterion], scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criterion, 'target_ref': output['refs']['a'], 'assessment_kind': 'export',
        'artifact_refs': [assigned], 'extent': {'kind': 'export_structure', 'artifact_ref': assigned}}]})
    with delegated_task(ws, 'coordinator', request) as (_, reviewer):
        payload = {'snapshot_ref': cs.read(other)['payload']['snapshot_ref'], 'export_ref': other,
            'export_digest': cs.read(other)['payload']['file_digest'], 'pdf_ref': 'unused.pdf',
            'pdf_digest': '0' * 64, 'page_assets': [], 'renderer_identity': {'executable': 'synthetic'}, 'config': {}}
        render = cs.operation(reviewer, 'unassigned-render-record', {},
            lambda db: {'ref': cs._insert(db, reviewer, 'RenderArtifact', payload)})['result']['ref']
        from report_agent import content_export
        monkeypatch.setattr(content_export, '_bytes', lambda *_: pytest.fail('unassigned bytes read'))
        with pytest.raises(ActionForbidden):
            await inspect_render(cs, reviewer, render, 1, 'Read the page')


async def test_explicit_render_grant_does_not_grant_export_read(case, monkeypatch):
    cs, output, ws, _ = configured(case)
    co = case[1]
    exported = export_snapshot(cs, co, 'render-only-word', None,
        deliverable={'kind': 'deliverable', 'operation_id': 'published'})['result']['export_ref']
    info = cs.read(exported)['payload']
    payload = {'snapshot_ref': info['snapshot_ref'], 'export_ref': exported,
        'export_digest': info['file_digest'], 'pdf_ref': 'unused.pdf', 'pdf_digest': '0' * 64,
        'page_assets': [{'asset_ref': 'unused.png', 'sha256': '0' * 64}],
        'renderer_identity': {'executable': 'synthetic'}, 'config': {}}
    render = cs.operation(co, 'assigned-render-record', {},
        lambda db: {'ref': cs._insert(db, co, 'RenderArtifact', payload)})['result']['ref']
    criterion = cs.list_objects('Criterion')[0]['ref']
    request = review_call([criterion], scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criterion, 'target_ref': output['refs']['a'], 'assessment_kind': 'render',
        'artifact_refs': [render], 'extent': {'kind': 'render_pages', 'artifact_ref': render, 'pages': [1]}}]})
    class AuthorizedPageAccess(Exception):
        pass
    from report_agent import content_export
    monkeypatch.setattr(content_export, '_bytes', lambda *_: (_ for _ in ()).throw(AuthorizedPageAccess()))
    with delegated_task(ws, 'coordinator', request) as (_, reviewer):
        with pytest.raises(ActionForbidden):
            read_export(cs, reviewer, exported)
        with pytest.raises(AuthorizedPageAccess):
            await inspect_render(cs, reviewer, render, 1, 'Read the page')
        # Fixture-only corruption: matching missing digests must not authorize pixels.
        import json
        with cs.store.connect() as db:
            for ref, field in ((exported, 'file_digest'), (render, 'export_digest')):
                row = db.execute('SELECT data FROM content_versions WHERE type=? AND id=? AND version=?',
                    (ref['type'], ref['id'], ref['version'])).fetchone()
                record = json.loads(row[0])
                record['payload'].pop(field)
                db.execute('UPDATE content_versions SET data=? WHERE type=? AND id=? AND version=?',
                    (json.dumps(record), ref['type'], ref['id'], ref['version']))
        with pytest.raises(ActionForbidden, match='provenance mismatch'):
            await inspect_render(cs, reviewer, render, 1, 'Read the page')
