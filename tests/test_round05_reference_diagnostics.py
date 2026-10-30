"""Precise rejection feedback without changing closure, basis or pair acceptance."""
from copy import deepcopy
import pytest

from report_agent.content_models import Ref
from report_agent.content_tasks import delegated_task
from report_agent.content_export import export_snapshot
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.workspace import Workspace
from test_hierarchical_content import ws,seed
from test_deliverable_declaration_v4 import case,node
from test_review_binding_v4 import prepared,review_call,task_record
from test_content_delivery_download import selected_pair


def test_closure_feedback_lists_all_three_missing_nodes_without_adding_them(ws):
    cs,actor,refs,_,members=seed(ws)
    objects=[]
    for index in range(3):
        name='workbook-only-'+str(index)
        objects += [node(name),{'client_key':'link-'+str(index),'type':'Relation','payload':{
            'subject_ref':{'client_key':name},'object_ref':refs['evidence'],'predicate':'supported_by',
            'provenance_kind':'adopted_during_generation'}}]
    added=cs.commit(actor,'add-workbook-only',objects)['result']['refs']
    missing=[added['workbook-only-'+str(i)] for i in range(3)]
    supplied=members+[added['link-'+str(i)] for i in range(3)]
    before=deepcopy(cs.list_objects())
    def attempt():
        return cs.freeze(actor,'incomplete-three',refs['root'],supplied,workbook_refs=missing)
    with pytest.raises(ActionRejected,match='^INCOMPLETE_REFERENCE_CLOSURE$') as failed:
        attempt()
    detail=failed.value.diagnostic
    assert detail['reason']=='referenced_objects_missing_from_manifest'
    assert detail['parameter_path']==['refs']
    assert {tuple(sorted(r.items())) for r in detail['missing_refs']}=={tuple(sorted(r.items())) for r in missing}
    assert len(detail['referrers'])==3
    assert cs.list_objects()==before
    receipt=cs.receipt(actor,'incomplete-three')
    with pytest.raises(ActionRejected) as cached:attempt()
    assert cached.value.diagnostic==detail
    assert cs.receipt(actor,'incomplete-three')==receipt
    accepted=cs.freeze(actor,'explicit-complete',refs['root'],supplied+missing,workbook_refs=missing)
    assert cs.read(accepted['result']['snapshot_ref'])['payload']['workbook_refs']==sorted(missing,key=lambda r:Ref(**r).key())


def test_basis_feedback_identifies_only_authorized_conflicting_assignment(case):
    cs,_,criteria,_=prepared(case);workspace=Workspace(cs.store);tasks=[]
    for index in range(2):
        with delegated_task(workspace,'coordinator',review_call(criteria[index:index+1],identity='basis-'+str(index))) as (_,actor):
            tasks.append(task_record(cs,actor))
    snapshot=tasks[0]['payload']['review_snapshot_ref']
    word=export_snapshot(cs,case[1],'basis-word',snapshot)['result']['export_ref']
    select=next(t for t in content_tools(workspace,'coordinator') if getattr(t,'__name__',None)=='select_content_delivery')
    args={'review_basis_assignment_ref':Ref(**tasks[0]['ref']),'review_assignment_refs':[Ref(**tasks[1]['ref'])]}
    with pytest.raises(ActionRejected,match='^REVIEW_ASSIGNMENT_BASIS_MISMATCH$') as failed:
        select('different-basis',Ref(**snapshot),Ref(**word),**args)
    detail=failed.value.diagnostic
    assert detail['parameter_path']==['review_assignment_refs',0]
    assert detail['basis_assignment_ref']==tasks[0]['ref']
    assert detail['provided_assignment_ref']==tasks[1]['ref']
    assert detail['expected_basis_digest']==tasks[0]['payload']['review_commission_basis']['digest']
    assert detail['provided_basis_digest']==tasks[1]['payload']['review_commission_basis']['digest']
    assert cs.store.get('content_delivery') is None
    with pytest.raises(ActionRejected) as cached:
        select('different-basis',Ref(**snapshot),Ref(**word),**args)
    assert cached.value.diagnostic==detail
    assert select('same-basis',Ref(**snapshot),Ref(**word),review_basis_assignment_ref=Ref(**tasks[0]['ref']),
                  review_assignment_refs=[Ref(**tasks[0]['ref'])])['ok']


def test_companion_feedback_explains_exact_word_link_without_selecting_latest(ws):
    cs,actor,snapshot,old_word,workbook,select=selected_pair(ws)
    new_word=export_snapshot(cs,actor,'new-word',snapshot)['result']['export_ref']
    before=deepcopy(cs.store.get('content_delivery'))
    with pytest.raises(ActionRejected,match='^COMPANION_EXPORT_VERSION_MISMATCH$') as failed:
        select('stale-companion',Ref(**snapshot),Ref(**new_word),workbook_export_ref=Ref(**workbook))
    detail=failed.value.diagnostic
    assert detail['parameter_path']==['workbook_export_ref']
    assert detail['selected_word_export_ref']==new_word
    assert detail['workbook_export_ref']==workbook
    assert detail['workbook_report_export_ref']==old_word
    assert detail['expected_snapshot_ref']==detail['workbook_snapshot_ref']==snapshot
    assert cs.store.get('content_delivery')==before
    with pytest.raises(ActionRejected) as cached:
        select('stale-companion',Ref(**snapshot),Ref(**new_word),workbook_export_ref=Ref(**workbook))
    assert cached.value.diagnostic==detail
    assert select('explicit-word-only',Ref(**snapshot),Ref(**new_word))['ok']
    assert 'workbook_export_ref' not in cs.store.get('content_delivery')
