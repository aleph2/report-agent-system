"""Exact recovery feedback for observed state-path/offset mistakes."""
import pytest
from report_agent.errors import ActionRejected
from report_agent.content_tasks import delegated_task
from report_agent.decision_state import read_state
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared,review_call
from test_reviewer_complete_materials import configure


def test_reviewer_missing_state_path_returns_scoped_keys_not_source_data(case):
    cs,_,criteria,_=prepared(case)
    workspace=configure(cs)
    with delegated_task(workspace,'coordinator',review_call(criteria)):
        with pytest.raises(ActionRejected,match='^STATE_PATH_NOT_FOUND$') as error:
            read_state(workspace,'reviewer',['review_requirements',0])
        detail=error.value.diagnostic
        assert detail['parameter_path']==['path',0]
        assert detail['resolved_path']==[] and 'assignment' in detail['available_keys']
        assert 'payload' not in detail and 'value' not in detail


def test_dictionary_offset_feedback_preserves_exact_state_path(case):
    cs,_,_,_=prepared(case)
    workspace=configure(cs)
    with pytest.raises(ActionRejected,match='^STATE_OFFSET_REQUIRES_LIST_OR_TEXT$') as error:
        read_state(workspace,'coordinator',['review_tasks'],offset=6000)
    assert error.value.diagnostic['read_state_path']==['review_tasks']
    assert error.value.diagnostic['parameter_path']==['offset']
    assert error.value.diagnostic['selected_type']=='dict' and error.value.diagnostic['allowed_offset']==0


from test_hierarchical_content import ws,seed

@pytest.mark.parametrize('kind',['Evidence','ContentNode'])
def test_content_selection_reports_wrong_slot_separately_from_missing_membership(ws,kind):
    from report_agent.content_selection import selected_content
    cs,_,refs,snapshot,_=seed(ws)
    target=refs['evidence'] if kind=='Evidence' else {'type':'ContentNode','id':'outside','version':1}
    with pytest.raises(ActionRejected,match='^CONTENT_SELECTION_OUTSIDE_SNAPSHOT$') as error:
        selected_content(ws,snapshot,[{'ref':target}])
    detail=error.value.diagnostic
    assert detail['reason']==('unsupported_selection_object_type' if kind=='Evidence' else 'object_not_in_snapshot')
    assert detail['allowed_object_types']==['ContentNode']
    assert detail['parameter_path']==['selections',0,'ref'] and detail['snapshot_ref']==snapshot
