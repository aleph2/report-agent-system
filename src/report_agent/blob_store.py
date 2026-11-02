"""Immutable, verified bytes within one case; database records own references."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from contextlib import closing

from .errors import ActionRejected


class BlobStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @contextmanager
    def locked(self):
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.blob-store.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _path(self, ref):
        sha = ref.get('sha256', '')
        if (not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                or ref.get('path') != f'blobs/{sha[:2]}/{sha}'
                or type(ref.get('size')) is not int or ref['size'] < 0
                or not isinstance(ref.get('media_type'), str)):
            raise ActionRejected('BLOB_DESCRIPTOR_INVALID')
        path = self.root / ref['path']
        if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
            raise ActionRejected('BLOB_PATH_INVALID')
        if not path.resolve().is_relative_to(self.root):
            raise ActionRejected('BLOB_PATH_INVALID')
        return path

    def read(self, ref):
        path = self._path(ref)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise ActionRejected('BLOB_INTEGRITY_MISSING') from None
        if len(data) != ref['size'] or hashlib.sha256(data).hexdigest() != ref['sha256']:
            raise ActionRejected('BLOB_INTEGRITY_MISMATCH')
        return data

    def put(self, data, media_type):
        with self.locked():
            return self._put_locked(data, media_type)

    def _put_locked(self, data, media_type):
        """Caller holds locked() through publication of its database reference."""
        sha = hashlib.sha256(data).hexdigest()
        ref = {'sha256': sha, 'size': len(data), 'media_type': media_type,
               'path': f'blobs/{sha[:2]}/{sha}'}
        path = self._path(ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.read(ref)  # Corruption is evidence, never silently overwritten.
            return ref
        fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            # Newly created hash directories also need their parent entries
            # persisted before the database can publish a durable reference.
            for parent in (path.parent, path.parent.parent, self.root):
                directory = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return ref


def verify_case_blobs(case):
    """Verify a fresh case whose main database hash will be pinned; never checkpoint drift."""
    from .store import digest
    root = Path(case).resolve()
    database = root / 'state.db'
    if not database.is_file():
        raise ActionRejected('CASE_DATABASE_MISSING')
    wal = root / 'state.db-wal'
    if wal.exists() and wal.stat().st_size:
        raise ActionRejected('CASE_DATABASE_WAL_NOT_SETTLED')
    blobs = BlobStore(root)
    verified = {}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        for raw, in db.execute('SELECT data FROM source_versions'):
            source = json.loads(raw)
            ref = source.get('original_blob')
            if ref is None:
                continue
            data = blobs.read(ref)
            if source.get('sha256') != ref['sha256'] or source.get('bytes') != len(data):
                raise ActionRejected('SOURCE_BLOB_INTEGRITY_MISMATCH')
            verified[ref['sha256']] = len(data)
        for key, raw in db.execute("SELECT key,value FROM state WHERE key LIKE 'prompt_capture:%'"):
            ref = json.loads(raw).get('capture_blob')
            if ref is None:
                continue
            data = blobs.read(ref)
            if key != 'prompt_capture:' + digest(json.loads(data)):
                raise ActionRejected('CAPTURE_BLOB_IDENTITY_MISMATCH')
            verified[ref['sha256']] = len(data)
    return {'verified_blobs': len(verified), 'verified_bytes': sum(verified.values())}
