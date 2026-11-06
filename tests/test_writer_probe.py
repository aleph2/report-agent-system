"""Offline trusted-operator proof and no-replay checks."""
import hashlib
import json
from pathlib import Path
import pytest
from report_agent.writer_probe import verified_request_bound, refusal_rows


def sha(value):
    return hashlib.sha256(value).hexdigest()


def proof(env, url):
    return {'model': 'glm-5.3', 'input_limit': 1_048_576, 'output_limit': 131_072,
            'env_sha256': sha(env.read_bytes()), 'base_url_sha256': sha(url.rstrip('/').encode()),
            'request_url_sha256': sha((url.rstrip('/')+'/chat/completions').encode()),
            'basis': 'documented_model_ceiling_not_measured_request_fit',
            'sources': ['https://docs.z.ai/guides/llm/glm-5.3',
                        'https://help.aliyun.com/zh/model-studio/glm-5-3']}


def test_verified_full_model_ceiling_matches_final_sdk_request_url(tmp_path):
    env=tmp_path/'env';env.write_text('synthetic')
    p=proof(env,'https://synthetic.invalid/v1/')
    bound=verified_request_bound(p,env,'glm-5.3','https://synthetic.invalid/v1/')
    assert bound.total==1_179_648
    assert bound.proof_sha256==sha(json.dumps(p,sort_keys=True,separators=(',',':')).encode())


@pytest.mark.parametrize('change', [dict(model='other'),dict(input_limit=200_000),
    dict(output_limit=65_536),dict(base_url_sha256='0'*64),dict(request_url_sha256='0'*64),
    dict(env_sha256='0'*64),dict(basis='estimated_prompt'),dict(sources=[])])
def test_changed_proof_refused_before_model_or_ledger(tmp_path,change):
    env=tmp_path/'env';env.write_text('synthetic')
    p=proof(env,'https://synthetic.invalid/v1');p.update(change)
    with pytest.raises(ValueError,match='PROBE_REQUEST_PROOF_INVALID'):
        verified_request_bound(p,env,'glm-5.3','https://synthetic.invalid/v1')


def test_refusals_dedupe_native_call_and_omit_private_fields():
    from langchain_core.messages import ToolMessage
    m=ToolMessage(json.dumps({'ok':False,'code':'GRADE_UNKNOWN','message':'PRIVATE_QUOTE',
                             'diagnostic':{'private':'PRIVATE_REASON'}}),
                  name='set_indicator',tool_call_id='call-one',status='error')
    result=refusal_rows([m,m])
    assert result==[{'tool':'set_indicator','tool_call_id':'call-one','code':'GRADE_UNKNOWN'}]
    assert 'PRIVATE' not in str(result)


# Integrated tests use real configured GLM/SDK admission and fresh local fixtures.
import httpx
from report_agent import writer_probe as probe
from report_agent.assessment_completion import read_finance
from report_agent.probe_case import prepare_probe_case
from report_agent.token_budget import TokenBudget
from report_agent.store import Store
from report_agent.content_store import ContentStore
from test_m1_g3_integration import method_commission
from test_m1_commission_plan import save, approve


