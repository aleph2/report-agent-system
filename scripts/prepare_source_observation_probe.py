"""Prepare source-search candidate from a protected public-input snapshot; no model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from prepare_completed_feedback_recovery import no_links, tree_hashes
from prepare_review_trial017 import backup, baseline_lock, file_hash
from run_selected_evidence_probe import prepare_candidate
from report_agent.acceptance import active_criteria
from report_agent.review import reviewer_prompt
from report_agent.store import digest, encode


ROOT = Path(__file__).resolve().parents[1]


def runtime_files():
    paths = [*sorted((ROOT / 'src/report_agent').rglob('*.py')),
             *sorted((ROOT / 'src/report_agent/rules').glob('*.md')), ROOT / 'pyproject.toml']
    paths += [ROOT / 'scripts' / name for name in (
        'prepare_source_observation_probe.py', 'run_source_observation_probe.py',
        'run_selected_evidence_probe.py', 'prepare_clean_trial009.py',
        'prepare_completed_feedback_recovery.py', 'prepare_review_trial017.py',
        'run_deepagents_trial.py', 'run_grader_diagnostic.py')]
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths}


def protected_candidate(baseline: Path, destination: Path, draft_id: str, expected_body_sha256: str):
    """Old public importer sees only an owned temporary DB/source snapshot."""
    no_links(baseline.absolute())
    no_links(destination.absolute())
    baseline, destination = baseline.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(baseline) or baseline.is_relative_to(destination):
        raise ValueError('NEW_ISOLATED_DESTINATION_REQUIRED')
    if len(expected_body_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_body_sha256):
        raise ValueError('EXPLICIT_BODY_SHA256_REQUIRED')
    with baseline_lock(baseline):
        before = tree_hashes(baseline)
        with tempfile.TemporaryDirectory(prefix='source-probe043-public-input-') as folder:
            snapshot = Path(folder)
            # backup() copies main/WAL first and opens only its temporary snapshot.
            backup(baseline / 'state.db', snapshot / 'state.db')
            with sqlite3.connect((snapshot / 'state.db').as_uri() + '?mode=ro', uri=True) as db:
                db.execute('PRAGMA query_only=ON')
                manifest = json.loads(db.execute("SELECT value FROM state WHERE key='manifest'").fetchone()[0])
                selected = db.execute("SELECT value FROM state WHERE key='delivery'").fetchone()
                rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM results')]
            original = next((r for r in rows if r['id'] == draft_id and r['kind'] == 'draft'), None)
            if not original or not selected or json.loads(selected[0]).get('draft_id') != draft_id:
                raise ValueError('EXACT_SELECTED_SAVED_DRAFT_REQUIRED')
            if hashlib.sha256(original['body'].encode()).hexdigest() != expected_body_sha256:
                raise ValueError('DRAFT_BODY_HASH_MISMATCH')
            sources = list(manifest['sources'])
            scope = manifest.get('scope_instruction')
            if isinstance(scope, dict) and scope.get('copied_path'):
                sources.append(scope)
            for source in sources:
                relative = Path(source['copied_path'])
                original_path = (baseline / relative).resolve()
                target = (snapshot / relative).resolve()
                if (relative.is_absolute() or not original_path.is_relative_to(baseline / 'sources')
                        or not target.is_relative_to(snapshot / 'sources')):
                    raise ValueError('SOURCE_PATH_NOT_PROJECT_BOUND')
                no_links(baseline / relative)
                if file_hash(original_path) != source['sha256']:
                    raise ValueError('BASELINE_SOURCE_HASH_MISMATCH')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original_path, target)
                if file_hash(target) != source['sha256']:
                    raise ValueError('SNAPSHOT_SOURCE_HASH_MISMATCH')
            # This preserves the existing importer semantics and new-ID mapping;
            # its direct SQLite opens cannot create sidecars in the real baseline.
            workspace = prepare_candidate(snapshot, destination, draft_id)
        if tree_hashes(baseline) != before:
            raise ValueError('BASELINE_CHANGED_DURING_PREPARATION')
    receipt = json.loads((destination / 'candidate-import.json').read_text(encoding='utf-8'))
    receipt.update(baseline=str(baseline), source_read_method='locked_temporary_main_WAL_and_verified_sources',
                   temporary_snapshot_disposed=True, original_baseline_files_sha256=before,
                   baseline_tree_unchanged=True, model_calls=0)
    (destination / 'candidate-import.json').write_text(encode(receipt), encoding='utf-8')
    workspace.store.set('protected_candidate_import', receipt)
    workspace.store.event('protected_candidate_imported', {
        'baseline': str(baseline), 'draft_body_sha256': expected_body_sha256,
        'baseline_tree_unchanged': True, 'model_calls': 0})
    return workspace, receipt


def prepare(baseline, destination, draft_id, expected_body_sha256):
    from report_agent.source_search import configure_source_search
    workspace, imported = protected_candidate(baseline, destination, draft_id, expected_body_sha256)
    identity = configure_source_search(workspace, default_table_detail='references')
    selected = workspace.store.get('delivery')['draft_id']
    draft = next(r for r in workspace.results() if r['id'] == selected)
    criteria = active_criteria(workspace)
    freeze = {'version': 'native-source-observation043-v1', 'files': runtime_files(),
              'role_prompt': reviewer_prompt(requirement_acceptance=True),
              'source_search_identity': identity, 'draft_id': selected,
              'draft_body_sha256': hashlib.sha256(draft['body'].encode()).hexdigest(),
              'criteria_id': criteria['id'], 'criteria_body_sha256': hashlib.sha256(criteria['body'].encode()).hexdigest(),
              'manifest_sha256': digest(workspace.store.manifest),
              'original_baseline': imported['baseline'],
              'original_baseline_files_sha256': imported['original_baseline_files_sha256'],
              'criterion_id_mapping': imported['criterion_id_mapping'],
              'scope': 'One fresh autonomous native grader; no prior answers, author or revision loop.',
              'expected_model': 'glm-5.3', 'expected_reasoning_effort': 'high'}
    (destination / 'source-observation-freeze.json').write_text(encode(freeze), encoding='utf-8')
    return freeze


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--draft-id', required=True)
    parser.add_argument('--expected-body-sha256', required=True)
    args = parser.parse_args()
    result = prepare(args.baseline, args.output, args.draft_id, args.expected_body_sha256)
    print(encode({k: result[k] for k in ('version', 'draft_id', 'draft_body_sha256',
                                       'criteria_id', 'source_search_identity')}))
