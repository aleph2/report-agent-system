"""Independent test oracle for effective, single-system full/delta controls.

Read captured request/wire content, never the application store or its renderer.
This intentionally rejects the retired per-call current_task-only envelope.
"""
from copy import deepcopy
import hashlib
import json


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def current_task(value):
    if hasattr(value, 'system_message'):
        value = value.system_message
    if hasattr(value, 'content_blocks'):
        value = value.content_blocks
    if isinstance(value, str):
        value = [value]
    blocks = []
    for item in value:
        if hasattr(item, 'type'):
            if item.type == 'system':
                blocks.extend(item.content_blocks)
        elif isinstance(item, dict) and item.get('role') == 'system':
            body = item.get('content', '')
            blocks.extend(body if isinstance(body, list) else [body])
        else:
            blocks.append(item)
    controls = []
    def walk(item):
        if isinstance(item, dict):
            if item.get('kind') in {'full', 'delta'} and 'state_digest' in item:
                controls.append(item)
                return
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    for block in blocks:
        text = block.get('text', '') if isinstance(block, dict) else block
        if not isinstance(text, str):
            continue
        try:
            walk(json.loads(text))
        except json.JSONDecodeError:
            continue
    assert controls, 'Effective system has no host full/delta state controls'
    state, previous = None, None
    for frame in controls:
        if frame['kind'] == 'full':
            assert isinstance(frame.get('state'), dict)
            state = deepcopy(frame['state'])
        else:
            assert state is not None, 'Delta has no visible full base'
            assert frame['base_digest'] == previous, 'Broken state-control chain'
            for path in frame['removed_paths']:
                assert isinstance(path, list) and path
                parent = state
                for key in path[:-1]:
                    parent = parent[key]
                del parent[path[-1]]
            assert isinstance(frame['changes'], dict)
            state.update(deepcopy(frame['changes']))
        assert _sha(state) == frame['state_digest'], 'State frame digest does not match reconstructed value'
        previous = frame['state_digest']
    return state
