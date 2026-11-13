"""Authorized persistent transport budget shared by every model/tool and case.

Reservations use documented model input+output upper bounds, never prompt estimates.
Unknown responses retain their full reservation. This is not a semantic agent loop.
"""
import json
import hashlib
import re
from dataclasses import dataclass
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from .request_budget import RequestBudgetExceeded

_active=ContextVar('report_token_budget',default=None)
_request_bound = ContextVar('report_request_token_bound', default=None)


@dataclass(frozen=True)
class RequestBound:
    """Trusted host-verified limits; a proof hash is provenance, not verification.

    Never construct this from a model response or caller-controlled tool arguments.
    The host must verify the service/model's hard limits before activating it.
    """
    model: str
    request_url_sha256: str
    input_limit: int
    output_limit: int
    proof_sha256: str
    image_max_edge: int | None = None
    wire_output_limit: int | None = None

    def __post_init__(self):
        if (not isinstance(self.model, str) or not self.model.strip()
                or any(type(n) is not int or n < 1 for n in (self.input_limit, self.output_limit))
                or any(not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h)
                       for h in (self.request_url_sha256, self.proof_sha256))):
            raise ValueError('VERIFIED_REQUEST_TOKEN_BOUND_REQUIRED')
        if ((self.image_max_edge is not None and (type(self.image_max_edge) is not int or not 1 <= self.image_max_edge <= 4096))
                or (self.wire_output_limit is not None and (type(self.wire_output_limit) is not int or not 0 < self.wire_output_limit <= self.output_limit))):
            raise ValueError('VERIFIED_REQUEST_TOKEN_BOUND_REQUIRED')

    @property
    def total(self):
        return self.input_limit + self.output_limit


@contextmanager
def request_token_bound(bound):
    """Host-only lexical override; nested recovery cannot replace its limits."""
    policies = (bound,) if isinstance(bound, RequestBound) else bound
    if (not isinstance(policies, tuple) or not policies or not all(isinstance(p, RequestBound) for p in policies)
            or len({p.model for p in policies}) != len(policies)):
        raise TypeError('VERIFIED_REQUEST_TOKEN_BOUND_REQUIRED')
    outer = _request_bound.get()
    if outer is not None and outer != bound:
        raise RequestBudgetExceeded('SCOPED_REQUEST_BOUND_CONFLICT')
    token = _request_bound.set(bound)
    try:
        yield bound
    finally:
        _request_bound.reset(token)


def _selected_bound(model):
    scoped = _request_bound.get()
    policies = (scoped,) if isinstance(scoped, RequestBound) else scoped or ()
    return next((p for p in policies if p.model == model), None)


def _effective_bound(budget, model):
    bound = _selected_bound(model)
    registered = budget.model_bounds.get(model)
    if bound is None:
        if _request_bound.get() is not None:
            raise RequestBudgetExceeded('SCOPED_REQUEST_BOUND_NOT_VERIFIED')
        return registered
    if model != bound.model or registered is None or bound.total > registered:
        raise RequestBudgetExceeded('SCOPED_REQUEST_BOUND_NOT_VERIFIED')
    return bound.total


def _contains_multimodal(value):
    if isinstance(value, dict):
        return bool({'image_url', 'input_image', 'input_audio', 'audio', 'video_url', 'input_file'} & value.keys()) or any(
            _contains_multimodal(v) for v in value.values())
    return isinstance(value, list) and any(_contains_multimodal(v) for v in value)


def _validate_bounded_request(request, body):
    if _request_bound.get() is None:
        return
    bound = _selected_bound(body.get('model')) if isinstance(body, dict) else None
    if (bound is None or not isinstance(body, dict) or body.get('model') != bound.model
            or hashlib.sha256(str(request.url).encode()).hexdigest() != bound.request_url_sha256
            or body.get('stream', False) is not False
            or type(body.get('n', 1)) is not int or body.get('n', 1) != 1):
        raise RequestBudgetExceeded('SCOPED_REQUEST_WIRE_MISMATCH')
    outputs = [body[k] for k in ('max_tokens', 'max_completion_tokens') if k in body]
    if not outputs or any(type(n) is not int or not 0 < n <= (bound.wire_output_limit or bound.output_limit) for n in outputs):
        raise RequestBudgetExceeded('SCOPED_REQUEST_OUTPUT_LIMIT_REQUIRED')
    if bound.image_max_edge is not None:
        _validate_image_request(body, bound)
        return
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages:
        raise RequestBudgetExceeded('SCOPED_REQUEST_TEXT_ONLY')
    for message in messages:
        if not isinstance(message, dict):
            raise RequestBudgetExceeded('SCOPED_REQUEST_TEXT_ONLY')
        content = message.get('content')
        if content is None and message.get('role') == 'assistant':
            continue
        if isinstance(content, str):
            continue
        if not isinstance(content, list) or any(
                not isinstance(part, dict) or set(part) != {'type', 'text'}
                or part['type'] != 'text' or not isinstance(part['text'], str) for part in content):
            raise RequestBudgetExceeded('SCOPED_REQUEST_TEXT_ONLY')
    # Reject extra multimodal channels even when messages themselves are text.
    if _contains_multimodal(body) or any(key in body for key in ('modalities', 'image', 'images')):
        raise RequestBudgetExceeded('SCOPED_REQUEST_TEXT_ONLY')



