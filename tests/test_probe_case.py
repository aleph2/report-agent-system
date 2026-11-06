"""Business-only probe imports preserve approval and own every runtime input."""
from pathlib import Path
import hashlib
import json
import sqlite3

import pytest

from report_agent.probe_case import prepare_probe_case
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.content_store import ContentStore
from report_agent.commission_plan import _confirmed
from report_agent.writer_runtime import writer_session
from report_agent.writer_assessment import read_assignment
from report_agent.writer_assignments import read_assignment_pages, read_assigned_page
from test_writer_assignments import assigned, method_commission
from test_deep_runtime import Driver
from test_m1_g4_requirements import anchored, required_case, confirm


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.name.endswith(('-shm', '-wal'))}


@pytest.fixture
def target(tmp_path_factory):
    return tmp_path_factory.mktemp('independent-probe') / 'case'


def prepare(f, target, **changes):
    pins = {'expected_plan_ref': f.ws.store.get('commission_plan'),
            'expected_decision_ref': f.ws.store.get('commission_confirmation')}
    return prepare_probe_case(f.ws.store.root, target, **{**pins, **changes})


def test_import_preserves_business_identity_without_old_execution_state(assigned, target):
    f = assigned
    source = f.ws.store.root
    f.ws.store.set('model_recovery_policy', {'forbidden':'old recovery'})
    f.ws.store.set('model_recovery_call:old', {'forbidden':'old raw'})
    f.ws.store.set('native_delegation:old', {'forbidden':'old task'})
    f.ws.store.set('prompt_capture:old', {'forbidden':'old prompt'})
    f.ws.store.set('tool_observation:old', {'forbidden':'old observation'})
    f.ws.store.set('report_error', 'historical timeout')
    f.ws.store.set('runtime', {'forbidden':'old runtime'})
    from report_agent.blob_store import BlobStore
    private_blob = BlobStore(source).put(b'old private prompt', 'application/json')
    for name in ('checkpoints.db','assessment-completion-checkpoints.db','runtime-metrics.jsonl'):
        (source / name).write_bytes(b'old execution must not cross')
    (source / 'outputs').mkdir(exist_ok=True)
    (source / 'outputs' / 'old.md').write_text('old writer prose')
    before = hashes(source)
    receipt = prepare(f, target)
    assert receipt['source_unchanged'] is True
    assert hashes(source) == before
    assert receipt['case_root'] == str(target)
    assert receipt['plan_ref'] == f.plan_ref
    assert receipt['decision_ref'] == f.ws.store.get('commission_confirmation')
    assert len(receipt['source_db_sha256']) == len(receipt['frozen_db_sha256']) == 64
    store = Store(target); cs = ContentStore(store)
    with store.connect() as db:
        plan, decision = _confirmed(cs, db)
        keys = {r[0] for r in db.execute('SELECT key FROM state')}
        assert not any(k.startswith(('model_recovery','native_','prompt_','tool_observation','runtime')) for k in keys)
        assert not db.execute('SELECT 1 FROM content_versions WHERE type="DelegatedTask"').fetchone()
        assert not db.execute('SELECT 1 FROM content_operations').fetchone()
        assert not db.execute('SELECT 1 FROM content_observations').fetchone()
        assert not db.execute('SELECT 1 FROM events').fetchone()
        assert not db.execute('SELECT 1 FROM results').fetchone()
    assert plan == f.cs.read(f.plan_ref)
    assert decision == f.cs.read(receipt['decision_ref'])
    assert not (target / 'checkpoints.db').exists()
    assert not (target / 'assessment-completion-checkpoints.db').exists()
    assert not (target / 'outputs' / 'old.md').exists()
    assert not (target / private_blob['path']).exists()
    assert json.loads((target / 'probe-import.json').read_text()) == receipt


