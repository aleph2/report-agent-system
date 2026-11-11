"""Probe safety through actual HTTP accounting and synthetic campaign ledgers."""
from concurrent.futures import ThreadPoolExecutor
import threading
from pathlib import Path
import pytest
import httpx
from report_agent import fake_verification as host
from report_agent.fake_verification_budget import FakeFlowBudget, FakeVerificationBudget
from report_agent.request_budget import RequestBudgetExceeded, account_request_sync
from report_agent.token_budget import token_budget, account_response_sync
from test_fake_verification_launcher import packet
from test_fake_fresh_comparison import pair


def flow(pair, cap=3_700_000):
    _,_,grant,comparison=pair
    return FakeFlowBudget(grant,'probe',{**comparison,'run_ids':['probe']},'a'*64,maximum_tokens=cap)


def send(budget, role='coordinator', used=10, provider=None):
    with token_budget(budget), httpx.Client(transport=httpx.MockTransport(provider or
            (lambda _:httpx.Response(200,json={'usage':{'total_tokens':used}}))),
            event_hooks={'request':[account_request_sync],'response':[account_response_sync]}) as client:
        return client.post('https://synthetic.invalid/chat/completions',json={'model':host.MODEL,'messages':[{'role':'user','content':role}]})


@pytest.mark.parametrize('cap,charges',[(3_700_000,[host.BOUND,host.BOUND,3_700_000-3*host.BOUND,host.BOUND]),
                                      (5_500_000,[host.BOUND]*3+[5_500_000-4*host.BOUND,host.BOUND])])
def test_all_roles_share_one_exact_run_cap_and_original_hold(pair,cap,charges):
    budget=flow(pair,cap); original=budget.snapshot()['reserved_or_unknown_upper_bounds']
    for role,used in zip(['coordinator','writer','reviewer','text_tool','coordinator'],charges):send(budget,role,used)
    assert budget.run_snapshot()=={'maximum_tokens':cap,'settled':cap,'held':0}
    assert budget.snapshot()['reserved_or_unknown_upper_bounds']==original==host.BOUND
    with pytest.raises(RequestBudgetExceeded):send(flow(pair,cap),provider=lambda _:pytest.fail('cap reached transport'))
    with pytest.raises(RequestBudgetExceeded):flow(pair,5_500_000 if cap==3_700_000 else 3_700_000).reserve(host.MODEL)


def test_one_request_in_flight_across_roles(pair):
    entered,release=threading.Event(),threading.Event();budget=flow(pair)
    def pending(_):
        entered.set();assert release.wait(10)
        return httpx.Response(200,json={'usage':{'total_tokens':10}})
    with ThreadPoolExecutor(max_workers=1) as pool:
        job=pool.submit(send,budget,provider=pending)
        try:
            assert entered.wait(10)
            with pytest.raises(RequestBudgetExceeded):send(flow(pair),'reviewer',provider=lambda _:pytest.fail('concurrent send'))
        finally:release.set()
        job.result()
    send(flow(pair),'writer')
    assert budget.run_snapshot()['settled']==20


@pytest.mark.parametrize('response',[False,True])
def test_unknown_outcome_stops_every_role_without_releasing_any_hold(pair,response):
    budget=flow(pair)
    def unknown(_):
        if response:return httpx.Response(200,json={})
        raise httpx.ReadError('synthetic lost outcome')
    if response:send(budget,provider=unknown)
    else:
        with pytest.raises(httpx.ReadError):send(budget,provider=unknown)
    for role in ['coordinator','writer','reviewer','text_tool']:
        with pytest.raises(RequestBudgetExceeded):send(flow(pair),role,provider=lambda _:pytest.fail('unknown replay'))
    assert budget.run_snapshot()['held']==host.BOUND
    assert budget.snapshot()['reserved_or_unknown_upper_bounds']==2*host.BOUND


@pytest.mark.parametrize('pair',[6],indirect=True)
def test_existing_campaign_cap_still_applies(pair):
    budget=flow(pair,5_500_000)
    send(budget,used=host.BOUND)
    send(budget,used=host.BOUND)
    with pytest.raises(RequestBudgetExceeded,match='AUTHORIZED_TOKEN_BUDGET_REACHED'):
        send(budget,provider=lambda _:pytest.fail('campaign cap reached transport'))
    assert budget.snapshot()['maximum_tokens']==10_000_000


