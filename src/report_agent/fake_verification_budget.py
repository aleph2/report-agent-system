"""Separate persistent grant for fake-data verification using the normal model HTTP hooks."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

from .request_budget import RequestBudgetExceeded
from .token_budget import TokenBudget, current_token_observation, token_budget


RUN_LIMIT = 3_700_000
LEDGER_FILENAME = 'fake-verification-token-budget.db'
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

# A permit names one new request and its owning run. Other callers remain subject
# to the existing pending-request trigger, including the historical one-shot route.
_COMPARISON_TRIGGER = _CONTINUATION_TRIGGER.replace(
    "id <> NEW.id", """id <> NEW.id AND NOT EXISTS (SELECT 1 FROM fake_comparison_requests p
        WHERE p.held_id=attempts.id AND p.request_id=NEW.id AND p.run_id=fake_run_id())""",
)


class FakeVerificationBudget(TokenBudget):
    """Run ids come from the trusted host and stay the same when inspecting a retry."""

    @staticmethod
    def initialize(grant_dir, model_bounds, *, maximum_tokens):
        """Explicit one-time bootstrap. All fake cases must share this durable directory."""
        path = Path(grant_dir).absolute() / LEDGER_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=False)
        account = TokenBudget(path, maximum_tokens, model_bounds)
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

    def __init__(self, grant_dir, run_id, *, aggregate_tokens=None):
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError('FAKE_RUN_ID_REQUIRED')
        self.run_id = run_id
        self.path = Path(grant_dir).absolute() / LEDGER_FILENAME
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError('FAKE_VERIFICATION_GRANT_REQUIRED')
        with closing(self.connect(read_only=True)) as db:
            self.maximum, bounds = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
            if (type(self.maximum) is not int or self.maximum < 1
                    or aggregate_tokens is not None and self.maximum != aggregate_tokens):
                raise ValueError('FAKE_VERIFICATION_AUTHORIZATION_MISMATCH')
            self.model_bounds = json.loads(bounds)

    def connect(self, *, read_only=False):
        # Opening for inspection or retry must never re-create a missing ledger.
        db = sqlite3.connect(self.path.as_uri() + ('?mode=ro' if read_only else '?mode=rw'), uri=True, timeout=30)
        if read_only:
            db.execute('PRAGMA query_only=ON')
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

    def __init__(self, grant_dir, run_id, previous_attempt, *, aggregate_tokens=None):
        super().__init__(grant_dir, run_id, aggregate_tokens=aggregate_tokens)
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
        elif not current or normalize(current[0]) not in {normalize(_CONTINUATION_TRIGGER), normalize(_COMPARISON_TRIGGER), normalize(_FLOW_TRIGGER)}:
            raise RequestBudgetExceeded('FAKE_CONTINUATION_GUARD_MISMATCH')
        if db.execute('SELECT 1 FROM fake_continuations WHERE previous_id=? OR retry_id=?',
                      (self.previous_attempt,self.previous_attempt)).fetchone():
            raise RequestBudgetExceeded('FAKE_CONTINUATION_ALREADY_USED')
        retry_id = super()._reservation_id(db,model,bound)
        db.execute('INSERT INTO fake_continuations VALUES (?,?,?)',(self.previous_attempt,retry_id,self.run_id))
        return retry_id


class FakeComparisonBudget(FakeVerificationBudget):
    """Fresh runs under one pinned campaign with an identified historical hold."""

    def __init__(self, grant_dir, run_id, comparison, comparison_sha256, *, qualitative_only=False, aggregate_tokens=None):
        super().__init__(grant_dir, run_id, aggregate_tokens=aggregate_tokens)
        if (len(comparison['run_ids']) != (1 if qualitative_only else 2)
                or run_id not in comparison['run_ids'] or run_id == comparison['previous_run_id']):
            raise ValueError('FAKE_COMPARISON_RUN_MISMATCH')
        self._campaign_model_bounds = dict(self.model_bounds)
        self.comparison = comparison
        self.comparison_sha256 = comparison_sha256
        self.qualitative_only = qualitative_only

    def _check_hold(self, db, model, bound):
        c = self.comparison
        if self._campaign_model_bounds != {model: bound} or model != 'glm-5.3' or bound != 1_179_648:
            raise RequestBudgetExceeded('FAKE_COMPARISON_BOUND_MISMATCH')
        pending = db.execute("""SELECT a.id,r.run_id,a.model,a.reserved,a.used
            FROM attempts a LEFT JOIN fake_run_attempts r ON r.attempt_id=a.id
            WHERE a.state IN ('reserved','unknown')""").fetchall()
        if pending != [(c['previous_attempt'], c['previous_run_id'], model, bound, None)]:
            raise RequestBudgetExceeded('FAKE_COMPARISON_HOLD_MISMATCH')
        mapped = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fake_continuations'").fetchone()
        settled = mapped and db.execute("""SELECT a.used FROM fake_continuations c
            JOIN attempts a ON a.id=c.retry_id JOIN fake_run_attempts r ON r.attempt_id=a.id
            WHERE c.previous_id=? AND c.retry_id=? AND c.run_id=? AND r.run_id=c.run_id
            AND a.model=? AND a.reserved=? AND a.state='settled' AND a.used BETWEEN 0 AND a.reserved""",
            (c['previous_attempt'], c['settled_retry_attempt'], c['previous_run_id'], model, bound)).fetchone()
        if not settled:
            raise RequestBudgetExceeded('FAKE_COMPARISON_RETRY_MISMATCH')

        if self.qualitative_only:
            return
        first,second = c['run_ids']
        if self.run_id == second:
            table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fake_comparison_terminals'").fetchone()
            ready = table and db.execute("""SELECT settled FROM fake_comparison_terminals
                WHERE run_id=? AND comparison_sha256=?""", (first,self.comparison_sha256)).fetchone()
            if not ready or db.execute(_RUN_COSTS,(first,)).fetchone()!=(ready[0],0):
                raise RequestBudgetExceeded('FAKE_COMPARISON_FIRST_TERMINAL_REQUIRED')

    def record_first_terminal(self, result):
        if self.qualitative_only or self.run_id != self.comparison['run_ids'][0]:
            return
        status = result.get('status')
        if status == 'incomplete':
            slopes = result.get('slopes', [])
            if [s.get('object_id') for s in slopes] != ['A','B']:
                return
            for slope in slopes:
                steps = slope.get('indicator_steps') or {}
                progress = steps.get('progress') or {}
                stopped = steps.get('interrupted_indicators', {})
                if (slope.get('status') not in {'closed_with_gaps','assessment_saved','incomplete'}
                        or progress.get('total') != 11 or progress.get('recorded') != 11-len(stopped)
                        or any(row.get('status') != 'interrupted: save rejected'
                               or len(row.get('refusals', [])) != 2 for row in stopped.values())):
                    return
        elif status not in {'closed_with_gaps','assessments_saved'}:
            return
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._check_hold(db, 'glm-5.3', 1_179_648)
            settled,held = db.execute(_RUN_COSTS,(self.run_id,)).fetchone()
            if (result.get('run_id')!=self.run_id or result.get('comparison_sha256')!=self.comparison_sha256
                    or not result.get('finished_at_utc') or held or not settled
                    or result.get('budget')!={'settled':settled,'held':0,'maximum_tokens':RUN_LIMIT}):
                raise RequestBudgetExceeded('FAKE_COMPARISON_FIRST_TERMINAL_REQUIRED')
            db.execute("""CREATE TABLE IF NOT EXISTS fake_comparison_terminals
                (run_id TEXT PRIMARY KEY, comparison_sha256 TEXT NOT NULL, settled INTEGER NOT NULL)""")
            db.execute('INSERT INTO fake_comparison_terminals VALUES (?,?,?)',
                       (self.run_id,self.comparison_sha256,settled))

    def check_fresh(self):
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._check_hold(db, 'glm-5.3', 1_179_648)
            if db.execute('SELECT 1 FROM fake_run_attempts WHERE run_id=?',(self.run_id,)).fetchone():
                raise RequestBudgetExceeded('FAKE_COMPARISON_RUN_ALREADY_COUNTED')

    def _reservation_id(self, db, model, bound):
        # Called inside the normal reservation's BEGIN IMMEDIATE after the campaign cap.
        self._check_hold(db, model, bound)
        current = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='fake_reservation'").fetchone()
        normalize = lambda sql: ' '.join(sql.rstrip(';').split())
        if current and normalize(current[0]) == normalize(_CONTINUATION_TRIGGER):
            db.execute("""CREATE TABLE fake_comparison_requests (
                request_id TEXT PRIMARY KEY, held_id TEXT NOT NULL, run_id TEXT NOT NULL)""")
            db.execute('DROP TRIGGER fake_reservation')
            db.execute(_COMPARISON_TRIGGER)
        elif not current or normalize(current[0]) not in {normalize(_COMPARISON_TRIGGER),normalize(_FLOW_TRIGGER)}:
            raise RequestBudgetExceeded('FAKE_COMPARISON_GUARD_MISMATCH')
        identity = super()._reservation_id(db, model, bound)
        db.execute('INSERT INTO fake_comparison_requests VALUES (?,?,?)',
                   (identity, self.comparison['previous_attempt'], self.run_id))
        return identity


@contextmanager
def fake_verification_budget(grant_dir, run_id, *, comparison=None, comparison_sha256=None, qualitative_only=False, aggregate_tokens=None):
    """Use around the trusted fake host's complete invocation, including its vision calls."""
    if current_token_observation() is not None:
        raise ValueError('FAKE_VERIFICATION_REQUIRES_SEPARATE_GRANT')
    budget = (FakeComparisonBudget(grant_dir, run_id, comparison, comparison_sha256,
                                   qualitative_only=qualitative_only, aggregate_tokens=aggregate_tokens) if comparison is not None
              else FakeVerificationBudget(grant_dir, run_id, aggregate_tokens=aggregate_tokens))
    with token_budget(budget):
        yield budget


