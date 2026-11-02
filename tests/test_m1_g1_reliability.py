"""M1 local-storage recovery contracts; synthetic data and no provider traffic."""
import sqlite3

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionRejected
from report_agent.store import Store


@pytest.fixture
def quick_busy(monkeypatch):
    original = sqlite3.connect

    def connect(*args, **kwargs):
        kwargs['timeout'] = 0.01
        return original(*args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', connect)


def test_runtime_store_uses_wal_and_full_synchronous(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert db.execute('PRAGMA synchronous').fetchone()[0] == 2


def test_store_refuses_start_when_wal_is_not_available(tmp_path, monkeypatch):
    from types import SimpleNamespace
    connect = sqlite3.connect

    class WalUnavailable:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def __enter__(self):
            self.db.__enter__()
            return self

        def __exit__(self, *args):
            return self.db.__exit__(*args)

        def execute(self, sql, *args, **kwargs):
            if sql.upper().replace(' ', '').startswith('PRAGMAJOURNAL_MODE'):
                return SimpleNamespace(fetchone=lambda: ('delete',))
            return self.db.execute(sql, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: WalUnavailable(connect(*args, **kwargs)))
    with pytest.raises((RuntimeError, ActionRejected), match='(?i)WAL'):
        Store(tmp_path)


def test_long_reader_does_not_block_store_write(tmp_path, quick_busy):
    store = Store(tmp_path)
    store.set('counter', 0)
    reader = sqlite3.connect(store.path)
    try:
        reader.execute('BEGIN')
        assert reader.execute("SELECT value FROM state WHERE key='counter'").fetchone()[0] == '0'
        store.set('counter', 1)
        # The existing reader remains consistent while a new reader sees the commit.
        assert reader.execute("SELECT value FROM state WHERE key='counter'").fetchone()[0] == '0'
        assert store.get('counter') == 1
    finally:
        reader.rollback()
        reader.close()


def test_wal_stale_snapshot_becomes_retryable_only_after_rollback(tmp_path):
    store = Store(tmp_path)
    store.set('counter', 0)
    with pytest.raises(ActionRejected) as failure:
        with store.connect() as stale:
            stale.execute('BEGIN')
            stale.execute("SELECT value FROM state WHERE key='counter'").fetchone()
            with sqlite3.connect(store.path) as other:
                other.execute("UPDATE state SET value='1' WHERE key='counter'")
            stale.execute("UPDATE state SET value='2' WHERE key='counter'")
    assert failure.value.diagnostic['retryable'] is True
    assert store.get('counter') == 1


def test_content_operation_busy_is_retryable_and_same_id_commits_once(tmp_path, quick_busy):
    store = Store(tmp_path)
    contents = ContentStore(store)
    actor = Actor('writer-test', 'writer', 'task-test')
    calls = []

    def execute(db):
        calls.append('execute')
        db.execute("INSERT INTO state VALUES ('effect', '1')")
        return {'saved': True}

    locker = sqlite3.connect(store.path)
    try:
        locker.execute('BEGIN IMMEDIATE')
        with pytest.raises(ActionRejected) as failure:
            contents.operation(actor, 'operation-test', {'save': 1}, execute)
        assert failure.value.diagnostic['retryable'] is True
        assert calls == []
    finally:
        locker.rollback()
        locker.close()
    first = contents.operation(actor, 'operation-test', {'save': 1}, execute)
    assert first['ok'] is True
    assert contents.operation(actor, 'operation-test', {'save': 1}, execute) == first
    assert calls == ['execute'] and store.get('effect') == 1


def test_busy_inside_local_callback_rolls_back_without_permanent_failure_receipt(tmp_path):
    from report_agent.errors import LocalStorageBusy
    store = Store(tmp_path)
    contents = ContentStore(store)
    actor = Actor('writer-test', 'writer', 'task-test')
    calls = []

    def execute(db):
        calls.append(True)
        db.execute("INSERT INTO state VALUES ('callback-effect', '1')")
        if len(calls) == 1:
            raise LocalStorageBusy()
        return {'saved': True}

    with pytest.raises(LocalStorageBusy) as failure:
        contents.operation(actor, 'callback-test', {'save': 1}, execute)
    assert failure.value.diagnostic['retryable'] is True
    assert store.get('callback-effect') is None
    assert contents.receipt(actor, 'callback-test')['state'] == 'unknown'
    assert contents.operation(actor, 'callback-test', {'save': 1}, execute)['ok'] is True
    assert store.get('callback-effect') == 1 and len(calls) == 2


def test_commit_busy_retries_same_transaction_without_reexecuting_callback(tmp_path, monkeypatch):
    from report_agent.store import _Connection
    store = Store(tmp_path)
    contents = ContentStore(store)
    actor = Actor('writer-test', 'writer', 'task-test')
    original_retry = _Connection._local_retry
    attempts, effects = [], []

    def retry(self, action):
        if getattr(action, '__name__', '') != 'commit':
            return original_retry(self, action)

        def commit():
            attempts.append(True)
            if len(attempts) == 1:
                error = sqlite3.OperationalError('synthetic commit lock')
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error
            return action()

        return original_retry(self, commit)

    monkeypatch.setattr(_Connection, '_local_retry', retry)

    def execute(db):
        effects.append(True)
        db.execute("INSERT INTO state VALUES ('commit-effect', '1')")
        return {'saved': True}

    result = contents.operation(actor, 'commit-test', {'save': 1}, execute)
    assert result['ok'] is True and len(attempts) == 2 and len(effects) == 1
    assert store.get('commit-effect') == 1


def test_post_external_write_failure_cannot_repeat_external_work(tmp_path, quick_busy):
    store = Store(tmp_path)
    contents = ContentStore(store)
    actor = Actor('layout-test', 'layout', 'task-test')
    locker = sqlite3.connect(store.path)
    calls = []

    def external(prepared):
        calls.append('external')
        locker.execute('BEGIN IMMEDIATE')
        return {'received': True}

    try:
        with pytest.raises(ActionRejected) as failure:
            contents.detached_operation(actor, 'external-test', {'render': 1},
                lambda db: {'prepared': True}, external, lambda db, prepared, result: result)
    finally:
        locker.rollback()
        locker.close()
    assert calls == ['external']
    assert failure.value.diagnostic['retryable'] is False
    assert contents.receipt(actor, 'external-test')['state'] == 'outcome_unresolved'
    with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
        contents.detached_operation(actor, 'external-test', {'render': 1},
            lambda db: {}, external, lambda db, prepared, result: result)
    assert calls == ['external']


@pytest.mark.parametrize('phase', ['prepare', 'finalize'])
def test_detached_callback_busy_preserves_correct_retry_boundary(tmp_path, phase):
    from report_agent.errors import LocalStorageBusy
    store = Store(tmp_path)
    contents = ContentStore(store)
    actor = Actor('layout-test', 'layout', 'task-test')
    external_calls, local_calls = [], []

    def local(db):
        local_calls.append(True)
        db.execute("INSERT INTO state VALUES ('local-effect', '1')")
        if len(local_calls) == 1:
            raise LocalStorageBusy()
        return {'prepared': True}

    def external(prepared):
        external_calls.append(True)
        return {'received': True}

    def invoke():
        return contents.detached_operation(actor, 'callback-external', {'render': 1},
            local if phase == 'prepare' else lambda db: {}, external,
            (lambda db, prepared, result: local(db)) if phase == 'finalize' else lambda db, prepared, result: result)

    with pytest.raises(LocalStorageBusy) as failure:
        invoke()
    assert store.get('local-effect') is None
    if phase == 'prepare':
        assert failure.value.diagnostic['retryable'] is True
        assert external_calls == []
        assert contents.receipt(actor, 'callback-external')['state'] == 'unknown'
        assert invoke()['ok'] is True and len(external_calls) == 1
    else:
        assert failure.value.diagnostic['retryable'] is False
        assert len(external_calls) == 1
        assert contents.receipt(actor, 'callback-external')['state'] == 'outcome_unresolved'
        with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
            invoke()
        assert len(external_calls) == 1


async def test_vision_admission_busy_does_not_dispatch_and_can_be_retried(tmp_path, quick_busy):
    from report_agent.vision import observe_source_image
    from test_document_tools import workspace
    from test_vision import VisionModel

    work = workspace(tmp_path)
    client = VisionModel()
    locker = sqlite3.connect(work.store.path)
    try:
        locker.execute('BEGIN IMMEDIATE')
        with pytest.raises(ActionRejected) as failure:
            await observe_source_image(work, 'original', 'read', client=client)
        assert failure.value.diagnostic['retryable'] is True
        assert client.calls == []
    finally:
        locker.rollback()
        locker.close()
    result = await observe_source_image(work, 'original', 'read', client=client)
    assert result['status'] == 'observed'
    assert len(client.calls) == 1
    repeated = await observe_source_image(work, 'original', 'read', client=client)
    assert repeated['reused'] is True and len(client.calls) == 1


async def test_vision_outcome_write_busy_is_unresolved_not_tool_retry_permission(tmp_path, quick_busy):
    from report_agent.vision import observe_source_image
    from test_document_tools import workspace
    from test_vision import VisionModel

    work = workspace(tmp_path)
    locker = sqlite3.connect(work.store.path)

    class OutcomeWriteBusy(VisionModel):
        async def create(self, **kwargs):
            result = await super().create(**kwargs)
            locker.execute('BEGIN IMMEDIATE')
            return result

    client = OutcomeWriteBusy()
    try:
        with pytest.raises(ActionRejected) as failure:
            await observe_source_image(work, 'original', 'read', client=client)
    finally:
        locker.rollback()
        locker.close()
    assert len(client.calls) == 1
    assert failure.value.diagnostic['retryable'] is False
    with work.store.connect() as db:
        import json
        attempts = [json.loads(row[0]) for row in db.execute("SELECT value FROM state WHERE key LIKE 'vision_attempt:%'")]
    assert len(attempts) == 1 and attempts[0]['state'] == 'reserved'
    with pytest.raises(ActionRejected, match='VISION_OUTCOME_UNRESOLVED'):
        await observe_source_image(work, 'original', 'read', client=client)
    assert len(client.calls) == 1


@pytest.mark.parametrize('diagnostic_busy', [False, True])
async def test_native_graph_observes_retryable_storage_error_and_continues(ws, monkeypatch, offline, diagnostic_busy):
    from report_agent import deep_runtime, vision_admission
    from report_agent.errors import LocalStorageBusy
    from test_deep_runtime import Driver, invoke, observation
    from test_vision import VisionModel

    client = VisionModel()
    monkeypatch.setattr('report_agent.vision.configured_vision_client', lambda: client)
    monkeypatch.setattr('report_agent.document_tools.vision_source_image',
        lambda workspace, source, page, crop: (b'synthetic-image',
            {'source_id': source, 'sha256': 'f' * 64, 'page': page, 'crop': crop}))
    original = vision_admission.reserve_vision
    attempted = []

    def reserve(*args, **kwargs):
        attempted.append(True)
        if len(attempted) == 1:
            raise LocalStorageBusy('LOCAL_STORAGE_BUSY', diagnostic={'retryable': True})
        return original(*args, **kwargs)

    monkeypatch.setattr(vision_admission, 'reserve_vision', reserve)
    if diagnostic_busy:
        from report_agent.repetition_guard import KnownWriteRepetition
        original_observe = KnownWriteRepetition.observe

        def observe(self, call, result, messages):
            if 'LOCAL_STORAGE_BUSY' in str(getattr(result, 'content', '')):
                raise LocalStorageBusy('LOCAL_STORAGE_BUSY', diagnostic={'retryable': True})
            return original_observe(self, call, result, messages)

        monkeypatch.setattr(KnownWriteRepetition, 'observe', observe)

    def retry(messages):
        result = observation(messages, 'analyze_source_image')
        assert result['ok'] is False and result['retryable'] is True
        assert client.calls == []
        return invoke('analyze_source_image', source_id='s', question='read')

    driver = Driver(coordinator=[invoke('analyze_source_image', source_id='s', question='read'),
        retry, AIMessage(content='Observation received; report is not yet complete.')])
    await deep_runtime.run_report(ws, driver)
    assert len(driver.calls) == 3 and len(client.calls) == 1
    assert not [event for event in ws.store.events() if event['kind'] == 'deep_run_error']


# Reuse the repository's isolated native harness and explicit network prohibition.
from test_task_supervision import ws, offline  # noqa: E402,F401
