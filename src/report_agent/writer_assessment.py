"""Incremental judgments for one host-assigned Writer; all identities stay server-owned."""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from typing import Literal

from pydantic import Field, create_model, model_validator

from .commission_plan import _set, _state
from .content_models import Contract, Ref
from .errors import ActionRejected
from .planning_inputs import quote_locations, reject, resolve_citations
from .store import digest


def _label(rule):
    return rule.get('display_label') or rule['label']


def _grade(grade):
    return grade['description'] + ' [' + grade['min_value'] + '–' + grade['max_value'] + ']'


def _layout(pack):
    labels = [_label(rule) for rule in pack['indicators']]
    if len(set(labels)) != len(labels):
        raise ActionRejected('WRITER_ASSESSMENT_DUPLICATE_INDICATOR_LABEL')
    return tuple((label, tuple(_grade(g) for g in rule['grades']))
        for label, rule in zip(labels, pack['indicators']))


@lru_cache(maxsize=32)
def _input_model(layout):
    choices = dict(layout)
    grades = tuple(dict.fromkeys(g for _, offered in layout for g in offered))
    @model_validator(mode='after')
    def offered_choices(self):
        if self.grade not in choices[self.indicator] or any(g not in choices[self.indicator] for g in self.plausible_grades):
            raise ValueError('Choose grades offered for the selected indicator label.')
        return self
    return create_model('WriterIndicatorInput', __base__=Contract,
        __validators__={'offered_choices': offered_choices},
        indicator=(Literal[tuple(choices)], ...), grade=(Literal[grades], ...),
        rank=(int, Field(strict=True, ge=1, le=len(layout))), value=(str, ...),
        basis_kind=(Literal['direct_evidence','applied_guideline','indirect_assumption','no_evidence_assumption'], ...),
        rationale=(str, Field(min_length=1)), rank_reason=(str, Field(min_length=1)),
        quotes=(list[str], Field(default_factory=list)), visual_pages=(list[str], Field(default_factory=list)),
        question=(str, ''), low=(str | None, None), high=(str | None, None),
        plausible_grades=(list[Literal[grades]], Field(default_factory=list)))


def _assignment(cs, db, actor):
    from .writer_assignments import bound_assignment
    scope = bound_assignment(cs, db, actor)
    _layout(scope['plan']['payload']['method_pack'])
    return scope


def indicator_schema(cs, actor):
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
    return _input_model(_layout(scope['plan']['payload']['method_pack']))


def _key(scope, actor):
    return 'writer_assessment_draft:' + digest([actor.id, scope['task_ref'], scope['plan']['ref'], scope['object']['object_id']])


def _draft(db, scope, actor):
    draft = _state(db, _key(scope, actor))
    if draft is None:
        return {'assignment_digest': scope['assignment_digest'], 'rows': {}}
    if draft.get('assignment_digest') != scope['assignment_digest']:
        raise ActionRejected('WRITER_ASSESSMENT_DRAFT_STALE')
    return draft


def _status(scope, draft):
    rules = scope['plan']['payload']['method_pack']['indicators']
    names = {r['id']: _label(r) for r in rules}
    ranks = defaultdict(list)
    for rule in rules:
        saved = draft['rows'].get(rule['id'])
        if saved:
            ranks[saved['judgment']['rank']].append(names[rule['id']])
    return {'missing_indicators': [names[r['id']] for r in rules if r['id'] not in draft['rows']],
        'rank_collisions': [{'rank': rank, 'indicators': labels} for rank, labels in sorted(ranks.items()) if len(labels) > 1]}


def _public_rows(scope, draft):
    result = []
    for rule in scope['plan']['payload']['method_pack']['indicators']:
        saved = draft['rows'].get(rule['id'])
        if saved:
            labels = {g['id']: _grade(g) for g in rule['grades']}
            row = deepcopy(saved['input']); normalized = saved['judgment']
            row.update(low=normalized['low'], high=normalized['high'],
                plausible_grades=[labels[g] for g in normalized['plausible_grades']])
            result.append(row)
    return result


