"""Authorized persistent transport budget shared by every model/tool and case.

Reservations use documented model input+output upper bounds, never prompt estimates.
Unknown responses retain their full reservation. This is not a semantic agent loop.
"""
import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from .request_budget import RequestBudgetExceeded

_active=ContextVar('report_token_budget',default=None)


def current_model_token_bound(model):
    """Read the active authoritative reservation bound; never estimate tokens."""
    budget = _active.get()
    return budget.model_bounds.get(model) if budget is not None else None


class TokenBudget:
    @staticmethod
    def increase_authorization(path, *, previous_maximum, new_maximum,
                               authorization_id, authorization_sha256):
        """Host-only additive grant with CAS/history; never resets attempts.

        The caller must independently verify the human authorization. This is
        not exposed to report agents and does not hotpatch live budget objects.
        A future instance must open with the exact new authorized maximum.
        """
        import re
        if (type(previous_maximum) is not int or type(new_maximum) is not int
                or previous_maximum < 1 or new_maximum <= previous_maximum
                or not isinstance(authorization_id, str) or not authorization_id.strip()
                or not isinstance(authorization_sha256, str)
                or not re.fullmatch(r'[0-9a-f]{64}', authorization_sha256)):
            raise ValueError('EXPLICIT_ADDITIVE_TOKEN_AUTHORIZATION_REQUIRED')
        path = Path(path)
        if not path.is_file():
            raise ValueError('EXISTING_TOKEN_LEDGER_REQUIRED')
        with sqlite3.connect(path, timeout=30) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS authorization_amendments ('
                'id TEXT PRIMARY KEY, previous_maximum INTEGER NOT NULL, new_maximum INTEGER NOT NULL, '
                'authorization_sha256 TEXT NOT NULL, at TEXT NOT NULL)')
            prior = db.execute('SELECT previous_maximum,new_maximum,authorization_sha256 '
                'FROM authorization_amendments WHERE id=?', (authorization_id,)).fetchone()
            expected = (previous_maximum, new_maximum, authorization_sha256)
            current = db.execute('SELECT maximum FROM authorization WHERE id=1').fetchone()
            if prior is not None:
                if tuple(prior) != expected:
                    raise ValueError('TOKEN_AUTHORIZATION_AMENDMENT_CONFLICT')
                return {'applied':False, 'authorization_id':authorization_id,
                        'maximum_tokens':current[0]}
            if current is None or current[0] != previous_maximum:
                raise ValueError('TOKEN_AUTHORIZATION_COMPARE_AND_SWAP_FAILED')
            db.execute('INSERT INTO authorization_amendments VALUES (?,?,?,?,?)',
                (authorization_id, *expected, datetime.now(timezone.utc).isoformat()))
            db.execute('UPDATE authorization SET maximum=? WHERE id=1', (new_maximum,))
        return {'applied':True, 'authorization_id':authorization_id, 'maximum_tokens':new_maximum}

    def __init__(self,path,maximum,model_bounds):
        if type(maximum) is not int or maximum<1 or not model_bounds or any(type(v) is not int or v<1 for v in model_bounds.values()):
            raise ValueError('EXPLICIT_POSITIVE_TOKEN_AUTHORIZATION_REQUIRED')
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.maximum=maximum;self.model_bounds=dict(model_bounds)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS authorization (id INTEGER PRIMARY KEY, maximum INTEGER NOT NULL, bounds TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, model TEXT, reserved INTEGER NOT NULL, used INTEGER, state TEXT NOT NULL, response_id TEXT, reason TEXT, at TEXT NOT NULL)')
            identity=(maximum,json.dumps(self.model_bounds,sort_keys=True))
            row=db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
            if row is not None and tuple(row)!=identity:raise ValueError('TOKEN_AUTHORIZATION_CONFLICT')
            db.execute('INSERT OR IGNORE INTO authorization VALUES (1,?,?)',identity)

    def connect(self):
        return sqlite3.connect(self.path,timeout=30)

    @staticmethod
    def totals(db):
        used,held=db.execute("SELECT COALESCE(SUM(used),0),COALESCE(SUM(CASE WHEN state IN ('reserved','unknown') THEN reserved ELSE 0 END),0) FROM attempts").fetchone()
        return used,held

    def reserve(self,model):
        if model not in self.model_bounds:raise RequestBudgetExceeded('MODEL_TOKEN_BOUND_NOT_VERIFIED')
        bound=self.model_bounds[model]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            used,held=self.totals(db)
            if used+held+bound>self.maximum:raise RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED')
            if db.execute("SELECT 1 FROM attempts WHERE state='bound_violation'").fetchone():raise RequestBudgetExceeded('TOKEN_BOUND_VIOLATION_REQUIRES_DIAGNOSIS')
            identity=str(uuid4())
            db.execute('INSERT INTO attempts VALUES (?,?,?,NULL,\'reserved\',NULL,NULL,?)',
                       (identity,model,bound,datetime.now(timezone.utc).isoformat()))
        return identity

    def before_send_cancelled(self,identity):
        with self.connect() as db:
            db.execute("UPDATE attempts SET state='known_not_sent',used=0,reason='Local transport admission rejected before send' WHERE id=? AND state='reserved'",(identity,))

    def settle(self,identity,usage,response_id=None):
        total=usage.get('total_tokens') if isinstance(usage,dict) else None
        if isinstance(usage,dict) and type(total) is int and total>=0:
            for left,right in (('prompt_tokens','completion_tokens'),('input_tokens','output_tokens')):
                components=[usage[k] for k in (left,right) if k in usage]
                if (any(type(v) is not int or v<0 or v>total for v in components)
                        or (len(components)==2 and sum(components)!=total)):
                    total=None
                    break
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT reserved,state,used FROM attempts WHERE id=?',(identity,)).fetchone()
            if not row:raise ValueError('UNKNOWN_TOKEN_RESERVATION')
            if row[1] in {'settled','bound_violation'}:
                if row[2]!=total:raise ValueError('TOKEN_USAGE_RECONCILIATION_CONFLICT')
                return {'state': row[1], 'used': row[2]}
            if row[1]=='known_not_sent':raise ValueError('UNSENT_REQUEST_HAS_NO_RESPONSE')
            if type(total) is not int or total<0:
                db.execute("UPDATE attempts SET state='unknown',reason='No trustworthy total_tokens; full upper bound retained',response_id=? WHERE id=?",(response_id,identity))
                result = {'state': 'unknown', 'used': None}
            else:
                state='settled' if total<=row[0] else 'bound_violation'
                db.execute('UPDATE attempts SET used=?,state=?,response_id=?,reason=? WHERE id=?',
                    (total,state,response_id,'Cached input is already included; no separate cached addition.',identity))
                result = {'state': state, 'used': total}
        return result

    def snapshot(self):
        with self.connect() as db:
            used,held=self.totals(db)
            counts=dict(db.execute('SELECT state,COUNT(*) FROM attempts GROUP BY state'))
        return {'origin':'authorized_persistent_transport_token_ledger','maximum_tokens':self.maximum,
                'recorded_tokens':used,'reserved_or_unknown_upper_bounds':held,
                'remaining_for_new_reservations':max(0,self.maximum-used-held),'attempt_states':counts,
                'note':'All current authorization cases share this ledger. Cached tokens are included once. Unknown results retain conservative reservations; this does not authorize extra work.'}


