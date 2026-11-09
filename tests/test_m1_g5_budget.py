"""G5 host-only budget tests: isolated synthetic finance, never a live ledger."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from report_agent.planning_budget import PlanningBudget, budget_scope_cost, grant_scope_cost, watch_planning, approvable_plan
from report_agent.request_budget import RequestBudgetExceeded, enforce_host_admission
from report_agent.token_budget import TokenBudget

M = 1_000_000


def row(identity, used=None, state="reserved", reserved=2*M):
    return [identity, "m", reserved, used, state, None, None, "synthetic"]


@pytest.fixture
def finances():
    baseline = {"auth": [478_464_822, '{"m": 2000000}'],
                "rows": [row("old-a"), row("old-b", state="unknown"), row("old-used", 193_802_770, "settled")]}
    current = deepcopy(baseline)
    return baseline, current


@pytest.mark.parametrize("used,alert,stopped", [(15*M-1,False,False),(15*M,True,False),
    (25*M-1,True,False),(25*M,True,True),(25*M+1,True,True)])
def test_exact_settled_thresholds(tmp_path, finances, used, alert, stopped):
    baseline, current = finances
    current["rows"].append(row("new", used, "settled", 30*M))
    untouched = deepcopy(current)
    guard = PlanningBudget(tmp_path/"planning.json", lambda: current, baseline)
    if stopped:
        with pytest.raises(RequestBudgetExceeded, match="^HOST_PLANNING_STOP_LOSS$"):
            guard.check()
    else:
        observed = guard.check()
        assert observed["settled_tokens"] == used and observed["held_tokens"] == 0
    saved = json.loads(guard.path.read_text())
    assert bool(saved["alert"]) == alert and bool(saved["stop"]) == stopped
    assert saved["baseline"] == baseline and current == untouched


def test_unknown_holds_do_not_trigger_settled_only_stop(tmp_path, finances):
    baseline, current = finances
    current["rows"] += [row("new-used", 24*M, "settled", 30*M), row("inflight"), row("unknown", state="unknown")]
    untouched = deepcopy(current)
    observed = PlanningBudget(tmp_path/"planning.json", lambda: current, baseline).check()
    assert observed["settled_tokens"] == 24*M
    assert observed["held_tokens"] == 4*M and observed["unknown"] is True
    assert observed["stop"] is None and current == untouched


def test_alert_is_once_and_stop_survives_reconstruction_and_later_plan(tmp_path, finances):
    baseline, current = finances
    current["rows"].append(row("first", 15*M, "settled", 30*M))
    guard = PlanningBudget(tmp_path/"planning.json", lambda: current, baseline)
    original_alert = deepcopy(guard.check()["alert"])
    original_bytes = guard.path.read_bytes()
    assert guard.check()["alert"] == original_alert and guard.path.read_bytes() == original_bytes
    current["rows"].append(row("second", 10*M, "settled", 30*M))
    with pytest.raises(RequestBudgetExceeded, match="HOST_PLANNING_STOP_LOSS"):
        guard.check()
    stopped = guard.path.read_bytes()
    reopened = PlanningBudget(guard.path, lambda: current, deepcopy(baseline))
    with pytest.raises(RequestBudgetExceeded, match="HOST_PLANNING_STOP_LOSS"):
        reopened.check(approvable=True)
    assert reopened.path.read_bytes() == stopped
    assert json.loads(stopped)["alert"] == original_alert
    assert json.loads(stopped)["stop"]["automatic_resume"] is False


def test_approvable_submitted_plan_avoids_new_stop_but_not_counter_reset(tmp_path, finances):
    baseline, current = finances
    current["rows"].append(row("new", 26*M, "settled", 30*M))
    guard = PlanningBudget(tmp_path/"planning.json", lambda: current, baseline)
    observed = guard.check(approvable=True)
    assert observed["settled_tokens"] == 26*M and observed["stop"] is None and observed["alert"] is None
    with pytest.raises(RequestBudgetExceeded, match="HOST_PLANNING_STOP_LOSS"):
        guard.check(approvable=False)


@pytest.mark.parametrize("change", ["baseline", "alert", "stop"])
def test_reopen_cannot_reset_baseline_or_policy(tmp_path, finances, change):
    baseline, current = finances
    path = tmp_path/"planning.json"
    PlanningBudget(path, lambda: current, baseline)
    kwargs = {}
    if change == "baseline":
        baseline = deepcopy(baseline)
        baseline["rows"].append(row("later", 1, "settled"))
    else:
        kwargs[change+"_tokens"] = (16 if change == "alert" else 26)*M
    with pytest.raises(RequestBudgetExceeded, match="HOST_BASELINE_CHANGED"):
        PlanningBudget(path, lambda: current, baseline, **kwargs)


@pytest.mark.parametrize("change", ["missing", "modified", "authority"])
def test_scope_rejects_history_or_authority_drift(finances, change):
    baseline, current = finances
    if change == "missing": current["rows"].pop(0)
    elif change == "modified": current["rows"][0][4] = "known_not_sent"
    else: current["auth"][0] += 1
    for calculate in (budget_scope_cost, grant_scope_cost):
        with pytest.raises(RequestBudgetExceeded, match="HOST_BASELINE_CHANGED"):
            calculate(baseline, current)


def test_grant_scope_counts_previous_run_and_protocol_not_old_unused_credit(finances):
    baseline, current = finances
    current["rows"] += [row("protocol", M, "settled"), row("run-one", 118*M, "settled", 120*M)]
    second_run_baseline = deepcopy(current)
    current["rows"] += [row("run-two", 80*M, "settled", 120*M), row("next-reservation")]
    assert budget_scope_cost(second_run_baseline, current) == (80*M, 2*M, False)
    used, held, unknown = grant_scope_cost(baseline, current)
    assert (used, held, unknown) == (199*M, 2*M, False)
    enforce_host_admission(used_plus_held=82*M, limit=120*M, unknown=False, failed=False)
    with pytest.raises(RequestBudgetExceeded, match="HOST_TOKEN_BUDGET_REACHED"):
        enforce_host_admission(used_plus_held=used+held, limit=200*M, unknown=False, failed=False)


def test_additive_cas_preserves_rows_and_unknowns_with_exact_idempotency(tmp_path):
    budget = TokenBudget(tmp_path/"ledger.db", 100, {"m": 20})
    old = budget.reserve("m"); budget.settle(old, None)
    with budget.connect() as db: before = db.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    args = dict(previous_maximum=100,new_maximum=300,authorization_id="g5-owner",authorization_sha256="a"*64)
    assert TokenBudget.increase_authorization(budget.path, **args)["applied"]
    assert not TokenBudget.increase_authorization(budget.path, **args)["applied"]
    with pytest.raises(ValueError, match="AMENDMENT_CONFLICT"):
        TokenBudget.increase_authorization(budget.path, **(args | {"authorization_sha256":"b"*64}))
    with budget.connect() as db:
        assert db.execute("SELECT * FROM attempts ORDER BY id").fetchall() == before
        assert db.execute("SELECT maximum FROM authorization").fetchone()[0] == 300
    assert TokenBudget(budget.path,300,{"m":20}).snapshot()["reserved_or_unknown_upper_bounds"] == 20


@pytest.mark.asyncio
async def test_watcher_detects_final_settlement_without_next_request(tmp_path, finances):
    baseline, current = finances
    guard = PlanningBudget(tmp_path/"planning.json", lambda: current, baseline)
    async def complete():
        current["rows"].append(row("last",25*M,"settled",30*M))
        return "would otherwise finish"
    with pytest.raises(RequestBudgetExceeded, match="HOST_PLANNING_STOP_LOSS"):
        await watch_planning(complete(),guard,lambda:False)
    assert json.loads(guard.path.read_text())["stop"]["settled_tokens"] == 25*M


@pytest.mark.asyncio
async def test_watcher_cancels_same_running_task_preserving_inflight(tmp_path, finances):
    baseline, current = finances
    entered, cancelled = asyncio.Event(), asyncio.Event()
    guard = PlanningBudget(tmp_path/"planning.json", lambda: current, baseline)
    async def running():
        current["rows"] += [row("settled",25*M,"settled",30*M),row("inflight")]
        entered.set()
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    with pytest.raises(RequestBudgetExceeded, match="HOST_PLANNING_STOP_LOSS"):
        await asyncio.wait_for(watch_planning(running(),guard,lambda:False),3)
    assert entered.is_set() and cancelled.is_set()
    assert current["rows"][-1] == row("inflight")
    assert all(current["rows"][i] == baseline["rows"][i] for i in range(len(baseline["rows"])))


@pytest.mark.asyncio
async def test_watcher_returns_normal_result(tmp_path, finances):
    baseline, current = finances
    async def complete(): return {"result":"done"}
    assert await watch_planning(complete(),PlanningBudget(tmp_path/"planning.json",lambda:current,baseline),lambda:False) == {"result":"done"}


@pytest.mark.parametrize("condition,expected", [("draft-only",False),("no-checkpoint",False),
    ("stale-plan",False),("stale-requirements",False),("missing-brief",False),("rejected",False),
    ("unresolved-source",False),("unresolved-method",False),("pending",True),("approved",True)])
def test_approvable_requires_current_submitted_complete_checkpoint(tmp_path, monkeypatch, condition, expected):
    # Isolate the host predicate; domain validity is still delegated to the shared checker.
    import report_agent.commission_plan as cp
    import report_agent.commission_requirements as cr
    from report_agent.content_store import ContentStore
    ref = {"type":"CommissionPlan","id":"p","version":2}
    requirements = {"type":"CommissionRequirements","id":"r","version":3}
    plan = {"requirements_ref":requirements,"sections":[{}]}
    checkpoint = {"plan_ref":deepcopy(ref),"requirements_ref":deepcopy(requirements),"brief_path":"brief.md"}
    issue = {"id":"i"}
    if condition in ("approved","rejected"):
        issue.update(decision_origin="operator",decision=json.dumps({"approved":condition=="approved","plan_ref":ref}))
    if condition == "stale-plan": checkpoint["plan_ref"]["version"] = 1
    if condition == "stale-requirements": checkpoint["requirements_ref"]["version"] = 2
    if condition != "missing-brief": (tmp_path/"brief.md").write_text("synthetic checkpoint")
    state = {"report_issues":[issue]}
    from report_agent import issue_state
    monkeypatch.setattr(issue_state, 'get_report_issues', lambda store, default=None: [issue])
    from report_agent import commission_assertions
    monkeypatch.setattr(commission_assertions, "checkpoint", lambda store, kind, issue_id:
                        checkpoint if (kind, issue_id) == ("plan", "i") and condition != "no-checkpoint" else None)
    store = SimpleNamespace(root=tmp_path,get=lambda key,default=None:state.get(key,default))
    monkeypatch.setattr(ContentStore,"__init__",lambda self,store:None)
    monkeypatch.setattr(cp,"read_plan",lambda store:None if condition=="draft-only" else {"ref":ref,"payload":plan})
    calls = []
    monkeypatch.setattr(cr,"require_complete",lambda cs,value:calls.append(value))
    monkeypatch.setattr(cp,"unresolved_sources",lambda section: condition=="unresolved-source")
    monkeypatch.setattr(cp,"method_questions",lambda value: ["missing"] if condition=="unresolved-method" else [])
    assert approvable_plan(SimpleNamespace(store=store)) is expected
    assert calls == ([] if condition=="draft-only" else [plan])


def test_caller_cannot_mutate_the_frozen_baseline(tmp_path, finances):
    baseline, current = finances
    guard = PlanningBudget(tmp_path/"planning.json",lambda:current,baseline)
    current["rows"].append(row("new",10*M,"settled",30*M))
    assert guard.check()["settled_tokens"] == 10*M
    baseline["rows"].append(deepcopy(current["rows"][-1]))
    assert guard.check()["settled_tokens"] == 10*M
    assert len(guard.state["baseline"]["rows"]) == 3


def test_saved_policy_fields_must_match_binding(tmp_path, finances):
    baseline, current = finances
    path = tmp_path/"planning.json"
    PlanningBudget(path,lambda:current,baseline)
    state = json.loads(path.read_text())
    state["stop_tokens"] = 250*M
    path.write_text(json.dumps(state))
    with pytest.raises(RequestBudgetExceeded,match="HOST_BASELINE_CHANGED"):
        PlanningBudget(path,lambda:current,baseline)


def test_alert_callback_follows_durable_save_once_including_restart(tmp_path, finances):
    baseline, current = finances
    path = tmp_path/"planning.json"
    notices = []
    def notify(record):
        assert json.loads(path.read_text())["alert"] == record
        notices.append(deepcopy(record))
    guard = PlanningBudget(path,lambda:current,baseline,on_alert=notify)
    current["rows"].append(row("threshold",15*M,"settled",30*M))
    guard.check(); guard.check()
    PlanningBudget(path,lambda:current,baseline,on_alert=notify).check()
    assert len(notices) == 1 and notices[0]["settled_tokens"] == 15*M


@pytest.fixture
def actual_host(tmp_path, monkeypatch, finances):
    import importlib.util
    from pathlib import Path
    import hashlib
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("g5_host_test",root/"scripts/report_host.py")
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    baseline, current = finances
    authority = {"ledger":str(tmp_path/"ledger.db"),"maximum_tokens":baseline["auth"][0],
        "model_bounds":{"m":2*M},"authorization_id":"synthetic-g5","user_authority":"synthetic owner",
        "grant_scope":{"maximum_tokens":200*M,"baseline":deepcopy(baseline),
            "baseline_sha256":hashlib.sha256(json.dumps(baseline,sort_keys=True,separators=(",",":")).encode()).hexdigest()}}
    path = tmp_path/"authority.json"
    def install():
        path.write_text(json.dumps(authority))
        host.DEPLOYMENT = {"reuse_ledger":True,"budget_authority":str(path),"budget_authority_sha256":host.sha(path)}
    monkeypatch.setattr(host,"LEDGER",tmp_path/"ledger.db")
    monkeypatch.setattr(host,"TOTAL_LIMIT",478_464_822)
    monkeypatch.setattr(host,"MODEL_BOUNDS",{"m":2*M})
    monkeypatch.setattr(host,"CONFIG",{"grant_token_limit":200*M})
    monkeypatch.setattr(host,"finance",lambda:deepcopy(current))
    install()
    return host, authority, current, install


def test_actual_host_accepts_pinned_grant_with_prior_protocol_cost(actual_host):
    host, authority, current, install = actual_host
    current["rows"].append(row("protocol",15_976,"settled"))
    host.validate_budget_authority()
    assert host.budget_scope_cost(authority["grant_scope"]["baseline"],current) == (15_976,0,False)


@pytest.mark.parametrize("change",["missing-grant","wrong-limit","wrong-baseline-hash","wrong-baseline-auth","changed-history","exhausted"])
def test_actual_host_rejects_unpinned_or_exhausted_grant(actual_host,change):
    host, authority, current, install = actual_host
    if change == "missing-grant": del authority["grant_scope"]
    elif change == "wrong-limit": authority["grant_scope"]["maximum_tokens"] = 201*M
    elif change == "wrong-baseline-hash": authority["grant_scope"]["baseline_sha256"] = "0"*64
    elif change == "wrong-baseline-auth": authority["grant_scope"]["baseline"]["auth"][0] += 1
    elif change == "changed-history": current["rows"][0][4] = "known_not_sent"
    else: current["rows"].append(row("spent",200*M+1,"settled",210*M))
    install()
    with pytest.raises((RuntimeError,RequestBudgetExceeded),match="G5_GRANT_SCOPE_REQUIRED|HOST_BASELINE_CHANGED|G5_GRANT_EXHAUSTED"):
        host.validate_budget_authority()
