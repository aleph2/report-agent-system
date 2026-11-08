"""One owner-authorized extraction, charged against the separate verification allowance."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .request_budget import RequestBudgetExceeded
from .token_budget import TokenBudget

MODEL = "deepseek-v4.1-flash-1017"
# The existing authorized native route reserves this full upper bound before send.
REQUEST_CEILING = 2_000_000
CAMPAIGN_LIMIT = 100_000_000
RUN_LIMIT = 2_200_000
RUN_ID = "o6-hp02-20261108"
FILE = "verification-budget.db"
_COST = """SELECT COALESCE(SUM(a.used),0),COALESCE(SUM(
           CASE WHEN a.state IN ('reserved','unknown') THEN a.reserved ELSE 0 END),0)
           FROM attempts a JOIN verification_requests r ON a.id=r.attempt WHERE r.run=?"""


class O6Budget(TokenBudget):
    @staticmethod
    def initialize(directory):
        root = Path(directory)
        root.mkdir(mode=0o700, exist_ok=False)
        base = TokenBudget(root / FILE, CAMPAIGN_LIMIT, {MODEL: REQUEST_CEILING})
        with closing(base.connect()) as db, db:
            db.execute("CREATE TABLE verification_runs(run TEXT PRIMARY KEY, owned_case TEXT NOT NULL)")
            db.execute("CREATE TABLE verification_requests(attempt TEXT PRIMARY KEY, run TEXT NOT NULL)")

    def __init__(self, directory):
        self.path = (Path(directory) / FILE).absolute()
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("O6_EXISTING_VERIFICATION_LEDGER_REQUIRED")
        with closing(self.connect()) as db:
            self.maximum, encoded = db.execute("SELECT maximum,bounds FROM authorization WHERE id=1").fetchone()
        self.model_bounds = json.loads(encoded)
        if self.maximum != CAMPAIGN_LIMIT or self.model_bounds != {MODEL: REQUEST_CEILING}:
            raise ValueError("O6_AUTHORIZATION_MISMATCH")

    def connect(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=30)

    def claim_launch(self, case):
        with closing(self.connect()) as db, db:
            try:
                db.execute("INSERT INTO verification_runs VALUES(?,?)", (RUN_ID, str(Path(case).resolve())))
            except sqlite3.IntegrityError as exc:
                raise ValueError("O6_ALREADY_LAUNCHED") from exc

    def _reservation_id(self, db, model, bound):
        # The parent holds BEGIN IMMEDIATE through this check and the actual reservation.
        if not db.execute("SELECT 1 FROM verification_runs WHERE run=?", (RUN_ID,)).fetchone():
            raise RequestBudgetExceeded("O6_LAUNCH_REQUIRED")
        if db.execute("SELECT 1 FROM attempts WHERE state IN ('reserved','unknown')").fetchone():
            raise RequestBudgetExceeded("O6_REQUEST_PENDING")
        used, held = db.execute(_COST, (RUN_ID,)).fetchone()
        if used + held + bound > RUN_LIMIT:
            raise RequestBudgetExceeded("O6_RUN_LIMIT")
        identity = str(uuid4())
        db.execute("INSERT INTO verification_requests VALUES(?,?)", (identity, RUN_ID))
        return identity

    def run_totals(self):
        with closing(self.connect()) as db:
            return tuple(db.execute(_COST, (RUN_ID,)).fetchone())
