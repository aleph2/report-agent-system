"""Current Co dictionary and assembly use the production native binder."""
from copy import deepcopy
import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, task_record
from test_deliverable_recovery_v4 import resolve


def setup_message(case):
    from langchain.agents.middleware.types import ModelRequest
    from langchain_core.messages import SystemMessage
    from langchain_core.tools import StructuredTool
    from report_agent.content_tasks import task_tool
    from report_agent.live_messages import _co_request
    cs, output, criteria, originals = prepared(case)
    snapshot = resolve(cs, case[1], 'message-target', {'kind':'deliverable','operation_id':'published'})
    with cs.store.connect() as db:
        word = cs._insert(db, case[1], 'ExportArtifact', {'snapshot_ref':snapshot,'file_ref':'synthetic.docx'})
        excel = cs._insert(db, case[1], 'ExportArtifact', {'snapshot_ref':snapshot,'file_ref':'synthetic.xlsx'})
    def task(description: str, subagent_type: str) -> str:
        """Native delegation."""
        return description
    tool=task_tool(StructuredTool.from_function(task),review_profile='native-reviewer-v2',interface_profile='review-interfaces-v4')
    _,binding=_co_request(Workspace(cs.store),ModelRequest(model=None,tools=[tool],state={},
        system_message=SystemMessage('Original coordinator role.'),messages=[]))
    def scope(ref):
        return next(e['scope'] for e in binding['resources'] if e['resource']==ref)
    message={'description':'Compare exports; retain missing-data limitations.','subagent_type':'reviewer',
        'snapshot_scope':scope(snapshot),'commission_criterion_scopes':[scope(r) for r in criteria],
        'criterion_scopes':[scope(criteria[2])],'review_scope':'targeted','target_scope':scope(snapshot),
        'assessment_kind':'export','artifact_scopes':[scope(word),scope(excel)]}
    return cs,binding,message,criteria,snapshot,word,excel


def assemble(cs,actor,identity,binding,message):
    from report_agent.live_messages import _assemble_task
    return _assemble_task(Workspace(cs.store),actor,binding,{'name':'task','id':identity,'args':message})


def test_co_dictionary_and_adapter_save_the_original_delegated_task(case):
    cs, binding, message, criteria, snapshot, word, excel = setup_message(case)
    dictionary = binding['packet']['resource_scopes']
    assert len([c for c in dictionary if c['object_type']=='Criterion'])==len(criteria)
    assert len([c for c in dictionary if c['object_type']=='ExportArtifact'])==2
    call = assemble(cs, case[1], 'co-flat-call', binding, message)
    assert call['name'] == 'task' and call['id'] == 'co-flat-call'
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        saved = task_record(cs, actor)['payload']
        assert saved['review_commission_basis']['criterion_refs'] == sorted(criteria, key=lambda r: (r['type'], r['id'], r['version']))
        requirement, = saved['review_requirements']
        assert requirement['criterion_ref'] == criteria[2]
        assert requirement['artifact_refs'] == [word, excel]
        assert saved['review_snapshot_ref'] == snapshot
        assert saved['goal'] == message['description']
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('field,value', [
    ('criterion_scopes', ['C7']), ('artifact_scopes', ['word']),
    ('artifact_scopes', ['s0']), ('criterion_scopes', []), ('artifact_scopes', None),
])
def test_co_rejects_bad_business_selections_without_guessing(case, field, value):
    cs, binding, message, *_ = setup_message(case)
    before = deepcopy(cs.list_objects('DelegatedTask'))
    with pytest.raises(ActionRejected):
        assemble(cs, case[1], 'invalid-co', binding, {**message, field: value})
    assert cs.list_objects('DelegatedTask') == before


def test_co_binding_cannot_be_replaced_by_a_forged_dictionary(case):
    cs, binding, message, *_ = setup_message(case)
    binding = deepcopy(binding)
    next(e for e in binding['resources'] if e['scope']==message['snapshot_scope'])['sha256']='forged'
    with pytest.raises(ActionRejected, match='TASK_RESOURCE_CHANGED'):
        assemble(cs, case[1], 'forged-co', binding, message)


async def test_assembled_co_call_runs_through_real_toolnode_and_business_boundary(case):
    from langchain_core.messages import AIMessage
    from support.flat_task_fixture import task_arguments
    from support.review_message_entry import delegate
    cs, _, _, criteria, snapshot, word, excel = setup_message(case)
    raw={'subagent_type':'reviewer','description':'Compare exports; retain missing-data limitations.',
        'review':{'deliverable':{'kind':'snapshot','snapshot_ref':snapshot},
            'standards':{'kind':'criteria','criterion_refs':criteria}, 'scope':{'kind':'mapped','items':[
            {'criterion_ref':criteria[2],'target_ref':snapshot,'assessment_kind':'export','artifact_refs':[word,excel]}]}}}
    args=task_arguments(cs,case[1],raw)
    result,_=await delegate(Workspace(cs.store),args,
        lambda state:{'messages':[AIMessage('Assigned review remains unperformed.')]},False,[])
    assert result['messages'][-1].status=='success',result['messages'][-1].content
    tasks=[r for r in cs.list_objects('DelegatedTask') if r['payload'].get('role')=='reviewer']
    assert len(tasks)==1
    assert tasks[0]['payload']['review_requirements'][0]['criterion_ref']==criteria[2]
    assert not cs.list_objects('ReviewRecord')
