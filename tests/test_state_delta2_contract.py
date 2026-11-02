"""Lossless delta2 protocol expectations, independent of producer diff choices.

Existing prepare_delivery/persist_frame entry points are used; missing invented
APIs or import failures are never the intended RED.
"""
from copy import deepcopy

import pytest
from langchain_core.messages import HumanMessage

from report_agent.task_state_delivery import prepare_delivery, persist_frame
from test_request_state_delivery_regression import FRAME, apply_frame, encoded, sha, text_json
from test_task_supervision import ws


def produce(ws, history, context):
    before = deepcopy(context)
    result = prepare_delivery(ws.store, history, context)
    assert context == before, 'Diffing must not mutate the current application state'
    return result[-1]


def save(ws, history, context):
    message = produce(ws, history, context)
    assert isinstance(message, HumanMessage), 'A real change needs a pending host frame'
    persist_frame(ws.store, context['actor_id'], message)
    return [*history, message], text_json(message)


@pytest.mark.parametrize('change', ['nested_set_delete', 'duplicate', 'reorder', 'clear', 'rolling', 'repeated_250'])
def test_delta2_reconstructs_nested_changes_without_resending_unchanged_items(ws, change):
    a, b, c = ({'id': key, 'body': key * 2200} for key in ('a', 'b', 'c'))
    initial = {'actor_id': 'content:coordinator', 'goal': 'Complete original goal and all conditions.',
               'received_returns': {'recent': [a, b, a, c], 'total': 4},
               'instructions': {'keep': 'REQUIRED_TAIL', 'remove': 'retired'}}
    if change == 'repeated_250':
        initial['received_returns']['recent'] = [a] * 250
    history, full = save(ws, [], initial)
    changed = deepcopy(initial)
    changed['received_returns']['total'] += 1
    if change == 'nested_set_delete':
        changed['instructions'].pop('remove')
        changed['instructions']['new'] = {'reason': 'Current human correction, no scope expansion.'}
    elif change == 'duplicate':
        changed['received_returns']['recent'] = [a, a, b, a, c]
    elif change == 'reorder':
        changed['received_returns']['recent'] = [c, a, a, b]
    elif change == 'clear':
        changed['received_returns']['recent'] = []
    elif change == 'rolling':
        changed['received_returns']['recent'] = [b, a, c, b]
    else:
        changed['received_returns']['recent'] = [b, *([a] * 249)]
    message = produce(ws, history, changed)
    delta = text_json(message)
    assert delta['kind'] == 'delta2', 'A changed established state uses nested delta2'
    assert delta['base_digest'] == full['state_digest']
    assert apply_frame(initial, delta) == changed
    assert delta['state_digest'] == sha(changed)
    assert 'state' not in delta and 'changes' not in delta
    splices = {}
    for operation in delta['ops']:
        assert operation['op'] in ('set', 'delete', 'splice')
        if operation['op'] == 'splice':
            splices.setdefault(tuple(operation['path']), []).append(operation['start'])
    assert all(starts == sorted(starts, reverse=True) for starts in splices.values())
    if change in ('rolling', 'repeated_250'):
        inserted = [item for operation in delta['ops'] if operation['op'] == 'splice'
                    for item in operation['items']]
        assert inserted == [b], 'Rolling/duplicate-rich history must not be replaced wholesale'
        assert len(message.text.encode()) <= len(encoded([b]).encode()) + 1024
    if change == 'nested_set_delete':
        assert any(op['op'] == 'delete' and op['path'] == ['instructions', 'remove'] for op in delta['ops'])
        assert all(op.get('path') != ['received_returns'] for op in delta['ops'])


@pytest.mark.parametrize('old_kind', ['full', 'delta'])
def test_legacy_frames_are_still_a_valid_exact_base_for_delta2(ws, old_kind):
    initial = {'actor_id': 'content:coordinator', 'goal': 'Original complete commission.', 'items': [1, 2]}
    full = {'kind': 'full', 'state': deepcopy(initial), 'state_digest': sha(initial)}
    def old_message(frame, suffix):
        message = HumanMessage(content=encoded(frame), additional_kwargs={
            FRAME: {'receipt': 'task_state_frame:legacy-' + suffix}})
        persist_frame(ws.store, initial['actor_id'], message)
        return message
    history = [old_message(full, 'full')]
    previous = initial
    if old_kind == 'delta':
        previous = {**initial, 'goal': 'Explicitly revised legacy commission.'}
        old_delta = {'kind': 'delta', 'base_digest': sha(initial), 'state_digest': sha(previous),
                     'changes': {'goal': previous['goal']}, 'removed_paths': []}
        history.append(old_message(old_delta, 'delta'))
    changed = {**previous, 'items': [2, 3]}
    new = produce(ws, history, changed)
    assert text_json(new)['kind'] == 'delta2', 'Legacy decoding must not force a fresh unrelated baseline'
    assert text_json(new)['base_digest'] == sha(previous)
    assert apply_frame(previous, text_json(new)) == changed


