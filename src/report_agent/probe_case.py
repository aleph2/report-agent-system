"""Trusted business-only import for a fresh probe, never a checkpoint continuation."""
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .blob_store import BlobStore
from .catalog import Catalog
from .content_models import refs_in
from . import legacy_state as legacy
from .content_store import ContentStore
from .store import Store, digest, encode
from .workspace import Workspace

BUSINESS_STATE = legacy.BUSINESS_STATE
BUSINESS_TYPES = frozenset({
    'CommissionPlan', 'CommissionDecision', 'CommissionRequirements', 'Requirement', 'SourceArtifact',
})


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def _read(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        yield db


def _db_hashes(root):
    # A read-only WAL reader may create empty WAL/SHM bookkeeping files.
    return {name: _sha(root / name) for name in ('state.db', 'state.db-wal')
            if (root / name).exists() and (name == 'state.db' or (root / name).stat().st_size)}


def _content_closure(db, state):
    # Carryover's old origin/source pins are historical provenance, not live refs.
    roots = [v for k, v in state.items() if k != 'commission_carryover']
    if state.get('commission_carryover'):
        roots.append(state['commission_carryover'].get('items', []))
    pending = [r for value in roots for r in refs_in(value)]
    records = {}
    while pending:
        ref = pending.pop()
        if ref.key() in records:
            continue
        if ref.type not in BUSINESS_TYPES:
            raise ValueError('PROBE_NONBUSINESS_DEPENDENCY')
        row = db.execute('SELECT data FROM content_versions WHERE type=? AND id=? AND version=?', ref.key()).fetchone()
        if row is None:
            raise ValueError('PROBE_BUSINESS_DEPENDENCY_MISSING')
        record = json.loads(row[0])
        if record['ref'] != ref.model_dump() or record['payload_digest'] != digest(record['payload']):
            raise ValueError('PROBE_BUSINESS_INTEGRITY_MISMATCH')
        records[ref.key()] = record
        pending.extend(refs_in(record))
    return records


def prepare_probe_case(source: Path, output: Path, *, expected_plan_ref, expected_decision_ref) -> dict:
    """Import an already approved business snapshot; this grants no model calls."""
    source, output = Path(source).absolute(), Path(output).absolute()
    if any(p.is_symlink() for path in (source, output) for p in (path, *path.parents)):
        raise ValueError('PROBE_PATH_SYMLINK_FORBIDDEN')
    source, output = source.resolve(), output.resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output) or output.exists():
        raise ValueError('NEW_ISOLATED_PROBE_CASE_REQUIRED')
    if not (source / 'state.db').is_file() or (source / 'state.db').is_symlink():
        raise ValueError('EXISTING_PROBE_SOURCE_REQUIRED')
    before = _db_hashes(source)
    with tempfile.TemporaryDirectory(prefix='probe-business-snapshot-') as folder:
        frozen_path = Path(folder) / 'state.db'
        with _read(source / 'state.db') as original, closing(sqlite3.connect(frozen_path)) as frozen:
            original.backup(frozen)
        frozen_sha = _sha(frozen_path)
        with _read(frozen_path) as frozen:
            state = legacy.read_probe_business_state(frozen)
            if (state.get('commission_plan') != expected_plan_ref
                    or state.get('commission_confirmation') != expected_decision_ref):
                raise ValueError('PROBE_APPROVED_PIN_MISMATCH')
            if any(s.get('copied_path') or s.get('original_path') for s in state['manifest']['sources']):
                raise ValueError('PROBE_MANIFEST_SOURCE_PATH_UNSUPPORTED')
            authority = state.get('source_use_authority_binding')
            if authority:
                key = 'source_use_authority:' + authority
                row = frozen.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
                if row is None:
                    raise ValueError('PROBE_SOURCE_AUTHORITY_MISSING')
                state[key] = json.loads(row[0])
            records = _content_closure(frozen, state)
            versions = frozen.execute('SELECT id,operation,data,original FROM source_versions ORDER BY rowid').fetchall()
            blocks = frozen.execute('SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal').fetchall()
        if _db_hashes(source) != before:
            raise ValueError('PROBE_SOURCE_CHANGED')

        output.mkdir(parents=True, exist_ok=False)
        store = Store(output)
        with store.connect() as db:
            legacy.insert_probe_business_state(db, state)
        Workspace(store)
        Catalog(store)
        cs = ContentStore(store)
        with store.connect() as db:
            db.execute('DELETE FROM source_blocks')
            db.executemany('INSERT INTO source_versions VALUES (?,?,?,?)', versions)
            db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)', blocks)
            db.executemany('INSERT INTO content_versions VALUES (?,?,?,?)',
                           [(*key, encode(record)) for key, record in records.items()])
            heads = {}
            for typ, identity, version in records:
                heads[typ, identity] = max(version, heads.get((typ, identity), 0))
            db.executemany('INSERT INTO content_heads VALUES (?,?,?)',
                           [(*key, version) for key, version in heads.items()])

        source_blobs, copied_blobs = BlobStore(source), BlobStore(output)
        dependencies = {}
        for _, _, raw, original in versions:
            value = json.loads(raw)
            ref = value.get('original_blob')
            if ref:
                data = source_blobs.read(ref)
                if value.get('sha256') != ref['sha256'] or value.get('bytes') != len(data):
                    raise ValueError('SOURCE_BLOB_INTEGRITY_MISMATCH')
                if copied_blobs.put(data, ref['media_type']) != ref:
                    raise ValueError('PROBE_SOURCE_BLOB_INTEGRITY_MISMATCH')
                dependencies[ref['path']] = ref
            elif value.get('sha256'):
                if hashlib.sha256(original).hexdigest() != value['sha256'] or len(original) != value['bytes']:
                    raise ValueError('SOURCE_ORIGINAL_INTEGRITY_MISMATCH')
        from .commission_plan import _confirmed
        from .deliverables import source_authority
        from .hierarchical_tools import actor_for
        with store.connect() as db:
            plan, decision = _confirmed(cs, db)
            if plan['ref'] != expected_plan_ref or decision['ref'] != expected_decision_ref:
                raise ValueError('PROBE_APPROVED_PIN_MISMATCH')
            sources = {s['id']: s for s in store.sources([r['payload']['source_id']
                       for r in records.values() if r['ref']['type'] == 'SourceArtifact'])}
            for record in records.values():
                if record['ref']['type'] == 'SourceArtifact':
                    value = record['payload']; original = sources[value['source_id']]
                    if (value['file_digest'] != (original.get('sha256') or digest(original['content']))
                            or value['content'] != original['content']):
                        raise ValueError('PROBE_SOURCE_PIN_INTEGRITY_MISMATCH')
            source_authority(cs, db, actor_for('coordinator'),
                             [r for r in records.values() if r['ref']['type'] == 'SourceArtifact'])
        if (_db_hashes(source) != before or any(_sha(source / path) != ref['sha256']
                                               for path, ref in dependencies.items())):
            raise ValueError('PROBE_SOURCE_CHANGED')
        receipt = {
            'version': 'business-only-probe-import-v1', 'case_root': str(output),
            'source': str(source), 'plan_ref': plan['ref'], 'decision_ref': decision['ref'],
            'source_db_sha256': before['state.db'], 'source_database_files': before,
            'frozen_db_sha256': frozen_sha, 'case_db_sha256': _sha(store.path),
            'source_unchanged': True, 'unchanged_scope': 'source_database_payload_nonempty_WAL_and_required_source_blobs',
            'reader_sidecar_note': 'SQLite mode=ro may create empty WAL/SHM lock metadata; no journal-mode change or immutable bypass.',
            'dependency_manifest': {
                'runtime_case_root': str(output), 'state_keys': sorted(state),
                'business_state_sha256': digest(state),
                'content_records': [{'ref': r['ref'], 'record_sha256': digest(r)} for r in records.values()],
                'source_versions_sha256': digest([r[:3] for r in versions]),
                'source_blocks_sha256': digest(blocks), 'blobs': list(dependencies.values()),
                'historical_carryover_provenance_retained': 'commission_carryover' in state,
                'old_execution_state_imported': False,
            },
        }
        with (output / 'probe-import.json').open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        return receipt
