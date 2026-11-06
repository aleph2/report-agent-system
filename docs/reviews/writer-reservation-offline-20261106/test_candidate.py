"""Offline prototype only; all ledger writes target synthetic databases."""
from copy import deepcopy
import json
import pytest
from candidate import forecast, check_response, CandidateExceeded
from report_agent.token_budget import TokenBudget
from report_agent.probe_budget import ProbeBudget
from report_agent.request_budget import RequestBudgetExceeded

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('OFFLINE_ONLY_NETWORK_FORBIDDEN')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket.socket,'connect_ex',denied)
    monkeypatch.setattr(socket,'create_connection',denied)

class Counter:
    def measure(self, payload):
        return {'tokens': payload.get('synthetic_count', 10000)}

def payload(**changes):
    return {'model': 'glm-5.3', 'max_completion_tokens': 65536,
            'messages': [{'role': 'user', 'content': 'synthetic'}], **changes}

def usage(i=10000, o=100):
    return {'prompt_tokens': i, 'completion_tokens': o, 'total_tokens': i+o,
            'prompt_tokens_details': {'cached_tokens': i}}

def finance(b):
    with b.connect() as db:
        return {'auth': list(db.execute('SELECT maximum,bounds FROM authorization').fetchone()),
                'rows': [list(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]}

def test_formula_rounds_up_without_mutating_wire():
    body=payload(synthetic_count=15536); before=deepcopy(body)
    f=forecast(body, Counter())
    assert f['input_estimate']==22740 and f['total_estimate']==88276
    assert f['hard_bound_verified'] is False and body==before
    assert forecast(payload(synthetic_count=3781), Counter())['total_estimate']==74170
    assert forecast(payload(synthetic_count=1048576), Counter())['input_estimate']==1048576

@pytest.mark.parametrize('changes', [
    {'max_completion_tokens': True}, {'max_completion_tokens': 65537},
    {'max_completion_tokens': 0}, {'max_tokens': 1}, {'n': True},
    {'n': 2}, {'stream': True}, {'model': 'other'},
    {'synthetic_count': True}, {'synthetic_count': -1},
    {'synthetic_count': 1048577}])
def test_rejects_unsupported_contract(changes):
    with pytest.raises(ValueError): forecast(payload(**changes), Counter())

def test_components_cache_and_exact_boundary():
    f=forecast(payload(), Counter())
    assert check_response(f, usage(16096,65536))['total_tokens']==81632
    assert check_response(f, usage())['total_tokens']==10100
    with pytest.raises(CandidateExceeded, match='INPUT_ESTIMATE_EXCEEDED'):
        check_response(f, usage(16097,0))
    with pytest.raises(CandidateExceeded, match='OUTPUT_ALLOWANCE_EXCEEDED'):
        check_response(f, usage(100,65537))
    with pytest.raises(CandidateExceeded, match='TOTAL_ESTIMATE_EXCEEDED'):
        check_response(f, usage(20000,65536))

@pytest.mark.parametrize('u', [None, {}, {'total_tokens': 1},
    {'prompt_tokens': True,'completion_tokens': 0,'total_tokens': 1},
    {'prompt_tokens': -1,'completion_tokens': 2,'total_tokens': 1},
    {'prompt_tokens': 1,'completion_tokens': 2,'total_tokens': 4}])
def test_missing_or_malformed_usage_refuses_continuation(u):
    with pytest.raises(CandidateExceeded, match='USAGE_UNVERIFIED'):
        check_response(forecast(payload(), Counter()), u)

def test_after_response_stop_cannot_prevent_cap_overrun(tmp_path):
    b=TokenBudget(tmp_path/'synthetic.db',100000000,{'glm-5.3':2000000})
    original=finance(b); hid=b.reserve('glm-5.3')
    hold=next(r for r in finance(b)['rows'] if r[0]==hid); stage=finance(b)
    guard=ProbeBudget(lambda:finance(b),original,stage,preserved_hold=hold,writer_model='glm-5.3')
    prior=b.reserve('glm-5.3');b.settle(prior,{'total_tokens':1418368})
    f=forecast(payload(),Counter())
    # Intentionally unsafe proposal, confined to a fresh synthetic database.
    request=b._reserve('glm-5.3',f['total_estimate'])
    assert guard.check()==(1418368,81632)
    result=b.settle(request,usage(20000,65536))
    assert result=={'state':'bound_violation','used':85536}
    with pytest.raises(CandidateExceeded): check_response(f,usage(20000,65536))
    with pytest.raises(RequestBudgetExceeded,match='PROBE_TOKEN_LIMIT'):guard.check()
    assert b.snapshot()['recorded_tokens']==1503904
    assert next(r for r in finance(b)['rows'] if r[0]==hid)==hold

def test_shadow_miss_is_not_a_real_ledger_violation(tmp_path):
    b=TokenBudget(tmp_path/'synthetic.db',100000000,{'glm-5.3':2000000})
    identity=b._reserve('glm-5.3',1179648)
    assert b.settle(identity,usage(20000,100))['state']=='settled'
    with pytest.raises(CandidateExceeded,match='INPUT_ESTIMATE_EXCEEDED'):
        check_response(forecast(payload(),Counter()),usage(20000,100))
    assert b.snapshot()['attempt_states']=={'settled':1}

def test_unverified_usage_retains_authoritative_hold(tmp_path):
    b=TokenBudget(tmp_path/'synthetic.db',100000000,{'glm-5.3':2000000})
    identity=b._reserve('glm-5.3',1179648)
    assert b.settle(identity,{})['state']=='unknown'
    assert b.snapshot()['reserved_or_unknown_upper_bounds']==1179648
