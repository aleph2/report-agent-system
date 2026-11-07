"""Actual synthetic Run 02 rejected public calls, replayed through GLM mock transport."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from report_agent.mini_commission import prepare_mini_commission
from report_agent.writer_runtime import writer_session
from report_agent.writer_assessment import read_indicator_step
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.content_store import ContentStore
from report_agent.deep_models import RequestBudgetExceeded
from test_transport_observation import close
from test_writer_context_replay import glm_model, reply, tool_content

FIXTURES = Path(__file__).parent
CALLS = json.loads((FIXTURES/'fixtures/mini_writer_rejected_saves.json').read_text())['calls']


@pytest.mark.asyncio
@pytest.mark.parametrize('seq,fields',[
    ('36', {'plausible_grades','value'}), ('48', {'plausible_grades'}),
    ('105', {'basis_kind','plausible_grades','value'}), ('117', {'contrary_evidence'}),
    ('129', {'question'}), ('141', {'question','value'}),
    ('extra', {'typo'}), ('wrong_kind',{'kind'}), ('assumption', {'quotes'})
])
async def test_next_request_names_incorrect_fields_and_corrected_save_advances(seq, fields, tmp_path, monkeypatch):
    case = tmp_path/'case'
    prepare_mini_commission(FIXTURES/'fake_data/mini_commission/inputs',case)
    ws = Workspace(Store(case))
    basic = dict(CALLS['48'])
    basic = {k:basic[k] for k in ('grade','value','basis_kind','quotes','rationale')}
    clean_gap = {k:CALLS['117'][k] for k in ('missing','question','rationale','quotes')}
    if seq in CALLS:
        args = dict(CALLS[seq]); kind = args.pop('kind')
    elif seq=='assumption':
        kind='assumption'
        args={'grade':basic['grade'],'value':'22.5','plausible_grades':[basic['grade']],
              'rationale':'Consider an engineering assumption.','question':'Confirm?','quotes':[]}
    else:
        kind='gap'
        args={**clean_gap,**({'typo':'unexpected'} if seq=='extra' else {'kind':'evidence'})}
    start=1 if kind!='gap' else 2
    def decide(turn,body):
        if turn<start:
            return reply([('first','save_evidence',basic)])
        if turn==start:
            names={t['function']['name'] for t in body['tools']}
            assert {'save_gap','save_assumption','save_evidence'}<=names
            for tool in body['tools']:
                if tool['function']['name'] not in {'save_gap','save_assumption','save_evidence'}:
                    continue
                def inspect(schema):
                    if isinstance(schema,dict):
                        assert not {'$ref','$defs','root_refs'} & schema.keys()
                        for field,prop in schema.get('properties',{}).items():
                            assert prop.get('description'), field
                        for value in schema.values():inspect(value)
                    elif isinstance(schema,list):
                        for value in schema:inspect(value)
                inspect(tool['function']['parameters'])
            return reply([('replay','save_'+kind,args)])
        feedback=json.loads(tool_content(body,'replay'))
        assert feedback['code']=='NATIVE_TOOL_VALIDATION_ERROR'
        errors={item['field'][0]:item for item in feedback['diagnostic']['fields']}
        assert fields<=errors.keys()
        for field in fields:
            assert errors[field]['reason'] and errors[field]['correction']
        return reply([('correct','save_gap' if kind=='gap' else 'save_evidence',clean_gap if kind=='gap' else basic)])
    model,wires=glm_model(SimpleNamespace(ws=ws),monkeypatch,decide,stop_at=start+2)
    try:
        with writer_session(ws,'坡段 A',model,section_id='3',assessment_only=True,indicator_steps=True) as session:
            with pytest.raises(RequestBudgetExceeded):await session.run()
            step=read_indicator_step(ContentStore(ws.store),session.actor)
            assert step['indicator_id']==('X21' if kind=='gap' else 'X12')
            assert step['progress']['recorded']==start
    finally:await close(model)


def test_applied_guideline_uses_visible_approved_rule_and_requires_both_source_kinds(tmp_path):
    from report_agent.writer_assessment import save_indicator_outcome
    from report_agent.errors import ActionRejected
    case=tmp_path/'case'
    prepare_mini_commission(FIXTURES/'fake_data/mini_commission/inputs',case)
    ws=Workspace(Store(case)); cs=ContentStore(ws.store)
    basic={k:CALLS['48'][k] for k in ('grade','value','quotes','rationale')}
    with writer_session(ws,'坡段 A',SimpleNamespace(profile={'image_inputs':False}),
                        section_id='3',assessment_only=True,indicator_steps=True) as session:
        step=read_indicator_step(cs,session.actor)
        # The approved rule is supplied in the step packet even though it is not a project page.
        rule_quote=step['grades'][0]['description']
        value={'kind':'evidence','basis_kind':'applied_guideline',**basic}
        with pytest.raises(ActionRejected,match='GUIDELINE_RULE_SOURCE_REQUIRED'):
            save_indicator_outcome(cs,session.actor,'missing-method','X11',value)
        with pytest.raises(ActionRejected,match='FACTUAL_SOURCE_REQUIRED'):
            save_indicator_outcome(cs,session.actor,'missing-fact','X11',{**value,'quotes':[rule_quote]})
        assert read_indicator_step(cs,session.actor)['progress']['recorded']==0
        result=save_indicator_outcome(cs,session.actor,'method-and-fact','X11',
                                     {**value,'quotes':basic['quotes']+[rule_quote]})
        assert result['result']['saved_indicator']=='X11'
        assert read_indicator_step(cs,session.actor)['progress']['recorded']==1


@pytest.mark.asyncio
async def test_native_save_gap_with_structured_conflict_commits_issue(tmp_path, monkeypatch):
    case=tmp_path/'case'
    prepare_mini_commission(FIXTURES/'fake_data/mini_commission/inputs',case)
    ws=Workspace(Store(case))
    height={k:CALLS['48'][k] for k in ('grade','value','basis_kind','quotes','rationale')}
    conflict=dict(basis='设计坡率 1:0.75，地勘实测坡率 1:1.0。',
        adopted_value='采用设计坡率 1:0.75，设计优先。',
        quotes=['设计坡率为 1:0.75，分三级开挖。','坡段 A：实测坡率为 1:1.0。'],
        question='请核对设计与调查坡率差异。',affects_level=True)
    def decide(turn,body):
        if turn==1:return reply([('height','save_evidence',height)])
        assert turn==2
        return reply([('angles','save_gap',dict(missing='自然坡角',question='自然坡角是多少？',
                                                contrary_evidence=conflict))])
    model,_=glm_model(SimpleNamespace(ws=ws),monkeypatch,decide,stop_at=3)
    try:
        with writer_session(ws,'坡段 A',model,section_id='3',assessment_only=True,indicator_steps=True) as session:
            with pytest.raises(RequestBudgetExceeded):await session.run()
            cs=ContentStore(ws.store)
            step=read_indicator_step(cs,session.actor)
            assert step['indicator_id']=='X21' and step['gap_indicators']==['X12']
            with cs.store.connect() as db:
                issues=[json.loads(raw) for raw, in db.execute(
                    "SELECT value FROM state WHERE key LIKE 'g6_issue_record:%'")]
            assert len(issues)==1
            assert issues[0]['issue']['adopted_value']==conflict['adopted_value']
            assert {s['quote'] for s in issues[0]['source_citations']}==set(conflict['quotes'])
    finally:await close(model)
