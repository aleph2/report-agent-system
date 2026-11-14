"""Offline two-slope routing; the trusted launch admission has separate tests."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from report_agent.content_store import ContentStore
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.fake_verification import run_mini_assessment
from test_deep_runtime import Driver
from test_writer_five_slopes import action


@pytest.mark.asyncio
async def test_unbound_or_forged_fake_profile_cannot_enter_writer():
    with pytest.raises(ValueError,match='VERIFIED_FAKE_RUN_REQUIRED'):
        await run_mini_assessment(None,None,verified_run=SimpleNamespace(run_id='invented'))


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupt_first',[False,True])
async def test_two_mini_slopes_run_twenty_two_independent_assessment_steps(tmp_path,monkeypatch,interrupt_first):
    from report_agent import fake_verification
    from report_agent.mini_commission import prepare_mini_commission
    inputs=Path(__file__).parent/'fake_data'/'mini_commission'/'inputs'
    case=tmp_path/'case'
    prepared=prepare_mini_commission(inputs,case)
    workspace=Workspace(Store(case))
    binding=SimpleNamespace(plan_ref=prepared['plan_ref'],assessment_section_id=prepared['assessment_section_id'])
    # This exercises runner routing. Launch tests exercise the verified budget and claim.
    def verify(run,ws):
        assert run is binding and ws is workspace
    monkeypatch.setattr(fake_verification,'assert_active_fake_run',verify)
    seen=[]
    def record(messages):
        packet=json.loads(next(m.content for m in messages if isinstance(m,HumanMessage)))
        seen.append((packet['object_label'],packet['indicator_id'],packet['rank'],packet['progress']['recorded']))
        if interrupt_first and len(seen)<=2:
            return action('save_gap',f'route-{len(seen)}',missing='Question deliberately missing.')
        return action('save_gap',f'route-{len(seen)}',
                      missing='Scripted routing-only gap.',question='Review fixture evidence independently?')
    driver=Driver(writer=[record]*22)
    result=await run_mini_assessment(workspace,driver('writer'),verified_run=binding)
    assert result['status']==('incomplete' if interrupt_first else 'closed_with_gaps') and result['scope']=='assessment_writer_only'
    assert [s['object_id'] for s in result['slopes']]==['A','B']
    assert len({s['writer_actor'] for s in result['slopes']})==2
    assert len(seen)==22+int(interrupt_first) and len({(label,indicator) for label,indicator,_,_ in seen})==22
    if interrupt_first:
        interrupted=result['slopes'][0]['indicator_steps']['interrupted_indicators']
        assert list(interrupted)==['X11']
        assert len(interrupted['X11']['refusals'])==2
        assert 'X11' not in result['slopes'][0]['indicator_steps']['gap_indicators']
        assert result['slopes'][1]['status']=='closed_with_gaps'
    for ix,s in enumerate(result['slopes']):
        assert s['indicator_steps']['progress']=={'recorded':10 if interrupt_first and ix==0 else 11,'total':11}
        assert ContentStore(workspace.store).read(s['indicator_steps']['assessment_ref'])['payload']['result']['status'] == 'unscored'
        assert len(s['refusals'])==(2 if interrupt_first and ix==0 else 0)
        normalized=seen[1:] if interrupt_first else seen
        batch=normalized[11*ix:11*(ix+1)]
        assert len({row[0] for row in batch})==1 and sorted(row[2] for row in batch)==list(range(1,12))
        assert [row[3] for row in batch]==([0,*range(10)] if interrupt_first and ix==0 else list(range(11)))
    cs=ContentStore(workspace.store)
    for slope in result['slopes']:
        actor_id=slope['writer_actor'].split(':')[-1]
        task=cs.read({'type':'DelegatedTask','id':actor_id,'version':1})['payload']
        assert task['assessment_object_id']==slope['object_id'] and task['section_ids']==['3']
    assert len(cs.list_objects('Assessment')) == 2

@pytest.mark.asyncio
@pytest.mark.parametrize('pending_after_cutoff',[False,True])
async def test_sdk_malformed_save_refusals_preserve_committed_row_and_continue_both_slopes(
        tmp_path,monkeypatch,pending_after_cutoff):
    from report_agent import fake_verification
    from report_agent.mini_commission import prepare_mini_commission
    from test_writer_context_replay import glm_model,reply
    from test_transport_observation import close

    prepared=prepare_mini_commission(Path(__file__).parent/'fake_data'/'mini_commission'/'inputs',tmp_path/'case')
    workspace=Workspace(Store(tmp_path/'case'))
    binding=SimpleNamespace(plan_ref=prepared['plan_ref'],assessment_section_id=prepared['assessment_section_id'])
    def verify(run,ws):
        assert run is binding and ws is workspace
    monkeypatch.setattr(fake_verification,'assert_active_fake_run',verify)
    steps=[]
    gap={'missing':'Synthetic routing-only data gap.','question':'Provide the missing data?'}
    def decide(turn,body):
        packet=json.loads(next(m['content'] for m in body['messages'] if m['role']=='user'))
        steps.append((packet['object_label'],packet['indicator_id']))
        if turn<=3:
            actions=[(f'malformed-{turn}','save_gap',{})]
            if turn==1:
                # One malformed call still allows the valid sibling to commit.
                actions.append(('committed-sibling','save_gap',gap))
            if turn==3 and pending_after_cutoff:
                # Both pending saves remain unexecuted after the second refusal, including one
                # listed first on the wire. The parser observes both refusals before dispatch.
                actions.insert(0,('pending-valid','save_gap',gap))
                actions.append(('pending-invalid','save_assumption',{}))
            response=reply(actions)
            calls=response['choices'][0]['message']['tool_calls']
            malformed=next(c for c in calls if c['id'].startswith('malformed-'))
            malformed['function']['arguments']='{"private":"raw-test-data","field": !}'
            if turn==2:
                calls.append(malformed.copy())  # An echoed ID counts once.
            return response
        return reply([(f'save-{turn}','save_gap',gap)])
    model,wires=glm_model(SimpleNamespace(ws=workspace),monkeypatch,decide)
    try:
        result=await run_mini_assessment(workspace,model,verified_run=binding)
    finally:
        await close(model)

    assert result['status']=='incomplete'
    assert len(wires)==23 and len(set(steps))==22
    assert steps[0][1]=='X11' and steps[1]==steps[2] and steps[1][1]!='X11'
    slope_a,slope_b=result['slopes']
    refused=slope_a['refusals']
    rows=[r for r in refused if r['tool_call_id'].startswith('malformed-')]
    pending=[r for r in refused if r['tool_call_id'].startswith('pending-')]
    expected_pending=['WRITER_STEP_TOOL_UNAVAILABLE']*2 if pending_after_cutoff else []
    assert [r['code'] for r in pending]==expected_pending
    assert [(r['tool_call_id'],r['tool'],r['code']) for r in rows]==[
        (f'malformed-{i}','save_gap','INVALID_TOOL_ARGUMENT_JSON') for i in (1,2,3)]
    assert all(r['parser_diagnostic']['column']>1 for r in rows)
    metrics=[json.loads(line) for line in (tmp_path/'case'/'runtime-metrics.jsonl').read_text().splitlines()]
    assert [e['tool_call_id'] for e in metrics if e['kind']=='tool_rejected' and
            e['tool_call_id'].startswith('malformed-')]==['malformed-1','malformed-2','malformed-3']
    assert slope_b['status']=='closed_with_gaps' and slope_b['indicator_steps']['progress']['recorded']==11
    final=slope_a['indicator_steps']
    interrupted_id=steps[1][1]
    assert list(final['interrupted_indicators'])==[interrupted_id] and interrupted_id not in final['gap_indicators']
    assert 'X11' in final['gap_indicators']
    interrupted=final['interrupted_indicators'][interrupted_id]
    assert interrupted['status']=='interrupted: save rejected'
    assert [r['tool_call_id'] for r in interrupted['refusals']]==['malformed-2','malformed-3']
    assert all(r['parser_diagnostic']['message'] for r in interrupted['refusals'])
    assert 'raw-test-data' not in json.dumps(refused) and 'raw-test-data' not in json.dumps(interrupted)
    assert final['progress']['recorded']==10 and ContentStore(workspace.store).read(final['assessment_ref'])['payload']['result']['status'] == 'unscored'


@pytest.mark.asyncio
@pytest.mark.parametrize('limit_before_save', [True, False])
async def test_graph_limit_advances_only_a_committed_indicator(tmp_path, monkeypatch, limit_before_save):
    from langgraph.errors import GraphRecursionError
    from report_agent import fake_verification, writer_indicator_steps
    from report_agent.mini_commission import prepare_mini_commission

    case = tmp_path / 'case'
    prepared = prepare_mini_commission(Path(__file__).parent / 'fake_data/mini_commission/inputs', case)
    workspace = Workspace(Store(case))
    binding = SimpleNamespace(plan_ref=prepared['plan_ref'], assessment_section_id=prepared['assessment_section_id'])
    monkeypatch.setattr(fake_verification, 'assert_active_fake_run', lambda run, ws: None)

    create = writer_indicator_steps.create_agent
    def limited_agent(*args, **kwargs):
        graph = create(*args, **kwargs)
        async def invoke(messages, config):
            if limit_before_save:
                raise GraphRecursionError('limit before the native tool')
            await graph.ainvoke(messages, config)
            raise GraphRecursionError('limit after the native tool')
        return SimpleNamespace(ainvoke=invoke)
    monkeypatch.setattr(writer_indicator_steps, 'create_agent', limited_agent)

    seen = []
    def decide(messages):
        packet = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))
        seen.append((packet['object_label'], packet['indicator_id']))
        return action('save_gap', f'bound-{len(seen)}', missing='Missing fixture value.', question='Supply the value?')

    result = await run_mini_assessment(workspace, Driver(writer=[decide] * 22)('writer'), verified_run=binding)
    if limit_before_save:
        assert result['status'] == 'interrupted'
        assert result['slopes'][0]['error_type'] == 'ActionRejected'
        limited=[e['data'] for e in workspace.store.events() if e['kind']=='assessment_graph_step_limit']
        assert len(limited)==1 and limited[0]['object_label'] and limited[0]['indicator_id']
        assert not seen
    else:
        assert result['status'] == 'closed_with_gaps'
        assert len(seen) == len(set(seen)) == 22
        assert [s['indicator_steps']['progress']['recorded'] for s in result['slopes']] == [11, 11]


@pytest.mark.asyncio
async def test_unexpected_writer_error_reports_only_deepest_project_location(tmp_path, monkeypatch):
    import inspect
    from report_agent import fake_verification, writer_assessment
    from report_agent.mini_commission import prepare_mini_commission

    prepared = prepare_mini_commission(Path(__file__).parent/'fake_data'/'mini_commission'/'inputs', tmp_path/'case')
    workspace = Workspace(Store(tmp_path/'case'))
    binding = SimpleNamespace(plan_ref=prepared['plan_ref'], assessment_section_id=prepared['assessment_section_id'])
    monkeypatch.setattr(fake_verification, 'assert_active_fake_run', lambda run, ws: None)
    secret = 'private-fixture-payload-MUST-NEVER-APPEAR'
    call_sites = []
    def fail(*args):
        call_sites.append(inspect.currentframe().f_back.f_lineno)
        raise TypeError(secret)
    monkeypatch.setattr(writer_assessment, '_step_state', fail)

    result = await run_mini_assessment(workspace, Driver(writer=[])('writer'), verified_run=binding)
    slope, = result['slopes']
    assert result['status'] == slope['status'] == 'interrupted' and slope['error_type'] == 'TypeError'
    expected_line, = call_sites
    assert slope['error_location'] == {'module': 'report_agent.writer_assessment',
                                       'function': 'read_indicator_step', 'line': expected_line}
    assert secret not in json.dumps(result) and 'stop_code' not in slope
