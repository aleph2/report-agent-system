"""Calculator arithmetic and immutable commission-bound derivations."""
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from . import assertions
from .assertion_host import AssertionHost, Grant, resource_digest
from .calculations import sum_products
from .method_pack import MethodPack, number
from .store import digest


def score_band(method, total, *, allow_unclassified=False):
    value = number(total)
    bands = [b for b in method.risk_bands
             if (value >= number(b.lower) if b.lower_inclusive else value > number(b.lower))
             and (value <= number(b.upper) if b.upper_inclusive else value < number(b.upper))]
    if not bands and allow_unclassified:
        return {'total': total, 'level': None}
    return {'total': total, 'level': bands[0].level}


def missing_weights(strategy, indicator_count, ranks):
    return {'status': 'unscored', 'weight_strategy_id': strategy,
            'indicator_count': indicator_count, 'missing_weight_ranks': list(ranks)}


def scoring_weights(method, strategy, indicator_count, ranks=()):
    row = next((row for table in method.weight_tables if table.id == strategy
                for row in table.rows if row.indicator_count == indicator_count), None)
    weights = row.weights if row is not None else []
    positions = set(range(1, indicator_count + 1)).union(ranks)
    missing = sorted(rank for rank in positions
                     if not 1 <= rank <= len(weights) or not weights[rank - 1].strip())
    if row is None or missing:
        return missing_weights(strategy, indicator_count, missing)
    return weights


def unscored_result(pack, strategy, ranks, entries, interruptions):
    """An interval uses explicit alternatives when supplied, else the entire approved grade domain."""
    method = MethodPack.model_validate(pack)
    definitions = {rule.id: rule for rule in method.indicators}
    weights = scoring_weights(method, strategy, len(ranks))
    if isinstance(weights, dict):
        return weights
    minima, maxima, missing, rows, open_rows = [], [], [], [], []
    for rank, (indicator, weight) in enumerate(zip(ranks, weights), 1):
        entry = entries.get(indicator, {})
        if row := entry.get('judgment'):
            low = row['low'] if row['basis_kind'].endswith('assumption') else row['value']
            high = row['high'] if row['basis_kind'].endswith('assumption') else row['value']
            rows.append({**row, 'weight': weight, 'score': sum_products([[row['value'], weight]])['total']})
        else:
            missing.append(indicator)
            original = entry.get('input', {})
            reason = original.get('missing') or '本指标尚未评定；尚不评价资料是否充足。'
            if indicator in interruptions:
                reason = '保存被拒绝而中断：' + '；'.join(str(r) for r in interruptions[indicator].get('refusals', []))
            open_rows.append(dict(indicator_id=indicator, rank=rank, weight=weight, reason=reason,
                question=original.get('question') or '请补充或复核本指标判断。',
                sources=entry.get('sources', []), alternatives=entry.get('claim', {}).get('alternatives', [])))
            alternatives = set(entry.get('claim', {}).get('alternatives', ()))
            grades = {g.id: g for g in definitions[indicator].grades}
            domain = [grades[g] for g in alternatives] if alternatives else list(grades.values())
            low = min((g.min_value for g in domain), key=number)
            high = max((g.max_value for g in domain), key=number)
        minima.append([low, weight])
        maxima.append([high, weight])
    low = score_band(method, sum_products(minima)['total'], allow_unclassified=True)
    high = score_band(method, sum_products(maxima)['total'], allow_unclassified=True)
    robust = low['level'] == high['level'] if low['level'] and high['level'] else None
    return dict(status='unscored', low=low, high=high, level_robust=robust,
                missing_indicators=missing, interrupted_indicators=sorted(interruptions), rows=rows, open_rows=open_rows)


def immutable_entries(cs, db, actor, scope, draft):
    from .operation_identity import bound_native_id
    from .writer_judgments import _saved, project, read_progress
    host = AssertionHost(cs.store.root)
    principal = str(uuid5(NAMESPACE_URL, actor.id))
    subject = scope['object']['object_id']
    known = host.commission.produced_ids(actor=principal, task=actor.task_id, subject=subject, kind='judgment')
    verified = {}
    for indicator, entry in draft['rows'].items():
        key = entry.get('assertion_id')
        item = host.commission.judgment_details(key)
        operation = bound_native_id(principal, 'save_judgment', item['operation'])
        saved, item = _saved(host, operation, key, scope['assignment_digest'])
        item.get('criterion_authority', {})
        verified[indicator] = project(saved, item)
    for key in known - {r['assertion_id'] for r in verified.values()}:
        item = host.commission.judgment_details(key)
    read_progress(cs.store, scope['assignment_digest'], db)
    return verified


