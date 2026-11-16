"""Claim checks for the qualitative pilot. Engineering interpretation belongs to review."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, create_model

from .content_models import Contract
from .errors import ActionRejected
from .writer_issues import IndicatorConflict


Text = Annotated[str, Field(min_length=1, pattern=r'\S')]


class ExternalSupport(Contract):
    statement: Text
    subject: Text
    scope: Text
    quotes: list[Text]


class ReferencedConflict(IndicatorConflict):
    # The host supplies quotes selected through contrary_fact_ids before native issue validation.
    quotes: list[Text] = Field(default_factory=list)


def claim_fields(kind, ids):
    handle = Literal[ids] if ids else Text
    handles = list[handle]
    common = {
        'quotes': (list[Text], Field(default_factory=list, description='Exact outside-register text only. Use fact_ids for quotations already in the register.')),
        'context_fact_ids': (handles, Field(default_factory=list)),
        'contrary_fact_ids': (handles, Field(default_factory=list)),
        'contrary_evidence': (ReferencedConflict | None, None),
    }
    if kind == 'gap':
        return {**common, 'fact_ids': (handles, Field(default_factory=list, description='Facts describing the gap or source coverage.'))}
    claim = create_model('FactClaim', __base__=Contract, statement=(Text,...), fact_ids=(handles,...))
    adjustment = create_model('AdjustmentClaim', __base__=claim, direction=(Literal['higher','lower'],...))
    frequency = create_model('EventFrequency', __base__=Contract, fact_id=(handle,...),
        event_count=(int,Field(ge=0,strict=True)), period_years=(float,Field(gt=0,allow_inf_nan=False)))
    count = create_model('InvestigationCount', __base__=Contract, fact_id=(handle,...),
        purpose=(Literal['survey_section_count','borehole_count','test_pit_count','geophysical_point_count'],...), count=(int,Field(ge=0,strict=True)))
    common.update(grade_claim=(claim, Field(description='Proposition establishing or provisionally supporting the grade, with its fact handles.')),
        external_support=(ExternalSupport | None,None),
        adjustment_claim=(adjustment | None,Field(default=None,description='Separate directional basis for a within-band departure.')),
        event_frequency=(frequency | None, Field(default=None,description='For direct frequency: select the event observation and its own count and time interval.')),
        investigation_counts=(list[count],Field(default_factory=list,description='Each survey count asserted for this object, including zero.')),
        question_effect=(Literal['information_only','in_band_value','grade'] | None,None))
    if kind=='assumption':
        basis=create_model('AssumptionBasis', __base__=claim, relationship=(Text,...), narrowing=(Text,...))
        common['assumption_basis']=(basis,Field(description='Positive fact, its relationship to this object, and how it narrows the proposed alternatives.'))
    return common


def _refuse(detail):
    raise ActionRejected('WRITER_CLAIM_UNSUPPORTED: '+detail+
        ' Use save_gap to record the missing support and a specific review question.',
        diagnostic={'reason':detail,'recommended_tool':'save_gap'})


def apply_claims(value, *, indicator_id, subject, attestations, midpoint, grade_id, registered_excerpts=()):
    """Validate the model's propositions and return the effective row and a separate audit record."""
    facts = {f['fact_id']: f for f in attestations}
    value = dict(value)
    checks = {'review_flags': [], 'semantic_review_required': value['kind']!='gap'}
    attached = []
    def selected(ids, *, attach=True):
        if any(i not in facts for i in ids):
            _refuse('Unknown or unoffered fact handle.')
        resolved = [facts[i] for i in ids]
        if attach:
            attached.extend(f['quote'] for f in resolved)
        return resolved

    external = value.get('external_support') or {}

    selected(value.get('context_fact_ids', []))
    contrary = selected(value.get('contrary_fact_ids', []))
    if issue := value.get('contrary_evidence'):
        value['contrary_evidence'] = {**issue,'quotes':list(dict.fromkeys([*issue.get('quotes',[]),*(f['quote'] for f in contrary)]))}
    if value['kind'] == 'gap':
        checks['semantic_review_required'] = True
        checks['review_flags'].append('GAP_RATIONALE_REQUIRES_SEMANTIC_REVIEW')
        if value.get('question'):
            checks['review_flags'].append('QUESTION_REQUIRES_SEMANTIC_REVIEW')
        selected(value.get('fact_ids', []))
        value['quotes'] = list(dict.fromkeys([*value.get('quotes',[]),*attached]))
        return value, checks

    assumption = value['kind'] == 'assumption'
    grade_facts = selected(value['grade_claim']['fact_ids'])
    selected(value['assumption_basis']['fact_ids'] if assumption else [])
    if external:
        attached.extend(external['quotes'])
        checks['review_flags'].append('EXTERNAL_SCOPE_REQUIRES_CRITICAL_REVIEW')
    if not assumption and indicator_id=='X23' and any(f['state']=='explicit_absence' for f in grade_facts):
        checks['review_flags'].append('ABSENCE_GRADE_REQUIRES_CRITICAL_REVIEW')

    if indicator_id=='X32' and value.get('event_frequency'):
        observed = value.get('event_frequency') or {}
        fact = facts.get(observed.get('fact_id'))
        if not assumption and fact['event_count']>0:
            checks['review_flags'].append('FREQUENCY_GRADE_REQUIRES_CRITICAL_REVIEW')
    if indicator_id=='X51':
        counts = value.get('investigation_counts', [])
        for count in counts:
            fact = facts.get(count['fact_id'])
    if assumption:
        checks['review_flags'].append('ASSUMPTION_REQUIRES_SEMANTIC_REVIEW')
    if value.get('question'):
        checks['review_flags'].append('QUESTION_REQUIRES_SEMANTIC_REVIEW')
        if indicator_id=='X32':
            checks['seasonal_adjustment_target'] = 'in_band_value'
            if value.get('question_effect')=='grade':
                checks['review_flags'].append('QUESTION_EFFECT_CONFLICT')

    if Decimal(value['value']) != midpoint:
        adjustment = value.get('adjustment_claim')
        refs = selected(adjustment['fact_ids'],attach=False) if adjustment else []
        attached.extend(f['quote'] for f in refs)
        checks['review_flags'].append('ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW')
    value['quotes'] = list(dict.fromkeys([*value.get('quotes',[]),*attached]))
    return value, checks