_FLOW_TRIGGER = _COMPARISON_TRIGGER.replace(str(RUN_LIMIT),
    f"COALESCE((SELECT maximum FROM fake_flow_runs WHERE run_id=fake_run_id()), {RUN_LIMIT})")


class FakeFlowBudget(FakeComparisonBudget):
    """One owner-capped full-flow run alongside the named preserved hold."""
    def __init__(self, grant_dir, run_id, comparison, authority_sha256, *, maximum_tokens, model_bounds=None, aggregate_tokens=None):
        super().__init__(grant_dir, run_id, comparison, authority_sha256, qualitative_only=True, aggregate_tokens=aggregate_tokens)
        if type(maximum_tokens) is not int or not 0 < maximum_tokens <= self.maximum:
            raise ValueError('FAKE_FLOW_LIMIT_INVALID')
        self.run_limit = maximum_tokens
        if model_bounds is not None:
            if (not model_bounds or any(not isinstance(k, str) or not k.strip() or type(v) is not int or v <= 0
                                       for k, v in model_bounds.items())
                    or any(k in self.model_bounds and self.model_bounds[k] != v for k, v in model_bounds.items())):
                raise ValueError('FAKE_FLOW_MODEL_BOUNDS_INVALID')
            self.model_bounds = {**self.model_bounds, **model_bounds}

    def _check_hold(self, db, model, bound):
        super()._check_hold(db, 'glm-5.3', 1_179_648)
        if self.model_bounds.get(model) != bound:
            raise RequestBudgetExceeded('FAKE_FLOW_MODEL_BOUND_MISMATCH')

    def _reservation_id(self, db, model, bound):
        # The existing campaign transaction serializes all roles and preserves the old hold.
        self._check_hold(db, model, bound)
        db.execute('CREATE TABLE IF NOT EXISTS fake_flow_runs '
                   '(run_id TEXT PRIMARY KEY, maximum INTEGER NOT NULL, authority TEXT NOT NULL)')
        binding = (self.run_limit, self.comparison_sha256)
        prior = db.execute('SELECT maximum,authority FROM fake_flow_runs WHERE run_id=?',
                           (self.run_id,)).fetchone()
        if prior is not None and prior != binding:
            raise RequestBudgetExceeded('FAKE_FLOW_AUTHORITY_CHANGED')
        normalize = lambda sql: ' '.join(sql.rstrip(';').split())
        current = db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='fake_reservation'").fetchone()
        if not current or normalize(current[0]) not in {normalize(sql) for sql in
                (_RESERVATION_TRIGGER, _CONTINUATION_TRIGGER, _COMPARISON_TRIGGER, _FLOW_TRIGGER)}:
            raise RequestBudgetExceeded('FAKE_COMPARISON_GUARD_MISMATCH')
        db.execute('INSERT OR IGNORE INTO fake_flow_runs VALUES (?,?,?)', (self.run_id, *binding))
        db.execute('CREATE TABLE IF NOT EXISTS fake_comparison_requests '
                   '(request_id TEXT PRIMARY KEY, held_id TEXT NOT NULL, run_id TEXT NOT NULL)')
        if normalize(current[0]) != normalize(_FLOW_TRIGGER):
            db.execute('DROP TRIGGER fake_reservation')
            db.execute(_FLOW_TRIGGER)
        identity = TokenBudget._reservation_id(self, db, model, bound)
        db.execute('INSERT INTO fake_comparison_requests VALUES (?,?,?)',
                   (identity, self.comparison['previous_attempt'], self.run_id))
        return identity

    def run_snapshot(self):
        return {**super().run_snapshot(), 'maximum_tokens': self.run_limit}