def _validate_image_request(body, bound):
    """One bounded inline PNG in a trusted vision request, not arbitrary modalities."""
    import base64
    from io import BytesIO
    from PIL import Image
    try:
        if 'max_tokens' in body or 'max_completion_tokens' not in body or body.get('tools'):
            raise ValueError('Unexpected vision request')
        images = 0
        cleaned = []
        for message in body['messages']:
            content = message['content']
            if isinstance(content, str):
                cleaned.append(message)
                continue
            parts = []
            for part in content:
                if set(part) == {'type', 'text'} and part['type'] == 'text' and isinstance(part['text'], str):
                    parts.append(part)
                    continue
                if set(part) != {'type', 'image_url'} or part['type'] != 'image_url':
                    raise ValueError('Unsupported modality')
                url = part['image_url']['url']
                if not url.startswith('data:image/png;base64,'):
                    raise ValueError('Inline PNG required')
                png = base64.b64decode(url.split(',',1)[1], validate=True)
                if len(png) > bound.image_max_edge ** 2 * 4 + 1024:
                    raise ValueError('Oversized PNG')
                with Image.open(BytesIO(png)) as image:
                    if (image.format != 'PNG' or max(image.size) > bound.image_max_edge
                            or getattr(image, 'n_frames', 1) != 1):
                        raise ValueError('Image outside host envelope')
                    image.verify()
                images += 1
            cleaned.append({**message, 'content': parts})
        if images != 1 or _contains_multimodal({**body, 'messages': cleaned}):
            raise ValueError('One image only')
    except Exception as error:
        raise RequestBudgetExceeded('SCOPED_REQUEST_IMAGE_POLICY_MISMATCH') from error


def current_model_token_bound(model):
    """Read the active authoritative reservation bound; never estimate tokens."""
    budget = _active.get()
    return _effective_bound(budget, model) if budget is not None else None


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
        return self._reserve(model, self.model_bounds.get(model))

    def _reservation_id(self, db, model, bound):
        return str(uuid4())

    def _reserve(self, model, bound):
        if model not in self.model_bounds:raise RequestBudgetExceeded('MODEL_TOKEN_BOUND_NOT_VERIFIED')
        if type(bound) is not int or not 0 < bound <= self.model_bounds[model]:
            raise RequestBudgetExceeded('SCOPED_REQUEST_BOUND_NOT_VERIFIED')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            used,held=self.totals(db)
            if used+held+bound>self.maximum:raise RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED')
            if db.execute("SELECT 1 FROM attempts WHERE state='bound_violation'").fetchone():raise RequestBudgetExceeded('TOKEN_BOUND_VIOLATION_REQUIRES_DIAGNOSIS')
            identity=self._reservation_id(db, model, bound)
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
            return self._snapshot(db)

    def _snapshot(self, db):
        used,held=self.totals(db)
        counts=dict(db.execute('SELECT state,COUNT(*) FROM attempts GROUP BY state'))
        return {'origin':'authorized_persistent_transport_token_ledger','maximum_tokens':self.maximum,
                'recorded_tokens':used,'reserved_or_unknown_upper_bounds':held,
                'remaining_for_new_reservations':max(0,self.maximum-used-held),'attempt_states':counts,
                'note':'All current authorization cases share this ledger. Cached tokens are included once. Unknown results retain conservative reservations; this does not authorize extra work.'}


