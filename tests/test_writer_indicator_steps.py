"""Offline final-wire regressions for a bounded assessment step."""
import json
import pytest
from report_agent.errors import ActionRejected
from report_agent.writer_runtime import writer_session
from test_writer_context_replay import assigned, method_commission, reply, glm_model
from test_transport_observation import close


@pytest.mark.asyncio
async def test_third_read_retains_all_pages_and_still_offers_one_issue(assigned, monkeypatch):
    from report_agent import writer_assessment as wa
    from report_agent.content_models import Contract
    from pydantic import create_model
    # Isolate actual model and tool-routing behavior from the plan-rank parsing test.
    f=assigned
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    steps=[]
    issues=[]
    from report_agent import writer_issues
    def record_issue(*args):
        issues.append(args[-1])
        return {'result':{'issue_id':'synthetic-issue'}}
    monkeypatch.setattr(writer_issues,'propose_material_issue',record_issue)
    def packet(cs,actor):
        i=len(steps)
        return {'complete':i==2, 'indicator_id':f'X{i}', 'rank':i+1,
                'progress':{'recorded':i,'total':2}, 'assessment_ref':None,
                'gap_indicators':[x[0] for x in steps],'interrupted_indicators':{}}
    def persist(cs,actor,op,indicator,outcome,*,read_locations):
        steps.append((indicator,dict(outcome),list(read_locations)))
        return {'result':packet(cs,actor)}
    monkeypatch.setattr(wa,'read_indicator_step',packet,raising=False)
    monkeypatch.setattr(wa,'save_indicator_outcome',persist,raising=False)
    schema=create_model('WireGap',__base__=Contract,missing=(str,...))
    monkeypatch.setattr(wa,'step_outcome_schema',lambda *args:schema,raising=False)
    def decide(turn,body):
        if turn<=3:
            return reply([(f'page-{turn}','read_assigned_page',{'source_handle':'source-1','page':turn+1})])
        if turn==4:
            assert {t['function']['name'] for t in body['tools']}=={'save_evidence','save_assumption','save_gap','propose_material_issue'}
            assert len([m for m in body['messages'] if m['role']=='tool'])==3
            assert 'Earlier page/window text cleared' not in str(body['messages'])
            issue={'kind':'missing','basis':'Geology not supplied','adopted_value':'Pending survey',
                   'question':'Supply geology?','affects_level':False}
            # Issue recording remains usable once; neither another read nor a second issue bypasses the limit.
            return reply([('issue-after-third','propose_material_issue',issue),
                          ('extra-issue','propose_material_issue',issue),
                          ('extra-read','read_assigned_page',{'source_handle':'source-1','page':5}),
                          ('save-first','save_gap',{'missing':'missing geology'})])
        assert turn==5
        assert not any(m['role'] in {'tool','assistant'} for m in body['messages'])
        assert 'missing geology' not in str(body['messages'])
        assert 'section prose' not in str(body['messages'])
        return reply([('save-second','save_gap',{'missing':'missing survey'})])
    model,wires=glm_model(f,monkeypatch,decide)
    try:
        with writer_session(f.ws,f.plan['objects'][0]['label'],model,assessment_only=True,indicator_steps=True) as run:
            result=await run.run()
        assert len(wires)==5 and result['progress']['recorded']==2
        assert [s[0] for s in steps]==['X0','X1']
        assert steps[0][2]==[{'source_handle':'source-1','page':p} for p in (2,3,4)]
        assert len(issues)==1 and not steps[1][2]
        assert [row['tool_call_id'] for row in run.refusals]==['extra-issue','extra-read']
    finally:
        await close(model)

from test_writer_probe import prepared_probe, sha, install_probe_transport, sdk_reply
from test_writer_indicator_outcomes import ranked, evidence


def authorize_steps(p):
    evidence_dir=p['evidence']
    authority_path=evidence_dir/'owner-authority.json'
    updated={**json.loads(authority_path.read_bytes()),'writer_workflow':'indicator-steps-v1'}
    authority_path.write_text(json.dumps(updated))
    inputs={**p['inputs'],'writer_workflow':'indicator-steps-v1',
            'authority_sha256':sha(authority_path.read_bytes())}
    (evidence_dir/'probe-inputs.json').write_text(json.dumps(inputs))


