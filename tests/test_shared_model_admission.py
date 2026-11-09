"""Native SDK admission/outcome contracts; no provider calls or report judgments."""
from report_agent import report_state
import asyncio
import json

import httpx
import openai
import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.deep_models import GLMChatOpenAI, model_async_client, model_sync_client
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.errors import ActionRejected
from report_agent.input_capacity import (CapacityProfile, InputTokenBounds,
    CapacityAdmissionRejected, evaluate_request, profile_for_service,
    bind_review_input_capacity, review_capacity, review_capacity_scope)
from report_agent.operation_receipts import operation_receipt
from report_agent.request_budget import logical_request_admission
from report_agent.store import Store
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.workspace import Workspace


URL = 'https://offline.invalid/v1'


def profile(lower=0, upper=None):
    return CapacityProfile('offline', URL, 100, 10, 'Controlled full-wire test bounds',
                           lambda payload: InputTokenBounds(lower, upper, 'Controlled test fixture'))


def response():
    return httpx.Response(200, json={'id': 'offline-response', 'object': 'chat.completion',
        'created': 1, 'model': 'offline', 'choices': [{'index': 0, 'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': '{"answer":"ok"}'}}],
        'usage': {'prompt_tokens': 3, 'completion_tokens': 2, 'total_tokens': 5}})


@pytest.mark.parametrize('lower,upper,status', [(1, 20, 'fit'), (99, None, 'known_exceeds'),
                                              (1, 9999, 'uncertain'), (0, None, 'uncertain')])
def test_full_request_bounds_not_bytes(lower, upper, status):
    decision = evaluate_request({'model': 'offline', 'max_tokens': 2,
        'messages': [{'role': 'user', 'content': 'x' * 100000}]},
        profile(lower, upper), wire_bytes=100000)
    assert decision['status'] == status
    assert decision['wire_utf8_bytes'] == 100000