_LEGACY_CAMPAIGN_RUN_TRIGGER = "CREATE TRIGGER fake_reservation AFTER INSERT ON attempts BEGIN\n                    SELECT CASE WHEN EXISTS(\n                        SELECT 1 FROM attempts WHERE id <> NEW.id AND NOT EXISTS (SELECT 1 FROM fake_comparison_requests p\n        WHERE p.held_id=attempts.id AND p.request_id=NEW.id AND p.run_id=fake_run_id()) AND NOT EXISTS (\n        SELECT 1 FROM fake_continuations c WHERE c.previous_id=attempts.id\n        AND c.retry_id=NEW.id AND c.run_id=fake_run_id()\n    ) AND state IN ('reserved','unknown')\n                    ) THEN RAISE(ABORT, 'FAKE_REQUEST_PENDING') END;\n                    INSERT INTO fake_run_attempts VALUES (NEW.id, fake_run_id());\n                    SELECT CASE WHEN (\n                        SELECT SUM(COALESCE(a.used, 0) +\n                            CASE WHEN a.state IN ('reserved','unknown') THEN a.reserved ELSE 0 END)\n                        FROM attempts a JOIN fake_run_attempts r ON r.attempt_id = a.id\n                        WHERE r.run_id = fake_run_id()\n                    ) > COALESCE((SELECT maximum FROM fake_flow_runs WHERE run_id=fake_run_id()), 3700000) THEN RAISE(ABORT, 'FAKE_RUN_TOKEN_LIMIT') END;\n                END;"


