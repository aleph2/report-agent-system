"""The approved plan binds rank; a gap closes work without manufacturing a score."""
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from report_agent import writer_assessment as api
from report_agent.errors import ActionRejected
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission
from test_writer_assessment import assigned


def attach_ranks(f):
    f.plan['indicator_rank_order'] = {'indicator_ids': ['B', 'A', 'D', 'C'],
        'source': f.cite('scope', 'Owner rank order: B, A, D, C.')}


def make_assignment(f):
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    from report_agent.catalog import Catalog
    from report_agent.commission_imports import source_roles, install_source_roles
    from test_ingestion import pdf_bytes
    from support.judgment_inputs import install_test_judgment_inputs
    f.evidence_quote = 'S1 survey records the synthetic observation.'
    source = Catalog(f.ws.store).import_file('S1-survey.pdf', pdf_bytes([f.evidence_quote]))['source']
    install_source_roles(f.ws.store, {**source_roles(f.ws.store), 'S1-survey': {'id': source['id'], 'purpose': 'survey'}})
    ref, = f.cs.capture_sources(f.co, 'survey-capture', [source['id']])['result']['source_refs']
    citation = dict(source_ref=ref, locator='page 1', quote=f.evidence_quote)
    next(section for section in f.plan['sections'] if section['section_id'] == '4')['sources'].append(citation)
    f.plan['objects'][0]['sources'].append(citation)
    saved = save(f)
    approve(f, saved)
    f.plan_ref = saved['plan_ref']
    install_test_judgment_inputs(f, 'S1', source['id'], 1, f.evidence_quote)
    f.actor = writer(f, saved, section_ids=['4'], assessment_object_id='S1', operation='assign-indicators')
    return f


@pytest.fixture
def ranked(method_commission):
    attach_ranks(method_commission)
    return make_assignment(method_commission)


def evidence(f, step):
    return {'kind':'evidence', 'grade':step['grades'][1]['choice'],
            'value':'40', 'basis_kind':'direct_evidence', 'rationale':'The supplied design records S1.',
            'quotes':[f.evidence_quote]}


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
    assert f.cs.read(done['assessment_ref'])['payload']['result']['status'] == 'unscored'
    from report_agent.assessment_completion import saved_assessments
    statuses = {}
    assert not saved_assessments(f.cs, f.plan_ref, ['S1'], f.actor.id, statuses=statuses)
    assert statuses == {'S1': 'unscored'}
    assert done['outcomes']['A']['judgment']['sources'][0]['quote'] == f.evidence_quote
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
    from report_agent.assessment_completion import saved_assessments
    statuses = {}
    assert saved_assessments(f.cs, f.plan_ref, ['S1'], f.actor.id, statuses=statuses) == {'S1': ref}
    assert statuses == {'S1': 'pending_review'}


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

@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_gap_accepts_rationale_but_refuses_scoring_fields(ranked):
    step=api.read_indicator_step(ranked.cs, ranked.actor)
    model=api.step_outcome_schema(ranked.cs,ranked.actor,step['indicator_id'],'gap')
    valid={'missing':'Natural slope angle missing','question':'What is the angle?',
           'rationale':'The difference of angles cannot be calculated.'}
    assert model.model_validate(valid).rationale == valid['rationale']
    for field,value in [('value',None),('grade',step['grades'][0]['choice']),
                        ('plausible_grades',[]),('basis_kind','direct_evidence'),('kind','gap')]:
        with pytest.raises(ValidationError):
            model.model_validate({**valid,field:value})

