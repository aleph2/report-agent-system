"""Source originals remain immutable, verified and independent of old run folders."""
import hashlib
from types import SimpleNamespace

import pytest

from report_agent.catalog import Catalog
from report_agent.document_tools import _original
from report_agent.errors import ActionRejected
from report_agent.store import Store, encode


def catalog(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Test source storage', 'sources': [
        {'id': 'seed', 'title': 'seed', 'content': 'Synthetic seed', 'coverage': 'complete'}]})
    return Catalog(store)


def test_blob_descriptor_deduplicates_and_reads_exact_bytes(tmp_path):
    from report_agent.blob_store import BlobStore
    blobs = BlobStore(tmp_path)
    data = b'\x00synthetic immutable original\xff'
    descriptor = blobs.put(data, 'application/octet-stream')
    sha = hashlib.sha256(data).hexdigest()
    assert descriptor == {'sha256': sha, 'size': len(data),
        'media_type': 'application/octet-stream', 'path': f'blobs/{sha[:2]}/{sha}'}
    assert blobs.put(data, 'application/octet-stream') == descriptor
    assert blobs.read(descriptor) == data
    assert [p for p in (tmp_path / 'blobs').rglob('*') if p.is_file()] == [tmp_path / descriptor['path']]


def test_blob_read_and_reimport_do_not_silently_repair_corruption(tmp_path):
    from report_agent.blob_store import BlobStore
    blobs = BlobStore(tmp_path)
    descriptor = blobs.put(b'original', 'text/plain')
    path = tmp_path / descriptor['path']
    path.write_bytes(b'tampered')
    with pytest.raises((ActionRejected, ValueError), match='(?i)(hash|sha256|integrity|corrupt)'):
        blobs.read(descriptor)
    with pytest.raises((ActionRejected, ValueError), match='(?i)(hash|sha256|integrity|corrupt)'):
        blobs.put(b'original', 'text/plain')
    assert path.read_bytes() == b'tampered'


@pytest.mark.parametrize('path', ['../outside', '/tmp/outside', 'blobs/aa/../../outside'])
def test_blob_descriptor_cannot_escape_case(tmp_path, path):
    from report_agent.blob_store import BlobStore
    blobs = BlobStore(tmp_path)
    descriptor = blobs.put(b'synthetic', 'text/plain')
    with pytest.raises((ActionRejected, ValueError)):
        blobs.read({**descriptor, 'path': path})


def test_new_catalog_import_keeps_bytes_out_of_database_and_original_readable(tmp_path):
    cat = catalog(tmp_path)
    data = b'Synthetic original text for M1 storage'
    imported = cat.import_file('source.txt', data)['source']
    descriptor = imported['original_blob']
    assert (tmp_path / descriptor['path']).read_bytes() == data
    with cat.store.connect() as db:
        original, = db.execute('SELECT original FROM source_versions WHERE id=?', (imported['id'],)).fetchone()
        assert original in (None, b'')
    assert _original(SimpleNamespace(store=cat.store), imported['id'])[1] == data
    assert cat.import_file('source.txt', data)['source']['id'] == imported['id']
    assert cat.import_file('same-bytes.txt', data)['source']['original_blob']['path'] == descriptor['path']


def test_old_blob_row_still_reads_without_rewriting_archive(tmp_path):
    cat = catalog(tmp_path)
    data = b'Historical source original'
    source = {'id': 'historical', 'title': 'Historical', 'filename': 'historical.txt',
        'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'content': data.decode(),
        'document_id': 'historical', 'replaces_id': '', 'coverage': 'complete'}
    with cat.store.connect() as db:
        db.execute('INSERT INTO source_versions VALUES (?,?,?,?)',
            ('historical', 'historical-operation', encode(source), data))
    assert _original(SimpleNamespace(store=cat.store), 'historical')[1] == data
    with cat.store.connect() as db:
        assert db.execute('SELECT original FROM source_versions WHERE id=?', ('historical',)).fetchone()[0] == data
    assert not (tmp_path / 'blobs').exists() or not list((tmp_path / 'blobs').rglob('*'))


def test_cleanup_preserves_references_and_refuses_while_project_is_running(tmp_path):
    from report_agent.blob_store import BlobStore
    cat = catalog(tmp_path)
    source = cat.import_file('keep.txt', b'Referenced original')['source']
    orphan = BlobStore(tmp_path).put(b'Unreferenced original', 'text/plain')
    with cat.store.run_lock(), pytest.raises(RuntimeError, match='ALREADY_RUNNING'):
        cat.collect_unreferenced_blobs()
    assert (tmp_path / orphan['path']).exists()
    cat.collect_unreferenced_blobs()
    assert not (tmp_path / orphan['path']).exists()
    assert _original(SimpleNamespace(store=cat.store), source['id'])[1] == b'Referenced original'


def test_import_rollback_leaves_no_false_source_and_cleanup_can_remove_orphan(tmp_path):
    import sqlite3
    cat = catalog(tmp_path)
    with cat.store.connect() as db:
        db.execute("""CREATE TRIGGER refuse_source BEFORE INSERT ON events
            WHEN NEW.kind='source_imported' BEGIN SELECT RAISE(ABORT, 'synthetic rollback'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic rollback'):
        cat.import_file('failed.txt', b'Synthetic failed import')
    assert not [s for s in cat.metadata() if s.get('filename') == 'failed.txt']
    cat.collect_unreferenced_blobs()
    assert not [p for p in (tmp_path / 'blobs').rglob('*') if p.is_file()]
