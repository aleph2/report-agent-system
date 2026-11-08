from contextlib import closing

import pytest

from .sqlite_probe import Action, Packet, Store, Refused, crash_child


def test_reopen_two_actions_retry_only_committed_action_after_status_change(tmp_path):
    path = tmp_path / 'case.sqlite'
    store = Store.create(path)
    packet = Packet()
    first, second = Action(), Action(operation='op-2', indicator='X42')
    store.assign(packet, ['A'])
    crash_child(store, packet, first, 'after_commit')
    reopened = Store(path)
    recorded = reopened.result(first.operation)
    assert recorded and reopened.result(second.operation) is None
    # The original record was superseded while the reply was lost.
    with closing(reopened.connect()) as db:
        db.execute("UPDATE judgments SET status='superseded' WHERE operation=?", (first.operation,))
    reopened.assign(packet, [])
    assert reopened.perform(packet, first) == recorded
    with pytest.raises(Refused, match='PACKET_SCOPE'):
        reopened.perform(packet, second)
    assert reopened.counts() == (1, 1, 1, 1)
    reopened.assign(packet, ['A'])
    assert reopened.perform(packet, second) != recorded
    assert reopened.counts() == (2, 2, 2, 1)


@pytest.mark.parametrize('field', ['actor', 'task', 'attempt', 'plan', 'snapshot', 'payload'])
def test_reused_operation_requires_identical_request_actor_and_bindings(tmp_path, field):
    store = Store.create(tmp_path / 'case.sqlite')
    packet, action = Packet(), Action()
    store.assign(packet, ['A'])
    store.perform(packet, action)
    if field == 'payload':
        action = action.model_copy(update={'proposal': {'value': 42}})
    else:
        packet = packet.model_copy(update={field: 'other'})
    with pytest.raises(Refused, match='OPERATION_CONFLICT'):
        store.perform(packet, action)
    assert store.counts() == (1, 1, 1, 1)


def test_receipt_lookup_honours_revoked_read_access(tmp_path):
    store = Store.create(tmp_path / 'case.sqlite')
    packet, action = Packet(), Action()
    store.assign(packet, ['A'])
    store.perform(packet, action)
    store.assign(packet, [], can_read=False)
    with pytest.raises(Refused, match='READ_PERMISSION'):
        store.perform(packet, action)
    assert store.counts() == (1, 1, 1, 1)
