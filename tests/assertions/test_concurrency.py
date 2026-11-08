from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from .sqlite_probe import Action, Packet, Store, Refused


def test_simultaneous_duplicates_return_single_saved_result(tmp_path):
    store = Store.create(tmp_path / 'case.sqlite')
    packet = Packet()
    store.assign(packet, ['A'])
    ready = Barrier(2)

    def submit():
        ready.wait(timeout=5)
        return store.perform(packet, Action())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [job.result(timeout=10) for job in [pool.submit(submit), pool.submit(submit)]]
    assert first == second
    assert store.counts() == (1, 1, 1, 1)


def test_two_valid_packets_still_enforce_producer(tmp_path):
    store = Store.create(tmp_path / 'case.sqlite')
    first, second = Packet(), Packet(actor='writer-2', task='task-2')
    for packet in (first, second):
        store.assign(packet, ['A'])
    store.perform(first, Action())
    with pytest.raises(Refused, match='PRODUCER_CONFLICT'):
        store.perform(second, Action(operation='op-2'))
    assert store.counts() == (1, 1, 1, 1)


def test_packet_check_independent_of_producer(tmp_path):
    store = Store.create(tmp_path / 'case.sqlite')
    packet = Packet()
    store.assign(packet, ['B'])
    with pytest.raises(Refused, match='PACKET_SCOPE'):
        store.perform(packet, Action())
    assert store.counts() == (0, 0, 0, 0)