class _CampaignConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class CampaignRunBudget(TokenBudget):
    """One pinned run on an existing campaign; accepted storage layouts share admission."""
    def __init__(self, path, run_id, *, maximum_tokens, aggregate_tokens, model_bounds,
                 authority_sha256, preserved_holds, guard_sha256):
        self.path = Path(path).absolute()
        if (not self.path.is_file() or self.path.is_symlink() or self.path.resolve() != self.path
                or not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', run_id)
                or type(maximum_tokens) is not int or type(aggregate_tokens) is not int
                or not 0 < maximum_tokens <= aggregate_tokens
                or not re.fullmatch('[0-9a-f]{64}', authority_sha256 or '')
                or not re.fullmatch('[0-9a-f]{64}', guard_sha256 or '')
                or not isinstance(preserved_holds, list) or any(not isinstance(r, list) or len(r) != 8 for r in preserved_holds)
                or not model_bounds or any(not isinstance(k,str) or type(v) is not int or v < 1 for k,v in model_bounds.items())):
            raise ValueError('REPORT_CAMPAIGN_AUTHORITY_REQUIRED')
        self.run_id, self.run_limit, self.maximum = run_id, maximum_tokens, aggregate_tokens
        self.pin, self.holds, self.guard_pin = authority_sha256, sorted(preserved_holds), guard_sha256
        self.model_bounds = dict(model_bounds)
        with self.connect(read_only=True) as db:
            row = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
            if row is None or row[0] != aggregate_tokens:
                raise ValueError('REPORT_CAMPAIGN_AUTHORIZATION_MISMATCH')
            self.authorization = tuple(row)
            registered = json.loads(row[1])
            if any(k in registered and registered[k] != v for k,v in self.model_bounds.items()):
                raise ValueError('REPORT_MODEL_BOUND_MISMATCH')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            legacy = {'fake_flow_runs','fake_run_attempts','fake_comparison_requests'}
            native = {'report_runs','report_run_attempts'}
            triggers = list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='attempts' ORDER BY name"))
            normalize = lambda sql:' '.join(sql.rstrip(';').split())
            if legacy <= tables and not tables & native and len(triggers)==1 and triggers[0][0]=='fake_reservation' and normalize(triggers[0][1])==normalize(_LEGACY_CAMPAIGN_RUN_TRIGGER):
                self.run_table, self.attempt_table, self.legacy_layout = 'fake_flow_runs', 'fake_run_attempts', True
                if len(self.holds) != 1:
                    raise ValueError('REPORT_PRESERVED_HOLD_SET_MISMATCH')
            elif not tables & legacy and (not tables & native or native <= tables) and not triggers:
                self.run_table, self.attempt_table, self.legacy_layout = 'report_runs', 'report_run_attempts', False
            else:
                raise ValueError('REPORT_CAMPAIGN_SCHEMA_UNRECOGNIZED')
            self.guard_sql = triggers[0][1] if triggers else ''
            if hashlib.sha256(self.guard_sql.encode()).hexdigest() != guard_sha256:
                raise ValueError('REPORT_CAMPAIGN_GUARD_PIN_MISMATCH')
            self._check(db)
            if self.run_table in tables:
                self._run_binding(db)

    def connect(self, *, read_only=False):
        db = sqlite3.connect(self.path.as_uri() + ('?mode=ro' if read_only else '?mode=rw'),
                             uri=True, timeout=30, factory=_CampaignConnection)
        if read_only:
            db.execute('PRAGMA query_only=ON')
        db.create_function('fake_run_id', 0, lambda:self.run_id)
        return db

    def _check(self, db):
        if tuple(db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone() or ()) != self.authorization:
            raise RequestBudgetExceeded('REPORT_CAMPAIGN_AUTHORIZATION_CHANGED')
        sql = list(db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='attempts' ORDER BY name"))
        if [r[0] for r in sql] != ([self.guard_sql] if self.guard_sql else []):
            raise RequestBudgetExceeded('REPORT_CAMPAIGN_GUARD_CHANGED')
        pending = [list(r) for r in db.execute("SELECT * FROM attempts WHERE state IN ('reserved','unknown') ORDER BY id")]
        if pending != self.holds:
            raise RequestBudgetExceeded('REPORT_UNRESOLVED_ATTEMPT')

    def _run_binding(self, db):
        prior = db.execute(f'SELECT maximum,authority FROM {self.run_table} WHERE run_id=?', (self.run_id,)).fetchone()
        if prior is not None and tuple(prior) != (self.run_limit,self.pin):
            raise RequestBudgetExceeded('REPORT_RUN_AUTHORITY_CHANGED')

    def _costs(self, db):
        return db.execute(f"""SELECT COALESCE(SUM(a.used),0), COALESCE(SUM(CASE WHEN a.state IN ('reserved','unknown') THEN a.reserved ELSE 0 END),0)
            FROM attempts a JOIN {self.attempt_table} r ON r.attempt_id=a.id WHERE r.run_id=?""",(self.run_id,)).fetchone()

    def _reservation_id(self, db, model, bound):
        self._check(db)
        if not self.legacy_layout:
            db.execute('CREATE TABLE IF NOT EXISTS report_runs (run_id TEXT PRIMARY KEY, maximum INTEGER NOT NULL, authority TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS report_run_attempts (attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL)')
        self._run_binding(db)
        used,held = self._costs(db)
        if used + held + bound > self.run_limit:
            raise RequestBudgetExceeded('REPORT_RUN_TOKEN_LIMIT')
        db.execute(f'INSERT OR IGNORE INTO {self.run_table} VALUES (?,?,?)',(self.run_id,self.run_limit,self.pin))
        identity = super()._reservation_id(db, model, bound)
        if self.legacy_layout:
            db.execute('INSERT INTO fake_comparison_requests VALUES (?,?,?)',(identity,self.holds[0][0],self.run_id))
        else:
            db.execute('INSERT INTO report_run_attempts VALUES (?,?)',(identity,self.run_id))
        return identity

    def _reserve(self, model, bound):
        if getattr(self,'admission_refusal',None):
            raise RequestBudgetExceeded(self.admission_refusal)
        try:
            return super()._reserve(model,bound)
        except RequestBudgetExceeded as exc:
            self.admission_refusal=str(exc)
            raise

    def snapshot(self):
        with self.connect(read_only=True) as db:
            return self._snapshot(db)

    def run_snapshot(self):
        with self.connect(read_only=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(self.run_table,)).fetchone()
            used,held = self._costs(db) if exists else (0,0)
        return {'maximum_tokens':self.run_limit,'settled':used,'held':held}


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
    bound = _request_bound.get()
    body = json.loads(request.content) if bound is not None else None
    _validate_bounded_request(request, body)
    budget=_active.get()
    if bound is not None and budget is None:
        raise RequestBudgetExceeded('AUTHORITATIVE_TOKEN_BUDGET_REQUIRED')
    effective = _effective_bound(budget, body.get('model')) if bound is not None else None
    admit_recovery_request(request)
    if budget is None:return None
    if body is None:body=json.loads(request.content)
    if body.get('stream'):raise RequestBudgetExceeded('STREAM_USAGE_BUDGET_NOT_SUPPORTED')
    if body.get('n',1)!=1:raise RequestBudgetExceeded('MODEL_TOKEN_BOUND_NOT_VERIFIED')
    identity=(budget._reserve(body.get('model'), effective) if bound is not None
              else budget.reserve(body.get('model')))
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
