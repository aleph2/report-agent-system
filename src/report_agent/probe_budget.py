"""Host-owned single-slope stop-loss; never changes financial records."""
from copy import deepcopy
import json

from .planning_budget import budget_scope_cost
from .request_budget import RequestBudgetExceeded
from .token_budget import current_model_token_bound


class ProbeBudget:
    def __init__(self, finance, original_baseline, stage_baseline, *,
                 maximum_tokens=1_500_000, overall_limit=20_000_000,
                 preserved_hold, writer_model):
        if (type(maximum_tokens) is not int or not 0 < maximum_tokens <= 2_200_000
                or type(overall_limit) is not int or not 0 < overall_limit <= 20_000_000):
            raise ValueError('PROBE_LIMIT_INVALID')
        if (not isinstance(preserved_hold, list) or len(preserved_hold) != 8
                or preserved_hold[1:6] != [writer_model, 2_000_000, None, 'reserved', None]
                or not isinstance(preserved_hold[0], str) or not preserved_hold[0]):
            raise ValueError('PROBE_PRESERVED_HOLD_INVALID')
        self.finance = finance
        self.original_baseline = deepcopy(original_baseline)
        self.stage_baseline = deepcopy(stage_baseline)
        self.preserved_hold = deepcopy(preserved_hold)
        self.maximum_tokens, self.overall_limit = maximum_tokens, overall_limit
        self.writer_model = writer_model
        self.bounds = json.loads(self.stage_baseline['auth'][1])
        if self.bounds.get(writer_model) != 2_000_000:
            raise ValueError('PROBE_WRITER_BOUND_REQUIRED')
        budget_scope_cost(self.original_baseline, self.stage_baseline)
        if next((r for r in self.stage_baseline['rows'] if r[0] == preserved_hold[0]), None) != preserved_hold:
            raise ValueError('PROBE_PRESERVED_HOLD_INVALID')

    def check(self):
        now = self.finance()
        if next((r for r in now['rows'] if r[0] == self.preserved_hold[0]), None) != self.preserved_hold:
            raise RequestBudgetExceeded('PROBE_PRESERVED_HOLD_CHANGED')
        used, held, _ = budget_scope_cost(self.stage_baseline, now)
        overall_used, overall_held, _ = budget_scope_cost(self.original_baseline, now)
        if used + held > self.maximum_tokens:
            raise RequestBudgetExceeded('PROBE_TOKEN_LIMIT')
        if overall_used + overall_held > self.overall_limit:
            raise RequestBudgetExceeded('PROBE_OVERALL_TOKEN_LIMIT')
        old = {r[0] for r in self.original_baseline['rows']}
        added = [r for r in now['rows'] if r[0] not in old]
        if any(r[1] != self.writer_model for r in added):
            raise RequestBudgetExceeded('PROBE_WRITER_MODEL_ONLY')
        if any(r[4] == 'bound_violation' for r in added):
            raise RequestBudgetExceeded('PROBE_TOKEN_BOUND_VIOLATION')
        stage_old = {r[0] for r in self.stage_baseline['rows']}
        pending = [r for r in added if r[0] not in stage_old and r[4] in ('reserved', 'unknown')]
        # Baseline holds remain immutable/charged; only this stage's current request may be pending.
        if len(pending) > 1 or any(r[4] == 'unknown' for r in pending):
            raise RequestBudgetExceeded('PROBE_UNRESOLVED_ATTEMPT')
        return used, held

    def observation(self):
        used, held, _ = budget_scope_cost(self.stage_baseline, self.finance())
        bound = current_model_token_bound(self.writer_model) or self.bounds[self.writer_model]
        return {'scope_id': 'single-slope-probe', 'maximum_tokens': self.maximum_tokens,
                'recorded_tokens': used, 'reserved_or_unknown_upper_bounds': held,
                'remaining_for_new_reservations': max(0, self.maximum_tokens-used-held),
                'model_reservation_bounds': {self.writer_model: bound},
                'includes_original_phases': False}
