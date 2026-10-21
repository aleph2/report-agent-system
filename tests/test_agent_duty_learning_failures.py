"""Learning-tool lifecycle and disposition CAS through actual Optimizer inputs.

Configured SDK + local MockTransport only. Budget refusal is a host stop, not an
ordinary agent observation. Raw-analysis completion is not typed learning success.
"""
import asyncio
from copy import deepcopy
import inspect
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import traceback

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from report_agent import deep_models
from report_agent.learning_runtime import build_optimizer
from report_agent.learning_text_work import LearningAnalysis
from report_agent.request_budget import RequestBudget, RequestBudgetExceeded, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_bounded_deadline import offline_model, close_model
from test_deep_runtime import Driver, invoke
from test_learning_text_work import case


def saved_state(ws):
    with ws.store.connect() as db:
        return {'reservations': {row[0]: json.loads(row[1]) for row in db.execute(
                    "SELECT key,value FROM state WHERE key LIKE 'bounded_review_attempt:%'")},
                'typed_analyses': {row[0]: json.loads(row[1]) for row in db.execute(
                    "SELECT key,value FROM state WHERE key LIKE 'learning_analysis:%'")},
                'raw_analyses': {row[0]: json.loads(row[1]) for row in db.execute('SELECT operation,data FROM analyses')}}


def retain(request, ws, observed, drivers):
    observed['state'] = saved_state(ws)
    observed['events'] = ws.store.events()
    observed['driver_calls'] = [[{'role': role, 'step': step, 'messages': messages_to_dict(messages)}
                                for role, step, messages in driver.calls] for driver in drivers]
    observed['driver_bindings'] = [driver.bindings for driver in drivers]
    observed['paid_calls'] = 0
    output = os.environ.get('REPORT_ARTIFACT_REPRO_OUT')
    if output:
        folder = Path(output) / re.sub(r'[^A-Za-z0-9_.-]', '_', request.node.name)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'evidence.json').write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding='utf-8')
        observed['evidence_directory'] = str(folder)
    request.node.user_properties.append(('learning_failure_evidence', json.dumps(observed, ensure_ascii=False)))


def tool_message(messages, name):
    # Middleware-generated errors may omit the optional name. Correlate with
    # the actual preceding model call identity, not an invented display field.
    ids = {call['id'] for m in messages if isinstance(m, AIMessage)
           for call in m.tool_calls if call['name'] == name}
    return next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.tool_call_id in ids)


async def run_optimizer_script(ws, driver, model):
    return await build_optimizer(ws, driver('optimizer'), text_model=model).ainvoke(
        {'messages': [('user', 'Inspect only assigned synthetic evidence; preserve failure and uncertainty, do not publish.')]},
        config={'recursion_limit': 16})


@pytest.mark.parametrize('failure', ['not_dispatched', 'deadline_unknown', 'received_invalid_structure'])
async def test_learning_analysis_lifecycle_reaches_native_optimizer_without_hidden_retry(case, monkeypatch, request, failure):
    await learning_lifecycle(case, monkeypatch, request, failure)


