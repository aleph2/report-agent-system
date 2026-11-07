"""Incremental judgments for one host-assigned Writer; all identities stay server-owned."""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, create_model, model_validator
from pydantic_core import PydanticCustomError

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


# Approved fake03 qualitative subset. Full-method grades, ranks and sources stay bound to the plan.
FAKE03_QUALITATIVE_INDICATORS = frozenset(('X21','X22','X23','X32','X41','X42','X51','X52'))


def _assignment(cs, db, actor):
    from .writer_assignments import bound_assignment
    scope = bound_assignment(cs, db, actor)
    _layout(scope['plan']['payload']['method_pack'])
    binding = _state(db, 'fake03_qualitative_actor:' + actor.id)
    if binding is not None:
        profile = _state(db, 'fake03_qualitative_profile')
        if (binding['plan_ref'] != scope['plan']['ref'] or binding['object_id'] != scope['object']['object_id']
                or binding['profile_digest'] != digest(profile)):
            raise ActionRejected('FAKE_QUALITATIVE_PROFILE_MISMATCH')
        scope['qualitative_profile'] = profile
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
        draft = {'rows': {}, 'assessment_ref': None, 'interrupted_indicators': {}}
    rules = scope['plan']['payload']['method_pack']['indicators']
    if 'qualitative_profile' in scope:
        rules = [r for r in rules if r['id'] in FAKE03_QUALITATIVE_INDICATORS]
    interrupted = draft.get('interrupted_indicators', {})
    rule = next((r for r in rules if r['id'] not in draft['rows'] and r['id'] not in interrupted), None)
    status = {'complete': rule is None, 'progress': {'recorded': len(draft['rows']), 'total': len(rules)},
              'gap_indicators': [r['id'] for r in rules if draft['rows'].get(r['id'], {}).get('kind') == 'gap'],
              'assessment_ref': draft['assessment_ref'], 'interrupted_indicators': interrupted}
    return key, draft, rule, status


def _source_priority(cs, db, plan):
    """Return the classified rule from the version approved with this plan."""
    if not plan.get('requirements_ref'):
        return None
    requirements = cs._read(db, plan['requirements_ref'])['payload']
    anchors = {a['id']: a['source'] for a in requirements['anchors']}
    return [{'scope_quote': anchors[i['anchor_id']]['quote'],
             'location': anchors[i['anchor_id']]['locator'], 'interpretation': i['interpretation']}
            for i in requirements['items']
            if i['status'] == 'required' and 'source_priority' in i['capabilities']]


def read_indicator_step(cs, actor):
    """Prepare just the next judgment, bound to the owner-confirmed plan and method."""
    from .method_pack import CATEGORY_DOCUMENTATION_NOTES
    from .writer_assignments import read_assignment_pages
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
        _, draft, rule, status = _step_state(db, scope, actor)
        if status['complete']:
            return {**status, 'outcomes': draft['rows']}
        order = scope['plan']['payload']['indicator_rank_order']
        packet = {**status, 'assignment_digest': scope['assignment_digest'],
                  'object_label': scope['object']['label'], 'indicator_id': rule['id'],
                  'indicator': _label(rule), 'notes': rule['notes'], 'category': rule.get('category', ''),
                  'source_priority': _source_priority(cs, db, scope['plan']['payload']),
                  'rank': order['indicator_ids'].index(rule['id']) + 1,
                  'rank_basis': order['source']['quote'],
                  'grades': [{**{k:g[k] for k in ('description','min_value','max_value')},
                              'choice':_grade(g)} for g in rule['grades']],
                  **_assignment_context(cs, db, scope)}
        if 'qualitative_profile' in scope:
            profile = scope['qualitative_profile']
            packet['object_facts'] = profile['facts'][scope['object']['object_id']]
            if decision := packet['object_facts'].get('engineering_reviews', {}).get(rule['id']):
                packet['engineering_review'] = decision
            packet['midpoint_convention'] = profile['midpoint_convention']
            if 'attestations' in packet['object_facts']:
                assigned_ids = {f['fact_id'] for f in packet['object_facts']['attestations']}
                packet['other_context_facts'] = [{k:f[k] for k in ('fact_id','subject','purpose','quote')}
                    for f in _typed_facts(scope) if f['fact_id'] not in assigned_ids]
                packet['claim_instructions'] = (
                    'Select the fact handles that support each distinct claim. State what establishes the grade, '
                    'how an assumption relates to this object and narrows alternatives, and the direction and basis '
                    'for any within-band adjustment. Cite registered excerpts by fact_id. Other objects’ facts can be '
                    'used as context or contrary evidence. An event count and '
                    'its period must refer to the same hazard observation. For every investigation count or zero, '
                    'identify the corresponding observation for this object. A source covering another object or '
                    'a reference to an unread drawing cannot establish absence. Use save_gap when support is missing.')
                if rule['id']=='X32':
                    packet['method_adjustment'] = {'condition':'construction during a disaster-prone season',
                                                   'target':'in_band_value','direction':'higher'}
        if note := CATEGORY_DOCUMENTATION_NOTES.get(packet['category']):
            packet['documentation_note'] = note
    index = read_assignment_pages(cs, actor)
    return {**packet, 'sources': index['sources'], 'page_index_digest': index['index_digest'],
            'limitations': index.get('limitations', [])}


