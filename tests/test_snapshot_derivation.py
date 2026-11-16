"""Synthetic native interfaces and real export bytes; no paid/semantic acceptance."""
from copy import deepcopy
from io import BytesIO

import pytest

from report_agent.content_models import Ref
from pydantic import ValidationError
from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.store import digest
from report_agent.errors import ActionRejected, ActionForbidden
from test_hierarchical_content import ws, seed


def workbook(cs, actor):
    return cs.commit(actor,'workbook-members',[
        {'client_key':'table','type':'ContentNode','payload':{'kind':'table',
         'body':{'columns':['Issue','Source'],'rows':[['ONLY_XLSX','verified source']]},
         'qualifiers':{},'claim_kind':'structure'}},
        {'client_key':'note','type':'ContentNode','payload':{'kind':'block',
         'body':{'text':'ONLY_XLSX_NOTE'},'qualifiers':{},'claim_kind':'structure'}}])['result']['refs']


def test_replacements_require_exact_base_and_explicit_updated_relations(ws):
    cs,actor,refs,base,members=seed(ws)
    old=cs.read(refs['claim'])
    changed=cs.commit(actor,'revise-claim',[{'client_key':'claim','type':'ContentNode','previous_ref':refs['claim'],
        'payload':{**old['payload'],'body':{'text':'Exact revised content.'}}}])['result']['refs']['claim']
    pair={'previous_ref':refs['claim'],'new_ref':changed}
    with pytest.raises(ActionRejected,match='INCOMPLETE_REFERENCE_CLOSURE'):
        cs.derive_snapshot(actor,'missing-relations',base,[],[pair])
    changes=[pair]
    for key in ('edge','support'):
        r=cs.read(refs[key]); payload=deepcopy(r['payload'])
        for field in ('subject_ref','object_ref'):
            if payload[field]==refs['claim']:payload[field]=changed
        new=cs.commit(actor,'revise-'+key,[{'client_key':key,'type':'Relation','previous_ref':refs[key],
            'payload':payload}])['result']['refs'][key]
        changes.append({'previous_ref':refs[key],'new_ref':new})
    derived=cs.derive_snapshot(actor,'all-explicit',base,[],changes)['result']['snapshot_ref']
    actual=cs.read(derived)['payload']['refs']
    assert changed in actual and refs['claim'] not in actual
    assert cs.read(base)['payload']['refs']==sorted(members,key=lambda r:Ref.model_validate(r).key())
    assert cs.read(refs['claim'])==old
    with pytest.raises(ActionRejected,match='OUTSIDE_BASE'):
        cs.derive_snapshot(actor,'wrong-previous',base,[],[{'previous_ref':changed,'new_ref':changed}])
    with pytest.raises(ActionRejected,match='DUPLICATE_SNAPSHOT_REPLACEMENT'):
        cs.derive_snapshot(actor,'twice',base,[],[pair,pair])


@pytest.mark.parametrize('scenario', ['duplicate','mixed','detached','channel_outside','duplicate_channel','wrong_role','foreign_root','operation_conflict'])
def test_derivation_guards_and_no_partial_write(ws,scenario):
    cs,actor,refs,base,members=seed(ws);added=workbook(cs,actor)
    before=len(cs.list_objects('DocumentSnapshot'))
    args=[actor,scenario,base,[]];kwargs={};error=ActionRejected
    if scenario=='duplicate':args[3]=[refs['claim']]
    if scenario=='mixed':
        new=cs.commit(actor,'revise',[{'client_key':'x','type':'ContentNode','previous_ref':refs['claim'],
            'payload':cs.read(refs['claim'])['payload']}])['result']['refs']['x'];args[3]=[new]
    if scenario=='detached':args[3]=list(added.values())
    if scenario=='channel_outside':kwargs['workbook_refs']=[added['table']]
    if scenario=='duplicate_channel':args[3]=list(added.values());kwargs['workbook_refs']=[added['table'],added['table'],added['note']]
    if scenario=='wrong_role':args[0]=actor_for('reviewer');error=ActionForbidden
    if scenario=='foreign_root':args[0]=actor_for('writer');error=ActionForbidden
    if scenario=='operation_conflict':
        cs.derive_snapshot(actor,scenario,base,[]);before+=1;args[3]=list(added.values())
    with pytest.raises(error):cs.derive_snapshot(*args,**kwargs)
    assert len(cs.list_objects('DocumentSnapshot'))==before
    if scenario!='operation_conflict':
        assert not [e for e in ws.store.events() if e['kind']=='snapshot_derived']


