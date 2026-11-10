"""Agent-selected grades and ranks; system-owned exact arithmetic and sensitivity."""
from . import legacy_state as legacy, report_state
from .assessment_results import score_band
from .assessment_projection import assessment_receipt, record_assessment_projection, score_blocker
from typing import Literal

from pydantic import Field, ValidationError

from .calculations import sum_products
from .content_models import Contract, SourceCitation
from .errors import ActionForbidden, ActionRejected
from .method_pack import MethodPack, number


class IndicatorAssessment(Contract):
    indicator_id: str = Field(min_length=1)
    rank: int = Field(strict=True, ge=1)
    grade_id: str = Field(min_length=1)
    value: str
    basis_kind: Literal['direct_evidence', 'applied_guideline', 'indirect_assumption', 'no_evidence_assumption']
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
    method_version: int = Field(strict=True, ge=1)
    weight_strategy_id: str = Field(min_length=1)
    indicators: list[IndicatorAssessment] = Field(min_length=1, max_length=1000)


def _indicator_errors(definition, row):
    errors = []
    prefix = row.indicator_id + ': '
    grade = next((g for g in definition.grades if g.id == row.grade_id), None) if definition else None
    if grade is None:
        errors.append(prefix + 'unknown grade')
    try:
        value = number(row.value)
        if grade and not number(grade.min_value) <= value <= number(grade.max_value):
            errors.append(prefix + 'value outside chosen grade')
    except ValueError:
        errors.append(prefix + 'value must be finite decimal')
        value = None
    assumption = row.basis_kind.endswith('assumption')
    if not row.rationale.strip():
        errors.append(prefix + 'rationale required')
    if row.basis_kind != 'no_evidence_assumption' and not row.sources:
        errors.append(prefix + 'source required')
    if row.basis_kind == 'no_evidence_assumption':
        if row.sources:
            errors.append(prefix + 'no-evidence assumption cannot invent sources')
        if definition and grade and number(grade.max_value) != max(number(g.max_value) for g in definition.grades):
            errors.append(prefix + 'no-evidence assumption requires adverse grade')
    if assumption:
        if not row.question.strip():
            errors.append(prefix + 'question required')
        try:
            low, high = number(row.low), number(row.high)
            if value is not None and not low <= value <= high:
                errors.append(prefix + 'adopted value outside ordered bounds')
            if definition and any(not any(number(g.min_value) <= v <= number(g.max_value) for g in definition.grades) for v in (low, high)):
                errors.append(prefix + 'bound outside plausible grade domains')
        except ValueError:
            errors.append(prefix + 'low/high finite bounds required')
    elif row.low is not None or row.high is not None:
        errors.append(prefix + 'only assumptions have low/high bounds')
    return errors


