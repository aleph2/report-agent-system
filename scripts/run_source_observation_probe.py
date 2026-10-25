"""Run one prepared native source-view candidate; no replay or semantic retry."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from prepare_completed_feedback_recovery import no_links, tree_hashes
from prepare_review_trial017 import file_hash
from prepare_source_observation_probe import runtime_files
from run_selected_evidence_probe import run_candidate
from report_agent.acceptance import active_criteria
from report_agent.deep_models import error_data
from report_agent.review import reviewer_prompt
from report_agent.store import Store, digest, encode
from report_agent.workspace import Workspace


def verify(workspace, freeze):
    from report_agent.source_search import bind_source_search
    if freeze['version'] != 'native-source-observation043-v1' or runtime_files() != freeze['files']:
        raise ValueError('FROZEN_RUNTIME_CHANGED')
    if reviewer_prompt(requirement_acceptance=True) != freeze['role_prompt']:
        raise ValueError('FROZEN_ROLE_CHANGED')
    if bind_source_search(workspace) != freeze['source_search_identity']:
        raise ValueError('SOURCE_SEARCH_BINDING_CHANGED')
    if digest(workspace.store.manifest) != freeze['manifest_sha256']:
        raise ValueError('FROZEN_MANIFEST_CHANGED')
    draft = workspace.result(freeze['draft_id'])
    standard = active_criteria(workspace)
    if (workspace.store.get('delivery')['draft_id'] != draft['id']
            or hashlib.sha256(draft['body'].encode()).hexdigest() != freeze['draft_body_sha256']
            or standard['id'] != freeze['criteria_id']
            or hashlib.sha256(standard['body'].encode()).hexdigest() != freeze['criteria_body_sha256']):
        raise ValueError('FROZEN_CANDIDATE_OR_CRITERIA_CHANGED')
    sources = list(workspace.store.manifest['sources'])
    scope = workspace.store.manifest.get('scope_instruction')
    if isinstance(scope, dict) and scope.get('copied_path'):
        sources.append(scope)
    for source in sources:
        path = workspace.store.root / source['copied_path']
        no_links(path)
        if not path.resolve().is_relative_to(workspace.store.root / 'sources') or file_hash(path) != source['sha256']:
            raise ValueError('FROZEN_SOURCE_FILE_CHANGED')
    if tree_hashes(Path(freeze['original_baseline'])) != freeze['original_baseline_files_sha256']:
        raise ValueError('PROTECTED_BASELINE_CHANGED')
    return True


async def run(args, *, invoke=run_candidate):
    project = args.project.resolve()
    no_links(project)
    # Check before Store can create an accidental empty project.
    frozen_path = project / 'source-observation-freeze.json'
    freeze = json.loads(frozen_path.read_text(encoding='utf-8'))
    frozen_hash = file_hash(frozen_path)
    if (project / 'receipt.json').exists() or (project / 'source-observation-execution.json').exists():
        raise ValueError('ALREADY_ATTEMPTED_NO_AUTOMATIC_REPLAY')
    workspace = Workspace(Store(project))
    with workspace.store.run_lock():
        verify(workspace, freeze)
        if workspace.store.get('rubric_targets') or any(e['kind'] == 'deep_model_request' for e in workspace.store.events()):
            raise ValueError('PRISTINE_PREPARED_REVIEW_REQUIRED')
        record = {'authorization': args.authorization_note,
                  'started': datetime.now(timezone.utc).isoformat(), 'status': 'attempted',
                  'frozen_input_sha256': frozen_hash, 'source_search_identity': freeze['source_search_identity'],
                  'scope': freeze['scope']}
        execution_path = project / 'source-observation-execution.json'
        with execution_path.open('x', encoding='utf-8') as stream:
            stream.write(encode(record))
        try:
            receipt = await invoke(workspace, SimpleNamespace(
                output=project, credential_container=args.credential_container,
                authorization_note=args.authorization_note), extra_freeze=freeze)
            record['status'] = receipt['status']
            if receipt['status'] == 'completed' and not receipt.get('exact_criterion_coverage'):
                record.update(status='error', error={'type': 'ProtocolFailure', 'message': 'CRITERION_COVERAGE_MISMATCH'})
        except Exception as exc:
            record.update(status='error', error=error_data(exc))
        try:
            verify(workspace, freeze)
            record['postflight_matches'] = file_hash(frozen_path) == frozen_hash
        except Exception as exc:
            record.update(postflight_matches=False, postflight_error=error_data(exc))
        if not record['postflight_matches']:
            record['status'] = 'error'
        record['ended'] = datetime.now(timezone.utc).isoformat()
        execution_path.write_text(encode(record), encoding='utf-8')
        print(encode(record), flush=True)
        return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--authorization-note', required=True)
    parser.add_argument('--credential-container', default='hunan-highway-trial067-api-1')
    asyncio.run(run(parser.parse_args()))
