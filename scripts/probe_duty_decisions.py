"""Native decision probe adapter; Main owns admission, budgets and live launch.

The helper owns fixture construction, run_report and independent saved-state
oracles. This adapter never supplies a terminal live action or a repair/retry.
Offline uses the helper's explicitly scripted controls, not a provider call.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import probe_agent_io as base
from report_agent.deep_models import (
    MODEL_REQUEST_DEADLINE_SECONDS, configured_model, configured_vision_client, connection_retry_count,
)
from report_agent.request_budget import current_budget_observation
from report_agent.token_budget import current_token_observation
from test_bounded_deadline import close_model
from duty_probe_agent_decisions import CASES, capture_agent_decision

ADOPTION_CASE = 'writer-candidate-missing'
OPTIMIZER_CASE = 'optimizer-feedback-outcomes'
SINGLE_OPTIMIZER_CASE = 'optimizer-single-feedback'
THREE_OPTIMIZER_CASE = 'optimizer-three-feedback'
REVIEWER_CASES = {'reviewer-consumer-full': 'full', 'reviewer-consumer-missing': 'missing'}
SOURCE_CASES = {'writer-source-hit': 'literal-hit', 'writer-source-nohit': 'synonym-no-hit'}
COORDINATOR_CASE = 'coordinator-requirements'
REVISION_CASE = 'writer-revision-consumer'
COORDINATOR_OUTCOME_CASE = 'coordinator-review-outcome'
COORDINATOR_COMMISSION_CASE = 'coordinator-review-commission'
LAYOUT_OUTCOME_CASE = 'layout-current-document-outcome'
WRITER_DELIVERY_CASE = 'writer-current-paired-delivery'
REVIEWER_SOURCE_CASE = 'reviewer-current-source-investigation'
LAYOUT_COMPARISON_CASE = 'layout-local-paired-page-comparison'
WRITER_ANALYSIS_CASE = 'writer-independent-analysis'
ARTIFACT_ERROR_CASE = 'artifact-error-consumer'
GUIDANCE_CASES = {'writer-guidance-applicable': 'applicable',
                  'writer-guidance-inapplicable': 'inapplicable'}
MULTI_CASE = 'writer-multi-consumer'


def source_wire_observation(capture, requests, responses):
    """Count exact blocks only in requests with an observed successful response.

    Native middleware and request hooks run before local transport admission.
    Their prepared input is retained separately, never counted as received by a
    provider. Other legal retrieval paths require manual source/trace review.
    """
    answered = {r['request_sequence'] for r in responses if 200 <= r['http_status'] < 300}
    complete = []
    for request in requests:
        if request['role'] != 'writer' or request['sequence'] not in answered:
            continue
        blocks = {}
        for message in request.get('body', {}).get('messages', []):
            if message.get('role') != 'tool':
                continue
            content = message.get('content')
            try:
                packet = json.loads(content if isinstance(content, str) else content[-1]['text'])
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            if not isinstance(packet, dict):
                continue
            value = packet.get('metadata', packet)
            if isinstance(value, dict) and value.get('source', {}).get('id') == 'geo-g17':
                blocks.update({b['ordinal']: b for b in value.get('blocks', [])})
        if all(blocks.get(b['ordinal']) == b for b in capture['fixture']['expected_geology_blocks']):
            complete.append(request['sequence'])
    return {'prepared_complete_input_indexes': capture['oracle']['complete_block_input_indexes'],
            'response_linked_complete_wire_sequences': complete,
            'complete_blocks_in_response_linked_wire': bool(complete),
            'scope': 'Exact frozen read_source_page blocks/locators in observed successful-response requests only; no semantic acceptance. Other legal retrieval methods require independent review.'}


class DecisionProbeHarnessError(RuntimeError):
    """Configuration/observation defects are separate from native outcomes."""


async def probe_native_decision(ws, folder, case, live):
    """Execute one bounded native case under the caller's existing contexts.