def test_inherited_workbook_maps_only_explicit_replacements_and_old_freeze_hash_stays(ws):
    cs,actor,refs,base,members=seed(ws);added=workbook(cs,actor)
    derived=cs.derive_snapshot(actor,'initial',base,list(added.values()),workbook_refs=list(added.values()))['result']['snapshot_ref']
    prior=cs.read(added['note'])
    new=cs.commit(actor,'revise-note',[{'client_key':'note','type':'ContentNode','previous_ref':added['note'],
        'payload':{**prior['payload'],'body':{'text':'Explicit new note.'}}}])['result']['refs']['note']
    # No current-head inference: inheritance without a replacement keeps v1.
    inherited=cs.derive_snapshot(actor,'inherit',derived,[])['result']['snapshot_ref']
    assert added['note'] in cs.read(inherited)['payload']['workbook_refs']
    revised=cs.derive_snapshot(actor,'replace-note',derived,[],[{'previous_ref':added['note'],'new_ref':new}])['result']['snapshot_ref']
    assert new in cs.read(revised)['payload']['workbook_refs']
    with pytest.raises(ActionRejected,match='DETACHED_PRESENTATION_NODE'):
        cs.derive_snapshot(actor,'explicit-empty',derived,[],workbook_refs=[])
    expected=digest({'actor':actor.__dict__,'request':{'freeze':{'root_ref':refs['root'],'refs':members}}})
    assert cs.receipt(actor,'snapshot')['request_digest']==expected
    assert not any(t.__name__=='derive_snapshot' for t in content_tools(ws,'reviewer'))


def test_explicit_root_replacement_and_changed_snapshot_identity_rejected(ws):
    cs,actor,refs,base,members=seed(ws)
    newroot=cs.commit(actor,'root2',[{'client_key':'r','type':'ContentNode','previous_ref':refs['root'],
        'payload':{**cs.read(refs['root'])['payload'],'body':{'text':'New exact title'}}}])['result']['refs']['r']
    oldedge=cs.read(refs['edge'])
    edge=cs.commit(actor,'edge2',[{'client_key':'e','type':'Relation','previous_ref':refs['edge'],
        'payload':{**oldedge['payload'],'subject_ref':newroot}}])['result']['refs']['e']
    pairs=[{'previous_ref':refs['root'],'new_ref':newroot},{'previous_ref':refs['edge'],'new_ref':edge}]
    new=cs.derive_snapshot(actor,'root-map',base,[],pairs)['result']['snapshot_ref']
    assert cs.read(new)['payload']['root_ref']==newroot
    with pytest.raises(ValidationError,match='SAME_IDENTITY'):
        cs.derive_snapshot(actor,'wrong-id',base,[],[{'previous_ref':refs['root'],'new_ref':refs['claim']}])
    with pytest.raises(ActionRejected,match='BASE_REQUIRES_DOCUMENT_SNAPSHOT'):
        cs.derive_snapshot(actor,'wrong-base-type',refs['root'],[])
    with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
        cs.derive_snapshot(actor,'root-map',new,[],pairs)


def test_failure_replay_and_shared_freeze_rollback(ws,monkeypatch):
    cs,actor,refs,base,members=seed(ws)
    insert=cs._insert
    def insert_then_reject(db,*args,**kwargs):
        insert(db,*args,**kwargs)
        raise ActionRejected('INJECTED_STORAGE_FINALIZATION_FAILURE')
    before=len(cs.list_objects())
    monkeypatch.setattr(cs,'_insert',insert_then_reject)
    for _ in range(2):
        with pytest.raises(ActionRejected,match='INJECTED_STORAGE_FINALIZATION_FAILURE'):
            cs.derive_snapshot(actor,'atomic-failure',base,[])
    assert len(cs.list_objects())==before
    assert cs.receipt(actor,'atomic-failure')['state']=='known_failure'
    assert not [e for e in ws.store.events() if e['kind']=='snapshot_derived']
