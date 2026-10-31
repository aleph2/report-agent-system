"""Launch an exactly reviewed fresh run once; --check never starts a process."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


def checked_intent(run):
    run = run.resolve(strict=True)
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    prepared = json.loads((run / 'prepared.json').read_text())
    approval = json.loads((run / 'neo-approval.json').read_text())
    if (approval.get('approved') is not True or approval.get('host_sha256') != sha(run / 'host.py')
            or approval.get('prepared_sha256') != sha(run / 'prepared.json')):
        raise RuntimeError('EXACT_REVIEW_REQUIRED')
    if any((run / name).exists() for name in ('started.json', 'run-launch-intent.json',
                                             'result.json', 'failure.json', 'cleanup.json')):
        raise RuntimeError('RUN_ALREADY_ATTEMPTED')
    if (run / 'case/checkpoints.db').exists():
        raise RuntimeError('CASE_NOT_FRESH')
    if prepared['host_sha256'] != sha(run / 'host.py'):
        raise RuntimeError('HOST_CHANGED')
    for name, field in (('deployment.json', 'deployment_sha256'),
                        ('authorization.json', 'authorization_sha256'),
                        ('case/state.db', 'state_sha256'),
                        ('case/experience-library/state.db', 'library_sha256')):
        if sha(run / name) != prepared[field]:
            raise RuntimeError('PREPARED_FILE_CHANGED: ' + name)
    for name, digest in prepared['source_pins'].items():
        if sha(run / 'source' / name) != digest:
            raise RuntimeError('SOURCE_CHANGED')
    actual_inputs = {str(path.relative_to(run / 'inputs')): sha(path)
                     for path in (run / 'inputs').rglob('*')
                     if path.is_file() and not path.name.startswith('~$')}
    if actual_inputs != prepared['input_hashes']:
        raise RuntimeError('INPUT_CHANGED')
    return {'at_utc': datetime.now(timezone.utc).isoformat(), 'phase': 'run',
            'argv': [sys.executable, '-B', '-u', str(run / 'host.py'), 'run'],
            'cwd': str(run), 'host_sha256': sha(run / 'host.py'),
            'prepared_sha256': sha(run / 'prepared.json'), 'automatic_host_relaunch': False}


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--check', action='store_true', help='Validate only, without writing launch intent')
    args = parser.parse_args()
    run = args.run.resolve(strict=True)
    deployment = json.loads((run / 'deployment.json').read_text())
    lock_path = Path(deployment['repository']) / '.runs/shared-model-validation.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        intent = checked_intent(run)
        if args.check:
            print('Launch checks passed; no process started.')
            return
        save(run / 'run-launch-intent.json', intent)
        with (run / 'run-stdout.log').open('xb') as output:
            # The host acquires this same lock; release ours before its first execution.
            fcntl.flock(lock, fcntl.LOCK_UN)
            process = subprocess.Popen(intent['argv'], cwd=run, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        save(run / 'run-launch-receipt.json', {**intent, 'pid': process.pid,
                                              'not_completion_evidence': True})
        print(json.dumps({'pid': process.pid, 'run': str(run), 'not_completion_evidence': True}))


if __name__ == '__main__':
    main()
