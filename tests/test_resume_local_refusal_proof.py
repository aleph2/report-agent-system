import httpx
import pytest
from report_agent.deep_models import error_data
from report_agent.model_recovery import activate_recovery
from report_agent.request_budget import RequestBudgetExceeded, record_local_refusal
from report_agent.token_budget import TokenBudget, token_budget
from test_transport_observation import setup_model, use_mock, close, body

@pytest.mark.asyncio
async def test_sdk_local_host_refusal_is_known_unsent_without_extra_budget(tmp_path, monkeypatch):
    store,model=setup_model(tmp_path,monkeypatch,role='coordinator')
    model.root_async_client.max_retries=0; model.root_client.max_retries=0
    monkeypatch.setenv('REPORT_SDK_RETRIES','0')
    activate_recovery(store,authorization='fake only',version=2)
    sent=[]
    await use_mock(model,lambda request: (sent.append(1),httpx.Response(200,json=body()))[1])
    async def fence(request):
        error=RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')
        record_local_refusal(error,{'resume_reason':'proof_required'},guard_origin='resume_fence')
        raise error
    model.http_async_client.event_hooks['request'].insert(0,fence)
    ledger=TokenBudget(tmp_path/'budget.db',100,{'deepseek-v4.1-flash':40})
    held=ledger.reserve('deepseek-v4.1-flash');before=ledger.snapshot()
    try:
        with token_budget(ledger),pytest.raises(Exception) as caught:
            await model.ainvoke('new synthetic coordinator decision')
        assert error_data(caught.value)['message']=='HOST_TECHNICAL_FAILURE_PENDING'
        assert sent==[] and ledger.snapshot()==before
        with store.read_only() as db:
            import json
            rows=[json.loads(v) for (v,) in db.execute("select value from state where key like 'model_recovery_call:%'")]
        assert len(rows)==1 and rows[0]['state']=='local_admission_blocked'
        assert rows[0]['provider_outcome']=='not_dispatched'
        assert rows[0]['admission_proof']['admitted_http_attempts']==0
        assert rows[0]['admission_proof']['capacity_admission']['resume_reason']=='proof_required'
        with ledger.connect() as db:
            assert db.execute('select state,reserved from attempts where id=?',(held,)).fetchone()==('reserved',40)
    finally:
        await close(model)


def test_already_admitted_attempt_never_proves_unsent():
    from report_agent.request_budget import AdmissionTrace
    trace=AdmissionTrace();trace.accepted()
    error=RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')
    trace.rejected(error,{'resume_reason':'proof_required'},guard_origin='resume_fence')
    assert trace.not_dispatched_proof(error) is None


def test_other_exception_never_inherits_unsent_proof():
    from report_agent.request_budget import AdmissionTrace
    trace=AdmissionTrace();first=RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')
    trace.rejected(first,{'resume_reason':'proof_required'},guard_origin='resume_fence')
    assert trace.not_dispatched_proof(RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING')) is None