def _assignment_context(cs, db, scope):
    from .commission_plan import outside_boundary, boundary_display
    plan = scope['plan']['payload']
    decision = scope['decision']['payload']
    def citation(value):
        source = cs._read(db, value['source_ref'])['payload']
        return {'document': source.get('source_metadata', {}).get('title', ''),
            'location': value['locator'], 'quote': value['quote']}
    facts = [{'name': attribute['name'], 'values': [
        {**{k: v for k, v in value.items() if k != 'source'},
         **({'source': citation(value['source'])} if value.get('source') else {})}
        for value in attribute['values']]} for attribute in scope['object'].get('attributes', [])]
    reductions = {row['object_id']: row['reason'] for row in decision.get('reductions', [])}
    excluded = [{'label': obj['label'], 'reason': reductions.get(obj['object_id'], obj['reason'])}
        for obj in plan['objects'] if obj['object_id'] in reductions or not obj['included'] or outside_boundary(plan, obj)]
    pack = plan['method_pack']
    choice = next(row for row in plan['method_conventions'] if row['key'] == 'weights')
    table = next(row for row in pack['weight_tables'] if row['id'] == choice['strategy_id'])
    weights = next(row['weights'] for row in table['rows'] if row['indicator_count'] == len(pack['indicators']))
    return {'inventory_facts': facts,
        'owner_conventions': [{'source': citation(row['source']), 'interpretation': row['interpretation']}
            for row in plan['conventions']],
        'boundary': {'range': boundary_display(plan['scope_boundary']) if plan.get('scope_boundary') else None,
            'excluded_objects': excluded},
        'approved_method': {'indicator_count': len(pack['indicators']),
            'weight_rule': {'interpretation': choice['interpretation'], 'status': choice['status'],
                'source': citation(choice['source'])}, 'rank_weights': weights}}


def read_assignment(cs, actor):
    from .writer_assignments import read_assignment_pages
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor); draft = _draft(db, scope, actor)
        pack = scope['plan']['payload']['method_pack']
        packet = {'assignment_digest': scope['assignment_digest'], 'object_label': scope['object']['label'],
            'indicators': [{'indicator': _label(rule), 'notes': rule['notes'],
                'grades': [{'choice': _grade(g), 'description': g['description'], 'min_value': g['min_value'],
                    'max_value': g['max_value']} for g in rule['grades']]} for rule in pack['indicators']],
            'draft': _public_rows(scope, draft), **_status(scope, draft), **_assignment_context(cs, db, scope)}
    pages = read_assignment_pages(cs, actor)
    return {**packet, 'sources': pages['sources'], 'page_index_digest': pages['index_digest'],
        'limitations': pages.get('limitations', [])}


def resolve_judgment_sources(cs, db, actor, context, quotes, visual_pages=()):
    """Resolve only the assigned source pool and host-verified visual read handles."""
    scope = context
    groups, pool = set(), []
    for ref in scope['sources']:
        payload = cs._read(db, ref)['payload']
        pin = tuple(payload.get(field) for field in ('source_id','file_digest','content'))
        identity = pin if all(isinstance(v,str) and v.strip() for v in pin) else Ref.model_validate(ref).key()
        if identity not in groups:
            groups.add(identity); pool.append((ref, payload))
    citations = []
    for index, quote in enumerate(quotes):
        if not quote.strip():
            reject(f'quotes[{index}]', 'quote_required', code='WRITER_ASSESSMENT_QUOTE_REQUIRED')
        matches = []
        for ref, payload in pool:
            rows = list(db.execute('SELECT locator,text FROM source_blocks WHERE source_id=? ORDER BY ordinal', (payload['source_id'],)))
            matches.extend((ref, locator, payload) for locator in quote_locations(rows, quote))
        if len(matches) != 1:
            choices = [{'document': p.get('source_metadata',{}).get('title',''), 'locator': loc} for _,loc,p in matches]
            reject(f'quotes[{index}]', 'quote_ambiguous' if matches else 'quote_not_found', choices,
                code='WRITER_ASSESSMENT_QUOTE_AMBIGUOUS' if matches else 'WRITER_ASSESSMENT_QUOTE_NOT_FOUND')
        citation = {'source_ref': matches[0][0], 'quote': quote}
        resolve_citations(cs, db, actor, {'sources': [citation]}, 'indicator')
        if citation['locator'].startswith('manifest text; chars '):
            citation['locator'] = 'manifest text'
        citations.append(citation)
    if visual_pages:
        from .writer_assignments import resolve_visual_pages
        citations += resolve_visual_pages(cs, db, actor, visual_pages)
    return citations


