"""V4 draft/basis/layout choices retain the same parent and source boundary."""
from report_agent import report_state
import pytest

from report_agent.content_store import Actor
from report_agent.content_tasks import delegated_task
from report_agent.content_models import Ref
from report_agent.content_export import export_snapshot
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case, node
from test_review_binding_v4 import prepared, review_call, task_record
from test_deliverable_recovery_v4 import declaration, resolve


def foreign_saved_export(cs):
    other_parent = Actor('other-parent','coordinator','other-root')
    task = cs.operation(other_parent,'foreign-producer',{},lambda db:{'ref':cs._insert(db,other_parent,
        'DelegatedTask',{'role':'writer','goal':'Foreign parent fixture.','delegated_by':other_parent.id})})['result']['ref']
    writer = Actor('content:writer:'+task['id'],'writer',task['id'])
    root = cs.commit(writer,'foreign-root',[node('foreign','report')])['result']['refs']['foreign']
    snapshot = cs.freeze(writer,'foreign-snapshot',root,[root])['result']['snapshot_ref']
    exported = export_snapshot(cs,writer,'foreign-export',snapshot)['result']['export_ref']
    return snapshot, exported


@pytest.mark.parametrize('with_basis',[False,True])
def test_current_co_cannot_select_foreign_parent_export_with_or_without_basis(case, with_basis):
    cs, _, criteria, _ = prepared(case)
    ws = Workspace(cs.store)
    kwargs = {}
    if with_basis:
        with delegated_task(ws,'coordinator',review_call(criteria[:1])) as (_,actor):
            kwargs['review_basis_assignment_ref'] = Ref(**task_record(cs,actor)['ref'])
    snapshot, exported = foreign_saved_export(cs)
    choose = next(t for t in content_tools(ws,'coordinator') if t.__name__=='select_content_delivery')
    with pytest.raises(ActionForbidden):
        choose('forbidden-selection',Ref(**snapshot),Ref(**exported),**kwargs)
    assert report_state.selected_delivery(cs.store) is None


def test_current_co_cannot_grant_layout_a_foreign_parent_snapshot(case):
    cs = case[0]
    snapshot, _ = foreign_saved_export(cs)
    before = cs.list_objects('DelegatedTask')
    call = {'name':'task','id':'foreign-layout','args':{'subagent_type':'layout',
        'description':'Presentation-only fixture.','layout_snapshot_ref':snapshot}}
    with pytest.raises(ActionForbidden):
        with delegated_task(Workspace(cs.store),'coordinator',call):
            pytest.fail('Foreign-parent layout grant must not dispatch')
    assert cs.list_objects('DelegatedTask') == before


def test_current_co_can_select_and_grant_its_writers_snapshot_without_cloning(case):
    cs, co, writer = case[:3]
    declaration(case)
    snapshot = resolve(cs,writer,'writer-freezes',{'kind':'deliverable','operation_id':'published'})
    exported = export_snapshot(cs,writer,'writer-export',snapshot)['result']['export_ref']
    ws = Workspace(cs.store)
    choose = next(t for t in content_tools(ws,'coordinator') if t.__name__=='select_content_delivery')
    assert choose('own-parent-selection',Ref(**snapshot),Ref(**exported))['ok']
    call = {'name':'task','id':'own-layout','args':{'subagent_type':'layout',
        'description':'Presentation-only fixture.','layout_snapshot_ref':snapshot}}
    with delegated_task(ws,'coordinator',call) as (_,actor):
        result = export_snapshot(cs,actor,'layout-export',snapshot)['result']
        assert cs.read(result['export_ref'])['owner_id'] == actor.id
    assert cs.read(snapshot)['owner_id'] == writer.id
    assert len(cs.list_objects('DocumentSnapshot')) == 1


def test_layout_content_node_misidentified_as_snapshot_is_known_rejection(case):
    cs = case[0]
    output = declaration(case)
    call = {'name':'task','id':'wrong-snapshot-kind','args':{'subagent_type':'layout',
        'description':'Presentation-only fixture.','layout_snapshot_ref':output['refs']['a']}}
    with pytest.raises(ActionRejected, match='SNAPSHOT_REQUIRED'):
        with delegated_task(Workspace(cs.store),'coordinator',call):
            pytest.fail('A content node is not a layout snapshot')
    assert cs.receipt(case[1],'delegate:wrong-snapshot-kind')['state'] == 'known_failure'
