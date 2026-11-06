"""The approved plan binds rank; a gap closes work without manufacturing a score."""
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from report_agent import writer_assessment as api
from report_agent.content_store import Actor
from report_agent.errors import ActionRejected
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission
from test_writer_assessment import assigned


def attach_ranks(f):
    f.plan['indicator_rank_order'] = {'indicator_ids': ['B', 'A', 'D', 'C'],
        'source': f.cite('scope', 'Owner rank order: B, A, D, C.')}


def make_assignment(f):
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    saved = save(f)
    approve(f, saved)
    prior = writer(f, saved, section_ids=['4'])
    task = deepcopy(f.cs.read({'type': 'DelegatedTask', 'id': prior.task_id, 'version': 1})['payload'])
    task['assessment_object_id'] = 'S1'
    ref = f.cs.operation(f.co, 'assign-indicators', {}, lambda db: f.cs._insert(db, f.co, 'DelegatedTask', task))['result']
    f.actor = Actor('content:writer:' + ref['id'], 'writer', ref['id'])
    return f


@pytest.fixture
def ranked(method_commission):
    attach_ranks(method_commission)
    return make_assignment(method_commission)


def evidence(f, step):
    return {'kind':'evidence', 'grade':step['grades'][1]['choice'],
            'value':'40', 'basis_kind':'direct_evidence', 'rationale':'The supplied design records S1.',
            'quotes':[f.cite('design')['quote']]}


def test_rankless_plan_refused_before_first_step(assigned):
    with pytest.raises(ActionRejected, match='CONFIRMED_RANK_ORDER_REQUIRED'):
        api.read_indicator_step(assigned.cs, assigned.actor)


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_evidence_then_gap_persist_and_no_score(ranked):
    f = ranked
    first = api.read_indicator_step(f.cs, f.actor)
    assert (first['indicator_id'], first['rank']) == ('A', 2)
    valid = evidence(f, first)
    with pytest.raises((ValidationError, ActionRejected)):
        api.save_indicator_outcome(f.cs, f.actor, 'forged', 'A', {**valid, 'rank':1})
    with pytest.raises(ActionRejected):
        api.save_indicator_outcome(f.cs, f.actor, 'fabricated', 'A', {**valid, 'quotes':['invented']})
    a = api.save_indicator_outcome(f.cs,f.actor,'choose-a','A',valid)
    assert api.save_indicator_outcome(f.cs,f.actor,'choose-a','A',valid) == a
    assert a['result']['progress'] == {'recorded':1,'total':4}
    for name in ['B','C','D']:
        step = api.read_indicator_step(f.cs,f.actor)
        assert step['indicator_id'] == name
        api.save_indicator_outcome(f.cs,f.actor,'gap-'+name,name,{'kind':'gap','missing':'Survey unavailable',
            'question':'Can a survey be supplied?'})
    done = api.read_indicator_step(f.cs, f.actor)
    assert done['complete'] and done['gap_indicators'] == ['B','C','D']
    assert done['assessment_ref'] is None and f.cs.list_objects('Assessment') == []
    assert done['outcomes']['A']['judgment']['sources'][0]['quote'] == f.cite('design')['quote']
    assert done['outcomes']['B']['input']['missing'] == 'Survey unavailable'



@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_all_rows_can_score_under_approved_ranks(ranked):
    f = ranked
    for name in ['A','B','C','D']:
        step = api.read_indicator_step(f.cs,f.actor)
        row = evidence(f, step)
        if name=='C':
            row.update(kind='assumption',basis_kind='indirect_assumption',
                question='Confirm grade?',plausible_grades=[g['choice'] for g in step['grades'][1:3]])
        receipt = api.save_indicator_outcome(f.cs, f.actor,'judgment-'+name,name,row)
    ref = receipt['result']['assessment_ref']
    payload = f.cs.read(ref)['payload']
    assert {row['indicator_id']:row['rank'] for row in payload['indicators']} == {'B':1,'A':2,'D':3,'C':4}
    assert float(payload['result']['adopted']['total']) == 40
    assert api.read_indicator_step(f.cs,f.actor)['assessment_ref'] == ref


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_rank_order_requires_complete_permutation_and_scope_source(method_commission):
    f=method_commission
    attach_ranks(f)
    f.plan['indicator_rank_order']['indicator_ids'][0]='A'
    with pytest.raises((ValidationError,ActionRejected), match='RANK_ORDER'):
        save(f)
    attach_ranks(f)
    f.plan['indicator_rank_order']['source']=f.cite('template')
    with pytest.raises(ActionRejected, match='RANK_ORDER'):
        save(f)


def test_real_mini_scope_ranks_are_exactly_bound_and_ambiguous_input_fails_closed(method_commission):
    import json
    from importlib.resources import files
    from report_agent.commission_planning import _owner_rank_binding
    from report_agent.commission_requirements import extract_anchors
    from test_m1_g4_requirements import capture

    f = method_commission
    scope = Path(__file__).parent / 'fake_data/mini_commission/inputs/00_scope.md'
    ref = capture(f, '00_scope.md', scope.read_bytes(), 'fake-commission-ranks')
    conventions = [a for a in extract_anchors(f.cs, ref, None) if a['kind'] == 'convention']
    pack = json.loads(files('report_agent').joinpath('methods/high_slope_guideline.json').read_text())
    rules = pack['indicators']
    order = _owner_rank_binding(conventions, rules)
    assert order['source']['source_ref'] == ref
    assert order['source']['quote'] in scope.read_text()
    assert order['indicator_ids'] == ['X11','X23','X21','X22','X12','X31','X32','X41','X51','X52','X42']
    with pytest.raises(ActionRejected, match='AMBIGUOUS'):
        _owner_rank_binding(conventions + conventions, rules)
    wrong = deepcopy(order['source'])
    wrong['quote'] = wrong['quote'].replace('10 X52', '10 X42')
    with pytest.raises(ActionRejected, match='INVALID'):
        _owner_rank_binding([{'source':wrong}], rules)
    assert _owner_rank_binding([{'source':{'quote':'Unapproved example: ' + order['source']['quote']}}], rules) is None