@pytest.fixture
def prepared_probe(method_commission, tmp_path_factory, monkeypatch):
    f = method_commission
    f.plan['objects'][0].update(object_id='HP-02-K9023p670-L', label='HP02 synthetic slope')
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract':'system-assembler-v1'})
    if 'Owner rank order: B, A, D, C.' in f.ws.store.manifest['goal']:
        from test_writer_indicator_outcomes import attach_ranks
        attach_ranks(f)
    saved = save(f); approve(f, saved)
    root = tmp_path_factory.mktemp('writer-probe')
    case, evidence, env = root/'case', root/'evidence', root/'synthetic.env'
    evidence.mkdir()
    imported = prepare_probe_case(f.ws.store.root, case, expected_plan_ref=saved['plan_ref'],
                                 expected_decision_ref=f.ws.store.get('commission_confirmation'))
    url = 'https://synthetic.invalid/v1'
    env.write_text('\n'.join([
        'HIGHWAY_MODEL_NAME=glm-5.3', 'HIGHWAY_MODEL_BASE_URL='+url,
        'HIGHWAY_MODEL_API_KEY=synthetic-key',
        'HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash',
        'HIGHWAY_MODEL_DEEPSEEK_BASE_URL=https://synthetic-deepseek.invalid/v1',
        'HIGHWAY_MODEL_DEEPSEEK_API_KEY=synthetic-key',
        'REPORT_REASONING_EFFORT=high',
    ]))
    # Record loader-owned environment keys with monkeypatch so its actual writes restore.
    for role in ('', 'COORDINATOR_', 'REVIEWER_', 'TEXT_TOOL_', 'VISION_', 'RUBRIC_GRADER_', 'GRADER_DIAGNOSTIC_', 'WRITER_'):
        for key in ('MODEL','BASE_URL','API_KEY'):
            monkeypatch.setenv('REPORT_'+role+key, 'synthetic-placeholder')
    for key in ('REPORT_COORDINATOR_REASONING_EFFORT','REPORT_REVIEWER_REASONING_EFFORT','REPORT_GRADER_MODEL'):
        monkeypatch.delenv(key, raising=False)
    for key,value in {'REPORT_REASONING_EFFORT':'high','REPORT_SDK_RETRIES':'0',
        'REPORT_CONNECT_RETRIES':'2','REPORT_DEEPSEEK_STRICT':'0',
        'LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false'}.items():
        monkeypatch.setenv(key,value)
    ledger = root/'tokens.db'
    budget = TokenBudget(ledger,20_000_000,{'glm-5.3':2_000_000})
    original = read_finance(ledger)
    prior = budget.reserve('glm-5.3')
    budget.settle(prior, {'total_tokens':1_000_000})
    hold_id = budget.reserve('glm-5.3')
    stage = read_finance(ledger)
    hold = next(r for r in stage['rows'] if r[0]==hold_id)
    authority = {'hard_probe_tokens':2_200_000,'investigation_threshold_tokens':1_000_000,
        'overall_rescue_tokens':20_000_000,
        'preserve_unknown_hold_tokens':2_000_000,'no_other_slopes_cleanup_export_or_model_tests':True}
    (evidence/'owner-authority.json').write_text(json.dumps(authority))
    inputs = {'import_sha256':sha((case/'probe-import.json').read_bytes()),
        'authority_sha256':sha((evidence/'owner-authority.json').read_bytes()),
        'ledger':str(ledger),'stage_baseline':stage,'original_baseline':original,
        'preserved_hold':hold,'request_bound_proof':proof(env,url),
        'plan_ref':imported['plan_ref'],'decision_ref':imported['decision_ref'],
        'object_id':'HP-02-K9023p670-L'}
    (evidence/'probe-inputs.json').write_text(json.dumps(inputs))
    return {'case':case,'evidence':evidence,'env':env,'ledger':ledger,
        'inputs':inputs,'hold':hold,'source':f.ws.store.root,
        'source_sha256':sha(f.ws.store.path.read_bytes()),'models':[],'wires':[]}


def sdk_reply(*, tool=None, arguments=None, usage=10):
    message = {'role':'assistant','content':'Synthetic evidence remains incomplete.'}
    if tool:
        message = {'role':'assistant','content':None,'tool_calls':[{
            'id':'synthetic-call','type':'function',
            'function':{'name':tool,'arguments':json.dumps(arguments or {})}}]}
    return {'id':'synthetic-response','object':'chat.completion','created':1,'model':'glm-5.3',
        'choices':[{'index':0,'finish_reason':'tool_calls' if tool else 'stop','message':message}],
        'usage':{'prompt_tokens':usage-4,'completion_tokens':4,'total_tokens':usage}}


def install_probe_transport(monkeypatch, setup, replies, *, mutate=None):
    from report_agent import deep_models
    actual = deep_models.configured_model
    def configured(store, role):
        assert role=='writer'
        model = actual(store,role)
        assert model.model_name=='glm-5.3'
        assert model.profile['image_inputs'] is False
        assert model.root_async_client.max_retries==0
        def respond(request):
            setup['wires'].append(request)
            assert len(setup['wires'])<=len(replies), 'Unexpected extra SDK dispatch'
            return httpx.Response(200,json=replies[len(setup['wires'])-1])
        model.http_async_client._transport = httpx.MockTransport(respond)
        model.http_async_client._mounts = {}
        if mutate:
            async def mutate_before_finance(request):
                body = json.loads(request.content)
                mutate(request,body)
                request._content = json.dumps(body).encode()
            hooks = model.http_async_client.event_hooks['request']
            position = next(i for i,h in enumerate(hooks) if h.__name__=='account_request')
            hooks.insert(position,mutate_before_finance)
        setup['models'].append(model)
        return model
    monkeypatch.setattr(deep_models,'configured_model',configured)