def _operation(assignment_digest, operation_id):
    task = digest([assignment_digest, 'assessment'])
    principal = str(uuid5(NAMESPACE_URL, 'report-agent:assessment-calculator'))
    return principal, task, digest([task, operation_id])


def lookup_committed_derivation(store, assignment_digest, operation_id):
    from .operation_identity import bound_native_id
    if not (store.root / 'assertions.sqlite3').is_file():
        return None
    principal, _task, call = _operation(assignment_digest, operation_id)
    saved = AssertionHost(store.root).recover_receipt(bound_native_id(principal, 'derive_result', call))
    if saved is None:
        return None
    return saved['result']


def commit_derivation(cs, scope, operation_id, strategy, entries, result, *, require_reviewed=False):
    from .assertions.schema.kinds import Derived

    plan, decision = scope['plan'], scope['decision']
    pack = plan['payload']['method_pack']
    approved = dict(id=pack['method_id'], version=pack['version'], digest=digest(pack))
    rule = dict(plan=plan['ref'], decision=decision['ref'], method=approved, strategy=strategy,
                rank_order=plan['payload']['indicator_rank_order'], calculation='rank-weighted-sum-v1')
    version = resource_digest(rule)
    subject = scope['object']['object_id']
    inputs = [entries[i['id']]['assertion_id'] for i in pack['indicators'] if i['id'] in entries]
    principal, task, op = _operation(scope['assignment_digest'], operation_id)
    packet = frozenset([*inputs, version])
    host = AssertionHost(cs.store.root)
    # Bind the same native call to the same input selection and arithmetic across task-DB rollback.
    attempt = digest([op, version, inputs, result])
    rules = {version: dict(version=version, **rule)}
    grant = Grant(principal, 'calculator', task, attempt, digest(plan['ref']), frozenset([subject]),
                  packet, frozenset(['derive_result']), resources={'rules': rules})
    ctx = host.bind(grant, native_call_id=op, action='derive_result')
    previous = host.recover_receipt(ctx.operation_id)
    if previous:
        claim = previous['result']['claim']
        result['review_status'] = claim['assessment']['status']
        # Replay still requires the original calculator grant to be live.
        with ctx.read() as (_, live):
            if 'derive_result' not in live.actions:
                raise PermissionError('Calculator grant no longer authorizes this action')
        return previous['result']
    read_grant = Grant(principal, 'calculator', task, 'read/' + attempt, digest(plan['ref']),
                       frozenset([subject]), packet, frozenset())
    read_ctx = host.issue_once(read_grant, 'derive_result', op)
    from .assertions.queries import assertion_states
    with read_ctx.read() as (db, live):
        states = assertion_states(db)
        eligible = all(key in live.packet and states.get(key, {}).get('status') in ('confirmed', 'endorsed')
                       for key in inputs)
    status = result['status']
    if status == 'scored' and not eligible:
        status = 'pending_review'
    result['review_status'] = status
    summary = dict(status=status, low=result['low'], high=result['high'], level_robust=result['level_robust'],
                   missing_indicators=result.get('missing_indicators', []),
                   interrupted_indicators=result.get('interrupted_indicators', []))
    strength, value = 'undetermined', None
    if status == 'scored':
        summary['adopted'] = result['adopted']
        strength = 'provisional' if any(e['kind'] == 'assumption' for e in entries.values()) else 'determined'
        value = result['adopted']['total']
    elif status == 'pending_review':
        summary['draft_arithmetic'] = result['adopted']
    claim = Derived.model_validate(dict(kind='derived', inputs=inputs, rule_version=version, strength=strength,
                                        value=value, assessment=summary)).model_dump(mode='json')
    expected = dict(subject=subject, claim=claim)
    grant = replace(grant, resources={'rules': rules, 'receipts': {resource_digest(expected): expected}})
    ctx = host.issue_once(grant, 'derive_result', op)
    return assertions.derive_result(ctx, **expected)
