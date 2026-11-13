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
from . import commission_assertions, commission_imports, legacy_state as legacy, plan_authority, plan_inputs
from .content_store import ContentStore
from .store import Store, digest, encode
from .workspace import Workspace

BUSINESS_TYPES = frozenset({
    'PlanSkeleton', 'PlanTextProfiles', *commission_imports.TYPES,
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
    return {name: _sha(root / name) for name in ('state.db', 'state.db-wal', 'assertions.sqlite3', 'assertions.sqlite3-wal')
            if (root / name).exists() and (name == 'state.db' or (root / name).stat().st_size)}


def _content_closure(db, state, plan_inputs_and_pins):
    # Carryover's old origin/source pins are historical provenance, not live refs.
    roots = [v for k, v in state.items() if k != 'commission_carryover']
    if state.get('commission_carryover'):
        roots.append(state['commission_carryover'].get('items', []))
    pending = [r for value in [*roots, plan_inputs_and_pins] for r in refs_in(value)]
    records = {}
    positions = {}
    while pending:
        ref = pending.pop()
        if ref.key() in records:
            continue
        if ref.type not in BUSINESS_TYPES:
            raise ValueError('PROBE_NONBUSINESS_DEPENDENCY')
        row = db.execute('SELECT rowid,data FROM content_versions WHERE type=? AND id=? AND version=?', ref.key()).fetchone()
        if row is None:
            raise ValueError('PROBE_BUSINESS_DEPENDENCY_MISSING')
        position, raw = row
        record = json.loads(raw)
        if record['ref'] != ref.model_dump() or record['payload_digest'] != digest(record['payload']):
            raise ValueError('PROBE_BUSINESS_INTEGRITY_MISMATCH')
        records[ref.key()] = record
        positions[ref.key()] = position
        pending.extend(refs_in(record))
    return {key: records[key] for key in sorted(records, key=positions.__getitem__)}


def _page_evidence(directory, plan, decision):
    from .assertions.launch import Commission
    from .source_use import immutable_version_digest
    from . import page_bindings
    rows = commission_assertions._rows(directory)
    questions = {body['id']: (body, status) for action, body, status in rows if action == 'ask'}
    sheets = []
    for action, body, status in rows:
        if action != 'decide' or not page_bindings.current(status) or body['claim']['reason'] != encode(decision):
            continue
        question, state = questions[body['claim']['target']]
        checkpoint = json.loads(question['claim']['text'])
        if checkpoint.get('plan_ref') == plan and 'page_bindings' in checkpoint:
            if not page_bindings.current(state):
                raise ValueError('PROBE_PAGE_SHEET_NOT_CURRENT')
            sheets.append(checkpoint)
    if not sheets:
        return [], [], []
    if len(sheets) != 1:
        raise ValueError('PROBE_PAGE_SHEET_AMBIGUOUS')
    wanted = set(sheets[0]['page_bindings'])
    bindings = [(body, state) for body, state in Commission.page_records(directory) if body['id'] in wanted]
    if {body['id'] for body, _ in bindings} != wanted or any(
            body['claim'].get('rule') != encode(plan) or body['claim'].get('scope') != 'source_page_binding'
            or state['stale'] or state['challenged'] for body, state in bindings):
        raise ValueError('PROBE_PAGE_BINDING_IMPORT_MISMATCH')
    selected = [body for body, _ in bindings]
    with _read(Path(directory) / 'assertions.sqlite3') as db:
        for action, role, raw in db.execute('SELECT action,role,body FROM assertions ORDER BY rowid'):
            body = json.loads(raw)
            if body['claim'].get('target') in wanted:
                if (action, role) not in {('confirm', 'owner'), ('retract', 'owner')}:
                    raise ValueError('PROBE_PAGE_HISTORY_UNSUPPORTED')
                selected.append(body)
    versions = {page['source_version'] for body, _ in bindings
                for page in body['claim']['page_binding']['pages']}
    refs, found = [], set()
    with _read(Path(directory) / 'state.db') as db:
        for raw, in db.execute("SELECT data FROM content_versions WHERE type='SourceArtifact' ORDER BY rowid"):
            record = json.loads(raw)
            version = immutable_version_digest(record['payload'])
            if version in versions:
                refs.append(record['ref']);found.add(version)
    if found != versions:
        raise ValueError('PROBE_PAGE_SOURCE_DEPENDENCY_MISSING')
    return selected, refs, bindings


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
            if (plan_authority.plan_ref(original) != expected_plan_ref
                    or plan_authority.decision_ref(original) != expected_decision_ref):
                raise ValueError('PROBE_APPROVED_PIN_MISMATCH')
            from .commission_requirements import requirements_ref
            current_requirements = requirements_ref(original)
            original.backup(frozen)
        if (source / 'assertions.sqlite3').is_file():
            with _read(source / 'assertions.sqlite3') as original, closing(sqlite3.connect(Path(folder) / 'assertions.sqlite3')) as frozen:
                original.backup(frozen)
        page_actions, page_sources, expected_bindings = _page_evidence(Path(folder), expected_plan_ref, expected_decision_ref)
        frozen_sha = _sha(frozen_path)
        with _read(frozen_path) as frozen:
            state = legacy.read_probe_business_state(frozen)
            if any(s.get('copied_path') or s.get('original_path') for s in state['manifest']['sources']):
                raise ValueError('PROBE_MANIFEST_SOURCE_PATH_UNSUPPORTED')
            # Retired state keys from an old source never become authority in a new-format case.
            state.pop('commission_source_roles', None)
            state.pop('commission_owner_records', None)
            legacy_requirements = state.pop('commission_requirements', None)
            legacy_roles = legacy_owner = None
            if commission_imports.requires_source_policy(frozen):
                state.pop('source_use_authority_binding', None)
                legacy_requirements = None
            else:
                legacy_roles = commission_imports.source_roles(frozen)
                legacy_owner = commission_imports.owner_records(frozen)
                legacy_requirements = legacy_requirements or plan_authority.imported_historical_ref(frozen, 'CommissionRequirements')
                authority = state.get('source_use_authority_binding')
                if authority:
                    key = 'source_use_authority:' + authority
                    row = frozen.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
                    if row is None:
                        raise ValueError('PROBE_SOURCE_AUTHORITY_MISSING')
                    state[key] = json.loads(row[0])
            records = _content_closure(frozen, state, [expected_plan_ref, expected_decision_ref, legacy_owner, page_sources])
            plan = records[('CommissionPlan', expected_plan_ref['id'], expected_plan_ref['version'])]
            pinned = plan['payload'].get('requirements_ref')
            if pinned and current_requirements != pinned:
                raise ValueError('PROBE_APPROVED_REQUIREMENTS_MISMATCH')
            if legacy_requirements != pinned:
                legacy_requirements = None
            historical = plan_authority.historical_refs(frozen) == (expected_plan_ref, expected_decision_ref)
            legacy_skeleton = plan_inputs.get_skeleton(frozen) if historical else None
            legacy_profiles = plan_inputs.get_text_profiles(frozen) if historical else None
            if historical:
                records.update(_content_closure(frozen, {}, [legacy_skeleton, legacy_profiles]))
            versions = frozen.execute('SELECT id,operation,data,original FROM source_versions ORDER BY rowid').fetchall()
            blocks = frozen.execute('SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal').fetchall()
        # Completed access facts travel with the source version, not the old task's receipts.
        from .source_access import coverage
        frozen_store = Store(Path(folder))
        report = coverage(ContentStore(frozen_store), plan['payload'], include_page_totals=False)
        with frozen_store.connect() as db:
            previous_reads = plan_inputs._head(db, 'ImportedSourceReadFacts')
        read_facts = previous_reads['payload'] if previous_reads else []
        for row in report['sources']:
            pages = sorted(set(row['text_returned_pages'] + row['inspected_text_pages']
                               + [image['page'] for image in row['image_observations']]))
            for ref in row['source_version_refs']:
                if pages and tuple(ref[k] for k in ('type', 'id', 'version')) in records:
                    fact = {'source_ref': ref, 'pages': pages}
                    if fact not in read_facts:
                        read_facts.append(fact)
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

            if read_facts:
                plan_inputs._save('ImportedSourceReadFacts', db, read_facts)

            if legacy_skeleton is not None and ('PlanSkeleton', 'PlanSkeleton') not in heads:
                plan_inputs.save_skeleton(db, legacy_skeleton)
            if legacy_profiles is not None and ('PlanTextProfiles', 'PlanTextProfiles') not in heads:
                plan_inputs.save_text_profiles(db, legacy_profiles)
            if legacy_roles is not None and ('CommissionSourceRoles', 'CommissionSourceRoles') not in heads:
                plan_inputs._save('CommissionSourceRoles', db, legacy_roles)
            if legacy_owner is not None and ('CommissionOwnerRecords', 'CommissionOwnerRecords') not in heads:
                commission_imports.save_owner_records(db, legacy_owner)
            if historical or legacy_requirements:
                plan_authority.install_historical_refs(
                    db, expected_plan_ref if historical else None, expected_decision_ref if historical else None,
                    requirements=legacy_requirements)
        if not historical:
            plan_authority.copy_plan_evidence(Path(folder), output, records.values(),
                                              plan=expected_plan_ref, decision=expected_decision_ref)
            commission_assertions.copy_planning_evidence(Path(folder), output, records.values(),
                                                         plan=expected_plan_ref, decision=expected_decision_ref)

        if page_actions:
            from .assertions.launch import Commission
            from . import page_bindings
            Commission(output).import_plan_actions(Path(folder), lambda _: page_actions)
            actual = {body['id']: (body, state) for body, state in page_bindings.records(store, expected_plan_ref)}
            if any(actual.get(body['id']) != (body, state) for body, state in expected_bindings):
                raise ValueError('PROBE_PAGE_CONFIRMATION_STATE_CHANGED')

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