def _validated_judgment(cs, db, actor, current, rule, value):
    from .risk_scoring import validate_indicator_judgment, validate_indicator_sources
    pack = current['plan']['payload']['method_pack']
    grades = {_grade(g): g['id'] for g in rule['grades']}
    row = {k: value[k] for k in ('rank','value','basis_kind','rationale','rank_reason','question','low','high')}
    row.update(indicator_id=rule['id'], grade_id=grades[value['grade']],
        plausible_grades=[grades[g] for g in value['plausible_grades']],
        sources=resolve_judgment_sources(cs, db, actor, current, value['quotes'], value['visual_pages']))
    row = validate_indicator_judgment(pack, row)
    validate_indicator_sources(cs, db, actor, current['plan'], current['section_id'], [row])
    return row


def set_indicator(cs, actor, operation_id, judgment):
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
    model = _input_model(_layout(scope['plan']['payload']['method_pack']))
    value = model.model_validate(judgment).model_dump(mode='json')
    def save(db):
        current = _assignment(cs, db, actor)
        if current['assignment_digest'] != scope['assignment_digest']:
            raise ActionRejected('WRITER_ASSESSMENT_ASSIGNMENT_CHANGED')
        pack = current['plan']['payload']['method_pack']
        rule = next(r for r in pack['indicators'] if _label(r) == value['indicator'])
        row = _validated_judgment(cs, db, actor, current, rule, value)
        draft = deepcopy(_draft(db, current, actor)); entry = {'input': deepcopy(value), 'judgment': row}
        changed = draft['rows'].get(rule['id']) != entry
        draft['rows'][rule['id']] = entry
        _set(db, _key(current, actor), draft)
        selected_key = 'g6_assessment:' + digest([current['plan']['ref'], current['object']['object_id']])
        selected = _state(db, selected_key)
        if changed and selected:
            previous = cs._read(db, selected)
            if previous['owner_id'] == actor.id and previous.get('task_id') == actor.task_id:
                _set(db, selected_key, None)
        return {'saved_indicator': value['indicator'], **_status(current, draft)}
    return cs.operation(actor, operation_id, {'writer_indicator': value}, save,
        binding_identity=lambda db, result: _assignment(cs, db, actor)['assignment_digest'])


def _score_saved_rows(cs, db, actor, operation_id, current, draft):
    from .risk_scoring import save_assessment_in_transaction
    pack = current['plan']['payload']['method_pack']
    choices = [c for c in current['plan']['payload']['method_conventions'] if c['key'] == 'weights']
    if len(choices) != 1:
        raise ActionRejected('WRITER_ASSESSMENT_WEIGHT_BINDING_REQUIRED')
    assessment = {'object_id': current['object']['object_id'], 'section_id': current['section_id'],
        'method_id': pack['method_id'], 'method_version': pack['version'], 'weight_strategy_id': choices[0]['strategy_id'],
        'indicators': [draft['rows'][r['id']]['judgment'] for r in pack['indicators']]}
    return save_assessment_in_transaction(cs, db, actor, operation_id, assessment)


