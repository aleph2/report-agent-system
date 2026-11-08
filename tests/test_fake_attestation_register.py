"""Typed fact boundaries are checked against the actual synthetic source pages."""
import hashlib
import json
from pathlib import Path
from pypdf import PdfReader
import pytest

from support.fake03 import (
    REGISTER, TYPED_REGISTER, load_attestations, attestations_for, qualitative_profile)

DATA=Path(__file__).parent/'fake_data'
FAKE04=DATA/'mini_commission_04'
ORIGINAL_REGISTER='2815c134887ae9e3fe12ae6c3ef130a3d53a94a6d8205778bc493ee669915fa1'


@pytest.mark.parametrize('register,sources',[
    (TYPED_REGISTER,DATA/'mini_commission'/'inputs'),
    (FAKE04/'attestations.json',FAKE04/'inputs')])
def test_attestations_bind_exact_source_page_quote_and_unique_id(register,sources):
    rows=load_attestations(register)
    assert rows and len({r['fact_id'] for r in rows})==len(rows)
    pages={}
    for row in rows:
        doc=row['document']
        if doc not in pages:
            pages[doc]=[p.extract_text() for p in PdfReader(sources/doc).pages]
        assert row['quote'] in pages[doc][row['page']-1], row['fact_id']


def test_fake03_provenance_and_visibility():
    assert hashlib.sha256(REGISTER.read_bytes()).hexdigest()==ORIGINAL_REGISTER
    per=qualitative_profile(ORIGINAL_REGISTER)['facts']
    a={r['purpose']:r for r in per['A']['attestations']}
    b={r['purpose']:r for r in per['B']['attestations']}
    assert a['borehole_count']['value']==3 and 'borehole_count' not in b
    assert b['groundwater_survey_coverage']['state']=='unknown'
    assert b['drawing_reference']['visual_verified'] is False
    assert a['drawing_reference']['applies_to']==['B']
    assert b['survey_coverage']['applies_to']==['A']
    assert 'facility_presence' not in a and 'facility_presence' not in b
    assert a['rainfall']['period_years']==5 and a['rainfall']['event_count'] is None
    assert b['hazard_event']['applies_to']==[] and b['hazard_event']['related_to']==['A']
    assert b['hazard_event']['period_years'] is None and 'hazard_frequency' not in b


def test_fake04_preserves_true_zero_and_measured_coverage():
    rows=load_attestations(FAKE04/'attestations.json')
    north={r['purpose']:r for r in attestations_for(rows,'North')}
    south={r['purpose']:r for r in attestations_for(rows,'South')}
    assert (north['hazard_frequency']['event_count'],north['hazard_frequency']['period_years'])==(3,5)
    assert (south['hazard_frequency']['event_count'],south['hazard_frequency']['period_years'])==(0,5)
    assert north['facility_presence']['state']=='explicit_absence'
    assert south['facility_presence']['state']=='known' and south['facility_presence']['coverage_detail']
    assert north['test_pit_count']['value']==0 and south['survey_coverage']['state']=='unknown'
    assert north['drawing_contents']['visual_verified'] and not south['drawing_reference']['visual_verified']
    assert north['design_file_coverage']['coverage']=='document'