@lru_cache(maxsize=128)
def _step_schema(choices, kind, qualitative=False, fact_ids=None):
    from .writer_issues import IndicatorConflict
    grade = Literal[choices]
    nonblank = Annotated[str, Field(min_length=1, pattern=r'\S')]
    common = {
        'quotes':(list[nonblank],Field(default_factory=list,
            description='Exact source quotations. The system resolves unique source locations.')),
        'contrary_evidence':(IndicatorConflict | None, Field(default=None,
            description='An actual conflict with both quoted values and the adopted basis, for the material-issue record.'))
    }
    typed_fields = {}
    if fact_ids is not None:
        from .writer_claims import claim_fields
        typed_fields = claim_fields(kind, fact_ids)
        common.update(typed_fields)
    if kind == 'gap':
        return create_model('WriterGap',__base__=Contract,**common,
            missing=(nonblank,Field(description='Name the missing fact that prevents a defensible judgment.')),
            question=(nonblank,Field(description='Ask the specific question needed to resolve this gap.')),
            rationale=(str,Field(default='',description='Optional explanation of why the supplied evidence cannot resolve the indicator.')))
    if kind not in ('evidence','assumption'):
        raise ActionRejected('WRITER_INDICATOR_KIND_INVALID')

    @model_validator(mode='after')
    def plausible(self):
        if kind=='assumption' and self.grade not in self.plausible_grades:
            raise PydanticCustomError('adopted_grade_not_plausible',
                'Include the adopted grade in plausible_grades, or correct the adopted grade.')
        return self

    scoring = {
        **common,
        'grade':(grade, Field(description='Choose one of the offered grade labels.')),
        'value':(str,Field(pattern=r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$',
            description='Finite decimal string within the chosen grade bounds. Put explanations and calculations in rationale.')),
        'rationale':(nonblank,Field(description='Explain the quoted basis, grade and numeric value, including limitations.')),
        'quotes':(list[nonblank],Field(min_length=1,
            description='Exact supporting project quotations. Applied-guideline evidence also needs an exact approved method quotation.'))
    }
    if qualitative:
        scoring['value'] = (str | None, Field(default=None, pattern=r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$',
            description='Omit to use the midpoint of the adopted grade. Supply an alternative only with value_reason.'))
        scoring['value_reason'] = (nonblank | None, Field(default=None,
            description='Specific object fact and reasoning for departing from the midpoint within the adopted grade.'))
    scoring.update(typed_fields)
    if kind=='evidence':
        scoring['basis_kind']=(Literal['direct_evidence','applied_guideline'],Field(
            description='direct_evidence uses project facts; applied_guideline uses project facts plus a quoted approved guideline rule.'))
    else:
        scoring.update(plausible_grades=(list[grade],Field(min_length=1,
            description='Plausible offered grades, including the adopted grade. The system computes sensitivity bounds.')),
            question=(nonblank,Field(description='Ask what evidence would confirm or revise this assumption.')))
    return create_model('WriterEvidence' if kind=='evidence' else 'WriterAssumption',
        __base__=Contract,__validators__={'plausible':plausible},**scoring)


