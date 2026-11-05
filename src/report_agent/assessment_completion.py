"""Trusted one-shot Writer assessment recovery; never resumes a stopped report host."""
import argparse
import asyncio
from contextlib import AsyncExitStack, closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from langchain.agents.middleware import AgentMiddleware, hook_config

from .planning_budget import budget_scope_cost
from .request_budget import RequestBudgetExceeded
from .store import digest

LIMIT = 10_000_000
GRANT_LIMIT = 200_000_000
READ_TOOLS = frozenset({'project_status', 'read_source_page', 'search_sources', 'inspect_source_page',
    'read_result', 'content_status', 'read_object_index', 'read_context', 'read_content_index',
    'read_content_selection', 'observe_evidence', 'read_feedback', 'get_operation_receipt',
    'read_commission_plan', 'read_task_assignment', 'read_decision_state'})


def read_finance(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('EXISTING_TOKEN_LEDGER_REQUIRED')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        auth = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
        rows = db.execute('SELECT id,model,reserved,used,state,response_id,reason,at FROM attempts ORDER BY id').fetchall()
        db.rollback()
    if auth is None:
        raise ValueError('TOKEN_AUTHORIZATION_REQUIRED')
    return {'auth': list(auth), 'rows': [list(row) for row in rows]}


class CompletionBudget:
    def __init__(self, finance, baseline, grant_baseline, bounds, *, writer_model):
        self.finance, self.baseline = finance, deepcopy(baseline)
        self.grant_baseline, self.bounds = deepcopy(grant_baseline), dict(bounds)
        if writer_model not in self.bounds:
            raise ValueError('ASSESSMENT_COMPLETION_WRITER_BOUND_REQUIRED')
        self.writer_model = writer_model

    def check(self):
        now = self.finance()
        used, held, _ = budget_scope_cost(self.baseline, now)
        grant_used, grant_held, _ = budget_scope_cost(self.grant_baseline, now)
        if used + held > LIMIT:
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_TOKEN_LIMIT')
        if grant_used + grant_held > GRANT_LIMIT:
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_GRANT_LIMIT')
        old = {row[0] for row in self.baseline['rows']}
        added = [row for row in now['rows'] if row[0] not in old]
        if any(row[1] != self.writer_model for row in added):
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_WRITER_MODEL_ONLY')
        pending = [row for row in added if row[4] in ('reserved', 'unknown')]
        # Admission runs after reserve: only the current serial request may be held.
        if len(pending) > 1 or any(row[4] == 'unknown' for row in pending):
            raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_UNRESOLVED_ATTEMPT')
        return used, held

    def observation(self):
        used, held, _ = budget_scope_cost(self.baseline, self.finance())
        return {'scope_id': 'assessment-completion', 'maximum_tokens': LIMIT, 'recorded_tokens': used,
            'reserved_or_unknown_upper_bounds': held, 'remaining_for_new_reservations': max(0, LIMIT-used-held),
            'model_reservation_bounds': self.bounds, 'includes_original_phases': True}


def claim_launch(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def _save(path, value):
    temporary = Path(path).with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_decision_pin(decision, approved):
    if decision['ref'] != approved['ref'] or decision['payload_digest'] != approved['payload_digest']:
        raise ValueError('ASSESSMENT_COMPLETION_DECISION_CHANGED')


def require_writer_model(model, expected):
    if (model.model_name != expected or any(getattr(client, 'max_retries', None) != 0
            for client in (model, model.root_client, model.root_async_client))):
        raise ValueError('ASSESSMENT_COMPLETION_WRITER_MODEL_OR_RETRIES_CHANGED')


def selected_tools(tools):
    return [tool for tool in tools if (getattr(tool, 'name', None) or getattr(tool, '__name__', None))
            in READ_TOOLS | {'calculate_assessment'}]


def saved_assessments(contents, plan_ref, object_ids, owner_id):
    result = {}
    for object_id in object_ids:
        ref = contents.store.get('g6_assessment:' + digest([plan_ref, object_id]))
        if ref is None:
            continue
        record = contents.read(ref)
        receipt = contents.store.get('assessment_receipt:' + digest(ref))
        if (ref.get('type') != 'Assessment' or record['payload'].get('commission_plan_ref') != plan_ref
                or record['payload'].get('object_id') != object_id or record['owner_id'] != owner_id
                or not receipt or receipt.get('assessment_ref') != ref):
            raise ValueError('ASSESSMENT_COMPLETION_SELECTION_INVALID')
        result[object_id] = ref
    return result


class AssessmentCompletionStop(AgentMiddleware):
    def __init__(self, complete):
        self.complete = complete

    @hook_config(can_jump_to=['end'])
    async def abefore_model(self, state, runtime):
        if self.complete():
            return {'jump_to': 'end'}


def _preflight(case, evidence, env, grant_file):
    authority, working, paths = [_load(evidence / name) for name in
        ('owner-approval.json', 'working-copy.json', 'financial-authority-paths.json')]
    if authority.get('hard_cap_tokens') != LIMIT or not all(authority.get(k) for k in ('turn_id', 'message_id')):
        raise ValueError('ASSESSMENT_COMPLETION_OWNER_AUTHORITY_REQUIRED')
    if case != Path(working['working_case']).resolve() or case == Path(working['source']).resolve():
        raise ValueError('ASSESSMENT_COMPLETION_WORKING_COPY_REQUIRED')
    if _sha(Path(working['source']) / 'state.db') != working['source_db_sha256']:
        raise ValueError('ASSESSMENT_COMPLETION_SOURCE_CHANGED')
    run = Path(paths['g5_prepared']).resolve().parent
    if run.name != 'g5-candidate-01':
        raise ValueError('ASSESSMENT_COMPLETION_G5_ONLY')
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().decode(errors='replace').split('\0')
        except (FileNotFoundError, PermissionError):
            continue
        if any(arg == str(run) or arg.startswith(str(run) + '/') for arg in argv):
            raise ValueError('ASSESSMENT_COMPLETION_G5_MUST_BE_STOPPED')
    deployment, prepared, config = [_load(run / name) for name in
        ('deployment.json', 'prepared.json', 'source/config/current.json')]
    if (env != (Path(deployment['repository']) / '.env').resolve()
            or grant_file != Path(deployment['budget_authority']).resolve()
            or _sha(grant_file) != deployment['budget_authority_sha256']):
        raise ValueError('ASSESSMENT_COMPLETION_DEPLOYMENT_AUTHORITY_MISMATCH')
    grant = _load(grant_file)['grant_scope']
    compact = json.dumps(grant['baseline'], sort_keys=True, separators=(',', ':')).encode()
    if grant['maximum_tokens'] != GRANT_LIMIT or hashlib.sha256(compact).hexdigest() != grant['baseline_sha256']:
        raise ValueError('ASSESSMENT_COMPLETION_GRANT_BASELINE_INVALID')
    from .model_config import load_mixed_services, role_service
    load_mixed_services(env)
    os.environ.update(REPORT_SDK_RETRIES='0', REPORT_CONNECT_RETRIES='0', REPORT_REASONING_EFFORT=config['reasoning_effort'])
    name, url, key = role_service('writer')
    if (name != config['models']['writer'] or not key or urlsplit(url).scheme != 'https'
            or hashlib.sha256(url.rstrip('/').encode()).hexdigest() != prepared['endpoint_pins']['writer']):
        raise ValueError('ASSESSMENT_COMPLETION_WRITER_PIN_MISMATCH')
    from .blob_store import verify_case_blobs
    blobs = verify_case_blobs(case)
    ledger = Path(deployment['ledger']).resolve()
    if ledger != Path(paths['account_ledger']).resolve():
        raise ValueError('ASSESSMENT_COMPLETION_LEDGER_MISMATCH')
    now = read_finance(ledger)
    account = _load(grant_file)
    if now['auth'][0] != account['maximum_tokens'] or json.loads(now['auth'][1]) != account['model_bounds']:
        raise ValueError('ASSESSMENT_COMPLETION_ACCOUNT_CHANGED')
    return authority, working, grant, ledger, now, blobs, name, hashlib.sha256(url.rstrip('/').encode()).hexdigest()


async def _run_completion_locked(case, evidence, env, grant_file):
    case, evidence, env, grant_file = [Path(p).resolve() for p in (case, evidence, env, grant_file)]
    launch_path = evidence / 'writer-launch.json'
    if launch_path.exists():
        raise FileExistsError('ASSESSMENT_COMPLETION_ALREADY_LAUNCHED_INSPECT_ORIGINAL_OUTCOME')
    authority, working, grant, ledger, now, blobs, model_name, endpoint_pin = _preflight(case, evidence, env, grant_file)
    from .store import Store
    from .workspace import Workspace
    from .content_store import ContentStore
    from .commission_plan import _confirmed
    store = Store(case)
    workspace, contents = Workspace(store), ContentStore(store)
    approved = _load(evidence / 'approved-plan.json')
    approved_decision = _load(evidence / 'approved-decision.json')
    with store.connect() as db:
        plan, decision = _confirmed(contents, db)
    if plan['ref'] != approved['ref'] or plan['payload_digest'] != approved['payload_digest']:
        raise ValueError('ASSESSMENT_COMPLETION_PLAN_CHANGED')
    require_decision_pin(decision, approved_decision)
    from .commission_plan import outside_boundary
    reduced = {row['object_id'] for row in decision['payload']['reductions']}
    ids = [obj['object_id'] for obj in plan['payload']['objects'] if not outside_boundary(plan['payload'], obj) and obj['object_id'] not in reduced]
    suggestions = _load(evidence / 'assessment-suggestions.json')
    if len(ids) != 5 or len(suggestions['rows']) != 55 or {row['object_id'] for row in suggestions['rows']} != set(ids):
        raise ValueError('ASSESSMENT_COMPLETION_FIVE_OBJECTS_REQUIRED')
    binding = {'authority_sha256': _sha(evidence/'owner-approval.json'), 'case': str(case), 'plan_ref': plan['ref'],
        'decision_ref': decision['ref'], 'approved_decision_sha256': _sha(evidence/'approved-decision.json'),
        'suggestions_sha256': _sha(evidence/'assessment-suggestions.json'),
        'grant_sha256': _sha(grant_file), 'source_db_sha256': working['source_db_sha256'],
        'environment_sha256': _sha(env),
        'g5_prepared_sha256': _sha(Path(_load(evidence/'financial-authority-paths.json')['g5_prepared'])),
        'writer_model': model_name, 'writer_endpoint_sha256': endpoint_pin, 'code_sha256': _sha(Path(__file__))}
    baseline_path = evidence / 'completion-budget-baseline.json'
    if baseline_path.exists():
        saved = _load(baseline_path)
        if saved['binding'] != binding or saved['baseline'] != now:
            raise ValueError('ASSESSMENT_COMPLETION_BASELINE_NOT_FRESH')
    else:
        claim_launch(baseline_path, {'binding': binding, 'baseline': now})
    guard = CompletionBudget(lambda: read_finance(ledger), now, grant['baseline'], json.loads(now['auth'][1]), writer_model=model_name)
    guard.check()
    launch = {'at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'binding': binding,
              'maximum_tokens': LIMIT, 'source_blobs': blobs, 'assessment_refs': {},
              'pid': os.getpid(), 'uid': os.getuid(),
              'process_start_ticks': Path('/proc/self/stat').read_text().rpartition(')')[2].split()[19]}
    claim_launch(launch_path, launch)
    metrics_path = case / 'runtime-metrics.jsonl'
    metric_offset = metrics_path.stat().st_size if metrics_path.exists() else 0
    try:
        store.set('manifest', {**store.manifest, 'assembly_contract': 'system-assembler-v1'})
        from .content_tasks import delegated_task
        goal = ('The owner has explicitly approved this bounded assessment-completion extension, hard cap10M tokens. '
            'This does not restart G5, change its approved plan or grant engineering sign-off. '
            'Complete ONLY the five canonical chapter4 assessments under the approved plan. The supplied55 rows are '
            'UNVERIFIED suggestions. Confirm or correct every grade,value,rank and explanation using the approved method '
            'and actual source evidence. Supply rank_reason, basis_kind, rationale, exact source refs and source pages '
            'for every value; assumptions need defensible plausible_grades and a question. Table-wide citations are not '
            'automatic per-indicator evidence. Preserve design-over-survey priority, the four owner exclusions, HP06 '
            'included with owner-provided14m, approved11indicators and A.3-1 n=11. A historical EXCLUDED suffix does not '
            'exclude HP06. Do not author prose/tables, alter plans/decisions/scope or export. Use calculate_assessment; '
            'the system computes arithmetic,tables,levels,sensitivity and assumption comments. Finish when allfive save. '
            'Engineering acceptance remains human. Report missing evidence honestly; never invent source pages.')
        call = {'name': 'task', 'id': 'owner-approved-assessment-completion', 'args': {
            'subagent_type': 'writer', 'section_ids': ['4'], 'description': goal}}
        from .token_budget import TokenBudget, token_budget
        from .request_budget import request_reservation_observer
        budget = TokenBudget(ledger, now['auth'][0], guard.bounds)
        from .deep_models import configured_model, model_client_ownership
        from langchain_core.messages import HumanMessage
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from .deep_runtime import business_tools
        with delegated_task(workspace, 'coordinator', call) as (native_call, actor):
            def saved():
                return saved_assessments(contents, plan['ref'], ids, actor.id)
            async with AsyncExitStack() as resources:
                clients = set()
                def own(client, asynchronous):
                    if id(client) not in clients:
                        clients.add(id(client))
                        resources.push_async_callback(client.aclose) if asynchronous else resources.callback(client.close)
                with model_client_ownership(own):
                    model = configured_model(store, 'writer')
                    require_writer_model(model, model_name)
                tools = selected_tools(business_tools(workspace, 'writer', None, None))
                launch.update(writer_actor=actor.__dict__, tools=[getattr(t,'name',None) or t.__name__ for t in tools])
                _save(launch_path, launch)
                async with AsyncSqliteSaver.from_conn_string(str(case/'assessment-completion-checkpoints.db')) as saver:
                    agent = build_writer_agent(workspace, model, tools, lambda: len(saved()) == 5, saver)
                    with token_budget(budget), request_reservation_observer(guard.check, observation=guard.observation):
                        await agent.ainvoke({'messages': [HumanMessage(content=native_call['args']['description'] +
                            '\nUnverified system prefill:\n' + json.dumps(suggestions, ensure_ascii=False))]},
                            {'configurable': {'thread_id': 'bounded-assessment-completion'}, 'recursion_limit': 10000})
                launch['assessment_refs'] = saved()
        launch['status'] = 'completed' if len(launch['assessment_refs']) == 5 else 'incomplete'
        launch['missing_objects'] = sorted(set(ids)-launch['assessment_refs'].keys())
    except BaseException as error:
        launch.update(status='blocked', error_type=type(error).__name__)
        raise
    finally:
        launch['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            launch['budget'] = guard.observation()
        except Exception as error:
            launch['budget'] = {'status': 'unavailable', 'error_type': type(error).__name__}
        _save(launch_path, launch)
        if metrics_path.exists():
            with metrics_path.open('rb') as stream:
                stream.seek(metric_offset)
                (evidence/'writer-metrics.jsonl').write_bytes(stream.read())
    return launch


def build_writer_agent(workspace, model, tools, complete, checkpointer):
    from deepagents import create_deep_agent, register_harness_profile, HarnessProfile, GeneralPurposeSubagentProfile
    from deepagents.backends import StateBackend
    from .deep_runtime import BusinessBoundary
    from .hierarchical_tools import role_prompt
    from .prompt_provenance import AgentPromptBoundary
    from .task_context import enabled as context_enabled, TaskContext, bind_projection
    from .prompt_sources import record_runtime_version, review_interface_profile, report_expression_profile, report_prompt_profile
    from .handoff_release import release
    store = workspace.store
    bind_projection(workspace, manifest=store.manifest)
    options = {'interface_profile': review_interface_profile(store), 'expression_profile': report_expression_profile(store),
               'prompt_profile': report_prompt_profile(store)}
    register_harness_profile('openai', HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))
    middleware = [AssessmentCompletionStop(complete),
        *([TaskContext(workspace, 'writer')] if context_enabled(workspace) else []),
        BusinessBoundary(workspace, 'writer'), AgentPromptBoundary(workspace, 'writer', **options)]
    agent = create_deep_agent(model=model, tools=tools, subagents=[], backend=StateBackend(),
        system_prompt=role_prompt('writer', **options), middleware=middleware,
        checkpointer=checkpointer, name='assessment_completion_writer')
    metadata = {'report_runtime_version_ref': record_runtime_version(store)}
    if options['interface_profile'] == 'review-interfaces-v4':
        metadata['report_handoff_release'] = release(store.manifest)
    return agent.with_config(metadata=metadata)


async def run_completion(case, evidence, env, grant_file):
    import fcntl
    case, evidence = Path(case).resolve(), Path(evidence).resolve()
    working = _load(evidence / 'working-copy.json')
    if case != Path(working['working_case']).resolve() or case == Path(working['source']).resolve():
        raise ValueError('ASSESSMENT_COMPLETION_WORKING_COPY_REQUIRED')
    with (case / 'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return await _run_completion_locked(case, evidence, env, grant_file)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('case', 'evidence', 'env', 'grant-baseline'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(run_completion(args.case,args.evidence,args.env,args.grant_baseline))
    except BaseException as error:
        print(json.dumps({'status':'blocked','error_type':type(error).__name__}))
        return 1
    print(json.dumps({k:result.get(k) for k in ('status','assessment_refs','missing_objects','budget')},ensure_ascii=False))
    return 0 if result['status']=='completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
