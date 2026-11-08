from copy import deepcopy

import pytest

from report_agent.errors import ActionRejected
from test_m1_commission_plan import commission, save
from support.plan_fixture import approve, confirmed_records, install_confirmed_plan


def test_successor_plan_needs_its_own_operator_decision(commission):
    first, _, _ = install_confirmed_plan(commission)
    plan, decision = confirmed_records(commission)
    assert plan["ref"] == first["plan_ref"] == decision["payload"]["plan_ref"]
    assert decision["owner_id"] == "operator"
    revised = deepcopy(commission.plan)
    revised["open_questions"].append("Confirm the revised delivery sequence.")
    second = save(commission, revised, operation="propose-successor")
    assert second["plan_ref"] != first["plan_ref"]
    with pytest.raises(ActionRejected, match="COMMISSION_CHECKPOINT_CONFIRMATION"):
        confirmed_records(commission)
    approve(commission, second)
    new_plan, new_decision = confirmed_records(commission)
    assert new_plan["ref"] == new_decision["payload"]["plan_ref"] == second["plan_ref"]
    assert new_decision["ref"] != decision["ref"]
    assert commission.cs.read(decision["ref"]) == decision
