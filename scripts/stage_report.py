"""Stage a committed release and independent inputs without contacting a model."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import tarfile


REPOSITORY = Path(__file__).resolve().parents[1]
RELEASE_PATHS = ('src/report_agent', 'pyproject.toml', 'requirements.lock', 'config/current.json',
                 'scripts/report_host.py', 'scripts/stage_report.py',
                 'scripts/prepare_report.py', 'scripts/launch_report.py')


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPOSITORY), *args])


def stage(args):
    run = args.run.resolve()
    inputs = args.inputs.resolve(strict=True)
    ledger = args.ledger.resolve()
    if not args.authority.strip():
        raise ValueError('EXPLICIT_RUN_AUTHORITY_REQUIRED')
    if run.exists() or ledger.exists():
        raise ValueError('RUN_OR_LEDGER_ALREADY_EXISTS')
    if (run.is_relative_to(REPOSITORY) or ledger.is_relative_to(REPOSITORY) or run.is_relative_to(inputs)
            or inputs.is_relative_to(run) or ledger.is_relative_to(run)
            or ledger.is_relative_to(inputs) or run.is_relative_to(ledger)):
        raise ValueError('INDEPENDENT_STORAGE_REQUIRED')
    commit = git('rev-parse', '--verify', args.revision + '^{commit}').decode().strip()
    # The staging algorithm itself must be the selected release, not a dirty replacement.
    committed_stage = git('show', commit + ':scripts/stage_report.py').decode()
    if committed_stage != Path(__file__).read_text(encoding='utf-8'):
        raise ValueError('STAGING_SCRIPT_DIFFERS_FROM_RELEASE')
    archive = git('archive', '--format=tar', commit, *RELEASE_PATHS)
    lock = REPOSITORY / '.runs/shared-model-validation.lock'
    lock.parent.mkdir(exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # An exclusive directory is also the staging intent; failed stages are not retried.
        run.mkdir(parents=True, exist_ok=False)
        source = run / 'source'
        source.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            if any(not (member.isfile() or member.isdir()) for member in tar.getmembers()):
                raise ValueError('RELEASE_LINKS_FORBIDDEN')
            tar.extractall(source, filter='data')
        shutil.copy2(source / 'scripts/report_host.py', run / 'host.py')
        save(run / 'deployment.json', {'repository': str(REPOSITORY),
                                     'ledger': str(ledger), 'commit': commit})
        host = runpy.run_path(str(run / 'host.py'), run_name='stage_only')
        config = host['CONFIG']
        # PDF parsing uses the same bounded memory allowance as prepare.
        import resource
        resource.setrlimit(resource.RLIMIT_AS,
                           (config['prepare_memory_bytes'], config['prepare_memory_bytes']))
        files = sorted(p for p in inputs.rglob('*') if p.is_file() and not p.name.startswith('~$'))
        if len(files) != config['input_file_count']:
            raise ValueError('INPUT_COUNT_MISMATCH')
        destination = run / 'inputs'
        destination.mkdir()
        for path in files:
            if (path.is_symlink() or not path.resolve().is_relative_to(inputs)
                    or path.suffix.lower() not in {'.pdf', '.md', '.docx'}
                    or path.stat().st_size > config['input_max_bytes']):
                raise ValueError('INPUT_ESCAPE_TYPE_OR_LIMIT')
            target = destination / path.relative_to(inputs)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if host['sha'](path) != host['sha'](target):
                raise ValueError('INPUT_CHANGED_DURING_COPY')
        pins = host['input_files']()
        from pypdf import PdfReader
        from report_agent.ingestion import MAX_PDF_PAGES
        profiles = []
        for name, digest in pins.items():
            if not name.lower().endswith('.pdf'):
                continue
            path = destination / name
            reader = PdfReader(path)
            if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError('PDF_ENCRYPTED_OR_PAGE_LIMIT')
            sizes = []
            for page in reader.pages:
                contents = page.get_contents()
                sizes.append(len(contents.get_data()) if contents is not None else 0)
            profiles.append({'path': name, 'sha256': digest, 'input_bytes': path.stat().st_size,
                             'pages': len(reader.pages), 'largest_page_bytes': max(sizes, default=0),
                             'total_decoded_bytes': sum(sizes)})
        save(run / 'approved-input-hashes.json', pins)
        save(run / 'approved-endpoint-pins.json', host['endpoint_pins']())
        save(run / 'pdf-limits.json', profiles)
        save(run / 'authorization.json', {'authority': args.authority,
                                        'round_token_limit': config['round_token_limit']})
        receipt = {'status': 'staged_no_model_calls', 'commit': commit, 'run': str(run),
                   'ledger': str(ledger), 'host_sha256': host['sha'](run / 'host.py'),
                   'source_pins': host['source_pins'](), 'input_hashes': pins,
                   'deployment_sha256': host['sha'](run / 'deployment.json'),
                   'authorization_sha256': host['sha'](run / 'authorization.json')}
        save(run / 'stage-receipt.json', receipt)
        print(json.dumps({'status': receipt['status'], 'commit': commit, 'run': str(run)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True, help='Explicit Git commit or tag to export')
    parser.add_argument('--inputs', required=True, type=Path, help='Independent original input directory')
    parser.add_argument('--run', required=True, type=Path, help='New independent run directory')
    parser.add_argument('--ledger', required=True, type=Path, help='New independent token-budget.db')
    parser.add_argument('--authority', required=True, help='Actual user authorization, not an automatic grant')
    args = parser.parse_args()
    def denied(*args, **kwargs):
        raise RuntimeError('STAGING_NETWORK_FORBIDDEN')
    socket.socket.connect = denied
    stage(args)


if __name__ == '__main__':
    main()
