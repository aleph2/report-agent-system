"""Real native tool boundary: no ignored export parameters or phantom refresh."""
import json
import pytest
from langchain_core.messages import AIMessage
from report_agent import deep_runtime
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared
from test_deep_runtime import Driver, invoke, observation
from test_reviewer_complete_materials import configure

@pytest.mark.parametrize('args,path', [({'refresh_toc':True},['refresh_toc']),
    ({'refresh_toc_default':True},['refresh_toc_default'])])
async def test_v4_export_unknown_top_level_parameter_is_rejected_before_side_effect(case,args,path):
    cs,_,_,_ = prepared(case)
    workspace = configure(cs)
    # Explicit declaration exists; this case tests parameter shape before selector resolution.
    seen=[]
    def feedback(messages):
        response = observation(messages,'export_content_snapshot')
        seen.append(response)
        assert response['ok'] is False, response
        assert response['diagnostic']['parameter_path'] == path
        assert response['diagnostic']['correct_parameter_path'] == ['layout','refresh_toc']
        assert not cs.list_objects('ExportArtifact')
        return AIMessage('Fixture parameter failure preserved; no retry.')
    driver = Driver(coordinator=[invoke('export_content_snapshot',operation_id='unsupported-export',deliverable={'kind':'deliverable','operation_id':'published'},**args),feedback])
    result = await deep_runtime.run_report(workspace,driver)
    assert result['last_error'] is None,(result,seen)
    assert len(seen)==1

async def test_v4_export_missing_selector_reports_exactly_one_without_creating_export(case):
    cs,_,_,_=prepared(case)
    workspace=configure(cs)
    def feedback(messages):
        response=observation(messages,'export_content_snapshot')
        assert response['ok'] is False,response
        assert response['diagnostic']['required_one_of'] == ['snapshot_ref','deliverable']
        assert not cs.list_objects('ExportArtifact')
        return AIMessage('Fixture selector absent; no retry.')
    result=await deep_runtime.run_report(workspace,Driver(coordinator=[
        invoke('export_content_snapshot',operation_id='no-selector'),feedback]))
    assert result['last_error'] is None,result
