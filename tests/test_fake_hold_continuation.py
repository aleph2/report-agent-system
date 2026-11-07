"""A retained unknown request counts against both caps for a single follow-up."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from report_agent.fake_verification_budget import FakeContinuationBudget, FakeVerificationBudget
from report_agent.request_budget import RequestBudgetExceeded

MODEL = 'glm-5.3'
BOUND = 1179648


def setup(tmp_path):
    FakeVerificationBudget.initialize(tmp_path, {MODEL: BOUND})
    budget = FakeVerificationBudget(tmp_path, '04')
    old = budget.reserve(MODEL)
    return budget, old


def test_one_concurrent_retry_only_and_no_reuse_even_when_settled(tmp_path):
    budget, old = setup(tmp_path)
    def reserve(_):
        try:
            return FakeContinuationBudget(tmp_path, '04', old).reserve(MODEL)
        except RequestBudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(reserve, range(2)))
    assert ids.count(None) == 1
    retry = next(i for i in ids if i)
    assert budget.run_snapshot()['held'] == 2 * BOUND
    for b in (budget, FakeVerificationBudget(tmp_path,'different')):
        with pytest.raises(RequestBudgetExceeded):
            b.reserve(MODEL)
    budget.settle(retry, {'total_tokens':123})
    assert budget.run_snapshot() == {'maximum_tokens':3700000,'held':BOUND,'settled':123}
    assert reserve(None) is None


def test_wrong_parent_run_and_cap_refuse_atomically(tmp_path):
    budget, old = setup(tmp_path)
    for b in (FakeContinuationBudget(tmp_path,'other',old), FakeContinuationBudget(tmp_path,'04','wrong')):
        with pytest.raises(RequestBudgetExceeded):
            b.reserve(MODEL)
    budget.settle(old,{'total_tokens':BOUND})
    second = budget.reserve(MODEL)
    budget.settle(second,{'total_tokens':500000})
    third = budget.reserve(MODEL)
    with pytest.raises(RequestBudgetExceeded,match='FAKE_RUN_TOKEN_LIMIT'):
        FakeContinuationBudget(tmp_path,'04',third).reserve(MODEL)
    assert budget.run_snapshot()['held'] == BOUND


def test_campaign_limit_checked_before_exception(tmp_path):
    FakeVerificationBudget.initialize(tmp_path,{MODEL:BOUND})
    for run in ('one','two'):
        b=FakeVerificationBudget(tmp_path,run)
        for usage in (BOUND,BOUND,3_700_000-3*BOUND,BOUND):
            b.settle(b.reserve(MODEL),{'total_tokens':usage})
    b=FakeVerificationBudget(tmp_path,'04')
    b.settle(b.reserve(MODEL),{'total_tokens':400_000})
    old=b.reserve(MODEL)
    with pytest.raises(RequestBudgetExceeded,match='AUTHORIZED_TOKEN_BUDGET_REACHED'):
        FakeContinuationBudget(tmp_path,'04',old).reserve(MODEL)
    assert b.run_snapshot()=={'maximum_tokens':3_700_000,'settled':400_000,'held':BOUND}
