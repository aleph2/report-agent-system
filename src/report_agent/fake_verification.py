"""Trusted offline preparation and explicitly invoked two-slope fake assessment launch.

Run identify, pin its values in the external authority record, then use prepare,
check and (only with launch authority) run. Supply the trusted authority digest
separately. init-grant is a one-time action for the entire verification campaign.
Each preparation owns GRANT/runs/RUN_ID/case, prepared.json, and result.json.
"""
import argparse
import asyncio
from contextlib import closing
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from .assessment_completion import claim_launch, _save
from .fake_verification_budget import CAMPAIGN_LIMIT, RUN_LIMIT, FakeVerificationBudget, fake_verification_budget
from .store import digest
from .token_budget import current_model_token_bound, request_token_bound
from .writer_probe import verified_request_bound

WORKFLOW = 'mini-assessment-writer-v1'
MODEL = 'glm-5.3'
BOUND = 1_179_648
_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = 'tests/fake_data/mini_commission/inputs'
INPUTS = _REPO / _FIXTURE
_NAMES = {'00_scope.md','01_initial.pdf','02_revision.pdf','03_requirements.pdf',
          '04_design.pdf','05_survey.pdf','06_drawing.pdf','07_region.pdf','08_template.docx'}
_active = ContextVar('operator_verified_fake_run', default=None)


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _fixture():
    if INPUTS.is_symlink() or {p.name for p in INPUTS.iterdir()} != _NAMES:
        raise ValueError('FAKE_FIXTURE_INPUT_SET')
    files = {}
    for name in sorted(_NAMES):
        path = INPUTS / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('FAKE_FIXTURE_INPUT_SET')
        files[name] = _sha(path)
    return files


def _candidate_commit():
    def git(*args):
        return subprocess.check_output(['git', '-C', str(_REPO), *args], text=True)
    paths = ['src', _FIXTURE, 'pyproject.toml']
    if git('status','--porcelain','--untracked-files=all','--',*paths):
        raise ValueError('FAKE_CANDIDATE_MUST_BE_COMMITTED')
    if set(git('ls-files',_FIXTURE).splitlines()) != {_FIXTURE+'/'+name for name in _NAMES}:
        raise ValueError('FAKE_FIXTURE_MUST_BE_TRACKED')
    return git('rev-parse','HEAD').strip()


def identify():
    return {'candidate_commit': _candidate_commit(), 'fixture_manifest_sha256': digest(_fixture())}


def preflight(approval_file, approval_sha256):
    path = Path(approval_file)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != approval_sha256:
        raise ValueError('FAKE_AUTHORITY_PIN_MISMATCH')
    authority = json.loads(raw)
    expected = {**identify(), 'workflow': WORKFLOW, 'per_run_tokens': RUN_LIMIT, 'aggregate_tokens': CAMPAIGN_LIMIT}
    if (not isinstance(authority,dict) or any(authority.get(k) != v for k,v in expected.items())
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', str(authority.get('run_id','')))
            or not isinstance(authority.get('run_id'),str)
            or not isinstance(authority.get('owner_authority_ref'),str) or not authority['owner_authority_ref'].strip()
            or not isinstance(authority.get('request_bound_proof'),dict)):
        raise ValueError('FAKE_AUTHORITY_SCOPE_MISMATCH')
    grant = Path(authority['grant_dir'])
    if (not grant.is_absolute() or grant.resolve() != grant or grant.is_relative_to(_REPO)
            or path.resolve().is_relative_to(grant / 'runs')):
        raise ValueError('FAKE_SEPARATE_GRANT_REQUIRED')
    run = grant/'runs'/authority['run_id']
    if run.resolve() != run:
        raise ValueError('FAKE_RUN_PATH_INVALID')
    return authority


def _seal(case):
    if case.resolve() != case or not case.is_dir():
        raise ValueError('FAKE_FRESH_CASE_REQUIRED')
    # Prepared business DB and all content-addressed blobs. A checkpoint or other
    # case file appearing before launch also changes the manifest.
    files = {}
    for p in sorted(case.rglob('*')):
        if p.is_symlink():
            raise ValueError('FAKE_CASE_SYMLINK')
        if p.is_file() and not (p.name=='state.db-shm' or (p.name=='state.db-wal' and p.stat().st_size==0)):
            files[str(p.relative_to(case))] = _sha(p)
    if 'state.db' not in files:
        raise ValueError('FAKE_PREPARED_DATABASE_REQUIRED')
    return digest(files)