@pytest.mark.asyncio
async def test_rankless_indicator_probe_interrupts_before_first_request(prepared_probe,monkeypatch):
    from report_agent.writer_probe import run_probe
    p=prepared_probe
    authorize_steps(p)
    install_probe_transport(monkeypatch,p,[])
    result=await run_probe(p['case'],p['evidence'],p['env'])
    assert not p['wires'] and result['budget']['recorded_tokens']==0
    assert result['status']=='stopped' and result['step_status']=='interrupted'
    assert result['stop_code']=='WRITER_CONFIRMED_RANK_ORDER_REQUIRED'
    assert result['indicator_steps'] is None and result['refusal_count']==0
    assert 'receipt_error_type' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_real_evidence_and_gap_steps_close_without_score(ranked,monkeypatch):
    from report_agent import writer_assessment as wa
    f=ranked
    def decide(turn,body):
        step=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
        assert step['progress']['recorded']==turn-1
        assert not any(m['role'] in {'tool','assistant'} for m in body['messages'])
        outcome=evidence(f,step) if turn==1 else {
            'kind':'gap','missing':'Site data absent from supplied materials','question':'Can the survey be supplied?'}
        return reply([('save-'+str(turn),'save_'+outcome.pop('kind'),outcome)])
    model,wires=glm_model(f,monkeypatch,decide)
    try:
        with writer_session(f.ws,'Slope 1',model,assessment_only=True,indicator_steps=True) as run:
            result=await run.run()
            durable=wa.read_indicator_step(f.cs,run.actor)
        assert len(wires)==4 and not run.refusals and durable['complete']
        assert result['gap_indicators']==['B','C','D'] and result['assessment_ref'] is None
        assert not f.cs.list_objects('Assessment')
    finally:
        await close(model)


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_plain_answer_interrupts_without_fabricating_gap(ranked,monkeypatch):
    from report_agent import writer_assessment as wa
    f=ranked
    model,wires=glm_model(f,monkeypatch,lambda turn,body: reply())
    try:
        with writer_session(f.ws,'Slope 1',model,assessment_only=True,indicator_steps=True) as run:
            with pytest.raises(ActionRejected,match='PROBE_INDICATOR_STEP_INTERRUPTED'):
                await run.run()
            saved=wa.read_indicator_step(f.cs,run.actor)
        assert len(wires)==1 and not saved['gap_indicators'] and saved['progress']['recorded']==0
    finally:
        await close(model)

from test_writer_five_slopes import five, action
from test_deep_runtime import Driver
from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
@pytest.mark.parametrize('five',['with-owner-ranks'],indirect=True)
async def test_eleventh_save_auto_submits_selected_canonical_assessment(five):
    def judge(messages):
        step=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
        rank=step['rank']
        assert rank==step['progress']['recorded']+1
        return action('save_evidence',f'save-{rank}',
                      grade=step['grades'][1]['choice'],value='40',
                      basis_kind='direct_evidence',rationale='Confirmed synthetic design fact.',
                      quotes=['Slope 1 has synthetic evidence.'])
    driver=Driver(writer=[judge]*11)
    with writer_session(five.ws,'Slope 1',driver('writer'),assessment_only=True,indicator_steps=True) as run:
        result=await run.run()
    assert len(driver.calls)==11 and not run.refusals
    assert result['progress']=={'recorded':11,'total':11}
    assert not result['gap_indicators']
    saved=five.cs.read(result['assessment_ref'])
    assert len(saved['payload']['indicators'])==11
    assert len(five.cs.list_objects('Assessment'))==1

