import pytest

from report_agent.o6_budget import O6Budget, MODEL, REQUEST_CEILING
from report_agent.request_budget import RequestBudgetExceeded


def test_one_o6_shares_verification_ledger_and_stops_before_exceeding_its_cap(tmp_path):
    root = tmp_path / "grant"
    O6Budget.initialize(root)
    budget = O6Budget(root)
    with pytest.raises(RequestBudgetExceeded):
        budget.reserve(MODEL)
    budget.claim_launch("case-1")
    first = budget.reserve(MODEL)
    assert budget.run_totals() == (0, REQUEST_CEILING)
    with pytest.raises(RequestBudgetExceeded):
        budget.reserve(MODEL)
    budget.settle(first, {"total_tokens": 200_001})
    assert budget.run_totals() == (200_001, 0)
    with pytest.raises(RequestBudgetExceeded, match="RUN_LIMIT"):
        budget.reserve(MODEL)
    with pytest.raises(ValueError, match="ALREADY"):
        O6Budget(root).claim_launch("case-2")
    with pytest.raises(FileExistsError):
        O6Budget.initialize(root)


def test_unknown_preserves_reservation_across_restart_and_blocks_fresh_requests(tmp_path):
    root = tmp_path / "grant"
    O6Budget.initialize(root)
    budget = O6Budget(root)
    budget.claim_launch("case")
    key = budget.reserve(MODEL)
    budget.settle(key, None)
    reopened = O6Budget(root)
    assert reopened.run_totals() == (0, REQUEST_CEILING)
    with pytest.raises(RequestBudgetExceeded, match="PENDING"):
        reopened.reserve(MODEL)


def test_campaign_total_admits_no_request_beyond_100m_even_for_new_run(tmp_path):
    root = tmp_path / "grant"
    O6Budget.initialize(root)
    budget = O6Budget(root)
    budget.claim_launch("case")
    with budget.connect() as db:
        db.execute("INSERT INTO attempts VALUES ('earlier',?,100000000,99000000,'settled',NULL,NULL,'t')", (MODEL,))
    with pytest.raises(RequestBudgetExceeded, match="AUTHORIZED_TOKEN_BUDGET_REACHED"):
        budget.reserve(MODEL)
