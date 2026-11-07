"""Claim checks for the qualitative pilot. Engineering interpretation belongs to review."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from unicodedata import normalize

from pydantic import Field, create_model

from .content_models import Contract
from .errors import ActionRejected
from .writer_issues import IndicatorConflict


Text = Annotated[str, Field(min_length=1, pattern=r'\S')]


class ExternalSupport(Contract):
    statement: Text
    subject: Text
    scope: Text
    quotes: list[Text] = Field(min_length=1)


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


# These are types of observations required by the indicator definitions, independent of object ID and prose.
_GRADE_PURPOSES = {
    'X21': {'material','weathering'}, 'X22': {'slope_structure'}, 'X23': {'groundwater_condition'},
    'X32': {'hazard_frequency'}, 'X41': {'engineering_measure'}, 'X42': {'facility_presence'},
    'X51': {'survey_section_count','borehole_count','test_pit_count','geophysical_point_count'}, 'X52': {'design_file_coverage','drawing_contents'},
}


def _facility_band(facts, grade):
    limits = {'very_high': (0.5,1.0), 'high': (1.0,1.5), 'moderate': (1.5,2.0)}
    if grade == 'low':
        surveyed = any(f['state']=='explicit_absence' and f.get('value')==0
            and (f.get('survey_extent') or {}).get('upslope_h',0)>=1.5
            and (f.get('survey_extent') or {}).get('downslope_h',0)>=2 for f in facts)
        if not surveyed:
            _refuse('The low facility band requires a negative inventory covering the method survey envelope.')
    closest = []
    for f in facts:
        loc = f.get('facility_location') or {}
        if loc:
            side = 0 if loc['side']=='upslope' else 1
            closest.append(next((g for g,pair in limits.items() if loc['distance_h']<=pair[side]),'low'))
    order = [*limits,'low']
    if closest and min(closest,key=order.index) != grade or grade!='low' and not closest:
        _refuse('The measured facility distance must support the selected band for the slope side.')


def _investigation_band(counts, grade):
    sections = counts.get('survey_section_count')
    holes = counts.get('borehole_count')
    pits = counts.get('test_pit_count',0)
    if sections is None:
        _refuse('State the documented section count as well as the investigation points for a direct survey grade.')
    if sections>1:
        _refuse('Object totals do not establish the investigation points in each section.')
    total_known = all(k in counts for k in ('borehole_count','test_pit_count','geophysical_point_count'))
    points = (holes or 0) + pits + counts.get('geophysical_point_count',0)
    valid = {
        'very_high': total_known and ((sections==0 and points==0) or (sections==1 and points<=1)),
        'high': total_known and sections==1 and points==2,
        'moderate': sections==1 and points==3,
        'low': sections>=1 and (holes or 0)>0 and pits>0 and holes+pits>=3,
    }
    if not valid.get(grade):
        _refuse('The stated section and investigation-point counts do not establish the selected method band.')


def _season_overlap(facts):
    months = {m for f in facts if f['purpose']=='hazard_season' for m in (f.get('months') or [])}
    for f in facts:
        if f['purpose']=='construction_date':
            try:
                if date.fromisoformat(f['value']).month in months:
                    return True
            except (ValueError,TypeError):
                continue
    return False


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

    def usable(f, *, offsite=False):
        if f['state'] not in ('known','explicit_absence') or indicator_id not in f['indicator_ids']:
            return False
        if f['purpose']=='drawing_contents' and not f.get('visual_verified'):
            return False
        if f['state']=='explicit_absence' and (f['subject']!=subject or f['coverage']!='object'):
            return False
        return subject in f['applies_to'] or (offsite and subject in f['related_to'])

    def normalized(text):
        return ''.join(normalize('NFKC', text).casefold().split())

    excerpts = {normalized(q) for q in [*(f['quote'] for f in attestations), *registered_excerpts] if q.strip()}
    external = value.get('external_support') or {}
    supplied_quotes = [*value.get('quotes', []), *external.get('quotes', [])]
    for q in map(normalized, supplied_quotes):
        if any(q in excerpt or excerpt in q for excerpt in excerpts):
            _refuse('Select the registered fact_id for this quotation using the appropriate claim or context field.')

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
    basis_facts = selected(value['assumption_basis']['fact_ids']) if assumption else []
    purposes = _GRADE_PURPOSES[indicator_id]
    if assumption and indicator_id=='X32':
        purposes = purposes | {'hazard_event'}
    def supports_grade(f):
        if f['purpose'] not in purposes or not usable(f,offsite=assumption and f['purpose']=='hazard_event'):
            return False
        if indicator_id in ('X42','X51','X52') and subject != f['subject']:
            return False
        if indicator_id in ('X42','X51') and f['coverage']!='object':
            return False
        return True
    if external:
        if external['subject'] != subject:
            _refuse('External evidence must concern the assessed object.')
        attached.extend(external['quotes'])
        checks['review_flags'].append('EXTERNAL_SCOPE_REQUIRES_CRITICAL_REVIEW')
    external_can_support = external and indicator_id in ('X21','X22','X41')
    def validate_decisive(rows, label):
        anchors = [f for f in rows if supports_grade(f)]
        if not anchors and not external_can_support:
            _refuse(label+' requires applicable '+', '.join(sorted(purposes))+' evidence.')
        for f in rows:
            if f in anchors:
                continue
            related_location = (assumption and indicator_id=='X32' and f['purpose']=='location' and usable(f,offsite=True)
                and any(a['purpose']=='hazard_event' and a.get('document')==f.get('document')
                        and a.get('page')==f.get('page') for a in anchors))
            if not related_location:
                _refuse('The decisive '+label+' handle '+f['fact_id']+' is contextual or concerns another subject.')
    validate_decisive(grade_facts,'grade')
    if assumption:
        validate_decisive(basis_facts,'assumption basis')
    if indicator_id=='X42' and not assumption:
        _facility_band(grade_facts,grade_id)
    if not assumption and indicator_id=='X23' and any(f['state']=='explicit_absence' for f in grade_facts):
        checks['review_flags'].append('ABSENCE_GRADE_REQUIRES_CRITICAL_REVIEW')

    if indicator_id=='X32' and (not assumption or value.get('event_frequency')):
        observed = value.get('event_frequency') or {}
        fact = facts.get(observed.get('fact_id'))
        if (not fact or fact not in grade_facts or fact['purpose']!='hazard_frequency'
                or not usable(fact) or fact.get('event_count') is None or fact.get('period_years') is None
                or observed.get('event_count') != fact['event_count'] or observed.get('period_years') != fact['period_years']):
            _refuse('A direct frequency claim needs the event count and observation period from the same applicable event history.')
        if not assumption and fact['event_count']==0 and grade_id!='low':
            _refuse('Zero observed events cannot establish a positive event frequency in this period.')
        if not assumption and fact['event_count']>0:
            checks['review_flags'].append('FREQUENCY_GRADE_REQUIRES_CRITICAL_REVIEW')
    if indicator_id=='X51':
        counts = value.get('investigation_counts', [])
        if not counts:
            _refuse('Identify the documented investigation counts for the assessed object.')
        quantities = {}
        for count in counts:
            fact = facts.get(count['fact_id'])
            if (not fact or fact not in grade_facts or not supports_grade(fact) or fact['purpose'] != count['purpose']
                    or fact.get('value') != count['count']):
                _refuse('Every investigation count, including zero, needs an explicit value for this object and investigation type.')
            if count['purpose'] in quantities and quantities[count['purpose']]!=count['count']:
                _refuse('Conflicting count values cannot establish the same decisive observation.')
            quantities[count['purpose']] = count['count']
        if {f['fact_id'] for f in grade_facts} != {c['fact_id'] for c in counts}:
            _refuse('Every decisive investigation count must be spelled out with its typed observation.')
        if not assumption:
            _investigation_band(quantities,grade_id)
    if assumption:
        checks['review_flags'].append('ASSUMPTION_REQUIRES_SEMANTIC_REVIEW')
    if value.get('question'):
        checks['review_flags'].append('QUESTION_REQUIRES_SEMANTIC_REVIEW')
        if indicator_id=='X32':
            checks['seasonal_adjustment_target'] = 'in_band_value'
            if value.get('question_effect')=='grade':
                checks['review_flags'].append('QUESTION_EFFECT_CONFLICT')

    if Decimal(value['value']) != midpoint:
        proposed, reason = value['value'], value.get('value_reason')
        adjustment = value.get('adjustment_claim')
        refs = selected(adjustment['fact_ids'],attach=False) if adjustment else []
        direction = 'higher' if Decimal(proposed)>midpoint else 'lower'
        supports_direction = adjustment and reason and adjustment['direction']==direction
        if indicator_id=='X51':
            quality = 'limited' if direction=='higher' else 'adequate'
            adequate = bool(refs) and all(usable(f) and f['purpose']=='survey_investigation_quality'
                                          and f.get('value')==quality for f in refs)
        elif indicator_id=='X32':
            if direction=='higher':
                adequate = all(usable(f) and f['purpose'] in ('hazard_season','construction_date') for f in refs) and _season_overlap(refs)
            else:
                events = [f for f in refs if f['purpose']=='hazard_event' and subject in f['related_to'] and usable(f,offsite=True)]
                adequate = bool(events) and all(f in events or (f['purpose']=='location' and usable(f,offsite=True)
                    and any(f.get('document')==e.get('document') and f.get('page')==e.get('page') for e in events)) for f in refs)
        else:
            # Other method factors have no independently typed directional observation in this pilot.
            adequate = False
        if supports_direction and adequate:
            attached.extend(f['quote'] for f in refs)
            checks['review_flags'].append('ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW')
        else:
            checks['adjustment'] = {'status':'refused_midpoint_retained', 'proposed_value':proposed,
                'proposed_reason':reason,'proposed_claim':adjustment,'retained_value':str(midpoint),
                'reason':'No applicable fact supporting the proposed within-band direction.'}
            checks['adjustment']['original_rationale'] = value['rationale']
            value['rationale'] = value['grade_claim']['statement']+' The system retained the midpoint; the proposed adjustment was refused.'
            value['value'] = str(midpoint)
            value.pop('value_reason',None)
            value.pop('adjustment_claim',None)
            checks['review_flags'].append('UNSUPPORTED_ADJUSTMENT_RETAINED_MIDPOINT')
    value['quotes'] = list(dict.fromkeys([*value.get('quotes',[]),*attached]))
    return value, checks
