"""Test-local S1 transaction proof. No runtime imports this module."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from report_agent.errors import ActionRejected


class Packet(BaseModel):
    """Trusted caller identity and original task bindings from the test dispatcher."""
    model_config = ConfigDict(frozen=True, extra='forbid')
    actor: str = 'writer-1'
    task: str = 'task-1'
    attempt: str = 'attempt-1'
    plan: str = 'plan-v1'
    snapshot: str = 'snapshot-v1'


class Action(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    operation: str = 'op-1'
    slope: str = 'A'
    indicator: str = 'X41'
    proposal: dict = Field(default_factory=dict)


class Refused(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def accept(action):
    return action.proposal, {}


def noop(stage):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        return db

    @classmethod
    def create(cls, path):
        store = cls(path)
        with closing(store.connect()) as db:
            assert db.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
            db.executescript("""
                CREATE TABLE packets (binding TEXT PRIMARY KEY, slopes TEXT NOT NULL, can_read INTEGER NOT NULL);
                CREATE TABLE producers (plan TEXT, slope TEXT, actor TEXT NOT NULL, PRIMARY KEY(plan,slope));
                CREATE TABLE operations (id TEXT PRIMARY KEY, binding TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE judgments (id INTEGER PRIMARY KEY, operation TEXT UNIQUE NOT NULL, row TEXT NOT NULL, status TEXT DEFAULT 'active');
                CREATE TABLE audits (judgment INTEGER PRIMARY KEY REFERENCES judgments(id), checks TEXT NOT NULL);
            """)
        return store

    def assign(self, packet, slopes, *, can_read=True):
        with closing(self.connect()) as db:
            db.execute('INSERT OR REPLACE INTO packets VALUES (?,?,?)',
                       (encoded(packet.model_dump()), encoded(slopes), can_read))

    def perform(self, packet, action, evaluate=accept, checkpoint=noop):
        binding = encoded(packet.model_dump())
        request = hashlib.sha256(encoded(action.model_dump()).encode()).hexdigest()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT binding,digest,result FROM operations WHERE id=?', (action.operation,)).fetchone()
            if prior:
                if prior[:2] != (binding, request):
                    raise Refused('OPERATION_CONFLICT')
                access = db.execute('SELECT can_read FROM packets WHERE binding=?', (binding,)).fetchone()
                if not access or not access[0]:
                    raise Refused('READ_PERMISSION')
                return json.loads(prior[2])
            assignment = db.execute('SELECT slopes FROM packets WHERE binding=?', (binding,)).fetchone()
            if not assignment or action.slope not in json.loads(assignment[0]):
                raise Refused('PACKET_SCOPE')
            scope = (packet.plan, action.slope)
            owner = db.execute('SELECT actor FROM producers WHERE plan=? AND slope=?', scope).fetchone()
            if owner and owner[0] != packet.actor:
                raise Refused('PRODUCER_CONFLICT')
            try:
                effective, checks = evaluate(action)
            except ActionRejected as exc:
                result = {'status': 'refused', 'reason': str(exc)}
            else:
                db.execute('INSERT OR IGNORE INTO producers VALUES (?,?,?)', (*scope, packet.actor))
                rid = db.execute('INSERT INTO judgments(operation,row) VALUES (?,?)',
                                 (action.operation, encoded(effective))).lastrowid
                checkpoint('between_records')
                db.execute('INSERT INTO audits VALUES (?,?)', (rid, encoded(checks)))
                result = {'status': 'committed', 'judgment_id': rid, 'operation': action.operation}
            db.execute('INSERT INTO operations VALUES (?,?,?,?)', (action.operation, binding, request, encoded(result)))
            db.commit()
            checkpoint('after_commit')
            return result

    def result(self, operation):
        with closing(self.connect()) as db:
            row = db.execute('SELECT result FROM operations WHERE id=?', (operation,)).fetchone()
        return json.loads(row[0]) if row else None

    def reviewer_view(self, operation):
        # An independent reader sees only committed records through a read-only connection.
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT j.row,a.checks FROM judgments j JOIN audits a ON a.judgment=j.id WHERE j.operation=?',
                             (operation,)).fetchone()
        return tuple(json.loads(value) for value in row) if row else None

    def counts(self):
        with closing(self.connect()) as db:
            return tuple(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                         for table in ('judgments', 'audits', 'operations', 'producers'))


def _terminate_at(path, packet, action, stage):
    def crash(at):
        if at == stage:
            os._exit(73)
    Store(path).perform(packet, action, checkpoint=crash)


def crash_child(store, packet, action, stage):
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).resolve().parents[1]), env.get('PYTHONPATH', '')])
    child = subprocess.run([sys.executable, '-B', '-m', 'assertions.sqlite_probe', str(store.path),
                            packet.model_dump_json(), action.model_dump_json(), stage], env=env, timeout=15)
    assert child.returncode == 73


if __name__ == '__main__':
    path, packet, action, stage = sys.argv[1:]
    _terminate_at(Path(path), Packet.model_validate_json(packet), Action.model_validate_json(action), stage)
