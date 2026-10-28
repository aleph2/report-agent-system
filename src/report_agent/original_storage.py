"""Immutable case-local originals; paths never become source identity."""
import hashlib
import os
import re
import stat
import uuid
from contextlib import contextmanager
from .errors import ActionRejected

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def _objects(store, *, create=False):
    root = os.open(store.root.resolve(), _DIR)
    opened = [root]
    try:
        parent = root
        for name in ('sources', 'objects'):
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=parent)
                    os.fsync(parent)
                except FileExistsError:
                    pass
            if stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
                raise ActionRejected('SOURCE_ORIGINAL_OUTSIDE_PROJECT')
            child = os.open(name, _DIR, dir_fd=parent)
            opened.append(child)
            parent = child
        yield parent
    except OSError:
        raise ActionRejected('SOURCE_ORIGINAL_UNAVAILABLE') from None
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _sha(sha):
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ActionRejected('SOURCE_ORIGINAL_SHA256_REQUIRED')
    return sha


def _read(directory, sha, expected_bytes):
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise ActionRejected('SOURCE_ORIGINAL_SIZE_REQUIRED')
    try:
        fd = os.open(_sha(sha), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ActionRejected('SOURCE_ORIGINAL_UNAVAILABLE')
            if os.fstat(f.fileno()).st_size != expected_bytes:
                raise ActionRejected('SOURCE_ORIGINAL_SHA256_MISMATCH')
            data = f.read(expected_bytes + 1)
    except OSError:
        raise ActionRejected('SOURCE_ORIGINAL_UNAVAILABLE') from None
    if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != sha:
        raise ActionRejected('SOURCE_ORIGINAL_SHA256_MISMATCH')
    return data


def read_original(store, sha, expected_bytes):
    with _objects(store) as directory:
        return _read(directory, sha, expected_bytes)


def save_original(store, data):
    sha = hashlib.sha256(data).hexdigest()
    with _objects(store, create=True) as directory:
        temp = '.pending-' + uuid.uuid4().hex
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(temp, sha, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                _read(directory, sha, len(data))
            os.fsync(directory)
        finally:
            os.unlink(temp, dir_fd=directory)
    return sha