@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_refused_step_is_durable_and_no_scorable_row_is_created(ranked):
    f=ranked
    step=api.read_indicator_step(f.cs,f.actor)
    api.save_indicator_outcome(f.cs,f.actor,'first','A',evidence(f,step))
    refusals=[{'tool':'save_gap','tool_call_id':i,'code':'MESSAGE_FIELDS_INVALID'} for i in ['bad-1','bad-2']]
    receipt=api.interrupt_indicator_step(f.cs,f.actor,'B',refusals)
    assert api.interrupt_indicator_step(f.cs,f.actor,'B',refusals)==receipt
    assert receipt['result']['progress']['recorded']==1
    next_step=api.read_indicator_step(f.cs,f.actor)
    assert next_step['indicator_id']=='C' and next_step['interrupted_indicators']['B']['refusals']==refusals
    for identity in ['C','D']:
        step=api.read_indicator_step(f.cs,f.actor)
        api.save_indicator_outcome(f.cs,f.actor,identity,identity,evidence(f,step))
    done=api.read_indicator_step(f.cs,f.actor)
    assert done['complete'] and done['progress']=={'recorded':3,'total':4}
    assert 'B' not in done['outcomes']
    assert f.cs.read(done['assessment_ref'])['payload']['result']['status'] == 'unscored'


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_historical_rows_remain_readable_without_becoming_score_authority(ranked):
    f = ranked
    first = api.read_indicator_step(f.cs, f.actor)
    old = {'kind':'evidence','rank':first['rank'],'input':{'kind':'evidence','value':'40'}}
    # Reproduce a partial working draft recorded before the migration.
    f.ws.store.set('writer_indicator_steps:' + first['assignment_digest'],
                   dict(rows={'A':old}, assessment_ref=None))
    for indicator in ('B','C','D'):
        step = api.read_indicator_step(f.cs,f.actor)
        assert step['indicator_id'] == indicator
        api.save_indicator_outcome(f.cs,f.actor,'native-'+indicator,indicator,evidence(f,step))
    result = api.read_indicator_step(f.cs,f.actor)
    assert result['complete'] and result['outcomes']['A'] == old
    assert result['assessment_ref'] is None and f.cs.list_objects('Assessment') == []
    assert all(result['outcomes'][indicator]['assertion_id'] for indicator in ('B','C','D'))

@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_terminal_interruption_persists_unscored_result_without_fabricating_judgments(ranked):
    f = ranked
    refusals = [dict(tool='save_gap', code='MESSAGE_FIELDS_INVALID', tool_call_id=str(i)) for i in (1, 2)]
    for indicator in ('A','B','C','D'):
        receipt = api.interrupt_indicator_step(f.cs, f.actor, indicator, refusals)
    final = api.read_indicator_step(f.cs, f.actor)
    assert receipt['result']['assessment_ref'] == final['assessment_ref']
    assert final['complete'] and not final['outcomes']
    assert set(final['interrupted_indicators']) == set('ABCD')
    assert f.cs.read(final['assessment_ref'])['payload']['result']['status'] == 'unscored'
    assert api.interrupt_indicator_step(f.cs, f.actor, 'D', refusals) == receipt
    assert len(f.cs.list_objects('Assessment')) == 1

@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_reopen_final_interruption_after_derivation_commit_repairs_the_original_receipt(ranked, monkeypatch):
    from report_agent.assertion_host import AssertionHost
    from report_agent.errors import LocalStorageBusy
    f = ranked
    for indicator in 'ABC':
        api.save_indicator_outcome(f.cs, f.actor, 'gap-' + indicator, indicator,
                                   dict(kind='gap', missing='survey', question='Which survey?'))
    refusals = [dict(tool='save_gap', code='bad', tool_call_id=str(i)) for i in (1, 2)]
    from report_agent import risk_scoring
    original = risk_scoring.record_assessment_projection
    with monkeypatch.context() as patch:
        def fail_after_native(*args, **kwargs):
            original(*args, **kwargs)
            raise ActionRejected('simulated projection loss')
        patch.setattr(risk_scoring, 'record_assessment_projection', fail_after_native)
        with pytest.raises(LocalStorageBusy):
            api.interrupt_indicator_step(f.cs, f.actor, 'D', refusals)
    status = api.read_indicator_step(f.cs, f.actor)
    assert status['complete'] and status['interrupted_indicators']['D']['refusals'] == refusals
    assert f.cs.read(status['assessment_ref'])['payload']['result']['status'] == 'unscored'
    assert api.interrupt_indicator_step(f.cs, f.actor, 'D', refusals)['result']['assessment_ref'] == status['assessment_ref']
    archive = f.cs.store.root / 'terminal-archive.jsonl'
    AssertionHost(f.cs.store.root).commission.export(archive)
    import json
    derived = [r for line in archive.read_text().splitlines() if (r := json.loads(line).get('assertion'))
               and r['claim']['kind'] == 'derived']
    assert len(derived) == len(f.cs.list_objects('Assessment')) == 1

@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_archived_native_judgment_prevents_raw_replacement_after_lost_runtime_binding(ranked):
    from report_agent.assessment_producers import bind_producer
    f = ranked
    first = api.read_indicator_step(f.cs, f.actor)
    api.save_indicator_outcome(f.cs, f.actor, 'native-a', 'A', evidence(f, first))
    with f.ws.store.connect() as db:
        db.execute('DROP TABLE assessment_producers')
    with f.ws.store.connect() as db, pytest.raises(ActionRejected, match='ASSESSMENT_NATIVE_INPUTS_REQUIRED'):
        bind_producer(f.cs, db, f.plan_ref, 'S1', f.actor, bulk=True)
