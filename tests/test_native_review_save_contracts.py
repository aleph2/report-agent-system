"""Save/receipt/coverage protocol tests. Verdict truth is a separate M evaluation."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from report_agent.content_store import Actor
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from test_hierarchical_content import ws, seed
from test_deep_runtime import call
from test_reviewer_native_profile import native, commission, candidate


@pytest.mark.parametrize('verdict',['satisfied','not_satisfied','undetermined'])
def test_three_valid_verdict_shapes_persist_with_exact_owner_version_receipt(ws,verdict):
    """S01: the Store must not reject a record merely for an adverse verdict."""
    native(ws); cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'verdict-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[receipt],verdict=verdict)
        saved=cs.submit_review(actor,'save',value,{})
        record=cs.read(saved['result']['review_ref'])
        assert record['owner_id']==actor.id and record['task_id']==actor.task_id
        assert record['payload']['snapshot_ref']==snapshot
        assert record['payload']['items'][0]['verdict']==verdict
        assert record['payload']['items'][0]['observations'][0]['receipt_id']==receipt
        assert cs.receipt(actor,'save')['state']=='known_success'


@pytest.mark.parametrize('missing',[None,'body','rule'])
def test_sparse_body_and_rule_citations_without_title_only_root(ws,missing):
    """S02: unrelated root/metadata entries do not require decorative citations."""
    native(ws); cs,owner,refs,snapshot,members=seed(ws)
    objects=[
        {'client_key':name,'type':'ContentNode','payload':{'kind':'block','body':{'text':name+' actual fixture body'},
            'qualifiers':{},'claim_kind':'fact'}} for name in ['body-two','body-three']]
    objects.extend({'client_key':'edge-'+name,'type':'Relation','payload':{'subject_ref':refs['root'],
        'object_ref':{'client_key':name},'predicate':'contains','position':i+1,
        'provenance_kind':'adopted_during_generation'}} for i,name in enumerate(['body-two','body-three']))
    extras=cs.commit(owner,'extra-bodies',objects)['result']['refs']
    members=[*members,*extras.values()]
    snapshot=cs.freeze(owner,'expanded-snapshot',refs['root'],members)['result']['snapshot_ref']
    source=next(r for r in members if r['type']=='SourceArtifact')
    needed=[refs['claim'],extras['body-two'],extras['body-three'],source]
    request=commission(snapshot,refs)
    requirement=request['review_requirements'][0]
    requirement['content_check_scopes']=[]  # Isolate declared-material admission.
    requirement['required_materials'][0]['refs']=needed
    with delegated_task(ws,'coordinator',call('task',request,'sparse-task')) as (_,actor):
        selected=[r for r in needed if not (missing=='body' and r==extras['body-two'])
                  and not (missing=='rule' and r==source)]
        receipts=[cs.read_context(actor,r)['receipt_id'] for r in selected]
        value=candidate(snapshot,refs,receipts)
        if missing:
            with pytest.raises(ActionRejected,match='COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL'):
                cs.submit_review(actor,'sparse',value,{})
            assert cs.list_objects('ReviewRecord')==[]
            assert any(e['kind']=='review_submission_candidate' for e in ws.store.events())
        else:
            saved=cs.submit_review(actor,'sparse',value,{})
            record=cs.read(saved['result']['review_ref'])
            assert len(record['payload']['items'][0]['observations'])==4
            assert refs['root'] not in selected


def test_partial_confirmed_violation_saves_without_completing_assignment(ws):
    """S03/R03: logical work or a saved partial does not erase remaining checks."""
    from report_agent.task_supervision import reconcile
    native(ws); cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'partial-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[receipt],state='running')
        value['items'][0]['findings']=[{'finding_type':'confirmed_defect','locator_state':'located',
            'description':'Confirmed fixture discrepancy in the inspected part.','impact':'Affects the assigned criterion.',
            'needed_outcome':'Resolve against actual evidence.','requirement_index':0,'observation_indexes':[0],
            'basis_kind':'supplied_content'}]
        saved=cs.submit_review(actor,'partial',value,{})
        item=cs.read(saved['result']['review_ref'])['payload']['items'][0]
        assert item['verdict']=='not_satisfied' and item['execution_state']=='running'
        assert item['check_results'][0]['execution_state']=='partial'
        assert item['check_results'][0]['remaining']
        assert not reconcile(cs,actor.task_id)['execution_complete']


def test_invalid_reason_preserves_raw_candidate_without_formal_record(ws):
    """S04: a received representation error is not silently rewritten or retried."""
    native(ws); cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'raw-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[receipt]); del value['items'][0]['reason']
        with pytest.raises(ActionRejected,match=r'items\.0\.reason'):
            cs.submit_review(actor,'bad-reason',value,{})
        raw=[e for e in ws.store.events() if e['kind']=='review_submission_candidate'][-1]
        assert raw['data']['submission']==value
        assert cs.list_objects('ReviewRecord')==[]
        assert cs.receipt(actor,'bad-reason')['state']=='known_failure'


@pytest.mark.parametrize('shape',['index-outside','check-missing','completed-with-remaining','foreign-receipt','finding-outside','finding-unlinked'])
def test_mechanical_overclaims_have_one_rejection_outcome(ws,shape):
    """S05/S06: deterministic mapping errors; no claim to detect bad reasoning."""
    native(ws); cs,_,refs,snapshot,_=seed(ws)
    request=commission(snapshot,refs)
    if shape=='finding-unlinked':
        request['review_requirements'][0]['required_checks'].append('A second independent check')
    with delegated_task(ws,'coordinator',call('task',request,'bad-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[receipt]); item=value['items'][0]
        expected=(ActionRejected,ValidationError)
        if shape=='index-outside':
            item['check_results'][0]['requirement_index']=999;item['checked_requirement_indexes']=[999]
        elif shape=='check-missing':
            item['check_results']=[];item['checked_requirement_indexes']=[]
        elif shape=='completed-with-remaining':
            item['check_results'][0]['remaining']='Unfinished required part'
        elif shape=='foreign-receipt':
            other=Actor('someone-else','reviewer','another-task')
            item['observations'][0]['receipt_id']=cs.read_context(other,refs['claim'])['receipt_id']
        else:
            item['findings']=[{'finding_type':'confirmed_defect','locator_state':'located','description':'Fixture defect',
                'impact':'Assigned criterion','needed_outcome':'Resolve actual discrepancy',
                'requirement_index':999 if shape=='finding-outside' else 1,
                'observation_indexes':[0], 'basis_kind':'supplied_content'}]
            if shape=='finding-unlinked':
                item['execution_state']='running'
                item['check_results'].append({'requirement_index':1,'execution_state':'partial',
                    'result':'No supporting observations yet.','observation_indexes':[], 'remaining':'Further evidence required.'})
        with pytest.raises(expected):
            cs.submit_review(actor,'overclaim',value,{})
        assert cs.list_objects('ReviewRecord')==[]


def test_operation_identity_and_owner_correction_preserve_history(ws):
    """S07: existing operation digest/receipt and supersession, no new ledger."""
    native(ws);cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'idempotent-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[receipt])
        first=cs.submit_review(actor,'same-operation',value,{})
        assert cs.submit_review(actor,'same-operation',value,{})==first
        changed=deepcopy(value);changed['items'][0]['reason']='Changed public explanation.'
        with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
            cs.submit_review(actor,'same-operation',changed,{})
        with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
            cs.submit_review(Actor('another-reviewer','reviewer','another-task'),'same-operation',value,{})
        replacement=cs.submit_review(actor,'new-known-correction',changed,{})
        correction=cs.supersede_review(actor,'correct-own',first['result']['review_ref'],
            replacement['result']['review_ref'],'Explicit corrected explanation.')
        assert correction['ok']
        assert len(cs.list_objects('ReviewRecord'))==2
        assert cs.read(first['result']['review_ref'])['payload']['items'][0]['reason']==value['items'][0]['reason']
        assert cs.list_objects('ReviewSupersession')


@pytest.mark.parametrize('after_commit',[False,True])
def test_save_response_loss_uses_actual_receipt_and_one_business_commit(ws,monkeypatch,after_commit):
    """S08: native local idempotent reentry is allowed; no model is invoked."""
    native(ws);cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'response-loss-task')) as (_,actor):
        receipt=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[receipt])
        original=cs.operation
        def interrupted(*args,**kwargs):
            if after_commit:
                original(*args,**kwargs)
            raise RuntimeError('Synthetic local response loss')
        monkeypatch.setattr(cs,'operation',interrupted)
        with pytest.raises(RuntimeError,match='Synthetic local response loss'):
            cs.submit_review(actor,'response-loss',value,{})
        monkeypatch.setattr(cs,'operation',original)
        actual=cs.receipt(actor,'response-loss')
        assert actual['state']==('known_success' if after_commit else 'unknown')
        assert len(cs.list_objects('ReviewRecord'))==(1 if after_commit else 0)
        if after_commit:
            recovered=cs.submit_review(actor,'response-loss',value,{})
            assert recovered['result']['review_ref']==cs.list_objects('ReviewRecord')[0]['ref']
            assert len(cs.list_objects('ReviewRecord'))==1
