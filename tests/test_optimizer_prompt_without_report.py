"""Independent learning is valid without a report manifest."""
import pytest
from langchain_core.messages import AIMessage
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.learning import LearningLibrary
from report_agent.learning_runtime import build_optimizer
from test_deep_runtime import Driver

@pytest.mark.parametrize('report_mode',[None,'native-reviewer-v2','bounded-tool-v1'])
async def test_independent_optimizer_diagnostic_has_no_report_profile_precondition(tmp_path,report_mode):
    store=Store(tmp_path/'case')
    if report_mode:
        store.initialize({'goal':'Synthetic report','sources':[{'id':'s','content':'Fixture source','coverage':'complete'}],
            'review_execution_mode':report_mode})
    workspace=Workspace(store)
    workspace.store.set('learning_config',{'library_path':str(tmp_path/'library'),'customer_id':'fixture'})
    LearningLibrary(tmp_path/'library')
    driver=Driver(optimizer=[AIMessage(content='Independent reflection, no report claim.')])
    await build_optimizer(workspace,driver('optimizer')).ainvoke({'messages':[('user','Inspect existing synthetic learning scope.')]})
    assert len(driver.calls)==1
    event=next(e for e in store.events() if e['kind']=='prompt_model_input')
    capture=store.get(event['data']['capture_key'])
    assert capture['purpose']=='experience_optimizer'
    assert capture['public_input']['review_profile']=='not_applicable'


@pytest.mark.parametrize('bad',['missing-manifest','unknown-profile'])
async def test_real_report_profile_errors_still_fail_closed(tmp_path,bad):
    from types import SimpleNamespace
    from langchain_core.messages import SystemMessage
    from report_agent.prompt_provenance import AgentPromptBoundary
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.errors import ActionRejected
    store=Store(tmp_path/'report')
    if bad=='unknown-profile':
        store.initialize({'goal':'Synthetic report','sources':[{'id':'s','content':'Fixture source','coverage':'complete'}],
            'review_execution_mode':'invalid-profile'})
    request=SimpleNamespace(system_message=SystemMessage(content=role_prompt('coordinator')),messages=[],tools=[])
    called=[]
    async def handler(_):called.append(True)
    with pytest.raises((ValueError,ActionRejected),match='PROJECT_NOT_INITIALIZED|UNKNOWN_REVIEW_EXECUTION_PROFILE'):
        await AgentPromptBoundary(Workspace(store),'coordinator').awrap_model_call(request,handler)
    assert called==[]