def _typed_facts(scope):
    profile = scope.get('qualitative_profile', {})
    current = profile.get('facts', {}).get(scope['object']['object_id'], {})
    if 'attestations' not in current:
        return None
    # A review question may cite a different object's source as context. Decisive support
    # is restricted to the assessed object by the native claim validator.
    return list({row['fact_id']:row for obj in profile['facts'].values()
                 for row in obj.get('attestations', [])}.values())


def _fact_ids(facts):
    return tuple(f['fact_id'] for f in facts) if facts is not None else None


def step_outcome_schema(cs, actor, indicator_id, kind):
    with cs.store.connect() as db:
        scope = _assignment(cs, db, actor)
        _, _, rule, _ = _step_state(db, scope, actor)
        if not rule or rule['id'] != indicator_id:
            raise ActionRejected('WRITER_INDICATOR_STEP_MISMATCH')
        return _step_schema(tuple(_grade(g) for g in rule['grades']),kind,'qualitative_profile' in scope,_fact_ids(_typed_facts(scope)))


def _step_value(rule, outcome, *, qualitative=False, facts=None):
    from .message_fields import validate_message
    data = deepcopy(outcome)
    kind = data.pop('kind', None)
    # Legacy local callers used an explicit basis tag. The public assumption tool owns it now.
    if kind == 'assumption' and data.get('basis_kind') == 'indirect_assumption':
        data.pop('basis_kind')
    value = validate_message(_step_schema(tuple(_grade(g) for g in rule['grades']),kind,qualitative,_fact_ids(facts)),data).model_dump(mode='json')
    if qualitative and kind in ('evidence','assumption'):
        from .method_pack import number
        band = next(g for g in rule['grades'] if _grade(g) == value['grade'])
        midpoint = (number(band['min_value']) + number(band['max_value'])) / 2
        if value['value'] is None:
            value['value'] = str(midpoint)
        elif facts is None and number(value['value']) != midpoint and not value['value_reason']:
            raise ActionRejected('WRITER_NON_MIDPOINT_VALUE_REASON_REQUIRED')
        if value['value_reason'] is None:
            value.pop('value_reason')
    return {'kind':kind,'grade':None,'value':None,'basis_kind':None,'question':'',
            'rationale':'','missing':'','plausible_grades':[],**value,
            **({'basis_kind':'indirect_assumption'} if kind=='assumption' else {})}


