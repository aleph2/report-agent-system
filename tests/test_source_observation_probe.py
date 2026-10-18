"""Protected public-input preparation and single native invocation, entirely offline."""
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_source_observation_probe as preparation
import run_source_observation_probe as runner
import run_selected_evidence_probe as shared
from report_agent.acceptance import active_criteria, bind_mode, save_criteria
from report_agent.deep_models import LocalAudit
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_acceptance_runtime import verdict
from test_deep_runtime import Driver, invoke


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    def forbidden(*args, **kwargs):
        raise AssertionError('NETWORK_FORBIDDEN')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def baseline(tmp_path):
    store = Store(tmp_path / 'baseline')
    source = store.root / 'sources/count.txt'
    source.parent.mkdir()
    source.write_bytes(b'Count: 7.')
    store.initialize({'goal': 'Compile the count.', 'sources': [{
        'id': 's', 'title': 'Count notice', 'filename': 'count.txt',
        'content': 'Count: 7.', 'coverage': 'complete', 'copied_path': 'sources/count.txt',
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]})
    workspace = Workspace(store)
    workspace.initialize()
    bind_mode(workspace)
    standard = save_criteria(workspace, actor='coordinator', title='Count standard', criteria=[{
        'condition': 'Report the known count accurately.', 'requirement_refs': ['commission']}],
        source_ids=['s'], input_ids=[], reason='Synthetic standard.')
    task = workspace.request_task('draft', 'Compile', [])
    draft = workspace.submit(task['id'], actor='writer', title='Count', body='Count: 7.',
        source_ids=['s'], input_ids=[standard['id']])
    workspace.select_delivery(draft['id'], '')
    store.set('rubric_reviews', [{'explanation': 'DO_NOT_IMPORT_PRIOR_VERDICT'}])
    store.set('corrections', [{'description': 'DO_NOT_IMPORT_CORRECTION'}])
    store.event('deep_model_response', {'content': 'DO_NOT_IMPORT_TRANSCRIPT'})
    (store.root / 'run.lock').touch()
    return workspace, draft


def prepare_arguments(baseline, destination):
    workspace, draft = baseline
    return (workspace.store.root, destination, draft['id'], hashlib.sha256(draft['body'].encode()).hexdigest())


@pytest.mark.parametrize('wal', [False, True])
def test_protected_import_preserves_baseline_files_and_excludes_old_feedback(baseline, tmp_path, wal):
    original, draft = baseline
    keeper = None
    if wal:
        keeper = sqlite3.connect(original.store.path)
        keeper.execute('PRAGMA journal_mode=WAL')
        keeper.execute('INSERT INTO state VALUES (?,?)', ('wal_fixture', encode('committed WAL evidence')))
        keeper.commit()
    try:
        before = preparation.tree_hashes(original.store.root)
        destination = tmp_path / 'candidate'
        workspace, receipt = preparation.protected_candidate(*prepare_arguments(baseline, destination))
        assert preparation.tree_hashes(original.store.root) == before
        assert receipt['baseline_tree_unchanged'] and receipt['original_baseline_files_sha256'] == before
        assert receipt['baseline'] == str(original.store.root)
        assert receipt['temporary_snapshot_disposed'] and receipt['model_calls'] == 0
        assert not (destination / 'checkpoints.db').exists()
        assert len(workspace.results()) == 2
        current = active_criteria(workspace)
        saved = workspace.result(workspace.store.get('delivery')['draft_id'])
        assert saved['body'] == draft['body'] and saved['id'] != draft['id']
        assert saved['input_ids'] == [current['id']]
        assert list(receipt['criterion_id_mapping'].values()) == [c['id'] for c in current['criteria']]
        assert (destination / 'sources/count.txt').read_bytes() == b'Count: 7.'
        assert not workspace.store.get('rubric_reviews') and not workspace.store.get('corrections')
        assert 'DO_NOT_IMPORT' not in encode(workspace.store.events())
        with pytest.raises(ValueError, match='NEW_ISOLATED'):
            preparation.protected_candidate(*prepare_arguments(baseline, destination))
    finally:
        if keeper:
            keeper.close()


def test_wrong_report_and_active_baseline_are_rejected_without_copy(baseline, tmp_path):
    original, draft = baseline
    before = preparation.tree_hashes(original.store.root)
    with pytest.raises(ValueError, match='BODY_HASH_MISMATCH'):
        preparation.protected_candidate(original.store.root, tmp_path / 'wrong', draft['id'], '0'*64)
    assert not (tmp_path / 'wrong').exists()
    with original.store.run_lock():
        with pytest.raises(RuntimeError, match='BASELINE_ALREADY_RUNNING'):
            preparation.protected_candidate(*prepare_arguments(baseline, tmp_path / 'locked'))
    assert preparation.tree_hashes(original.store.root) == before


def arguments(project):
    return SimpleNamespace(project=project, authorization_note='Offline synthetic test.',
                           credential_container='NEVER_READ_CREDENTIALS')


async def test_attempt_failure_is_retained_and_cannot_replay(baseline, tmp_path):
    destination = tmp_path / 'failure'
    preparation.prepare(*prepare_arguments(baseline, destination))
    calls = []
    async def broken(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('Synthetic failure before response')
    result = await runner.run(arguments(destination), invoke=broken)
    assert result['status'] == 'error' and result['postflight_matches']
    with pytest.raises(ValueError, match='ALREADY_ATTEMPTED'):
        await runner.run(arguments(destination), invoke=broken)
    assert calls == [True]


async def test_changed_frozen_candidate_is_rejected_before_invocation(baseline, tmp_path):
    destination = tmp_path / 'changed'
    preparation.prepare(*prepare_arguments(baseline, destination))
    path = destination / 'source-observation-freeze.json'
    value = json.loads(path.read_text())
    value['draft_body_sha256'] = '0'*64
    path.write_text(encode(value))
    async def forbidden(*args, **kwargs):
        raise AssertionError('MUST_NOT_INVOKE')
    with pytest.raises(ValueError, match='FROZEN_CANDIDATE'):
        await runner.run(arguments(destination), invoke=forbidden)
    assert not (destination / 'source-observation-execution.json').exists()


async def test_prepared_candidate_runs_actual_native_graph_with_bound_view(baseline, tmp_path, monkeypatch):
    destination = tmp_path / 'native'
    frozen = preparation.prepare(*prepare_arguments(baseline, destination))
    workspace = Workspace(Store(destination))
    driver = Driver(rubric_grader=[invoke('search_sources', query='Count'),
                                   lambda messages: verdict(workspace, ['satisfied'])])
    def model(store, role):
        value = driver(role)
        value.callbacks = [LocalAudit(store, role)]
        return value
    monkeypatch.setattr(shared, 'configured_model', model)
    monkeypatch.setattr(shared, 'load_service_environment', lambda container: None)
    result = await runner.run(arguments(destination))
    assert result['status'] == 'completed' and result['postflight_matches']
    public = json.loads((destination / 'output.json').read_text())
    assert public['result'] == 'satisfied'
    targets = workspace.store.get('rubric_targets')
    assert len(targets) == 1
    assert frozen['source_search_identity'] in [v for target in targets.values() for v in target.values()]
    assert len(workspace.results()) == 2  # no author/result writes from the grader
    assert not any('DO_NOT_IMPORT' in str(messages) for _, _, messages in driver.calls)
