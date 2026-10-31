"""Prepare a staged fresh report with network access denied."""
import argparse
import fcntl
import json
from pathlib import Path
import runpy
import socket


def prepare(run):
    run = run.resolve(strict=True)
    receipt = json.loads((run / 'stage-receipt.json').read_text())
    import hashlib
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    for name, field in (('host.py', 'host_sha256'), ('deployment.json', 'deployment_sha256'),
                        ('authorization.json', 'authorization_sha256')):
        if sha(run / name) != receipt[field]:
            raise RuntimeError('STAGED_FILE_CHANGED: ' + name)
    host = runpy.run_path(str(run / 'host.py'), run_name='prepare_only')
    if host['source_pins']() != receipt['source_pins'] or host['input_files']() != receipt['input_hashes']:
        raise RuntimeError('STAGED_SOURCE_OR_INPUT_CHANGED')
    if any((run / name).exists() for name in ('prepared.json', 'prepare-launch-intent.json', 'started.json')):
        raise RuntimeError('PREPARE_ALREADY_ATTEMPTED')
    with host['LOCK'].open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        host['save'](run / 'prepare-launch-intent.json', {'host_sha256': sha(run / 'host.py'),
                                                        'zero_model_calls': True})
        host['prepare']()
        print('Prepared without model calls; exact independent review is still required before launch.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    def denied(*args, **kwargs):
        raise RuntimeError('PREPARE_NETWORK_FORBIDDEN')
    socket.socket.connect = denied
    prepare(args.run)


if __name__ == '__main__':
    main()
