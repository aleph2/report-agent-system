"""Reserve real upper bounds in isolated fake-grant copies; never call a provider."""
import json
from pathlib import Path

import pytest

from report_agent import fake_verification as host
from report_agent.fake_verification_budget import FakeVerificationBudget, FakeContinuationBudget, FakeComparisonBudget
from report_agent.request_budget import RequestBudgetExceeded
from test_fake_verification_launcher import packet, write_json


@pytest.fixture
def pair(packet, request):
    path, _, data = packet
    grant = Path(data['grant_dir'])
    FakeVerificationBudget.initialize(grant, {host.MODEL: host.BOUND}, maximum_tokens=10_000_000)
    for i in range(getattr(request,'param',0)):
        earlier=FakeVerificationBudget(grant,'early-'+str(i))
        earlier.settle(earlier.reserve(host.MODEL),{'total_tokens':1_000_000})
    old_run = 'run-04'
    original = FakeVerificationBudget(grant, old_run)
    held = original.reserve(host.MODEL)
    retry = FakeContinuationBudget(grant, old_run, held)
    settled = retry.reserve(host.MODEL)
    retry.settle(settled, {'total_tokens':6114})
    history = grant/'runs'/old_run/'indicator-retry-result.json'
    history.parent.mkdir(parents=True)
    result = dict(run_id=old_run,old_attempt=held,indicator='X41',status='row_saved',scope_preserved=True,
                  seven_rows_preserved=True,old_hold_preserved=True,
                  retry_attempt=dict(id=settled,state='settled',reserved=host.BOUND,used=6114))
    comparison = dict(previous_run_id=old_run,previous_attempt=held,settled_retry_attempt=settled,
                      run_ids=['run-05a','run-05b'],retry_result_sha256=write_json(history,result))
    shared=grant/'comparison-receipts'
    shared.mkdir()
    history.rename(shared/(comparison['retry_result_sha256']+'.json'))
    data.update(run_id='run-05a',fresh_comparison=comparison)
    return path,data,grant,comparison


def test_admission_charges_old_hold_and_requires_one_exact_mapped_outcome(pair):
    path,data,grant,c=pair
    host.preflight(path,write_json(path,data))
    a=FakeComparisonBudget(grant,'run-05a',c,host._comparison_identity(data))
    a.check_fresh()
    first=a.reserve(host.MODEL)
    with pytest.raises(RequestBudgetExceeded):
        a.reserve(host.MODEL)
    a.settle(first,{'total_tokens':200})
    second=a.reserve(host.MODEL)
    a.settle(second,{'total_tokens':300})
    assert a.snapshot()['reserved_or_unknown_upper_bounds']==host.BOUND
    assert a.run_snapshot()['settled']==500
    with pytest.raises(RequestBudgetExceeded):
        a.check_fresh()
    with pytest.raises(RequestBudgetExceeded):
        FakeVerificationBudget(grant,'other').reserve(host.MODEL)
    with pytest.raises(RequestBudgetExceeded):
        FakeContinuationBudget(grant,'run-04',c['previous_attempt']).reserve(host.MODEL)
    wrong={**c,'settled_retry_attempt':'another-request'}
    with pytest.raises(RequestBudgetExceeded):
        FakeComparisonBudget(grant,'run-05a',wrong,host._comparison_identity(data)).reserve(host.MODEL)
    a.reserve(host.MODEL)  # simulate unknown delivery
    b=FakeComparisonBudget(grant,'run-05b',c,host._comparison_identity(data))
    with pytest.raises(RequestBudgetExceeded):
        b.check_fresh()
    with pytest.raises(RequestBudgetExceeded):
        b.reserve(host.MODEL)
    assert b.run_snapshot()['held']==0


def test_preflight_checks_named_run_and_pinned_successful_x41(pair):
    path,data,grant,c=pair
    for bad in [dict(run_ids=['run-05a','run-05a']),dict(previous_run_id='../escape'),
                dict(previous_attempt='another-request'),dict(retry_result_sha256='a'*64)]:
        with pytest.raises(ValueError):
            host.preflight(path,write_json(path,{**data,'fresh_comparison':{**c,**bad}}))
    with pytest.raises(ValueError):
        host.preflight(path,write_json(path,{**data,'run_id':'different'}))

def test_second_requires_same_treatment_and_successful_first_in_campaign(pair):
    path,data,grant,c=pair
    key=host._comparison_identity(data)
    a=FakeComparisonBudget(grant,'run-05a',c,key)
    b=FakeComparisonBudget(grant,'run-05b',c,key)
    a.settle(a.reserve(host.MODEL),{'total_tokens':240})
    terminal=dict(run_id=a.run_id,comparison_sha256=key,budget=a.run_snapshot(),finished_at_utc='2026-11-06')
    a.record_first_terminal({**terminal,'status':'interrupted'})
    with pytest.raises(RequestBudgetExceeded,match='FIRST_TERMINAL'):
        b.reserve(host.MODEL)
    a.record_first_terminal({**terminal,'status':'closed_with_gaps'})
    with pytest.raises(RequestBudgetExceeded,match='FIRST_TERMINAL'):
        FakeComparisonBudget(grant,b.run_id,c,'0'*64).check_fresh()
    b.check_fresh()
    b.settle(b.reserve(host.MODEL),{'total_tokens':241})
    assert b.snapshot()['reserved_or_unknown_upper_bounds']==host.BOUND


