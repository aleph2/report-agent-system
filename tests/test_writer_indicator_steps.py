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
    step_prefix=[]
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
            system = next(m for m in body['messages'] if m['role']=='system')
            assert 'Page read attempts left' not in str(system)
            if turn==1:
                step_prefix.append(system)
            else:
                assert system == step_prefix[0]
            tails = [m for m in body['messages'] if m['role']=='user' and
                     str(m.get('content','')).startswith('[host-observations]')]
            assert len(tails)==1
            packet = json.loads(tails[0]['content'].split('\n',1)[1])
            allowances = [p for p in packet['moved_blocks'] if p['source']=='indicator_step/reading_allowance']
            assert len(allowances)==1
            assert allowances[0]['text'] == f"Page read attempts left for this indicator: {4-turn}."
            assert '"current_state"' not in str(tails[0])
            return reply([(f'page-{turn}','read_assigned_page',{'source_handle':'source-1','page':turn+1})])
        if turn==4:
            assert {t['function']['name'] for t in body['tools']}=={'save_evidence','save_assumption','save_gap','propose_material_issue','assert_source','record_conflict'}
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
        assert [{k:r[k] for k in ('source_handle','page')} for r in steps[0][2]] == [
            {'source_handle':'source-1','page':p} for p in (2,3,4)]
        assert len({r['delivery'] for r in steps[0][2]}) == 3
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
    inner_turn=0
    def decide(turn,body):
        nonlocal inner_turn
        first=next(m['content'] for m in body['messages'] if m['role']=='user')
        try:
            step=json.loads(first)
        except (TypeError,ValueError):
            step={}
        if not isinstance(step,dict) or 'indicator_id' not in step:
            names={t['function']['name'] for t in body.get('tools',[])}
            assert 'assess_assigned_object' in names and 'calculate_assessment' not in names
            return reply() if any(m['role']=='tool' for m in body['messages']) else reply([('assess','assess_assigned_object',{})])
        inner_turn+=1
        assert step['progress']['recorded']==inner_turn-1
        assert not any(m['role'] in {'tool','assistant'} for m in body['messages'])
        assert 'assess_assigned_object' not in {t['function']['name'] for t in body.get('tools',[])}
        outcome=evidence(f,step) if inner_turn==1 else {
            'kind':'gap','missing':'Site data absent from supplied materials','question':'Can the survey be supplied?'}
        return reply([('save-'+str(inner_turn),'save_'+outcome.pop('kind'),outcome)])
    model,wires=glm_model(f,monkeypatch,decide)
    try:
        from report_agent.deep_runtime import run_report
        from report_agent.content_store import Actor
        from langchain_core.messages import AIMessage
        driver=Driver(coordinator=[action('task','sdk-assessment',subagent_type='writer',
            description='Assess Slope 1 and keep missing data explicit.',section_ids=['4'],assessment_object_id='S1'),
            AIMessage(content='Assessment returned with its gaps.')])
        original_tasks={t['ref']['id'] for t in f.cs.list_objects('DelegatedTask')}
        await run_report(f.ws,lambda role:model if role=='writer' else driver(role))
        saved,=f.cs.list_objects('Assessment')
        actor=Actor(saved['owner_id'],'writer',saved['task_id'])
        durable=wa.read_indicator_step(f.cs,actor)
        new_tasks={t['ref']['id'] for t in f.cs.list_objects('DelegatedTask')}-original_tasks
        assert new_tasks=={saved['task_id']}
        assert len(wires)==6 and inner_turn==4 and durable['complete']
        assert durable['gap_indicators']==['B','C','D'] and saved['payload']['result']['status']=='unscored'
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
from langchain_core.messages import HumanMessage, ToolMessage


