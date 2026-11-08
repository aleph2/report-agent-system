"""Canonical save guards for typed grade support in a disposable qualitative pilot."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import pytest

from report_agent import writer_assessment as api
from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected
from support.fake03 import REGISTER, qualitative_profile, install
from report_agent.mini_commission import prepare_mini_commission
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from report_agent.writer_runtime import writer_session
from report_agent.writer_judgments import read_progress


def fact(fid, purpose, quote, obj='A', **kwargs):
    return {'fact_id':fid,'purpose':purpose,'state':'known','subject':obj,'applies_to':[obj],
            'indicator_ids':['X32','X42','X51','X52'],'related_to':[],'quote':quote,'coverage':'object','coverage_detail':'','visual_verified':False,
            **kwargs}


@pytest.fixture
def fixture(tmp_path):
    record = prepare_mini_commission(Path(__file__).parent/'fake_data'/'mini_commission'/'inputs',tmp_path/'case')
    ws = Workspace(Store(tmp_path/'case'))
    cs = ContentStore(ws.store)
    profile = qualitative_profile(hashlib.sha256(REGISTER.read_bytes()).hexdigest())
    actual = {r['fact_id']:r for obj in profile['facts'].values() for r in obj['attestations']}
    names = {'F03-A-SURVEY-SECTIONS':'sec','F03-A-BOREHOLES':'holes','F03-SURVEY-COVERAGE':'only',
             'F03-REGIONAL-RAIN':'rain','F03-OFFSITE-ROCKFALL':'event','F03-ROCKFALL-LOCATION':'loc'}
    records = [{**actual[key], 'fact_id':name} for key,name in names.items()]
    for obj in ['A','B']:
        profile['facts'][obj]['attestations'] = records
    return SimpleNamespace(ws=ws,cs=cs,profile=profile, plan=record['plan_ref'])


from contextlib import contextmanager
@contextmanager
def at(f, oid, indicator):
    label = next(o['label'] for o in f.cs.read(f.plan)['payload']['objects'] if o['object_id']==oid)
    install(f.ws, f.plan, f.profile)
    with writer_session(f.ws,label,None,assessment_only=True,indicator_steps=True,section_id='3') as session:
        actor = session.actor
        while True:
            step=api.read_indicator_step(f.cs,actor)
            if step['indicator_id']==indicator:
                yield actor, step
                return
            api.save_indicator_outcome(f.cs,actor,'skip-'+step['indicator_id'],step['indicator_id'],
                {'kind':'gap','missing':'Synthetic traversal','question':'Supply the documents?'})


def claim(*refs):
    return {'statement':'Synthetic proposition under test.','fact_ids':list(refs)}


def scored(step, grade='moderate', **kwargs):
    choices = {g['min_value']:g['choice'] for g in step['grades']}
    return {'kind':'evidence','grade':choices[{'moderate':'25','very_high':'75','low':'0'}[grade]],
            'rationale':'Synthetic rationale.','basis_kind':'direct_evidence',**kwargs}


@pytest.mark.parametrize('oid,indicator,fields',[('B','X32',{'grade_claim':claim('rain','event'),
    'event_frequency':{'fact_id':'rain','event_count':1,'period_years':5}}),
    ('A','X42',{'grade_claim':claim('event')}),
    ('A','X52',{'grade_claim':claim('only')}),
    ('B','X51',{'grade_claim':claim('only'),'investigation_counts':[{'fact_id':'only','purpose':'survey_section_count','count':0}]})])
def test_external_quote_cannot_bypass_typed_decisive_fact(fixture,oid,indicator,fields):
    with at(fixture,oid,indicator) as (actor,step):
        value=scored(step,quotes=['Additional outside-register source.'],**fields)
        with pytest.raises(ActionRejected,match='save_gap'):
            api.save_indicator_outcome(fixture.cs,actor,'bad',indicator,value)
        assert api.read_indicator_step(fixture.cs,actor)['indicator_id']==indicator


def test_positive_counts_keep_grade_with_midpoint_when_requested_override_has_no_quality_basis(fixture):
    # Exercise the general adjustment rule on a synthetic assignment without the pilot deferral.
    fixture.profile['facts']['A']['engineering_reviews'].clear()
    with at(fixture,'A','X51') as (actor,step):
        value=scored(step,grade_claim=claim('sec','holes'),investigation_counts=[
            {'fact_id':'sec','purpose':'survey_section_count','count':1},{'fact_id':'holes','purpose':'borehole_count','count':3}],
            value='49',value_reason='Other types were not mentioned.',adjustment_claim={**claim('holes'),'direction':'higher'})
        value['rationale'] = 'Use 49 because the other types were not mentioned.'
        receipt=api.save_indicator_outcome(fixture.cs,actor,'save','X51',value)['result']
        draft=read_progress(fixture.ws.store, step['assignment_digest'])['rows']['X51']
        assert draft['judgment']['value']=='37' and draft['judgment']['grade_id']=='moderate'
        assert len(draft['judgment']['sources'])==1
        adjustment=receipt['claim_checks']['adjustment']
        assert adjustment==draft['claim_checks']['adjustment'] and adjustment['proposed_value']=='49'
        assert adjustment['status']=='refused_midpoint_retained' and adjustment['retained_value']=='37'
        assert adjustment['original_rationale']==value['rationale']
        assert '49' not in draft['judgment']['rationale']



def test_owner_deferred_row_stays_unscored_for_reviewer(fixture):
    with at(fixture,'A','X51') as (actor,step):
        decision = step['engineering_review']
        assert decision['conditional_grades'] == ['low','moderate']
        evidence = scored(step, grade_claim=claim('sec','holes'), investigation_counts=[
            {'fact_id':'sec','purpose':'survey_section_count','count':1},
            {'fact_id':'holes','purpose':'borehole_count','count':3}])
        assumption = {**evidence, 'kind':'assumption', 'assumption_basis':{
            **claim('holes'), 'relationship':'Single section.', 'narrowing':'Three boreholes.'},
            'plausible_grades':[g['choice'] for g in step['grades'] if g['min_value'] in ['0','25']]}
        assumption.pop('basis_kind')
        for proposed in (evidence, assumption):
            with pytest.raises(ActionRejected, match='save_gap'):
                api.save_indicator_outcome(fixture.cs,actor,'attempt-'+proposed['kind'],'X51',proposed)
        receipt = api.save_indicator_outcome(fixture.cs,actor,'defer','X51',{
            'kind':'gap','missing':'X51 interpretation and remaining per-section counts.',
            'question':'Which reading applies, and were test pits or geophysical points recorded?'})['result']
        row = read_progress(fixture.ws.store, step['assignment_digest'])['rows']['X51']
        assert row['kind']=='gap' and 'judgment' not in row
        assert row['input']['grade'] is None and row['input']['value'] is None
        assert row['claim_checks']['engineering_review'] == receipt['claim_checks']['engineering_review'] == decision


@pytest.mark.parametrize(('supports','effective','disposition'), [
    (('event','loc'), '27', 'accepted_with_flag'), (('event',), '37', 'refused_midpoint_retained')])
def test_offsite_assumption_survives_and_question_is_flagged(fixture, supports, effective, disposition):
    with at(fixture,'A','X32') as (actor,step):
        value=scored(step,grade_claim=claim('event'))
        del value['basis_kind']
        value.update(kind='assumption',assumption_basis={**claim('event'),'relationship':'Nearby event outside A.',
                      'narrowing':'Nearby rockfall supports the low/moderate provisional range.'},
                     plausible_grades=[g['choice'] for g in step['grades'] if g['min_value'] in ['0','25']],
                     question='Would work in that season raise the frequency grade?',question_effect='grade',
                     value='27',value_reason='The event was off site.',adjustment_claim={**claim(*supports),'direction':'lower'})
        result=api.save_indicator_outcome(fixture.cs,actor,'save','X32',value)['result']
        draft=read_progress(fixture.ws.store, step['assignment_digest'])['rows']['X32']
        assert draft['kind']=='assumption' and draft['judgment']['value']==effective
        assert draft['claim']['adjustment']['disposition']==disposition
        assert draft['claim']['adjustment']['proposed']=='27'
        assert 'QUESTION_EFFECT_CONFLICT' in result['claim_checks']['review_flags']
        writer_ref = {'type':'DelegatedTask','id':actor.task_id,'version':1}
    from report_agent.qualitative_review import qualitative_reviewer_session
    with qualitative_reviewer_session(fixture.ws, writer_ref) as tools:
        frozen = tools['read_qualitative_row']('X32')['saved_row']
    assert frozen == draft
    assert {g['assertion_id'] for g in frozen['ground_details']} == {g['assertion_id'] for g in frozen['grounds']}
    event = next(g for g in frozen['ground_details'] if g['qualifiers']['fact_id']=='event')
    assert frozen['criterion_authority']['plan_ref'] == fixture.plan and frozen['criterion_authority']['rule_id'] == 'X32'
    assert event['status']=='confirmed' and event['strength_rank']==2
    assert event['subject']=='Region' and event['claim']['coverage']=='region'
    assert event['qualifiers']['event_count']==1
    assert 'no observation period' in event['qualifiers']['coverage_detail']
    assert not event['qualifiers'].get('period_years')


@pytest.mark.parametrize('kind', ['evidence', 'gap'])
def test_registered_subquote_must_use_fact_handle_before_native_save(fixture, kind):
    fixture.profile['facts']['A']['engineering_reviews'].clear()
    with at(fixture,'A','X51') as (actor,step):
        value = scored(step, grade_claim=claim('sec','holes'), investigation_counts=[
            {'fact_id':'sec','purpose':'survey_section_count','count':1},
            {'fact_id':'holes','purpose':'borehole_count','count':3}]) if kind=='evidence' else {
            'kind':'gap','question':'Is additional documentation available?', 'missing':'Other investigation points.'}
        value['quotes'] = ['断面设置 三个钻孔']
        with pytest.raises(ActionRejected, match='fact_id'):
            api.save_indicator_outcome(fixture.cs,actor,'registered-subquote','X51',value)
        assert api.read_indicator_step(fixture.cs,actor)['indicator_id']=='X51'



def test_object_totals_do_not_establish_per_section_count():
    from decimal import Decimal
    from report_agent.writer_claims import apply_claims

    facts = [fact('sections','survey_section_count','Two sections.',value=2),
             fact('holes','borehole_count','Three holes in the whole survey.',value=3)]
    value = {'kind':'evidence','value':'37','grade_claim':claim('sections','holes'),
             'investigation_counts':[{'fact_id':f['fact_id'],'purpose':f['purpose'],'count':f['value']} for f in facts]}
    with pytest.raises(ActionRejected, match='section'):
        apply_claims(value, indicator_id='X51', subject='A', attestations=facts, midpoint=Decimal(37), grade_id='moderate')


def test_gap_question_always_has_semantic_review_even_when_writer_claims_no_issue():
    from report_agent.writer_claims import apply_claims
    original = {'kind':'gap','missing':'Groundwater investigation is missing.',
                'question':'When did all the known wells dry up?'}
    row, checks = apply_claims(original, indicator_id='X23', subject='B', attestations=[], midpoint=None,grade_id=None)
    assert row['question']==original['question']
    assert 'QUESTION_REQUIRES_SEMANTIC_REVIEW' in checks['review_flags']
    assert checks['semantic_review_required']


def test_upper_bound_cannot_assume_unknown_geophysical_or_test_pit_count_is_zero():
    from decimal import Decimal
    from report_agent.writer_claims import apply_claims
    facts = [fact('sec','survey_section_count','One section.',value=1),
             fact('holes','borehole_count','Two boreholes.',value=2)]
    value = {'kind':'evidence','value':'62','grade_claim':claim('sec','holes'),
             'investigation_counts':[{'fact_id':f['fact_id'],'purpose':f['purpose'],'count':f['value']} for f in facts]}
    with pytest.raises(ActionRejected, match='count'):
        apply_claims(value, indicator_id='X51', subject='A', attestations=facts, midpoint=Decimal(62), grade_id='high')



def test_external_evidence_has_native_source_check_and_critical_scope_review(fixture):
    # Simulate a register that has not catalogued one real sentence of the synthetic design PDF.
    quote = '防护采用锚杆框架梁，设置截排水沟。'
    for obj in fixture.profile['facts'].values():
        obj['observations'] = [f for f in obj['observations'] if f['quote']!=quote]
    with at(fixture,'A','X41') as (actor,step):
        support = {'statement':'The drawing describes an anchored frame.', 'subject':'A',
                   'scope':'Design notes for A', 'quotes':['No such sentence in any attached source.']}
        value = scored(step, grade_claim=claim(), external_support=support)
        with pytest.raises(ActionRejected, match='QUOTE_NOT_FOUND'):
            api.save_indicator_outcome(fixture.cs,actor,'fabricated-external','X41',value)
        support['quotes'] = [quote]
        # Resolving a real quote proves its origin. A scored verdict also requires a confirmed
        # observation and an applicable classification rule for that object.
        with pytest.raises(ActionRejected, match="C3"):
            api.save_indicator_outcome(fixture.cs,actor,'real-external','X41',value)
        assert 'X41' not in read_progress(fixture.ws.store, step['assignment_digest'])['rows']