def test_import_is_runtime_independent_when_source_no_longer_exists(assigned, target, monkeypatch):
    f = assigned
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract':'system-assembler-v1'})
    receipt = prepare(f, target)
    source = f.ws.store.root
    retired = source.with_name(source.name + '-unavailable')
    source.rename(retired)
    original_open = Path.open
    original_connect = sqlite3.connect
    def blocked(path):
        text = str(path).removeprefix('file://').split('?')[0]
        return text.startswith(str(source)) or text.startswith(str(retired))
    def guarded_open(path, *args, **kwargs):
        assert not blocked(path), 'old source file dependency'
        return original_open(path, *args, **kwargs)
    def guarded_connect(path, *args, **kwargs):
        assert not blocked(path), 'old source SQLite dependency'
        return original_connect(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    store = Store(target); ws = Workspace(store); cs = ContentStore(store)
    with writer_session(ws, f.plan['objects'][0]['label'], Driver(writer=[])('writer')) as session:
        packet = read_assignment(cs, session.actor)
        assert packet['object_label'] == f.plan['objects'][0]['label']
        pages = read_assignment_pages(cs, session.actor)
        source_handle = next(s['source_handle'] for s in pages['sources'] if s['title'] == 'design')
        page = read_assigned_page(cs, session.actor, source_handle, 3, include_image=False)
        assert page['native_text'] == 'Drawing K1p250'
    assert receipt['dependency_manifest']['runtime_case_root'] == str(target)


@pytest.mark.parametrize('pin', ['expected_plan_ref','expected_decision_ref'])
def test_exact_approved_pins_are_required(assigned, target, pin):
    with pytest.raises(ValueError, match='PIN'):
        prepare(assigned, target, **{pin:{'type':'CommissionPlan','id':'wrong','version':1}})


@pytest.mark.parametrize('kind', ['same','child','parent','exists'])
def test_target_is_exclusive_and_outside_source_tree(assigned, target, kind):
    source = assigned.ws.store.root
    chosen = source if kind == 'same' else source / 'child' if kind == 'child' else source.parent if kind == 'parent' else target
    if kind == 'exists':
        chosen.mkdir()
        (chosen / 'keep').write_text('untouched')
    with pytest.raises((ValueError, FileExistsError)):
        prepare(assigned, chosen)
    if kind == 'exists':
        assert (chosen / 'keep').read_text() == 'untouched'


def test_tampered_source_blob_cannot_be_published(assigned, target):
    f = assigned
    source = next(s for s in f.ws.store.sources([f.pdf_source_id]) if s['id'] == f.pdf_source_id)
    (f.ws.store.root / source['original_blob']['path']).write_bytes(b'corrupt synthetic blob')
    with pytest.raises(Exception, match='INTEGRITY'):
        prepare(f, target)
    assert not (target / 'probe-import.json').exists()


def test_business_payload_integrity_is_checked_before_acceptance(assigned, target):
    f = assigned
    with f.ws.store.connect() as db:
        row = db.execute('SELECT data FROM content_versions WHERE type=? AND id=? AND version=?',
                         tuple(f.plan_ref[k] for k in ('type','id','version'))).fetchone()
        record = json.loads(row[0]); record['payload']['deliverables'] = ['tampered']
        db.execute('UPDATE content_versions SET data=? WHERE type=? AND id=? AND version=?',
                   (json.dumps(record), *[f.plan_ref[k] for k in ('type','id','version')]))
    with pytest.raises(ValueError, match='INTEGRITY'):
        prepare(f, target)
    assert not (target / 'probe-import.json').exists()


def test_copied_source_authority_remains_bound_and_never_inherits_old_task(assigned, target):
    from report_agent.source_use import configure_source_use
    f = assigned
    authority = configure_source_use(f.ws.store, [s['id'] for s in f.ws.store.source_catalog()], 'synthetic approved source')
    prepare(f, target)
    store = Store(target)
    assert store.get('source_use_authority_binding') == authority
    assert store.get('source_use_authority:' + authority) == f.ws.store.get('source_use_authority:' + authority)
    assert store.get('source_use_task_binding:' + f.actor.task_id) is None



def test_current_requirements_and_previous_immutable_versions_survive(required_case, target):
    from test_m1_commission_plan import save
    f = required_case
    saved = save(f)
    confirm(f, saved)
    receipt = prepare(f, target)
    store = Store(target); cs = ContentStore(store)
    assert store.get('commission_requirements') == f.requirements_ref
    with store.connect() as db:
        plan, decision = _confirmed(cs, db)
        assert plan['ref'] == saved['plan_ref']
        assert decision['payload']['requirements_ref'] == f.requirements_ref
    assert cs.read(f.initial_requirements['ref']) == f.initial_requirements
    assert receipt['dependency_manifest']['old_execution_state_imported'] is False


def test_readonly_backup_preserves_nonempty_committed_wal(assigned, target):
    f = assigned
    with sqlite3.connect(f.ws.store.path) as writer:
        writer.execute('INSERT INTO state VALUES (?,?)', ('unused-test-key', json.dumps('committed WAL evidence')))
        writer.commit()
        wal = f.ws.store.root / 'state.db-wal'
        assert wal.stat().st_size > 0
        before = hashlib.sha256(wal.read_bytes()).hexdigest()
        receipt = prepare(f, target)
        assert hashlib.sha256(wal.read_bytes()).hexdigest() == before
        assert receipt['source_database_files']['state.db-wal'] == before
    assert Store(target).get('unused-test-key') is None


def test_manifest_file_paths_are_not_silently_retained_as_runtime_dependencies(assigned, target):
    f = assigned
    manifest = f.ws.store.manifest
    manifest['sources'][0]['copied_path'] = 'sources/not-imported.pdf'
    f.ws.store.set('manifest', manifest)
    with pytest.raises(ValueError, match='SOURCE_PATH'):
        prepare(f, target)
