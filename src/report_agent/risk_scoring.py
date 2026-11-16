"""Agent-selected grades and ranks; system-owned exact arithmetic and sensitivity."""
from . import report_state
from .assessment_results import missing_weights, score_band, scoring_weights
from .assessment_projection import assessment_receipt, record_assessment_projection

from pydantic import Field

from .calculations import sum_products
from .content_models import Contract, SourceCitation
from .errors import ActionRejected
from .method_pack import MethodPack, number


class IndicatorAssessment(Contract):
    indicator_id: str = Field(min_length=1)
    rank: int = Field(strict=True)
    grade_id: str = Field(min_length=1)
    value: str
    basis_kind: str
    sources: list[SourceCitation]
    rationale: str
    question: str = ''
    low: str | None = None
    high: str | None = None
    rank_reason: str = ''
    plausible_grades: list[str] = Field(default_factory=list)


class Assessment(Contract):
    object_id: str = Field(min_length=1)
    section_id: str = ''
    method_id: str = Field(min_length=1)
    method_version: int = Field(strict=True)
    weight_strategy_id: str = Field(min_length=1)
    indicators: list[IndicatorAssessment]


def _indicator_errors(definition, row):
    errors = []
    prefix = row.indicator_id + ': '
    grade = next((g for g in definition.grades if g.id == row.grade_id), None) if definition else None
    if grade is None:
        errors.append(prefix + 'unknown grade')
    try:
        number(row.value)
    except ValueError:
        errors.append(prefix + 'value must be finite decimal')
    assumption = row.basis_kind.endswith('assumption')
    if assumption:
        try:
            number(row.low)
            number(row.high)
        except ValueError:
            errors.append(prefix + 'low/high finite bounds required')
    return errors


def calculate(pack: dict, assessment: dict) -> dict:
    method = MethodPack.model_validate(pack)
    parsed = Assessment.model_validate(assessment)
    rows = parsed.indicators
    weights = scoring_weights(method, parsed.weight_strategy_id, len(method.indicators),
                              (row.rank for row in rows))
    if isinstance(weights, dict):
        return weights
    definitions = {indicator.id: indicator for indicator in method.indicators}
    ordered = sorted(rows, key=lambda r: list(definitions).index(r.indicator_id))
    result: dict = {'rows': []}
    for mode in ('adopted', 'low', 'high'):
        values = [getattr(r, mode) if mode != 'adopted' and r.basis_kind.endswith('assumption') else r.value for r in ordered]
        arithmetic = sum_products([[v, weights[r.rank - 1]] for r, v in zip(ordered, values)])
        result[mode] = score_band(method, arithmetic['total'])
    result['affects_level'] = len({result[m]['level'] for m in ('adopted', 'low', 'high')}) > 1
    for row in ordered:
        weight = weights[row.rank - 1]
        result['rows'].append({**row.model_dump(mode='json'), 'weight': weight,
            'score': sum_products([[row.value, weight]])['total']})
    return result


TABLE_RECORD_CONTRACT = {
    'values': ['object_label', 'ranking.number', 'evaluation.number'],
    'rows': {
        'ranking.rows': ['rank', 'indicator_id', 'indicator', 'weight', 'rank_reason'],
        'evaluation.rows': ['category', 'indicator', 'description', 'condition', 'range', 'value',
            'weight', 'score', 'explanation', 'category_id', 'indicator_id', 'grade_id', 'description_group_id'],
        'evaluation.total_rows': ['category', 'indicator', 'description', 'condition', 'range', 'value',
            'weight', 'score', 'explanation'],
    },
}


def _table_records(pack, result, label, prefix):
    """Save source descriptions and calculated values before presentation can reference them."""
    definitions = {i['id']: i for i in pack['indicators']}
    ranking, evaluation = [], []
    from .draft_assessment import display_rows
    order = {key:i for i,key in enumerate(definitions)}
    displayed = sorted(display_rows(result, pack), key=lambda row: order[row['indicator_id']])
    for row in displayed:
        definition = definitions[row['indicator_id']]
        ranking.append({'rank': row['rank'], 'indicator_id': row['indicator_id'],
            'indicator': definition['display_label'], 'weight': row['weight'], 'rank_reason': row['rank_reason']})
        grades = {g['id']: g for g in definition['grades']}
        for display in definition['presentation_rows']:
            grade = grades[display['grade_id']]
            evaluation.append({'category': definition['category_display_label'],
                'category_id': definition['category'], 'indicator': definition['display_label'],
                'indicator_id': row['indicator_id'], **display,
                'range': grade['min_value'] + '～' + grade['max_value'],
                'value': row['value'], 'weight': row['weight'], 'score': row['score'],
                'explanation': row['rationale']})
    total = {key: '' for key in TABLE_RECORD_CONTRACT['rows']['evaluation.total_rows']}
    total.update(category=pack['display_labels']['total'], score=result.get('adopted', {}).get('total', '未评分'),
                 weight=sum_products([['1', row['weight']] for row in displayed])['total'])
    return {'object_label': label, 'ranking': {'number': prefix + '-1', 'rows': ranking},
            'evaluation': {'number': prefix + '-2', 'rows': evaluation, 'total_rows': [total]}}



