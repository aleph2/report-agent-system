"""Native offline failure routing; no model quality or engineering-pass claim."""
import asyncio
import json

import httpx
import openai
import pytest
from langchain_core.exceptions import ContextOverflowError
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.content_store import Actor, ContentStore
from report_agent.deep_models import GLMChatOpenAI, error_data, model_async_client
from report_agent.errors import ActionRejected
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.input_capacity import (CapacityAdmissionRejected, CapacityHandlingRequired,
    CapacityProfile, capacity_failure, capacity_handling, capacity_response_received)
from report_agent.operation_receipts import operation_receipt
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.workspace import Workspace
from report_agent.working_summary import working_summary, SummaryRepairRequired
from test_bounded_review import Model
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_shared_model_admission import URL, profile, response
from test_text_work import writer_call


def local(reason='FULL_REQUEST_EXCEEDS_MODEL_CONTEXT'):
    return CapacityAdmissionRejected({'reason': reason, 'status': 'known_exceeds',
        'context_tokens': 100, 'requested_output_tokens': 2, 'input_token_lower_bound': 99,
        'wire_sha256': 'a'*64, 'private_prompt': 'PRIVATE', 'profile_evidence': 'SECRET'})


@pytest.mark.parametrize('reason,category', [
    ('FULL_REQUEST_EXCEEDS_MODEL_CONTEXT', 'local_capacity_exceeded'),
    ('REQUESTED_OUTPUT_EXCEEDS_MODEL_CAPACITY', 'local_capacity_exceeded'),
    ('TRUSTED_MODEL_PROFILE_MISMATCH', 'profile_binding_or_configuration'),
    ('TRUSTED_SERVICE_PROFILE_MISMATCH', 'profile_binding_or_configuration'),
    ('CAPACITY_CONFIGURATION_OR_MEASUREMENT_INVALID', 'profile_binding_or_configuration')])
def test_classification_and_handler_do_not_expose_private_payload(reason, category):
    facts = capacity_failure(local(reason))
    assert facts['category'] == category and facts['automatic_retry'] is False
    root = capacity_handling(facts, 'root_agent')
    assert root['handling_owner'] == ('maintenance' if 'configuration' in category else 'host_operator')
    assert root['fallback_available'] is False and root['automatic_resume'] is False
    assert capacity_handling(facts, 'tool')['handling_owner'] == 'calling_agent'
    assert capacity_handling(facts, 'delegated_agent')['handling_owner'] == 'parent_coordinator'
    assert 'PRIVATE' not in json.dumps(error_data(local(reason)))
    assert 'SECRET' not in json.dumps(error_data(local(reason)))


@pytest.mark.parametrize('status,body,recognized', [
    (400, {'code': 'context_length_exceeded'}, True),
    (413, {'error': {'code': 'context_length_exceeded'}}, True),
    (422, {'code': 'context_length_exceeded'}, True),
    (400, {'message': 'context_length_exceeded'}, False),
    (413, {}, False), (429, {'code': 'context_length_exceeded'}, False),
    (500, {'code': 'context_length_exceeded'}, False)])
def test_provider_classification_uses_structured_code_not_error_prose(status, body, recognized):
    error = openai.APIStatusError('PRIVATE maximum context length',
        response=httpx.Response(status, request=httpx.Request('POST', URL)), body=body)
    facts = capacity_failure(error)
    assert (facts is not None) is recognized
    if recognized:
        assert facts['failure_phase'] == 'provider_response' and facts['http_status'] == status
    assert 'PRIVATE' not in json.dumps(error_data(error))


def test_framework_exception_does_not_prove_provider_received_or_not_sent():
    facts = capacity_failure(ContextOverflowError('Private framework payload'))
    assert facts['failure_phase'] == 'framework_context_check' and facts['http_status'] is None
    assert 'provider_outcome' not in facts and 'admission_proof' not in facts
    assert capacity_failure(RuntimeError('context_length_exceeded')) is None


async def test_root_capacity_preserves_checkpoint_and_names_responsible_handler(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic root failure', 'content_contract': 'hierarchical-review-v1',
        'review_entrypoint': 'delegated-reviewer-v1',
        'sources': [{'id': 's', 'content': 'Synthetic original', 'coverage': 'complete'}]})
    store.set('knowledge_enabled', False)
    def refuse(messages):
        raise local()
    driver = Driver(coordinator=[refuse])
    await deep_runtime.run_report(Workspace(store), driver)
    assert store.get('report_status') == 'needs_attention'
    error = store.get('report_error')
    assert error['failure_kind'] == 'model_capacity_blocked'
    assert error['handling_owner'] == 'host_operator' and error['automatic_resume'] is False
    assert len(driver.calls) == 1 and (store.root/'checkpoints.db').exists()
    assert not ContentStore(store).list_objects('ReviewRecord')