def test_durable_step_refusals_allow_independent_second_run_only_after_all_steps(pair):
    _,data,grant,c=pair
    key=host._comparison_identity(data)
    a=FakeComparisonBudget(grant,'run-05a',c,key)
    b=FakeComparisonBudget(grant,'run-05b',c,key)
    a.settle(a.reserve(host.MODEL),{'total_tokens':100})
    refused={'status':'interrupted: save rejected','refusals':[
        {'tool_call_id':'r1','code':'MESSAGE_FIELDS_INVALID'}, {'tool_call_id':'r2','code':'QUOTE_NOT_FOUND'}]}
    slopes=[
        {'object_id':'A','status':'incomplete','indicator_steps':{
            'progress':{'total':11,'recorded':10},'interrupted_indicators':{'X12':refused}}},
        {'object_id':'B','status':'closed_with_gaps','indicator_steps':{
            'progress':{'total':11,'recorded':11},'interrupted_indicators':{}}}]
    terminal=dict(run_id=a.run_id,comparison_sha256=key,budget=a.run_snapshot(),
                  finished_at_utc='2026-11-06',status='incomplete')
    a.record_first_terminal({**terminal,'slopes':slopes[:1]})
    with pytest.raises(RequestBudgetExceeded,match='FIRST_TERMINAL'):
        b.check_fresh()
    a.record_first_terminal({**terminal,'slopes':slopes})
    b.check_fresh()

@pytest.mark.parametrize('pair,charges,expected',[
    (0,3,'FAKE_RUN_TOKEN_LIMIT'), (6,2,'AUTHORIZED_TOKEN_BUDGET_REACHED')],indirect=['pair'])
def test_unchanged_limits_and_per_request_run_attribution(pair,charges,expected):
    _,data,grant,c=pair
    a=FakeComparisonBudget(grant,'run-05a',c,host._comparison_identity(data))
    issued=[]
    for _ in range(charges):
        request_id=a.reserve(host.MODEL)
        issued.append(request_id)
        a.settle(request_id,{'total_tokens':host.BOUND})
    with pytest.raises(RequestBudgetExceeded,match=expected):
        a.reserve(host.MODEL)
    with a.connect() as db:
        permits=db.execute('SELECT request_id,held_id,run_id FROM fake_comparison_requests').fetchall()
    assert permits==[(req,c['previous_attempt'],a.run_id) for req in issued]
    assert a.snapshot()['reserved_or_unknown_upper_bounds']==host.BOUND


@pytest.mark.asyncio
async def test_real_launch_pair_uses_same_verified_grant_and_independent_cases(pair,tmp_path,monkeypatch):
    import hashlib
    import httpx
    path,data,grant,c=pair
    env=tmp_path/'services.env'
    url='https://offline.invalid/v1'
    env.write_text('HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash-1017\n'
        f'HIGHWAY_MODEL_DEEPSEEK_BASE_URL={url}\nHIGHWAY_MODEL_DEEPSEEK_API_KEY=test\n'
        f'HIGHWAY_MODEL_NAME=glm-5.3\nHIGHWAY_MODEL_BASE_URL={url}\nHIGHWAY_MODEL_API_KEY=test\n')
    sha=lambda x:hashlib.sha256(x.encode()).hexdigest()
    data['request_bound_proof']={'model':host.MODEL,'input_limit':1_048_576,'output_limit':131_072,
        'basis':'documented_model_ceiling_not_measured_request_fit','env_sha256':host._sha(env),
        'base_url_sha256':sha(url),'request_url_sha256':sha(url+'/chat/completions'),
        'sources':['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3']}
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    calls=[]
    async def reply(self,request):
        assert request.url.host=='offline.invalid'
        calls.append(request)
        call={'id':f'row-{len(calls)}','type':'function','function':{'name':'save_gap',
              'arguments':json.dumps({'missing':'fixture test','question':'Clarify?'})}}
        message={'role':'assistant','content':None,'tool_calls':[call]}
        return httpx.Response(200,json={'id':'offline','object':'chat.completion','created':1,'model':host.MODEL,
            'choices':[{'index':0,'finish_reason':'tool_calls','message':message}],
            'usage':{'prompt_tokens':6,'completion_tokens':4,'total_tokens':10}})
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',reply)
    runs=[]
    for name in c['run_ids']:
        authority=path.with_name(name+'.json')
        pin=write_json(authority,{**data,'run_id':name})
        prepared=host.prepare(authority,pin)
        runs.append((authority,pin,prepared['prepared_sha256'],env))
    with pytest.raises(RequestBudgetExceeded,match='FIRST_TERMINAL'):
        await host.launch(*runs[1])
    assert not calls
    first=await host.launch(*runs[0])
    (grant/'runs'/c['run_ids'][0]).rename(tmp_path/'independent-finished-case')
    second=await host.launch(*runs[1])
    assert len(calls)==44
    assert first['plan_ref']!=second['plan_ref']
    assert first['budget']==second['budget']==dict(maximum_tokens=3_700_000,settled=220,held=0)
    assert first['comparison_sha256']==second['comparison_sha256']
    assert second['campaign_budget']['reserved_or_unknown_upper_bounds']==host.BOUND


def test_prepared_case_seal_keeps_nonempty_assertion_wal(tmp_path):
    (tmp_path / 'state.db').write_bytes(b'state')
    (tmp_path / 'assertions.sqlite3').write_bytes(b'assertions')
    sealed = host._seal(tmp_path)
    (tmp_path / 'assertions.sqlite3-shm').write_bytes(b'lock bookkeeping')
    wal = tmp_path / 'assertions.sqlite3-wal'
    wal.touch()
    assert host._seal(tmp_path) == sealed
    wal.write_bytes(b'committed pages')
    assert host._seal(tmp_path) != sealed
