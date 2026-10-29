import json
import httpx
import pytest
from report_agent.content_tasks import delegated_task
from report_agent.workspace import Workspace
from report_agent.deep_models import configured_model
from report_agent.model_recovery import activate_recovery, recovery_block
from report_agent.token_budget import TokenBudget, token_budget
from test_transport_observation import use_mock, close
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call

@pytest.mark.asyncio
async def test_v4_reviewer_500_raw_no_usage_is_not_replayed_and_holds_remain(case,monkeypatch,tmp_path):
    cs,_,criteria,_=prepared(case)
    manifest={**cs.store.manifest,'context_policy':'stateful-tools-v2','history_projection_profile':'exact-history-v1',
        'review_plan_contract':'optional-v1','context_projection':'review-materials-v2','tool_discovery_profile':'agent-search-v2'}
    cs.store.set('manifest',manifest)
    activate_recovery(cs.store,authorization='synthetic only',version=2)
    monkeypatch.setenv('REPORT_SDK_RETRIES','0');monkeypatch.setenv('REPORT_CONNECT_RETRIES','0')
    monkeypatch.setenv('REPORT_REASONING_EFFORT','high')
    for suffix,value in [('MODEL','deepseek-v4.1-flash'),('BASE_URL','https://offline.invalid/v1'),('API_KEY','fake')]:
        monkeypatch.setenv('REPORT_REVIEWER_'+suffix,value)
    model=configured_model(cs.store,'reviewer');model.root_async_client.max_retries=0;model.root_client.max_retries=0
    sent=[]
    def fail(request):
        sent.append(request.content)
        return httpx.Response(500,json={'error':{'message':'synthetic unavailable'}})
    await use_mock(model,fail)
    ledger=TokenBudget(tmp_path/'synthetic-budget.db',50000000,{'deepseek-v4.1-flash':2000000})
    old_text=ledger.reserve('deepseek-v4.1-flash')
    try:
        with delegated_task(Workspace(cs.store),'coordinator',review_call(criteria)) as (_,actor):
            before_task=cs.read({'type':'DelegatedTask','id':actor.task_id,'version':1})
            with token_budget(ledger),pytest.raises(Exception):
                await model.ainvoke('synthetic reviewer input')
            assert len(sent)==1
            first=ledger.snapshot(); assert first['reserved_or_unknown_upper_bounds']==4000000
            with cs.store.read_only() as db:
                recovery={k:json.loads(v) for k,v in db.execute("select key,value from state where key like 'model_recovery_call:%'") if json.loads(v).get('role')=='reviewer'}
            assert len(recovery)==1
            record=next(iter(recovery.values()))
            assert record['state']=='response_received' and record['raw']['status']==500
            with token_budget(ledger),pytest.raises(Exception) as caught:
                await model.ainvoke('synthetic reviewer input')
            assert recovery_block(caught.value) is not None
            assert len(sent)==1 and ledger.snapshot()==first
            assert cs.read({'type':'DelegatedTask','id':actor.task_id,'version':1})==before_task
            with ledger.connect() as db:
                assert db.execute('select state,reserved from attempts where id=?',(old_text,)).fetchone()==('reserved',2000000)
            assert not cs.list_objects('ReviewRecord')
        import hashlib, importlib.util
        spec=importlib.util.spec_from_file_location('resume_host_guards',str(__import__('pathlib').Path(__file__).parent / 'fixtures' / 'resume_host_guards.py'))
        assert hashlib.sha256(__import__('pathlib').Path(spec.origin).read_bytes()).hexdigest() == '43516f41f8ce6ed106b6eed273fae1616f4fbae256b6302ddda070a70b241d21'
        guards=importlib.util.module_from_spec(spec);spec.loader.exec_module(guards)
        old_raw=hashlib.sha256(sent[0]).hexdigest();old_canonical=guards.canonical_wire_sha256(sent[0])
        fence_hits=[]
        async def fence(request):
            fence_hits.append(1)
            guards.guard_unknown_wire(request,old_raw,old_canonical)
        model.http_async_client.event_hooks['request'].insert(0,fence)
        task_id=actor.task_id
        resume={'name':'task','id':'new-review-call','args':{'subagent_type':'reviewer','description':'Continue the original review.','resume_content_task_id':task_id}}
        with delegated_task(Workspace(cs.store),'coordinator',resume) as (_,same):
            assert same.task_id==task_id
            assert cs.read({'type':'DelegatedTask','id':task_id,'version':1})==before_task
            with token_budget(ledger),pytest.raises(Exception):
                await model.ainvoke('synthetic reviewer input')
            assert fence_hits==[1] and len(sent)==1 and ledger.snapshot()==first
            assert {k:cs.store.get(k) for k in recovery}==recovery
        from copy import deepcopy
        from report_agent.errors import ActionForbidden
        for mutation in ('role','snapshot','criteria','plugin'):
            bad=deepcopy(resume);bad['id']='bad-'+mutation
            if mutation=='role':bad['args']['subagent_type']='writer'
            if mutation=='snapshot':bad['args']['review']={'deliverable':{'kind':'deliverable','operation_id':'other'},'standards':{'kind':'criteria','criterion_refs':criteria},'scope':{'kind':'whole_content'}}
            if mutation=='criteria':bad['args']['review']={'deliverable':{'kind':'deliverable','operation_id':'published'},'standards':{'kind':'criteria','criterion_refs':criteria[:1]},'scope':{'kind':'whole_content'}}
            if mutation=='plugin':bad['args']['supervision_plugin']='task-checks-v1'
            with pytest.raises(ActionForbidden):
                with delegated_task(Workspace(cs.store),'coordinator',bad):pass
        assert cs.read({'type':'DelegatedTask','id':task_id,'version':1})==before_task
    finally:
        await close(model)