@pytest.mark.parametrize('role', ['writer', 'reviewer'])
async def test_child_model_refusal_reaches_native_parent_without_success_or_extra_model_call(tmp_path, role):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic child refusal', 'content_contract': 'hierarchical-review-v1',
        'review_entrypoint': 'delegated-reviewer-v1',
        'sources': [{'id': 's', 'content': 'Class B permits 75 to 100.', 'coverage': 'complete'}]})
    store.set('knowledge_enabled', False)
    ws = Workspace(store)
    cs, _, refs, snapshot, _ = seed(ws)
    original_nodes = cs.list_objects('ContentNode')
    seen = []
    def inspect_parent(messages):
        msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'task')
        data = json.loads(msg.content)
        assert msg.status == 'error' and data['code'] == 'DELEGATED_CAPACITY_BLOCKED'
        assert data['completed'] is False and data['handling']['handling_owner'] == 'parent_coordinator'
        seen.append(data)
        return AIMessage(content='The delegated work remains blocked, not reviewed.')
    from test_bounded_review import review_call
    assignment = writer_call() if role == 'writer' else review_call(snapshot, refs)
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[assignment]), inspect_parent])
    sent = []
    transport = model_async_client(store, role, capacity_profile=profile(99))
    def handle(request):
        sent.append(request)
        return response()
    transport._transport = httpx.MockTransport(handle)
    native = GLMChatOpenAI(model='offline', api_key='offline', base_url=URL, http_async_client=transport,
        max_tokens=2, max_retries=5, use_responses_api=False)
    budget = TokenBudget(tmp_path/'tokens.db', 1000, {'offline': 100})
    try:
        with token_budget(budget):
            await deep_runtime.run_report(ws, lambda name: native if name == role else driver(name))
        assert len(seen) == 1 and not sent
        assert len([e for e in store.events() if e['kind']=='model_capacity_admission']) == 1
        assert budget.snapshot()['attempt_states'] == {}
        assert cs.list_objects('ContentNode') == original_nodes and not cs.list_objects('ReviewRecord')
    finally:
        await native.root_async_client.close()
        native.root_client.close()


@pytest.mark.parametrize('wrapped', [False, True])
async def test_received_provider_context_failure_has_owned_receipt_without_fake_notsent(tmp_path, wrapped):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic receipt', 'sources': [{'id': 's', 'content': 'Original', 'coverage': 'complete'}]})
    actor = Actor('fixture-reviewer', 'reviewer', 'fixture-task')
    error = openai.APIStatusError('PRIVATE', response=httpx.Response(400,
        request=httpx.Request('POST', URL)), body={'code': 'context_length_exceeded'})
    if wrapped:
        outer = ContextOverflowError('Framework reduction failed')
        outer.__cause__ = error
        error = outer
    with pytest.raises(ActionRejected, match='MODEL_CONTEXT_CAPACITY_REJECTED'):
        await analyze_evidence_packet(Workspace(store), Model(error), {'evidence': ['original']},
            'Original instruction', 'fixture', reserve_attempt=True, owner=actor, caller_operation_id='first')
    receipt = operation_receipt(ContentStore(store), actor, 'first')['model_attempts'][0]
    assert receipt['provider_outcome'] == 'response_received' and receipt['state'] == 'received_invalid'
    assert receipt['admission_proof'] is None and receipt['adoptable_result'] is False
    assert receipt['handling']['handling_owner'] == 'calling_agent'
    other = Actor('other', 'reviewer', 'other-task')
    assert operation_receipt(ContentStore(store), other, receipt['raw_operation'])['state'] == 'unknown'
    assert not ContentStore(store).list_objects('ReviewRecord')


async def test_vision_local_capacity_returns_same_actionable_owned_receipt(tmp_path, monkeypatch):
    from report_agent.vision import _observe
    monkeypatch.setenv('REPORT_VISION_MODEL', 'offline')
    store = Store(tmp_path/'case')
    transport = model_async_client(store, 'vision', capacity_profile=CapacityProfile('offline', URL, 100, 10))
    sent = []
    def handle(request):
        sent.append(request)
        return response()
    transport._transport = httpx.MockTransport(handle)
    actor = Actor('fixture-reader', 'writer', 'fixture-task')
    budget = TokenBudget(tmp_path/'tokens.db', 1000, {'offline': 100})
    async with openai.AsyncOpenAI(api_key='offline', base_url=URL, http_client=transport, max_retries=5) as client:
        with token_budget(budget):
            result = await _observe(store, b'synthetic', {'source_id': 's'}, 'Read only this image.', client, actor)
    assert result['provider_outcome'] == 'not_dispatched' and not sent
    assert result['handling']['handling_owner'] == 'calling_agent'
    assert result['capacity']['reason'] == 'REQUESTED_OUTPUT_EXCEEDS_MODEL_CAPACITY'
    owned = operation_receipt(ContentStore(store), actor, result['operation'])['model_attempts'][0]
    assert owned['capacity'] == result['capacity'] and owned['provider_outcome'] == 'not_dispatched'
    assert budget.snapshot()['attempt_states'] == {}


