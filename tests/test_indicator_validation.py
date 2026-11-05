from copy import deepcopy
import pytest
from report_agent.errors import ActionRejected
from report_agent.risk_scoring import (validate_indicator_judgment, validate_indicator_sources,
    save_assessment_in_transaction)
from test_m1_g3_integration import method_commission, persistence_input
from test_m1_commission_plan import save, approve, writer

@pytest.fixture
def ready(method_commission):
    f=method_commission
    saved=save(f);approve(f,saved);f.actor=writer(f,saved)
    f.saved_plan=f.cs.read(saved['plan_ref'])
    return f

def test_one_indicator_validates_without_inventing_other_rows(ready):
    f=ready;row=persistence_input(f)['indicators'][0];before=deepcopy(row)
    actual=validate_indicator_judgment(f.plan['method_pack'],row)
    assert actual['indicator_id']==row['indicator_id'] and row==before

@pytest.mark.parametrize('field,value,match',[
    ('rank',99,'rank'),('value','NaN','finite'),('grade_id','invented','grade'),
    ('rank_reason','','rank_reason'),('rationale','','rationale')])
def test_invalid_indicator_is_rejected_before_draft_save(ready,field,value,match):
    f=ready;row=persistence_input(f)['indicators'][0];row[field]=value
    with pytest.raises(ActionRejected,match=match):validate_indicator_judgment(f.plan['method_pack'],row)

def test_assumption_extremes_come_from_offered_plausible_grades(ready):
    f=ready;row=next(r for r in persistence_input(f)['indicators'] if r['basis_kind']=='indirect_assumption')
    actual=validate_indicator_judgment(f.plan['method_pack'],row)
    definition=next(i for i in f.plan['method_pack']['indicators'] if i['id']==row['indicator_id'])
    grades=[g for g in definition['grades'] if g['id'] in row['plausible_grades']]
    from decimal import Decimal
    assert Decimal(actual['low'])==min(Decimal(g['min_value']) for g in grades)
    assert Decimal(actual['high'])==max(Decimal(g['max_value']) for g in grades)

def test_row_source_checks_share_exact_locator_guard(ready):
    f=ready;row=persistence_input(f)['indicators'][0];row['sources'][0]['quote']='not in this source'
    with f.ws.store.connect() as db,pytest.raises(ActionRejected,match='QUOTE_NOT_AT_SOURCE_LOCATION'):
        validate_indicator_sources(f.cs,db,f.actor,f.saved_plan,'4',[row])

def test_canonical_transaction_helper_rolls_back_with_caller(ready):
    f=ready;data=persistence_input(f)
    with f.ws.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        result=save_assessment_in_transaction(f.cs,db,f.actor,'in-transaction',data)
        assert result['assessment_ref']['type']=='Assessment'
        db.rollback()
    assert not f.cs.list_objects('Assessment')
