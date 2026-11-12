"""Independent decoder of actual host-projected requests, not producer state.

Only marked user/Human controls or legacy System envelopes are decoded. This
wire oracle relies on separate provenance/adversarial tests to establish that
untrusted quoted markers were escaped by the production delivery boundary.
"""
from copy import deepcopy
import json


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


def current_task(value):
    messages = value.messages if hasattr(value, 'messages') else value
    packets = []
    for message in messages:
        role = getattr(message, 'type', None) if not isinstance(message, dict) else message.get('role')
        text = message.text if hasattr(message, 'text') else message.get('content', '') if isinstance(message, dict) else ''
        if role in ('human', 'user') and isinstance(text, str) and text.startswith('[host-observations]\n'):
            packet = json.loads(text.split('\n', 1)[1])
            if 'current_state' in packet:
                packets.append(packet['current_state'])
    assert len(packets) == 1, 'One current host-state tail is required; history is not an authority fallback'
    return packets[0]


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
    assert messages[last + 1:] == [tail], 'Only this call tail may follow a complete tool batch'
    return tool