def test_saved_summary_failure_is_not_a_new_provider_response():
    prior = CapacityHandlingRequired({'reason': 'PROVIDER_CONTEXT_LENGTH_EXCEEDED', 'http_status': 400})
    assert capacity_failure(prior)['historical_failure'] is True
    assert capacity_response_received(prior) is False


async def test_recovery_keeps_actual_provider_capacity_response_without_extra_inference(tmp_path, monkeypatch):
    from test_model_recovery import active_model, use_mock, calls, close
    from report_agent.model_recovery import STATE_KEY
    store, native = await active_model(tmp_path, monkeypatch)
    sent = []
    def handle(request):
        sent.append(request)
        return httpx.Response(400, json={'error': {'code': 'context_length_exceeded', 'message': 'Synthetic oversized input'}})
    await use_mock(native, handle)
    budget = TokenBudget(tmp_path/'tokens.db', 200, {'deepseek-v4.1-flash-1017': 40})
    try:
        with token_budget(budget), pytest.raises(openai.APIStatusError):
            await native.ainvoke('Synthetic unchanged required material')
        saved = calls(store)[0]
        assert saved['provider_outcome'] == 'response_received' and saved['raw_response_received'] is True
        assert saved['state'] == 'capacity_blocked' and saved['raw']['status'] == 400
        assert store.get(STATE_KEY)['extra_calls'] == 0 and len(sent) == 1
        assert budget.snapshot()['reserved_or_unknown_upper_bounds'] == 40
    finally:
        await close(native)


async def test_summary_local_capacity_proof_and_saved_failure_survive_without_replay(tmp_path):
    store = Store(tmp_path/'case')
    store.initialize({'goal': 'Synthetic summary', 'sources': [{'id': 's', 'content': 'Original', 'coverage': 'complete'}]})
    transport = model_async_client(store, 'coordinator', capacity_profile=profile())
    sent = []
    def handle(request):
        sent.append(request)
        return response()
    transport._transport = httpx.MockTransport(handle)
    native = GLMChatOpenAI(model='offline', api_key='offline', base_url=URL, http_async_client=transport,
        max_tokens=2, max_retries=5, use_responses_api=False)
    summary = working_summary(native, store, role='coordinator')
    history = [HumanMessage('Preserve original requirement.'), AIMessage('Unverified hypothesis.')]
    budget = TokenBudget(tmp_path/'budget.db', 1000, {'offline': 100})
    try:
        with token_budget(budget), pytest.raises(CapacityAdmissionRejected):
            await summary._acreate_summary(history)
        saved = store.get(summary._failure_key())
        assert saved['reason'] == 'SUMMARY_NOT_DISPATCHED'
        assert saved['provider_outcome'] == 'not_dispatched' and saved['raw_response_received'] is False
        assert saved['capacity']['reason'] == 'REQUESTED_OUTPUT_EXCEEDS_MODEL_CAPACITY'
        with pytest.raises(SummaryRepairRequired) as caught:
            await summary._acreate_summary(history)
        assert capacity_failure(caught.value)['category'] == 'local_capacity_exceeded'
        assert store.get(summary._failure_key()) == saved and not sent
        assert budget.snapshot()['attempt_states'] == {} and len(history) == 2
    finally:
        await native.root_async_client.close()
        native.root_client.close()


async def test_platform_backoff_cancel_keeps_permission_consumed_and_no_second_dispatch(tmp_path, monkeypatch):
    from report_agent import model_recovery as recovery
    from report_agent.errors import ModelRequestDeadlineExceeded
    store = Store(tmp_path/'case')
    recovery.activate_recovery(store, authorization='Synthetic explicit policy')
    budget = TokenBudget(tmp_path/'budget.db', 1000, {'m': 40})
    entered = asyncio.Event()
    original_engine = recovery.AsyncRetrying
    def engine(**kwargs):
        async def sleep(delay):
            entered.set()
            await asyncio.Event().wait()
        return original_engine(sleep=sleep, **kwargs)
    monkeypatch.setattr(recovery, 'AsyncRetrying', engine)
    seen = []
    async def fail():
        seen.append(True)
        raise ModelRequestDeadlineExceeded(600)
    with token_budget(budget):
        task = asyncio.create_task(recovery.recover_model_call(store=store, role='coordinator',
            profile={'model': 'm'}, payload={'model': 'm'}, invoke=fail, parse_raw=lambda x: x))
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with store.connect() as db:
        calls = [json.loads(raw) for raw, in db.execute("SELECT value FROM state WHERE key LIKE 'model_recovery_call:%'")]
    assert seen == [True] and calls[0]['state'] == 'cancelled' and calls[0]['active'] is False
    assert calls[0]['ordinal'] == 1 and store.get(recovery.STATE_KEY)['extra_calls'] == 1
    assert budget.snapshot()['attempt_states'] == {}