@contextmanager
def token_budget(budget):
    token=_active.set(budget)
    try:yield budget
    finally:_active.reset(token)


def current_token_observation():
    budget=_active.get()
    return budget.snapshot() if budget else None


def reserve_request(request):
    from .model_recovery import admit_recovery_request
    admit_recovery_request(request)
    budget=_active.get()
    if budget is None:return None
    body=json.loads(request.content)
    if body.get('stream'):raise RequestBudgetExceeded('STREAM_USAGE_BUDGET_NOT_SUPPORTED')
    if body.get('n',1)!=1:raise RequestBudgetExceeded('MODEL_TOKEN_BOUND_NOT_VERIFIED')
    identity=budget.reserve(body.get('model'))
    request.extensions['report_token_budget']=(budget,identity)
    return budget,identity


async def account_response(response):
    from .transport_observation import has_http_observer, observe_http_phase
    reservation=response.request.extensions.get('report_token_budget')
    if not reservation and not has_http_observer(response.request):return
    await response.aread()
    observe_http_phase(response.request, 'body_read_completed')
    from .model_recovery import capture_response
    if not reservation:
        capture_response(response)
        return
    budget,identity=reservation
    try:body=response.json()
    except (ValueError,UnicodeError):body={}
    if not isinstance(body,dict):body={}
    try:result=budget.settle(identity,body.get('usage'),body.get('id'))
    except Exception as exc:
        response.headers['x-should-retry']='false'
        raise RequestBudgetExceeded('TOKEN_LEDGER_SETTLEMENT_FAILED') from exc
    observe_http_phase(response.request, 'usage_accounted',
                       accounting_state=result['state'], recorded_tokens=result['used'])
    capture_response(response)


def account_response_sync(response):
    from .transport_observation import has_http_observer, observe_http_phase
    reservation=response.request.extensions.get('report_token_budget')
    if not reservation and not has_http_observer(response.request):return
    response.read()
    observe_http_phase(response.request, 'body_read_completed')
    if not reservation:return
    budget,identity=reservation
    try:body=response.json()
    except (ValueError,UnicodeError):body={}
    if not isinstance(body,dict):body={}
    try:result=budget.settle(identity,body.get('usage'),body.get('id'))
    except Exception as exc:
        response.headers['x-should-retry']='false'
        raise RequestBudgetExceeded('TOKEN_LEDGER_SETTLEMENT_FAILED') from exc
    observe_http_phase(response.request, 'usage_accounted',
                       accounting_state=result['state'], recorded_tokens=result['used'])
