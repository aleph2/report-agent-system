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
@pytest.mark.parametrize('transport_failure',[False,True])
async def test_real_evidence_and_gap_steps_close_without_score(ranked,monkeypatch,transport_failure):
    from report_agent import writer_assessment as wa
    f=ranked
    inner_turn=0
    disconnected=[]
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
        assert step['progress']['recorded']==inner_turn-1-int(bool(disconnected))
        assert not any(m['role'] in {'tool','assistant'} for m in body['messages'])
        assert 'assess_assigned_object' not in {t['function']['name'] for t in body.get('tools',[])}
        if transport_failure and inner_turn==3 and not disconnected:
            import httpx
            disconnected.append(True)
            raise httpx.RemoteProtocolError('Synthetic disconnect after request dispatch')
        outcome=evidence(f,step) if step['indicator_id']=='A' else {
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
        from contextlib import nullcontext,closing
        from report_agent.token_budget import TokenBudget,CampaignRunBudget,token_budget
        from hashlib import sha256
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        if transport_failure:
            campaign=TokenBudget(f.ws.store.root/'transport-ledger.db',10000,{'glm-5.3':1000})
            for _ in range(2):campaign.settle(campaign.reserve('glm-5.3'),None)
            with campaign.connect() as db:old_holds=[list(r) for r in db.execute("SELECT * FROM attempts ORDER BY id")]
            options=dict(maximum_tokens=8000,aggregate_tokens=10000,model_bounds={'glm-5.3':1000},
                authority_sha256='a'*64,preserved_holds=old_holds,guard_sha256=sha256(b'').hexdigest())
            budget=CampaignRunBudget(campaign.path,'transport-child',**options)
        with token_budget(budget) if transport_failure else nullcontext():
            first=await run_report(f.ws,lambda role:model if role=='writer' else driver(role))
        if transport_failure:
            assert first.get('last_error') is not None,first
            with campaign.connect() as db:
                held=[list(r) for r in db.execute("SELECT * FROM attempts WHERE state IN ('reserved','unknown') ORDER BY id")]
                rows={r[0]:list(r) for r in db.execute('SELECT * FROM attempts')}
            assert len(held)==3 and all(rows[r[0]]==r for r in old_holds)
            with f.ws.store.connect() as db:
                receipts=db.execute('SELECT assignment,indicator,operation,assertion_id,interruption FROM writer_step_receipts ORDER BY indicator').fetchall()
            assert len(receipts)==2
            tasks=f.cs.list_objects('DelegatedTask')
            checkpoint=f.ws.store.root/'checkpoints.db'
            with closing(sqlite3.connect(checkpoint.as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('PRAGMA query_only=ON');saver=SqliteSaver(db);saver.is_setup=True
                head=saver.get_tuple({'configurable':{'thread_id':'report','checkpoint_ns':''}})
                namespaces=[r[0] for r in db.execute("SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE checkpoint_ns!=''")]
                assert any(row[1]=='__error__' for row in head.pending_writes)
                assert len(namespaces)==1
                child=saver.get_tuple({'configurable':{'thread_id':'report','checkpoint_ns':namespaces[0]}})
                assert any(row[1]=='__error__' for row in child.pending_writes)
                assert not any(isinstance(row[2],dict) and 'DELEGATED_EXECUTION_FAILED' in str(row[2]) for row in head.pending_writes)
            from report_agent.store import Store
            from report_agent.workspace import Workspace
            reopened=Workspace(Store(f.ws.store.root))
            resumed_model,resumed_wires=glm_model(f,monkeypatch,decide)
            resumed_driver=Driver(coordinator=[AIMessage(content='Unused pending task'),AIMessage(content='Assessment returned with its gaps.')])
            continued_budget=CampaignRunBudget(campaign.path,'transport-child',**{**options,'preserved_holds':held})
            try:
                with token_budget(continued_budget):
                    resumed=await run_report(reopened,lambda role:resumed_model if role=='writer' else resumed_driver(role),
                        continue_from_checkpoint=head.config['configurable']['checkpoint_id'])
                assert resumed.get('last_error') is None,resumed.get('last_error')
                step=json.loads(next(m['content'] for m in resumed_wires[0]['messages'] if m['role']=='user'))
                assert step['indicator_id']=='C' and step['progress']['recorded']==2
                assert not any(role=='text_tool' for role,_,_ in resumed_driver.calls)
                assert f.cs.list_objects('DelegatedTask')==tasks
                with f.ws.store.connect() as db:
                    assert db.execute('SELECT assignment,indicator,operation,assertion_id,interruption FROM writer_step_receipts WHERE indicator IN (?,?) ORDER BY indicator',
                        [r[1] for r in receipts]).fetchall()==receipts
                with campaign.connect() as db:
                    current={r[0]:list(r) for r in db.execute('SELECT * FROM attempts')}
                    assert all(current[r[0]]==r for r in held)
                with closing(sqlite3.connect(checkpoint.as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('PRAGMA query_only=ON')
                    assert [r[0] for r in db.execute("SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE checkpoint_ns!=''")]==namespaces
            finally:await close(resumed_model)
        saved,=f.cs.list_objects('Assessment')
        actor=Actor(saved['owner_id'],'writer',saved['task_id'])
        durable=wa.read_indicator_step(f.cs,actor)
        new_tasks={t['ref']['id'] for t in f.cs.list_objects('DelegatedTask')}-original_tasks
        assert new_tasks=={saved['task_id']}
        assert (transport_failure and disconnected==[True] or len(wires)==6 and inner_turn==4) and durable['complete']
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
@pytest.mark.parametrize('recorded',[None,'continuation','continuation-second','historical-e','small-limit'])
async def test_eleventh_save_auto_submits_selected_canonical_assessment(five,recorded,record_testsuite_property,monkeypatch):
    from pathlib import Path
    from hashlib import sha256
    if recorded=='historical-e':
        import shutil,sqlite3
        from contextlib import closing
        from report_agent.store import Store
        from report_agent.workspace import Workspace
        from report_agent.content_store import ContentStore
        from report_agent.deep_runtime import run_report
        from report_agent.tool_selection import tool_scope
        from langchain_core.messages import AIMessage
        root=Path(__file__).resolve().parents[1]
        source=root/'.private/e-failed-checkpoint'
        if not source.is_dir():pytest.skip('Private synthetic e checkpoint required in frozen full snapshot')
        manifest=json.loads((root/'tests/fixtures/e_failed_checkpoint.json').read_text())
        for name,expected in manifest['files'].items():assert sha256((source/name).read_bytes()).hexdigest()==expected
        evidence=json.loads((source/'provenance.json').read_text())
        target=five.ws.store.root/'retained-e-case'
        shutil.copytree(source/'case',target)
        reopened=Workspace(Store(target));cs=ContentStore(reopened.store)
        def resume(messages):
            step=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
            assert step['rank']==step['progress']['recorded']+1
            return action('save_evidence','save-'+str(step['rank']),grade=step['grades'][1]['choice'],value='40',
                basis_kind='direct_evidence',rationale='Confirmed synthetic design fact.',quotes=['Slope 1 has synthetic evidence.'])
        driver=Driver(coordinator=[AIMessage(content='Unused before retained child.'),AIMessage(content='Assessment delegation returned.')],
            writer=[resume,AIMessage(content='Unused'),AIMessage(content='Unused'),
                    action('assess_assigned_object','canonical-repeat'),AIMessage(content='Saved assessment.')])
        with tool_scope({'offline-runtime-test'},dict.fromkeys(['coordinator','writer','reviewer','layout','text_tool','vision'],'offline-runtime-test')):
            report=await run_report(reopened,driver,continue_from_checkpoint=evidence['root_head'])
        assert report.get('last_error') is None,report.get('last_error')
        assert driver.calls[0][0]=='writer'
        step=json.loads(next(m.content for m in driver.calls[0][2] if isinstance(m,HumanMessage)))
        assert step['rank']==3 and step['progress']['recorded']==2
        assert not any(role=='text_tool' for role,_,_ in driver.calls)
        assert cs.list_objects('DelegatedTask')==[evidence['task']]
        with reopened.store.connect() as db:
            rows=[list(r) for r in db.execute('SELECT assignment,indicator,operation,assertion_id,interruption FROM writer_step_receipts WHERE indicator IN (?,?) ORDER BY indicator',
                [r[1] for r in evidence['first_two_receipts']])]
        assert rows==evidence['first_two_receipts']
        with closing(sqlite3.connect((target/'checkpoints.db').as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            assert [r[0] for r in db.execute("SELECT DISTINCT checkpoint_ns FROM checkpoints WHERE checkpoint_ns!=''")]==evidence['namespaces']
        saved,=cs.list_objects('Assessment');assert len(saved['payload']['indicators'])==11
        assert cs.list_objects('ContentNode')
        record_testsuite_property('historical_e_child_resume',json.dumps({'head':evidence['root_head'],'same_child':True,'first_two_receipts_unchanged':True,'source_commit':manifest['source_commit']}))
        return
    specs=json.loads((Path(__file__).parent/'fixtures/text_work_refused_outputs.json').read_text())
    spec=specs.get(recorded)
    raw=None
    if spec:
        fixture=Path(__file__).resolve().parents[1]/'.private/text-work-refused'/spec['file']
        if not fixture.is_file():pytest.skip('Private exact response required in frozen full snapshot')
        data=fixture.read_bytes();assert sha256(data).hexdigest()==spec['sha256']
        raw=data.decode('utf-8')
    observed=[]
    small_limit=recorded=='small-limit'
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
                      input_refs=[five.sources['design']],source_selections=[{'source_id':five.cs.read(five.sources['design'])['payload']['source_id']}],
                      output_count=spec['count'] if spec else 1)
    def adopt_prose(messages):
        from test_deep_runtime import observation
        result=observation(messages,'process_report_content')
        if spec:
            assert result['code']=='TEXT_WORK_OUTPUT_CONTRACT_INVALID',result
            assert 'qualifiers' in result['message']
            if recorded=='continuation-second':assert 'kind' in result['message']
            observed.append(result)
            return AIMessage(content='Exact retained output is not eligible for section prose; no qualifiers were discarded.')
        receipt=result['text_work_id']
        return action('save_section_prose','object-prose',operation_id='save-object-prose',section_id='4',text_work_id=receipt)
    candidate={'kind':'block','body':{'text':'Slope 1 has synthetic evidence.'},
               'qualifiers':{},'claim_kind':'fact','citations':[five.cite('design')]}
    def prose_response(messages):
        if spec:return AIMessage(content=raw)
        import jsonschema
        packet=json.loads(next(m.content for m in reversed(messages) if isinstance(m,HumanMessage)))
        jsonschema.validate(candidate,packet['output_schema'])
        for bad in ({**candidate,'kind':'chapter'},{**candidate,'qualifiers':{'condition':'Must stay visible in prose.'}},
                    {**candidate,'body':{'other':'Wrong key'}},{**candidate,'body':{'text':''}},
                    {**candidate,'body':{'text':'   \n\t'}}):
            with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,packet['output_schema'])
        return AIMessage(content=json.dumps(candidate))
    driver=Driver(coordinator=[action('task','native-assessment',subagent_type='writer',
        description='Write Slope 1 context and assess it using its confirmed method and pages.',
        section_ids=['4'],assessment_object_id='S1'),AIMessage(content='Assessment delegation returned.')],
        writer=[choose_writer_action,adopt_prose,action('assess_assigned_object','canonical-first'),
                action('assess_assigned_object','canonical-repeat'),AIMessage(content='Saved prose and assessment.')],
        text_tool=[prose_response])
    if spec:driver.scripts['writer']=driver.scripts['writer'][:2]
    from report_agent.tool_selection import tool_scope
    from report_agent import run_authority
    if small_limit:driver.scripts['writer']=driver.scripts['writer'][:3]+[AIMessage(content='Recorded indicator refusal; parent continues.')]
    if small_limit:
        from report_agent.writer_indicator_steps import IndicatorRun
        original_run=IndicatorRun.run
        async def limited(run,**kwargs):
            # Fixture criteria are already granted; scope the authority to graph execution.
            token=run_authority._active.set({'graph_limits':{'root':10000,'assessment':2}})
            try:return await original_run(run,**kwargs)
            finally:run_authority._active.reset(token)
        monkeypatch.setattr(IndicatorRun,'run',limited)
    with tool_scope({'offline-runtime-test'},dict.fromkeys(['coordinator','writer','reviewer','layout','text_tool','vision'],'offline-runtime-test')):
        report=await run_report(five.ws,driver)
    assert report.get('last_error') is None,report.get('last_error')
    if small_limit:
        messages=[m for role,_,items in driver.calls if role=='writer' for m in items
                  if isinstance(m,ToolMessage) and m.name=='assess_assigned_object']
        result=json.loads(messages[-1].content)
        assert result['code']=='ASSESSMENT_GRAPH_STEP_LIMIT' and result['diagnostic']['supersteps']==2
        events=[e['data'] for e in five.ws.store.events() if e['kind']=='assessment_graph_step_limit']
        assert len(events)==1 and events[0]['indicator_id']=='I01' and events[0]['object_label']=='Slope 1'
        assert not five.cs.list_objects('Assessment') and five.cs.list_objects('ContentNode')
        assert driver.calls[-1][0]=='coordinator'
        return
    if spec:
        assert len(observed)==1 and not five.cs.list_objects('ContentNode')
        failures=[e['data'] for e in five.ws.store.events() if e['kind']=='text_work_output_rejected']
        assert len(failures)==1 and failures[0]['raw_response_received']
        assert five.ws.store.analysis(failures[0]['operation'])['analysis']==raw
        record_testsuite_property('section_prose_'+recorded,json.dumps({'fixture_sha256':spec['sha256'],
            'result':'not_adoptable','code':observed[0]['code'],'reason':observed[0]['message'],
            'contract_basis':'section_writing.validate_prose: block/text-only/empty-qualifiers'}))
        return
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
    record_testsuite_property('section_prose_conforming_example',json.dumps(five.cs.read(prose)['payload']))
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
