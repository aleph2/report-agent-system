"""Real SDK hooks and native checkpoint replay, with only an offline transport."""
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.bounded_operations import record_not_dispatched, reserve_once
from report_agent.content_store import ContentStore
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.request_budget import RequestBudget, RequestBudgetExceeded, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_bounded_deadline import offline_model, close_model
from test_deep_runtime import Driver, invoke, observation, snapshot
from test_task_supervision import ws
from test_text_work import content, writer_call


PROOF = {'origin': 'logical_request_admission_hook', 'admitted_http_attempts': 0,
         'refused_before_send': 1, 'provider_outcome': 'not_dispatched'}


def response(payload=None, total=20):
    return httpx.Response(200, json={
        'id': 'offline-response', 'object': 'chat.completion', 'created': 1,
        'model': 'glm-5.3', 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': json.dumps(payload or content())}}],
        'usage': {'prompt_tokens': total-1, 'completion_tokens': 1, 'total_tokens': total}})


def make_model(ws, monkeypatch):
    model = offline_model(ws, monkeypatch)
    monkeypatch.setattr('report_agent.deep_models.MODEL_REQUEST_DEADLINE_SECONDS', 600)
    return model


def test_linked_cas_is_atomic_idempotent_and_cannot_reclassify_unknown(ws):
    store = ws.store
    raw, parent = 'bounded_review_attempt:r', 'text_work:a:old'
    store.set(raw, {'state': 'reserved', 'operation': 'r'})
    store.set(parent, {'state': 'reserved', 'request_hash': 'h', 'actor': {'id': 'a'}})
    before = [store.get(raw), store.get(parent)]
    with pytest.raises(ValueError, match='CAS_FAILED'):
        record_not_dispatched(store, [(raw, {'operation': 'r'}),
            (parent, {'request_hash': 'wrong'})], PROOF)
    assert [store.get(raw), store.get(parent)] == before
    linked = [(raw, {'operation': 'r'}), (parent, {'request_hash': 'h', 'actor': {'id': 'a'}})]
    assert record_not_dispatched(store, linked, PROOF)
    assert not record_not_dispatched(store, linked, PROOF)
    assert len([e for e in store.events() if e['kind']=='bounded_operation_not_dispatched']) == 1
    store.set('unknown', {'state': 'unknown'})
    with pytest.raises(ValueError, match='CAS_FAILED'):
        record_not_dispatched(store, [('unknown', {})], PROOF)
    assert store.get('unknown') == {'state': 'unknown'}


def test_only_one_new_parent_can_readmit_raw_operation(ws):
    store = ws.store
    raw = 'bounded_review_attempt:r'
    store.set(raw, {'state': 'reserved', 'operation': 'r'})
    store.set('old', {'state': 'reserved', 'request_hash': 'h'})
    record_not_dispatched(store, [(raw, {'operation': 'r'}), ('old', {'request_hash': 'h'})], PROOF)
    assert reserve_once(store, raw, {'state': 'reserved', 'operation': 'r'},
        new_parent=('old', {'request_hash': 'h'}))['state'] == 'not_dispatched'
    for parent in ['new1', 'new2']:
        store.set(parent, {'state': 'reserved', 'request_hash': 'h'})
    def attempt(parent):
        return reserve_once(store, raw, {'state': 'reserved', 'operation': 'r'},
            new_parent=(parent, {'request_hash': 'h'}))
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, ['new1', 'new2']))
    assert sum(r is None for r in results) == 1
    assert store.get('old')['state'] == 'not_dispatched'
    assert len([e for e in store.events() if e['kind']=='bounded_operation_readmitted']) == 1