def assert_probe_preserved(setup, result):
    now = read_finance(setup['ledger'])
    assert now['auth']==setup['inputs']['stage_baseline']['auth']
    assert all(row in now['rows'] for row in setup['inputs']['stage_baseline']['rows'])
    assert json.loads((setup['evidence']/'probe-inputs.json').read_text())==setup['inputs']
    assert next(r for r in now['rows'] if r[0]==setup['hold'][0])==setup['hold']
    assert sha((setup['source']/'state.db').read_bytes())==setup['source_sha256']
    assert result['overall_rescue']['preserved_hold_unchanged'] is True
    assert result['automatic_continuation'] is False and result['engineering_acceptance'] is False
    assert result['visual_verification']=='SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE'
    assert result['maximum_tokens']==2_200_000 and result['request_bound']==1_179_648
    assert result['connection_retries']==2 and result['sdk_retries']==0
    assert result['keepalive_expiry_seconds']==60.0
    assert result['retry_scope']=='pre_http_connection_only'
    assert result['budget']['maximum_tokens']==2_200_000
    assert result['investigation_threshold_tokens']==1_000_000
    assert result['investigation_threshold_basis']=='settled_stage_tokens'
    assert result['investigation_threshold_reached']==(result['budget']['recorded_tokens']>=1_000_000)
    assert json.loads((setup['evidence']/'probe-launch.json').read_text())==result
    assert set(result['tools'])=={'read_assignment','read_assigned_page','read_assigned_text',
                                 'set_indicator','submit_assessment','propose_material_issue'}
    tasks = ContentStore(Store(setup['case'])).list_objects('DelegatedTask')
    assert len(tasks)==1 and tasks[0]['payload']['assessment_object_id']=='HP-02-K9023p670-L'
    assert result['object_id']=='HP-02-K9023p670-L'
    assert result['budget']['model_reservation_bounds']=={'glm-5.3':1_179_648}
    assert 'receipt_error_type' not in result
    return now


@pytest.mark.asyncio
async def test_probe_actual_glm_sdk_incomplete_refusal_receipt_and_exclusive_launch(prepared_probe, monkeypatch):
    p = prepared_probe
    install_probe_transport(monkeypatch,p,[
        sdk_reply(tool='read_assigned_page',arguments={'source_handle':'foreign-source','page':1}),
        sdk_reply()])
    result = await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert result['status']=='returned' and result['assessment_refs']=={}
    assert result['refusals']==[{'tool':'read_assigned_page','tool_call_id':'synthetic-call',
                                 'code':'WRITER_SOURCE_HANDLE_UNKNOWN'}]
    now = assert_probe_preserved(p,result)
    assert len(p['models'])==1 and len(p['wires'])==2
    for request in p['wires']:
        body = json.loads(request.content)
        assert str(request.url)=='https://synthetic.invalid/v1/chat/completions'
        assert body['model']=='glm-5.3' and body['max_completion_tokens']==65536
        assert not body.get('stream') and body.get('n',1)==1
        assert 'image_url' not in str(body['messages'])
    assert result['budget']['recorded_tokens']==20
    assert result['budget']['effective_request_bound']==1_179_648
    assert result['metrics']['roles']['writer']['tokens']==20
    assert result['metrics']['roles']['writer']['invocations']==2
    assert len(now['rows'])==len(p['inputs']['stage_baseline']['rows'])+2
    with pytest.raises(FileExistsError,match='ALREADY_LAUNCHED'):
        await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert len(p['models'])==1 and len(p['wires'])==2
    assert read_finance(p['ledger'])==now


@pytest.mark.asyncio
async def test_probe_budget_stops_second_sdk_dispatch_and_preserves_old_hold(prepared_probe, monkeypatch):
    p = prepared_probe
    install_probe_transport(monkeypatch,p,[sdk_reply(tool='read_assignment',usage=1_020_353)])
    result = await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert result['status']=='stopped' and result['stop_code']=='PROBE_TOKEN_LIMIT'
    assert result['assessment_refs']=={}
    now = assert_probe_preserved(p,result)
    assert len(p['wires'])==1
    assert result['budget']['recorded_tokens']==1_020_353
    assert result['budget']['reserved_or_unknown_upper_bounds']==0
    assert sum(r[4]=='known_not_sent' and r[3]==0 for r in now['rows'])==1
    assert sum(r[4]=='settled' and r[2]==1_179_648 for r in now['rows'])==1
    assert result['metrics']['roles']['writer']['tokens']==1_020_353
    with pytest.raises(FileExistsError):
        await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert len(p['wires'])==1 and read_finance(p['ledger'])==now


@pytest.mark.asyncio
@pytest.mark.parametrize('change,code',[
    ('model','SCOPED_REQUEST_WIRE_MISMATCH'),
    ('url','SCOPED_REQUEST_WIRE_MISMATCH'),
    ('output','SCOPED_REQUEST_OUTPUT_LIMIT_REQUIRED'),
    ('image','SCOPED_REQUEST_TEXT_ONLY'),
])
async def test_probe_final_sdk_wire_rejection_precedes_finance(prepared_probe, monkeypatch, change, code):
    p = prepared_probe
    def mutate(request,body):
        if change=='model': body['model']='other-model'
        elif change=='url': request.url=httpx.URL(str(request.url)+'?different=1')
        elif change=='output': body['max_completion_tokens']=131_073
        else: body['messages'][-1]['content']=[{'type':'image_url','image_url':{'url':'https://synthetic.invalid/image'}}]
    install_probe_transport(monkeypatch,p,[sdk_reply()],mutate=mutate)
    result = await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert result['status']=='stopped' and result['stop_code']==code
    assert_probe_preserved(p,result)
    assert p['wires']==[]
    assert read_finance(p['ledger'])==p['inputs']['stage_baseline']


