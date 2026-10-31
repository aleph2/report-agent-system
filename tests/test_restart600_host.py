"""Exercise the exact candidate host factories with actual SDK + MockTransport."""
import json
import os
import runpy
import socket
from pathlib import Path

import httpx
import openai
import pytest

from report_agent.content_store import Actor
from report_agent.learning import LearningLibrary
from report_agent.model_recovery import activate_recovery, recovery_owner
from report_agent.store import Store
from report_agent.token_budget import TokenBudget
from test_transport_observation import body, close, use_mock


@pytest.mark.parametrize('fatal_mode',[None,'direct_auth','wrapped_auth','wrapped_ledger'])
async def test_exact_host_allows_post_failure_work_and_protects_independent_budget(tmp_path,monkeypatch,fatal_mode):
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    from report_agent import deep_runtime,vision
    root=Path(__file__).resolve().parents[1]
    candidate=root/'scripts/report_host.py'
    ns=runpy.run_path(str(candidate),run_name='offline_host_proof')
    state=ns['run'].__globals__
    here=tmp_path/'run';here.mkdir();case=here/'case';inputs=here/'inputs';inputs.mkdir()
    for i in range(state['CONFIG']['input_file_count']):(inputs/f'input-{i}.md').write_text('Synthetic source only',encoding='utf-8')
    for name,value in [('HERE',here),('CASE',case),('INPUT',inputs),('SOURCE',root),
                       ('LEDGER',tmp_path/'finance/new/token-budget.db'),('CANONICAL',tmp_path/'canonical/token-budget.db'),
                       ('LOCK',tmp_path/'shared.lock'),('ENV',here/'fixture.env')]:
        monkeypatch.setitem(state,name,value)
    state['ENV'].write_text('HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash-1017\n'
        'HIGHWAY_MODEL_DEEPSEEK_BASE_URL=https://offline.invalid/v1\n'
        'HIGHWAY_MODEL_DEEPSEEK_API_KEY=offline-only\n'
        'HIGHWAY_MODEL_NAME=glm-5.3\nHIGHWAY_MODEL_BASE_URL=https://offline.invalid/v1\n'
        'HIGHWAY_MODEL_API_KEY=offline-only\nREPORT_REASONING_EFFORT=high\n',encoding='utf-8')
    for suffix in ['MODEL','BASE_URL','API_KEY']:monkeypatch.delenv('REPORT_LAYOUT_'+suffix,raising=False)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    monkeypatch.setenv('LANGSMITH_TRACING','false')
    def denied(*args,**kwargs):pytest.fail('Host verification cannot open a network socket')
    monkeypatch.setattr(socket.socket,'connect',denied)
    bounds={m:2_000_000 for m in set(state['ROLE_MODELS'].values())}
    prior=TokenBudget(state['CANONICAL'],200_000_000,bounds)
    held=prior.reserve('glm-5.3')
    settled=prior.reserve('glm-5.3');prior.settle(settled,{'total_tokens':123})
    old=state['canonical_baseline']()
    budget=TokenBudget(state['LEDGER'],state['LIMIT'],bounds)
    store=Store(case);store.initialize({'goal':'Synthetic independent host recovery proof',
        'sources':[{'id':'s','title':'Synthetic source','content':'Offline test source only.','coverage':'complete'}]})
    LearningLibrary(case/'experience-library')
    policy=activate_recovery(store,authorization='desktop-20261031-start-600s-first-plus-two',
        extra_per_call=2,extra_per_case=None,extra_token_ceiling=None,backoff_seconds=0)
    endpoints=state['endpoint_pins']()
    prepared={'host_sha256':state['sha'](candidate),'source_pins':state['source_pins'](),
        'input_hashes':state['input_files'](),'state_sha256':state['sha'](store.path),
        'library_sha256':state['sha'](case/'experience-library/state.db'),
        'canonical_baseline':old,'endpoint_pins':endpoints,'recovery_policy':policy}
    state['save'](here/'prepared.json',prepared)
    state['save'](here/'neo-approval.json',{'approved':True,'host_sha256':state['sha'](candidate),
        'prepared_sha256':state['sha'](here/'prepared.json'),'synthetic_only':True})
    sends=[];models=[];clients=[]
    async def scripted(workspace):
        # These are the host's real guarded factories installed by run(), not a parallel test factory.
        co=deep_runtime.configured_model(workspace.store,'coordinator');models.append(co)
        def first(request):
            sends.append(('co',request))
            if sum(k=='co' for k,_ in sends)<3:raise httpx.ReadTimeout('offline',request=request)
            return httpx.Response(200,json=body('deepseek-v4.1-flash-1017'))
        await use_mock(co,first)
        assert (await co.ainvoke('Initial request recovers on attempt three')).content=='unchanged result'
        client=vision.configured_vision_client();clients.append(client)
        def no_vision(request):
            sends.append(('vision',request));raise httpx.ReadTimeout('offline',request=request)
        client._client._transport=httpx.MockTransport(no_vision);client._client._mounts={}
        observed=await vision._observe(workspace.store,b'fixture',{'source_id':'s','page':1,'sha256':'a'*64},
            'fixture question',client,Actor('writer','writer','task'))
        assert observed['status']=='failed'
        assert len([x for x in sends if x[0]=='vision'])==3
        # Exhausted vision + preserved holds must not trip a blanket global host latch.
        assert (await co.ainvoke('Independent decision after visual failure')).content=='unchanged result'
        for role in ['writer','reviewer','layout','text_tool','rubric_grader']:
            model=deep_runtime.configured_model(workspace.store,role);models.append(model)
            def respond(request,role=role):
                sends.append((role,request));return httpx.Response(200,json=body(state['ROLE_MODELS'][role]))
            await use_mock(model,respond)
            with recovery_owner(workspace.store,Actor(role,role,'task-'+role),'operation-'+role):
                assert (await model.ainvoke('Pure inference '+role)).content=='unchanged result'
        if fatal_mode:
            from report_agent.deep_models import error_data
            from report_agent.request_budget import RequestBudgetExceeded
            def fatal(request):
                sends.append(('fatal',request))
                cause=(RequestBudgetExceeded('TOKEN_LEDGER_SETTLEMENT_FAILED') if fatal_mode=='wrapped_ledger'
                    else openai.AuthenticationError('offline auth failure',response=httpx.Response(401,request=request),body={}))
                if fatal_mode=='direct_auth':raise cause
                raise openai.APIConnectionError(request=request) from cause
            await use_mock(co,fatal)
            with pytest.raises(Exception) as raised:
                await co.ainvoke('Fatal identity or ledger failure')
            assert error_data(raised.value)['message']==('TOKEN_LEDGER_SETTLEMENT_FAILED'
                if fatal_mode=='wrapped_ledger' else 'MODEL_AUTHENTICATION_FAILED')
            assert len([x for x in sends if x[0]=='fatal'])==1
            with pytest.raises(Exception) as blocked:
                await co.ainvoke('This request must be locally refused after fatal error')
            assert error_data(blocked.value)['message']=='HOST_TECHNICAL_FAILURE_PENDING'
            assert len([x for x in sends if x[0]=='fatal'])==1
        workspace.store.set('report_status','needs_attention')
        return {'synthetic_protocol_only':True}
    monkeypatch.setattr(deep_runtime,'run_report',scripted)
    try:
        await ns['run']()
    finally:
        for model in models:await close(model)
        for client in clients:await client.close()
    assert len(sends)==(13 if fatal_mode else 12)
    assert all(request.extensions['timeout']['read']==600 for _,request in sends)
    snapshot=budget.snapshot()
    assert snapshot['attempt_states']['reserved']==(6 if fatal_mode else 5)
    assert snapshot['attempt_states']['settled']==7
    assert snapshot['reserved_or_unknown_upper_bounds']==(12_000_000 if fatal_mode else 10_000_000)
    assert budget.snapshot()['recorded_tokens']==70
    assert state['canonical_baseline']()==old
    assert prior.snapshot()['reserved_or_unknown_upper_bounds']==2_000_000
    assert prior.snapshot()['recorded_tokens']==123
    assert (here/'cleanup.json').is_file()
    assert json.loads((here/'result.json').read_text())['report_status']=='needs_attention'
