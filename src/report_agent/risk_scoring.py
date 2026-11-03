"""Agent-selected grades and ranks; system-owned exact arithmetic and sensitivity."""
from typing import Literal

from pydantic import Field, ValidationError

from .calculations import sum_products
from .content_models import Contract, SourceCitation
from .errors import ActionRejected
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
        prefix = row.indicator_id + ': '
        definition = definitions.get(row.indicator_id)
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
    if errors:
        raise ActionRejected('ASSESSMENT_INVALID: ' + '; '.join(dict.fromkeys(errors)))
    ordered = sorted(rows, key=lambda r: list(definitions).index(r.indicator_id))
    result = {'rows': []}
    for mode in ('adopted', 'low', 'high'):
        values = [getattr(r, mode) if mode != 'adopted' and r.basis_kind.endswith('assumption') else r.value for r in ordered]
        arithmetic = sum_products([[v, weights[r.rank - 1]] for r, v in zip(ordered, values)])
        total = number(arithmetic['total'])
        bands = [b for b in method.risk_bands if (total >= number(b.lower) if b.lower_inclusive else total > number(b.lower))
                 and (total <= number(b.upper) if b.upper_inclusive else total < number(b.upper))]
        if len(bands) != 1:
            raise ActionRejected('ASSESSMENT_INVALID: calculated total outside risk bands')
        result[mode] = {'total': arithmetic['total'], 'level': bands[0].level}
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


def save_assessment(cs, actor, operation_id, assessment):
    """Persist a complete judgment with reproducible calculation and rendered tables."""
    from .commission_plan import assert_writing_allowed, _validate_sources, _state, _set, _confirmed, outside_boundary, require_assessment_tables
    from .content_models import ContentNode, Ref
    from .store import digest

    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        if not plan or not plan['payload'].get('method_pack'):
            raise ActionRejected('ASSESSMENT_METHOD_PACK_REQUIRED')
        require_assessment_tables(_state(db, 'manifest', {}), plan['payload'])
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
        assigned = [s for s in task['section_ids'] if any(p['section_id'] == s and p['kind'] == 'extracted' for p in plan['payload']['sections'])]
        section_id = assessment.get('section_id') or (assigned[0] if len(assigned) == 1 else None)
        if section_id not in assigned:
            raise ActionRejected('ASSESSMENT_REQUIRES_EXTRACTED_SECTION_ASSIGNMENT')
        try:
            candidate = Assessment.model_validate(assessment).model_dump(mode='json')
        except ValidationError:
            calculate(pack, assessment)
            raise
        definitions = {i['id']: i for i in pack['indicators']}
        problems = []
        for row in candidate['indicators']:
            if not row['rank_reason'].strip():
                problems.append(row['indicator_id'] + ': rank_reason required')
            if row['basis_kind'].endswith('assumption'):
                grades = definitions.get(row['indicator_id'], {}).get('grades', [])
                if row['basis_kind'] == 'no_evidence_assumption':
                    # No evidence can exclude a grade from the uncertainty interval.
                    row['plausible_grades'] = [g['id'] for g in grades]
                plausible = [g for g in grades if g['id'] in row['plausible_grades']]
                if not plausible or len(plausible) != len(row['plausible_grades']) or row['grade_id'] not in row['plausible_grades']:
                    problems.append(row['indicator_id'] + ': plausible_grades required, including adopted grade')
                else:
                    row['low'] = str(min(number(g['min_value']) for g in plausible))
                    row['high'] = str(max(number(g['max_value']) for g in plausible))
        try:
            result = calculate(pack, candidate)
        except ActionRejected as exc:
            problems.append(str(exc).removeprefix('ASSESSMENT_INVALID: '))
        if problems:
            raise ActionRejected('ASSESSMENT_INVALID: ' + '; '.join(problems))
        _validate_sources(cs, db, actor, candidate)
        roles = _state(db, 'commission_source_roles', {})
        templates = {r['id'] for r in roles.values() if r['purpose'] == 'template'}
        template_refs = {Ref.model_validate(c['source_ref']).key() for s in plan['payload']['sections'] if s['kind'] == 'fixed' for c in s['sources']}
        factual_refs = {Ref.model_validate(c['source_ref']).key() for s in plan['payload']['sections'] if s['section_id'] == section_id for c in s['sources']}
        method_refs = {Ref.model_validate(c['source_ref']).key() for c in pack['sources']}
        customer_ids = {r['id'] for r in roles.values() if r['purpose'] == 'commission'}
        factual_refs -= method_refs | template_refs
        for row in candidate['indicators']:
            actual = {Ref.model_validate(c['source_ref']).key() for c in row['sources']}
            if row['basis_kind'] != 'no_evidence_assumption' and not actual & factual_refs:
                raise ActionRejected('ASSESSMENT_FACTUAL_SOURCE_REQUIRED: ' + row['indicator_id'])
            if row['basis_kind'] == 'applied_guideline' and not actual & method_refs:
                raise ActionRejected('ASSESSMENT_GUIDELINE_RULE_SOURCE_REQUIRED: ' + row['indicator_id'])
            for citation in row['sources']:
                source = cs._read(db, citation['source_ref'])['payload']
                if source['source_id'] in templates or Ref.model_validate(citation['source_ref']).key() in template_refs:
                    raise ActionRejected('ASSESSMENT_TEMPLATE_IS_NOT_FACTUAL_BASIS')
                if source['source_id'] in customer_ids:
                    raise ActionRejected('ASSESSMENT_COMMISSION_IS_NOT_FACTUAL_BASIS')
        index = plan['payload']['objects'].index(obj) + 1
        parts = section_id.split('.')
        table_prefix = '.'.join((parts + ['2'])[:2] + [str(index)])
        table_records = (_table_records(pack, result, obj['label'], table_prefix)
                         if plan['payload'].get('table_specs') else None)
        assessment_ref = cs._insert(db, actor, 'Assessment', {'commission_plan_ref': plan['ref'], **candidate,
            'result': result, **({'table_records': table_records} if table_records else {})})
        evidence_ref = cs._insert(db, actor, 'Evidence', {'source_refs': [], 'locator': 'system calculation',
            'excerpt': '', 'input_refs': [assessment_ref, plan['ref']], 'method': 'reviewed method table lookup and decimal sum_products',
            'tool_receipt': operation_id, 'result': result})
        if table_records:
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
        if not table_records:
            ranking_body = {'columns': ['指标', '重要性排序', '权重'], 'rows': ranking,
                'caption': table_prefix + '-1 ' + obj['label'] + '指标重要性排序表', 'assessment_part': 'ranking'}
            evaluation_body = {'columns': ['因素', '指标', '分级描述', '分值范围', '采用值', '权重', '得分', '指南注释'],
                'caption': table_prefix + '-2 ' + obj['label'] + '施工安全风险评价表',
                'rows': rows, 'merges': merges, 'material_issues': issues, 'assessment_part': 'evaluation'}
        ranking_ref = node('table', ranking_body)
        evaluation_ref = node('table', evaluation_body)
        qualification = '假设指标按现有依据取值，补充相关资料后需复核风险等级。' if result['affects_level'] else ''
        level = (plan['payload']['table_specs']['evaluation']['level_labels'][result['adopted']['level']]
                 if table_records else result['adopted']['level'])
        level_ref = node('block', {'text': f"{obj['label']}：综合评分{result['adopted']['total']}，风险等级{level}。" + qualification,
            'assessment_part': 'level', 'level_qualification': qualification})
        generated = [ranking_ref, evaluation_ref, level_ref]
        relations = [cs._insert(db, actor, 'Relation', {'subject_ref': ref, 'object_ref': evidence_ref,
            'predicate': 'supported_by', 'provenance_kind': 'adopted_during_generation'}) for ref in generated]
        receipt = {'assessment_ref': assessment_ref, 'evidence_ref': evidence_ref, 'ranking_ref': ranking_ref,
            'evaluation_ref': evaluation_ref, 'level_ref': level_ref, 'result': result,
            'refs': dict(zip(['assessment', 'evidence', 'ranking', 'evaluation', 'level',
                             *['relation' + str(n) for n in range(len(relations))]],
                            [assessment_ref, evidence_ref, *generated, *relations]))}
        _set(db, 'assessment_receipt:' + digest(assessment_ref), receipt)
        return receipt
    return cs.operation(actor, operation_id, {'assessment': assessment}, save,
        binding_identity=lambda db, result: _confirmed(cs, db)[0]['ref'])


