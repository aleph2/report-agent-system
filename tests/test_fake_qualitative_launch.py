"""Admission and frozen profile for the single-run qualitative pilot."""
import pytest

from report_agent import fake_verification as host
from report_agent.fake_verification_budget import FakeComparisonBudget
from report_agent.request_budget import RequestBudgetExceeded
from test_fake_fresh_comparison import pair
from test_fake_verification_launcher import packet, write_json


def pilot(data, comparison, register='1'*64):
    return {**data,'run_id':'qualitative-01',
            'qualitative_pilot':{'register_sha256':register},
            'fresh_comparison':{**comparison,'run_ids':['qualitative-01']}}


def test_single_run_requires_separate_qualitative_authority_and_register(pair):
    path, data, grant, c = pair
    approved=pilot(data,c)
    assert host.preflight(path,write_json(path,approved))==approved
    for invalid in [
        {k:v for k,v in approved.items() if k!='qualitative_pilot'},
        {k:v for k,v in approved.items() if k!='fresh_comparison'},
        {**approved,'fresh_comparison':c},
        {**approved,'qualitative_pilot':{'register_sha256':'not-a-digest'}},
        {**approved,'qualitative_pilot':{'register_sha256':'0'*64,'more_runs':1}},
        {**approved,'qualitative_pilot':None},
    ]:
        with pytest.raises(ValueError):
            host.preflight(path,write_json(path,invalid))
    changed=pilot(data,c,'2'*64)
    assert host._comparison_identity(changed)!=host._comparison_identity(approved)


def test_single_fresh_budget_stops_on_new_unknown_without_pair_terminal(pair):
    path,data,grant,c=pair
    approved=pilot(data,c)
    comparison=approved['fresh_comparison']
    with pytest.raises(ValueError):
        FakeComparisonBudget(grant,approved['run_id'],comparison,host._comparison_identity(approved))
    budget=FakeComparisonBudget(grant,approved['run_id'],comparison,host._comparison_identity(approved),
                                qualitative_only=True)
    budget.check_fresh()
    budget.settle(budget.reserve(host.MODEL),{'total_tokens':200})
    budget.reserve(host.MODEL)
    with pytest.raises(RequestBudgetExceeded,match='HOLD_MISMATCH'):
        budget.reserve(host.MODEL)
    assert budget.snapshot()['reserved_or_unknown_upper_bounds']==2*host.BOUND

def test_qualitative_operator_cli_seals_profile_and_verifies_fresh_binding(pair,tmp_path,monkeypatch):
    import hashlib
    import sys
    from report_agent import writer_indicator_steps
    from report_agent.fake03_fact_register import REGISTER, qualitative_profile
    path,data,grant,c=pair
    register=host._sha(REGISTER)
    env=tmp_path/'services.env'
    url='https://offline.invalid/v1'
    env.write_text('HIGHWAY_MODEL_DEEPSEEK_NAME=deepseek-v4.1-flash-1017\n'
        f'HIGHWAY_MODEL_DEEPSEEK_BASE_URL={url}\nHIGHWAY_MODEL_DEEPSEEK_API_KEY=test\n'
        f'HIGHWAY_MODEL_NAME=glm-5.3\nHIGHWAY_MODEL_BASE_URL={url}\nHIGHWAY_MODEL_API_KEY=test\n')
    sha=lambda text:hashlib.sha256(text.encode()).hexdigest()
    data['request_bound_proof']={'model':host.MODEL,'input_limit':1_048_576,'output_limit':131_072,
        'basis':'documented_model_ceiling_not_measured_request_fit','env_sha256':host._sha(env),
        'base_url_sha256':sha(url),'request_url_sha256':sha(url+'/chat/completions'),
        'sources':['https://docs.z.ai/guides/llm/glm-5.3','https://help.aliyun.com/zh/model-studio/glm-5-3']}
    approved=pilot(data,c,register)
    bad=pilot(data,c,'0'*64)
    with pytest.raises(ValueError):
        host.prepare(path,write_json(path,bad))
    assert not (grant/'runs'/approved['run_id']).exists()
    pin=write_json(path,approved)
    receipt=host.prepare(path,pin)
    assert receipt['qualitative_pilot']==approved['qualitative_pilot']
    host.check_prepared(path,pin,receipt['prepared_sha256'])
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES','2')
    calls=[]
    async def mock_runner(ws,model,*,verified_run):
        host.assert_active_fake_run(verified_run,ws)
        assert verified_run.qualitative_only
        assert ws.store.get('fake03_qualitative_profile')==qualitative_profile(register)
        assert model.profile['image_inputs'] is False
        budget=verified_run.budget
        budget.settle(budget.reserve(host.MODEL),{'total_tokens':100})
        calls.append(verified_run.run_id)
        return {'status':'qualitative_rows_saved'}
    monkeypatch.setattr(writer_indicator_steps,'run_mini_assessment',mock_runner)
    monkeypatch.setattr(sys,'argv',['fake_verification','run','--authority',str(path),'--authority-sha256',pin,
                                  '--prepared-sha256',receipt['prepared_sha256'],'--env',str(env)])
    assert host.main()==0
    assert calls==[approved['run_id']]
    with pytest.raises(FileExistsError,match='ALREADY_CLAIMED'):
        host.main()
    from report_agent.fake_verification_budget import FakeVerificationBudget
    budget=FakeVerificationBudget(grant,approved['run_id'])
    assert budget.run_snapshot()['settled']==100
    assert budget.snapshot()['reserved_or_unknown_upper_bounds']==host.BOUND
    with budget.connect() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='fake_comparison_terminals'").fetchone()