async def test_native_pending_refusal_replay_then_explicit_new_work_adopts_once(ws, monkeypatch, tmp_path):
    model = make_model(ws, monkeypatch)
    dispatched = []
    async def handle(request):
        dispatched.append(request)
        return response()
    model.http_async_client._transport = httpx.MockTransport(handle)
    budget = TokenBudget(tmp_path/'budget.db', 1, {'glm-5.3': 10000})
    args = dict(objective='Describe source', object_type='ContentNode', source_selections=[{'source_id':'s'}])
    def after_old(messages):
        assert not dispatched
        assert observation(messages, 'process_report_content')['code'] == 'TEXT_WORK_NOT_DISPATCHED'
        return invoke('process_report_content', operation_id='new-explicit-choice', **args)
    def after_new(messages):
        work = observation(messages, 'process_report_content')
        assert len(dispatched) == 1 and work['state'] == 'completed'
        return invoke('save_text_node', operation_id='adopt-new', text_work_id=work['text_work_id'])
    def after_adopt(messages):
        return invoke('get_operation_receipt', operation_id='old-pending')
    def after_receipt(messages):
        old = observation(messages, 'get_operation_receipt')['text_work']
        assert old['state']=='not_dispatched' and old['provider_outcome']=='not_dispatched'
        assert old['usage'] is None and not old['raw_response_received']
        assert old['admission_proof']['reason_code']=='AUTHORIZED_TOKEN_BUDGET_REACHED'
        assert old['admission_proof']['token_budget_at_refusal']['maximum_tokens']==1
        return AIMessage(content='Candidate adopted; original local refusal retained.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]), AIMessage(content='Done.')],
        writer=[invoke('process_report_content', operation_id='old-pending', **args),
                after_old, after_new, after_adopt, after_receipt])
    factory = lambda role: model if role=='text_tool' else driver(role)
    try:
        with token_budget(budget):
            stopped = await deep_runtime.run_report(ws, factory)
        assert stopped['status']=='failed' and not dispatched
        pending = await snapshot(ws, factory)
        assert pending.next
        events = [e['data'] for e in ws.store.events() if e['kind']=='bounded_operation_not_dispatched']
        assert len(events)==1 and len(events[0]['previous'])==2
        old_key = next(k for k in events[0]['previous'] if k.startswith('text_work:'))
        old = ws.store.get(old_key)
        assert old['state']=='not_dispatched'
        TokenBudget.increase_authorization(budget.path, previous_maximum=1, new_maximum=20000,
            authorization_id='offline-test', authorization_sha256='a'*64)
        budget = TokenBudget(budget.path, 20000, {'glm-5.3':10000})
        with token_budget(budget):
            completed = await deep_runtime.run_report(ws, factory)
        assert completed['last_error'] is None, completed
        assert len(dispatched)==1
        assert ws.store.get(old_key)==old
        nodes = ContentStore(ws.store).list_objects('ContentNode')
        assert len(nodes)==1 and nodes[0]['payload']==content()
        assert len([e for e in ws.store.events() if e['kind']=='evidence_analysis_input'])==1
        assert budget.snapshot()['recorded_tokens']==20
        assert budget.snapshot()['reserved_or_unknown_upper_bounds']==0
        assert not (await snapshot(ws, factory)).next
    finally:
        await close_model(model)


async def test_failed_diagnostic_read_cannot_replace_admission_refusal(ws, monkeypatch, tmp_path):
    model=make_model(ws,monkeypatch)
    dispatched=[]
    async def handle(request):
        dispatched.append(request)
        return response()
    model.http_async_client._transport=httpx.MockTransport(handle)
    budget=TokenBudget(tmp_path/'budget.db',1,{'glm-5.3':10000})
    def fail_snapshot():
        raise OSError('synthetic diagnostic read failure')
    monkeypatch.setattr(budget,'snapshot',fail_snapshot)
    try:
        with token_budget(budget),pytest.raises(RequestBudgetExceeded,match='AUTHORIZED_TOKEN_BUDGET_REACHED'):
            await analyze_evidence_packet(ws,model,{'evidence':[]},'offline','offline',reserve_attempt=True)
        event=next(e['data'] for e in ws.store.events() if e['kind']=='bounded_operation_not_dispatched')
        assert not dispatched
        assert event['proof']['reason_code']=='AUTHORIZED_TOKEN_BUDGET_REACHED'
        assert event['proof']['token_budget_at_refusal']=={'context_unavailable':True}
    finally:
        await close_model(model)