def _prepare_indicator(pack, row):
    row = IndicatorAssessment.model_validate(row).model_dump(mode='json')
    definition = next((i for i in pack['indicators'] if i['id'] == row['indicator_id']), None)
    problems = []
    if row['basis_kind'].endswith('assumption'):
        grades = definition.get('grades', []) if definition else []
        plausible = [g for g in grades if g['id'] in row['plausible_grades']]
        if not plausible or len(plausible) != len(row['plausible_grades']):
            problems.append(row['indicator_id'] + ': plausible_grades required')
        else:
            row['low'] = str(min(number(g['min_value']) for g in plausible))
            row['high'] = str(max(number(g['max_value']) for g in plausible))
    return row, problems


def validate_indicator_judgment(pack, row):
    """Validate one real judgment without manufacturing the other indicator rows."""
    method = MethodPack.model_validate(pack)
    normalized, problems = _prepare_indicator(pack, row)
    parsed = IndicatorAssessment.model_validate(normalized)
    definition = next((i for i in method.indicators if i.id == parsed.indicator_id), None)
    if definition is None:
        problems.append(parsed.indicator_id + ': unknown indicator')
    if parsed.rank > len(method.indicators):
        problems.append(parsed.indicator_id + ': rank outside indicator count')
    problems.extend(_indicator_errors(definition, parsed))
    return normalized


def validate_indicator_sources(cs, db, actor, plan, section_id, rows):
    from .commission_plan import _validate_sources
    _validate_sources(cs, db, actor, {'indicators': rows})

def _save_legacy_bulk_assessment(cs, db, actor, operation_id, assessment):
    """Compatibility entry for historical raw-row callers."""
    from .commission_plan import assert_writing_allowed

    plan = assert_writing_allowed(cs, db, actor)
    [b for b in plan['payload'].get('method_conventions', []) if b['key'] == 'weights']
    obj = next((o for o in plan['payload']['objects'] if o['object_id'] == assessment.get('object_id')), None)
    from .commission_plan import _confirmed
    _, _decision = _confirmed(cs, db)
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    assigned = [s for s in task['section_ids'] if any(p['section_id'] == s and p['kind'] == 'extracted' for p in plan['payload']['sections'])]
    section_id = assessment.get('section_id') or (assigned[0] if len(assigned) == 1 else None)
    candidate, result = _prepare_complete(cs, db, actor, plan, section_id, assessment)
    if 'missing_weight_ranks' in result:
        return result
    from .assessment_producers import bind_producer
    from .section_writing import enabled as system_writing
    draft_only = system_writing(cs.store)
    bind_producer(cs, db, plan['ref'], obj['object_id'], actor, bulk=True, draft_only=draft_only)
    result['status'] = 'legacy_draft' if draft_only else 'legacy_g3_scored'
    # Bulk callers predate immutable indicator submissions. Preserve their historical provenance.
    return _project_assessment(cs, db, actor, operation_id, plan, obj, section_id, candidate, result, {})


def _prepare_complete(cs, db, actor, plan, section_id, assessment):
    pack = plan['payload']['method_pack']
    candidate = Assessment.model_validate(assessment).model_dump(mode='json')
    for index, row in enumerate(candidate['indicators']):
        candidate['indicators'][index], _ = _prepare_indicator(pack, row)
    result = calculate(pack, candidate)
    validate_indicator_sources(cs, db, actor, plan, section_id, candidate['indicators'])
    return candidate, result


