"""R3 configured-client adapter; the parent runner owns budgets and TCP policy.

One synthetic page observation and one independent artifact check. This module
never selects credentials, changes retry settings, retries a logical operation,
or starts an autonomous Reviewer loop. Offline mode replaces only HTTP transport.
"""
import base64
import hashlib
import json
from pathlib import Path

import httpx

from report_agent.deep_models import (
    MODEL_REQUEST_DEADLINE_SECONDS, configured_model, configured_vision_client,
    connection_retry_count,
)
from report_agent.request_budget import current_budget_observation
from report_agent.token_budget import current_token_observation
from duty_probe_visual_packets import (
    prepare_visual, perform_visual_and_artifact, perform_public_visual_and_artifact,
)


class ProbeHarnessError(RuntimeError):
    """A probe/observer failure must not be reported as an application defect."""


def _json_default(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    raise TypeError('Unsupported probe archive value: ' + type(value).__name__)


def _save(folder, name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                        default=_json_default), encoding='utf-8')


def _artifact_fixture(packet, *, include_note_column=False):
    """Legal synthetic answer derived from exact received identities/receipts."""
    if include_note_column:
        from test_duty_artifact_contrast import artifact_fixture
        return artifact_fixture(packet, note_present=True)
    requirements = packet['requirements']
    assert len(requirements) == 1
    requirement = requirements[0]
    evidence = packet['evidence']
    assert len(evidence) == 3
    assert evidence[2]['actual_observation']['source']['render_ref'] == requirement['artifact_refs'][0]
    return {'snapshot_ref': packet['snapshot_ref'], 'target_ref': packet['snapshot_ref'],
        'scope': 'Single synthetic page only', 'criteria_refs': [requirement['criterion_ref']],
        'dependency_refs': requirement['required_read_refs'], 'items': [{
            'target_ref': requirement['target_ref'], 'criterion_ref': requirement['criterion_ref'],
            'scope': 'Single page', 'scope_id': requirement['scope_id'], 'assessment_kind': 'render',
            'artifact_refs': requirement['artifact_refs'], 'execution_state': 'completed',
            'verdict': 'not_satisfied', 'checked_requirement_indexes': [0, 1],
            'observations': [{'locator': str(i), 'observation': text,
                'receipt_id': evidence[i]['receipt_id'],
                'limitations': 'Synthetic transport response does not validate model semantics.'}
                for i, text in enumerate([
                    'The saved table has Indicator, Class, Score columns and TEST-OBJECT/B/70.',
                    'The source requires Class B score 75 and a fourth Note column.',
                    'The actual page observation describes the three-column table and score 70.'])],
            'check_results': [{'requirement_index': i, 'execution_state': 'completed',
                'result': '70 differs from required 75.' if i == 0 else 'Required Note column absent.',
                'observation_indexes': [0, 1, 2], 'remaining': ''} for i in range(2)],
            'coverage': {'checked': ['score', 'columns'], 'unchecked': [], 'blocked': [],
                         'basis': 'Exact source and actual full-page observation receipt.'},
            'reason': 'Two synthetic discrepancies remain; no engineering acceptance.', 'findings': []}],
        'delivery_checks': [], 'coverage_accounting': []}