@pytest.mark.asyncio
async def test_second_probe_threshold_is_observation_and_exact_boundary_allows_next_sdk(prepared_probe,monkeypatch):
    p=prepared_probe
    install_probe_transport(monkeypatch,p,[
        sdk_reply(tool='read_assignment',usage=1_020_352),sdk_reply()])
    result=await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert result['status']=='returned'
    assert result['investigation_threshold_reached'] is True
    assert result['budget']['recorded_tokens']==1_020_362
    assert len(p['wires'])==2
    now=assert_probe_preserved(p,result)
    with pytest.raises(FileExistsError,match='ALREADY_LAUNCHED'):
        await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert len(p['wires'])==2 and read_finance(p['ledger'])==now


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[
    {'hard_probe_tokens':1_500_000},{'hard_probe_tokens':2_200_001},
    {'hard_probe_tokens':2_200_000.0},{'hard_probe_tokens':True},
    {'investigation_threshold_tokens':None},{'investigation_threshold_tokens':1_000_001},
    {'investigation_threshold_tokens':1_000_000.0},{'overall_rescue_tokens':20_000_001},
    {'overall_rescue_tokens':20_000_000.0},{'preserve_unknown_hold_tokens':0},
    {'preserve_unknown_hold_tokens':2_000_000.0},
    {'no_other_slopes_cleanup_export_or_model_tests':False},
])
async def test_second_probe_requires_exact_new_authority_before_model_or_finance(prepared_probe,monkeypatch,change):
    p=prepared_probe
    path=p['evidence']/'owner-authority.json'
    authority=json.loads(path.read_text());authority.update(change)
    if authority.get('investigation_threshold_tokens') is None:
        authority.pop('investigation_threshold_tokens',None)
    path.write_text(json.dumps(authority))
    p['inputs']['authority_sha256']=sha(path.read_bytes())
    (p['evidence']/'probe-inputs.json').write_text(json.dumps(p['inputs']))
    before=read_finance(p['ledger'])
    install_probe_transport(monkeypatch,p,[])
    with pytest.raises(ValueError,match='PROBE_OWNER_AUTHORITY_REQUIRED'):
        await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert not p['models'] and not p['wires']
    assert read_finance(p['ledger'])==before
    assert not (p['evidence']/'probe-launch.json').exists()


@pytest.mark.asyncio
async def test_second_probe_nonobject_authority_refused_before_finance(prepared_probe):
    p=prepared_probe
    path=p['evidence']/'owner-authority.json';path.write_text('[]')
    p['inputs']['authority_sha256']=sha(path.read_bytes())
    (p['evidence']/'probe-inputs.json').write_text(json.dumps(p['inputs']))
    with pytest.raises(ValueError,match='PROBE_OWNER_AUTHORITY_REQUIRED'):
        await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert read_finance(p['ledger'])==p['inputs']['stage_baseline']


@pytest.mark.asyncio
@pytest.mark.parametrize('settled,reached',[(999_999,False),(1_000_000,True)])
async def test_second_probe_investigation_flag_counts_only_settled_stage_tokens(prepared_probe,monkeypatch,settled,reached):
    p=prepared_probe
    install_probe_transport(monkeypatch,p,[sdk_reply(usage=settled)])
    result=await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert result['status']=='returned'
    assert result['investigation_threshold_reached'] is reached
    assert result['budget']['recorded_tokens']==settled
    assert result['overall_rescue']['held']==2_000_000
    assert_probe_preserved(p,result)


@pytest.mark.asyncio
@pytest.mark.parametrize('connect,sdk', [('0','0'),('1','0'),('3','0'),('0','1'),('2','1')])
async def test_probe_requires_bounded_connection_only_retry_policy_before_model_or_ledger(prepared_probe,monkeypatch,connect,sdk):
    p=prepared_probe
    monkeypatch.setenv('REPORT_CONNECT_RETRIES',connect)
    monkeypatch.setenv('REPORT_SDK_RETRIES',sdk)
    before=read_finance(p['ledger'])
    install_probe_transport(monkeypatch,p,[])
    with pytest.raises((ValueError,RuntimeError)):
        await probe.run_probe(p['case'],p['evidence'],p['env'])
    assert not p['models'] and not p['wires']
    assert read_finance(p['ledger'])==before
    assert not (p['evidence']/'probe-launch.json').exists()
