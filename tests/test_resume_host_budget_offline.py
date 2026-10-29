import httpx
import pytest
from report_agent.token_budget import TokenBudget, token_budget
from report_agent.request_budget import request_reservation_observer, account_request_sync, enforce_host_admission, RequestBudgetExceeded

def test_continuation_guard_counts_existing_used_and_held_and_new_reservation(tmp_path):
    budget=TokenBudget(tmp_path/'synthetic-ledger.db',100,{'fake':10})
    settled=budget.reserve('fake');budget.settle(settled,{'total_tokens':7})
    unknown=budget.reserve('fake')
    before=budget.snapshot();assert before['recorded_tokens']==7 and before['reserved_or_unknown_upper_bounds']==10
    def admission():
        snap=budget.snapshot()
        enforce_host_admission(used_plus_held=snap['recorded_tokens']+snap['reserved_or_unknown_upper_bounds'],limit=26,unknown=False,failed=False)
    request=httpx.Request('POST','https://fake.invalid',json={'model':'fake'})
    with token_budget(budget),request_reservation_observer(admission):
        with pytest.raises(RequestBudgetExceeded,match='HOST_TOKEN_BUDGET_REACHED'):
            account_request_sync(request)
    after=budget.snapshot()
    assert after['recorded_tokens']==7 and after['reserved_or_unknown_upper_bounds']==10
    with budget.connect() as db:
        assert db.execute('select state,reserved from attempts where id=?',(unknown,)).fetchone()==('reserved',10)
        assert db.execute("select count(*) from attempts where state='known_not_sent'").fetchone()[0]==1
