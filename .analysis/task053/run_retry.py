from pathlib import Path
import sys
from copy import deepcopy

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'scripts'))
import run_deepseek_flat_probe as probe

source = probe.DEST
manifest = probe.read(source / 'manifest.json')
for path, digest in manifest['frozen_files'].items():
    if probe.sha((root / path).read_bytes()) != digest:
        raise ValueError('PRIOR_PROTECTED_FILE_CHANGED')
probe.config(Path(sys.argv[1]))
probe.DEST = root / '.runs/task053/flat-retry'
probe.DEST.mkdir(parents=True, exist_ok=False)
fresh = deepcopy(manifest)
for stage in ('a', 'b'):
    fresh.pop(stage + '_results', None)
fresh.pop('stage_b_reason', None)
fresh.update(prepared=probe.now(), stages={'a': 'prepared', 'b': 'not_planned'},
             replay_of=str(source.relative_to(root)), authorized_requests=2,
             replay_scope='Only stage A; explicit user request; no automatic B')
for path in (Path(__file__), root / '.ase/tasks/053-flat-retry.md'):
    fresh['frozen_files'][str(path.relative_to(root))] = probe.sha(path.read_bytes())
for item in probe.PLAN:
    if item['stage'] != 'a':
        continue
    body = (source / item['id'] / 'request.json').read_bytes()
    if probe.sha(body) != manifest['request_sha256'][item['id']]:
        raise ValueError('PRIOR_REQUEST_CHANGED')
    folder = probe.DEST / item['id']
    folder.mkdir()
    (folder / 'request.json').write_bytes(body)
probe.write(probe.DEST / 'manifest.json', fresh)
probe.run(Path(sys.argv[1]), 'a')
