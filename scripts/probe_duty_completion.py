"""Approved duty-plan probes: native synthetic packets, one actual response each.

Offline by default. Existing project/phase accounting and unknown reservations
are preserved. Five initial waves allow 20 HTTP attempts; the separately
registered missing-correction delta adds at most two. R7 adds four independently
registered semantic contrasts. R8/R9 separately register bounded native agent
decisions; all are new cases, not retries.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3

import probe_agent_io as base
import httpx
from filelock import FileLock
from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, messages_to_dict
from report_agent.bounded_review import perform_review
from report_agent.content_tasks import delegated_task
from report_agent.deep_models import (configured_model, connection_retry_count,
                                      MODEL_REQUEST_DEADLINE_SECONDS)
from report_agent.deep_runtime import run_report
from report_agent.model_config import load_mixed_services
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_repro_judgments import assessment_fixture
from test_agent_result_delivery import packet, reply
from test_bounded_deadline import close_model
from test_bounded_review import Model, review_call
from test_hierarchical_content import seed
from test_deep_runtime import Driver, invoke

WAVES = {'R1': ['co-partial', 'co-negative', 'check-full', 'check-missing'],
         'R2': ['text-full', 'text-missing', 'writer-full', 'writer-missing'],
         'R3': ['layout-standard', 'layout-old-reference', 'visual-artifact-pair'],
         'R4': ['learning-full', 'learning-missing', 'optimizer-full', 'optimizer-missing'],
         'R5': ['co-criteria-full', 'co-criteria-conflict', 'reviewer-reuse-local', 'reviewer-reuse-expanded'],
         'R6': ['optimizer-correction'],
         'R7': ['text-class-known', 'text-class-unknown',
                'text-revision-process', 'text-revision-all'],
         'R8': ['writer-chapter-order'], 'R9': ['co-current-delivery'],
         'R10': ['writer-candidate-missing'], 'R11': ['optimizer-feedback-outcomes'],
         'R12': ['visual-artifact-columns-complete'], 'R13': ['optimizer-single-feedback'],
         'R14': ['reviewer-consumer-missing'], 'R15': ['writer-source-nohit'],
         'R16': ['writer-revision-consumer'], 'R17': ['coordinator-requirements'], 'R18': ['writer-source-hit'],
         'R19': ['coordinator-review-outcome'], 'R20': ['artifact-error-consumer'],
         'R21': ['writer-guidance-applicable'], 'R22': ['writer-guidance-inapplicable'],
         'R23': ['writer-multi-consumer'], 'R24': ['optimizer-three-feedback'],
         'R25': ['coordinator-review-commission'], 'R26': ['layout-current-document-outcome'],
         'R27': ['writer-current-paired-delivery'], 'R28': ['reviewer-current-source-investigation'],
         'R29': ['layout-local-paired-page-comparison'], 'R30': ['writer-independent-analysis']}
INCREMENT_ATTEMPT_LIMITS = {'R7': 26, 'R8': 30, 'R9': 34, 'R10': 38, 'R11': 42, 'R12': 44, 'R13': 48, 'R14': 52, 'R15': 56, 'R16': 60, 'R17': 64, 'R18': 68,
                            'R19': 72, 'R20': 76, 'R21': 80, 'R22': 84, 'R23': 88, 'R24': 94, 'R25': 98, 'R26': 99, 'R27': 105, 'R28': 113, 'R29': 121, 'R30': 127}
PHASE_ATTEMPT_LIMITS = {'R7': 34, 'R8': 38, 'R9': 42, 'R10': 46, 'R11': 50, 'R12': 52, 'R13': 56, 'R14': 60, 'R15': 64, 'R16': 68, 'R17': 72, 'R18': 76,
                        'R19': 80, 'R20': 84, 'R21': 88, 'R22': 92, 'R23': 96, 'R24': 102, 'R25': 106, 'R26': 107, 'R27': 113, 'R28': 121, 'R29': 129, 'R30': 135}
HTTP_ATTEMPT_LIMITS = {
    'R1': 4, 'R2': 4, 'R3': 4, 'R4': 4, 'R5': 4, 'R6': 2,
    'R7': 4, 'R8': 4, 'R9': 4, 'R10': 4, 'R11': 4, 'R12': 2,
    'R13': 4, 'R14': 4, 'R15': 4, 'R16': 4, 'R17': 4, 'R18': 4,
    'R19': 4, 'R20': 4, 'R21': 4, 'R22': 4, 'R23': 4, 'R24': 6,
    'R25': 4, 'R26': 8, 'R27': 6, 'R28': 8, 'R29': 8, 'R30': 6,
}
LEGACY_UNREGISTERED_WAVES = frozenset({'R1', 'R2', 'R3', 'R4', 'R5', 'R6'})


def wave_attempt_limit(wave):
    return HTTP_ATTEMPT_LIMITS[wave]
ROOT = base.ROOT
TABLE = 'Class | Permitted score | Explanation\nB | 75–100 | Use only for described class B.\nC | 90–100 | Class C only.\nFootnote: unresolved class must remain unresolved.'


def text_material(ws, missing):
    text = 'The selected material names class B but contains no class value table.' if missing else TABLE
    manifest = ws.store.manifest
    manifest['goal'] = 'Reproduce the supplied complete table and footnote. If the table is missing, retain the limitation; do not invent values.'
    manifest['sources'][0]['content'] = text
    ws.store.set('manifest', manifest)
    return text


def text_answer(missing):
    return {'payloads': [{'kind': 'block' if missing else 'table',
        'body': {'text': 'The supplied material does not include the table.'} if missing else {
            'columns': ['Class', 'Permitted score', 'Explanation'],
            'rows': [['B', '75–100', 'Use only for described class B.'], ['C', '90–100', 'Class C only.']]},
        'qualifiers': {'limitations': 'No value can be selected without the table.'} if missing else {
            'footnote': 'Unresolved class must remain unresolved.'}, 'claim_kind': 'fact'}],
        'generation_notes': [{'output_index': 0, 'text': 'Only the supplied material was used; engineering applicability is not established.'}]}


def text_args():
    return {'operation_id': 'synthetic-table', 'objective': 'Reproduce all supplied table columns, both rows and the complete footnote in one ContentNode. If table missing, return a limited block instead; do not infer values. Keep process notes separate in generation_notes.',
            'object_type': 'ContentNode', 'output_count': 1, 'source_selections': [{'source_id': 's'}]}


def prior_raw(out, name):
    previous = out / name
    state = json.loads((previous / 'result.json').read_text())
    assert state['status'] == 'passed_structure', 'PREDECESSOR_OUTPUT_INVALID: do not pay to consume an invalid packet'
    return json.loads((previous / 'model-output.json').read_text())['content']


async def capture_writer(ws, missing, raw, folder):
    text_material(ws, missing)
    seed(ws)
    service = Model(raw)
    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description=ws.store.manifest['goal']),
                                 AIMessage(content='Capture ended without publication.')],
                    writer=[invoke('process_report_content', **text_args()), AIMessage(content='Capture only.')])
    result = await run_report(ws, lambda role: service if role == 'text_tool' else driver(role))
    base.save(folder / 'fixture-native-trace.json', {'result': result,
        'calls': [{'role': r, 'step': n, 'messages': messages_to_dict(m)} for r, n, m in driver.calls]})
    assert result['last_error'] is None, result
    messages = [m for r, _, m in driver.calls if r == 'writer'][-1]
    actual = packet(reply(messages, 'process_report_content'))
    assert actual.get('metadata', actual)['state'] == 'completed'
    return messages, [{'type': 'function', 'function': t} for t in driver.bindings['writer'][-1]], {'delivered': actual}


def learning_fixture(ws, missing):
    from report_agent.learning import binding
    ws.store.set('learning_config', {'library_path': str(ws.store.root / 'library'), 'customer_id': 'synthetic'})
    lib, scope = binding(ws)
    feedback = lib.feedback(scope, {}, {}, 'Customer feedback claims class B permits 70. Check whether this claim agrees with the actual source; retain the distinction between feedback and verified fact.',
        'Adopted class B, score 70.', ['The supplied material contains no class B value table.' if missing else 'Class B permits 75–100.'])
    ws.store.set('learning_active_feedback', {'id': 'synthetic-current', 'feedback_ids': [feedback['id']]})
    ws.store.set('learning_job', {'id': 'synthetic-job', 'state': 'running'})
    return feedback


def learning_args(feedback):
    return {'question': 'Compare the recorded value with supplied evidence; distinguish missing evidence from a confirmed conflict.',
        'feedback_selections': [{'feedback_id': feedback['id'], 'field': 'before'},
                                {'feedback_id': feedback['id'], 'field': 'evidence'}]}


async def capture_optimizer(ws, missing, raw, folder, *, text_model=None, include_correction=False):
    from report_agent.learning_runtime import build_optimizer
    feedback = learning_fixture(ws, missing)
    args = learning_args(feedback)
    steps = []
    if include_correction:
        args['feedback_selections'].insert(0, {'feedback_id': feedback['id'], 'field': 'correction'})
        steps.append(invoke('read_learning_feedback', feedback_id=feedback['id'], field='correction'))
    driver = Driver(optimizer=[*steps, invoke('analyze_learning_material', **args),
                               AIMessage(content='Capture only, no candidate or release.')])
    await build_optimizer(ws, driver('optimizer'), text_model=text_model if text_model is not None else Model(raw)).ainvoke(
        {'messages': [('user', 'Handle this assigned synthetic feedback using actual evidence. Save an inactive candidate only if useful; otherwise account for no change or insufficient evidence. Do not publish.')]})
    messages = driver.calls[-1][2]
    actual = packet(reply(messages, 'analyze_learning_material'))
    base.save(folder / 'fixture-native-trace.json', {'calls': [
        {'role': r, 'step': n, 'messages': messages_to_dict(m)} for r, n, m in driver.calls]})
    assert actual['fact_correctness_verified'] is False
    return messages, [{'type': 'function', 'function': t} for t in driver.bindings['optimizer'][-1]], {'delivered': actual}


def scoped_fixture(ws, missing):
    manifest = ws.store.manifest
    manifest['goal'] = 'Check independently adopted class B=70 and class C=85 against each original class rule; preserve unperformed comparisons and distinguish execution from acceptance.'
    manifest['sources'].append({'id': 'c', 'title': 'Independent class C reference', 'coverage': 'complete',
        'content': ('The supplied reference has no class C value table. Class B rules do not establish class C values.'
                    if missing else 'For class C only, the permitted interval is 90 to 100.')})
    ws.store.set('manifest', manifest)
    cs, owner, refs, _, members = seed(ws)
    c = cs.import_inputs(owner, 'c-input', ['c'])['result']
    extra = cs.commit(owner, 'c-target', [
        {'client_key': 'claim2', 'type': 'ContentNode', 'payload': {'kind': 'claim',
            'body': {'text': 'For independently adopted class C use 85.'}, 'qualifiers': {}, 'claim_kind': 'inference'}},
        {'client_key': 'k2', 'type': 'Criterion', 'payload': {**cs.read(refs['k'])['payload'],
            'scope': 'Class C target only', 'evidence_expectation': 'Compare class C against its own original reference, not class B.'}},
        {'client_key': 'edge2', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'claim2'}, 'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    refs.update(extra)
    all_refs = {json.dumps(r, sort_keys=True): r for r in [*members, c['requirement_ref'], *c['source_refs'], *extra.values()]}
    snapshot = cs.freeze(owner, 'two-scope-snapshot', refs['root'], list(all_refs.values()))['result']['snapshot_ref']
    source = next(r for r in members if r['type'] == 'SourceArtifact')
    args = dict(review_call(snapshot, refs)['args']); args.pop('supervision_plugin', None)
    args['review_requirements'].append({**deepcopy(args['review_requirements'][0]),
        'scope_id': 'second-comparison', 'target_ref': refs['claim2'], 'criterion_ref': refs['k2']})
    for i, requirement in enumerate(args['review_requirements']):
        requirement['required_materials'][0]['refs'] = [refs['claim' if i == 0 else 'claim2'],
                                                        source if i == 0 else c['source_refs'][0]]
    call = {'id': 'synthetic-review', 'name': 'task', 'type': 'tool_call', 'args': args}
    outputs = [deepcopy(assessment_fixture('not_satisfied')['items'][0]),
               deepcopy(assessment_fixture('blocked' if missing else 'not_satisfied')['items'][0])]
    outputs[1]['scope_id'] = 'second-comparison'
    if not missing:
        outputs[1]['reason'] = 'Class C value 85 is below its independent 90 to 100 interval.'
    # Actual bounded input orders all targets first, then selected sources.
    for i, item in enumerate(outputs):
        item['observations'][0]['evidence_index'] = i
        item['observations'][0]['observation'] = 'Adopted class B,70.' if i == 0 else 'Adopted class C,85.'
        item['observations'].append({'evidence_index': i + 2, 'locator': 'original rule',
            'observation': 'Class B permits 75 to 100.' if i == 0 else manifest['sources'][-1]['content'],
            'limitations': 'Selected reference only.'})
        item['check_results'][0]['observation_indexes'] = [0, 1]
    return cs, refs, snapshot, call, {'items': outputs}


async def capture_co(ws, missing, folder):
    cs, refs, snapshot, call, output = scoped_fixture(ws, missing)
    service = Model(json.dumps(output))
    observed = {}

    def child(messages):
        value = packet(reply(messages, 'perform_assigned_review'))
        value = value.get('metadata', value)
        observed['saved_review'] = value
        return AIMessage(content=json.dumps(value))

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]),
        invoke('read_task_supervision'), AIMessage(content='Capture only, no completion claim.')],
        reviewer=[invoke('perform_assigned_review', operation_id='two-scopes',
                         scope_ids=['rule-comparison', 'second-comparison'], source_selections=[], content_selections=[]), child])
    result = await run_report(ws, lambda role: service if role == 'text_tool' else driver(role))
    base.save(folder / 'fixture-native-trace.json', {'result': result,
        'calls': [{'role': r, 'step': n, 'messages': messages_to_dict(m)} for r, n, m in driver.calls],
        'bindings': driver.bindings, 'observed': observed, 'independent_calls': service.calls})
    assert result['last_error'] is None, result
    assert len(cs.list_objects('ReviewRecord')) == 1, 'FIXTURE_REVIEW_NOT_SAVED: inspect fixture-native-trace.json'
    actual = [messages for role, _, messages in driver.calls if role == 'coordinator'][-1]
    assert observed['saved_review']['items'][1]['execution_state'] == ('blocked' if missing else 'completed')
    return actual, [{'type': 'function', 'function': t} for t in driver.bindings['coordinator'][-1]], observed


async def probe(case, out, live):
    folder = out / case
    folder.mkdir()
    ws = base.workspace(folder / 'workspace')
    if case in WAVES['R8'] + WAVES['R9'] + WAVES['R10'] + WAVES['R11'] + WAVES['R13'] + WAVES['R14'] + WAVES['R15'] + WAVES['R16'] + WAVES['R17'] + WAVES['R18'] + WAVES['R19'] + WAVES['R20'] + WAVES['R21'] + WAVES['R22'] + WAVES['R23'] + WAVES['R24'] + WAVES['R25'] + WAVES['R26'] + WAVES['R27'] + WAVES['R28'] + WAVES['R29'] + WAVES['R30']:
        from probe_duty_decisions import probe_native_decision
        return await probe_native_decision(ws, folder, case, live)
    if case in {'visual-artifact-pair', 'visual-artifact-columns-complete'}:
        from probe_duty_visual import probe_visual_pair
        return await probe_visual_pair(ws, folder, live, case=case)
    role = next((r for r in ('coordinator', 'writer', 'optimizer', 'reviewer', 'layout')
                 if case.startswith({'coordinator': 'co-', 'writer': 'writer-', 'optimizer': 'optimizer-', 'reviewer': 'reviewer-', 'layout': 'layout-'}[r])), 'text_tool')
    model = configured_model(ws.store, role)
    requests, responses = [], []
    secondary_model = None
    async def request_hook(request):
        requests.append(json.loads(request.content))
        base.save(folder / 'wire-requests.json', requests)
    async def response_hook(response):
        await response.aread()
        responses.append({'http_status': response.status_code, 'body': response.text})
        base.save(folder / 'wire-responses.json', responses)
    model.http_async_client.event_hooks['request'].append(request_hook)
    model.http_async_client.event_hooks['response'].append(response_hook)
    result = {'case': case, 'mode': 'live' if live else 'offline', 'model': model.model_name,
              'configured_output_limit': model.max_tokens, 'generated_actions_executed': False,
              'sdk_max_retries': model.max_retries,
              'httpx_connect_retries': connection_retry_count(),
              'logical_request_deadline_seconds': MODEL_REQUEST_DEADLINE_SECONDS,
              'logical_case_auto_replay': False,
              'intent': 'One synthetic decision or independent checking response; no customer report acceptance.'}
    base.save(folder / 'intent.json', result)
    fake_response = {}
    provider_response = {}
    if not live:
        async def transport(request):
            requested_model = json.loads(request.content)['model']
            return httpx.Response(200, json={'id': 'offline-' + case, 'object': 'chat.completion',
                'created': 1, 'model': requested_model, 'choices': [{'index': 0,
                'finish_reason': 'tool_calls' if provider_response.get('tool_calls') else 'stop',
                'message': provider_response or {'role': 'assistant', 'content': json.dumps(fake_response)}}],
                'usage': {'prompt_tokens': 19, 'completion_tokens': 1, 'total_tokens': 20}})
        await model.http_async_client._transport.aclose()
        model.http_async_client._transport = httpx.MockTransport(transport)
        model.http_async_client._mounts = {}
    class Observed:
        def __init__(self, selected=None, prefix=''):
            self.selected = model if selected is None else selected
            self.prefix = prefix
        def __getattr__(self, key):
            return getattr(self.selected, key)
        async def ainvoke(self, messages):
            base.save(folder / (self.prefix + 'independent-input.json'), messages)
            answer = await self.selected.ainvoke(messages)
            base.save(folder / (self.prefix + 'model-output.json'), answer.model_dump())
            return answer
    try:
        if role != 'text_tool':
            missing = case.endswith('missing') or case == 'co-partial'
            if case == 'optimizer-correction':
                secondary_model = configured_model(ws.store, 'text_tool')
                secondary_model.http_async_client.event_hooks['request'].append(request_hook)
                secondary_model.http_async_client.event_hooks['response'].append(response_hook)
                if not live:
                    await secondary_model.http_async_client._transport.aclose()
                    secondary_model.http_async_client._transport = httpx.MockTransport(transport)
                    secondary_model.http_async_client._mounts = {}
                fake_response.update({'findings': 'The customer assertion 70 conflicts with the supplied 75–100 source interval; feedback is not source truth.', 'project_fact': None})
                messages, schemas, observed = await capture_optimizer(ws, False, None, folder,
                    text_model=Observed(secondary_model, 'analysis-'), include_correction=True)
                independent = json.loads((folder / 'analysis-independent-input.json').read_text())
                assert independent[-1][0] == 'user'
                selected = json.loads(independent[-1][1])['evidence']
                assert [v['selection']['field'] for v in selected] == ['correction', 'before', 'evidence']
                assert 'Customer feedback claims class B permits 70.' in selected[0]['text']
                assert '75–100' in selected[2]['text']
                serialized = json.dumps(messages_to_dict(messages), ensure_ascii=False)
                assert selected[0]['text'] in serialized
                result['analysis_and_consumer_same_job_feedback'] = True
                result['analysis_model'] = secondary_model.model_name
                result['captured_feedback_id'] = selected[0]['selection']['feedback_id']
                provider_response.update({'role': 'assistant', 'content': 'The correction conflicts with the supplied original rule; retain the conflict and do not publish.'})
            elif case in WAVES['R5']:
                from duty_probe_packets import capture_r5
                captured = await capture_r5(ws, case, folder)
                messages, schemas, observed = captured['messages'], captured['tools'], captured['observations']
                provider_response.update(captured['fake_response'])
            elif role == 'layout':
                from duty_probe_visual_packets import capture_layout
                captured = await capture_layout(ws, case, folder)
                messages, schemas, observed = captured['messages'], captured['tools'], captured['observations']
                provider_response.update(captured['fake_response'])
            elif role == 'coordinator':
                messages, schemas, observed = await capture_co(ws, missing, folder)
            elif role == 'writer':
                messages, schemas, observed = await capture_writer(ws, missing,
                    prior_raw(out, 'text-missing' if missing else 'text-full'), folder)
                result['prior_raw_reused_for_native_fixture'] = str(out / ('text-missing' if missing else 'text-full'))
            else:
                messages, schemas, observed = await capture_optimizer(ws, missing,
                    prior_raw(out, 'learning-missing' if missing else 'learning-full'), folder)
                result['prior_raw_reused_for_native_fixture'] = str(out / ('learning-missing' if missing else 'learning-full'))
            base.save(folder / 'native-input.json', {'messages': messages_to_dict(messages), 'tools': schemas,
                                                   'fixture_observations': observed})
            fake_response.update({'execution_state': 'partial' if missing else 'completed',
                                  'acceptance': False, 'remaining': 'B comparison unresolved' if missing else ''})
            answer = await model.bind_tools(schemas).ainvoke(messages)
            base.save(folder / 'model-output.json', answer.model_dump())
            assert answer.response_metadata.get('finish_reason') in ('stop', 'tool_calls'), 'INCOMPLETE_RESPONSE'
            assert not answer.invalid_tool_calls, 'INVALID_TOOL_CALL_JSON'
            assert answer.tool_calls or answer.content, 'EMPTY_RESPONSE'
            by_name = {s['function']['name']: s['function']['parameters'] for s in schemas}
            for call in answer.tool_calls:
                assert call['name'] in by_name, 'UNREGISTERED_TOOL'
                Draft202012Validator(by_name[call['name']]).validate(call['args'])
            result['returned_actions'] = answer.tool_calls
            if case in WAVES['R5']:
                result['expected_semantic_boundary'] = ('Resolve or preserve conflicting current instructions; existing seed criteria do not prove new requirements covered.'
                    if role == 'coordinator' else 'Old local review may remain useful but cannot close expanded subtree checks. Partial reuse is allowed; no full completion inferred.')
            elif role == 'writer':
                result['expected_semantic_boundary'] = 'Use the actual returned candidate/notes and decide next action without inventing absent table values; reading, adoption or further investigation may be valid.'
            elif role == 'optimizer':
                result['expected_semantic_boundary'] = 'Choose scoped handling from the actual analysis; wrong customer assertion is not source truth, absent evidence stays uncertain, candidate is not release.'
            elif role == 'layout':
                result['expected_semantic_boundary'] = 'Use current standard, preserve four table columns and footnote; old unverified parameters must not override the current standard. One response is not completed layout or visual acceptance.'
            else:
                result['expected_semantic_boundary'] = ('Second comparison remains incomplete; do not infer acceptance.' if missing
                    else 'All assigned executions complete but not_satisfied; do not confuse execution with acceptance.')
        elif case.startswith('check-'):
            cs, refs, snapshot, call, response = scoped_fixture(ws, case == 'check-missing')
            fake_response.update(response)
            with delegated_task(ws, 'coordinator', call) as (_, actor):
                result['tool_result'] = await perform_review(ws, actor, Observed(), 'synthetic-two-scopes',
                    ['rule-comparison', 'second-comparison'])
            result['expected_semantic_boundary'] = 'Scope identity, declared materials, observation links and unperformed checks remain distinct.'
        elif case in WAVES['R7']:
            from duty_probe_semantic_packets import capture_semantic, semantic_fake_response
            fake_response.update(semantic_fake_response(case))
            captured = await capture_semantic(ws, case, folder, Observed())
            result['tool_result'] = captured['tool_result']
            result['fixture_observations'] = captured['observations']
            result['expected_semantic_boundary'] = (
                'Arithmetic85 alone does not establish an engineering class; preserve the selected class evidence or uncertainty.'
                if case.startswith('text-class-') else
                'Qualifiers-only revision preserves body/kind/claim_kind and factual technical uncertainty; process commentary may be removed. Candidate is not adopted.')
        elif case.startswith('text-'):
            from test_text_work import tools, writer_call
            missing = case.endswith('missing')
            text_material(ws, missing)
            fake_response.update(text_answer(missing))
            with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
                result['tool_result'] = await tools(ws, 'writer', Observed())['process_report_content'](**text_args())
            result['expected_semantic_boundary'] = 'Complete table/footnote or explicit missing-material qualification; no invented range.'
        elif case.startswith('learning-'):
            from report_agent.learning_text_work import learning_analysis_tool, FeedbackSelection
            missing = case.endswith('missing')
            feedback = learning_fixture(ws, missing)
            fake_response.update({'findings': 'The value cannot be checked without the table.' if missing else '70 conflicts with the supplied B interval 75–100.',
                'project_fact': None if missing else {'title': 'Synthetic B rule', 'strategy': 'Class B permits 75–100.', 'conditions': 'This synthetic source only.'}})
            args = learning_args(feedback)
            result['tool_result'] = await learning_analysis_tool(ws, Observed())(args['question'],
                [FeedbackSelection(**s) for s in args['feedback_selections']])
            result['expected_semantic_boundary'] = 'User correction is a claim to compare, not established source truth; missing table must remain unknown.'
        result['status'] = 'passed_structure'
        result['semantic_acceptance'] = 'pending independent review of raw response, not implied by parser'
    except Exception as exc:
        result.update(status='failed' if requests else 'blocked_before_http', error_type=type(exc).__name__, error=str(exc))
    finally:
        result.update(observed_http_requests=len(requests), observed_http_responses=len(responses))
        base.save(folder / 'result.json', result)
        base.save(folder / 'events.json', ws.store.events())
        await close_model(model)
        if secondary_model is not None:
            await close_model(secondary_model)
    return result


async def run_wave(args, out, budget, phase, services):
    old = base.ledger_rows(budget.path)
    base.save(out / 'ledger-before.json', old)
    hashes = base.code_hashes()
    source_archive = out / 'probe-source'
    source_archive.mkdir()
    archived_sources = {}
    for source in [Path(__file__), Path(base.__file__), Path(__file__).with_name('probe_duty_visual.py'),
                   Path(__file__).with_name('probe_duty_decisions.py'),
                   ROOT / 'tests/duty_probe_packets.py', ROOT / 'tests/duty_probe_visual_packets.py',
                   ROOT / 'tests/duty_probe_semantic_packets.py', ROOT / 'tests/test_duty_semantic_packets.py',
                   ROOT / 'tests/duty_probe_agent_decisions.py', ROOT / 'tests/test_duty_agent_decisions.py',
                   ROOT / 'tests/duty_probe_writer_adoption.py', ROOT / 'tests/test_duty_writer_adoption.py',
                   ROOT / 'tests/duty_probe_optimizer_outcome.py', ROOT / 'tests/test_duty_optimizer_outcome.py',
                   ROOT / 'tests/test_duty_artifact_contrast.py', ROOT / 'tests/test_duty_artifact_adapter.py',
                   ROOT / 'tests/duty_probe_optimizer_single.py', ROOT / 'tests/test_duty_optimizer_single.py',
                   ROOT / 'tests/test_duty_optimizer_single_adapter.py',
                   ROOT / 'tests/duty_probe_reviewer_consumer.py', ROOT / 'tests/test_duty_reviewer_consumer.py',
                   ROOT / 'tests/test_duty_reviewer_consumer_adapter.py',
                   ROOT / 'tests/duty_probe_source_continuation.py', ROOT / 'tests/test_duty_source_continuation.py',
                   ROOT / 'tests/test_duty_source_continuation_adapter.py',
                   ROOT / 'tests/duty_probe_coordinator_requirements.py', ROOT / 'tests/test_duty_coordinator_requirements.py',
                   ROOT / 'tests/duty_probe_writer_revision_consumer.py', ROOT / 'tests/test_duty_writer_revision_consumer.py',
                   ROOT / 'tests/test_duty_remaining_consumers_adapter.py',
                   ROOT / 'tests/duty_probe_coordinator_review_outcome.py', ROOT / 'tests/test_duty_coordinator_review_outcome.py',
                   ROOT / 'tests/duty_probe_coordinator_review_commission.py', ROOT / 'tests/test_duty_coordinator_review_commission.py',
                   ROOT / 'tests/test_duty_coordinator_review_commission_adapter.py',
                   ROOT / 'tests/duty_probe_layout_outcome.py', ROOT / 'tests/test_duty_layout_outcome.py',
                   ROOT / 'tests/test_duty_layout_outcome_adapter.py',
                   ROOT / 'tests/duty_probe_writer_delivery_outcome.py', ROOT / 'tests/test_duty_writer_delivery_outcome.py',
                   ROOT / 'tests/test_duty_writer_delivery_outcome_adapter.py',
                   ROOT / 'tests/duty_probe_reviewer_source_investigation.py',
                   ROOT / 'tests/test_duty_reviewer_source_investigation.py',
                   ROOT / 'tests/test_duty_reviewer_source_investigation_adapter.py',
                   ROOT / 'tests/duty_probe_layout_comparison_outcome.py',
                   ROOT / 'tests/test_duty_layout_comparison_outcome.py',
                   ROOT / 'tests/test_duty_layout_comparison_adapter.py',
                   ROOT / 'tests/duty_probe_writer_analysis_outcome.py',
                   ROOT / 'tests/test_duty_writer_analysis_outcome.py',
                   ROOT / 'tests/test_duty_writer_analysis_outcome_adapter.py',
                   ROOT / 'tests/duty_probe_artifact_error_consumer.py', ROOT / 'tests/test_duty_artifact_error_consumer.py',
                   ROOT / 'tests/duty_probe_writer_guidance.py', ROOT / 'tests/test_duty_writer_guidance.py',
                   ROOT / 'tests/duty_probe_writer_multi_consumer.py', ROOT / 'tests/test_duty_writer_multi_consumer.py',
                   ROOT / 'tests/test_duty_review_consumers_adapter.py', ROOT / 'tests/test_duty_writer_next_adapter.py',
                   ROOT / 'tests/duty_probe_optimizer_three.py', ROOT / 'tests/test_duty_optimizer_three.py',
                   ROOT / 'tests/test_duty_optimizer_three_adapter.py']:
        if source.exists():
            saved = source_archive / source.name
            saved.write_bytes(source.read_bytes())
            archived_sources[str(source.resolve().relative_to(ROOT)).replace('\\', '/')] = {
                'archive_path': str(saved.relative_to(out)).replace('\\', '/'),
                'sha256': hashlib.sha256(saved.read_bytes()).hexdigest()}
    base.save(out / 'probe-source-manifest.json', archived_sources)
    wave_attempts = wave_attempt_limit(args.wave)
    summary = {'wave': args.wave, 'services': services, 'case_plan': WAVES[args.wave],
        'new_plan_maximum_http_attempts': 22 if args.wave in LEGACY_UNREGISTERED_WAVES else INCREMENT_ATTEMPT_LIMITS[args.wave],
        'phase_maximum_http_attempts': 30 if args.wave in LEGACY_UNREGISTERED_WAVES else PHASE_ATTEMPT_LIMITS[args.wave],
        'wave_maximum_http_attempts_including_retries': wave_attempts, 'budget_before': budget.snapshot(),
        'source_sha256': hashes, 'probe_source_archive_sha256': archived_sources,
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases': []}
    base.save(out / 'registration.json', summary)
    cap = RequestBudget(wave_attempts)
    with token_budget(budget), request_budget(cap):
        for case in WAVES[args.wave]:
            answer = await probe(case, out, args.live)
            summary['cases'].append(answer)
            current = base.ledger_rows(budget.path)
            summary.update(http_budget=cap.snapshot(), budget_after=budget.snapshot(),
                phase_budget_after=base.phase_admission(phase['baseline'], current, phase['maximum_tokens'],
                    budget.model_bounds, attempts=0, max_attempts=summary['phase_maximum_http_attempts']),
                previous_ledger_rows_unchanged=current['authorization'] == old['authorization'] and
                    all(current['attempts'].get(k) == row for k, row in old['attempts'].items()),
                code_unchanged_during_probes=base.code_hashes() == hashes)
            summary['application_source_unchanged_during_probes'] = {
                k: v for k, v in base.code_hashes().items() if k.startswith('src/')
            } == {k: v for k, v in hashes.items() if k.startswith('src/')}
            base.save(out / 'result.json', summary)
            print(json.dumps({k: answer.get(k) for k in ('case', 'status', 'observed_http_requests', 'error')}, ensure_ascii=False), flush=True)
    return int(any(c['status'] not in {'passed_structure', 'passed_native_oracle',
                                     'native_observation_requires_review'} for c in summary['cases']))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--wave', choices=list(WAVES), required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    os.environ.update(LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false',
                      REPORT_SDK_RETRIES='5', REPORT_CONNECT_RETRIES='0')
    os.environ.pop('REPORT_GRAPH_TEST_URI', None)
    if not args.live:
        original = socket.socket.connect
        def deny(sock, *a, **kw):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise OSError('PROBE_OFFLINE_NETWORK_DENIED')
            return original(sock, *a, **kw)
        socket.socket.connect = deny
        for role in ('', 'COORDINATOR_', 'WRITER_', 'REVIEWER_', 'TEXT_TOOL_', 'LAYOUT_', 'OPTIMIZER_'):
            for k, v in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'offline'}.items():
                os.environ['REPORT_' + role + k] = v
        os.environ['REPORT_DEEPSEEK_STRICT'] = '0'
        for k, v in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'offline'}.items():
            os.environ['REPORT_VISION_' + k] = v
        if args.wave == 'R20':
            from test_vision import VisionModel
            os.environ['REPORT_VISION_MODEL'] = VisionModel().returned_model
        budget = TokenBudget(out / 'offline-budget.db', 10000000, {'glm-5.3': 2000000})
        phase = {'baseline': base.ledger_rows(budget.path), 'maximum_tokens': 10000000}
        return await run_wave(args, out, budget, phase, {'mode': 'offline MockTransport'})
    assert args.env_file and args.env_file.is_file(), 'EXISTING_PROVIDER_FILE_REQUIRED'
    if args.wave not in LEGACY_UNREGISTERED_WAVES:
        assert type(HTTP_ATTEMPT_LIMITS.get(args.wave)) is int and HTTP_ATTEMPT_LIMITS[args.wave] > 0, 'WAVE_HTTP_CAP_REQUIRED'
        assert type(INCREMENT_ATTEMPT_LIMITS.get(args.wave)) is int and INCREMENT_ATTEMPT_LIMITS[args.wave] > 0, 'WAVE_INCREMENT_CAP_REQUIRED'
        assert type(PHASE_ATTEMPT_LIMITS.get(args.wave)) is int and PHASE_ATTEMPT_LIMITS[args.wave] > 0, 'WAVE_PHASE_CAP_REQUIRED'
        registration = ROOT / ('.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/' + args.wave.lower() + '-registration.json')
        registered = json.loads(registration.read_text(encoding='utf-8'))
        assert registered['status'] == 'approved_after_offline_and_neo_review'
        assert registered['cases'] == WAVES[args.wave]
        assert registered['maximum_http_attempts_including_retries'] == wave_attempt_limit(args.wave)
        assert out == (ROOT / registered['live_output']).resolve(), 'REGISTERED_OUTPUT_REQUIRED'
        for filename, expected in registered['approved_source_sha256'].items():
            assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == expected, 'REGISTERED_SOURCE_CHANGED'
    services = load_mixed_services(args.env_file)
    ledger = ROOT / '.runs/full-chain-budget-20261014/token-budget.db'
    with sqlite3.connect(ledger.resolve().as_uri() + '?mode=ro', uri=True) as db:
        maximum, bounds = db.execute('SELECT maximum,bounds FROM authorization WHERE id=1').fetchone()
    assert maximum == 170000000, 'AUTHORIZATION_CHANGED'
    budget = TokenBudget(ledger, maximum, json.loads(bounds))
    auth = ROOT / '.analysis/agent-duty-validation-20261018/validation-budget-authorization.json'
    with FileLock(str(auth) + '.lock', timeout=0):
        data = json.loads(auth.read_text(encoding='utf-8'))
        baseline = ROOT / data['baseline_ledger_rows']
        assert isinstance(data['maximum_tokens'], int) and data['maximum_tokens'] > 0
        assert hashlib.sha256(baseline.read_bytes()).hexdigest() == data['baseline_sha256']
        phase = {'baseline': json.loads(baseline.read_text(encoding='utf-8')),
                 'maximum_tokens': data['maximum_tokens']}
        admission = base.phase_admission(phase['baseline'], base.ledger_rows(ledger), phase['maximum_tokens'],
                                         budget.model_bounds, attempts=wave_attempt_limit(args.wave),
                                         max_attempts=30 if args.wave in LEGACY_UNREGISTERED_WAVES else PHASE_ATTEMPT_LIMITS[args.wave])
        base.save(out / 'phase-admission.json', admission)
        return await run_wave(args, out, budget, phase, services)


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
