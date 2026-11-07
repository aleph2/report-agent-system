"""Separate persistent grant for fake-data verification using the normal model HTTP hooks."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

from .request_budget import RequestBudgetExceeded
from .token_budget import TokenBudget, current_token_observation, token_budget


RUN_LIMIT = 3_700_000
CAMPAIGN_LIMIT = 10_000_000
_FILENAME = 'fake-verification-token-budget.db'
_APPLICATION_ID = 0x46564231  # FVB1
_USAGE = """COALESCE(SUM(a.used), 0),
    COALESCE(SUM(CASE WHEN a.state IN ('reserved','unknown') THEN a.reserved ELSE 0 END), 0)"""
_RUN_COSTS = f"""SELECT {_USAGE} FROM attempts a
    JOIN fake_run_attempts r ON r.attempt_id = a.id WHERE r.run_id = ?"""


_RESERVATION_TRIGGER = f"""CREATE TRIGGER fake_reservation AFTER INSERT ON attempts BEGIN
                    SELECT CASE WHEN EXISTS(
                        SELECT 1 FROM attempts WHERE id <> NEW.id AND state IN ('reserved','unknown')
                    ) THEN RAISE(ABORT, 'FAKE_REQUEST_PENDING') END;
                    INSERT INTO fake_run_attempts VALUES (NEW.id, fake_run_id());
                    SELECT CASE WHEN (
                        SELECT SUM(COALESCE(a.used, 0) +
                            CASE WHEN a.state IN ('reserved','unknown') THEN a.reserved ELSE 0 END)
                        FROM attempts a JOIN fake_run_attempts r ON r.attempt_id = a.id
                        WHERE r.run_id = fake_run_id()
                    ) > {RUN_LIMIT} THEN RAISE(ABORT, 'FAKE_RUN_TOKEN_LIMIT') END;
                END;"""
_CONTINUATION_TRIGGER = _RESERVATION_TRIGGER.replace(
    "id <> NEW.id",
    """id <> NEW.id AND NOT EXISTS (
        SELECT 1 FROM fake_continuations c WHERE c.previous_id=attempts.id
        AND c.retry_id=NEW.id AND c.run_id=fake_run_id()
    )""",
)


class FakeVerificationBudget(TokenBudget):
    """Run ids come from the trusted host and stay the same when inspecting a retry."""

    @staticmethod
    def initialize(grant_dir, model_bounds):
        """Explicit one-time bootstrap. All fake cases must share this durable directory."""
        path = Path(grant_dir).absolute() / _FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=False)
        account = TokenBudget(path, CAMPAIGN_LIMIT, model_bounds)
        with closing(account.connect()) as db, db:
            # Run attribution and both guards commit in the same transaction as
            # TokenBudget._reserve's BEGIN IMMEDIATE, including across processes.
            db.executescript(f"""
                BEGIN IMMEDIATE;
                CREATE TABLE fake_run_attempts (
                    attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL
                );
                CREATE INDEX fake_run_attempts_by_run ON fake_run_attempts(run_id);
                {_RESERVATION_TRIGGER}
                PRAGMA application_id={_APPLICATION_ID};
                COMMIT;
            """)

    def __init__(self, grant_dir, run_id):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('FAKE_RUN_ID_REQUIRED')
        self.run_id = run_id
        self.path = Path(grant_dir).absolute() / _FILENAME
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError('FAKE_VERIFICATION_GRANT_REQUIRED')
        with closing(self.connect()) as db:
            self.maximum, bounds = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
            if self.maximum != CAMPAIGN_LIMIT:
                raise ValueError('FAKE_VERIFICATION_AUTHORIZATION_MISMATCH')
            self.model_bounds = json.loads(bounds)

    def connect(self):
        # Opening for inspection or retry must never re-create a missing ledger.
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=30)
        if db.execute('PRAGMA application_id').fetchone()[0] != _APPLICATION_ID:
            db.close()
            raise ValueError('FAKE_VERIFICATION_GRANT_REQUIRED')
        db.create_function('fake_run_id', 0, lambda: self.run_id)
        return db

    def _reserve(self, model, bound):
        try:
            return super()._reserve(model, bound)
        except sqlite3.IntegrityError as exc:
            if str(exc) in {'FAKE_RUN_TOKEN_LIMIT', 'FAKE_REQUEST_PENDING'}:
                raise RequestBudgetExceeded(str(exc)) from exc
            raise

    def run_snapshot(self):
        with closing(self.connect()) as db:
            used, held = db.execute(_RUN_COSTS, (self.run_id,)).fetchone()
        return {'maximum_tokens': RUN_LIMIT, 'settled': used, 'held': held}




class FakeContinuationBudget(FakeVerificationBudget):
    """One fresh reservation beside one named unresolved attempt in the same run."""

    def __init__(self, grant_dir, run_id, previous_attempt):
        super().__init__(grant_dir, run_id)
        self.previous_attempt = previous_attempt

    def _reservation_id(self, db, model, bound):
        # TokenBudget holds BEGIN IMMEDIATE, and already checked total campaign exposure.
        pending = db.execute("""
            SELECT a.id, r.run_id, a.model, a.reserved
            FROM attempts a LEFT JOIN fake_run_attempts r ON r.attempt_id=a.id
            WHERE a.state IN ('reserved','unknown')
        """).fetchall()
        if pending != [(self.previous_attempt,self.run_id,model,bound)]:
            raise RequestBudgetExceeded('FAKE_CONTINUATION_HOLD_MISMATCH')
        db.execute("""CREATE TABLE IF NOT EXISTS fake_continuations (
            previous_id TEXT PRIMARY KEY, retry_id TEXT UNIQUE NOT NULL, run_id TEXT NOT NULL
        )""")
        # Upgrade only the known guard. Ordinary attempts have no matching permit.
        current = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='fake_reservation'").fetchone()
        normalize = lambda sql: ' '.join(sql.rstrip(';').split())
        if current and normalize(current[0]) == normalize(_RESERVATION_TRIGGER):
            db.execute('DROP TRIGGER fake_reservation')
            db.execute(_CONTINUATION_TRIGGER)
        elif not current or normalize(current[0]) != normalize(_CONTINUATION_TRIGGER):
            raise RequestBudgetExceeded('FAKE_CONTINUATION_GUARD_MISMATCH')
        if db.execute('SELECT 1 FROM fake_continuations WHERE previous_id=? OR retry_id=?',
                      (self.previous_attempt,self.previous_attempt)).fetchone():
            raise RequestBudgetExceeded('FAKE_CONTINUATION_ALREADY_USED')
        retry_id = super()._reservation_id(db,model,bound)
        db.execute('INSERT INTO fake_continuations VALUES (?,?,?)',(self.previous_attempt,retry_id,self.run_id))
        return retry_id


@contextmanager
def fake_verification_budget(grant_dir, run_id):
    """Use around the trusted fake host's complete invocation, including its vision calls."""
    if current_token_observation() is not None:
        raise ValueError('FAKE_VERIFICATION_REQUIRES_SEPARATE_GRANT')
    budget = FakeVerificationBudget(grant_dir, run_id)
    with token_budget(budget):
        yield budget
