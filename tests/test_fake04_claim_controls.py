"""Acceptance and refusal pairs through the production claim validator on real PDF-backed facts."""
from decimal import Decimal
from pathlib import Path
import pytest

from report_agent.errors import ActionRejected
from support.fake03 import attestations_for, load_attestations
from report_agent.writer_claims import apply_claims

FACTS=load_attestations(Path(__file__).parent/'fake_data/mini_commission_04/attestations.json')
N_FREQ='F04-N-FREQUENCY'
N_SEASON='F04-N-SEASON'
N_START='F04-N-START'
S_FREQ='F04-S-FREQUENCY'


def check(indicator, subject, ids, **fields):
    # The storage path checks grade bounds; use that band's midpoint here too.
    grade = fields.pop('grade_id','moderate')
    midpoint = Decimal({'low':12,'moderate':37,'high':62,'very_high':87}[grade])
    value={'kind':'evidence','value':str(midpoint),'grade_claim':{'statement':'Grounded test proposition.',
           'fact_ids':ids},'quotes':[],'rationale':'The saved observation supports this grade.',**fields}
    return apply_claims(value,indicator_id=indicator,subject=subject,attestations=attestations_for(FACTS,subject),
                        midpoint=midpoint,grade_id=grade)


def frequency(fid,count,years):
    return {'grade_id':'low' if count==0 else 'moderate', 'event_frequency':{'fact_id':fid,'event_count':count,'period_years':years}}


def count(fid,purpose,n):
    return {'investigation_counts':[{'fact_id':fid,'purpose':purpose,'count':n}]}


SURVEY_IDS=['F04-N-SECTIONS','F04-N-BOREHOLES','F04-N-PITS']
SURVEY_COUNTS=[
    {'fact_id':'F04-N-SECTIONS','purpose':'survey_section_count','count':1},
    {'fact_id':'F04-N-BOREHOLES','purpose':'borehole_count','count':3},
    {'fact_id':'F04-N-PITS','purpose':'test_pit_count','count':0},
]


@pytest.mark.parametrize('subject,indicator,valid,valid_fields,invalid,invalid_fields',[
    pytest.param('North','X32',[N_FREQ],frequency(N_FREQ,3,5),[N_FREQ],frequency(N_FREQ,3,1),id='event-specific-period'),
    pytest.param('South','X32',[S_FREQ],frequency(S_FREQ,0,5),[S_FREQ],frequency(S_FREQ,3,5),id='true-zero-not-an-invented-count'),
    pytest.param('North','X32',[N_FREQ],frequency(N_FREQ,3,5),[N_SEASON,N_START],{},id='season-and-start-cannot-set-frequency-grade'),
    pytest.param('North','X42',['F04-N-FACILITIES'],{'grade_id':'low'},['F04-N-GROUNDWATER'],{'grade_id':'low'},id='zero-facilities-vs-absence-of-groundwater'),
    pytest.param('South','X42',['F04-S-FACILITY'],{'grade_id':'very_high'},['F04-N-FACILITIES'],{'grade_id':'low'},id='survey-applies-to-own-object'),
    pytest.param('North','X51',SURVEY_IDS,{'investigation_counts':SURVEY_COUNTS},
                 SURVEY_IDS,{'investigation_counts':[*SURVEY_COUNTS[:2],
                 {'fact_id':'F04-N-BOREHOLES','purpose':'test_pit_count','count':0}]},id='zero-vs-unrecorded-investigation-type'),
    pytest.param('North','X51',SURVEY_IDS,{'investigation_counts':SURVEY_COUNTS},
                 ['F04-N-SECTIONS','F04-S-SURVEY-RECORD'],{'investigation_counts':[
                 SURVEY_COUNTS[0],{'fact_id':'F04-S-SURVEY-RECORD','purpose':'borehole_count','count':0}]},
                 id='object-count-vs-page-coverage'),
    pytest.param('North','X52',['F04-N-INDEX'],{},['F04-S-REF'],{},id='verified-file-inventory-vs-drawing-reference'),
    pytest.param('North','X52',['F04-N-INDEX','F04-N-DRAWING'],{},['F04-S-REF'],{},id='verified-drawing-contents-vs-unread-reference'),
    pytest.param('North','X23',['F04-N-GROUNDWATER'],{'grade_id':'low'},['F04-N-FACILITIES'],{'grade_id':'low'},id='groundwater-absence-vs-facility-absence'),
])
def test_supported_grade_and_paired_refusal(subject,indicator,valid,valid_fields,invalid,invalid_fields):
    row,checks=check(indicator,subject,valid,**valid_fields)
    assert row['quotes']
    if indicator=='X23':
        assert checks['semantic_review_required']
        assert 'ABSENCE_GRADE_REQUIRES_CRITICAL_REVIEW' in checks['review_flags']
    with pytest.raises(ActionRejected,match='save_gap'):
        check(indicator,subject,invalid,**invalid_fields)


@pytest.mark.parametrize('indicator,valid_grade,grade_fields,value,direction,valid_ids,invalid_ids',[
    ('X32',[N_FREQ],frequency(N_FREQ,3,5),'42','higher',[N_SEASON,N_START],[N_START]),
    ('X51',SURVEY_IDS,{'investigation_counts':SURVEY_COUNTS},
     '32','lower',['F04-N-INVESTIGATION'],['F04-N-BOREHOLES']),
])
def test_within_band_adjustment_and_paired_midpoint(indicator,valid_grade,grade_fields,value,direction,valid_ids,invalid_ids):
    def run(ids):
        return check(indicator,'North',valid_grade,**grade_fields,value=value,
                     value_reason='Separate directional evidence.',
                     adjustment_claim={'statement':'Within-band proposition.','fact_ids':ids,'direction':direction})
    row,checks=run(valid_ids)
    assert row['value']==value and 'ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW' in checks['review_flags']
    row,checks=run(invalid_ids)
    assert row['value']=='37' and checks['adjustment']['status']=='refused_midpoint_retained'


@pytest.mark.parametrize('subject,indicator,ids,fields',[
    ('South','X52',['F04-S-REF'],{}),
    ('South','X51',['F04-S-SURVEY-RECORD'],count('F04-S-SURVEY-RECORD','survey_section_count',0)),
    ('South','X32',[S_FREQ],frequency(N_FREQ,3,5)),
    ('South','X42',['F04-S-PARTIAL-ZERO'],{'grade_id':'low'}),
    ('North','X42',['F04-N-FACILITIES','F04-N-GROUNDWATER'],{'grade_id':'low'}),
    ('North','X51',['F04-N-PITS'],count('F04-N-PITS','test_pit_count',0)),
])
def test_own_reference_own_missing_coverage_and_foreign_frequency_are_insufficient(subject,indicator,ids,fields):
    with pytest.raises(ActionRejected,match='save_gap'):
        check(indicator,subject,ids,**fields)
