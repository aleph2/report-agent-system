"""Pinned operator entry: planning checkpoint, then a separate approved-sheet draft run."""
import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from . import fake_verification as host, fake_planning_probe as planning
from .assessment_completion import claim_launch, _save
from .fake_verification_budget import FakeFlowBudget
from .request_budget import RequestBudgetExceeded
from .token_budget import token_budget, request_token_bound

WORKFLOW = 'fake03-approved-sheet-draft-v1'
_CRITERIA = host._REPO / 'tests/fake_data/mini_commission/writer-conventions.json'
_TEXT_ROLES = ('writer', 'reviewer', 'text_tool')


def identify():
    return {**planning.identify(), 'criteria_sha256': host._sha(_CRITERIA)}


def preflight(path, pin):
    data = json.loads(Path(path).read_bytes())
    if data.get('workflow') == planning.WORKFLOW:
        authority = planning.preflight(path, pin)
    else:
        cap = data.get('per_run_tokens')
        if type(cap) is not int or cap <= 0 or 'fresh_comparison' not in data:
            raise ValueError('FAKE_FULL_FLOW_AUTHORITY_REQUIRED')
        authority = host.preflight(path, pin, workflow=WORKFLOW, per_run_tokens=cap, comparison_count=1)
        if (authority.get('criteria_sha256') != host._sha(_CRITERIA)
                or set(authority.get('roles', {})) != {*_TEXT_ROLES, 'vision'}
                or any(authority['roles'][role] != authority.get('model') for role in _TEXT_ROLES)
                or authority['roles']['vision'] != authority.get('vision_model')
                or authority.get('vision_thinking') not in {'enabled', 'disabled'}
                or not isinstance(authority.get('vision_request_bound_proof'), dict)
                or not isinstance(authority.get('approved_input'), dict)
                or not isinstance(authority.get('issue_routes'), dict)):
            raise ValueError('FAKE_FULL_FLOW_SCOPE_MISMATCH')
    root = Path(authority['grant_dir']) / 'runs' / authority['run_id']
    if authority.get('case_path') != str(root / 'case'):
        raise ValueError('FAKE_FULL_FLOW_CASE_AUTHORITY_MISMATCH')
    if authority['workflow'] == planning.WORKFLOW and (not isinstance(authority.get('confirmers'), dict) or not authority['confirmers']):
        raise ValueError('FAKE_FULL_FLOW_CONFIRMERS_REQUIRED')
    tag = authority.get('candidate_tag')
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError('FAKE_FULL_FLOW_CANDIDATE_TAG_REQUIRED')
    commit = subprocess.check_output(['git', '-C', str(host._REPO), 'rev-parse', '--verify',
        'refs/tags/' + tag + '^{commit}'], text=True).strip()
    if commit != authority['candidate_commit']:
        raise ValueError('FAKE_FULL_FLOW_CANDIDATE_TAG_MISMATCH')
    return authority


def completion_inputs(workspace, authority):
    """Validate business authority before constructing or spending on any model."""
    from .commission_plan import _confirmed, verified_confirmer
    from .content_store import Actor, ContentStore
    from . import page_bindings
    from .writer_judgment_authority import rule_pin
    from .system_assembler import record_issue_routes
    cs = ContentStore(workspace.store)
    with workspace.store.connect() as db:
        plan, decision = _confirmed(cs, db)
    source = authority['approved_input']
    if plan['ref'] != source['plan_ref'] or decision['ref'] != source['decision_ref']:
        raise ValueError('FAKE_FULL_FLOW_APPROVED_INPUT_MISMATCH')
    if not decision['payload'].get('confirmer'):
        raise ValueError('FAKE_FULL_FLOW_ATTRIBUTED_CONFIRMATION_REQUIRED')
    verified_confirmer(source['case_path'], decision['payload']['confirmer'],
        source['planning_authority'], source['planning_authority_sha256'])
    criteria = json.loads(_CRITERIA.read_bytes())['criteria']
    rules = {r['id']: r for r in plan['payload']['method_pack']['indicators']}
    if not criteria or any(key not in rules or value.get('rule_digest') != rule_pin(rules[key])
                           for key, value in criteria.items()):
        raise ValueError('FAKE_FULL_FLOW_CRITERIA_METHOD_MISMATCH')
    for subject in page_bindings.eligible_subjects(cs, plan['ref'], decision['payload']):
        indicators = {r['claim']['page_binding']['indicator_id']
                      for r in page_bindings.confirmed(workspace.store, plan['ref'], subject)}
        if set(rules) - indicators:
            raise ValueError('FAKE_DRAFT_CONFIRMED_PAGE_SHEET_REQUIRED')
    record_issue_routes(cs, Actor('operator', 'operator', 'fake-draft-routing'),
        'fake-draft-routes', authority['issue_routes'],
        note='Trusted operator routing of the owner-approved planning conflicts; no change to judgments.')
    return criteria


