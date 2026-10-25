"""Synthetic native interfaces and real export bytes; no paid/semantic acceptance."""
import json
from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document
from openpyxl import load_workbook
from langchain_core.messages import AIMessage

from report_agent.content_models import Ref
from pydantic import ValidationError
from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.hierarchical_tools import actor_for, content_tools
from report_agent.store import digest
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.deep_runtime import run_report
from test_hierarchical_content import ws, seed
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, observation


def workbook(cs, actor):
    return cs.commit(actor,'workbook-members',[
        {'client_key':'table','type':'ContentNode','payload':{'kind':'table',
         'body':{'columns':['Issue','Source'],'rows':[['ONLY_XLSX','verified source']]},
         'qualifiers':{},'claim_kind':'structure'}},
        {'client_key':'note','type':'ContentNode','payload':{'kind':'block',
         'body':{'text':'ONLY_XLSX_NOTE'},'qualifiers':{},'claim_kind':'structure'}}])['result']['refs']


async def test_registered_197_member_base_two_additions_word_excel_exact_pair(ws):
    cs,actor,refs,base,members=seed(ws)
    extras=cs.commit(actor,'large-base-members',[{'client_key':str(i),'type':'ContentNode',
        'payload':{'kind':'claim','body':{'text':f'Explicit dependency {i}'},
        'qualifiers':{},'claim_kind':'fact'}} for i in range(197-len(members))])['result']['refs']
    base=cs.freeze(actor,'large-base',refs['root'],members+list(extras.values()))['result']['snapshot_ref']
    original=deepcopy(cs.read(base)); added=workbook(cs,actor); activate(ws)
    saved={}
    def word(messages):
        r=observation(messages,'derive_snapshot'); assert r['ok'],r
        saved['snapshot']=r['result']['snapshot_ref']
        return invoke('export_content_snapshot',operation_id='derived-word',snapshot_ref=saved['snapshot'])
    def excel(messages):
        r=observation(messages,'export_content_snapshot'); assert r['ok'],r
        saved['word']=r['result']['export_ref']
        return invoke('export_content_workbook',operation_id='derived-excel',snapshot_ref=saved['snapshot'],
            sheets=[{'name':'Issues','table_ref':added['table'],'note_refs':[added['note']]}],
            report_export_ref=saved['word'])
    def done(messages):
        r=observation(messages,'export_content_workbook');assert r['ok'],r
        saved['excel']=r['result']['export_ref'];return AIMessage(content='Exported fixture; no semantic judgment.')
    driver=Driver(coordinator=[invoke('derive_snapshot',operation_id='derive-native',base_snapshot_ref=base,
        additional_refs=list(added.values()),workbook_refs=list(added.values())),word,excel,done])
    await run_report(ws,driver)
    schema=next(t for t in driver.bindings['coordinator'][0] if t['name']=='derive_snapshot')
    serialized=json.dumps(schema)
    assert all(x in serialized for x in ('previous_ref','new_ref','base_snapshot_ref','additional_refs'))
    assert 'refs' not in schema['parameters']['properties']
    result=cs.read(saved['snapshot']);assert len(result['payload']['refs'])==199
    assert cs.read(base)==original
    assert all(cs.read(r)['owner_id']==actor.id for r in members)
    word_record=cs.read(saved['word'])['payload'];excel_record=cs.read(saved['excel'])['payload']
    assert word_record['snapshot_ref']==excel_record['snapshot_ref']==saved['snapshot']
    doc=Document(ws.store.root/word_record['file_ref'])
    assert 'ONLY_XLSX' not in '\n'.join(p.text for p in doc.paragraphs)
    book=load_workbook(ws.store.root/excel_record['file_ref'])
    values=str(list(book.active.values));book.close()
    assert 'ONLY_XLSX' in values and 'ONLY_XLSX_NOTE' in values
    again=cs.derive_snapshot(actor,'derive-native',base,list(added.values()),workbook_refs=list(added.values()))
    assert again['result']['snapshot_ref']==saved['snapshot']
    events=[e for e in ws.store.events() if e['kind']=='snapshot_derived']
    assert len(events)==1 and events[0]['data']['base_manifest_digest']==original['payload']['manifest_digest']
    assert cs.receipt(actor,'derive-native')['response']==again


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