def test_documented_service_keeps_uncertified_template_and_image_uncertainty():
    bound = profile_for_service('deepseek-v4.1-flash',
                                'https://fixture.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
    payload = {'model': bound.model_name, 'max_tokens': 65536, 'messages': [
        {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,large'}}]}]}
    decision = evaluate_request(payload, bound, wire_bytes=2000000)
    assert decision['context_tokens'] == 1000000 and decision['status'] == 'uncertain'
    assert decision['input_token_upper_bound'] is None
    payload['max_tokens'] = 393217
    assert evaluate_request(payload, bound, wire_bytes=10)['status'] == 'known_exceeds'


@pytest.mark.parametrize('sync', [False, True])
async def test_capacity_refusal_precedes_finance_and_never_sdk_retries(tmp_path, sync):
    store = Store(tmp_path / 'case')
    budget = TokenBudget(tmp_path / 'tokens.db', 1000, {'offline': 100})
    sent = []
    def handle(request):
        sent.append(request)
        return response()
    transport = model_sync_client(store, 'text_tool', capacity_profile=profile(99)) if sync else model_async_client(store, 'text_tool', capacity_profile=profile(99))
    transport._transport = httpx.MockTransport(handle)
    sdk = (openai.OpenAI if sync else openai.AsyncOpenAI)(api_key='offline', base_url=URL,
                                                       http_client=transport, max_retries=3)
    try:
        with token_budget(budget), logical_request_admission() as admission:
            with pytest.raises(CapacityAdmissionRejected) as caught:
                if sync:
                    sdk.chat.completions.create(model='offline', max_tokens=2,
                        messages=[{'role': 'user', 'content': 'Synthetic full request'}])
                else:
                    await sdk.chat.completions.create(model='offline', max_tokens=2,
                        messages=[{'role': 'user', 'content': 'Synthetic full request'}])
            proof = admission.not_dispatched_proof(caught.value)
        assert proof['admitted_http_attempts'] == 0 and proof['refused_before_send'] == 1
        assert not sent and budget.snapshot()['attempt_states'] == {}
        events = [e for e in store.events() if e['kind'] == 'model_capacity_admission']
        assert len(events) == 1
        assert 'Synthetic full request' not in json.dumps(events)
    finally:
        if sync:
            sdk.close()
        else:
            await sdk.close()


async def test_final_wire_large_material_tools_and_uncertainty_are_preserved(tmp_path):
    store = Store(tmp_path)
    seen = []
    transport = model_async_client(store, 'text_tool', capacity_profile=CapacityProfile('offline', URL))
    async def handle(request):
        seen.append(json.loads(request.content))
        assert request.extensions['report_capacity_admission']['status'] == 'uncertain'
        return response()
    transport._transport = httpx.MockTransport(handle)
    async with openai.AsyncOpenAI(api_key='offline', base_url=URL, http_client=transport, max_retries=0) as sdk:
        await sdk.chat.completions.create(model='offline', max_tokens=2,
            messages=[{'role': 'system', 'content': 'Original instructions'},
                      {'role': 'user', 'content': '测' * 70000}],
            tools=[{'type': 'function', 'function': {'name': 'original', 'strict': True,
                'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}])
    assert seen[0]['messages'][1]['content'] == '测' * 70000
    assert seen[0]['tools'][0]['function']['strict'] is True


async def test_later_refusal_cannot_mark_prior_admitted_sdk_attempt_unsent(tmp_path, monkeypatch):
    counts = []
    def measure(payload):
        counts.append(True)
        return InputTokenBounds(0 if len(counts) == 1 else 99, None, 'Controlled per-attempt bounds')
    bound = CapacityProfile('offline', URL, 100, 10, 'Fixture', measure)
    transport = model_async_client(Store(tmp_path / 'case'), 'text_tool', capacity_profile=bound)
    sent = []
    async def handle(request):
        sent.append(True)
        return httpx.Response(503, json={'error': {'message': 'Synthetic unavailable'}})
    transport._transport = httpx.MockTransport(handle)
    async with openai.AsyncOpenAI(api_key='offline', base_url=URL, http_client=transport, max_retries=3) as sdk:
        monkeypatch.setattr(sdk, '_calculate_retry_timeout', lambda *a: 0)
        with logical_request_admission() as admission:
            with pytest.raises(CapacityAdmissionRejected) as caught:
                await sdk.chat.completions.create(model='offline', max_tokens=2,
                    messages=[{'role': 'user', 'content': 'Synthetic'}])
            assert admission.not_dispatched_proof(caught.value) is None
        assert len(sent) == 1 and len(counts) == 2


async def test_legacy_constraint_same_owner_context_reset_and_no_database_migration(tmp_path):
    store = Store(tmp_path)
    store.initialize({'report_id': 'fixture', 'goal': 'Offline admission', 'sources': [{'id': 's', 'content': 'Synthetic', 'coverage': 'complete'}]})
    store.set('role_model_services', {'text_tool': {'model': 'offline', 'base_url': URL}})
    value = dict(version=1, report_id='fixture', case_root=str(store.root.resolve()),
        route='perform_assigned_review', service={'scheme': 'https', 'host': 'offline.invalid', 'port': None, 'path': '/v1'},
        model_name='offline', max_input_utf8_bytes=100, output_tokens=10,
        declared_context_tokens=1000, host_headroom_tokens=10, tokenizer_sha256='0'*64,
        provider_evidence='Historical fixture', authorization_record='Offline fixture')
    bind_review_input_capacity(store, value)
    old = store.get('review_input_capacity')
    transport = model_async_client(store, 'text_tool', capacity_profile=CapacityProfile('offline', URL))
    sent = []
    async def handle(request):
        sent.append(True)
        return response()
    transport._transport = httpx.MockTransport(handle)
    async with openai.AsyncOpenAI(api_key='offline', base_url=URL, http_client=transport, max_retries=3) as sdk:
        with review_capacity_scope(store, review_capacity(store)):
            await sdk.chat.completions.create(model='offline', max_tokens=2, messages=[
                {'role': 'system', 'content': 'System'}, {'role': 'user', 'content': 'x'*101}])
            audit = [e['data'] for e in store.events() if e['kind']=='model_capacity_admission'][-1]
            assert audit['legacy_constraint']['enforced'] is False
            assert audit['legacy_constraint']['input_utf8_bytes'] > value['max_input_utf8_bytes']
            assert audit['status'] == 'uncertain'
        # Context reset: same large material may proceed under the ordinary
        # uncertified service profile, rather than inheriting another route's cap.
        await sdk.chat.completions.create(model='offline', max_tokens=2,
            messages=[{'role': 'user', 'content': 'x'*101}])
    assert len(sent) == 2 and store.get('review_input_capacity') == old


async def test_raw_tool_timeout_receipt_owned_unknown_and_exact_replay_fenced(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Offline ownership', 'sources': [{'id': 's', 'content': 'Synthetic', 'coverage': 'complete'}]})
    ws = Workspace(store)
    actor = Actor('fixture-reviewer', 'reviewer', 'fixture-task')
    transport = model_async_client(store, 'text_tool', capacity_profile=CapacityProfile('offline', URL))
    sent = []
    async def handle(request):
        sent.append(True)
        raise httpx.ReadTimeout('Synthetic timeout', request=request)
    transport._transport = httpx.MockTransport(handle)
    model = GLMChatOpenAI(model='offline', api_key='offline', base_url=URL,
        http_async_client=transport, max_tokens=2, max_retries=0, use_responses_api=False)
    try:
        for caller in ('first', 'renamed'):
            with pytest.raises(ActionRejected, match='UNRESOLVED'):
                await analyze_evidence_packet(ws, model, {'task_id': actor.task_id, 'evidence': []},
                    'Synthetic exact instruction', 'fixture', reserve_attempt=True,
                    owner=actor, caller_operation_id=caller)
        receipt = operation_receipt(ContentStore(store), actor, 'first')
        attempt = receipt['model_attempts'][0]
        assert attempt['state'] == 'unknown' and attempt['usage'] is None
        assert attempt['failure_phase'] == 'transport_timeout' and not attempt['adoptable_result']
        assert attempt['model_call']['observed_attempts'][0]['response_complete'] is False
        other = Actor('other-reviewer', 'reviewer', 'other-task')
        assert operation_receipt(ContentStore(store), other, attempt['raw_operation'])['state'] == 'unknown'
        assert len(sent) == 1 and not ContentStore(store).list_objects('ReviewRecord')
    finally:
        await model.root_async_client.close()
        model.root_client.close()


async def test_host_decision_timeout_is_recovery_needed_without_automatic_resume(tmp_path):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    from langchain_core.messages import AIMessage
    store = Store(tmp_path)
    store.initialize({'goal': 'Offline timeout', 'content_contract': 'hierarchical-review-v1',
        'review_entrypoint': 'delegated-reviewer-v1', 'sources': [{'id': 's', 'content': 'Synthetic', 'coverage': 'complete'}]})
    store.set('knowledge_enabled', False)
    driver = Driver(coordinator=[AIMessage(content='Unreached')])
    driver.fail_once = ('coordinator', 0)
    await run_report(Workspace(store), driver)
    assert store.get('report_status') == 'needs_attention'
    assert store.get('report_error')['automatic_resume'] is False
    assert len(driver.calls) == 1 and report_state.selected_final_review(store) is None


@pytest.mark.parametrize('lower,status', [(101, 'known_exceeds'), (99, 'uncertain')])
def test_input_bound_without_output(lower, status):
    assert evaluate_request({'model': 'offline'}, profile(lower), wire_bytes=1)['status'] == status


@pytest.mark.parametrize('status', [408, 504, 429])
def test_received_http_error_is_not_local_timeout(status):
    from report_agent.model_invocation import is_model_timeout
    request = httpx.Request('POST', URL + '/chat/completions')
    error = openai.APIStatusError('received error', response=httpx.Response(status, request=request), body={})
    assert not is_model_timeout(error)


def test_unrelated_local_timeout_is_not_model_timeout():
    from report_agent.model_invocation import is_model_timeout
    assert not is_model_timeout(TimeoutError('Local file operation deadline'))


async def test_timeout_preserves_complete_http_and_recorded_usage_without_parsed_success(tmp_path):
    from test_bounded_review import Model
    store = Store(tmp_path)
    store.initialize({'goal': 'Offline outcomes', 'sources': [{'id': 's', 'content': 'Synthetic', 'coverage': 'complete'}]})
    actor = Actor('fixture-reviewer', 'reviewer', 'fixture-task')
    error = openai.APITimeoutError(request=httpx.Request('POST', URL))
    error.model_call_facts = {'observed_attempts': [{'attempt_id': 'physical-1',
        'response_complete': True, 'http_status': 200, 'accounting_state': 'settled', 'recorded_tokens': 123}]}
    with pytest.raises(ActionRejected, match='UNRESOLVED'):
        await analyze_evidence_packet(Workspace(store), Model(error), {'task_id': actor.task_id, 'evidence': []},
            'Synthetic instruction', 'fixture', reserve_attempt=True, owner=actor, caller_operation_id='first')
    receipt = operation_receipt(ContentStore(store), actor, 'first')['model_attempts'][0]
    assert receipt['http_body_complete'] is True and receipt['model_response_parsed'] is False
    assert receipt['recorded_usage_by_attempt'][0]['recorded_tokens'] == 123
    assert 'usage' not in receipt and not receipt['adoptable_result']
    assert receipt['state'] == 'unknown' and not ContentStore(store).list_objects('ReviewRecord')


async def test_deidentified_historical_74_material_shape_reaches_native_wire_intact(tmp_path):
    from pathlib import Path
    from collections import Counter
    shape = json.loads((Path(__file__).parent / 'fixtures/review_material_shape74.json').read_text())
    assert Counter(x['kind'] for x in shape['items']) == {'saved_object': 53, 'source_blocks': 14,
        'snapshot_structure': 1, 'source_version_binding': 6}
    materials = [{'kind': x['kind'], 'synthetic_id': f"fixture-{x['index']}",
        'text': f"BEGIN-{x['index']}-" + '合成资料' * (x['serialized_characters']//4 + 1) + f"-END-{x['index']}"}
        for x in shape['items']]
    packet = {'evidence': materials + [{'kind': 'saved_object', 'synthetic_id': f'requirement-{i}'} for i in range(2)],
        'assignment': {'review_requirements': [{'scope_id': f'fixture-scope-{i}',
            'required_checks': [f'Synthetic requirement {j}' for j in range(n)]} for i,n in enumerate(shape['scope_check_counts'])]}}
    text = json.dumps(packet,ensure_ascii=False)
    assert len(text)>64000 and len(packet['evidence']) == 76
    received = []
    def handle(request):
        payload=json.loads(request.content)
        assert json.loads(payload['messages'][0]['content']) == packet
        assert payload['max_tokens']==2
        received.append(request.extensions['report_capacity_admission']['status'])
        return response()
    transport=model_async_client(Store(tmp_path), 'text_tool', capacity_profile=CapacityProfile('offline', URL))
    transport._transport=httpx.MockTransport(handle)
    async with openai.AsyncOpenAI(api_key='offline',base_url=URL,http_client=transport,max_retries=0) as sdk:
        await sdk.chat.completions.create(model='offline',max_tokens=2,messages=[{'role':'user','content':text}])
    assert received==['uncertain']



def test_old_deadline_read_api_uses_shared_owner():
    from report_agent import deep_models, model_invocation
    assert deep_models.MODEL_REQUEST_DEADLINE_SECONDS == model_invocation.MODEL_REQUEST_DEADLINE_SECONDS == 600


async def test_native_capacity_refusal_becomes_tool_observation_and_writer_can_read(tmp_path):
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke
    from test_hierarchical_content import seed
    from test_text_work import writer_call
    from langchain_core.messages import AIMessage, ToolMessage
    store=Store(tmp_path/'case')
    store.initialize({'goal':'Synthetic capacity tool handling','content_contract':'hierarchical-review-v1',
        'review_entrypoint':'delegated-reviewer-v1','sources':[{'id':'s','content':'Class B permits 75 to 100.','coverage':'complete'}]})
    store.set('knowledge_enabled',False)
    ws=Workspace(store);cs,_,refs,_,_=seed(ws)
    original_nodes=cs.list_objects('ContentNode');sent=[]
    def handle(request):
        sent.append(True);return response()
    transport=model_async_client(store,'text_tool',capacity_profile=profile(99))
    transport._transport=httpx.MockTransport(handle)
    native=GLMChatOpenAI(model='offline',api_key='offline',base_url=URL,http_async_client=transport,
        max_tokens=2,max_retries=3,use_responses_api=False)
    seen=[]
    def see_refusal(messages):
        message=next(m for m in reversed(messages) if isinstance(m,ToolMessage))
        assert message.status=='error' and 'MODEL_CONTEXT_CAPACITY_REJECTED' in message.content
        assert 'not_dispatched' in message.content
        seen.append(message.content)
        return invoke('read_context',target_ref=refs['claim'])
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Limited result received.')],
        writer=[invoke('process_report_content',operation_id='local-capacity',objective='Synthetic selected content',
            object_type='ContentNode',input_refs=[refs['claim']]),see_refusal,AIMessage(content='Independent saved-content read completed; no new prose adopted.')])
    budget=TokenBudget(tmp_path/'tokens.db',1000,{'offline':100})
    try:
        with token_budget(budget):
            result=await deep_runtime.run_report(ws,lambda role:native if role=='text_tool' else driver(role))
        assert result['last_error'] is None and len(seen)==1 and not sent
        assert cs.list_objects('ContentNode')==original_nodes and not cs.list_objects('ReviewRecord')
        with budget.connect() as db:assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
        assert any(role=='writer' and any(isinstance(m,ToolMessage) and m.name=='read_context' for m in messages)
                   for role,_,messages in driver.calls)
    finally:
        await native.root_async_client.close();native.root_client.close()