async def probe_visual_pair(ws, folder, live, *, case='visual-artifact-pair'):
    """Use inherited request/token contexts for both configured provider clients.

    One logical invocation per tool; SDK retries remain the configured sole
    transient recovery owner and consume the parent's shared HTTP budget.
    Response bodies are archived before accounting/parsing; no headers or keys.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if case not in {'visual-artifact-pair', 'visual-artifact-columns-complete'}:
        raise ProbeHarnessError('UNKNOWN_VISUAL_CASE')
    include_note_column = case == 'visual-artifact-columns-complete'
    result = {'case': case, 'mode': 'live' if live else 'offline',
        'intent': 'Synthetic actual-page observation plus scoped independent artifact I/O check.',
        'interface_boundary': ('Public Reviewer tools in native runtime with fake Coordinator/Reviewer decisions.'
            if include_note_column else 'Internal tool implementations under a real delegated Reviewer task.'),
        'fixture_contrast': 'Four columns, score conflict unchanged; both original required checks retained.'
            if include_note_column else 'Original three-column fixture.',
        'generated_actions_executed': False, 'automatic_logical_retry': False,
        'real_agent_actions_executed': False,
        'scripted_public_tool_actions_executed': include_note_column,
        'engineering_acceptance': False, 'semantic_acceptance': 'pending independent raw-response review',
        'budget_before': {'request': current_budget_observation(), 'token': current_token_observation()}}
    requests, responses, observer_errors, fixture_errors = [], [], [], []
    vision = model = None
    stage = 'configuration'

    def archive(name, value):
        try:
            _save(folder, name, value)
        except Exception as exc:
            observer_errors.append({'file': name, 'type': type(exc).__name__, 'message': str(exc)})
            return False
        return True

    def hook_pair(role):
        async def request_hook(request):
            raw = request.content
            entry = {'role': role, 'body_utf8': raw.decode('utf-8', errors='replace'),
                     'body_sha256': hashlib.sha256(raw).hexdigest()}
            try:
                entry['body'] = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                entry['json_parse_error'] = type(exc).__name__
            requests.append(entry)
            archive('wire-requests.json', requests)

        async def response_hook(response):
            # A real transport read failure propagates under the existing SDK
            # policy; an archive/JSON-observer error never triggers SDK retry.
            raw = await response.aread()
            entry = {'role': role, 'http_status': response.status_code,
                     'body': raw.decode('utf-8', errors='replace'),
                     'body_sha256': hashlib.sha256(raw).hexdigest()}
            responses.append(entry)
            archive('wire-responses.json', responses)
        return request_hook, response_hook

    try:
        if live and (result['budget_before']['request'] is None or result['budget_before']['token'] is None):
            raise ProbeHarnessError('PARENT_REQUEST_AND_TOKEN_BUDGETS_REQUIRED')
        vision = configured_vision_client()
        model = configured_model(ws.store, 'text_tool')
        result['configured_policy'] = {'vision_sdk_retries': vision.max_retries,
            'artifact_sdk_retries': model.root_async_client.max_retries,
            'httpx_connect_retries': connection_retry_count(),
            'logical_deadline_seconds': MODEL_REQUEST_DEADLINE_SECONDS,
            'artifact_model': model.model_name, 'artifact_output_limit': model.max_tokens}
        if (vision.max_retries != 5 or model.root_async_client.max_retries != 5
                or connection_retry_count() != 0 or MODEL_REQUEST_DEADLINE_SECONDS != 600):
            raise ProbeHarnessError('CONFIGURED_RETRY_OR_DEADLINE_POLICY_CHANGED')
        for role, client in [('vision', vision._client), ('artifact', model.http_async_client)]:
            request_hook, response_hook = hook_pair(role)
            client.event_hooks['request'].insert(0, request_hook)
            client.event_hooks['response'].insert(0, response_hook)
            if not live:
                async def transport(request, role=role):
                    try:
                        body = json.loads(request.content)
                        if role == 'vision':
                            content = ('Displayed rule says Class B uses 75. Table columns are Indicator, Class, Score, Note; '
                                'row TEST-OBJECT/B/70/Synthetic note. All four required columns are visible. Synthetic observation only.'
                                if include_note_column else
                                'Displayed rule says Class B uses 75. Table columns are Indicator, Class, Score; '
                                'row TEST-OBJECT/B/70. No Note column is visible. Synthetic observation only.')
                        else:
                            packet = json.loads(body['messages'][-1]['content'])
                            content = json.dumps(_artifact_fixture(packet, include_note_column=include_note_column))
                        return httpx.Response(200, json={'id': 'offline-r3-' + role,
                            'object': 'chat.completion', 'created': 1, 'model': body['model'],
                            'choices': [{'index': 0, 'finish_reason': 'stop',
                                         'message': {'role': 'assistant', 'content': content}}],
                            'usage': {'prompt_tokens': 19, 'completion_tokens': 1, 'total_tokens': 20}})
                    except Exception as exc:
                        fixture_errors.append({'role': role, 'type': type(exc).__name__, 'message': str(exc)})
                        # Invalid offline input is a harness error, never a
                        # simulated transient failure that would invoke retries.
                        return httpx.Response(400, headers={'x-should-retry': 'false'},
                            json={'error': {'message': 'OFFLINE_VISUAL_FIXTURE_ERROR', 'type': 'invalid_request_error'}})
                await client._transport.aclose()
                client._transport = httpx.MockTransport(transport)
                client._mounts = {}
        if not archive('intent.json', result):
            raise ProbeHarnessError('PROBE_INTENT_ARCHIVE_FAILED')
        stage = 'fixture_preparation'
        prepared = await prepare_visual(ws, folder, include_note_column=include_note_column)

        class ObservedArtifact:
            def __getattr__(self, key):
                return getattr(model, key)

            async def ainvoke(self, messages):
                if not archive('independent-input.json', messages):
                    raise ProbeHarnessError('ARTIFACT_INPUT_ARCHIVE_FAILED')
                answer = await model.ainvoke(messages)
                archive('model-output.json', answer.model_dump())
                return answer

        stage = 'tool_execution'
        execute = perform_public_visual_and_artifact if include_note_column else perform_visual_and_artifact
        execution = await execute(ws, prepared, folder,
            vision_client=vision, artifact_model=ObservedArtifact())
        result['tool_result'] = execution
        if execution.get('failure'):
            # Public ToolNode may return a typed error without raising. Preserve
            # that original failure instead of misclassifying a later None read.
            result.update(status='failed', failure_stage='tool_execution',
                failure_category='public_native_tool_failure_requires_diagnosis',
                error=execution['failure'])
            return result
        result['status'] = 'passed_structure'
        # Independent binding/identity checks do not reinterpret model prose.
        stage = 'observer_verification'
        result['receipt_binding'] = {
            'saved_review_actor_matches': execution['saved_review']['owner_id'] == execution['actor']['id'],
            'snapshot_matches': execution['saved_review']['payload']['snapshot_ref'] == prepared['snapshot'],
            'image_sha256': execution['vision']['result']['image_sha256']}
        vision_request = next(r['body'] for r in requests if r['role'] == 'vision' and 'body' in r)
        image_url = next(b['image_url']['url'] for b in vision_request['messages'][1]['content'] if b['type'] == 'image_url')
        sent_hash = hashlib.sha256(base64.b64decode(image_url.split(',', 1)[1], validate=True)).hexdigest()
        result['receipt_binding']['sent_image_matches'] = sent_hash == execution['vision']['result']['image_sha256']
        assert all(result['receipt_binding'][k] for k in ('saved_review_actor_matches', 'snapshot_matches', 'sent_image_matches'))
        if not live:
            assert len(requests) == len(responses) == 2
            assert execution['artifact_check_completed'] is True
            assert execution['saved_review']['payload']['items'][0]['verdict'] == 'not_satisfied'
    except Exception as exc:
        result.update(status='failed' if requests else 'blocked_before_http',
                      failure_stage=stage, error_type=type(exc).__name__, error=str(exc))
        result['failure_category'] = ('probe_harness' if isinstance(exc, ProbeHarnessError)
            else 'fixture_or_environment' if stage == 'fixture_preparation'
            else 'observer' if stage == 'observer_verification'
            else 'application_or_provider_requires_diagnosis')
    finally:
        for name, close in [('vision', vision.close if vision else None),
                            ('artifact_async', model.root_async_client.close if model else None)]:
            if close:
                try:
                    await close()
                except Exception as exc:
                    observer_errors.append({'cleanup': name, 'type': type(exc).__name__, 'message': str(exc)})
        if model:
            try:
                model.root_client.close()
            except Exception as exc:
                observer_errors.append({'cleanup': 'artifact_sync', 'type': type(exc).__name__, 'message': str(exc)})
        result.update(observed_http_requests=len(requests), observed_http_responses=len(responses),
            observed_request_note='Request hook entries include local admission attempts; the parent ledger determines reservations/usage.',
            observer_errors=observer_errors, offline_fixture_errors=fixture_errors,
            budget_after={'request': current_budget_observation(), 'token': current_token_observation()})
        if fixture_errors or observer_errors:
            result['underlying_status'] = result.get('status')
            result.update(status='probe_harness_failed', failure_category='offline_fixture' if fixture_errors else 'observer')
        _save(folder, 'result.json', result)
    return result
