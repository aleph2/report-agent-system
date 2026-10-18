"""Real SQLite and PDF rendering; Office is an explicit local test double."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event
import hashlib
import json

import pypdfium2 as pdfium
import pytest

from report_agent.content_export import _asset, render_export
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionRejected
from report_agent.store import Store, digest, encode


@pytest.fixture
def context(tmp_path):
    store = Store(tmp_path)
    return ContentStore(store), Actor('renderer', 'layout', 'render-task')


def export_fixture(contents, actor, suffix='.docx'):
    data = b'original immutable export fixture'
    asset = _asset(contents.store, 'original'+suffix, data)
    with contents.store.connect() as db:
        ref = contents._insert(db, actor, 'ExportArtifact', {
            'snapshot_ref': {'type':'DocumentSnapshot','id':'snapshot','version':1},
            'file_ref':asset, 'file_digest':hashlib.sha256(data).hexdigest()})
    return ref


def pdf_bytes():
    output = BytesIO()
    with pdfium.PdfDocument.new() as document:
        page = document.new_page(100, 100)
        page.close()
        document.save(output)
    return output.getvalue()


@pytest.mark.parametrize('suffix', ['.docx', '.xlsx'])
def test_conversion_releases_database_lock_and_reserves_original_operation(context, monkeypatch, suffix):
    contents, actor = context
    ref = export_fixture(contents, actor, suffix)
    entered, release = Event(), Event()
    calls = []
    pdf = pdf_bytes()
    def convert(store, data, actual_suffix):
        calls.append(actual_suffix)
        assert data == b'original immutable export fixture'
        entered.set()
        assert release.wait(5)
        return pdf, {'engine':'test fixture'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(render_export, contents, actor, 'render-op', ref)
        try:
            assert entered.wait(5)
            # The old implementation times out here while Office owns BEGIN IMMEDIATE.
            observed = pool.submit(contents.observe, actor, {'concurrent':True}).result(timeout=2)
            assert observed['ok']
            assert contents.receipt(actor, 'render-op')['state'] == 'outcome_unresolved'
            with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
                render_export(contents, actor, 'render-op', ref)
            with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
                contents.operation(actor, 'render-op', {'render':ref}, lambda db:pytest.fail('must not execute'))
            with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
                contents.commit(actor, 'render-op', [])
            with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
                render_export(contents, Actor('other','layout','task'), 'render-op', ref)
        finally:
            release.set()
        result = running.result(timeout=5)
    assert calls == [suffix]
    assert contents.receipt(actor, 'render-op')['state'] == 'known_success'
    record = contents.read(result['result']['render_ref'])
    assert record['owner_id'] == actor.id and record['payload']['export_ref'] == ref
    assert len(record['payload']['page_assets']) == 1
    assert (contents.store.root / record['payload']['page_assets'][0]['asset_ref']).read_bytes().startswith(b'\x89PNG')
    assert render_export(contents, actor, 'render-op', ref) == result
    assert calls == [suffix]


@pytest.mark.parametrize('failure', [RuntimeError('converter interrupted'), KeyboardInterrupt()])
def test_external_unknown_is_not_replayed(context, monkeypatch, failure):
    contents, actor = context
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        raise failure
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with pytest.raises(type(failure)):
        render_export(contents, actor, 'unknown', ref)
    assert contents.receipt(actor, 'unknown')['state'] == 'outcome_unresolved'
    with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
        render_export(contents, actor, 'unknown', ref)
    assert len(calls) == 1 and not contents.list_objects('RenderArtifact')


@pytest.mark.parametrize('change', ['asset', 'record'])
def test_finalize_rechecks_exact_input(context, monkeypatch, change):
    contents, actor = context
    ref = export_fixture(contents, actor)
    def convert(*args):
        if change == 'asset':
            (contents.store.root/'content-assets/original.docx').write_bytes(b'changed')
        else:
            with contents.store.connect() as db:
                record = contents._read(db, ref)
                record['payload']['unexpected'] = 'changed'
                db.execute('UPDATE content_versions SET data=? WHERE id=?', (encode(record),ref['id']))
        return pdf_bytes(), {'engine':'fixture'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    with pytest.raises(ActionRejected, match='ASSET_DIGEST_MISMATCH|RENDER_EXPORT_CHANGED'):
        render_export(contents, actor, 'changed', ref)
    assert contents.receipt(actor, 'changed')['state'] == 'known_failure'
    assert not contents.list_objects('RenderArtifact')


def test_finalize_failure_rolls_back_artifact_and_preserves_pending(context, monkeypatch):
    contents, actor = context
    ref = export_fixture(contents, actor)
    monkeypatch.setattr('report_agent.office_render.convert_pdf', lambda *args:(pdf_bytes(), {}))
    insert = contents._insert
    def fail_after_insert(*args, **kwargs):
        insert(*args, **kwargs)
        raise OSError('synthetic commit interruption')
    monkeypatch.setattr(contents, '_insert', fail_after_insert)
    with pytest.raises(OSError):
        render_export(contents, actor, 'finalize', ref)
    assert contents.receipt(actor, 'finalize')['state'] == 'outcome_unresolved'
    assert not contents.list_objects('RenderArtifact')


def test_preexisting_completed_receipt_is_unchanged(context, monkeypatch):
    contents, actor = context
    ref = export_fixture(contents, actor)
    saved = {'ok':True,'result':{'render_ref':{'type':'RenderArtifact','id':'historical','version':1}},'receipt_id':'old'}
    encoded = encode(saved)
    with contents.store.connect() as db:
        db.execute('INSERT INTO content_operations VALUES (?,?,?,?)',
            ('old',actor.id,digest({'actor':actor.__dict__,'request':{'render':ref}}),encoded))
    monkeypatch.setattr('report_agent.office_render.convert_pdf', lambda *args:pytest.fail('old success must be reused'))
    assert render_export(contents, actor, 'old', ref) == saved
    with contents.store.connect() as db:
        assert db.execute('SELECT response FROM content_operations WHERE operation_id=?',('old',)).fetchone()[0] == encoded


def test_blocked_and_prepare_rejection_are_known_and_cached(context, monkeypatch):
    contents, actor = context
    ref = export_fixture(contents, actor)
    calls = []
    def convert(*args):
        calls.append(1)
        return None, {'code':'RENDER_UNAVAILABLE'}
    monkeypatch.setattr('report_agent.office_render.convert_pdf', convert)
    result = render_export(contents, actor, 'blocked', ref)
    assert result['result']['execution_state'] == 'blocked'
    assert render_export(contents, actor, 'blocked', ref) == result
    assert len(calls) == 1
    bad = export_fixture(contents, actor, '.txt')
    with pytest.raises(ActionRejected, match='RENDER_FORMAT_UNSUPPORTED'):
        render_export(contents, actor, 'bad-format', bad)
    assert contents.receipt(actor, 'bad-format')['state'] == 'known_failure'
    assert len(calls) == 1
