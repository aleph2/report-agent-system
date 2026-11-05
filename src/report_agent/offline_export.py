"""Trusted local operator export: copy first, preserve original state, never run a model."""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from .errors import ActionRejected


def hashes(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ActionRejected('OFFLINE_SYMLINK_UNSUPPORTED: ' + str(path.relative_to(root)))
        if path.is_file() and not path.name.endswith('-shm'):
            with path.open('rb') as stream:
                result[str(path.relative_to(root))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def export_offline(source, output, *, assembly_input=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise ActionRejected('OFFLINE_OUTPUT_MUST_BE_SEPARATE')
    if not (source / 'state.db').is_file():
        raise ActionRejected('OFFLINE_SOURCE_REQUIRED')
    output.mkdir(parents=True, exist_ok=False)
    before = hashes(source)
    receipt = {'started_at': datetime.now(timezone.utc).isoformat(), 'source': str(source),
               'classification': 'stopped during export; content assembled',
               'mode': 'offline; no model invocation', 'source_before': before}
    try:
        copy = output / 'case'
        # Copy stopped files first: even mode=ro can create WAL/SHM sidecars at its source.
        shutil.copytree(source, copy, ignore=lambda directory, names:
            [name for name in names if name.endswith('-shm')])
        # Read-only evidence copies remain immutable; only the new working copy is writable.
        for path in [copy, *copy.rglob('*')]:
            path.chmod(0o700 if path.is_dir() else 0o600)
        frozen = output / 'frozen-state.db'
        with sqlite3.connect((copy / 'state.db').as_uri() + '?mode=ro', uri=True) as original:
            original.execute('PRAGMA query_only=ON')
            with sqlite3.connect(frozen) as destination:
                original.backup(destination)
        original.close()
        destination.close()
        for suffix in ('-wal', '-shm'):
            (copy / ('state.db' + suffix)).unlink(missing_ok=True)
        frozen.replace(copy / 'state.db')
        if hashes(source) != before:
            raise ActionRejected('OFFLINE_SOURCE_CHANGED_DURING_COPY')
        from .store import Store
        from .content_store import ContentStore, Actor
        from .content_export import export_snapshot
        contents = ContentStore(Store(copy))
        snapshots = contents.list_objects('DocumentSnapshot')
        if not snapshots:
            raise ActionRejected('OFFLINE_SNAPSHOT_REQUIRED')
        snapshot = max(snapshots, key=lambda record: record['created_at'])
        owner = snapshot['owner_id']
        if owner == 'content:coordinator':
            role = 'coordinator'
        elif owner.startswith('content:writer:'):
            role = 'writer'
        else:
            raise ActionRejected('OFFLINE_PRODUCER_IDENTITY_UNSUPPORTED: ' + owner)
        actor = Actor(owner, role, snapshot['task_id'])
        receipt.update(snapshot_ref=snapshot['ref'], snapshot_digest=snapshot['payload_digest'],
                       acting_as_frozen_producer=actor.__dict__)
        if assembly_input is not None:
            from .system_assembler import assemble_report, record_issue_routes
            if role != 'coordinator':
                raise ActionRejected('OFFLINE_ASSEMBLY_COORDINATOR_SNAPSHOT_REQUIRED')
            expected = {'prose_bindings', 'assessment_refs', 'issue_bindings', 'issue_routes', 'routing_note'}
            if set(assembly_input) - expected or not {'prose_bindings', 'assessment_refs', 'issue_bindings'} <= set(assembly_input):
                raise ActionRejected('OFFLINE_ASSEMBLY_INPUT_FIELDS_INVALID')
            if assembly_input.get('issue_routes'):
                record_issue_routes(contents, Actor('operator', 'operator', 'operator-offline'),
                    'operator-offline-routes', assembly_input['issue_routes'], note=assembly_input.get('routing_note', ''))
            assembled = assemble_report(contents, actor, 'operator-offline-assembly',
                source_snapshot_ref=snapshot['ref'], **{k: assembly_input[k] for k in ('prose_bindings', 'assessment_refs', 'issue_bindings')})['result']
            receipt['assembly_result'] = assembled
            snapshot = contents.read(assembled['snapshot_ref'])
        result = export_snapshot(contents, actor, 'operator-offline-export', snapshot['ref'])['result']
        receipt['export_result'] = result
        for name, artifact in [('G5-report.docx', result), ('G5-clarifications.xlsx', result['workbook'])]:
            shutil.copy2(copy / artifact['file_ref'], output / name)
        receipt['status'] = 'exported; verification pending'
    except Exception as exc:
        receipt.update(status='blocked', error_type=type(exc).__name__, error=str(exc), diagnostic=getattr(exc, 'diagnostic', None))
    finally:
        receipt['source_after'] = hashes(source)
        receipt['source_unchanged'] = receipt['source_after'] == before
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        if not receipt['source_unchanged']:
            receipt['status'] = 'source changed during offline export'
        (output / 'offline-export-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--assembly-input', type=Path, help='Reviewed bindings and optional operator routes; never engineering guesses')
    args = parser.parse_args()
    def no_network(event, arguments):
        if event == 'socket.connect':
            raise RuntimeError('OFFLINE_NETWORK_DISABLED')
    sys.addaudithook(no_network)
    receipt = export_offline(args.source, args.output,
        assembly_input=json.loads(args.assembly_input.read_text(encoding='utf-8')) if args.assembly_input else None)
    print(json.dumps({key: receipt.get(key) for key in ['status', 'snapshot_ref', 'error', 'source_unchanged']}, ensure_ascii=False))
    return 0 if receipt['status'] == 'exported; verification pending' else 1


if __name__ == '__main__':
    raise SystemExit(main())