async def learning_lifecycle(case, monkeypatch, request, failure):
    ws, library, scope, feedback = case
    ws.store.set('learning_active_feedback', {'id': 'current-claim', 'feedback_ids': [feedback['id']]})
    model = offline_model(ws, monkeypatch)
    # Only the timeout probe shortens the real adapter-owned deadline. The
    # delayed MockTransport is entered first; no external cancellation is used.
    monkeypatch.setattr(deep_models, 'MODEL_REQUEST_DEADLINE_SECONDS', 1 if failure == 'deadline_unknown' else 600)
    tokens = TokenBudget(ws.store.root / 'probe-budget.db', 10000000, {'glm-5.3': 2000000})
    cap = RequestBudget(1)
    if failure == 'not_dispatched':
        cap.reserve()  # Synthetic pre-exhausted host allowance; no HTTP implied.
    observed = {'failure': failure, 'wire_requests': [], 'wire_responses': [],
                'cancelled_transport_calls': 0, 'next_optimizer_messages': [],
                'invalid_raw': '{"findings": {"not_a_string": true}, "project_fact": null}',
                'host_preexhausted_allowance': failure == 'not_dispatched'}

    async def transport(http_request):
        observed['wire_requests'].append(json.loads(http_request.content))
        if failure == 'deadline_unknown':
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                observed['cancelled_transport_calls'] += 1
                raise
        body = {'id': 'offline-invalid-learning', 'object': 'chat.completion', 'created': 1,
                'model': 'glm-5.3', 'choices': [{'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': observed['invalid_raw']}}],
                'usage': {'prompt_tokens': 19, 'completion_tokens': 1, 'total_tokens': 20}}
        observed['wire_responses'].append(body)
        return httpx.Response(200, json=body)

    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(transport)
    model.http_async_client._mounts = {}
    args = {'question': 'Compare the exact selected rule without inventing a result.',
            'feedback_selections': [{'feedback_id': feedback['id'], 'field': 'evidence'}]}
    def analysis_call(identity):
        message = invoke('analyze_learning_material', **args)
        message.tool_calls[0]['id'] = identity
        return message

    def next_step(messages):
        message = tool_message(messages, 'analyze_learning_material')
        observed['next_optimizer_messages'].append(message.model_dump())
        assert message.status == 'error', message
        state = saved_state(ws)
        assert not state['typed_analyses']
        if failure == 'deadline_unknown':
            assert 'EVIDENCE_ANALYSIS_OUTCOME_UNRESOLVED' in str(message.content)
            assert 'unknown' in str(message.content) and '"usage": null' in str(message.content)
        elif failure == 'received_invalid_structure':
            # ToolNode translates Pydantic errors to field/message text. An
            # internal Pydantic error code is not part of its public contract.
            assert 'findings' in str(message.content) and 'Input should be a valid string' in str(message.content)
            observed['invalid_structure_signal'] = {
                'actual_field_message_preserved': True,
                'received_response_explicit': 'raw_response_received' in str(message.content),
                'raw_operation_link_present': 'raw_operation' in str(message.content),
                'generic_tool_invocation_advice': 'Please fix the error and try again' in str(message.content)}
        else:
            assert 'EVIDENCE_ANALYSIS_NOT_DISPATCHED' in str(message.content)
        # A deliberately scripted second selection tests retained state; the
        # application must not issue another independent provider request.
        return analysis_call('analysis-second') if failure != 'not_dispatched' else AIMessage(content='Local admission refusal retained; no analysis available.')

    def finish(messages):
        message = tool_message(messages, 'analyze_learning_material')
        observed['next_optimizer_messages'].append(message.model_dump())
        assert message.status == 'error'
        expected = 'PREVIOUS_ATTEMPT_UNRESOLVED' if failure == 'deadline_unknown' else 'Input should be a valid string'
        assert expected in str(message.content)
        return AIMessage(content='Original failure retained; no learned fact or candidate.')

    driver = Driver(optimizer=[analysis_call('analysis-first'), next_step, finish])
    drivers = [driver]
    try:
        with token_budget(tokens), request_budget(cap):
            if failure == 'not_dispatched':
                with pytest.raises(RequestBudgetExceeded, match='MODEL_REQUEST_BUDGET_REACHED') as caught:
                    await run_optimizer_script(ws, driver, model)
                observed['host_stop'] = {'type': type(caught.value).__name__, 'message': str(caught.value)}
                assert len(driver.calls) == 1, 'Host budget refusal must not create another model turn.'
                assert not observed['wire_requests']
                observed['state_before_explicit_reentry'] = saved_state(ws)
                # Separate host test invocation, not automatic continuation or
                # budget reset: the same refused operation must remain refused.
                replay = Driver(optimizer=[analysis_call('explicit-refusal-inspection'), next_step])
                drivers.append(replay)
                await run_optimizer_script(ws, replay, model)
            else:
                await run_optimizer_script(ws, driver, model)
        state = saved_state(ws)
        reservation, = state['reservations'].values()
        if failure == 'not_dispatched':
            assert reservation['state'] == 'not_dispatched'
            assert reservation['admission_proof']['admitted_http_attempts'] == 0
            assert reservation['admission_proof']['refused_before_send'] == 1
            assert reservation['provider_outcome'] == 'not_dispatched'
            assert not reservation['raw_response_received']
            assert len(observed['wire_requests']) == len(observed['wire_responses']) == 0
            assert not state['raw_analyses']
            assert tokens.snapshot()['attempt_states'] == {'known_not_sent': 1}
        elif failure == 'deadline_unknown':
            assert reservation['state'] == 'unknown' and not reservation['raw_response_received']
            assert reservation['result']['provider_outcome'] == 'unknown' and reservation['result']['usage'] is None
            assert len(observed['wire_requests']) == observed['cancelled_transport_calls'] == 1
            assert not observed['wire_responses'] and not state['raw_analyses']
            assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 2000000
        else:
            # The shared layer records completed raw transport analysis before
            # the LearningAnalysis validator rejects its business structure.
            assert reservation['state'] == 'completed' and reservation['raw_response_received']
            raw, = state['raw_analyses'].values()
            assert raw['analysis'] == observed['invalid_raw']
            assert len(observed['wire_requests']) == len(observed['wire_responses']) == 1
            assert tokens.snapshot()['recorded_tokens'] == 20
        assert not state['typed_analyses']
        assert not library.list_versions(scope) and not library.search(scope)
        assert not ws.store.get('learning_job').get('feedback_dispositions')
    finally:
        observed['request_budget'] = cap.snapshot()
        observed['token_budget'] = tokens.snapshot()
        retain(request, ws, observed, drivers)
        await close_model(model)
    return observed