@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_probe_keeps_committed_gap_and_latest_refusal_when_next_request_is_blocked(prepared_probe,monkeypatch):
    from report_agent.writer_probe import run_probe
    p=prepared_probe
    authorize_steps(p)
    rejected=sdk_reply(tool='read_assigned_page',arguments={'source_handle':'foreign','page':1},usage=1_020_343)
    rejected['choices'][0]['message']['tool_calls'][0]['id']='rejected-page'
    install_probe_transport(monkeypatch,p,[
        sdk_reply(tool='save_gap',arguments={
            'missing':'Available input lacks rainfall','question':'Supply rainfall?'},usage=10),
        rejected])
    result=await run_probe(p['case'],p['evidence'],p['env'])
    assert result==json.loads((p['evidence']/'probe-launch.json').read_text())
    assert len(p['wires'])==2 and result['stop_code']=='PROBE_TOKEN_LIMIT'
    assert result['step_status']=='interrupted' and result['assessment_refs']=={}
    assert result['refusals']==[{'tool':'read_assigned_page','tool_call_id':'rejected-page',
                                'code':'WRITER_SOURCE_HANDLE_UNKNOWN'}]
    assert result['refusal_count']==1 and result['metrics']['roles']['writer']['rejections']==1
    assert result['indicator_steps']=={'interrupted_indicators':{},'progress':{'recorded':1,'total':4},
                                      'gap_indicators':['A'],'assessment_ref':None}

@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_two_save_refusals_advance_but_failed_read_and_corrected_save_do_not_interrupt(ranked,monkeypatch):
    from report_agent import writer_assessment as wa
    f=ranked
    def decide(turn,body):
        step=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
        scope=step['indicator_id']
        actions={
            1:('A','save_gap',{'missing':'No field evidence'}),
            2:('A','save_evidence',{'plausible_grades':['invented']}),
            3:('B','read_assigned_page',{'source_handle':'foreign','page':1}),
            4:('B','save_gap',{'missing':'Missing survey'}),
            5:('B','save_gap',{'missing':'Missing survey','question':'Supply it?'}),
            6:('C','save_gap',{'missing':'Missing geology','question':'Supply it?'}),
            7:('D','save_gap',{'missing':'Missing drainage','question':'Supply it?'})}
        expected,tool,args=actions[turn]
        assert scope==expected
        return reply([(f'native-{turn}',tool,args)])
    model,wires=glm_model(f,monkeypatch,decide)
    try:
        with writer_session(f.ws,'Slope 1',model,assessment_only=True,indicator_steps=True) as run:
            final=await run.run()
            durable=wa.read_indicator_step(f.cs,run.actor)
        assert len(wires)==7 and durable['complete']
        assert final['progress']=={'recorded':3,'total':4}
        assert final['gap_indicators']==['B','C','D'] and final['assessment_ref'] is None
        assert list(final['interrupted_indicators'])==['A']
        stop=final['interrupted_indicators']['A']
        assert stop['status']=='interrupted: save rejected'
        assert [row['tool_call_id'] for row in stop['refusals']]==['native-1','native-2']
        assert all(row.get('diagnostic') for row in stop['refusals'])
        assert durable['interrupted_indicators']==final['interrupted_indicators']
        assert not f.cs.list_objects('Assessment')
    finally:
        await close(model)

@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
def test_refused_save_counter_deduplicates_native_ids_and_ignores_reads(ranked):
    from langchain_core.messages import ToolMessage
    from types import SimpleNamespace
    from report_agent.writer_indicator_steps import IndicatorBoundary,IndicatorToolReceipts
    f=ranked
    boundary=IndicatorBoundary()
    receipts=IndicatorToolReceipts(f.ws)
    receipts.boundary=boundary
    for name,identity in [('read_assigned_page','read'),('save_gap','once'),
                          ('save_gap','once'),('save_assumption','twice')]:
        result=ToolMessage(json.dumps({'code':'NATIVE_TOOL_VALIDATION_ERROR',
            'diagnostic':{'fields':[{'field':['question'],'reason':'missing','correction':'Supply a review question'}]}}),
            name=name,tool_call_id=identity,status='error')
        request=SimpleNamespace(tool_call={'id':identity,'name':name,'args':{}})
        receipts._record_tool_result(request,result)
    assert list(boundary.save_refusals)==['once','twice']
    assert not boundary.offered('save_evidence') and not boundary.saved