def prepare(approval_file, approval_sha256):
    from .mini_commission import prepare_mini_commission
    authority = preflight(approval_file, approval_sha256)
    run = Path(authority['grant_dir'])/'runs'/authority['run_id']
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    case = run/'case'
    result = prepare_mini_commission(INPUTS, case)
    if (result['fixture_sha256'] != _fixture() or result['object_ids'] != ['A','B']
            or Path(result['case_path']).resolve() != case or result['assessment_section_id']!='3'
            or result['method_source_name']!='system-method-high-slope.txt'
            or result['plan_ref']['type']!='CommissionPlan' or result['decision_ref']['type']!='CommissionDecision'):
        raise ValueError('FAKE_PREPARED_HANDOFF_MISMATCH')
    receipt = {**result, 'case_path': str(case), 'authority_sha256': approval_sha256, **identify(),
               'case_seal':_seal(case)}
    claim_launch(run/'prepared.json',receipt)
    return {**receipt,'prepared_sha256':_sha(run/'prepared.json')}


def check_prepared(approval_file, approval_sha256, prepared_sha256):
    authority = preflight(approval_file, approval_sha256)
    run = Path(authority['grant_dir'])/'runs'/authority['run_id']; case = run/'case'
    if (run/'result.json').exists():
        raise FileExistsError('FAKE_ALREADY_CLAIMED')
    raw = (run/'prepared.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != prepared_sha256:
        raise ValueError('FAKE_PREPARED_RECEIPT_PIN_MISMATCH')
    receipt = json.loads(raw)
    if (receipt['authority_sha256']!=approval_sha256 or receipt['fixture_sha256']!=_fixture()
            or receipt['case_path']!=str(case) or receipt['candidate_commit']!=authority['candidate_commit']
            or receipt['fixture_manifest_sha256']!=authority['fixture_manifest_sha256']
            or receipt['case_seal']!=_seal(case)):
        raise ValueError('FAKE_PREPARED_CASE_CHANGED')
    with closing(sqlite3.connect((case/'state.db').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute("SELECT 1 FROM content_versions WHERE type IN ('DelegatedTask','Assessment') LIMIT 1").fetchone():
            raise ValueError('FAKE_FRESH_CASE_REQUIRED')
        raw=db.execute("SELECT key,value FROM state WHERE key IN ('commission_plan','commission_confirmation')").fetchall()
        pins={k:json.loads(v) for k,v in raw}
        if pins!={'commission_plan':receipt['plan_ref'],'commission_confirmation':receipt['decision_ref']}:
            raise ValueError('FAKE_CONFIRMED_PLAN_CHANGED')
    return receipt


@dataclass(frozen=True)
class VerifiedFakeRun:
    run_id: str
    case_root: Path
    candidate_commit: str
    fixture_manifest_sha256: str
    plan_ref: dict
    assessment_section_id: str
    object_ids: tuple
    budget: FakeVerificationBudget


def assert_active_fake_run(verified_run, workspace):
    from .token_budget import _active as active_budget
    if (verified_run is not _active.get() or not isinstance(verified_run,VerifiedFakeRun)
            or verified_run.case_root!=workspace.store.root.resolve() or active_budget.get() is not verified_run.budget
            or current_model_token_bound(MODEL)!=BOUND):
        raise ValueError('VERIFIED_FAKE_RUN_REQUIRED')


async def launch(approval_file, approval_sha256, prepared_sha256, env_file):
    from .model_config import load_mixed_services,role_service,bind_role_services
    from .deep_models import configured_model, sdk_retry_count, connection_retry_count
    from .assessment_completion import require_writer_model
    from .model_recovery import load_recovery_policy
    from .store import Store
    from .workspace import Workspace
    from .writer_indicator_steps import run_mini_assessment

    authority=preflight(approval_file,approval_sha256)
    receipt=check_prepared(approval_file,approval_sha256,prepared_sha256)
    case=Path(receipt['case_path'])
    env_file=Path(env_file).resolve()
    if env_file.is_relative_to(case.parent) or env_file.is_relative_to(_REPO):
        raise ValueError('FAKE_EXTERNAL_SERVICE_CONFIG_REQUIRED')
    proof=authority['request_bound_proof']
    if _sha(env_file)!=proof.get('env_sha256'):
        raise ValueError('FAKE_SERVICE_CONFIG_PIN_MISMATCH')
    load_mixed_services(env_file)
    name,url,_=role_service('writer')
    bound=verified_request_bound(proof,env_file,name,url)
    if bound.total!=BOUND or sdk_retry_count()!=0 or connection_retry_count()!=2:
        raise ValueError('FAKE_SERVICE_POLICY_REQUIRED')
    with fake_verification_budget(authority['grant_dir'],authority['run_id']) as budget, request_token_bound(bound):
        account=budget.snapshot()
        if (budget.model_bounds!={MODEL:BOUND} or budget.run_snapshot()['settled'] or account['reserved_or_unknown_upper_bounds']
                or account['remaining_for_new_reservations']<BOUND or account['attempt_states'].get('bound_violation')):
            raise ValueError('FAKE_FRESH_RUN_BUDGET_REQUIRED')
        binding=VerifiedFakeRun(authority['run_id'],case,authority['candidate_commit'],authority['fixture_manifest_sha256'],
                                receipt['plan_ref'],receipt['assessment_section_id'],tuple(receipt['object_ids']),budget)
        path=case.parent/'result.json'
        result={'status':'claimed','run_id':binding.run_id,'scope':WORKFLOW,'started_at_utc':_utc(),
                'candidate_commit':binding.candidate_commit,'authority_sha256':approval_sha256,'case_seal':receipt['case_seal'],'prepared_sha256':prepared_sha256,
                'plan_ref':receipt['plan_ref'],'decision_ref':receipt['decision_ref'],'fixture_manifest_sha256':binding.fixture_manifest_sha256}
        claim_launch(path,result)
        t=_active.set(binding); model=None
        try:
            ws=Workspace(Store(case))
            if load_recovery_policy(ws.store):
                raise ValueError('FAKE_RECOVERY_DISABLED_REQUIRED')
            bind_role_services(ws.store)
            model=configured_model(ws.store,'writer')
            require_writer_model(model,MODEL)
            if (getattr(model,'profile',None) or {}).get('image_inputs') is not False:
                raise ValueError('FAKE_TEXT_ONLY_WRITER_REQUIRED')
            result.update(await run_mini_assessment(ws,model,verified_run=binding))
        except BaseException as error:
            result.update(status='interrupted',error_type=type(error).__name__)
            if re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}',str(error)):
                result['stop_code']=str(error)
            raise
        finally:
            _active.reset(t)
            try:
                if model is not None:
                    try: await model.root_async_client.close()
                    finally: model.root_client.close()
            finally:
                result.update(finished_at_utc=_utc(),budget=budget.run_snapshot(),campaign_budget=budget.snapshot())
                _save(path,result)
    return result


def _utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['identify','init-grant','prepare','check','run'])
    parser.add_argument('--authority',type=Path)
    parser.add_argument('--authority-sha256')
    parser.add_argument('--env',type=Path)
    parser.add_argument('--prepared-sha256')
    args=parser.parse_args()
    if args.action=='identify':
        result=identify()
    else:
        if not args.authority or not args.authority_sha256:parser.error('authority and separately pinned SHA-256 required')
        auth=preflight(args.authority,args.authority_sha256)
        if args.action=='init-grant':
            FakeVerificationBudget.initialize(Path(auth['grant_dir']),{MODEL:BOUND})
            result={'status':'initialized','maximum_tokens':CAMPAIGN_LIMIT}
        elif args.action=='run':
            if not args.env or not args.prepared_sha256:parser.error('external service config and pinned preparation receipt required')
            result=asyncio.run(launch(args.authority,args.authority_sha256,args.prepared_sha256,args.env))
        elif args.action=='check':
            if not args.prepared_sha256:parser.error('pinned preparation receipt required')
            result=check_prepared(args.authority,args.authority_sha256,args.prepared_sha256)
        else:
            result=prepare(args.authority,args.authority_sha256)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(args.action=='run' and result.get('status') not in {'closed_with_gaps','assessments_saved'})


if __name__=='__main__':
    # The Writer imports this module's binding class and ContextVar by package name.
    from report_agent.fake_verification import main as package_main
    raise SystemExit(package_main())
