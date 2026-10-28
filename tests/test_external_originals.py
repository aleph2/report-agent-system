import hashlib
import os
import sqlite3
from io import BytesIO
from zipfile import ZipFile
import pytest

from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.document_tools import source_page_info, source_page_png
from report_agent.errors import ActionRejected
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from test_document_tools import workspace
from test_ingestion import pdf_bytes
from test_deliverable_declaration_v4 import case, work


def test_external_original_survives_reopen_and_preserves_source_identity(tmp_path):
    ws = workspace(tmp_path)
    data = pdf_bytes(('Synthetic imported page',))
    source = Catalog(ws.store).import_file('imported.pdf', data)['source']
    sid = source['id']
    before = digest(ContentStore.source_payload(ws.store.sources([sid])[0]))
    with ws.store.connect() as db:
        blob = db.execute('SELECT original FROM source_versions WHERE id=?', (sid,)).fetchone()[0]
    assert blob != data
    reopened = Workspace(Store(tmp_path))
    assert digest(ContentStore.source_payload(reopened.store.sources([sid])[0])) == before
    assert source_page_info(reopened, sid, 1)['native_text'] == 'Synthetic imported page'
    assert source_page_png(reopened, sid, 1).startswith(b'\x89PNG\r\n\x1a\n')
    assert Catalog(reopened.store).import_file('imported.pdf', data)['reused']


def test_external_original_tamper_or_missing_fails_closed(tmp_path):
    ws = workspace(tmp_path)
    data = pdf_bytes(('Synthetic imported page',))
    sid = Catalog(ws.store).import_file('imported.pdf', data)['source']['id']
    path = tmp_path / 'sources' / 'objects' / hashlib.sha256(data).hexdigest()
    path.write_bytes(b'tampered')
    with pytest.raises(ActionRejected, match='SHA256_MISMATCH'):
        source_page_info(ws, sid, 1)
    path.unlink()
    with ws.store.connect() as db:
        db.execute('UPDATE source_versions SET original=? WHERE id=?', (data, sid))
    with pytest.raises(ActionRejected, match='SOURCE_ORIGINAL_UNAVAILABLE'):
        source_page_info(ws, sid, 1)


def test_failed_import_never_publishes_database_reference(tmp_path):
    ws = workspace(tmp_path)
    cat = Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("CREATE TRIGGER import_failure BEFORE INSERT ON events WHEN NEW.kind='source_imported' BEGIN SELECT RAISE(ABORT, 'simulated'); END")
    with pytest.raises(sqlite3.IntegrityError):
        cat.import_file('imported.pdf', pdf_bytes(('Synthetic',)))
    with ws.store.connect() as db:
        assert db.execute('SELECT count(*) FROM source_versions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM source_originals').fetchone()[0] == 0


def test_legacy_database_original_remains_readable(tmp_path):
    ws = workspace(tmp_path)
    data = pdf_bytes(('Legacy synthetic page',))
    sid = Catalog(ws.store).import_file('legacy.pdf', data)['source']['id']
    before = digest(ContentStore.source_payload(ws.store.sources([sid])[0]))
    with ws.store.connect() as db:
        db.execute('DELETE FROM source_originals WHERE source_id=?', (sid,))
        db.execute('UPDATE source_versions SET original=? WHERE id=?', (data, sid))
        db.execute('DROP TABLE source_originals')
    reopened = Workspace(Store(tmp_path))
    assert source_page_info(reopened, sid, 1)['native_text'] == 'Legacy synthetic page'
    assert digest(ContentStore.source_payload(reopened.store.sources([sid])[0])) == before


def test_external_storage_rejects_symlink_outside_case(tmp_path):
    ws = workspace(tmp_path / 'case')
    outside = tmp_path / 'foreign'
    outside.mkdir()
    (ws.store.root / 'sources' / 'objects').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ActionRejected, match='SOURCE_ORIGINAL_OUTSIDE_PROJECT'):
        Catalog(ws.store).import_file('escaped.pdf', pdf_bytes(('Synthetic',)))


def test_external_storage_rejects_non_regular_original(tmp_path):
    ws = workspace(tmp_path)
    data = pdf_bytes(('Synthetic imported page',))
    sid = Catalog(ws.store).import_file('imported.pdf', data)['source']['id']
    path = tmp_path / 'sources' / 'objects' / hashlib.sha256(data).hexdigest()
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ActionRejected, match='SOURCE_ORIGINAL_UNAVAILABLE'):
        source_page_info(ws, sid, 1)


