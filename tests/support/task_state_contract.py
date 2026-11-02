"""Independent decoder of actual host-projected requests, not producer state.

Only marked user/Human controls or legacy System envelopes are decoded. This
wire oracle relies on separate provenance/adversarial tests to establish that
untrusted quoted markers were escaped by the production delivery boundary.
"""
from copy import deepcopy
import hashlib
import json


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def state_frames(value):
    if hasattr(value, 'system_message'):
        value = [value.system_message, *value.messages]
    elif hasattr(value, 'content_blocks') or isinstance(value, str):
        value = [value]
    frames = []
    for item in value:
        role = getattr(item, 'type', None)
        if hasattr(item, 'content_blocks'):
            blocks = item.content_blocks
        elif isinstance(item, dict) and 'role' in item:
            role = item['role']
            content = item.get('content', '')
            blocks = content if isinstance(content, list) else [content]
        else:
            role, blocks = 'system', [item]
        for block in blocks:
            text = block.get('text', '') if isinstance(block, dict) else block
            if not isinstance(text, str):
                continue
            marked = role in ('human', 'user') and text.startswith('[host-state]')
            if marked:
                text = text[len('[host-state]'):].lstrip()
            elif role != 'system':
                continue
            try:
                packet = json.loads(text)
            except ValueError:
                continue
            candidates = ([packet] if marked else packet.get('task_state_frames', [])
                          if isinstance(packet, dict) else [])
            frames.extend(frame for frame in candidates if isinstance(frame, dict)
                          and frame.get('kind') in ('full', 'delta', 'delta2') and 'state_digest' in frame)
    return frames


def moved_blocks(value):
    messages = value.messages if hasattr(value, 'messages') else value
    found = []
    for message in messages:
        if hasattr(message, 'type'):
            role, text = message.type, message.text
        elif isinstance(message, dict):
            role, text = message.get('role'), message.get('content')
        else:
            continue
        if role in ('human', 'user') and isinstance(text, str) and text.startswith('[host-observations]'):
            packet = json.loads(text[len('[host-observations]'):].lstrip())
            found.extend(packet['moved_blocks'])
    return found


def _apply(state, frame):
    if frame['kind'] == 'full':
        state = deepcopy(frame['state'])
        if not isinstance(state, dict):
            raise ValueError('Full state must be a mapping')
    else:
        if state is None or frame['base_digest'] != _sha(state):
            raise ValueError('Missing or broken state-control predecessor')
        state = deepcopy(state)
        if frame['kind'] == 'delta':
            for path in frame['removed_paths']:
                parent = state
                for key in path[:-1]:
                    parent = parent[key]
                del parent[path[-1]]
            state.update(deepcopy(frame['changes']))
        else:
            for operation in frame['ops']:
                path = operation['path']
                if not isinstance(path, list) or not path:
                    raise ValueError('Invalid nested control path')
                parent = state
                for key in path[:-1]:
                    parent = parent[key]
                key = path[-1]
                if operation['op'] == 'set':
                    parent[key] = deepcopy(operation['value'])
                elif operation['op'] == 'delete':
                    del parent[key]
                elif operation['op'] == 'splice':
                    target, start, count = parent[key], operation['start'], operation['delete_count']
                    if (not isinstance(target, list) or type(start) is not int or type(count) is not int
                            or not 0 <= start <= len(target) or not 0 <= count <= len(target) - start):
                        raise ValueError('Invalid list splice')
                    target[start:start + count] = deepcopy(operation['items'])
                else:
                    raise ValueError('Unknown control operation')
    if _sha(state) != frame['state_digest']:
        raise ValueError('State digest differs from reconstructed control')
    return state


def current_task(value):
    controls = state_frames(value)
    assert controls, 'Effective request has no host full/delta state controls'
    state = None
    for frame in controls:
        try:
            state = _apply(state, frame)
        except (ValueError, KeyError, TypeError, IndexError):
            state = None
    assert state is not None, 'Effective request has no valid current state base'
    return state


def native_model_call_record(role, messages, functions):
    """Read the live model callback scope; never infer a call from old content."""
    from report_agent.prompt_provenance import _CALL
    call = _CALL.get()
    owner = call.get('store') if call else None
    return {'role': role, 'purpose': call.get('purpose') if call else None,
        'call_id': call.get('call_id') if call else None,
        'store_root': str(owner.root.resolve()) if owner is not None else None,
        'messages': list(messages),
        'tools': [{'type': 'function', 'function': deepcopy(f)} for f in functions]}


