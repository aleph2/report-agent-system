"""Both export entry points recheck the pinned owner decision, including on replay."""
from uuid import NAMESPACE_URL, uuid5

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.commission_requirements import export_preflight
from report_agent.errors import ActionRejected
from report_agent.store import encode
from support.plan_fixture import confirmed_records, install_confirmed_plan, plan_action_id
from test_m1_commission_plan import commission
from test_m1_g4_requirements import anchored, required_case, method_commission


@pytest.mark.parametrize(("case_fixture", "preexisting"), [("commission", False), ("required_case", False), ("commission", True)])
def test_snapshot_preflight_refuses_withdrawn_owner_confirmation(request, case_fixture, preexisting, monkeypatch):
    case = request.getfixturevalue(case_fixture)
    if preexisting:
        # A plan version created before input pins were introduced may still be proposed today.
        insert = case.cs._insert
        def insert_old_version(db, actor, kind, payload, **kwargs):
            if kind == "CommissionPlan":
                kwargs.pop("plan_input_refs", None)
            return insert(db, actor, kind, payload, **kwargs)
        monkeypatch.setattr(case.cs, "_insert", insert_old_version)
    install_confirmed_plan(case, requirements_ref=getattr(case, "requirements_ref", None))
    plan, decision = confirmed_records(case)
    with case.cs.store.connect() as db:
        snapshot = case.cs._insert(db, case.co, "DocumentSnapshot", {
            "refs": [plan["ref"], decision["ref"]], "commission_plan_ref": plan["ref"],
            "commission_confirmation_ref": decision["ref"]})
    export_preflight(case.cs, case.co, snapshot, None)
    host = AssertionHost(case.ws.store.root)
    target = plan_action_id(case, "confirm", decision["ref"])
    subject = plan["ref"]["id"]
    grant = Grant(str(uuid5(NAMESPACE_URL, "operator")), "owner", "withdraw", "attempt",
                  encode(plan["ref"]), {subject}, {target}, {"retract"})
    ctx = host.issue_once(grant, "retract", "withdraw")
    assertions.retract(ctx, subject=subject, claim={
        "kind": "act", "effect": "retract", "target": target, "reason": "Owner withdrew approval"})
    with pytest.raises(ActionRejected, match="PLAN_AUTHORITY"):
        export_preflight(case.cs, case.co, snapshot, None)
