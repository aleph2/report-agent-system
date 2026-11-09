from report_agent import report_state
import pytest
from report_agent.content_models import Ref
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import content_tools
from test_hierarchical_content import ws, seed


def test_flat_text_tool_preserves_binding_ownership_and_versions(ws):
    cs, _, _, _, _ = seed(ws)
    tool = next(t for t in content_tools(ws, 'writer') if t.__name__ == 'save_text_node')
    args = dict(operation_id='save-text', text='Observed "quoted" text\n第二行', kind='block',
                claim_kind='inference', qualifications='Draft; unresolved scope')
    with pytest.raises(ActionForbidden):
        tool(**args)
    call = {'id':'writer-a','args':{'subagent_type':'writer','description':'Save section'}}
    with delegated_task(ws,'coordinator',call):
        saved = tool(**args)
        assert tool(**args) == saved
        ref = saved['result']['refs']['text']
        assert cs.read(ref)['payload']['body']['text'] == args['text']
        revised = tool(**{**args,'operation_id':'revise','text':'New text'},previous_ref=Ref(**ref))
        assert revised['result']['refs']['text']['version'] == 2
        with pytest.raises(ActionRejected,match='VERSION_CONFLICT'):
            tool(**{**args,'operation_id':'stale'},previous_ref=Ref(**ref))
    other = {'id':'writer-b','args':{'subagent_type':'writer','description':'Separate section'}}
    with delegated_task(ws,'coordinator',other):
        with pytest.raises(ActionForbidden):
            tool(**{**args,'operation_id':'other'},previous_ref=Ref(**revised['result']['refs']['text']))
    assert 'save_text_node' not in {t.__name__ for t in content_tools(ws,'reviewer')}
    assert report_state.selected_delivery(ws.store) is None