def test_external_storage_rejects_oversized_original_before_reading(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    data = pdf_bytes(('Synthetic imported page',))
    sid = Catalog(ws.store).import_file('imported.pdf', data)['source']['id']
    path = tmp_path / 'sources' / 'objects' / hashlib.sha256(data).hexdigest()
    with path.open('wb') as f:
        f.truncate(2**30)
    from report_agent import original_storage
    fdopen = original_storage.os.fdopen
    class GuardedFile:
        def __init__(self, file): self.file = file
        def __enter__(self): self.file.__enter__(); return self
        def __exit__(self, *args): return self.file.__exit__(*args)
        def fileno(self): return self.file.fileno()
        def read(self, *args): raise AssertionError('oversized original was read')
    monkeypatch.setattr(original_storage.os, 'fdopen', lambda fd, mode: GuardedFile(fdopen(fd, mode)))
    with pytest.raises(ActionRejected, match='SOURCE_ORIGINAL_SHA256_MISMATCH'):
        source_page_info(ws, sid, 1)


def test_page_block_lookup_uses_store_boundary(tmp_path, monkeypatch):
    from report_agent.document_tools import _frozen_page_blocks
    ws = workspace(tmp_path)
    seen = []
    monkeypatch.setattr(ws.store, 'source_page_blocks', lambda source_id, page: seen.append((source_id, page)) or ['block'])
    assert _frozen_page_blocks(ws, 'source', 7) == ['block']
    assert seen == [('source', 7)]


def test_store_read_only_contract_rejects_writes(tmp_path):
    ws = workspace(tmp_path)
    with ws.store.read_only() as db:
        assert db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO state VALUES ('synthetic-write','0')")
        db.execute('PRAGMA query_only=OFF')
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO state VALUES ('synthetic-write','0')")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute('SELECT 1')
    original = ws.store.path
    held = original.with_name('temporarily-held.db')
    original.rename(held)
    try:
        with pytest.raises(sqlite3.OperationalError):
            with ws.store.read_only():
                pass
        assert not original.exists()
    finally:
        held.rename(original)


def test_imported_external_original_table_and_word_image_export(tmp_path):
    from report_agent.exporting import export_docx
    from report_agent.source_tables import source_tables
    ws = workspace(tmp_path)
    ws.initialize()
    data = pdf_bytes(('Imported source for synthetic report',))
    sid = Catalog(ws.store).import_file('report-source.pdf', data)['source']['id']
    reopened = Workspace(Store(tmp_path))
    assert source_tables(reopened, sid, [1])[0]['status'] == 'no_tables_detected'
    task = reopened.request_task('draft', 'Create synthetic report', [])
    result = reopened.submit(task['id'], actor=task['owner'], title='Synthetic report',
        body=f'![Source](source-page://{sid}/1)', source_ids=[sid], input_ids=[])
    docx = export_docx(reopened, result['id'], template='technical_zh')
    with ZipFile(BytesIO(docx)) as package:
        images = [x for x in package.namelist() if x.startswith('word/media/')]
        assert len(images) == 1 and package.read(images[0]).startswith(b'\x89PNG\r\n\x1a\n')


def test_external_original_v4_snapshot_and_image_export(case):
    from report_agent.content_export import export_snapshot
    cs, co, writer, _, _ = case
    ws = Workspace(cs.store)
    data = pdf_bytes(('Synthetic page',))
    sid = Catalog(ws.store).import_file('synthetic.pdf', data)['source']['id']
    source = cs.import_inputs(co, 'external-image-input', [sid])['result']['source_refs'][0]
    objects = work(source)
    next(o for o in objects if o['client_key'] == 'a-body')['payload']['body']['text'] = f'![Source](source-page://{sid}/1)'
    next(o for o in objects if o['client_key'] == 'e')['payload']['excerpt'] = 'Synthetic page'
    cs.commit(writer, 'external-image-save', objects, deliverable_selection={
        'kind':'saved_work', 'root_ref':{'client_key':'a'}, 'include_current_save':True,
        'members_from':[], 'workbook_refs':[{'client_key':'sheet'}]})
    result = export_snapshot(cs, writer, 'external-image-export', None,
        deliverable={'kind':'deliverable','operation_id':'external-image-save'})['result']
    with ZipFile(cs.store.root / result['file_ref']) as package:
        images = [x for x in package.namelist() if x.startswith('word/media/')]
        assert len(images) == 1 and package.read(images[0]).startswith(b'\x89PNG\r\n\x1a\n')
