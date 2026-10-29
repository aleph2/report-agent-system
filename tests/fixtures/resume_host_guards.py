"""Resume-host guards. This module performs no network or ledger writes."""
import hashlib, json
from report_agent.request_budget import RequestBudgetExceeded


def cumulative_case_cost(rows, baseline):
    """Rows are (id, model, reserved, used, state, ...); baseline predates both phases."""
    current = {row[0]: tuple(row) for row in rows}
    original = {row[0]: tuple(row) for row in baseline}
    if len(current) != len(rows) or len(original) != len(baseline):
        raise ValueError('DUPLICATE_LEDGER_ID')
    if any(current.get(key) != value for key, value in original.items()):
        raise ValueError('ORIGINAL_BASELINE_CHANGED')
    included = [row for key, row in current.items() if key not in original]
    used = sum(row[3] or 0 for row in included)
    held = sum(row[2] for row in included if row[4] in {'reserved', 'unknown'})
    return {'attempts':len(included), 'used':used, 'held':held, 'total':used+held}


def guard_cumulative(rows, baseline, limit):
    cost = cumulative_case_cost(rows, baseline)
    if cost['total'] > limit:
        raise RequestBudgetExceeded('HOST_TOKEN_BUDGET_REACHED')
    return cost


def canonical_wire_sha256(content):
    def unique_pairs(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    body=json.loads(content,object_pairs_hook=unique_pairs,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('INVALID_JSON_CONSTANT')))
    if not isinstance(body,dict):
        raise ValueError('MODEL_REQUEST_JSON_OBJECT_REQUIRED')
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def guard_unknown_wire(request, blocked_wire_sha256, blocked_canonical_sha256=None):
    if hashlib.sha256(request.content).hexdigest() == blocked_wire_sha256:
        raise RequestBudgetExceeded('HOST_PRIOR_UNKNOWN_WIRE_FENCED')
    if blocked_canonical_sha256 is not None and canonical_wire_sha256(request.content) == blocked_canonical_sha256:
        raise RequestBudgetExceeded('HOST_PRIOR_UNKNOWN_WIRE_FENCED')


def binding_state_hash(store, task_id):
    if not isinstance(task_id,str) or not task_id:
        raise ValueError('RESUME_TASK_ID_INVALID')
    keys={'manifest','role_model_services','role_generation','decision_data_binding',
          'source_search_view','source_search_binding','tool_discovery_binding',
          'tool_discovery_registry','learning_config','model_recovery_policy',
          'source_use_authority_binding','source_use_task_binding:'+task_id}
    return {key:hashlib.sha256(json.dumps(store.get(key),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest() for key in keys}


def verify_binding_state(store, task_id, expected):
    if store.get('decision_observation'):
        raise ValueError('RESUME_DECISION_OBSERVATION_TERMINAL')
    actual=binding_state_hash(store,task_id)
    if not isinstance(expected,dict) or actual!=expected:
        raise ValueError('RESUME_BINDING_STATE_CHANGED')