def validate_outcome(cs, db, plan, object_id, score_ref, level_ref, basis_refs, unresolved):
    from .commission_plan import _state
    from .store import digest
    assessment_ref = cs._read(db, score_ref)['payload']['body'].get('assessment_ref')
    receipt = _state(db, 'assessment_receipt:' + digest(assessment_ref)) if assessment_ref else None
    if (not receipt or receipt['evaluation_ref'] != score_ref or receipt['level_ref'] != level_ref
            or receipt['evidence_ref'] not in basis_refs or unresolved):
        raise ActionRejected('COMMISSION_OUTCOME_SYSTEM_ASSESSMENT_REQUIRED')
    saved = cs._read(db, assessment_ref)['payload']
    if saved['object_id'] != object_id or saved['commission_plan_ref'] != plan['ref']:
        raise ActionRejected('COMMISSION_OUTCOME_ASSESSMENT_MISMATCH')
    return assessment_ref


def create_planned_section(cs, actor, operation_id, section_id, assessment_refs=()):
    """Copy approved source text, inserting only system-calculated result slots."""
    from .commission_plan import assert_writing_allowed, fixed_section_text, fixed_source_views, _state, _confirmed, outside_boundary
    from .content_models import ContentNode, Ref
    from .store import digest
    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        if not plan or not plan['payload'].get('method_pack'):
            raise ActionRejected('PLANNED_SECTION_METHOD_REQUIRED')
        assignment = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        section = next((s for s in plan['payload']['sections'] if s['section_id'] == section_id), None)
        if section is None or section_id not in assignment['section_ids'] or section['kind'] not in ('fixed', 'derived'):
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
            receipt = _state(db, 'assessment_receipt:' + digest(ref))
            if not receipt:
                raise ActionRejected('PLANNED_SECTION_SYSTEM_RECEIPT_REQUIRED')
            bound[obj] = record['payload']['result']
            receipts.append(receipt)
        slots = section.get('result_bindings', [])
        aggregate = any(s['field'] in ('object_count', 'level_count') for s in slots)
        referenced_objects = {s['object_id'] for s in slots if s['object_id'] is not None}
        if section['kind'] == 'derived' and (not slots or (not aggregate and referenced_objects != set(bound)) or not referenced_objects <= set(bound)):
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
                   'section_id': section_id, 'text_digest': digest(text)}
        if views:
            receipt['source_views_digest'] = digest(views)
        from .commission_plan import _set
        _set(db, 'planned_section_receipt:' + digest(ref), receipt)
        return {'node_ref': ref, 'refs': {'section': ref}, 'assessment_refs': list(assessment_refs)}
    return cs.operation(actor, operation_id, {'planned_section': section_id, 'assessment_refs': list(assessment_refs)}, save,
        binding_identity=lambda db, result: _confirmed(cs, db)[0]['ref'])