def test_pending_frame_receipt_is_deterministic_and_has_no_write_before_success(ws):
    context = {'actor_id': 'content:coordinator', 'goal': 'Same original pure inference request.'}
    first = produce(ws, [], context)
    second = produce(ws, [], context)
    assert first.text == second.text
    assert first.additional_kwargs[FRAME] == second.additional_kwargs[FRAME]
    frame = text_json(first)
    assert first.additional_kwargs[FRAME]['receipt'] == 'task_state_frame:' + sha([
        context['actor_id'], None, frame['state_digest'], 'delta2'])
    assert ws.store.get(first.additional_kwargs[FRAME]['receipt']) is None
    history, _ = save(ws, [], context)
    assert produce(ws, history, context) is None, 'An unchanged state creates no additional frame'


def test_broken_delta2_predecessor_cannot_supply_partial_authority(ws):
    initial = {'actor_id': 'content:coordinator', 'goal': 'Actual authority.', 'items': [1, 2, 3]}
    history, _ = save(ws, [], initial)
    corrupted = {'kind': 'delta2', 'base_digest': 'not-the-previous-digest',
                 'state_digest': sha(initial), 'ops': [{'op': 'set', 'path': ['goal'], 'value': 'FAKE'}]}
    message = HumanMessage(content=encoded(corrupted), additional_kwargs={
        FRAME: {'receipt': 'task_state_frame:authenticated-but-invalid-predecessor'}})
    persist_frame(ws.store, initial['actor_id'], message)
    rebuilt = produce(ws, [*history, message], initial)
    assert text_json(rebuilt)['kind'] == 'full'
    assert text_json(rebuilt)['state'] == initial


def test_repeated_transition_keeps_distinct_native_occurrences_and_stable_retry_bytes(ws):
    from langgraph.graph.message import add_messages
    a = {'actor_id': 'content:coordinator', 'goal': 'A'}
    b = {**a, 'goal': 'B'}
    history, _ = save(ws, [], a)
    first_b = produce(ws, history, b)
    retry_b = produce(ws, history, b)
    assert first_b.text == retry_b.text
    assert first_b.additional_kwargs[FRAME] == retry_b.additional_kwargs[FRAME]
    assert first_b.id == retry_b.id, 'Retry of this exact occurrence must not create another native message'
    persist_frame(ws.store, a['actor_id'], first_b)
    history = add_messages(history, [first_b])
    second_a = produce(ws, history, a)
    persist_frame(ws.store, a['actor_id'], second_a)
    history = add_messages(history, [second_a])
    second_b = produce(ws, history, b)
    assert second_b.text == first_b.text
    assert second_b.additional_kwargs[FRAME] == first_b.additional_kwargs[FRAME]
    assert second_b.id != first_b.id, 'Equal transition receipts are not equal native history occurrences'
    persist_frame(ws.store, a['actor_id'], second_b)
    history = add_messages(history, [second_b])
    assert len(history) == 4
    current = None
    for message in history:
        current = apply_frame(current, text_json(message))
    assert current == b


@pytest.mark.parametrize('shape', ['scalar_bool', 'scalar_float', 'nested', 'list_item'])
def test_json_type_change_is_not_mistaken_for_unchanged_python_value(ws, shape):
    initial = {'actor_id': 'content:coordinator', 'goal': 'Exact JSON value types are authoritative.',
               'value': 1, 'nested': {'value': 1}, 'items': [{'value': 1}]}
    history, _ = save(ws, [], initial)
    changed = deepcopy(initial)
    if shape == 'scalar_bool':
        changed['value'] = True
    elif shape == 'scalar_float':
        changed['value'] = 1.0
    elif shape == 'nested':
        changed['nested']['value'] = True
    else:
        changed['items'][0]['value'] = 1.0
    assert initial == changed and sha(initial) != sha(changed), 'This fixture targets Python equality vs JSON identity'
    message = produce(ws, history, changed)
    assert message is not None, 'Different JSON types require a real delta even when Python == is True'
    delta = text_json(message)
    assert delta['kind'] == 'delta2'
    assert sha(apply_frame(initial, delta)) == sha(changed)