@pytest.mark.asyncio
@pytest.mark.parametrize('five',['with-owner-ranks'],indirect=True)
async def test_eleventh_save_auto_submits_selected_canonical_assessment(five):
    def judge(messages):
        errors=[m.content for m in messages if isinstance(m,ToolMessage) and m.status=='error']
        assert not errors, errors
        step=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
        rank=step['rank']
        assert rank==step['progress']['recorded']+1
        return action('save_evidence',f'save-{rank}',
                      grade=step['grades'][1]['choice'],value='40',
                      basis_kind='direct_evidence',rationale='Confirmed synthetic design fact.',
                      quotes=['Slope 1 has synthetic evidence.'])
    from report_agent.deep_runtime import run_report
    from langchain_core.messages import AIMessage
    def choose_writer_action(messages):
        first=next(m.content for m in messages if isinstance(m,HumanMessage))
        try:
            step=json.loads(first)
        except (TypeError,ValueError):
            step={}
        if isinstance(step,dict) and 'indicator_id' in step:
            return judge(messages)
        return action('process_report_content','produce-prose',operation_id='produce-prose',
                      objective='Write the assigned object context from the supplied design.',object_type='ContentNode',
                      input_refs=[five.sources['design']],source_selections=[{'source_id':five.cs.read(five.sources['design'])['payload']['source_id']}])
    def adopt_prose(messages):
        from test_deep_runtime import observation
        receipt=observation(messages,'process_report_content')['text_work_id']
        return action('save_section_prose','object-prose',operation_id='save-object-prose',section_id='4',text_work_id=receipt)
    driver=Driver(coordinator=[action('task','native-assessment',subagent_type='writer',
        description='Write Slope 1 context and assess it using its confirmed method and pages.',
        section_ids=['4'],assessment_object_id='S1'),AIMessage(content='Assessment delegation returned.')],
        writer=[choose_writer_action,adopt_prose,action('assess_assigned_object','canonical-first'),
                action('assess_assigned_object','canonical-repeat'),AIMessage(content='Saved prose and assessment.')],
        text_tool=[AIMessage(content=json.dumps({'kind':'block','body':{'text':'Slope 1 has synthetic evidence.'},
                   'qualifiers':{},'claim_kind':'fact','citations':[five.cite('design')]}))])
    from report_agent.tool_selection import tool_scope
    with tool_scope({'offline-runtime-test'},dict.fromkeys(['coordinator','writer','reviewer','layout','text_tool','vision'],'offline-runtime-test')):
        report=await run_report(five.ws,driver)
    assert report.get('last_error') is None,report.get('last_error')
    tasks=five.cs.list_objects('DelegatedTask')
    assert len(tasks)==1 and tasks[0]['payload']['assessment_object_id']=='S1'
    writer_calls=[messages for role,_,messages in driver.calls if role=='writer']
    errors=[m.content for messages in writer_calls for m in messages if isinstance(m,ToolMessage) and m.status=='error']
    assert not errors,errors
    inner=[messages for messages in writer_calls if any(isinstance(m,HumanMessage) and isinstance(m.content,str) and m.content.startswith('{') and '"indicator_id"' in m.content for m in messages)]
    assert len(inner)==11
    assert all(not any(isinstance(m,(AIMessage,ToolMessage)) for m in messages) for messages in inner)
    assert all('calculate_assessment' not in {t['name'] for t in tools} for tools in driver.bindings['writer'] if any(t['name']=='save_evidence' for t in tools))
    saved,=five.cs.list_objects('Assessment')
    assert saved['task_id']==tasks[0]['ref']['id'] and len(saved['payload']['indicators'])==11
    from report_agent import report_state
    from report_agent.store import encode
    prose=report_state.prose_ref(five.ws.store,'prose:'+encode([five.plan_ref,'4','S1']))
    assert prose is not None and five.cs.read(prose)['task_id']==tasks[0]['ref']['id']
    returns=[m for role,_,messages in driver.calls if role=='coordinator' for m in messages
             if isinstance(m,ToolMessage) and m.name=='task']
    assert returns and returns[-1].tool_call_id=='native-assessment'
    from test_deep_runtime import observation
    progress=observation(writer_calls[-1],'assess_assigned_object')
    assert progress['assessment_ref']==saved['ref'] and progress['progress']=={'recorded':11,'total':11}

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
        assert final['gap_indicators']==['B','C','D'] and f.cs.read(final['assessment_ref'])['payload']['result']['status'] == 'unscored'
        assert list(final['interrupted_indicators'])==['A']
        stop=final['interrupted_indicators']['A']
        assert stop['status']=='interrupted: save rejected'
        assert [row['tool_call_id'] for row in stop['refusals']]==['native-1','native-2']
        assert all(row.get('diagnostic') for row in stop['refusals'])
        assert durable['interrupted_indicators']==final['interrupted_indicators']
        assert len(f.cs.list_objects('Assessment')) == 1
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