def save_indicator_outcome(cs, actor, operation_id, indicator_id, outcome, *, read_locations=()):
    """Atomically record one step, and score the last one only when every row supports it."""
    def save(db):
        scope = _assignment(cs, db, actor)
        key, draft, rule, _ = _step_state(db, scope, actor)
        if not rule or rule['id'] != indicator_id:
            raise ActionRejected('WRITER_INDICATOR_STEP_MISMATCH')
        object_facts = scope.get('qualitative_profile', {}).get('facts', {}).get(scope['object']['object_id'], {})
        decision = object_facts.get('engineering_reviews', {}).get(indicator_id)
        if decision and outcome.get('kind') != 'gap':
            raise ActionRejected('WRITER_ENGINEERING_REVIEW_PENDING: use save_gap. '+decision['reason'])
        facts = _typed_facts(scope)
        value = _step_value(rule, outcome, qualitative='qualitative_profile' in scope, facts=facts)
        claim_receipt = {}
        if facts is not None:
            from .method_pack import number
            from .writer_claims import apply_claims
            band = next((g for g in rule['grades'] if _grade(g)==value['grade']),None)
            midpoint = (number(band['min_value'])+number(band['max_value']))/2 if band else None
            if band and not number(band['min_value']) <= number(value['value']) <= number(band['max_value']):
                raise ActionRejected('WRITER_VALUE_OUTSIDE_CHOSEN_GRADE')
            value, checks = apply_claims(value, indicator_id=indicator_id, subject=scope['object']['object_id'],
                                         attestations=facts, midpoint=midpoint, grade_id=band['id'] if band else None,
                                         registered_excerpts=[r['quote'] for obj in scope['qualitative_profile']['facts'].values()
                                            for r in [*obj.get('observations',[]), *obj.get('attestations',[])] if r.get('quote')])
            claim_receipt = {'claim_checks': checks}
        if decision:
            claim_receipt.setdefault('claim_checks', {}).update(engineering_review=decision, semantic_review_required=True)
        order = scope['plan']['payload']['indicator_rank_order']
        rank = order['indicator_ids'].index(indicator_id) + 1
        entry = {'kind':value['kind'], 'input':value, 'rank':rank, 'read_locations':list(read_locations), **claim_receipt}
        if value['kind'] == 'gap':
            entry['sources'] = resolve_judgment_sources(cs, db, actor, scope, value['quotes'])
        else:
            bound = {**value, 'rank':rank, 'rank_reason':order['source']['quote'],
                     'low':None, 'high':None, 'visual_pages':[]}
            entry['judgment'] = _validated_judgment(cs, db, actor, scope, rule, bound)
        issue_receipt = {}
        if value['contrary_evidence']:
            from .writer_issues import save_indicator_conflict
            issue_receipt = save_indicator_conflict(cs,db,actor,operation_id,scope,value['contrary_evidence'])
            entry.update(issue_receipt)
        draft['rows'][indicator_id] = entry
        _set(db, key, draft)
        _, _, _, status = _step_state(db, scope, actor)
        if (status['complete'] and 'qualitative_profile' not in scope
                and not status['gap_indicators'] and not status['interrupted_indicators']):
            receipt = _score_saved_rows(cs, db, actor, operation_id, scope, draft)
            draft['assessment_ref'] = status['assessment_ref'] = receipt['assessment_ref']
            _set(db, key, draft)
        return {**status, 'saved_indicator':indicator_id, **issue_receipt, **claim_receipt}
    return cs.operation(actor, operation_id,
        {'indicator_step':indicator_id,'outcome':outcome,'read_locations':list(read_locations)}, save,
        binding_identity=lambda db, result: _assignment(cs, db, actor)['assignment_digest'])


def interrupt_indicator_step(cs, actor, indicator_id, refusals):
    """Trusted host records two distinct refused saves without inventing an engineering outcome."""
    names = {'save_evidence','save_assumption','save_gap'}
    if (len(refusals)!=2 or any(r.get('tool') not in names or not r.get('code') or not r.get('tool_call_id')
                               for r in refusals)
            or len({r['tool_call_id'] for r in refusals})!=2):
        raise ActionRejected('WRITER_TWO_DISTINCT_SAVE_REFUSALS_REQUIRED')
    with cs.store.connect() as db:
        scope = _assignment(cs,db,actor)
    operation = 'indicator-interruption:' + digest([actor.id,scope['assignment_digest'],indicator_id,refusals])
    def record(db):
        current = _assignment(cs,db,actor)
        key,draft,rule,_ = _step_state(db,current,actor)
        if not rule or rule['id']!=indicator_id:
            raise ActionRejected('WRITER_INDICATOR_STEP_MISMATCH')
        draft.setdefault('interrupted_indicators',{})[indicator_id] = {
            'status':'interrupted: save rejected','refusals':deepcopy(refusals)}
        _set(db,key,draft)
        return _step_state(db,current,actor)[3]
    return cs.operation(actor,operation,{'indicator':indicator_id,'refusals':refusals},record,
        binding_identity=lambda db,result:_assignment(cs,db,actor)['assignment_digest'])
