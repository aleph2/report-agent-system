"""A clean Git release can stage/prepare without old runs, credentials or paid calls."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

import pytest
from test_ingestion import pdf_bytes


@pytest.mark.parametrize('synthetic,limit,input_count', [(False, 200_000_000, 11), (True, 50_000_000, 6)])
def test_committed_release_stages_and_prepares_without_legacy_dependencies(tmp_path, monkeypatch, synthetic, limit, input_count):
    project = Path(__file__).resolve().parents[1]
    repo = tmp_path / 'checkout'
    repo.mkdir()
    paths = ('src/report_agent', 'pyproject.toml', 'requirements.lock', 'config/current.json',
             'scripts/report_host.py', 'scripts/stage_report.py',
             'scripts/prepare_report.py', 'scripts/launch_report.py')
    for name in paths:
        origin, target = project / name, repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if origin.is_dir():
            shutil.copytree(origin, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(origin, target)
    config_path = repo / 'config/current.json'
    config = json.loads(config_path.read_text())
    config.update(synthetic=synthetic, round_token_limit=limit, input_file_count=input_count)
    config_path.write_text(json.dumps(config))
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    git('init', '-q')
    git('add', '--', *paths)
    git('-c', 'user.name=Offline Test', '-c', 'user.email=offline@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic release fixture')
    commit = git('rev-parse', 'HEAD').decode().strip()
    original = (repo / 'src/report_agent/task_context.py').read_bytes()
    (repo / 'src/report_agent/task_context.py').write_bytes(original + b'\n# UNREVIEWED_CHANGE\n')
    (repo / 'src/report_agent/rules/unreviewed-draft.md').write_text('UNREVIEWED_PROMPT')
    (repo / '.env').write_text(
        'HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash-1017\n'
        'HIGHWAY_MODEL_DEEPSEEK_BASE_URL=https://fixture.invalid/v1\n'
        'HIGHWAY_MODEL_DEEPSEEK_API_KEY=offline-only\n'
        'HIGHWAY_MODEL_NAME=glm-5.3\nHIGHWAY_MODEL_BASE_URL=https://fixture.invalid/v1\n'
        'HIGHWAY_MODEL_API_KEY=offline-only\n', encoding='utf-8')
    inputs = tmp_path / 'originals'
    (inputs / '成果报告').mkdir(parents=True)
    (inputs / '报告编写范围说明.md').write_text('Synthetic offline report scope.', encoding='utf-8')
    (inputs / '成果报告/format.pdf').write_bytes(pdf_bytes(('Synthetic format reference.',)))
    for number in range(input_count - 2):
        (inputs / f'source-{number}.md').write_text('Synthetic independent input.')
    run = tmp_path / 'runtime'
    ledger = tmp_path / 'finance/token-budget.db'
    def command(script, *args):
        return subprocess.run([sys.executable, '-B', str(repo / 'scripts' / script), *map(str, args)],
                              cwd=tmp_path, capture_output=True, text=True, timeout=90)
    rejected = command('stage_report.py', '--revision', commit, '--inputs', inputs,
                       '--run', run, '--ledger', repo / 'finance/token-budget.db',
                       '--authority', 'OFFLINE SYNTHETIC TEST ONLY')
    assert rejected.returncode != 0
    assert 'INDEPENDENT_STORAGE_REQUIRED' in rejected.stderr
    assert not run.exists()
    staged = command('stage_report.py', '--revision', commit, '--inputs', inputs,
                     '--run', run, '--ledger', ledger, '--authority', 'OFFLINE SYNTHETIC TEST ONLY')
    assert staged.returncode == 0, staged.stdout + staged.stderr
    assert (run / 'source/src/report_agent/task_context.py').read_bytes() == original
    assert not (run / 'source/src/report_agent/rules/unreviewed-draft.md').exists()
    assert not (run / 'source/.env').exists()
    assert not ledger.exists()
    assert not (run / 'case').exists()
    assert not (repo / '.analysis').exists()
    assert not (repo / '.financial-records').exists()
    prepared = command('prepare_report.py', '--run', run)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    result = json.loads((run / 'prepared.json').read_text())
    assert result['canonical_baseline'] is None
    assert result['timeout_seconds'] == 600
    assert result['maximum_attempts_per_call'] == 3
    assert result['scope_limit'] == limit
    assert result['synthetic'] is synthetic
    assert result['recovery_policy']['extra_per_call'] == 2
    assert result['recovery_policy']['extra_per_case'] is None
    assert result['recovery_policy']['extra_token_ceiling'] is None
    assert ledger.exists()
    assert not (run / 'case/checkpoints.db').exists()
    assert not (run / 'started.json').exists()
    repeat = command('prepare_report.py', '--run', run)
    assert repeat.returncode != 0
    assert 'PREPARE_ALREADY_ATTEMPTED' in repeat.stderr
    launch = runpy.run_path(str(repo / 'scripts/launch_report.py'), run_name='offline_launch_check')
    with pytest.raises(FileNotFoundError):
        launch['checked_intent'](run)
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    # A synthetic local approval exercises mechanics only, never a real report authorization.
    (run / 'neo-approval.json').write_text(json.dumps({'approved': True,
        'host_sha256': sha(run / 'host.py'), 'prepared_sha256': sha(run / 'prepared.json'),
        'synthetic_only': True}))
    original_popen = subprocess.Popen
    verified = []
    verifier = [sys.executable, '-I', '-B', '-c',
        'import sys; sys.path.insert(0, sys.argv[1]); '
        'from report_agent.blob_store import verify_case_blobs; verify_case_blobs(sys.argv[2])',
        str(run / 'source/src'), str(run / 'case')]

    def no_launch(*args, **kwargs):
        if args != (verifier,) or kwargs != {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'text': True}:
            pytest.fail('Restore verification permits only the pinned read-only blob verifier, never a report process')
        verified.append(args[0])
        return original_popen(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', no_launch)
    monkeypatch.setattr(sys, 'argv', ['launch_report.py', '--run', str(run), '--check'])
    launch['main']()
    assert verified == [verifier]
    assert not (run / 'run-launch-intent.json').exists()
    assert not (run / 'started.json').exists()
    (run / 'source/config/current.json').write_text('{}')
    with pytest.raises(RuntimeError, match='SOURCE_CHANGED'):
        launch['checked_intent'](run)
