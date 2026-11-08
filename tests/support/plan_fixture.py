"""Exercise the normal proposal and owner checkpoint when a synthetic case needs a plan."""
from report_agent import commission_plan


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