def test_unselected_caps_and_authority_reuse_are_refused(pair):
    for cap in [True,3_700_001,10_000_000]:
        with pytest.raises(ValueError):flow(pair,cap)
    budget=flow(pair);send(budget)
    _,_,grant,c=pair
    other=FakeFlowBudget(grant,'probe',{**c,'run_ids':['probe']},'b'*64,maximum_tokens=3_700_000)
    with pytest.raises(RequestBudgetExceeded):other.reserve(host.MODEL)


@pytest.fixture
def planning_packet(pair,tmp_path):
    from report_agent import fake_planning_probe as probe
    from test_fake_verification_launcher import write_json
    path,data,grant,c=pair
    data.update(workflow=probe.WORKFLOW,model=host.MODEL,objects=['A','B'],proposed_exclusions=['C'],
                stop_at='page_sheet',answer_key_sha256=probe.identify()['answer_key_sha256'],
                run_id='probe',fresh_comparison={**c,'run_ids':['probe']})
    return path,write_json(path,data),data


def test_probe_authority_caps_scope_and_empty_preparation(planning_packet):
    from report_agent import fake_planning_probe as probe
    from test_fake_verification_launcher import write_json
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    path,pin,data=planning_packet
    for key,bad in [('stop_at','export'),('model','other'),('per_run_tokens',5_500_001),('objects',['A','B','C'])]:
        with pytest.raises(ValueError):probe.preflight(path,write_json(path,{**data,key:bad}))
    pin=write_json(path,data);prepared=probe.prepare(path,pin)
    cs=ContentStore(Store(Path(prepared['case_path'])))
    assert not cs.list_objects('CommissionPlan') and not cs.list_objects('CommissionDecision')
    assert not cs.list_objects('DelegatedTask')
    assert probe.check_prepared(path,pin,prepared['prepared_sha256'])==prepared


