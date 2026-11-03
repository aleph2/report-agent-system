"""Native Linux storage is checked before financial/database/provider effects."""
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from test_pilot_m1_preparation import ROOT, host_case, stage_fixture
from test_m1_blob_launch import prepared_run


def guard():
    from report_agent.storage_preflight import require_native_storage
    return require_native_storage


def mounts(monkeypatch, text):
    original = Path.read_text
    def read(path, *args, **kwargs):
        if str(path) == '/proc/self/mountinfo':
            return text
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)


def line(point='/', fs='ext4', identifier=1):
    escaped = str(point).replace('\\', '\\134').replace(' ', '\\040').replace('\t', '\\011')
    return f'{identifier} 0 8:{identifier} / {escaped} rw,relatime shared:1 - {fs} /dev/test rw\n'


@pytest.mark.parametrize('fs', ['ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'f2fs', 'zfs'])
def test_new_native_paths_return_resolved_mount_evidence_without_creating_them(tmp_path, monkeypatch, fs):
    mounts(monkeypatch, line(fs=fs))
    target = tmp_path / 'new' / 'case'
    facts = guard()(target)
    assert facts[0]['path'] == str(target.resolve())
    assert facts[0]['filesystem'] == fs and facts[0]['mount_point'] == '/'
    assert not target.exists()


@pytest.mark.parametrize('fs', ['9p', 'drvfs', 'nfs', 'nfs4', 'cifs', 'smb3', 'fuse.sshfs',
                              'fuseblk', 'tmpfs', 'overlay', 'unknown'])
def test_unsupported_or_volatile_mount_is_refused(tmp_path, monkeypatch, fs):
    mounts(monkeypatch, line() + line(tmp_path, fs, 2))
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        guard()(tmp_path / 'case')


def test_deepest_mount_wins_and_component_boundary_is_respected(tmp_path, monkeypatch):
    nested = tmp_path / 'nested'; nested.mkdir()
    mounts(monkeypatch, line() + line(tmp_path, 'nfs', 2) + line(nested, 'ext4', 3))
    assert guard()(nested / 'case')[0]['mount_point'] == str(nested)
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        guard()(tmp_path / 'nested-sibling')


def test_mountpoint_escapes_and_symlink_target_are_resolved(tmp_path, monkeypatch):
    target = tmp_path / 'space here'; target.mkdir()
    link = tmp_path / 'safe-looking'; link.symlink_to(target, target_is_directory=True)
    mounts(monkeypatch, line() + line(target, '9p', 2))
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        guard()(link / 'new-case')


@pytest.mark.parametrize('mountinfo', ['', 'malformed mount record\n'])
def test_missing_or_unparseable_mount_evidence_fails_closed(tmp_path, monkeypatch, mountinfo):
    mounts(monkeypatch, mountinfo)
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        guard()(tmp_path)


def deny_guard(monkeypatch):
    from report_agent import storage_preflight
    calls = []
    def deny(*paths):
        calls.append([Path(p).resolve() for p in paths])
        raise RuntimeError('NATIVE_LINUX_STORAGE_REQUIRED: synthetic blocked mount')
    monkeypatch.setattr(storage_preflight, 'require_native_storage', deny)
    return calls


def test_stage_rejects_storage_before_writable_run_or_ledger(tmp_path, monkeypatch):
    stage, args = stage_fixture(tmp_path, monkeypatch, extras=1)
    calls = deny_guard(monkeypatch)
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        stage['stage'](args)
    assert calls and args.ledger.resolve() in calls[0]
    assert not args.run.exists() and not args.ledger.exists()


def test_prepare_rejects_storage_before_finance_and_database_creation(tmp_path, monkeypatch):
    state = host_case(tmp_path, monkeypatch)
    calls = deny_guard(monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('Financial reads/provider configuration must follow storage check')
    monkeypatch.setitem(state, 'canonical_baseline', forbidden)
    monkeypatch.setitem(state, 'endpoint_pins', forbidden)
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        state['prepare']()
    assert calls and state['LEDGER'].resolve() in calls[0]
    assert not state['CASE'].exists() and not state['LEDGER'].exists()


async def test_direct_host_run_rechecks_before_reading_databases_or_provider_setup(tmp_path, monkeypatch):
    run, state = prepared_run(tmp_path, monkeypatch)
    calls = deny_guard(monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail('Run must check storage before database verification')
    from report_agent import blob_store, model_config
    monkeypatch.setattr(blob_store, 'verify_case_blobs', forbidden)
    monkeypatch.setattr(model_config, 'load_mixed_services', forbidden)
    with pytest.raises(RuntimeError, match='NATIVE_LINUX_STORAGE_REQUIRED'):
        await state['run']()
    assert calls and state['LEDGER'].resolve() in calls[0]
    assert not (run / 'started.json').exists()


def test_launcher_runs_storage_check_in_pinned_interpreter_before_intent(tmp_path, monkeypatch):
    run, state = prepared_run(tmp_path, monkeypatch)
    checked = runpy.run_path(str(ROOT / 'scripts/launch_report.py'))['checked_intent']
    actual = subprocess.run
    observed = []
    def launch(argv, **kwargs):
        # Inject a filesystem refusal only inside the pinned verification process.
        if '-c' in argv:
            code = argv[argv.index('-c') + 1]
            assert 'storage_preflight' in code and 'require_native_storage' in code
            observed.append(argv)
            patch = ('from pathlib import Path; original=Path.read_text; '
                     'Path.read_text=lambda self,*a,**k: "1 0 0:1 / / rw - 9p drvfs rw\\n" '
                     'if str(self)=="/proc/self/mountinfo" else original(self,*a,**k); ')
            argv = list(argv)
            argv[argv.index('-c') + 1] = patch + code
        return actual(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'run', launch)
    with pytest.raises(RuntimeError):
        checked(run)
    assert observed
    assert not (run / 'run-launch-intent.json').exists() and not (run / 'started.json').exists()
