"""Require proven local Linux storage before opening a report's writable databases."""
from pathlib import Path
import re
import sys


def require_native_storage(*paths):
    allowed = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'f2fs', 'zfs'}
    try:
        if sys.platform != 'linux':
            raise ValueError('Linux mount evidence unavailable')
        mounts = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            fields, details = line.split(' - ', 1)
            fields, details = fields.split(), details.split()
            point = Path(re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4]))
            mounts.append((point, details[0], fields[5].split(',')))
        facts = []
        for path in paths:
            target = Path(path).resolve()
            ancestor = target
            while not ancestor.exists():
                ancestor = ancestor.parent
            candidates = [m for m in mounts if ancestor.is_relative_to(m[0])]
            if not candidates:
                raise ValueError('No matching mount: ' + str(target))
            point, filesystem, options = max(candidates, key=lambda m: len(m[0].parts))
            if filesystem not in allowed or 'rw' not in options:
                raise ValueError(f'{target}: {filesystem} at {point}')
            facts.append({'path': str(target), 'mount_point': str(point), 'filesystem': filesystem})
        return facts
    except (OSError, ValueError, IndexError) as exc:
        raise RuntimeError('NATIVE_LINUX_STORAGE_REQUIRED: ' + str(exc)) from exc