@pytest.mark.parametrize('scenario',['checkpoint','refusal','unknown','budget','writer','partial_sheet'])
async def test_probe_real_native_operator_reaches_owner_checkpoint_without_writer(planning_packet,tmp_path,monkeypatch,scenario):
    from report_agent import fake_planning_probe as probe,deep_models,model_config
    from report_agent.workspace import Workspace
    from report_agent.store import Store
    from report_agent.content_store import ContentStore
    from test_fake_draft_flow import coordinator_script
    from test_fake_verification_launcher import write_json
    from langchain_openai.chat_models.base import _convert_message_to_dict,_convert_dict_to_message
    from report_agent.tool_trace import summarize_trace
    path,_,data=planning_packet;url='https://offline.invalid/v1'
    env=tmp_path/'services.env';env.write_text('synthetic config only')
    sha=lambda value:__import__('hashlib').sha256(value.encode()).hexdigest()
    data['request_bound_proof']={'model':host.MODEL,'input_limit':1_048_576,'output_limit':131_072,
        'basis':'documented_model_ceiling_not_measured_request_fit','env_sha256':host._sha(env),
        'base_url_sha256':sha(url),'request_url_sha256':sha(url+'/chat/completions'),
        'sources':['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3']}
    pin=write_json(path,data);prepared=probe.prepare(path,pin)
    driver=None
    for suffix,value in {'MODEL':host.MODEL,'BASE_URL':url,'API_KEY':'synthetic'}.items():monkeypatch.setenv('REPORT_WRITER_'+suffix,value)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    monkeypatch.setattr(model_config,'load_mixed_services',lambda _:None)
    original=deep_models.configured_model;sent=[]
    async def provider(request):
        body=__import__('json').loads(request.content);sent.append(body)
        assert body['model']==host.MODEL
        if scenario=='unknown':raise httpx.ReadError('synthetic unknown delivery')
        assert not any('expected' in str(m) or 'answer-key' in str(m) for m in body['messages'])
        messages=[_convert_dict_to_message(m) for m in body['messages']]
        names={c['id']:c['name'] for m in messages for c in getattr(m,'tool_calls',[])}
        from langchain_core.messages import ToolMessage
        for m in messages:
            if isinstance(m,ToolMessage) and not m.name:m.name=names.get(m.tool_call_id)
        response=await driver.respond('coordinator',messages)
        message=_convert_message_to_dict(response.generations[0].message)
        return httpx.Response(200,json={'id':'offline-'+str(len(sent)),'object':'chat.completion','created':1,
            'model':host.MODEL,'choices':[{'index':0,'finish_reason':'tool_calls','message':message}],
            'usage':{'prompt_tokens':host.BOUND-4 if scenario=='budget' else 6,'completion_tokens':4,'total_tokens':host.BOUND if scenario=='budget' else 10}})
    def configured(store,role):
        nonlocal driver
        if driver is None:
            driver,_=coordinator_script(Workspace(store))
            if scenario=='refusal':
                from test_deep_runtime import invoke
                message=invoke('publish_planning_draft');message.tool_calls[0]['id']='probe-refusal'
                driver.scripts['coordinator'].insert(0,message)
        model=original(store,role);monkeypatch.setattr(model.http_async_client._transport,'handle_async_request',provider)
        return model
    monkeypatch.setattr(deep_models,'configured_model',configured)
    if scenario=='partial_sheet':
        from report_agent import fake_draft_flow,page_bindings,plan_authority
        async def early_question(ws,factory):return {'status':'needs_human'}
        monkeypatch.setattr(fake_draft_flow,'plan',early_question)
        monkeypatch.setattr(plan_authority,'plan_ref',lambda _:dict(type='CommissionPlan',id='partial',version=1))
        monkeypatch.setattr(page_bindings,'records',lambda *args:[({'id':'one-proposal'},{'status':'proposed'})])
        monkeypatch.setattr(page_bindings,'sheet_route',lambda *args:False)
        result=await probe.launch(path,pin,prepared['prepared_sha256'],env)
        assert result['status']=='other_human_checkpoint' and sent==[]
        return
    if scenario=='writer':
        from report_agent import fake_draft_flow
        async def forbidden(ws,factory):await factory('writer').ainvoke('not authorized')
        monkeypatch.setattr(fake_draft_flow,'plan',forbidden)
        with pytest.raises(RequestBudgetExceeded):await probe.launch(path,pin,prepared['prepared_sha256'],env)
        assert sent==[]
        return
    result=await probe.launch(path,pin,prepared['prepared_sha256'],env)
    if scenario in ('unknown','budget'):
        assert result['status']==('unknown_outcome_held' if scenario=='unknown' else 'budget_stop'),result
        assert len(sent)==(1 if scenario=='unknown' else 3)
        assert result['budget']['held']==(host.BOUND if scenario=='unknown' else 0)
        with pytest.raises(FileExistsError):await probe.launch(path,pin,prepared['prepared_sha256'],env)
        return
    expected=62 if scenario=='refusal' else 61
    assert result['status']=='page_sheet_checkpoint',result
    assert len(sent)==expected and result['budget']['settled']==expected*10 and result['budget']['held']==0
    assert result['campaign_budget']['reserved_or_unknown_upper_bounds']==host.BOUND
    assert len(result['page_bindings'])==22
    cs=ContentStore(Store(Path(prepared['case_path'])))
    assert not cs.list_objects('CommissionDecision') and not cs.list_objects('DelegatedTask')
    summary=summarize_trace(Path(prepared['case_path']).parent/'tool-trace.jsonl')
    assert summary['roles']['coordinator']['model_calls']==expected and summary['roles']['coordinator']['tool_rejections']==(1 if scenario=='refusal' else 0)
    assert summary['unattributed_tool_outcomes']==0
    with pytest.raises(FileExistsError):await probe.launch(path,pin,prepared['prepared_sha256'],env)
    assert len(sent)==expected


def test_accepted_writer_only_route_still_works_after_probe_guard_install(pair):
    from report_agent.fake_verification_budget import FakeComparisonBudget
    budget=flow(pair);send(budget)
    _,_,grant,c=pair
    legacy=FakeComparisonBudget(grant,'later-writer',{**c,'run_ids':['later-writer']},'b'*64,qualitative_only=True)
    send(legacy,'writer')
    assert legacy.run_snapshot()['settled']==10 and budget.run_snapshot()['settled']==10
    assert legacy.snapshot()['reserved_or_unknown_upper_bounds']==host.BOUND