def _writer_input(scope, entries):
    plan = scope['plan']['payload']
    pack = plan['method_pack']
    strategy = next((choice.get('strategy_id') for choice in plan.get('method_conventions', [])
                     if choice['key'] == 'weights'), None)
    if not strategy:
        count = len(pack['indicators'])
        return missing_weights(strategy, count, range(1, count + 1))
    return dict(object_id=scope['object']['object_id'], section_id=scope['section_id'],
                method_id=pack['method_id'], method_version=pack['version'], weight_strategy_id=strategy,
                indicators=[entries[r['id']]['judgment'] for r in pack['indicators'] if entries.get(r['id'], {}).get('judgment')])


def preview_writer_assessment(cs, db, actor, scope, draft):
    candidate = _writer_input(scope, draft['rows'])
    if 'missing_weight_ranks' in candidate:
        return candidate
    if len(candidate['indicators']) == len(scope['plan']['payload']['method_pack']['indicators']):
        candidate, result = _prepare_complete(cs, db, actor, scope['plan'], scope['section_id'], candidate)
        if 'missing_weight_ranks' in result:
            return result
        # Verify every rendering invariant before the last immutable judgment commits.
        db.execute('SAVEPOINT assessment_preview')
        try:
            _project_assessment(cs, db, actor, 'preview', scope['plan'], scope['object'], scope['section_id'],
                            candidate, result, {})
        finally:
            db.execute('ROLLBACK TO assessment_preview')
            db.execute('RELEASE assessment_preview')


def save_assessment_in_transaction(cs, db, actor, operation_id, assessment=None, *, scope=None, draft=None, require_reviewed=False):
    """Derive from immutable Writer inputs inside the caller's content transaction."""
    from .assessment_producers import bind_producer
    from .assessment_results import commit_derivation, immutable_entries, unscored_result
    from .writer_assignments import bound_assignment

    if scope is None and draft is None and assessment is not None:
        return _save_legacy_bulk_assessment(cs, db, actor, operation_id, assessment)
    current = bound_assignment(cs, db, actor)
    plan, obj, section = current['plan'], current['object'], current['section_id']
    bind_producer(cs, db, plan['ref'], obj['object_id'], actor)
    entries = immutable_entries(cs, db, actor, current, draft)
    candidate = _writer_input(current, entries)
    if 'missing_weight_ranks' in candidate:
        return candidate
    pack = plan['payload']['method_pack']
    complete = len(candidate['indicators']) == len(pack['indicators'])
    if complete:
        candidate, result = _prepare_complete(cs, db, actor, plan, section, candidate)
    else:
        result = unscored_result(pack, candidate['weight_strategy_id'], plan['payload']['indicator_rank_order']['indicator_ids'],
                                 entries, draft.get('interrupted_indicators', {}))
    if 'missing_weight_ranks' in result:
        return result
    if complete:
        result.update(status='scored', level_robust=not result['affects_level'])
    assertion = commit_derivation(cs, current, operation_id, candidate['weight_strategy_id'], entries, result, require_reviewed=require_reviewed)
    native = dict(derived_assertion_id=assertion['id'], derive_operation_id=assertion['operation_id'])
    return _project_assessment(cs, db, actor, operation_id, plan, obj, section, candidate, result, native)