def submit_assessment(cs, actor, operation_id):
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
    def submit(db):
        current = _assignment(cs, db, actor); draft = _draft(db, current, actor)
        status = _status(current, draft)
        if status['missing_indicators'] or status['rank_collisions']:
            return {'accepted': False, **status}
        receipt = _score_saved_rows(cs, db, actor, operation_id, current, draft)
        return {'accepted': True, **receipt, **status}
    def binding(db, result):
        current = _assignment(cs, db, actor)
        return [current['assignment_digest'], digest(_draft(db, current, actor))]
    return cs.operation(actor, operation_id, {'writer_assessment_submit': scope['assignment_digest']}, submit,
        binding_identity=binding)


def tool_functions(cs, actor):
    """Main applies existing native_write_tools; the same model validates tool and backend."""
    model = indicator_schema(cs, actor())
    def read_tool() -> dict:
        """Read the assigned slope, offered choices, saved rows and remaining problems."""
        return read_assignment(cs, actor())
    def set_tool(operation_id: str, **judgment) -> dict:
        """Save one professional judgment using an offered indicator/grade label and exact source quotes."""
        return set_indicator(cs, actor(), operation_id, judgment)
    def submit_tool(operation_id: str) -> dict:
        """Submit saved rows; missing indicators or rank collisions remain incomplete."""
        return submit_assessment(cs, actor(), operation_id)
    read_tool.__name__ = 'read_assignment'
    set_tool.__name__ = 'set_indicator'
    submit_tool.__name__ = 'submit_assessment'
    set_tool.message_model = model
    submit_tool.message_model = create_model('WriterAssessmentSubmitInput', __base__=Contract)
    return [read_tool, set_tool, submit_tool]


# The bounded route uses its own draft so an old free-form save cannot complete a step.
def _step_state(db, scope, actor):
    order = scope['plan']['payload'].get('indicator_rank_order')
    if not order:
        raise ActionRejected('WRITER_CONFIRMED_RANK_ORDER_REQUIRED')
    key = 'writer_indicator_steps:' + scope['assignment_digest']
    draft = _state(db, key)
    if draft is None:
        selected = 'g6_assessment:' + digest([scope['plan']['ref'], scope['object']['object_id']])
        if _state(db, selected) or _draft(db, scope, actor)['rows']:
            raise ActionRejected('WRITER_FRESH_INDICATOR_ASSIGNMENT_REQUIRED')
        draft = {'rows': {}, 'assessment_ref': None}
    rules = scope['plan']['payload']['method_pack']['indicators']
    rule = next((r for r in rules if r['id'] not in draft['rows']), None)
    status = {'complete': rule is None, 'progress': {'recorded': len(draft['rows']), 'total': len(rules)},
              'gap_indicators': [r['id'] for r in rules if draft['rows'].get(r['id'], {}).get('kind') == 'gap'],
              'assessment_ref': draft['assessment_ref']}
    return key, draft, rule, status


def read_indicator_step(cs, actor):
    """Prepare just the next judgment, bound to the owner-confirmed plan and method."""
    from .writer_assignments import read_assignment_pages
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
        _, draft, rule, status = _step_state(db, scope, actor)
        if status['complete']:
            return {**status, 'outcomes': draft['rows']}
        order = scope['plan']['payload']['indicator_rank_order']
        packet = {**status, 'assignment_digest': scope['assignment_digest'],
                  'object_label': scope['object']['label'], 'indicator_id': rule['id'],
                  'indicator': _label(rule), 'notes': rule['notes'],
                  'rank': order['indicator_ids'].index(rule['id']) + 1,
                  'rank_basis': order['source']['quote'],
                  'grades': [{**{k:g[k] for k in ('description','min_value','max_value')},
                              'choice':_grade(g)} for g in rule['grades']],
                  **_assignment_context(cs, db, scope)}
    index = read_assignment_pages(cs, actor)
    return {**packet, 'sources': index['sources'], 'page_index_digest': index['index_digest'],
            'limitations': index.get('limitations', [])}


