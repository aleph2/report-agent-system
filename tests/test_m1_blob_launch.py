"""Fresh-case checks cover referenced files before a provider can be configured."""
import hashlib
import json
import runpy
import sqlite3

import pytest

from report_agent.blob_store import BlobStore
from report_agent.catalog import Catalog
from report_agent.errors import ActionRejected
from report_agent.store import Store, digest, encode
from test_m1_blob_store import catalog
from test_pilot_m1_preparation import ROOT, put_json, stage_fixture


def verify(case):
    from report_agent.blob_store import verify_case_blobs
    return verify_case_blobs(case)


def test_blob_preflight_is_read_only_and_counts_shared_content_once(tmp_path, monkeypatch):
    cat = catalog(tmp_path)
    content = b'Shared synthetic original'
    cat.import_file('a.txt', content)
    cat.import_file('b.txt', content)
    before = cat.store.path.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('Preflight must not initialize Store or Catalog')

    monkeypatch.setattr(Store, '__init__', forbidden)
    monkeypatch.setattr(Catalog, '__init__', forbidden)
    assert verify(tmp_path) == {'verified_blobs': 1, 'verified_bytes': len(content)}
    assert cat.store.path.read_bytes() == before


def test_blob_preflight_refuses_missing_database_without_creating_case(tmp_path):
    case = tmp_path / 'missing-case'
    with pytest.raises((ActionRejected, RuntimeError, FileNotFoundError), match='(?i)(case|database|missing)'):
        verify(case)
    assert not case.exists()


@pytest.mark.parametrize('fault', ['missing', 'corrupt', 'escape', 'source-sha', 'source-size'])
def test_blob_preflight_rejects_changed_source_storage(tmp_path, fault):
    cat = catalog(tmp_path)
    source = cat.import_file('a.txt', b'Synthetic source')['source']
    path = tmp_path / source['original_blob']['path']
    if fault == 'missing':
        path.unlink()
    elif fault == 'corrupt':
        path.write_bytes(b'Corrupted source')
    else:
        with cat.store.connect() as db:
            row = db.execute('SELECT data FROM source_versions WHERE id=?', (source['id'],)).fetchone()
            data = json.loads(row[0])
            if fault == 'escape':
                data['original_blob']['path'] = '../outside'
            elif fault == 'source-sha':
                data['sha256'] = '0' * 64
            else:
                data['bytes'] += 1
            db.execute('UPDATE source_versions SET data=? WHERE id=?', (encode(data), source['id']))
    before = cat.store.path.read_bytes()
    with pytest.raises((ActionRejected, RuntimeError, ValueError)):
        verify(tmp_path)
    assert cat.store.path.read_bytes() == before