Every live factory role retains its configured BaseChatModel and bind_tools.
The helper adds a passive native callback to those same adapters. Request hooks
archive complete bodies before local admission, so their count is not evidence
of dispatch; the existing parent transport/token ledgers remain authoritative.
"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    models, requests, responses, observer_errors, vision_clients = {}, [], [], [], []
    result = {
        'case': case, 'mode': 'live' if live else 'offline_fake_native',
        'intent': 'Run synthetic role decisions through native tools and inspect saved outcomes.',
        'generated_actions_executed': True, 'host_completes_model_work': False,
        'logical_case_auto_replay': False, 'engineering_acceptance': False,
        'acceptance_scope': 'finite_saved_state_only',
        'semantic_acceptance': 'pending Neo review of actual reasoning and limitations',
        'offline_limit': None if live else 'Scripted native control only; no provider or SDK transport validation.',
        'configured_models': [],
        'source_sha256': {str(p.relative_to(base.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (Path(__file__).resolve(), base.ROOT / 'tests/duty_probe_agent_decisions.py',
                                    base.ROOT / 'tests/duty_probe_writer_adoption.py',
                                    base.ROOT / 'tests/duty_probe_optimizer_outcome.py',
                                    base.ROOT / 'tests/duty_probe_optimizer_single.py',
                                    base.ROOT / 'tests/duty_probe_reviewer_consumer.py',
                                    base.ROOT / 'tests/duty_probe_source_continuation.py',
                                    base.ROOT / 'tests/duty_probe_coordinator_requirements.py',
                                    base.ROOT / 'tests/duty_probe_writer_revision_consumer.py',
                                    base.ROOT / 'tests/duty_probe_coordinator_review_outcome.py',
                                    base.ROOT / 'tests/duty_probe_coordinator_review_commission.py',
                                    base.ROOT / 'tests/duty_probe_layout_outcome.py',
                                    base.ROOT / 'tests/duty_probe_writer_delivery_outcome.py',
                                    base.ROOT / 'tests/duty_probe_reviewer_source_investigation.py',
                                    base.ROOT / 'tests/test_duty_reviewer_source_investigation.py',
                                    base.ROOT / 'tests/duty_probe_layout_comparison_outcome.py',
                                    base.ROOT / 'tests/test_duty_layout_comparison_outcome.py',
                                    base.ROOT / 'tests/test_duty_layout_comparison_adapter.py',
                                    base.ROOT / 'tests/duty_probe_writer_analysis_outcome.py',
                                    base.ROOT / 'tests/test_duty_writer_analysis_outcome.py',
                                    base.ROOT / 'tests/test_duty_writer_analysis_outcome_adapter.py',
                                    base.ROOT / 'tests/duty_probe_artifact_error_consumer.py',
                                    base.ROOT / 'tests/duty_probe_writer_guidance.py',
                                    base.ROOT / 'tests/duty_probe_writer_multi_consumer.py',
                                    base.ROOT / 'tests/duty_probe_optimizer_three.py')},
        'budget_before': {'request': current_budget_observation(), 'token': current_token_observation()},
        'status': 'preparing',
    }
    stage = 'admission'

    def archive(name, value):
        try:
            base.save(folder / name, value)
            return True
        except Exception as exc:
            observer_errors.append({'file': name, 'type': type(exc).__name__, 'message': str(exc)})
            return False

    def raw_archive(name, raw):
        try:
            (folder / name).write_bytes(raw)
        except Exception as exc:
            observer_errors.append({'file': name, 'type': type(exc).__name__, 'message': str(exc)})

    def hooks(role):
        async def request_hook(request):
            raw = request.content
            number = len(requests) + 1
            request.extensions['duty_decision_observation'] = number
            entry = {'sequence': number, 'role': role,
                     'body_sha256': hashlib.sha256(raw).hexdigest(),
                     'raw_file': f'wire-request-{number:04d}.json'}
            raw_archive(entry['raw_file'], raw)
            try:
                entry['body'] = json.loads(raw)
                entry['model'] = entry['body'].get('model')
            except Exception as exc:
                entry['body_utf8'] = raw.decode('utf-8', errors='replace')
                entry['json_observer_error'] = type(exc).__name__
                observer_errors.append({'phase': 'request_json', 'sequence': number,
                                        'type': type(exc).__name__, 'message': str(exc)})
            requests.append(entry)
            archive('wire-requests.json', requests)

        async def response_hook(response):
            # Preserve received bytes before the existing accounting/parser hooks.
            # Transport read exceptions propagate to the existing SDK policy;
            # archive/JSON observer errors never create a retry.
            raw = await response.aread()
            number = len(responses) + 1
            entry = {'sequence': number, 'role': role,
                     'request_sequence': response.request.extensions.get('duty_decision_observation'),
                     'http_status': response.status_code,
                     'body_sha256': hashlib.sha256(raw).hexdigest(),
                     'raw_file': f'wire-response-{number:04d}.json',
                     'body': raw.decode('utf-8', errors='replace')}
            raw_archive(entry['raw_file'], raw)
            try:
                parsed = json.loads(raw)
                entry['usage'] = parsed.get('usage') if isinstance(parsed, dict) else None
                entry['model'] = parsed.get('model') if isinstance(parsed, dict) else None
            except (ValueError, UnicodeError) as exc:
                # An invalid provider body is retained for diagnosis, not an
                # observer or caller-argument failure invented by this wrapper.
                entry['body_json_parse_error'] = type(exc).__name__
            responses.append(entry)
            archive('wire-responses.json', responses)
        return request_hook, response_hook

    def model_factory(role):
        if role in models:
            return models[role]
        model = configured_model(ws.store, role)
        models[role] = model  # Also close models whose policy validation fails.
        policy = {'role': role, 'model': model.model_name, 'output_limit': model.max_tokens,
                  'sdk_max_retries': model.root_async_client.max_retries,
                  'httpx_connect_retries': connection_retry_count(),
                  'logical_request_deadline_seconds': MODEL_REQUEST_DEADLINE_SECONDS}
        result['configured_models'].append(policy)
        if (policy['sdk_max_retries'] != 5 or policy['httpx_connect_retries'] != 0
                or policy['logical_request_deadline_seconds'] != 600):
            raise DecisionProbeHarnessError('CONFIGURED_RETRY_OR_DEADLINE_POLICY_CHANGED')
        request_hook, response_hook = hooks(role)
        model.http_async_client.event_hooks['request'].insert(0, request_hook)
        model.http_async_client.event_hooks['response'].insert(0, response_hook)
        archive('configured-models.json', result['configured_models'])
        return model

    def vision_factory():
        # Called only if the actual consumer selects a new visual observation.
        # Initial recorded preparation is handled separately by the fixture.
        client = configured_vision_client()
        vision_clients.append(client)
        policy = {'sdk_max_retries': client.max_retries,
                  'httpx_connect_retries': connection_retry_count(),
                  'logical_request_deadline_seconds': MODEL_REQUEST_DEADLINE_SECONDS}
        result.setdefault('configured_vision_clients', []).append(policy)
        if policy != {'sdk_max_retries': 5, 'httpx_connect_retries': 0,
                      'logical_request_deadline_seconds': 600}:
            raise DecisionProbeHarnessError('CONFIGURED_VISION_POLICY_CHANGED')
        request_hook, response_hook = hooks('vision')
        client._client.event_hooks['request'].insert(0, request_hook)
        client._client.event_hooks['response'].insert(0, response_hook)
        return client

    try:
        if case not in (*CASES, ADOPTION_CASE, OPTIMIZER_CASE, SINGLE_OPTIMIZER_CASE, THREE_OPTIMIZER_CASE, *REVIEWER_CASES, *SOURCE_CASES, COORDINATOR_CASE, REVISION_CASE, COORDINATOR_OUTCOME_CASE, COORDINATOR_COMMISSION_CASE, LAYOUT_OUTCOME_CASE, WRITER_DELIVERY_CASE, REVIEWER_SOURCE_CASE, LAYOUT_COMPARISON_CASE, WRITER_ANALYSIS_CASE, ARTIFACT_ERROR_CASE, *GUIDANCE_CASES, MULTI_CASE):
            raise DecisionProbeHarnessError('UNKNOWN_NATIVE_DECISION_CASE')
        if live and (result['budget_before']['request'] is None or result['budget_before']['token'] is None):
            raise DecisionProbeHarnessError('PARENT_REQUEST_AND_TOKEN_BUDGETS_REQUIRED')
        if not archive('intent.json', result):
            raise DecisionProbeHarnessError('PROBE_INTENT_ARCHIVE_FAILED')
        archive('wire-requests.json', requests)
        archive('wire-responses.json', responses)
        factory = model_factory
        selected_vision_factory = vision_factory
        if not live:
            if case == WRITER_ANALYSIS_CASE:
                from test_deep_runtime import Driver
                from langchain_core.messages import AIMessage
                from test_duty_writer_analysis_outcome import analysis_finding, writer_analysis_script
                finding = analysis_finding(True)
                factory = Driver(writer=writer_analysis_script(True, finding, {}),
                                 text_tool=[AIMessage(content=finding)])
            elif case == LAYOUT_COMPARISON_CASE:
                from test_deep_runtime import Driver
                from test_duty_layout_comparison_outcome import comparison_script, VISION_TEXT
                from test_vision import VisionModel
                comparison_services = []
                def fake_comparison_vision():
                    service = VisionModel(content=VISION_TEXT)
                    comparison_services.append(service)
                    return service
                selected_vision_factory = fake_comparison_vision
                factory = Driver(layout=[comparison_script(folder, False, {})] * 12)
            elif case == REVIEWER_SOURCE_CASE:
                from test_deep_runtime import Driver
                from test_duty_reviewer_source_investigation import CheckerCalibration, investigation_script
                driver = Driver(reviewer=[investigation_script(folder, True, {})] * 5)
                checker = CheckerCalibration()
                factory = lambda role: checker if role == 'text_tool' else driver(role)
            elif case == WRITER_DELIVERY_CASE:
                from test_deep_runtime import Driver
                from test_duty_writer_delivery_outcome import delivery_script
                factory = Driver(writer=delivery_script(folder, 'current', {}))
            elif case == LAYOUT_OUTCOME_CASE:
                from test_deep_runtime import Driver
                from test_duty_layout_outcome import layout_outcome_script, VISION_TEXT
                from test_vision import VisionModel
                service = VisionModel(content=VISION_TEXT)
                selected_vision_factory = lambda: service
                factory = Driver(layout=layout_outcome_script(folder, 'normal', {}))
            elif case in GUIDANCE_CASES:
                from test_deep_runtime import Driver
                from test_duty_writer_guidance import writer_guidance_script
                factory = Driver(writer=writer_guidance_script(GUIDANCE_CASES[case], {}))
            elif case == MULTI_CASE:
                from test_duty_writer_multi_consumer import multi_consumer_factory
                factory = multi_consumer_factory(True, {})
            elif case == COORDINATOR_COMMISSION_CASE:
                from test_deep_runtime import Driver
                from test_duty_coordinator_review_commission import commission_script
                factory = Driver(coordinator=commission_script(folder, 'both-objects', {}))
            elif case == COORDINATOR_OUTCOME_CASE:
                from test_deep_runtime import Driver
                from test_duty_coordinator_review_outcome import coordinator_outcome_script
                factory = Driver(coordinator=coordinator_outcome_script(ws, 'honest-negative', {}))
            elif case == ARTIFACT_ERROR_CASE:
                from test_duty_artifact_error_consumer import error_consumer_factory, HONEST
                factory = error_consumer_factory(HONEST, {})
            elif case == COORDINATOR_CASE:
                from test_deep_runtime import Driver
                from test_duty_coordinator_requirements import coordinator_requirements_script
                factory = Driver(coordinator=coordinator_requirements_script(ws, 'complete', {}))
            elif case == REVISION_CASE:
                from test_duty_writer_revision_consumer import revision_consumer_factory
                factory = revision_consumer_factory(True, {})
            elif case in SOURCE_CASES:
                from test_duty_source_continuation import source_consumer_factory
                factory = source_consumer_factory(SOURCE_CASES[case], False, {})
            elif case in REVIEWER_CASES:
                from test_deep_runtime import Driver
                from test_duty_reviewer_consumer import reviewer_script
                factory = Driver(reviewer=reviewer_script(ws, REVIEWER_CASES[case], {'folder': folder}))
            elif case == THREE_OPTIMIZER_CASE:
                from test_deep_runtime import Driver
                from test_duty_optimizer_three import three_optimizer_script
                factory = Driver(optimizer=three_optimizer_script(False, {}))
            elif case == SINGLE_OPTIMIZER_CASE:
                from test_deep_runtime import Driver
                from test_duty_optimizer_single import single_optimizer_script
                factory = Driver(optimizer=single_optimizer_script('candidate', {}))
            elif case == OPTIMIZER_CASE:
                from test_deep_runtime import Driver
                from test_duty_optimizer_outcome import optimizer_script
                # Driver indexes the full AI-message history, including the
                # prepared six-read action. Retain the full script coordinates;
                # the preparation already occupies slot 0 without a model call.
                factory = Driver(optimizer=optimizer_script('candidate-and-insufficient', {}))
            elif case == ADOPTION_CASE:
                from test_deep_runtime import Driver
                from test_duty_writer_adoption import consumer_scripts
                factory = Driver(writer=consumer_scripts('missing-adopt', {}))
            else:
                from test_duty_agent_decisions import fake_factory
                factory = fake_factory(ws, case, 'correct', {})
        stage = 'native_execution'
        if case == WRITER_ANALYSIS_CASE:
            from duty_probe_writer_analysis_outcome import capture_writer_analysis
            capture = await capture_writer_analysis(ws, folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['fixture']['limits'],
                          initial_parent_and_source_read_choices_are_fake=True,
                          originals_unchanged=capture['originals_unchanged'],
                          source_rows_unchanged=capture['source_rows_unchanged'],
                          catalog_sources_unchanged=capture['catalog_sources_unchanged'])
        elif case == LAYOUT_COMPARISON_CASE:
            from duty_probe_layout_comparison_outcome import capture_layout_comparison
            if live:
                capture = await capture_layout_comparison(ws, folder, factory,
                    vision_client_factory=selected_vision_factory)
            else:
                # The fake vision service has its own identity. This fixture
                # override is local, restored and never affects live clients.
                with patch.dict(os.environ, {'REPORT_VISION_MODEL': 'deepseek-v4.1-flash-1017'}):
                    capture = await capture_layout_comparison(ws, folder, factory,
                        vision_client_factory=selected_vision_factory)
                result['fake_vision_responses'] = sum(len(s.calls) for s in comparison_services)
                result['offline_fake_vision_model'] = 'deepseek-v4.1-flash-1017'
            result.update(capture_file='capture.json', fixture_limits=capture['fixture']['limits'],
                          initial_parent_and_pair_preparation_are_fake=True,
                          saved_export_refs=[r['ref'] for r in capture['objects'] if r['ref']['type'] == 'ExportArtifact'],
                          saved_render_refs=[r['ref'] for r in capture['objects'] if r['ref']['type'] == 'RenderArtifact'],
                          originals_unchanged=capture['originals_unchanged'])
        elif case == REVIEWER_SOURCE_CASE:
            from duty_probe_reviewer_source_investigation import capture_reviewer_source_investigation
            capture = await capture_reviewer_source_investigation(ws, folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['fixture']['limits'],
                          initial_parent_and_catalog_transition_are_fake=True,
                          saved_review_refs=[r['ref'] for r in capture['saved_reviews']],
                          saved_task_status=capture['task_status'], originals_unchanged=capture['originals_unchanged'])
        elif case == WRITER_DELIVERY_CASE:
            from duty_probe_writer_delivery_outcome import capture_writer_delivery_outcome
            capture = await capture_writer_delivery_outcome(ws, folder, factory,
                vision_client_factory=selected_vision_factory)
            result.update(capture_file='capture.json', fixture_limits=capture['fixture']['limits'],
                          initial_parent_and_original_read_choices_are_fake=True,
                          saved_snapshot_refs=[r['ref'] for r in capture['saved_snapshots']],
                          saved_export_refs=[r['ref'] for r in capture['saved_exports']],
                          consumer_finals=capture['finals'], originals_unchanged=capture['originals_unchanged'])
        elif case == LAYOUT_OUTCOME_CASE:
            from duty_probe_layout_outcome import capture_layout_outcome
            if live:
                capture = await capture_layout_outcome(ws, folder, factory,
                    vision_client_factory=selected_vision_factory)
            else:
                # A fake service retains its own identity. Configure only this
                # offline fixture's request to match, then restore caller env.
                with patch.dict(os.environ, {'REPORT_VISION_MODEL': service.returned_model}):
                    capture = await capture_layout_outcome(ws, folder, factory,
                        vision_client_factory=selected_vision_factory)
            result.update(capture_file='capture.json', fixture_limits=capture['fixture']['limits'],
                          initial_parent_and_original_read_choices_are_fake=True,
                          saved_export_refs=[r['ref'] for r in capture['saved_exports']],
                          saved_render_refs=[r['ref'] for r in capture['saved_renders']],
                          consumer_finals=capture['finals'], originals_unchanged=capture['originals_unchanged'])
            if not live:
                result['fake_vision_responses'] = len(service.calls)
                result['offline_fake_vision_model'] = service.returned_model
        elif case in GUIDANCE_CASES:
            from duty_probe_writer_guidance import capture_writer_guidance
            capture = await capture_writer_guidance(ws, GUIDANCE_CASES[case], folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limitations'],
                          initial_guidance_release_and_reads_are_fixtures=True,
                          declared_uses=capture['declared_uses'], consumer_finals=capture['finals'],
                          originals_unchanged=capture['originals_unchanged'])
        elif case == MULTI_CASE:
            from duty_probe_writer_multi_consumer import capture_writer_multi_consumer
            capture = await capture_writer_multi_consumer(ws, folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limits'],
                          initial_request_is_fake=True, initial_producer_is_recorded_fixture=False)
        elif case == COORDINATOR_COMMISSION_CASE:
            from duty_probe_coordinator_review_commission import capture_coordinator_review_commission
            capture = await capture_coordinator_review_commission(ws, case, folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limits'],
                          initial_original_reads_and_reviewer_are_fake=True,
                          saved_tasks=capture['saved_tasks'], saved_task_status=capture['saved_task_status'],
                          consumer_finals=capture['finals'], originals_unchanged=capture['originals_unchanged'])
        elif case == COORDINATOR_OUTCOME_CASE:
            from duty_probe_coordinator_review_outcome import capture_coordinator_review_outcome
            capture = await capture_coordinator_review_outcome(ws, 'honest-negative', folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limitations'],
                          initial_producer_and_assignment_are_fixtures=True,
                          historic_producer_usage_is_not_new_usage=True,
                          saved_review_refs=[r['ref'] for r in capture['saved_reviews']],
                          saved_task_status=capture['saved_task_status'], consumer_finals=capture['finals'])
        elif case == ARTIFACT_ERROR_CASE:
            from duty_probe_artifact_error_consumer import capture_artifact_error_consumer
            capture = await capture_artifact_error_consumer(ws, folder, factory,
                                                         vision_client_factory=vision_factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limits'],
                          initial_checker_and_vision_are_fixtures=True,
                          historic_producer_usage_is_not_new_usage=True,
                          fixture_vision_calls=capture['fixture_vision_calls'],
                          vision_routes=capture['vision_routes'])
        elif case == COORDINATOR_CASE:
            from duty_probe_coordinator_requirements import capture_coordinator_requirements
            capture = await capture_coordinator_requirements(ws, 'complete', folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limitations'],
                          initial_original_reads_are_fake=True,
                          saved_criteria_refs=[r['ref'] for r in capture['criteria']],
                          saved_tasks=capture['tasks'], consumer_finals=capture['finals'],
                          originals_unchanged=capture['originals_unchanged'])
        elif case == REVISION_CASE:
            from duty_probe_writer_revision_consumer import capture_writer_revision_consumer
            capture = await capture_writer_revision_consumer(ws, folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limits'],
                          initial_and_revision_producer_are_fixtures=True,
                          historic_producer_usage_is_not_new_usage=True,
                          fixture_producer_calls=sum(c['origin'] in {'initial', 'revision'} for c in capture['text_service_calls']),
                          later_text_calls=sum(c['origin'] not in {'initial', 'revision'} for c in capture['text_service_calls']))
        elif case in SOURCE_CASES:
            from duty_probe_source_continuation import capture_source_continuation
            capture = await capture_source_continuation(ws, SOURCE_CASES[case], folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limits'],
                          initial_query_is_scripted=True,
                          source_wire_observation=source_wire_observation(capture, requests, responses))
        elif case in REVIEWER_CASES:
            from duty_probe_reviewer_consumer import capture_reviewer_consumer
            capture = await capture_reviewer_consumer(ws, REVIEWER_CASES[case], folder, factory)
            result.update(capture_file='capture.json', fixture_limits=capture['limits'],
                          initial_producer_is_recorded_fixture=True,
                          historic_producer_usage_is_not_new_usage=True,
                          fixture_producer_calls=sum(c['origin'] == 'recorded_R1_fixture' for c in capture['checker_calls']),
                          later_checker_calls=sum(c['origin'] != 'recorded_R1_fixture' for c in capture['checker_calls']),
                          saved_review_refs=[r['ref'] for r in capture['saved_reviews']],
                          saved_task_status=capture['saved_task_status'],
                          consumer_semantic_status=capture['semantic_status'])
        elif case in (OPTIMIZER_CASE, SINGLE_OPTIMIZER_CASE, THREE_OPTIMIZER_CASE):
            if case == THREE_OPTIMIZER_CASE:
                from duty_probe_optimizer_three import capture_optimizer_three as capture_optimizer
            elif case == SINGLE_OPTIMIZER_CASE:
                from duty_probe_optimizer_single import capture_optimizer_single as capture_optimizer
            else:
                from duty_probe_optimizer_outcome import capture_optimizer_outcome as capture_optimizer
            capture = await capture_optimizer(ws, folder, factory, prepared_reads=True)
            result.update(capture_file='capture.json', assessment=capture['assessment'],
                          fixture_read_setup_is_fake=True, fixture_limits=capture['limits'],
                          model_client_policy=capture['model_client_policy'],
                          call_boundaries=[c['boundary'] for c in capture['native_model_calls']])
        elif case == ADOPTION_CASE:
            from duty_probe_writer_adoption import capture_writer_adoption
            # This selects the missing-material fixture, not the live Writer's action.
            capture = await capture_writer_adoption(ws, 'missing-adopt', folder, factory)
            result.update(capture_file='capture.json',
                          fixture_producer_calls=capture['fixture_producer_calls'],
                          later_text_calls=capture['later_text_calls'],
                          initial_producer_is_recorded_fixture=True,
                          historic_producer_usage_is_not_new_usage=True,
                          fixture_limits=capture['limits'])
        else:
            capture = await capture_agent_decision(ws, case, folder, factory)
            result['capture_file'] = 'agent-decision-capture.json'
        if case not in (OPTIMIZER_CASE, SINGLE_OPTIMIZER_CASE, THREE_OPTIMIZER_CASE, *REVIEWER_CASES, COORDINATOR_CASE, COORDINATOR_OUTCOME_CASE, COORDINATOR_COMMISSION_CASE, LAYOUT_OUTCOME_CASE, WRITER_DELIVERY_CASE, REVIEWER_SOURCE_CASE, LAYOUT_COMPARISON_CASE, WRITER_ANALYSIS_CASE, *GUIDANCE_CASES):
            result['oracle'] = capture['oracle']
        result['runtime_result'] = capture.get('runtime_result', capture.get('runtime'))
        result['raised_error'] = capture['raised_error']
        runtime_error = (result['runtime_result'] or {}).get('last_error')
        if capture['raised_error'] or runtime_error:
            result['status'] = 'native_execution_incomplete'
        elif case in (ADOPTION_CASE, OPTIMIZER_CASE, SINGLE_OPTIMIZER_CASE, THREE_OPTIMIZER_CASE, *REVIEWER_CASES, *SOURCE_CASES, COORDINATOR_CASE, REVISION_CASE, COORDINATOR_OUTCOME_CASE, COORDINATOR_COMMISSION_CASE, LAYOUT_OUTCOME_CASE, WRITER_DELIVERY_CASE, REVIEWER_SOURCE_CASE, LAYOUT_COMPARISON_CASE, WRITER_ANALYSIS_CASE, ARTIFACT_ERROR_CASE, *GUIDANCE_CASES, MULTI_CASE):
            # A saved node or handoff is an observation, not a semantic pass.
            result['status'] = 'native_observation_requires_review'
        elif capture['oracle']['status'] == 'finite_state_satisfied':
            result['status'] = 'passed_native_oracle'
        elif capture['oracle']['status'] == 'behavior_not_met':
            result['status'] = 'failed_native_oracle'
        else:
            result['status'] = capture['oracle']['status']
    except asyncio.CancelledError:
        result.update(status='interrupted', failure_stage=stage,
                      error_type='CancelledError', provider_outcome='consult existing reservations and raw responses')
        raise
    except Exception as exc:
        result.update(status='probe_harness_failed' if isinstance(exc, DecisionProbeHarnessError)
                      else 'native_capture_failed', failure_stage=stage,
                      error_type=type(exc).__name__, error=str(exc),
                      failure_category='probe_harness' if isinstance(exc, DecisionProbeHarnessError)
                      else 'application_or_fixture_requires_diagnosis')
    finally:
        for role, model in models.items():
            try:
                await close_model(model)
            except Exception as exc:
                observer_errors.append({'phase': 'cleanup', 'role': role,
                                        'type': type(exc).__name__, 'message': str(exc)})
                # close_model closes async then sync; preserve sync cleanup even
                # if the first close failed. This never creates a new client.
                try:
                    model.root_client.close()
                except Exception as sync_exc:
                    observer_errors.append({'phase': 'cleanup_sync', 'role': role,
                                            'type': type(sync_exc).__name__, 'message': str(sync_exc)})
        for client in vision_clients:
            try:
                if not client.is_closed():
                    await client.close()
            except Exception as exc:
                observer_errors.append({'phase': 'cleanup', 'role': 'vision',
                                        'type': type(exc).__name__, 'message': str(exc)})
        after = {'request': current_budget_observation(), 'token': current_token_observation()}
        before_request, after_request = result['budget_before']['request'], after['request']
        admitted = (after_request['reserved_http_attempts'] - before_request['reserved_http_attempts']
                    if before_request is not None and after_request is not None else
                    0 if not live and not models else None)
        result.update(observed_request_hook_entries=len(requests), observed_http_responses=len(responses),
                      admitted_http_attempts=admitted, observed_http_requests=admitted,
                      count_origin='request_budget_reserved_delta' if before_request is not None and after_request is not None else 'offline_no_configured_clients' if not live and not models else 'unavailable',
                      observed_http_requests_not_dispatch_proof=True,
                      admitted_without_observed_response=None if admitted is None else max(0, admitted - len(responses)),
                      hook_entries_without_admission=None if admitted is None else max(0, len(requests) - admitted),
                      observer_errors=observer_errors,
                      request_count_limit='observed_http_requests is a compatibility alias for parent reserved-attempt delta, not proof of network send. Hook entries can include local refusal; admitted attempts without a response may be unsent or unknown. Preserve the parent ledger states.',
                      budget_after=after)
        if observer_errors:
            result['underlying_status'] = result['status']
            result.update(status='probe_harness_failed', failure_category='observer')
        base.save(folder / 'result.json', result)
    return result
