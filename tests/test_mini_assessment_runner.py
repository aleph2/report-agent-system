"""Offline two-slope routing; the trusted launch admission has separate tests."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from report_agent.content_store import ContentStore
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.writer_indicator_steps import run_mini_assessment
from test_deep_runtime import Driver
from test_writer_five_slopes import action


@pytest.mark.asyncio
async def test_unbound_or_forged_fake_profile_cannot_enter_writer():
    with pytest.raises(ValueError,match='VERIFIED_FAKE_RUN_REQUIRED'):
        await run_mini_assessment(None,None,verified_run=SimpleNamespace(run_id='invented'))


@pytest.mark.asyncio
async def test_two_mini_slopes_run_twenty_two_independent_assessment_steps(tmp_path,monkeypatch):
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
        return action('save_indicator_outcome',f'route-{len(seen)}',kind='gap',
                      missing='Scripted routing-only gap.',question='Review fixture evidence independently?')
    driver=Driver(writer=[record]*22)
    result=await run_mini_assessment(workspace,driver('writer'),verified_run=binding)
    assert result['status']=='closed_with_gaps' and result['scope']=='assessment_writer_only'
    assert [s['object_id'] for s in result['slopes']]==['A','B']
    assert len({s['writer_actor'] for s in result['slopes']})==2
    assert len(seen)==22 and len({(label,indicator) for label,indicator,_,_ in seen})==22
    for ix,s in enumerate(result['slopes']):
        assert s['indicator_steps']['progress']=={'recorded':11,'total':11}
        assert s['indicator_steps']['assessment_ref'] is None and not s['refusals']
        batch=seen[11*ix:11*(ix+1)]
        assert len({row[0] for row in batch})==1 and sorted(row[2] for row in batch)==list(range(1,12))
        assert [row[3] for row in batch]==list(range(11))
    cs=ContentStore(workspace.store)
    for slope in result['slopes']:
        actor_id=slope['writer_actor'].split(':')[-1]
        task=cs.read({'type':'DelegatedTask','id':actor_id,'version':1})['payload']
        assert task['assessment_object_id']==slope['object_id'] and task['section_ids']==['3']
    assert not cs.list_objects('Assessment')
