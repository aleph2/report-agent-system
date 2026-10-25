"""Copy original inputs/OCR only into a fresh autonomous trial; never old outcomes."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from report_agent.catalog import Catalog
from report_agent.store import Store, encode
from report_agent.workspace import Workspace


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(baseline: Path, destination: Path):
    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError('NEW_ISOLATED_DESTINATION_REQUIRED')
    with sqlite3.connect((baseline / 'state.db').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        original = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
        if db.execute('SELECT count(*) FROM source_versions').fetchone()[0]:
            raise ValueError('TRIAL_REQUIRES_FROZEN_MANIFEST_SOURCES')
        blocks = db.execute('SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal').fetchall()
    # Explicit root allowlist: no imported artifacts, feedback or previously judged uses.
    manifest = {key: original[key] for key in ('goal', 'sources', 'scope_instruction') if key in original}
    source_ids = {s['id'] for s in manifest['sources']}
    if {r[0] for r in blocks} != source_ids:
        raise ValueError('BASELINE_SOURCE_INDEX_INCOMPLETE')
    scope = manifest.get('scope_instruction')
    sources = manifest['sources'] + ([scope] if isinstance(scope, dict) and scope.get('copied_path') else [])
    copies = []
    for source in sources:
        relative = Path(source['copied_path'])
        src, dst = (baseline / relative).resolve(), (destination / relative).resolve()
        if relative.is_absolute() or not src.is_relative_to(baseline / 'sources') or not dst.is_relative_to(destination / 'sources'):
            raise ValueError('SOURCE_PATH_NOT_PROJECT_BOUND')
        if file_hash(src) != source['sha256']:
            raise ValueError('BASELINE_SOURCE_HASH_MISMATCH')
        copies.append((source, src, dst))
    public_scope = scope.get('text', '') if isinstance(scope, dict) else scope
    manifest['export'] = {'template': 'technical_zh', 'metadata': {'scope': public_scope or manifest['goal']}}
    for source, src, dst in copies:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if file_hash(dst) != source['sha256']:
            raise ValueError('COPIED_SOURCE_HASH_MISMATCH')
    store = Store(destination)
    store.initialize(manifest)
    Catalog(store)
    with store.connect() as db:
        db.execute('DELETE FROM source_blocks')
        db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)', blocks)
    workspace = Workspace(store)
    workspace.initialize()
    if workspace.results() or store.get('knowledge_project_id') or (destination / 'checkpoints.db').exists():
        raise ValueError('CLEAN_START_REQUIRED')
    repo = Path(__file__).resolve().parents[1]
    code = [*sorted((repo / 'src/report_agent').rglob('*.py')), repo / 'pyproject.toml']
    receipt = {'baseline': str(baseline), 'source_blocks': len(blocks),
               'goal_sha256': hashlib.sha256(manifest['goal'].encode()).hexdigest(),
               'source_index_sha256': hashlib.sha256(encode(blocks).encode()).hexdigest(),
               'sources': [{'id': s.get('id'), 'filename': s.get('filename'), 'sha256': s['sha256']} for s in sources],
               'code_sha256': {str(p.relative_to(repo)): file_hash(p) for p in code},
               'copied_results': False, 'copied_reviews': False, 'copied_feedback': False,
               'copied_issues': False, 'copied_graph': False, 'copied_checkpoints': False, 'new_ocr': False}
    store.set('clean_import', receipt)
    store.event('clean_inputs_imported', receipt)
    (destination / 'import-receipt.json').write_text(encode(receipt), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    print(encode(prepare(args.baseline, args.project)))
