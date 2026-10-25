"""Portable input/save replay; hidden truth is NOT an autonomous model result."""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage,ToolMessage

from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver,invoke,observation

DATA=Path(__file__).parent/'fake_data/reviewer'
INPUTS=json.loads((DATA/'inputs.json').read_text(encoding='utf-8'))
TRUTH=json.loads((DATA/'hidden-oracles.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('fixture',[v for v in INPUTS if v['variant'] in
    {'correct','wrong_but_arithmetic_consistent','uncertain'}],ids=lambda v:v['case_id'])
async def test_two_domain_real_task_tools_preserve_independent_facts_criteria_and_scoped_save(tmp_path,fixture):
    """R01/R02/R05/R09/E01 I-layer, deliberately scripted verdict and decisions."""
    criterion_text='\n'.join(fixture['criteria'])
    sources=[{'id':s['id'],'title':'Synthetic authorized ledger',
        'content':json.dumps(s['rows'],ensure_ascii=False),'coverage':'complete'} for s in fixture['authorized_sources']]
    store=Store(tmp_path/'case');store.initialize({'goal':criterion_text,'sources':sources,
        'content_contract':'hierarchical-review-v1','review_entrypoint':'delegated-reviewer-v1',
        'review_execution_mode':'native-reviewer-v2'})
    ws=Workspace(store);cs=ContentStore(store);owner=actor_for('coordinator')
    imported=cs.import_inputs(owner,'inputs',[s['id'] for s in sources])['result']
    refs=cs.commit(owner,'deliverable',[
        {'client_key':'k','type':'Criterion','payload':{'requirement_refs':[imported['requirement_ref']],
            'purpose':'Verify the synthetic delivery','scope':'entire fixture','expected_outcome':criterion_text,
            'evidence_expectation':'Compare against authorized independent ledgers and rules.','allowed_limits':fixture['authority']}},
        {'client_key':'body','type':'ContentNode','payload':{'kind':'report',
            'body':{'text':json.dumps(fixture['deliverable'],ensure_ascii=False)},'qualifiers':{},'claim_kind':'fact'}}
        ])['result']['refs']
    members=[imported['requirement_ref'],*imported['source_refs'],*refs.values()]
    snap=cs.freeze(owner,'snapshot',refs['body'],members)['result']['snapshot_ref']
    request={'subagent_type':'reviewer','description':'Verify supplied deliverable using assigned standards and independent facts.',
        'review_snapshot_ref':snap,'review_requirements':[{'scope_id':'fixture','target_ref':refs['body'],
            'criterion_ref':refs['k'],'required_checks':fixture['criteria'],
            'required_materials':[{'requirement_index':i,'purpose':'Independent facts plus delivery',
                'refs':[refs['body'],*imported['source_refs']]} for i in range(len(fixture['criteria']))]}]}
    expected=TRUTH[fixture['case_id']]['verdict']
    def save(messages):
        # Assert actual delivered source and standards, not fake model assertions.
        assert all(c in '\n'.join(m.text for m in messages) for c in fixture['criteria'])
        reads=[json.loads(m.content) for m in messages if isinstance(m,ToolMessage) and m.name=='read_context']
        payloads=[obj['payload'] for read in reads for obj in read['result']['objects']]
        assert any(p.get('body',{}).get('text')==json.dumps(fixture['deliverable'],ensure_ascii=False) for p in payloads)
        assert len([p for p in payloads if p.get('source_id')])==len(sources)
        receipts=[v['receipt_id'] for v in reads]
        item={'target_ref':refs['body'],'criterion_ref':refs['k'],'scope':'fixture','scope_id':'fixture',
            'execution_state':'completed','verdict':expected,'reason':'Scripted protocol result; semantic evaluation is separate.',
            'observations':[{'locator':str(i),'observation':'Actual fixture read.','receipt_id':r} for i,r in enumerate(receipts)],
            'checked_requirement_indexes':list(range(len(fixture['criteria']))),
            'check_results':[{'requirement_index':i,'execution_state':'completed','result':'Scripted fixture comparison.',
                'observation_indexes':list(range(len(receipts))),'remaining':''} for i in range(len(fixture['criteria']))],
            'coverage':{'checked':fixture['criteria'],'unchecked':[],'blocked':[],'basis':'Exact input receipts'},'findings':[]}
        return invoke('submit_review',operation_id='fixture-save',review={'snapshot_ref':snap,'target_ref':snap,
            'scope':'fixture','criteria_refs':[refs['k']],'dependency_refs':imported['source_refs'],'items':[item]})
    saved=[]
    def finish(messages):
        result=observation(messages,'submit_review');assert result['ok'],result
        saved.append(result['result']['review_ref']);return AIMessage(content=json.dumps(result))
    driver=Driver(coordinator=[invoke('task',**request),AIMessage(content='Retained actual fixture outcome.')],
        reviewer=[invoke('read_task_assignment'),invoke('read_context',target_ref=refs['body']),
            *[invoke('read_context',target_ref=s) for s in imported['source_refs']],save,finish])
    result=await deep_runtime.run_report(ws,driver)
    assert result['last_error'] is None,result
    record=cs.read(saved[0]);assert record['payload']['items'][0]['verdict']==expected
    assert len(record['payload']['items'][0]['check_results'])==len(fixture['criteria'])
    assert cs.read(refs['body'])['payload']['body']['text']==json.dumps(fixture['deliverable'],ensure_ascii=False)


def test_synthetic_truth_is_independent_of_self_consistent_aggregate():
    """Fixture sanity only: arithmetic consistency does not remove fact errors."""
    for family,key in [('F_INV','available'),('F_TRAIN','completed')]:
        correct=next(v for v in INPUTS if v['case_id']==family+'-correct')
        wrong=next(v for v in INPUTS if v['case_id']==family+'-wrong_but_arithmetic_consistent')
        assert correct['deliverable'][key]==wrong['deliverable'][key]
        assert correct['deliverable']['rate']==wrong['deliverable']['rate']
        assert correct['deliverable']['rows']!=wrong['deliverable']['rows']
        assert TRUTH[correct['case_id']]['verdict']=='satisfied'
        assert TRUTH[wrong['case_id']]['verdict']=='not_satisfied'
    # Inputs and hidden calibration facts remain separate artifacts.
    assert not any('oracle_not_model_visible' in v or 'facts' in v for v in INPUTS)