def _project_assessment(cs, db, actor, operation_id, plan, obj, section_id, candidate, result, native):
    from .content_models import ContentNode
    pack = plan['payload']['method_pack']
    index = plan['payload']['objects'].index(obj) + 1
    table_prefix = section_id + '.' + str(index)
    unscored = result.get('status') == 'unscored'
    table_records = _table_records(pack, result, obj['label'], table_prefix)
    assessment_ref = cs._insert(db, actor, 'Assessment', {'commission_plan_ref': plan['ref'], **candidate,
        'result': result, **native, 'table_records': table_records})
    evidence_ref = cs._insert(db, actor, 'Evidence', {'source_refs': [], 'locator': 'system calculation',
        'excerpt': '', 'input_refs': [assessment_ref, plan['ref']], 'method': 'reviewed method table lookup and decimal sum_products',
        'tool_receipt': operation_id, 'result': result})
    from .table_spec import assessment_tables
    ranking_body, evaluation_body, citations = assessment_tables(
        cs, db, plan, assessment_ref, table_records, result, obj['label'])
    base = {'qualifiers': {}, 'claim_kind': 'calculation', 'citations': citations}
    def node(kind, body):
        payload = ContentNode.model_validate({**base, 'kind': kind, 'body': {
            **body, 'section_id': section_id, 'assessment_ref': assessment_ref}}).model_dump(mode='json')
        return cs._insert(db, actor, 'ContentNode', payload)
    ranking_ref = node('table', ranking_body)
    evaluation_ref = node('table', evaluation_body)
    if unscored:
        qualification = '本草稿尚有未评分指标，不采用综合评分或风险等级。'
        text = obj['label'] + '：未评分，风险等级未确定。' + qualification
    else:
        qualification = '假设指标按现有依据取值，补充相关资料后需复核风险等级。' if result['affects_level'] else ''
        level = plan['payload']['table_specs']['evaluation']['level_labels'][result['adopted']['level']]
        if result.get('status') == 'legacy_draft':
            qualification = '批量录入的试算草稿，需按已确认的方法逐项复核。' + qualification
        if result.get('review_status') == 'pending_review':
            qualification = '指标判断待复核，当前评分及等级为试算结果。' + qualification
        text = f"{obj['label']}：综合评分{result['adopted']['total']}，风险等级{level}。" + qualification
    level_ref = node('block', {'text': text, 'assessment_part': 'level', 'level_qualification': qualification})
    generated = [ranking_ref, evaluation_ref, level_ref]
    relations = [cs._insert(db, actor, 'Relation', {'subject_ref': ref, 'object_ref': evidence_ref,
        'predicate': 'supported_by', 'provenance_kind': 'adopted_during_generation'}) for ref in generated]
    receipt = {**native, 'assessment_ref': assessment_ref, 'evidence_ref': evidence_ref, 'ranking_ref': ranking_ref,
        'evaluation_ref': evaluation_ref, 'level_ref': level_ref, 'result': result,
        'refs': dict(zip(['assessment', 'evidence', 'ranking', 'evaluation', 'level',
                         *['relation' + str(n) for n in range(len(relations))]],
                        [assessment_ref, evidence_ref, *generated, *relations]))}
    from .section_writing import enabled as system_writing
    record_assessment_projection(db, plan['ref'], obj['object_id'], receipt,
                                 select=bool(native) and system_writing(cs.store))
    return receipt


def save_assessment(cs, actor, operation_id, assessment):
    """Persist a complete judgment with reproducible calculation and rendered tables."""
    from .commission_plan import _confirmed
    return cs.operation(actor, operation_id, {'assessment': assessment},
        lambda db: save_assessment_in_transaction(cs, db, actor, operation_id, assessment),
        binding_identity=lambda db, result: _confirmed(cs, db)[0]['ref'])


def validate_outcome(cs, db, plan, object_id, score_ref, level_ref, basis_refs, unresolved, *, draft=False):
    assessment_ref = cs._read(db, score_ref)['payload']['body'].get('assessment_ref')
    assessment_receipt(db, assessment_ref) if assessment_ref else None
    cs._read(db, assessment_ref)['payload']
    return assessment_ref


def create_planned_section(cs, actor, operation_id, section_id, assessment_refs=()):
    """Copy approved source text, inserting only system-calculated result slots."""
    from .commission_plan import assert_writing_allowed, _confirmed
    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        if not plan or not plan['payload'].get('method_pack'):
            raise ActionRejected('PLANNED_SECTION_METHOD_REQUIRED')
        assignment = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        if section_id not in assignment['section_ids']:
            raise ActionRejected('PLANNED_SECTION_ASSIGNMENT_REQUIRED')
        return create_planned_section_in_transaction(cs, db, actor, plan, section_id, assessment_refs)
    return cs.operation(actor, operation_id, {'planned_section': section_id, 'assessment_refs': list(assessment_refs)}, save,
        binding_identity=lambda db, result: _confirmed(cs, db)[0]['ref'])