def prepare(path, pin):
    from .probe_case import prepare_probe_case
    from .store import Store
    from .workspace import Workspace
    authority = preflight(path, pin)
    if authority['workflow'] == planning.WORKFLOW:
        return planning.prepare(path, pin)
    root = Path(authority['case_path']).parent
    root.mkdir(parents=True, exist_ok=False)
    source = authority['approved_input']
    original = Path(source['case_path'])
    if original.resolve() != original or host._seal(original) != source['case_seal']:
        raise ValueError('FAKE_FULL_FLOW_INPUT_CHANGED')
    imported = prepare_probe_case(original, root / 'case', expected_plan_ref=source['plan_ref'],
        expected_decision_ref=source['decision_ref'])
    if host._seal(original) != source['case_seal']:
        raise ValueError('FAKE_FULL_FLOW_INPUT_CHANGED')
    ws = Workspace(Store(root / 'case'))
    completion_inputs(ws, authority)
    receipt = {**identify(), 'authority_sha256': pin, 'case_path': str(root / 'case'),
        'import': imported, 'case_seal': host._seal(root / 'case')}
    claim_launch(root / 'prepared.json', receipt)
    return {**receipt, 'prepared_sha256': host._sha(root / 'prepared.json')}


def check_prepared(path, pin, prepared_pin):
    authority = preflight(path, pin)
    if authority['workflow'] == planning.WORKFLOW:
        return planning.check_prepared(path, pin, prepared_pin)
    root = Path(authority['case_path']).parent
    if (root / 'result.json').exists():
        raise FileExistsError('FAKE_FULL_FLOW_ALREADY_CLAIMED')
    receipt = json.loads((root / 'prepared.json').read_bytes())
    if (host._sha(root / 'prepared.json') != prepared_pin or receipt['authority_sha256'] != pin
            or any(receipt.get(k) != v for k, v in identify().items())
            or receipt['case_path'] != authority['case_path']
            or receipt['case_seal'] != host._seal(Path(authority['case_path']))):
        raise ValueError('FAKE_FULL_FLOW_PREPARED_CASE_CHANGED')
    return {**receipt, 'prepared_sha256': prepared_pin}


async def launch(path, pin, prepared_pin, env_file):
    from . import deep_models, model_config
    from .writer_probe import verified_request_bound
    from .store import Store
    from .workspace import Workspace
    from .hierarchical_tools import actor_for
    from .model_recovery import load_recovery_policy
    from .fake_draft_flow import complete
    from .tool_selection import tool_scope
    from .tool_trace import ToolTrace, capture_tools, summarize_trace
    authority = preflight(path, pin)
    if authority['workflow'] == planning.WORKFLOW:
        return await planning.launch(path, pin, prepared_pin, env_file)
    receipt = check_prepared(path, pin, prepared_pin)
    case = Path(receipt['case_path']);root = case.parent
    env_file = Path(env_file).resolve()
    if env_file.is_relative_to(root) or env_file.is_relative_to(host._REPO):
        raise ValueError('FAKE_EXTERNAL_SERVICE_CONFIG_REQUIRED')
    model_config.load_mixed_services(env_file)
    service = model_config.role_service('writer')
    vision = model_config.role_service('vision')
    if service[0] != authority['model'] or vision[0] != authority['vision_model']:
        raise ValueError('FAKE_FULL_FLOW_SERVICE_MISMATCH')
    bound = verified_request_bound(authority['request_bound_proof'], env_file, *service[:2])
    visual_bound = planning.verified_vision_bound(authority['vision_request_bound_proof'], env_file, *vision[:2])
    policies = (bound, visual_bound)
    for role in _TEXT_ROLES:
        for suffix, value in zip(('MODEL', 'BASE_URL', 'API_KEY'), service):
            os.environ['REPORT_' + role.upper() + '_' + suffix] = value
    os.environ['REPORT_VISION_THINKING'] = authority['vision_thinking']
    if deep_models.sdk_retry_count() != 0 or deep_models.connection_retry_count() != 2:
        raise ValueError('FAKE_SERVICE_POLICY_REQUIRED')
    ws = Workspace(Store(case))
    if load_recovery_policy(ws.store):
        raise ValueError('FAKE_RECOVERY_DISABLED_REQUIRED')
    criteria = completion_inputs(ws, authority)
    budget = FakeFlowBudget(authority['grant_dir'], authority['run_id'], authority['fresh_comparison'], pin,
        maximum_tokens=authority['per_run_tokens'], aggregate_tokens=authority['aggregate_tokens'],
        model_bounds={p.model: p.total for p in policies})
    budget.check_fresh()
    if budget.snapshot()['remaining_for_new_reservations'] < max(p.total for p in policies):
        raise RequestBudgetExceeded('AUTHORIZED_TOKEN_BUDGET_REACHED')
    model_config.bind_role_services(ws.store)
    result = dict(status='claimed', run_id=authority['run_id'], workflow=WORKFLOW,
        authority_sha256=pin, candidate_commit=authority['candidate_commit'], candidate_tag=authority['candidate_tag'],
        prepared_sha256=prepared_pin, roles=authority['roles'], automatic_continuation=False, formal_release=False,
        started_utc=datetime.now(timezone.utc).isoformat())
    claim_launch(root / 'result.json', result)
    trace = ToolTrace(ws, authority['run_id'], root / 'tool-trace.jsonl', actor_for('coordinator'))
    try:
        async with AsyncExitStack() as clients:
            seen = set()
            def own(client, asynchronous):
                if id(client) not in seen:
                    seen.add(id(client))
                    clients.push_async_callback(client.aclose) if asynchronous else clients.callback(client.close)
            def factory(role):
                if role not in _TEXT_ROLES:
                    raise RequestBudgetExceeded('FAKE_FULL_FLOW_ROLE_NOT_AUTHORIZED')
                model = deep_models.configured_model(ws.store, role)
                if model.model_name != authority['roles'][role]:
                    raise ValueError('FAKE_FULL_FLOW_EFFECTIVE_MODEL_MISMATCH')
                return model
            with (deep_models.model_client_ownership(own), token_budget(budget), request_token_bound(policies),
                  capture_tools(trace), tool_scope(set(authority['roles'].values()), authority['roles'],
                      excluded=planning.PROBE_UNAVAILABLE_TOOLS)):
                result['completion'] = await complete(ws, factory, authority['issue_routes'], criteria)
                exported = result['completion']['exports']
                result['export_sha256'] = {}
                for relative in (exported['file_ref'], exported['workbook']['file_ref']):
                    artifact = (case / relative).resolve()
                    if not artifact.is_relative_to(case):
                        raise ValueError('FAKE_FULL_FLOW_EXPORT_PATH_INVALID')
                    result['export_sha256'][relative] = host._sha(artifact)
                result['status'] = result['completion']['status']
    except BaseException as error:
        result.update(status='stopped', error_type=type(error).__name__, stop_code=str(error))
        raise
    finally:
        from .runtime_metrics import summarize
        result.update(runtime_metrics=summarize(case / 'runtime-metrics.jsonl'),
            finished_utc=datetime.now(timezone.utc).isoformat(), budget=budget.run_snapshot(),
            campaign_budget=budget.snapshot(), trace_summary=summarize_trace(root / 'tool-trace.jsonl'))
        if result['budget']['held']:
            result['status'] = 'unknown_outcome_held'
        if trace.last_admission_code:
            result['stop_code'] = trace.last_admission_code
        _save(root / 'result.json', result)
    return result


