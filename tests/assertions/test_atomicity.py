from contextlib import closing

import pytest

from .sqlite_probe import Action, Packet, Store, crash_child


@pytest.fixture
def store(tmp_path):
    return Store.create(tmp_path / 'commission.sqlite')


def test_process_death_between_record_and_audit_rolls_back(store):
    packet, action = Packet(), Action()
    store.assign(packet, ['A'])
    crash_child(store, packet, action, 'between_records')
    assert store.counts() == (0, 0, 0, 0)
    assert store.perform(packet, action)['status'] == 'committed'
    assert store.counts() == (1, 1, 1, 1)


def test_sqlite_settings(store):
    with closing(store.connect()) as db:
        assert db.execute('PRAGMA journal_mode').fetchone() == ('wal',)
        assert db.execute('PRAGMA busy_timeout').fetchone() == (5000,)
        assert db.execute('PRAGMA foreign_keys').fetchone() == (1,)
        assert db.execute('PRAGMA synchronous').fetchone() == (2,)
