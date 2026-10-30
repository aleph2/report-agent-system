"""Mixed artifact saves and current-version isolation using the real Store."""
from copy import deepcopy
import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from test_hierarchical_content import ws,seed
from test_deep_runtime import call
from test_reviewer_native_profile import native,commission,candidate
from test_artifact_review import setup,visual,payload


@pytest.mark.parametrize('shape',['complete','missing-page','partial'])
def test_native_mixed_content_and_render_does_not_bypass_actual_page_coverage(ws,shape):
    cs,refs,snap,export,render,source,request=setup(ws,pages=2,reference=False)
    native(ws)
    request['args']['review_requirements']+=commission(snap,refs)['review_requirements']
    with delegated_task(ws,'coordinator',request) as (_,actor):
        body=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snap,refs,[body])
        pages=range(1,3) if shape=='complete' else [1]
        receipts=[visual(cs,actor,render,export,source,p) for p in pages]
        item=payload(snap,refs,render,receipts,complete=shape!='partial').model_dump()['items'][0]
        item['check_results']=[{'requirement_index':0,'execution_state':'partial' if shape=='partial' else 'completed',
            'result':'Actual synthetic page observations.','observation_indexes':list(range(len(receipts))),
            'remaining':'Page two still unchecked.' if shape=='partial' else ''}]
        item['checked_requirement_indexes']=[] if shape=='partial' else [0]
        value['items'].append(item)
        if shape=='missing-page':
            with pytest.raises(ActionRejected,match='ARTIFACT_REVIEW_COVERAGE_INCOMPLETE'):
                cs.submit_review(actor,'mixed-save',value,{})
            assert not cs.list_objects('ReviewRecord')
        else:
            result=cs.submit_review(actor,'mixed-save',value,{})
            saved=cs.read(result['result']['review_ref'])['payload']['items']
            assert len(saved)==2 and saved[1]['execution_state']==('running' if shape=='partial' else 'completed')


def test_new_snapshot_does_not_inherit_old_native_acceptance_or_task_permission(ws):
    """R10/S06: frozen original, changed body and snapshot remain separate."""
    native(ws);cs,owner,refs,snap,members=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snap,refs),'old-version-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snap,refs,[receipt],verdict='satisfied')
        result=cs.submit_review(actor,'old-reviewed-version',value,{})
        before=deepcopy(cs.read(result['result']['review_ref']))
        node=cs.read(refs['claim'])['payload']
        new=cs.commit(owner,'change-body',[{'client_key':'new','type':'ContentNode','previous_ref':refs['claim'],
            'payload':{**node,'body':{'text':'Changed synthetic claim; old conclusion cannot approve it.'}}}])['result']['refs']['new']
        # Derive the closed graph through the actual supported snapshot derivation.
        changes=[{'previous_ref':refs['claim'],'new_ref':new}]
        for key in ('edge','support'):
            old=cs.read(refs[key]);changed=deepcopy(old['payload'])
            for field in ('subject_ref','object_ref'):
                if changed[field]==refs['claim']:changed[field]=new
            relation=cs.commit(owner,'change-'+key,[{'client_key':key,'type':'Relation',
                'previous_ref':refs[key],'payload':changed}])['result']['refs'][key]
            changes.append({'previous_ref':refs[key],'new_ref':relation})
        derived=cs.derive_snapshot(owner,'changed-snapshot',snap,[],changes)
        new_snap=derived['result']['snapshot_ref']
        assert cs.review_summary(new_snap,[{'target_ref':refs['root'],'criterion_ref':refs['k'],'scope':'delivery'}])['overall_verdict'] is None
        changed=deepcopy(value);changed['snapshot_ref']=new_snap;changed['target_ref']=new_snap
        with pytest.raises(ActionRejected,match='REVIEW_SNAPSHOT_OUTSIDE_ASSIGNMENT'):
            cs.submit_review(actor,'wrong-task-new-version',changed,{})
        assert cs.read(result['result']['review_ref'])==before