async def test_native_vision_local_refusal_replay_is_failed_observation_without_dispatch(ws,monkeypatch,tmp_path):
    from openai import AsyncOpenAI
    from report_agent.deep_models import model_async_client
    transport=model_async_client()
    await transport._transport.aclose()
    dispatched=[]
    def handle(request):
        dispatched.append(request)
        return response()
    transport._transport=httpx.MockTransport(handle)
    transport._mounts={}
    client=AsyncOpenAI(api_key='offline',base_url='https://offline.invalid/v1',http_client=transport,max_retries=5)
    monkeypatch.setenv('REPORT_VISION_MODEL','glm-5.3')
    monkeypatch.setattr('report_agent.vision.configured_vision_client',lambda:client)
    monkeypatch.setattr('report_agent.document_tools.vision_source_image',
        lambda workspace,source,page,crop:(b'offline-image',{'source_id':source,'page':page,'crop':crop}))
    def after_replay(messages):
        observed=observation(messages,'analyze_source_image')
        assert observed['status']=='failed' and observed['provider_outcome']=='not_dispatched'
        assert observed['reused'] and not observed['raw_response_received']
        assert observed['admission_proof']['reason_code']=='AUTHORIZED_TOKEN_BUDGET_REACHED'
        return AIMessage(content='Original vision request was refused locally.')
    driver=Driver(coordinator=[invoke('analyze_source_image',source_id='s',question='Read page'),after_replay])
    budget=TokenBudget(tmp_path/'budget.db',1,{'glm-5.3':10000})
    try:
        with token_budget(budget):
            first=await deep_runtime.run_report(ws,driver)
        assert first['status']=='failed' and not dispatched
        pending=await snapshot(ws,driver)
        assert pending.next and not pending.interrupts
        result=await deep_runtime.run_report(ws,driver)
        assert result['last_error'] is None and not dispatched
        assert not (await snapshot(ws,driver)).interrupts
    finally:
        await client.close()


def test_archived_input_collapses_only_identical_full_bindings(ws):
    from report_agent.operation_receipts import archived_input
    from report_agent.content_store import Actor
    from report_agent.store import digest
    actor=Actor('a','writer','t')
    record={'input':{'actor':actor.__dict__},'model':{'name':'offline'},'system_prompt':'p','operation':'r'}
    fingerprint=digest({'packet':record['input'],'model':record['model'],'prompt':'p'})
    ws.store.event('evidence_analysis_input',record)
    ws.store.event('evidence_analysis_input',record)
    with ws.store.connect() as db:
        assert archived_input(db,actor,fingerprint)==record
    ws.store.event('evidence_analysis_input',{**record,'operation':'conflict'})
    with ws.store.connect() as db:
        assert archived_input(db,actor,fingerprint) is None


@pytest.mark.parametrize('failure', ['settlement', 'retry_admission'])
async def test_budget_exception_after_an_admitted_attempt_stays_unresolved(ws, monkeypatch, tmp_path, failure):
    model = make_model(ws, monkeypatch)
    dispatched = []
    async def handle(request):
        dispatched.append(request)
        return response(total=10001) if failure=='settlement' else httpx.Response(500, json={'error':{'message':'offline'}})
    model.http_async_client._transport = httpx.MockTransport(handle)
    budget = TokenBudget(tmp_path/'budget.db', 20000, {'glm-5.3':10000})
    if failure == 'settlement':
        def fail_settlement(*args, **kwargs):
            raise OSError('synthetic ledger persistence failure')
        monkeypatch.setattr(budget, 'settle', fail_settlement)
    try:
        with token_budget(budget), request_budget(RequestBudget(1)):
            with pytest.raises(RequestBudgetExceeded):
                await analyze_evidence_packet(ws, model, {'evidence':[]}, 'offline', 'offline', reserve_attempt=True)
        assert len(dispatched)==1
        assert not any(e['kind']=='bounded_operation_not_dispatched' for e in ws.store.events())
        operation = next(e['data']['operation'] for e in ws.store.events() if e['kind']=='evidence_analysis_input')
        assert ws.store.get('bounded_review_attempt:'+operation)['state']=='reserved'
    finally:
        await close_model(model)
