"""Four bounded synthetic I/O probes; no generated tool call is executed.

Default is offline MockTransport. --live requires the existing authorized ledger
and provider file. No fallback, automatic semantic repair, or new report run.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

import httpx
from filelock import FileLock
from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, messages_to_dict
from report_agent.content_tasks import delegated_task
from report_agent.deep_models import configured_model
from report_agent.deep_runtime import run_report
from report_agent.model_config import load_mixed_services
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.workspace import Workspace
from test_bounded_deadline import close_model
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_text_work import tools, writer_call


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def code_hashes():
    paths = [Path(__file__), *sorted((ROOT / 'tests').glob('*.py')),
             *[p for p in (ROOT / 'src').rglob('*') if p.suffix in ('.py', '.md')]]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def ledger_rows(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return {'authorization': db.execute('SELECT * FROM authorization ORDER BY id').fetchall(),
                'attempts': {row[0]: row for row in db.execute('SELECT * FROM attempts ORDER BY id')}}


def phase_admission(baseline, current, maximum, model_bounds, attempts=4, *, max_attempts=12):
    """Conservative whole-wave admission; all HTTP still uses the parent ledger.

    The phase lock serializes these probes. A wave can spend at most its shared
    RequestBudget times the largest verified per-request bound, including retries.
    No old unknown reservation is released or counted as a fresh phase request.
    """
    baseline, current = (json.loads(json.dumps(value)) for value in (baseline, current))
    if (current['authorization'] != baseline['authorization'] or
            any(current['attempts'].get(k) != row for k, row in baseline['attempts'].items())):
        raise ValueError('PHASE_BASELINE_CHANGED')
    if any(row[4] == 'bound_violation' for row in current['attempts'].values()):
        raise ValueError('PHASE_BOUND_VIOLATION_REQUIRES_DIAGNOSIS')
    added = [row for key, row in current['attempts'].items() if key not in baseline['attempts']]
    used = sum(row[3] or 0 for row in added)
    held = sum(row[2] for row in added if row[4] in ('reserved', 'unknown'))
    # The transport can reserve tokens before rejecting HTTP admission locally.
    # Exclude only its confirmed known_not_sent state; unresolved rows still count.
    known_not_sent = sum(row[4] == 'known_not_sent' for row in added)
    admitted_or_unresolved = len(added) - known_not_sent
    if admitted_or_unresolved + attempts > max_attempts:
        raise ValueError('PHASE_HTTP_ATTEMPT_LIMIT')
    upper = attempts * max(model_bounds.values())
    if used + held + upper > maximum:
        raise ValueError('PHASE_TOKEN_BUDGET_REACHED')
    return {'maximum_tokens': maximum, 'recorded_tokens': used,
            'reserved_or_unknown_upper_bounds': held, 'http_attempt_rows': len(added),
            'ledger_row_count': len(added), 'known_not_sent_rows': known_not_sent,
            'admitted_or_unresolved_attempts': admitted_or_unresolved,
            'next_wave_worst_case_tokens': upper, 'remaining_tokens': maximum - used - held,
            'prior_attempt_rows_preserved': len(baseline['attempts'])}


def workspace(path, missing=False, source_text=None):
    store = Store(path)
    store.initialize({'goal': 'Describe synthetic class B, preserving uncertainty.',
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': 'delegated-reviewer-v1',
        'sources': [{'id': 's', 'title': 'Synthetic rule', 'coverage': 'partial' if missing else 'complete',
                     'content': source_text or ('The class-B value table is absent from the supplied material.' if missing
                     else 'Class B permits 75 to 100.')}]})
    ws = Workspace(store)
    activate(ws)
    return ws


async def capture_role(ws, role):
    _, _, refs, snapshot, _ = seed(ws)
    if role == 'optimizer':
        from report_agent.learning import binding
        from report_agent.learning_runtime import run_optimizer
        ws.store.set('learning_config', {'library_path': str(ws.store.root / 'library'), 'customer_id': 'synthetic'})
        library, scope = binding(ws)
        feedback = library.feedback(scope, {}, {}, 'Select the described class before choosing its score.',
                                    'B,70', ['Synthetic source: class B permits 75–100.'])
        driver = Driver(optimizer=[
            invoke('read_learning_feedback', feedback_id=feedback['id'], field='before'),
            invoke('read_learning_feedback', feedback_id=feedback['id'], field='evidence'),
            AIMessage(content='Capture only; no changes.')])
        await run_optimizer(ws, driver('optimizer'))
        return driver.calls[-1][2], [{'type': 'function', 'function': t}
                                    for t in driver.bindings['optimizer'][-1]]
    if role == 'coordinator':
        args = dict(review_call(snapshot, refs)['args'])
        args.pop('supervision_plugin', None)
        driver = Driver(coordinator=[invoke('task', **args), AIMessage(content='Capture only; no acceptance.')],
            reviewer=[AIMessage(content=json.dumps({'snapshot_ref': snapshot,
                'execution_state': 'partial', 'verdict': None,
                'remaining': 'The class-B interval comparison was not performed. No acceptance is established.'}))])
        result = await run_report(ws, driver)
        assert result['last_error'] is None, result
        return driver.calls[-1][2], [{'type': 'function', 'function': t}
                                    for t in driver.bindings['coordinator'][-1]]
    args = ({'subagent_type': 'writer', 'description':
             'Prepare a paragraph about class B using source s. First inspect the actual source; do not invent the permitted range.'}
            if role == 'writer' else dict(review_call(snapshot, refs)['args']))
    if role == 'layout':
        args = {'subagent_type': 'layout', 'layout_snapshot_ref': snapshot, 'description':
                'Produce a Word draft from the granted snapshot. Use top/bottom/left margins 25mm, '
                'right margin 15mm, body line spacing 1.5. Preserve all content and qualifiers. '
                'No semantic acceptance is requested. Inspect capabilities or the snapshot if needed.'}
    args.pop('supervision_plugin', None)
    script = [AIMessage(content='Synthetic capture only.')]
    if role == 'layout':
        script = [invoke('read_layout_capabilities'), invoke('read_context', target_ref=snapshot), *script]
    driver = Driver(coordinator=[invoke('task', **args), AIMessage(content='Synthetic capture ended.')],
                    **{role: script})
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    selected = [messages for name, _, messages in driver.calls if name == role]
    assert len(selected) == len(script)
    errors = [message for message in selected[-1] if getattr(message, 'status', None) == 'error']
    assert not errors, [message.model_dump() for message in errors]
    return selected[-1], [{'type': 'function', 'function': t} for t in driver.bindings[role][-1]]


def fixture(case):
    if case == 'text-table':
        return {'role': 'assistant', 'content': json.dumps({'kind': 'table',
            'body': {'columns': ['Class', 'Permitted score'],
                     'rows': [['A', '50–74'], ['B', '75–100']]},
            'qualifiers': {'scope': 'Synthetic supplied table only'}, 'claim_kind': 'fact'})}
    if case == 'qualifiers-only':
        from test_text_work_scoped_revision import DELTA
        return {'role': 'assistant', 'content': json.dumps(DELTA)}
    if case in ('writer', 'reviewer', 'coordinator', 'layout', 'optimizer'):
        name, args = {'writer': ('read_source_page', {'source_id': 's'}),
                      'reviewer': ('read_task_assignment', {}),
                      'coordinator': ('project_status', {}),
                      'layout': ('read_layout_capabilities', {}),
                      'optimizer': ('read_learning_feedback', {})}[case]
        return {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'synthetic-call', 'type': 'function',
             'function': {'name': name, 'arguments': json.dumps(args)}}]}
    missing = case == 'text-missing'
    return {'role': 'assistant', 'content': json.dumps({
        'kind': 'block', 'body': {'text': 'The class-B value table was not supplied.' if missing else
                                 'Class B permits values from 75 to 100.'},
        'qualifiers': {'limitations': 'Missing table; no value selected.'} if missing else {},
        'claim_kind': 'fact'})}


async def probe(case, out, live, requested_output_limit=0):
    if type(requested_output_limit) is not int or requested_output_limit < 0:
        raise ValueError('OUTPUT_LIMIT_MUST_BE_A_NONNEGATIVE_INTEGER')
    folder = out / case
    folder.mkdir()
    source_text = ('Supplied reference table. Columns, in this order: Class | Permitted score. '
                   'Rows, in this order: A | 50–74; B | 75–100. Retain both rows and column order.'
                   if case == 'text-table' else None)
    ws = workspace(folder / 'workspace', case == 'text-missing', source_text)
    role = case if case in ('writer', 'reviewer', 'coordinator', 'layout', 'optimizer') else 'text_tool'
    model = configured_model(ws.store, role)
    configured_output_limit = model.max_tokens
    output_limit = requested_output_limit or configured_output_limit
    if type(output_limit) is not int or output_limit < 1:
        await close_model(model)
        raise ValueError('EXPLICIT_OR_CONFIGURED_OUTPUT_LIMIT_REQUIRED')
    wire_requests, responses = [], []

    async def request_hook(request):
        # Exact JSON only; never record HTTP headers, URL query or credentials.
        wire_requests.append(json.loads(request.content))
        save(folder / 'wire-requests.json', wire_requests)

    async def response_hook(response):
        await response.aread()
        responses.append({'http_status': response.status_code, 'body': response.text})
        save(folder / 'wire-responses.json', responses)

    model.http_async_client.event_hooks['request'].append(request_hook)
    model.http_async_client.event_hooks['response'].append(response_hook)
    if not live:
        async def transport(request):
            answer = fixture(case) if case != 'content-checker' else {
                'role': 'assistant', 'content': (await Model().ainvoke([])).content}
            return httpx.Response(200, json={'id': 'offline-' + case, 'object': 'chat.completion',
                'created': 1, 'model': model.model_name,
                'choices': [{'index': 0, 'finish_reason': 'tool_calls' if role != 'text_tool' else 'stop',
                             'message': answer}],
                'usage': {'prompt_tokens': 19, 'completion_tokens': 1, 'total_tokens': 20}})
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(transport)
        model.http_async_client._mounts = {}
    result = {'case': case, 'mode': 'live' if live else 'offline', 'model': model.model_name,
              'configured_output_limit': configured_output_limit,
              'requested_output_limit': requested_output_limit,
              'output_limit_source': 'explicit_probe_override' if requested_output_limit else 'configured_model',
              'output_limit': output_limit, 'generated_actions_executed': False}
    if out.name == 'contract-live-wave2' and case in ('coordinator', 'content-checker'):
        result['prior_received_attempt'] = str(out.parent / 'roles-live-wave1' / case)
        result['purpose'] = 'Reassess the same synthetic scenario with configured output capacity; prior length-bound response is preserved, not reused or relabelled.'
    save(folder / 'intent.json', result)
    try:
        if role != 'text_tool':
            messages, schemas = await capture_role(ws, role)
            save(folder / 'native-input.json', {'messages': messages_to_dict(messages), 'tools': schemas})
            bound = model.bind_tools(schemas)
            reply = await bound.ainvoke(messages, max_tokens=output_limit)
            save(folder / 'model-output.json', reply.model_dump())
            assert reply.response_metadata.get('finish_reason') in ('stop', 'tool_calls'), 'INCOMPLETE_RESPONSE'
            assert not reply.invalid_tool_calls, 'INVALID_TOOL_CALL_JSON'
            assert reply.tool_calls or reply.content, 'EMPTY_RESPONSE'
            by_name = {s['function']['name']: s['function']['parameters'] for s in schemas}
            for call in reply.tool_calls:
                assert call['name'] in by_name, 'UNREGISTERED_TOOL'
                Draft202012Validator(by_name[call['name']]).validate(call['args'])
            result['returned_actions'] = reply.tool_calls
            result['interpretation'] = 'Parsed response/arguments validated; action suitability requires separate trace review. No tool executed.'
        else:
            class Observed:
                max_tokens = output_limit

                def __getattr__(self, name):
                    return getattr(model, name)

                async def ainvoke(self, messages):
                    save(folder / 'text-tool-input.json', messages)
                    reply = await model.ainvoke(messages, max_tokens=output_limit)
                    save(folder / 'model-output.json', reply.model_dump())
                    return reply

            if case == 'content-checker':
                from report_agent.bounded_review import perform_review
                cs, _, refs, snapshot, _ = seed(ws)
                source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
                with delegated_task(ws, 'coordinator', review_call(snapshot, refs, reads=[source])) as (_, actor):
                    result['tool_result'] = await perform_review(ws, actor, Observed(), 'synthetic-check', ['rule-comparison'])
            elif case == 'qualifiers-only':
                from test_text_work_scoped_revision import TABLE, save_fixture, revision
                from report_agent.content_store import ContentStore
                with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
                    ref = save_fixture(ws, actor)
                    result['selected_original_ref'] = ref
                    original = ContentStore(ws.store).read(ref)
                    tool = tools(ws, 'writer', Observed())['process_report_content']
                    result['tool_result'] = await tool('synthetic-qualifier-revision',
                        'Remove only the old process commentary. Keep the technical weathering uncertainty. '
                        'Return qualifiers only; do not change the existing table body or select a score.',
                        'ContentNode', revision=revision(ref))
                    assert result['tool_result']['payload']['body'] == TABLE['body']
                    assert ContentStore(ws.store).read(ref) == original
                    result['body_unchanged_and_original_not_adopted'] = True
            else:
                with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
                    tool = tools(ws, 'writer', Observed())['process_report_content']
                    objective = ('Produce one table ContentNode reproducing the complete supplied two-column table: '
                        'same column labels/order and both rows, without adding a calculated total or selecting a score.'
                        if case == 'text-table' else
                        'Write one block describing class B using only the supplied material. If the value table is missing, '
                        'state that limitation; do not invent a range or select a score.')
                    result['tool_result'] = await tool('synthetic-' + case, objective,
                    'ContentNode', source_selections=[{'source_id': 's'}])
                    if case == 'text-table':
                        body = result['tool_result']['payload']['body']
                        result['table_fixture_match'] = (
                            result['tool_result']['payload'].get('kind') == 'table' and
                            body.get('columns') == ['Class', 'Permitted score'] and
                            body.get('rows') == [['A', '50–74'], ['B', '75–100']])
            result['interpretation'] = (
                'Actual parser saved an independent ReviewRecord in a synthetic workspace; not applied to the original report or whole-report acceptance.'
                if case == 'content-checker' else
                'Actual parser accepted candidate; no adoption into report content or semantic acceptance.')
        result['status'] = 'passed_structure'
    except Exception as exc:
        result.update(status='blocked_before_http' if not wire_requests else 'failed',
                      error_type=type(exc).__name__, error=str(exc))
    finally:
        result['observed_http_requests'] = len(wire_requests)
        result['observed_http_responses'] = len(responses)
        save(folder / 'events.json', ws.store.events())
        save(folder / 'result.json', result)
        await close_model(model)
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--phase-authorization', type=Path)
    parser.add_argument('--wave', choices=['original', 'roles', 'contracts'], default='original')
    parser.add_argument('--output-limit', type=int, default=0,
                        help='Default 0 inherits the configured model limit; a positive value explicitly overrides capacity for this probe.')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)  # Never replay an existing attempt directory.
    os.environ.update(LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false',
                      REPORT_SDK_RETRIES='5', REPORT_CONNECT_RETRIES='0')
    os.environ.pop('REPORT_GRAPH_TEST_URI', None)
    if args.live:
        if not args.env_file or not args.ledger or not args.ledger.is_file():
            raise ValueError('EXISTING_PROVIDER_FILE_AND_LEDGER_REQUIRED')
        assert args.ledger.resolve() == (ROOT / '.runs/full-chain-budget-20261014/token-budget.db').resolve()
        services = load_mixed_services(args.env_file)
        with sqlite3.connect(args.ledger.resolve().as_uri() + '?mode=ro', uri=True) as db:
            maximum, bounds = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
        assert maximum == 170000000, 'AUTHORIZATION_CHANGED_REVIEW_REQUIRED'
        budget = TokenBudget(args.ledger, maximum, json.loads(bounds))
    else:
        original_connect = socket.socket.connect

        def deny(sock, *a, **kw):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise OSError('PROBE_OFFLINE_NETWORK_DENIED')
            return original_connect(sock, *a, **kw)

        socket.socket.connect = deny
        for role in ('', 'COORDINATOR_', 'WRITER_', 'REVIEWER_', 'TEXT_TOOL_', 'LAYOUT_', 'OPTIMIZER_'):
            for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'offline'}.items():
                os.environ['REPORT_' + role + key] = value
        os.environ['REPORT_DEEPSEEK_STRICT'] = '0'
        services = {'mode': 'offline fake service; production strict compatibility not established'}
        budget = TokenBudget(out / 'offline-budget.db', 10000000, {'glm-5.3': 2000000})
    if args.live:
        expected = ROOT / '.analysis/agent-duty-validation-20261018/validation-budget-authorization.json'
        if not args.phase_authorization or args.phase_authorization.resolve() != expected.resolve():
            raise ValueError('EXPLICIT_CURRENT_PHASE_AUTHORIZATION_REQUIRED')
        with FileLock(str(expected) + '.lock', timeout=0):
            authorization = json.loads(expected.read_text(encoding='utf-8'))
            assert authorization['maximum_tokens'] == 10000000
            baseline_file = ROOT / authorization['baseline_ledger_rows']
            assert hashlib.sha256(baseline_file.read_bytes()).hexdigest() == authorization['baseline_sha256']
            phase = {'authorization_sha256': hashlib.sha256(expected.read_bytes()).hexdigest(),
                     'baseline': json.loads(baseline_file.read_text(encoding='utf-8')),
                     'maximum': authorization['maximum_tokens']}
            admitted = phase_admission(phase['baseline'], ledger_rows(budget.path),
                                       phase['maximum'], budget.model_bounds)
            save(out / 'phase-admission.json', {**admitted,
                 'authorization_sha256': phase['authorization_sha256']})
            return await run_wave(args, out, budget, services, phase)
    return await run_wave(args, out, budget, services)


async def run_wave(args, out, budget, services, phase=None):
    cap = RequestBudget(4)
    hashes = code_hashes()
    old_rows = ledger_rows(budget.path)
    save(out / 'ledger-before.json', old_rows)
    summary = {'services': services, 'wave': args.wave, 'max_http_attempts_including_retries': 4,
               'budget_before': budget.snapshot(), 'source_sha256': hashes,
               'ledger_path': str(budget.path.resolve()),
               'ledger_before_sha256': hashlib.sha256((out / 'ledger-before.json').read_bytes()).hexdigest(),
               'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases': []}
    save(out / 'registration.json', summary)
    with token_budget(budget), request_budget(cap):
        cases = {'original': ('writer', 'reviewer', 'text-normal', 'text-missing'),
                 'roles': ('coordinator', 'layout', 'optimizer', 'content-checker'),
                 'contracts': ('coordinator', 'content-checker', 'text-table', 'qualifiers-only')}[args.wave]
        for case in cases:
            result = await probe(case, out, args.live, args.output_limit)
            summary['cases'].append(result)
            summary['http_budget'] = cap.snapshot()
            summary['budget_after'] = budget.snapshot()
            now_rows = ledger_rows(budget.path)
            if phase:
                summary['phase_budget_after'] = phase_admission(phase['baseline'], now_rows,
                    phase['maximum'], budget.model_bounds, attempts=0)
            summary['previous_ledger_rows_unchanged'] = (now_rows['authorization'] == old_rows['authorization'] and
                all(now_rows['attempts'].get(k) == row for k, row in old_rows['attempts'].items()))
            summary['code_unchanged_during_probes'] = code_hashes() == hashes
            save(out / 'result.json', summary)
            print(json.dumps({k: result.get(k) for k in ('case', 'status', 'observed_http_requests', 'error_type')}, ensure_ascii=False), flush=True)
    return 0 if all(c['status'] == 'passed_structure' for c in summary['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