def observe_native_model_calls(monkeypatch):
    """Transparent observation of the existing async test Driver callback."""
    from test_deep_runtime import Driver
    original = Driver.respond
    records = []
    async def observed(driver, role, messages):
        records.append(native_model_call_record(role, messages,
            driver.bindings.get(role, [[]])[-1]))
        return await original(driver, role, messages)
    monkeypatch.setattr(Driver, 'respond', observed)
    return records


def current_public_capture(store, record):
    """Bind this actual callback ID to its one saved public request, or fail."""
    from report_agent.prompt_provenance import public_projection
    assert record['call_id'] and record['purpose'] == record['role'], 'No current business prompt scope'
    assert record['store_root'] == str(store.root.resolve()), 'Foreign callback store'
    events = [e['data'] for e in store.events() if e['kind'] == 'prompt_model_input'
              and e['data'].get('call_id') == record['call_id']]
    assert len(events) == 1, 'Current callback has no unique saved input; old content is not a fallback'
    event = events[0]
    captured = store.get(event['capture_key'])
    assert event['purpose'] == captured['purpose'] == record['role']
    assert captured['call_id'] == record['call_id']
    messages = record['messages']
    assert messages and messages[0].type == 'system'
    assert sum(m.type == 'system' for m in messages) == 1
    actual = public_projection({'messages': [
        {'role': 'system', 'content': messages[0].content_blocks},
        *[m.model_dump(mode='json') for m in messages[1:]]], 'tools': record['tools']})
    public = captured['public_input']
    assert actual == {'messages': public['messages'], 'tools': public['tools']}, 'Current public input mismatch'
    actors = [p['references']['actor_id'] for p in captured['sources']
              if p['source'] == 'task_context/current_server_bound_state' and p.get('references', {}).get('actor_id')]
    assert len(actors) == 1, 'Current input must identify its bound actor'
    return captured, actors[0]


def authenticated_state_frame(store, message, actor_id):
    """Independent receipt/type/content/actor check, never a prefix filter."""
    from langchain_core.messages import HumanMessage
    if not isinstance(message, HumanMessage):
        return False
    metadata = message.additional_kwargs.get('report_task_state_frame')
    key = metadata.get('receipt') if isinstance(metadata, dict) else None
    if not isinstance(key, str) or not key.startswith('task_state_frame:'):
        return False
    receipt = store.get(key)
    return bool(isinstance(receipt, dict) and receipt.get('actor_id') == actor_id
                and receipt.get('content_digest') == _sha(message.content))


def assert_native_tool_then_host_suffix(store, record, messages, tools, *, expected_tool):
    """Keep the real last tool exchange; permit only the same-call host suffix."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    assert len(record['messages']) == len(messages)
    assert all(a is b for a, b in zip(record['messages'], messages)), 'Probe is not this callback input'
    assert record['tools'] == tools
    _, actor = current_public_capture(store, record)
    last = max(i for i, m in enumerate(messages) if isinstance(m, ToolMessage))
    tool = messages[last]
    assert tool.name == expected_tool and tool.status == 'success'
    prior = [i for i, m in enumerate(messages[:last]) if isinstance(m, AIMessage)
             and any(c['id'] == tool.tool_call_id and c['name'] == tool.name for c in m.tool_calls)]
    assert prior, 'Tool result has no matching original AI call'
    decision = prior[-1]
    batch = messages[decision + 1:last + 1]
    assert all(isinstance(m, ToolMessage) for m in batch), 'Host controls split an outstanding tool batch'
    assert [(m.tool_call_id, m.name) for m in batch] == [(c['id'], c['name']) for c in messages[decision].tool_calls]
    assert last < len(messages) - 1
    tail = messages[-1]
    assert isinstance(tail, HumanMessage) and tail.text.startswith('[host-observations]')
    packet = json.loads(tail.text.split('\n', 1)[1])
    assert packet['origin'] == 'server_bound_execution_observations'
    assert packet['actor_id'] == actor and packet['role'] == record['role']
    for frame in messages[last + 1:-1]:
        assert authenticated_state_frame(store, frame, actor), 'Non-host or foreign message after the tool'
        assert frame.text.startswith('[host-state]')
    return tool