def confirm(path, pin, issue_id, decision, confirmer_id):
    from .commission_plan import reply, OwnerDecision
    from .store import Store
    from .workspace import Workspace
    authority = preflight(path, pin)
    if authority['workflow'] != planning.WORKFLOW or confirmer_id not in authority['confirmers']:
        raise ValueError('FAKE_FULL_FLOW_CONFIRMATION_AUTHORITY_REQUIRED')
    confirmer = {**authority['confirmers'][confirmer_id], 'id': confirmer_id, 'authority_sha256': pin}
    decision = OwnerDecision.model_validate({**decision, 'confirmer': confirmer}).model_dump()
    case = Path(authority['case_path'])
    if not (case / 'state.db').is_file():
        raise ValueError('FAKE_FULL_FLOW_EXISTING_CHECKPOINT_REQUIRED')
    return reply(Workspace(Store(case)), issue_id, decision, authority_path=path, authority_sha256=pin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['identify', 'prepare', 'check', 'run', 'confirm'])
    for option in ('authority', 'authority-sha256', 'prepared-sha256', 'env', 'issue-id', 'reply', 'confirmer-id'):
        parser.add_argument('--' + option)
    args = parser.parse_args()
    if args.action == 'identify':
        result = identify()
    else:
        if not args.authority or not args.authority_sha256:
            parser.error('external authority and separately pinned digest required')
        if args.action == 'prepare':result = prepare(args.authority, args.authority_sha256)
        elif args.action == 'check':result = check_prepared(args.authority, args.authority_sha256, args.prepared_sha256)
        elif args.action == 'confirm':
            if not args.issue_id or not args.reply or not args.confirmer_id:
                parser.error('issue, explicit decision file and authorized actual confirmer required')
            result = confirm(args.authority, args.authority_sha256, args.issue_id,
                json.loads(Path(args.reply).read_bytes()), args.confirmer_id)
        else:
            if not args.env or not args.prepared_sha256:
                parser.error('external services and prepared digest required')
            result = asyncio.run(launch(args.authority, args.authority_sha256, args.prepared_sha256, args.env))
            result = {key: result[key] for key in ('status', 'run_id', 'budget', 'campaign_budget')}
    print(json.dumps(result, ensure_ascii=False))
    return int(args.action == 'run' and result['status'] not in {'draft_exported', 'page_sheet_checkpoint'})


if __name__ == '__main__':raise SystemExit(main())
