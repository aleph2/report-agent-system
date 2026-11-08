"""Host-owned planning stop-loss and grant accounting; no ledger mutation."""
from . import legacy_state as legacy
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
from .request_budget import RequestBudgetExceeded
from .store import digest


def budget_scope_cost(before, now):
    old = {x[0]: x for x in before['rows']}
    rows = {x[0]: x for x in now['rows']}
    if now['auth'] != before['auth'] or any(rows.get(k) != v for k,v in old.items()):
        raise RequestBudgetExceeded('HOST_BASELINE_CHANGED')
    diff = [x for k,x in rows.items() if k not in old]
    return (sum(x[3] or 0 for x in diff), sum(x[2] for x in diff if x[4] in ('reserved','unknown')),
            any(x[4] == 'unknown' for x in diff))


def grant_scope_cost(baseline, now):
    return budget_scope_cost(baseline, now)


class PlanningBudget:
    def __init__(self, path, finance, baseline, alert_tokens=15_000_000, stop_tokens=25_000_000, on_alert=None):
        if any(type(n) is not int for n in (alert_tokens,stop_tokens)) or not 0 < alert_tokens < stop_tokens:
            raise ValueError('PLANNING_LIMITS_INVALID')
        self.path, self.finance, self.baseline = Path(path), finance, deepcopy(baseline)
        self.alert_tokens, self.stop_tokens = alert_tokens, stop_tokens
        self.on_alert = on_alert
        self.lock = RLock()
        self.binding = digest({'baseline':baseline,'alert':alert_tokens,'stop':stop_tokens})
        self.state = {'binding':self.binding,'baseline':deepcopy(baseline),'alert_tokens':alert_tokens,'stop_tokens':stop_tokens,
                      'alert':None,'stop':None}
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if (self.state.get('binding') != self.binding or self.state.get('baseline') != baseline
                    or self.state.get('alert_tokens') != alert_tokens or self.state.get('stop_tokens') != stop_tokens):
                raise RequestBudgetExceeded('HOST_BASELINE_CHANGED')
        else:
            self._save()

    def _save(self):
        temporary = self.path.with_suffix(self.path.suffix + '.tmp')
        with temporary.open('w',encoding='utf-8') as f:
            json.dump(self.state,f,ensure_ascii=False,indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(temporary,self.path)

    def check(self, approvable=False):
        with self.lock:
            used, held, unknown = budget_scope_cost(self.baseline,self.finance())
            observation = {'settled_tokens':used,'held_tokens':held,'unknown':unknown,'approvable_plan':approvable}
            changed = False
            new_alert = False
            if used >= self.alert_tokens and not approvable and self.state['alert'] is None:
                self.state['alert'] = {**observation,'at_utc':datetime.now(timezone.utc).isoformat()}
                changed = new_alert = True
            if used >= self.stop_tokens and not approvable and self.state['stop'] is None:
                self.state['stop'] = {**observation,'at_utc':datetime.now(timezone.utc).isoformat(),
                                      'reason':'HOST_PLANNING_STOP_LOSS','automatic_resume':False}
                changed = True
            if changed:
                self._save()
            if new_alert and self.on_alert:
                self.on_alert(deepcopy(self.state['alert']))
            if self.state['stop'] is not None:
                raise RequestBudgetExceeded('HOST_PLANNING_STOP_LOSS')
            return {**observation,'alert':self.state['alert'],'stop':self.state['stop']}


def approvable_plan(workspace):
    """A current submitted, validated checkpoint, never an unfinished draft."""
    from .content_store import ContentStore
    from .commission_plan import read_plan, unresolved_sources, method_questions
    from .commission_requirements import require_complete
    from .errors import ActionRejected
    cs = ContentStore(workspace.store)
    try:
        record = read_plan(workspace.store)
        if not record:
            return False
        plan = record['payload']
        require_complete(cs,plan)
        if any(unresolved_sources(s) for s in plan['sections']) or method_questions(plan):
            return False
        for issue in legacy.get_report_issues(workspace.store,[]):
            checkpoint = legacy.get_commission_checkpoint(workspace.store, issue['id'])
            if not checkpoint or checkpoint['plan_ref'] != record['ref'] or checkpoint.get('requirements_ref') != plan.get('requirements_ref'):
                continue
            if not (workspace.store.root / checkpoint['brief_path']).is_file():
                continue
            if issue.get('decision_origin') != 'operator':
                return True
            decision = json.loads(issue['decision'])
            if decision.get('approved') is True and decision.get('plan_ref') == record['ref']:
                return True
    except (ActionRejected, KeyError, ValueError):
        return False
    return False


async def watch_planning(awaitable, guard, is_approvable):
    task = asyncio.create_task(awaitable)
    try:
        while True:
            guard.check(is_approvable())
            done, _ = await asyncio.wait({task},timeout=1)
            if done:
                guard.check(is_approvable())
                return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)