async def test_received_learning_output_error_is_not_attributed_to_valid_agent_arguments(case, monkeypatch, request):
    """Independent phase oracle; no required replacement error code/format."""
    import langgraph.prebuilt.tool_node as tool_node
    captured = []
    constructor = tool_node.ToolInvocationError.__init__

    def observe(self, tool_name, source, tool_kwargs, filtered_errors=None):
        constructor(self, tool_name, source, tool_kwargs, filtered_errors)
        if tool_name == 'analyze_learning_material':
            captured.append({'tool_name': tool_name, 'source_schema': source.title,
                'source_errors': source.errors(include_url=False), 'tool_kwargs': deepcopy(tool_kwargs),
                'formatted_message': self.message,
                'stack': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                          for f in traceback.extract_stack()[-20:]]})

    monkeypatch.setattr(tool_node.ToolInvocationError, '__init__', observe)
    observed = await learning_lifecycle(case, monkeypatch, request, 'received_invalid_structure')
    schemas = observed['driver_bindings'][0]['optimizer'][0]
    schema = next(s['parameters'] for s in schemas if s['name'] == 'analyze_learning_material')
    actual_calls = [call for turn in observed['driver_calls'][0] for message in turn['messages']
                   if message['type'] == 'ai' for call in message['data']['tool_calls']
                   if call['name'] == 'analyze_learning_material']
    args = actual_calls[0]['args']
    Draft202012Validator(schema).validate(args)
    assert 'findings' not in args
    with pytest.raises(ValidationError) as failure:
        LearningAnalysis.model_validate_json(observed['invalid_raw'])
    assert failure.value.errors()[0]['loc'] == ('findings',)
    assert len(observed['wire_requests']) == len(observed['wire_responses']) == 1
    assert observed['token_budget']['attempt_states'] == {'settled': 1}
    public_errors = [m['content'] for m in observed['next_optimizer_messages']]
    wrong_phase = [entry for entry in captured if entry['source_schema'] == 'LearningAnalysis'
                   and entry['tool_kwargs'] == args and entry['formatted_message'] in public_errors]
    framework = Path(inspect.getsourcefile(tool_node))
    attribution = {'input_schema_valid': True, 'actual_caller_args': args,
        'raw_response_received': True, 'output_schema_invalid': True,
        'registered_input_schema': schema, 'output_error': failure.value.errors(include_url=False),
        'tool_invocation_error_documented_meaning': tool_node.ToolInvocationError.__doc__,
        'framework': {'path': str(framework), 'sha256': hashlib.sha256(framework.read_bytes()).hexdigest(),
                      'langgraph_prebuilt_version': version('langgraph-prebuilt'),
                      'execute_tool_line': inspect.getsourcelines(tool_node.ToolNode._execute_tool_async)[1]},
        'actual_exception_constructions': captured, 'wrong_phase_records': wrong_phase,
        'oracle': 'A received invalid independent-model output must not be attributed to the already-valid agent call arguments.'}
    observed['phase_attribution'] = attribution
    if observed.get('evidence_directory'):
        folder = Path(observed['evidence_directory'])
        (folder / 'phase-attribution.json').write_text(json.dumps(attribution, ensure_ascii=False, indent=2), encoding='utf-8')
        (folder / 'framework-error-handler.py').write_text(inspect.getsource(tool_node.ToolNode._execute_tool_async)
            + '\n' + inspect.getsource(tool_node.ToolInvocationError), encoding='utf-8')
    request.node.user_properties.append(('learning_output_error_phase', json.dumps(attribution, ensure_ascii=False)))
    assert not wrong_phase, ('Received LearningAnalysis output validation was presented as invalid tool arguments, '
                             'although the actual agent arguments satisfy the registered input schema.', wrong_phase)


async def test_p18_native_disposition_rejects_job_identity_changed_between_read_and_write(case, monkeypatch, request):
    ws, library, scope, feedback = case
    ws.store.set('learning_active_feedback', {'id': 'old-claim', 'feedback_ids': [feedback['id']]})
    old_job = deepcopy(ws.store.get('learning_job'))
    new_job = {**old_job, 'id': 'new-job'}  # Change exactly the ID; retain state.
    observed = {'old_job': old_job, 'new_job': new_job, 'switches': 0}
    original_get = ws.store.get

    def read_then_switch(key, default=None):
        value = original_get(key, default)
        caller = inspect.currentframe().f_back
        if key == 'learning_job' and caller.f_code.co_name == 'record_feedback_disposition' and not observed['switches']:
            observed['captured_read'] = deepcopy(value)
            ws.store.set('learning_job', new_job)
            observed['switches'] += 1
        return value

    monkeypatch.setattr(ws.store, 'get', read_then_switch)

    def finish(messages):
        message = tool_message(messages, 'record_feedback_disposition')
        observed['next_optimizer_message'] = message.model_dump()
        assert message.status == 'error' and 'LEARNING_JOB_CHANGED' in str(message.content)
        assert ws.store.get('learning_job') == new_job
        return AIMessage(content='Job changed; no disposition written against the new job.')

    driver = Driver(optimizer=[invoke('record_feedback_disposition', feedback_id=feedback['id'],
        outcome='insufficient_evidence', rationale='Preserve this selected uncertainty.'), finish])
    try:
        await run_optimizer_script(ws, driver, None)
        assert observed['switches'] == 1 and observed['captured_read'] == old_job
        assert ws.store.get('learning_job') == new_job
        assert not any(e['kind'] == 'learning_feedback_disposition' for e in ws.store.events())
        assert not library.list_versions(scope)
    finally:
        retain(request, ws, observed, [driver])