def create_planned_section_in_transaction(cs, db, actor, plan, section_id, assessment_refs=(), *, positional_anchors=False):
    """Trusted assembler and writer API share the same validated projection."""
    from .commission_plan import fixed_section_text, fixed_source_views, _confirmed
    from .content_models import ContentNode
    section = next((s for s in plan['payload']['sections'] if s['section_id'] == section_id), None)
    text = fixed_section_text(section)
    views = [{**view, 'source_id': cs._read(db, view['source_ref'])['payload']['source_id']}
             for view in fixed_source_views(section)]
    bound, receipts = {}, []
    for ref in assessment_refs:
        record = cs._read(db, ref)
        obj = record['payload']['object_id']
        receipt = assessment_receipt(db, ref)
        bound[obj] = record['payload']['result']
        receipts.append(receipt)
    slots = section.get('result_bindings', [])
    aggregate = bool(section.get('result_composition')) or any(s['field'] in ('object_count', 'level_count') for s in slots)
    {s['object_id'] for s in slots if s['object_id'] is not None}
    if aggregate:
        _, decision = _confirmed(cs, db)
        reduced = {r['object_id'] for r in decision['payload']['reductions']}
        {o['object_id'] for o in plan['payload']['objects'] if o['included']} - reduced
        {b['level'] for b in plan['payload']['method_pack']['risk_bands']}
    if section.get('result_composition'):
        from .commission_results import composed_nodes
        nodes = composed_nodes(plan['payload'], section, bound,
            [c for c in decision['payload'].get('template_decisions', []) if c['section_id'] in {p['section_id'] for p in section['result_composition']}],
            decision['payload'].get('required_material_issues', []), positional_anchors=positional_anchors)
        root = ContentNode.model_validate({'kind': 'block', 'body': {'text': section['section_id'] + ' ' + section['title'],
            'section_id': section_id}, 'qualifiers': {}, 'claim_kind': 'structure', 'citations': section['sources']}).model_dump(mode='json')
        all_nodes = [root, *nodes]
        for node in all_nodes:
            node['body'].update(planned_section=True, commission_plan_ref=plan['ref'], commission_confirmation_ref=decision['ref'], assessment_refs=list(assessment_refs))
        refs = [cs._insert(db, actor, 'ContentNode', node) for node in all_nodes]
        relations = [cs._insert(db, actor, 'Relation', {'subject_ref': refs[0], 'object_ref': ref,
            'predicate': 'contains', 'position': n, 'provenance_kind': 'adopted_during_generation'}) for n, ref in enumerate(refs[1:])]
        for ref in refs:
            receipt = {'node_ref': ref, 'commission_plan_ref': plan['ref'], 'assessment_refs': list(assessment_refs),
                'section_id': section_id, 'group_ref': refs[0], 'commission_confirmation_ref': decision['ref']}
            if ref == refs[0]:
                receipt['node_refs'] = refs
            report_state.record_section(db, ref, receipt)
        return {'node_ref': refs[0], 'refs': {**{'section': refs[0]}, **{'part' + str(i): ref for i, ref in enumerate(refs[1:])},
            **{'relation' + str(i): ref for i, ref in enumerate(relations)}}, 'assessment_refs': list(assessment_refs)}
    for slot in slots:
        if slot['field'] in ('object_count', 'level_count'):
            value = str(len(bound) if slot['field'] == 'object_count' else sum(r.get('adopted', {}).get('level') == slot['level'] for r in bound.values()))
            text = text.replace(slot['old'], value, 1)
            continue
        result = bound[slot['object_id']]
        receipt = next(r for r in receipts if cs._read(db, r['assessment_ref'])['payload']['object_id'] == slot['object_id'])
        if slot['field'] == 'assessment_text':
            value = cs._read(db, receipt['level_ref'])['payload']['body']['text']
        else:
            value = ('未评分' if slot['field'] == 'total' else '未确定') if result.get('status') == 'unscored' else result['adopted'][slot['field']]
            if slot['field'] == 'level':
                if plan['payload'].get('table_specs') and result.get('status') != 'unscored':
                    value = plan['payload']['table_specs']['evaluation']['level_labels'][value]
                value += '。' + cs._read(db, receipt['level_ref'])['payload']['body']['level_qualification'] if result.get('status') != 'unscored' and result['affects_level'] else ''
        text = text.replace(slot['old'], value, 1)
    payload = ContentNode.model_validate({'kind': 'block', 'body': {'text': text,
        'section_id': section_id, 'planned_section': True, 'commission_plan_ref': plan['ref'],
        'assessment_refs': list(assessment_refs), **({'source_views': views} if views else {})}, 'qualifiers': {},
        'citations': section['sources'], 'claim_kind': 'calculation' if slots else 'structure',
        'working_notes': 'Source copy and reviewed literal/result substitutions.'}).model_dump(mode='json')
    ref = cs._insert(db, actor, 'ContentNode', payload)
    receipt = {'node_ref': ref, 'commission_plan_ref': plan['ref'], 'assessment_refs': list(assessment_refs),
               'section_id': section_id}
    report_state.record_section(db, ref, receipt)
    return {'node_ref': ref, 'refs': {'section': ref}, 'assessment_refs': list(assessment_refs)}
