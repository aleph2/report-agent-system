"""Exercise the normal proposal and owner checkpoint when a synthetic case needs a plan."""
from report_agent import commission_plan
from report_agent.store import encode


def save(fixture, plan=None, operation="save-plan"):
    return commission_plan.save_plan(fixture.cs, fixture.co, operation, plan or fixture.plan)["result"]


def approve(fixture, saved, *, reductions=(), requirements_ref=None):
    checkpoint = commission_plan.request_checkpoint(fixture.ws)
    decision = dict(plan_ref=saved["plan_ref"], approved=True, corrections="", reductions=list(reductions))
    if requirements_ref is not None:
        decision["requirements_ref"] = requirements_ref
    commission_plan.reply(fixture.ws, checkpoint["issue_id"], decision)
    return checkpoint, decision


def install_confirmed_plan(fixture, *, requirements_ref=None):
    saved = save(fixture)
    checkpoint, decision = approve(fixture, saved, requirements_ref=requirements_ref)
    return saved, checkpoint, decision


def confirmed_records(fixture):
    with fixture.cs.store.connect() as db:
        return commission_plan._confirmed(fixture.cs, db)


def plan_action_id(fixture, action, ref):
    import json
    import sqlite3
    from contextlib import closing

    field = "rule" if action == "record_convention" else "reason"
    with closing(sqlite3.connect(fixture.ws.store.root / "assertions.sqlite3")) as db:
        for identity, body in db.execute("SELECT id,body FROM assertions WHERE action=?", (action,)):
            if json.loads(body)["claim"][field] == encode(ref):
                return identity
    raise AssertionError(f"Missing {action} for {ref}")


def enroll_planning_file(fixture, filename, source_id, purpose):
    """Give this supplied fixture file its role in the commission intake."""
    from report_agent import commission_imports
    current = commission_imports.source_roles(fixture.ws.store, {})
    commission_imports.install_source_roles(fixture.ws.store, {
        **current, filename: {'id': source_id, 'purpose': purpose}})
