"""Exact structure/source observation bridges; metadata never stands for bodies."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from report_agent.content_models import Ref
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.hierarchical_tools import content_tools
from report_agent.task_supervision import material_refs_in_observation,source_extents_in_observation,missing_required_materials
from report_agent.source_materials import returned,block_material
from test_hierarchical_content import ws,seed
from test_reviewer_native_profile import native,commission,candidate
from test_deep_runtime import call


def finding(basis='snapshot_structure',locator='absent'):
    return {'finding_type':'confirmed_defect','locator_state':locator,'description':'Synthetic required section is absent.',
        'impact':'Assigned fixture criterion','needed_outcome':'Supply the required section or correct with evidence.',
        'requirement_index':0,'observation_indexes':[0],'basis_kind':basis}


@pytest.mark.parametrize('complete',[False,True])
def test_native_index_receipt_is_paged_structure_only_and_absence_needs_complete_inventory(ws,complete):
    """R07/S05: complete structure versus missing initial selection are distinct."""
    native(ws);cs,_,refs,snap,_=seed(ws)
    request=commission(snap,refs);req=request['review_requirements'][0]
    req.update(required_materials=[],content_check_scopes=[])
    with delegated_task(ws,'coordinator',call('task',request,'structural-task')) as (_,actor):
        read=next(t for t in content_tools(ws,'reviewer') if t.__name__=='read_content_index')
        first=read(Ref.model_validate(snap),0,1)
        assert first['receipt_id']
        index=first['result']['snapshot_structure']
        assert index['offset']==0 and index['next_offset']==1 and len(index['nodes'])==1
        assert not material_refs_in_observation(first['result'])
        receipts=[first['receipt_id']]
        if complete:
            second=read(Ref.model_validate(snap),1,1)
            assert second['result']['snapshot_structure']['next_offset'] is None
            receipts.append(second['receipt_id'])
        value=candidate(snap,refs,receipts,state='running')
        value['items'][0]['findings']=[finding()]
        value['items'][0]['findings'][0]['observation_indexes']=list(range(len(receipts)))
        if not complete:
            with pytest.raises(ActionRejected,match='INCOMPLETE_INVENTORY_CANNOT_ESTABLISH_ABSENCE'):
                cs.submit_review(actor,'structure-absence',value,{})
        else:
            saved=cs.submit_review(actor,'structure-absence',value,{})
            assert saved['ok'] and cs.read(saved['result']['review_ref'])['payload']['items'][0]['execution_state']=='running'


@pytest.mark.parametrize('basis',['snapshot_structure','supplied_content'])
def test_native_finding_cannot_relabel_evidence_kind(ws,basis):
    native(ws);cs,_,refs,snap,_=seed(ws)
    request=commission(snap,refs);request['review_requirements'][0].update(required_materials=[],content_check_scopes=[])
    with delegated_task(ws,'coordinator',call('task',request,'basis-task')) as (_,actor):
        if basis=='snapshot_structure':receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        else:
            read=next(t for t in content_tools(ws,'reviewer') if t.__name__=='read_content_index')
            receipt=read(Ref.model_validate(snap),0,20)['receipt_id']
        value=candidate(snap,refs,[receipt],state='running')
        value['items'][0]['findings']=[finding(basis,'located')]
        with pytest.raises(ActionRejected,match='STRUCTURE_FINDING_REQUIRES_SNAPSHOT_EVIDENCE|STRUCTURE_METADATA_IS_NOT_CONTENT_EVIDENCE'):
            cs.submit_review(actor,'wrong-basis',value,{})


def test_legacy_content_index_return_contract_remains_metadata_without_receipt(ws):
    cs,_,refs,snap,_=seed(ws)
    read=next(t for t in content_tools(ws,'reviewer') if t.__name__=='read_content_index')
    # Historical fixture has no mode; task ownership remains enforced.
    with delegated_task(ws,'coordinator',call('task',commission(snap,refs),'legacy-index-task')):
        result=read(Ref.model_validate(snap))
    assert result['snapshot_ref']==snap and 'receipt_id' not in result and 'nodes' in result


@pytest.mark.parametrize('kind',['unresolved','candidate','suggestion'])
def test_partial_structural_investigation_does_not_require_global_inventory(ws,kind):
    """A still-unverified absence report is not a confirmed whole-snapshot defect."""
    native(ws);cs,_,refs,snap,_=seed(ws)
    request=commission(snap,refs);request['review_requirements'][0].update(required_materials=[],content_check_scopes=[])
    with delegated_task(ws,'coordinator',call('task',request,'unresolved-structure')) as (_,actor):
        read=next(t for t in content_tools(ws,'reviewer') if t.__name__=='read_content_index')
        receipt=read(Ref.model_validate(snap),0,1)['receipt_id']
        value=candidate(snap,refs,[receipt],verdict='undetermined',state='running')
        value['items'][0]['findings']=[{**finding(),'finding_type':kind,
            'description':'Not found on this page; remaining inventory still needs inspection.'}]
        saved=cs.submit_review(actor,'unfinished-inventory',value,{})
        assert saved['ok']


@pytest.mark.parametrize('change',['valid','wrong-view','wrong-span','wrong-version','foreign-owner','snippet','tampered'])
def test_native_source_receipt_proves_only_actual_version_view_and_blocks(ws,change):
    """R06/R08/S05: original full source payload and located block reads differ."""
    native(ws);cs,_,refs,snap,members=seed(ws)
    source=next(r for r in members if r['type']=='SourceArtifact')
    request=commission(snap,refs,source)
    with delegated_task(ws,'coordinator',call('task',request,'source-task')) as (_,actor):
        from report_agent.deep_runtime import business_tools
        read=next(t for t in business_tools(ws,'reviewer',None,None) if t.__name__=='read_source_page')
        message=read(source_id='s',offset=0,limit=1,runtime=SimpleNamespace(tool_call_id='source-read'))
        page=json.loads(message.content);receipt=page['receipt_id']
        with ws.store.connect() as db:
            raw=json.loads(db.execute('SELECT data FROM content_observations WHERE id=?',(receipt,)).fetchone()[0])
        assert not material_refs_in_observation(raw)  # binding is not whole-source reading
        target=deepcopy(request['review_requirements'][0])
        if change=='wrong-view':target['required_materials'][0]['source_spans'][0]['table_detail']='references'
        if change=='wrong-span':target['required_materials'][0]['source_spans'][0]['offset']=1
        if change=='wrong-version':target['required_materials'][0]['source_spans'][0]['source_ref']={**source,'version':999}
        if change=='snippet':
            message=returned(ws,'reviewer','search_sources',{'matches':[{'source_id':'s','snippet':'fixture'}]},[],
                SimpleNamespace(tool_call_id='snippet-read'))
            with ws.store.connect() as db:
                raw=json.loads(db.execute('SELECT data FROM content_observations WHERE id=?',
                    (json.loads(message.content)['receipt_id'],)).fetchone()[0])
        if change=='tampered':
            record=ws.store.get('source_material:'+raw['native_source_material_receipt'])
            ws.store.set('tool_observation:'+record['body_ref'],{'owner':actor.id,'tool':'read_source_page',
                'text':'changed','sha256':'wrong'})
        if change in {'foreign-owner','tampered'}:
            with pytest.raises((ActionRejected,ActionForbidden)):
                source_extents_in_observation(cs,'other-actor' if change=='foreign-owner' else actor.id,raw)
        else:
            extents=source_extents_in_observation(cs,actor.id,raw)
            # Use Store's canonical encoding for the positive exact claim receipt.
            from report_agent.store import encode
            missing=missing_required_materials(target,{encode(refs['claim'])},{0},extents)
            assert bool(missing)==(change!='valid')


def test_source_receipt_and_review_observation_roll_back_together(ws):
    """Same production read boundary, actual SQLite failure between linked writes."""
    import sqlite3
    native(ws);cs,_,refs,snap,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snap,refs),'atomic-source')):
        from report_agent.deep_runtime import business_tools
        read=next(t for t in business_tools(ws,'reviewer',None,None) if t.__name__=='read_source_page')
        with ws.store.connect() as db:
            before=list(db.execute("SELECT key,value FROM state WHERE key LIKE 'source_material%' OR key LIKE 'tool_observation:%'"))
            db.execute("CREATE TRIGGER synthetic_fail_observation BEFORE INSERT ON content_observations BEGIN SELECT RAISE(ABORT,'synthetic observation write failure'); END")
        with pytest.raises(sqlite3.IntegrityError,match='synthetic observation write failure'):
            read(source_id='s',offset=0,limit=1,runtime=SimpleNamespace(tool_call_id='atomic-read'))
        with ws.store.connect() as db:
            assert list(db.execute("SELECT key,value FROM state WHERE key LIKE 'source_material%' OR key LIKE 'tool_observation:%'"))==before
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0]==0