def calculate(pack: dict, assessment: dict) -> dict:
    errors = []
    try:
        method = MethodPack.model_validate(pack)
    except ValueError as exc:
        raise ActionRejected('ASSESSMENT_INVALID: method pack: ' + str(exc)) from exc
    # Validate rows independently so one malformed value does not hide rank or basis errors.
    rows = []
    for index, row in enumerate(assessment.get('indicators', [])):
        try:
            rows.append(IndicatorAssessment.model_validate(row))
        except ValidationError as exc:
            errors.extend(f'indicator[{index}].' + '.'.join(map(str, e['loc'])) + ': ' + e['msg'] for e in exc.errors())
    try:
        Assessment.model_validate(assessment)
    except ValidationError as exc:
        errors.extend('.'.join(map(str, e['loc'])) + ': ' + e['msg'] for e in exc.errors() if not e['loc'] or e['loc'][0] != 'indicators')
    if assessment.get('method_id') != method.method_id or assessment.get('method_version') != method.version:
        errors.append('method identity/version mismatch')
    table = next((t for t in method.weight_tables if t.id == assessment.get('weight_strategy_id')), None)
    weights = next((r.weights for r in table.rows if r.indicator_count == len(method.indicators)), None) if table else None
    if weights is None:
        errors.append('weight strategy/count unavailable')
    definitions = {i.id: i for i in method.indicators}
    ids = [r.indicator_id for r in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(definitions):
        errors.append('indicator set missing, extra or duplicate')
    ranks = [r.rank for r in rows]
    if sorted(ranks) != list(range(1, len(definitions) + 1)):
        errors.append('rank must contain each position exactly once')
    for row in rows:
        errors.extend(_indicator_errors(definitions.get(row.indicator_id), row))
    if errors:
        raise ActionRejected('ASSESSMENT_INVALID: ' + '; '.join(dict.fromkeys(errors)))
    ordered = sorted(rows, key=lambda r: list(definitions).index(r.indicator_id))
    assert weights is not None  # The unavailable strategy is reported with other input errors above.
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
    for row in result['rows']:
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
    total.update(category=pack['display_labels']['total'], score=result['adopted']['total'],
                 weight=sum_products([['1', row['weight']] for row in result['rows']])['total'])
    return {'object_label': label, 'ranking': {'number': prefix + '-1', 'rows': ranking},
            'evaluation': {'number': prefix + '-2', 'rows': evaluation, 'total_rows': [total]}}


def _projected_tables(cs, db, plan, assessment_ref, table_records, result, label):
    from .table_spec import render_saved_table
    from .store import digest
    bodies, origins = {}, {}
    for role in ('ranking', 'evaluation'):
        spec = plan['payload']['table_specs'][role]
        bodies[role] = render_saved_table(cs, db, plan['ref'], assessment_ref, spec['table_type'])
        origins[role] = bodies[role].pop('row_origins')
        bodies[role]['assessment_part'] = role
    # Semantic field bindings locate annotations even when a specification reorders columns or rows.
    def column(role, field):
        spec = plan['payload']['table_specs'][role]
        from .table_spec import column_keys
        keys = column_keys(spec)
        matches = [n for n, key in enumerate(keys) if spec['column_bindings'][key] == field]
        if len(matches) != 1:
            raise ActionRejected('TABLE_SPEC_ANNOTATION_BINDING_REQUIRED: ' + field)
        return matches[0]
    issues, citations = [], []
    for row in result['rows']:
        sources = []
        for citation in row['sources']:
            title = cs._read(db, citation['source_ref'])['payload']['source_metadata'].get('title')
            if not title:
                raise ActionRejected('ASSESSMENT_READABLE_SOURCE_TITLE_REQUIRED')
            sources.append({'document': title, 'page': citation['locator']})
            if citation not in citations:
                citations.append(citation)
        if not row['basis_kind'].endswith('assumption'):
            continue
        positions = [n for n, origin in enumerate(origins['evaluation'])
                     if origin['binding'] == 'evaluation.rows' and
                     table_records['evaluation']['rows'][origin['index']]['indicator_id'] == row['indicator_id']]
        if not positions:
            raise ActionRejected('TABLE_SPEC_ASSUMPTION_ROW_REQUIRED')
        issues.append({'id': digest([assessment_ref, row['indicator_id']]), 'kind': row['basis_kind'],
            'object_label': label, 'basis': row['rationale'], 'sources': sources,
            'adopted_value': row['value'], 'question': row['question'],
            'anchor': {'row': min(positions), 'column': column('evaluation', 'value')},
            'affects_level': result['affects_level']})
    bodies['evaluation']['material_issues'] = issues
    return bodies['ranking'], bodies['evaluation'], citations


def _prepare_indicator(pack, row):
    row = IndicatorAssessment.model_validate(row).model_dump(mode='json')
    definition = next((i for i in pack['indicators'] if i['id'] == row['indicator_id']), None)
    problems = []
    if not row['rank_reason'].strip():
        problems.append(row['indicator_id'] + ': rank_reason required')
    if row['basis_kind'].endswith('assumption'):
        grades = definition.get('grades', []) if definition else []
        if row['basis_kind'] == 'no_evidence_assumption':
            # No evidence can exclude a grade from the uncertainty interval.
            row['plausible_grades'] = [g['id'] for g in grades]
        plausible = [g for g in grades if g['id'] in row['plausible_grades']]
        if not plausible or len(plausible) != len(row['plausible_grades']) or row['grade_id'] not in row['plausible_grades']:
            problems.append(row['indicator_id'] + ': plausible_grades required, including adopted grade')
        else:
            row['low'] = str(min(number(g['min_value']) for g in plausible))
            row['high'] = str(max(number(g['max_value']) for g in plausible))
    return row, problems


def validate_indicator_judgment(pack, row):
    """Validate one real judgment without manufacturing the other indicator rows."""
    method = MethodPack.model_validate(pack)
    try:
        normalized, problems = _prepare_indicator(pack, row)
    except ValidationError as error:
        raise ActionRejected('ASSESSMENT_INVALID: ' + str(error)) from error
    parsed = IndicatorAssessment.model_validate(normalized)
    definition = next((i for i in method.indicators if i.id == parsed.indicator_id), None)
    if definition is None:
        problems.append(parsed.indicator_id + ': unknown indicator')
    if parsed.rank > len(method.indicators):
        problems.append(parsed.indicator_id + ': rank outside indicator count')
    problems.extend(_indicator_errors(definition, parsed))
    if problems:
        raise ActionRejected('ASSESSMENT_INVALID: ' + '; '.join(dict.fromkeys(problems)))
    return normalized


def validate_indicator_sources(cs, db, actor, plan, section_id, rows):
    """Use the canonical source, permission and role checks for an indicator draft."""
    from .commission_plan import _validate_sources
    from .content_models import Ref
    pack = plan['payload']['method_pack']
    _validate_sources(cs, db, actor, {'indicators': rows})
    roles = legacy.get_commission_source_roles(db, {})
    templates = {r['id'] for r in roles.values() if r['purpose'] == 'template'}
    template_refs = {Ref.model_validate(c['source_ref']).key() for s in plan['payload']['sections'] if s['kind'] == 'fixed' for c in s['sources']}
    factual_refs = {Ref.model_validate(c['source_ref']).key() for s in plan['payload']['sections'] if s['section_id'] == section_id for c in s['sources']}
    method_refs = {Ref.model_validate(c['source_ref']).key() for c in pack['sources']}
    source_pins = {}
    def source_pin(ref):
        key = Ref.model_validate(ref).key()
        if key not in source_pins:
            payload = cs._read(db, ref)['payload']
            values = tuple(payload.get(field) for field in ('source_id', 'file_digest', 'content'))
            source_pins[key] = values if key[0] == 'SourceArtifact' and all(
                isinstance(value, str) and value.strip() for value in values) else None
        return source_pins[key]
    method_pins = {pin for citation in pack['sources']
                   if (pin := source_pin(citation['source_ref'])) is not None}
    def method_source(ref):
        return (Ref.model_validate(ref).key() in method_refs or
                (source_pin(ref) is not None and source_pin(ref) in method_pins))
    customer_ids = {r['id'] for r in roles.values() if r['purpose'] == 'commission'}
    # A second frozen capture of the same guideline is still method evidence.
    factual_refs -= {key for key in factual_refs if method_source(
        {'type': key[0], 'id': key[1], 'version': key[2]})} | template_refs
    for row in rows:
        actual = {Ref.model_validate(c['source_ref']).key() for c in row['sources']}
        if row['basis_kind'] != 'no_evidence_assumption' and not actual & factual_refs:
            raise ActionRejected('ASSESSMENT_FACTUAL_SOURCE_REQUIRED: ' + row['indicator_id'])
        if row['basis_kind'] == 'applied_guideline' and not any(method_source(c['source_ref']) for c in row['sources']):
            raise ActionRejected('ASSESSMENT_GUIDELINE_RULE_SOURCE_REQUIRED: ' + row['indicator_id'])
        for citation in row['sources']:
            source = cs._read(db, citation['source_ref'])['payload']
            if source['source_id'] in templates or Ref.model_validate(citation['source_ref']).key() in template_refs:
                raise ActionRejected('ASSESSMENT_TEMPLATE_IS_NOT_FACTUAL_BASIS')
            if source['source_id'] in customer_ids:
                raise ActionRejected('ASSESSMENT_COMMISSION_IS_NOT_FACTUAL_BASIS')

def _save_legacy_bulk_assessment(cs, db, actor, operation_id, assessment):
    """Compatibility entry for historical raw-row callers."""
    from .commission_plan import assert_writing_allowed, outside_boundary

    plan = assert_writing_allowed(cs, db, actor)
    if not plan or not plan['payload'].get('method_pack'):
        raise ActionRejected('ASSESSMENT_METHOD_PACK_REQUIRED')
    pack = plan['payload']['method_pack']
    choices = [b for b in plan['payload'].get('method_conventions', []) if b['key'] == 'weights']
    if len(choices) != 1 or assessment.get('weight_strategy_id') != choices[0]['strategy_id']:
        raise ActionRejected('ASSESSMENT_COMMISSION_STRATEGY_MISMATCH')
    obj = next((o for o in plan['payload']['objects'] if o['object_id'] == assessment.get('object_id')), None)
    if obj is None:
        raise ActionRejected('ASSESSMENT_OBJECT_NOT_IN_COMMISSION')
    if outside_boundary(plan['payload'], obj):
        raise ActionRejected('ASSESSMENT_OBJECT_OUTSIDE_COMMISSION_BOUNDARY')
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    if task.get('assessment_object_id') is not None and task['assessment_object_id'] != assessment.get('object_id'):
        raise ActionRejected('ASSESSMENT_OBJECT_OUTSIDE_WRITER_ASSIGNMENT')
    assigned = [s for s in task['section_ids'] if any(p['section_id'] == s and p['kind'] == 'extracted' for p in plan['payload']['sections'])]
    section_id = assessment.get('section_id') or (assigned[0] if len(assigned) == 1 else None)
    if section_id not in assigned:
        raise ActionRejected('ASSESSMENT_REQUIRES_EXTRACTED_SECTION_ASSIGNMENT')
    candidate, result = _prepare_complete(cs, db, actor, plan, section_id, assessment)
    from .assessment_producers import bind_producer
    from .section_writing import enabled as system_writing
    draft_only = system_writing(cs.store)
    bind_producer(cs, db, plan['ref'], obj['object_id'], actor, bulk=True, draft_only=draft_only)
    result['status'] = 'legacy_draft' if draft_only else 'legacy_g3_scored'
    # Bulk callers predate immutable indicator submissions. Preserve their historical provenance.
    return _project_assessment(cs, db, actor, operation_id, plan, obj, section_id, candidate, result, {})


def _prepare_complete(cs, db, actor, plan, section_id, assessment):
    pack = plan['payload']['method_pack']
    try:
        candidate = Assessment.model_validate(assessment).model_dump(mode='json')
    except ValidationError:
        calculate(pack, assessment)
        raise
    problems = []
    for index, row in enumerate(candidate['indicators']):
        prepared, errors = _prepare_indicator(pack, row)
        candidate['indicators'][index] = prepared
        problems.extend(errors)
    try:
        result = calculate(pack, candidate)
    except ActionRejected as exc:
        problems.append(str(exc).removeprefix('ASSESSMENT_INVALID: '))
    if problems:
        raise ActionRejected('ASSESSMENT_INVALID: ' + '; '.join(problems))
    validate_indicator_sources(cs, db, actor, plan, section_id, candidate['indicators'])
    return candidate, result


def _writer_input(scope, entries):
    plan = scope['plan']['payload']
    pack = plan['method_pack']
    choices = [c for c in plan['method_conventions'] if c['key'] == 'weights']
    if len(choices) != 1:
        raise ActionRejected('WRITER_ASSESSMENT_WEIGHT_BINDING_REQUIRED')
    ranks = plan['indicator_rank_order']['indicator_ids']
    if set(entries) - set(ranks) or any(e['rank'] != ranks.index(i) + 1 for i, e in entries.items()):
        raise ActionRejected('ASSESSMENT_CONFIRMED_RANK_MISMATCH')
    return dict(object_id=scope['object']['object_id'], section_id=scope['section_id'],
                method_id=pack['method_id'], method_version=pack['version'], weight_strategy_id=choices[0]['strategy_id'],
                indicators=[entries[r['id']]['judgment'] for r in pack['indicators'] if entries.get(r['id'], {}).get('judgment')])


def preview_writer_assessment(cs, db, actor, scope, draft):
    candidate = _writer_input(scope, draft['rows'])
    if len(candidate['indicators']) == len(scope['plan']['payload']['method_pack']['indicators']):
        candidate, result = _prepare_complete(cs, db, actor, scope['plan'], scope['section_id'], candidate)
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
    if scope is None or draft is None or assessment is not None:
        raise ActionRejected('ASSESSMENT_INPUT_MODE_MISMATCH')
    current = bound_assignment(cs, db, actor)
    if current['assignment_digest'] != scope['assignment_digest']:
        raise ActionRejected('ASSESSMENT_ASSIGNMENT_CHANGED')
    plan, obj, section = current['plan'], current['object'], current['section_id']
    bind_producer(cs, db, plan['ref'], obj['object_id'], actor)
    entries = immutable_entries(cs, db, actor, current, draft)
    candidate = _writer_input(current, entries)
    pack = plan['payload']['method_pack']
    interruptions = draft.get('interrupted_indicators', {})
    if set(interruptions) & set(entries) or set(interruptions) - {r['id'] for r in pack['indicators']}:
        raise ActionRejected('ASSESSMENT_INTERRUPTION_SCOPE_MISMATCH')
    if len(candidate['indicators']) == len(pack['indicators']):
        candidate, result = _prepare_complete(cs, db, actor, plan, section, candidate)
        result.update(status='scored', level_robust=not result['affects_level'])
    else:
        result = unscored_result(pack, candidate['weight_strategy_id'], plan['payload']['indicator_rank_order']['indicator_ids'],
                                 entries, interruptions)
    try:
        assertion = commit_derivation(cs, current, operation_id, candidate['weight_strategy_id'], entries, result, require_reviewed=require_reviewed)
    except (ValueError, PermissionError) as exc:
        raise ActionRejected('ASSESSMENT_DERIVATION_REFUSED: ' + str(exc)) from exc
    native = dict(derived_assertion_id=assertion['id'], derive_operation_id=assertion['operation_id'])
    return _project_assessment(cs, db, actor, operation_id, plan, obj, section, candidate, result, native)


def _project_assessment(cs, db, actor, operation_id, plan, obj, section_id, candidate, result, native):
    from .content_models import ContentNode
    from .store import digest
    pack = plan['payload']['method_pack']
    definitions = {i['id']: i for i in pack['indicators']}
    index = plan['payload']['objects'].index(obj) + 1
    parts = section_id.split('.')
    table_prefix = '.'.join((parts + ['2'])[:2] + [str(index)])
    unscored = result.get('status') == 'unscored'
    table_records = (_table_records(pack, result, obj['label'], table_prefix)
                     if plan['payload'].get('table_specs') and not unscored else None)
    assessment_ref = cs._insert(db, actor, 'Assessment', {'commission_plan_ref': plan['ref'], **candidate,
        'result': result, **native, **({'table_records': table_records} if table_records else {})})
    evidence_ref = cs._insert(db, actor, 'Evidence', {'source_refs': [], 'locator': 'system calculation',
        'excerpt': '', 'input_refs': [assessment_ref, plan['ref']], 'method': 'reviewed method table lookup and decimal sum_products',
        'tool_receipt': operation_id, 'result': result})
    if unscored:
        from .draft_assessment import tables
        ranking_body, evaluation_body, citations = tables(cs, db, plan, obj, assessment_ref, result, table_prefix)
    elif table_records:
        ranking_body, evaluation_body, citations = _projected_tables(
            cs, db, plan, assessment_ref, table_records, result, obj['label'])
    else:
        rows, merges, issues, ranking, citations = [], [], [], [], []
        for row in result['rows']:
            definition = definitions[row['indicator_id']]
            start = len(rows)
            source_texts = []
            for citation in row['sources']:
                source = cs._read(db, citation['source_ref'])['payload']
                title = source['source_metadata'].get('title')
                if not title:
                    raise ActionRejected('ASSESSMENT_READABLE_SOURCE_TITLE_REQUIRED')
                source_texts.append({'document': title, 'page': citation['locator']})
                if citation not in citations:
                    citations.append(citation)
            note = definition['notes']
            if not row['basis_kind'].endswith('assumption'):
                note += '\n取值说明：' + row['rationale']
                note += '\n依据：' + '；'.join(s['document'] + '（' + s['page'].replace('page ', '第') + ('页' if s['page'].startswith('page ') else '') + '）' for s in source_texts)
            for grade in definition['grades']:
                rows.append([definition['category'], definition['label'], grade['description'],
                    grade['min_value'] + '–' + grade['max_value'], row['value'], row['weight'], row['score'], note])
            end = len(rows) - 1
            if end > start:
                for column in (1, 4, 5, 6, 7):
                    merges.append({'start_row': start, 'end_row': end, 'start_col': column, 'end_col': column})
            ranking.append([definition['label'], str(row['rank']), row['weight']])
            if row['basis_kind'].endswith('assumption'):
                issues.append({'id': digest([assessment_ref, row['indicator_id']]), 'kind': row['basis_kind'],
                    'object_label': obj['label'], 'basis': row['rationale'], 'sources': source_texts,
                    'adopted_value': row['value'], 'question': row['question'], 'anchor': {'row': start, 'column': 4},
                    'affects_level': result['affects_level']})
        start = 0
        while start < len(rows):
            end = start
            while end + 1 < len(rows) and rows[end + 1][0] == rows[start][0]:
                end += 1
            if end > start:
                merges.append({'start_row': start, 'end_row': end, 'start_col': 0, 'end_col': 0})
            start = end + 1
    base = {'qualifiers': {}, 'claim_kind': 'calculation', 'citations': citations}
    def node(kind, body):
        payload = ContentNode.model_validate({**base, 'kind': kind, 'body': {
            **body, 'section_id': section_id, 'assessment_ref': assessment_ref}}).model_dump(mode='json')
        return cs._insert(db, actor, 'ContentNode', payload)
    if not table_records and not unscored:
        ranking_body = {'columns': ['指标', '重要性排序', '权重'], 'rows': ranking,
            'caption': table_prefix + '-1 ' + obj['label'] + '指标重要性排序表', 'assessment_part': 'ranking'}
        evaluation_body = {'columns': ['因素', '指标', '分级描述', '分值范围', '采用值', '权重', '得分', '指南注释'],
            'caption': table_prefix + '-2 ' + obj['label'] + '施工安全风险评价表',
            'rows': rows, 'merges': merges, 'material_issues': issues, 'assessment_part': 'evaluation'}
    ranking_ref = node('table', ranking_body)
    evaluation_ref = node('table', evaluation_body)
    if unscored:
        qualification = '本草稿尚有未评分指标，不采用综合评分或风险等级。'
        text = obj['label'] + '：未评分，风险等级未确定。' + qualification
    else:
        qualification = '假设指标按现有依据取值，补充相关资料后需复核风险等级。' if result['affects_level'] else ''
        level = (plan['payload']['table_specs']['evaluation']['level_labels'][result['adopted']['level']]
                 if table_records else result['adopted']['level'])
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


def validate_outcome(cs, db, plan, object_id, score_ref, level_ref, basis_refs, unresolved):
    assessment_ref = cs._read(db, score_ref)['payload']['body'].get('assessment_ref')
    receipt = assessment_receipt(db, assessment_ref) if assessment_ref else None
    if receipt and (reason := score_blocker(receipt)):
        raise ActionRejected('COMMISSION_OUTCOME_REVIEWED_SCORE_REQUIRED: ' + reason)
    if (not receipt or receipt['evaluation_ref'] != score_ref or receipt['level_ref'] != level_ref
            or receipt['evidence_ref'] not in basis_refs or unresolved):
        raise ActionRejected('COMMISSION_OUTCOME_SYSTEM_ASSESSMENT_REQUIRED')
    saved = cs._read(db, assessment_ref)['payload']
    if saved['object_id'] != object_id or saved['commission_plan_ref'] != plan['ref']:
        raise ActionRejected('COMMISSION_OUTCOME_ASSESSMENT_MISMATCH')
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
    from .commission_plan import fixed_section_text, fixed_source_views, _confirmed, outside_boundary
    from .content_models import ContentNode
    if not plan or not plan['payload'].get('method_pack'):
        raise ActionRejected('PLANNED_SECTION_METHOD_REQUIRED')
    section = next((s for s in plan['payload']['sections'] if s['section_id'] == section_id), None)
    if section is None or section['kind'] not in ('fixed', 'derived'):
        raise ActionRejected('PLANNED_SECTION_ASSIGNMENT_REQUIRED')
    text = fixed_section_text(section)
    views = [{**view, 'source_id': cs._read(db, view['source_ref'])['payload']['source_id']}
             for view in fixed_source_views(section)]
    bound, receipts = {}, []
    for ref in assessment_refs:
        record = cs._read(db, ref)
        if ref['type'] != 'Assessment' or record['payload']['commission_plan_ref'] != plan['ref']:
            raise ActionRejected('PLANNED_SECTION_ASSESSMENT_STALE')
        obj = record['payload']['object_id']
        if obj in bound:
            raise ActionRejected('PLANNED_SECTION_DUPLICATE_ASSESSMENT')
        receipt = assessment_receipt(db, ref)
        if receipt and (reason := score_blocker(receipt)):
            raise ActionRejected('PLANNED_SECTION_REVIEWED_SCORE_REQUIRED: ' + reason)
        if not receipt:
            raise ActionRejected('PLANNED_SECTION_SYSTEM_RECEIPT_REQUIRED')
        bound[obj] = record['payload']['result']
        receipts.append(receipt)
    slots = section.get('result_bindings', [])
    aggregate = bool(section.get('result_composition')) or any(s['field'] in ('object_count', 'level_count') for s in slots)
    referenced_objects = {s['object_id'] for s in slots if s['object_id'] is not None}
    if section['kind'] == 'derived' and (not (slots or section.get('result_composition')) or (not aggregate and referenced_objects != set(bound)) or not referenced_objects <= set(bound)):
        raise ActionRejected('PLANNED_SECTION_RESULT_BINDINGS_REQUIRED')
    if aggregate:
        _, decision = _confirmed(cs, db)
        reduced = {r['object_id'] for r in decision['payload']['reductions']}
        expected = {o['object_id'] for o in plan['payload']['objects'] if not outside_boundary(plan['payload'], o)} - reduced
        if set(bound) != expected:
            raise ActionRejected('PLANNED_SECTION_AGGREGATE_REQUIRES_ALL_COMMISSIONED_ASSESSMENTS')
        levels = {b['level'] for b in plan['payload']['method_pack']['risk_bands']}
        if any(s['field'] == 'level_count' and s['level'] not in levels for s in slots):
            raise ActionRejected('PLANNED_SECTION_UNKNOWN_LEVEL')
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
    if section['kind'] == 'fixed' and (slots or assessment_refs):
        raise ActionRejected('FIXED_SECTION_CANNOT_INSERT_UNDECLARED_RESULTS')
    for slot in slots:
        if text.count(slot['old']) != 1:
            raise ActionRejected('PLANNED_SECTION_RESULT_PASSAGE_AMBIGUOUS')
        if slot['field'] in ('object_count', 'level_count'):
            value = str(len(bound) if slot['field'] == 'object_count' else sum(r['adopted']['level'] == slot['level'] for r in bound.values()))
            text = text.replace(slot['old'], value, 1)
            continue
        result = bound[slot['object_id']]
        receipt = next(r for r in receipts if cs._read(db, r['assessment_ref'])['payload']['object_id'] == slot['object_id'])
        if slot['field'] == 'assessment_text':
            value = cs._read(db, receipt['level_ref'])['payload']['body']['text']
        else:
            value = result['adopted'][slot['field']]
            if slot['field'] == 'level':
                if plan['payload'].get('table_specs'):
                    value = plan['payload']['table_specs']['evaluation']['level_labels'][value]
                value += '。' + cs._read(db, receipt['level_ref'])['payload']['body']['level_qualification'] if result['affects_level'] else ''
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