def test_blob_preflight_preserves_legacy_inline_original_without_migration(tmp_path):
    cat = catalog(tmp_path)
    content = b'Historical source original'
    source = {'id': 'historical', 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
    with cat.store.connect() as db:
        db.execute('INSERT INTO source_versions VALUES (?,?,?,?)',
                   ('historical', 'historical-operation', encode(source), content))
    before = cat.store.path.read_bytes()
    assert verify(tmp_path) == {'verified_blobs': 0, 'verified_bytes': 0}
    assert cat.store.path.read_bytes() == before and not (tmp_path / 'blobs').exists()


def test_blob_preflight_checks_capture_logical_identity_not_only_blob_hash(tmp_path):
    cat = catalog(tmp_path)
    captured = {'purpose': 'writer', 'public_input': {'messages': [{'content': 'Synthetic capture'}]}}
    blob = BlobStore(tmp_path).put(encode(captured).encode(), 'application/json')
    cat.store.set('prompt_capture:' + digest(captured), {'capture_blob': blob})
    assert verify(tmp_path) == {'verified_blobs': 1, 'verified_bytes': blob['size']}
    with cat.store.connect() as db:
        db.execute('UPDATE state SET key=? WHERE key=?',
            ('prompt_capture:' + '0' * 64, 'prompt_capture:' + digest(captured)))
    with pytest.raises((ActionRejected, RuntimeError, ValueError), match='(?i)(capture|identity|integrity)'):
        verify(tmp_path)


def prepared_run(tmp_path, monkeypatch):
    stage, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    stage['stage'](args)
    host = runpy.run_path(str(args.run / 'host.py'), run_name='blob_launch_fixture')
    state = host['prepare'].__globals__
    monkeypatch.setitem(state, 'endpoint_pins', lambda: {'coordinator': 'offline-endpoint-pin'})
    monkeypatch.setitem(state, 'CANONICAL', tmp_path / 'unrelated-missing.db')
    state['prepare']()
    put_json(args.run / 'neo-approval.json', {'approved': True,
        'host_sha256': state['sha'](args.run / 'host.py'),
        'prepared_sha256': state['sha'](args.run / 'prepared.json')})
    return args.run, state


@pytest.mark.parametrize('fault', ['missing', 'corrupt'])
def test_actual_checked_intent_refuses_blob_drift_with_all_old_pins_unchanged(tmp_path, monkeypatch, fault):
    from report_agent import blob_store
    run, state = prepared_run(tmp_path, monkeypatch)
    checked = runpy.run_path(str(ROOT / 'scripts/launch_report.py'))['checked_intent']

    def wrong_checkout(*args, **kwargs):
        raise AssertionError('Launch must verify with pinned staged source, not cached checkout code')

    monkeypatch.setattr(blob_store, 'verify_case_blobs', wrong_checkout)
    assert checked(run)['automatic_host_relaunch'] is False
    path = next(p for p in (run / 'case/blobs').rglob('*') if p.is_file())
    if fault == 'missing':
        path.unlink()
    else:
        path.write_bytes(b'Changed after preparation')
    with pytest.raises((ActionRejected, RuntimeError, ValueError), match='(?i)(blob|integrity)'):
        checked(run)
    assert not (run / 'run-launch-intent.json').exists()
    assert not (run / 'started.json').exists()


async def test_actual_host_run_checks_blobs_before_provider_setup(tmp_path, monkeypatch):
    from report_agent import model_config
    run, state = prepared_run(tmp_path, monkeypatch)
    path = next(p for p in (run / 'case/blobs').rglob('*') if p.is_file())
    path.unlink()
    setup = []

    def forbidden(*args, **kwargs):
        setup.append(True)
        raise AssertionError('Provider setup must not precede source verification')

    monkeypatch.setattr(model_config, 'load_mixed_services', forbidden)
    with pytest.raises((ActionRejected, RuntimeError, ValueError), match='(?i)(blob|integrity)'):
        await state['run']()
    assert setup == [] and not (run / 'started.json').exists()


@pytest.mark.parametrize('entry', ['checked_intent', 'host_run'])
async def test_fresh_launch_refuses_committed_wal_drift_without_checkpointing(tmp_path, monkeypatch, entry):
    from report_agent import model_config
    run, state = prepared_run(tmp_path, monkeypatch)
    prepared = json.loads((run / 'prepared.json').read_text())
    database = run / 'case/state.db'
    writer = sqlite3.connect(database)
    setup = []

    def forbidden(*args, **kwargs):
        setup.append(True)
        raise AssertionError('Provider setup must not precede fresh-case integrity checks')

    monkeypatch.setattr(model_config, 'load_mixed_services', forbidden)
    try:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        manifest = json.loads(writer.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
        manifest['goal'] = 'Unapproved post-preparation commission change'
        writer.execute("UPDATE state SET value=? WHERE key='manifest'", (encode(manifest),))
        writer.commit()
        wal = run / 'case/state.db-wal'
        assert wal.stat().st_size > 0
        assert state['sha'](database) == prepared['state_sha256']
        wal_before = wal.read_bytes()
        with pytest.raises((ActionRejected, RuntimeError, ValueError), match='(?i)(wal|fresh|integrity)'):
            if entry == 'checked_intent':
                runpy.run_path(str(ROOT / 'scripts/launch_report.py'))['checked_intent'](run)
            else:
                await state['run']()
        assert state['sha'](database) == prepared['state_sha256']
        assert wal.read_bytes() == wal_before
        assert setup == [] and not (run / 'started.json').exists()
        assert not (run / 'run-launch-intent.json').exists()
    finally:
        writer.close()