@lru_cache(maxsize=128)
def _step_schema(choices):
    grade = Literal[choices]

    @model_validator(mode='after')
    def matches_kind(self):
        if self.kind == 'gap':
            if (not self.missing.strip() or not self.question.strip() or self.grade is not None
                    or self.value is not None or self.basis_kind or self.plausible_grades or self.rationale):
                raise ValueError('A gap requires missing information and a review question, without a proposed score.')
        else:
            if self.missing or self.grade is None or self.value is None or not self.rationale.strip() or not self.quotes:
                raise ValueError('A scored judgment requires a grade, value, rationale and exact quoted basis.')
            if self.kind == 'assumption':
                if self.basis_kind != 'indirect_assumption' or not self.question.strip() or not self.plausible_grades:
                    raise ValueError('Explain the assumption and provide plausible grades and a review question.')
            elif self.basis_kind not in ('direct_evidence', 'applied_guideline') or self.plausible_grades:
                raise ValueError('Evidence requires a supported evidence basis.')
        return self

    return create_model('IndicatorStepOutcome', __base__=Contract, __validators__={'matches_kind':matches_kind},
        kind=(Literal['evidence','assumption','gap'], ...), grade=(grade | None, None),
        value=(str | None, None), basis_kind=(Literal['direct_evidence','applied_guideline','indirect_assumption'] | None, None),
        rationale=(str, ''), quotes=(list[str], Field(default_factory=list)),
        plausible_grades=(list[grade], Field(default_factory=list)), missing=(str, ''), question=(str, ''),
        contrary_evidence=(str, ''))


def step_outcome_schema(cs, actor, indicator_id):
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
        _, _, rule, _ = _step_state(db, scope, actor)
        if not rule or rule['id'] != indicator_id:
            raise ActionRejected('WRITER_INDICATOR_STEP_MISMATCH')
        return _step_schema(tuple(_grade(g) for g in rule['grades']))


def save_indicator_outcome(cs, actor, operation_id, indicator_id, outcome, *, read_locations=()):
    """Atomically record one step, and score the last one only when every row supports it."""
    def save(db):
        scope = _assignment(cs, db, actor)
        key, draft, rule, _ = _step_state(db, scope, actor)
        if not rule or rule['id'] != indicator_id:
            raise ActionRejected('WRITER_INDICATOR_STEP_MISMATCH')
        model = _step_schema(tuple(_grade(g) for g in rule['grades']))
        value = model.model_validate(outcome).model_dump(mode='json')
        order = scope['plan']['payload']['indicator_rank_order']
        rank = order['indicator_ids'].index(indicator_id) + 1
        entry = {'kind':value['kind'], 'input':value, 'rank':rank, 'read_locations':list(read_locations)}
        if value['kind'] == 'gap':
            entry['sources'] = resolve_judgment_sources(cs, db, actor, scope, value['quotes'])
        else:
            bound = {**value, 'rank':rank, 'rank_reason':order['source']['quote'],
                     'low':None, 'high':None, 'visual_pages':[]}
            entry['judgment'] = _validated_judgment(cs, db, actor, scope, rule, bound)
        draft['rows'][indicator_id] = entry
        _set(db, key, draft)
        _, _, _, status = _step_state(db, scope, actor)
        if status['complete'] and not status['gap_indicators']:
            receipt = _score_saved_rows(cs, db, actor, operation_id, scope, draft)
            draft['assessment_ref'] = status['assessment_ref'] = receipt['assessment_ref']
            _set(db, key, draft)
        return {**status, 'saved_indicator':indicator_id}
    return cs.operation(actor, operation_id,
        {'indicator_step':indicator_id,'outcome':outcome,'read_locations':list(read_locations)}, save,
        binding_identity=lambda db, result: _assignment(cs, db, actor)['assignment_digest'])
