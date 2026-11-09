"""The case contents commit before a proposal or owner act can establish authority."""
from copy import deepcopy

import pytest

from report_agent import commission_plan, plan_authority
from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden, ActionRejected
from support.plan_fixture import confirmed_records, save
from test_m1_commission_plan import commission


def interrupt(*args, **kwargs):
    raise RuntimeError("crash before assertion")


def test_content_survives_a_crash_without_becoming_current(commission, monkeypatch):
    cs = commission.cs
    with monkeypatch.context() as patch:
        patch.setattr(plan_authority, "propose", interrupt, raising=False)
        with pytest.raises(RuntimeError, match="before assertion"):
            save(commission)
    [saved] = cs.list_objects("CommissionPlan")
    assert "plan_authority" not in saved
    assert plan_authority.plan_ref(cs.store) is None
    for other in (Actor(commission.co.id, "writer", commission.co.task_id),
                  Actor("other-coordinator", "coordinator", commission.co.task_id)):
        with pytest.raises(ActionForbidden):
            commission_plan.save_plan(cs, other, "save-plan", commission.plan)
    changed = deepcopy(commission.plan)
    changed["open_questions"].append("Different submission")
    with pytest.raises(ActionRejected, match="OPERATION_CONFLICT"):
        save(commission, changed)
    assert plan_authority.plan_ref(cs.store) is None
    assert save(commission)["plan_ref"] == saved["ref"] == plan_authority.plan_ref(cs.store)
    assert cs.list_objects("CommissionPlan") == [saved]


def test_owner_content_crash_does_not_resolve_checkpoint(commission, monkeypatch):
    from report_agent import legacy_state as legacy

    saved = save(commission)
    issue_id = commission_plan.request_checkpoint(commission.ws)["issue_id"]
    answer = dict(plan_ref=saved["plan_ref"], approved=True, corrections="", reductions=[])
    with monkeypatch.context() as patch:
        patch.setattr(plan_authority, "decide", interrupt, raising=False)
        with pytest.raises(RuntimeError, match="before assertion"):
            commission_plan.reply(commission.ws, issue_id, answer)
    [decision] = commission.cs.list_objects("CommissionDecision")
    assert plan_authority.decision_ref(commission.cs.store) is None
    assert not next(i for i in legacy.get_report_issues(commission.cs.store) if i["id"] == issue_id)["resolved"]
    with pytest.raises(ActionRejected):
        confirmed_records(commission)
    with pytest.raises(ActionRejected, match="ALREADY_ANSWERED"):
        commission_plan.reply(commission.ws, issue_id, {**answer, "approved": False, "corrections": "Different"})
    commission_plan.reply(commission.ws, issue_id, answer)
    assert confirmed_records(commission)[1] == decision
    assert commission.cs.list_objects("CommissionDecision") == [decision]


def test_late_redo_keeps_the_newer_proposal_current(commission, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(plan_authority, "propose", interrupt, raising=False)
        with pytest.raises(RuntimeError, match="before assertion"):
            save(commission)
    [older] = commission.cs.list_objects("CommissionPlan")
    changed = deepcopy(commission.plan)
    changed["open_questions"].append("The revised proposal")
    newer = save(commission, changed, "revised")["plan_ref"]
    assert older["ref"]["id"] == newer["id"]
    assert newer["version"] > older["ref"]["version"]
    assert save(commission)["plan_ref"] == older["ref"]
    assert plan_authority.plan_ref(commission.cs.store) == newer


def test_lost_owner_reply_finishes_the_issue_projection(commission, monkeypatch):
    from report_agent import legacy_state as legacy

    proposal = save(commission)
    issue_id = commission_plan.request_checkpoint(commission.ws)["issue_id"]
    answer = dict(plan_ref=proposal["plan_ref"], approved=True, corrections="", reductions=[])
    decide = plan_authority.decide

    def lose_reply(*args, **kwargs):
        decide(*args, **kwargs)
        raise RuntimeError("lost committed result")

    with monkeypatch.context() as patch:
        patch.setattr(plan_authority, "decide", lose_reply)
        with pytest.raises(RuntimeError, match="lost committed result"):
            commission_plan.reply(commission.ws, issue_id, answer)
    _, decision = confirmed_records(commission)
    issues = legacy.get_report_issues(commission.cs.store)
    assert not next(i for i in issues if i["id"] == issue_id)["resolved"]
    issue = commission_plan.reply(commission.ws, issue_id, answer)
    assert issue["resolved"] and (commission.cs.store.root / issue["confirmation_checklist_path"]).is_file()
    assert commission.cs.list_objects("CommissionDecision") == [decision]


def test_replaced_pending_checkpoint_is_preserved_after_owner_act(commission, monkeypatch):
    from report_agent import legacy_state as legacy

    proposal = save(commission)
    issue_id = commission_plan.request_checkpoint(commission.ws)["issue_id"]
    answer = dict(plan_ref=proposal["plan_ref"], approved=True, corrections="", reductions=[])
    decide = plan_authority.decide
    successor = {}

    def replace_checkpoint(*args, **kwargs):
        result = decide(*args, **kwargs)
        revision = deepcopy(commission.plan)
        revision["open_questions"].append("Owner input on successor")
        save(commission, revision, "successor")
        successor.update(commission_plan.request_checkpoint(commission.ws))
        commission.cs.store.set("report_status", "awaiting_user")
        return result

    monkeypatch.setattr(plan_authority, "decide", replace_checkpoint)
    issue = commission_plan.reply(commission.ws, issue_id, answer)
    assert issue["resolved"] and "confirmation_checklist_path" not in issue
    issues = legacy.get_report_issues(commission.cs.store)
    assert not next(i for i in issues if i["id"] == successor["issue_id"])["resolved"]
    assert commission.cs.store.get("report_status") == "awaiting_user"


def test_repeated_issue_projection_is_idempotent(commission, monkeypatch):
    from report_agent import legacy_state as legacy
    from report_agent.store import encode

    proposal = save(commission)
    issue_id = commission_plan.request_checkpoint(commission.ws)["issue_id"]
    answer = commission_plan.OwnerDecision.model_validate(dict(
        plan_ref=proposal["plan_ref"], approved=True, corrections="", reductions=[])).model_dump()
    decide = plan_authority.decide

    def project_elsewhere(*args, **kwargs):
        result = decide(*args, **kwargs)
        with commission.cs.store.connect() as db:
            issues = legacy.get_report_issues(db)
            issue = next(i for i in issues if i["id"] == issue_id)
            issue.update(decision=encode(answer), decision_origin="operator", resolved=True)
            legacy.set_report_issues(db, issues)
            db.execute("INSERT INTO events(kind,data) VALUES ('commission_owner_decision', '{}')")
            commission_plan._set(db, "context_revision", 123)
        return result

    monkeypatch.setattr(plan_authority, "decide", project_elsewhere)
    assert commission_plan.reply(commission.ws, issue_id, answer)["resolved"]
    with commission.cs.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE kind='commission_owner_decision'").fetchone() == (1,)
        assert commission_plan._state(db, "context_revision") == 123


def test_foreign_prepared_content_cannot_claim_a_new_plan_identity(commission):
    with commission.cs.store.connect() as db:
        foreign = commission.cs._insert(db, Actor("other", "coordinator", "other-task"),
            "CommissionPlan", commission.plan, plan_input_refs=[])
    saved = save(commission)["plan_ref"]
    assert saved["id"] != foreign["id"]
    assert commission.cs.read(saved)["previous_ref"] is None
