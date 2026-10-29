from types import SimpleNamespace
from langchain_core.messages import AIMessage
from report_agent.deep_runtime import finish_native_run
from test_task_supervision import ws


def test_delegated_finish_records_existing_status_and_interrupt_semantics_without_dumping_messages(ws):
    ws.store.set('report_status','running')
    snapshot=SimpleNamespace(values={},next=(),interrupts=[])
    result={'messages':[AIMessage(content='Public status.',additional_kwargs={'reasoning_content':'SECRET_REASONING'})]}
    finish_native_run(ws,snapshot,result,delegated_review=True,native_enabled=True,hierarchical=True)
    assert ws.store.get('report_status')=='completed'
    assert ws.store.get('checkpoint_resume') is False
    assert ws.store.get('native_interrupts')==[]
    assert ws.store.get('agent_summary')=='Public status.'
    assert ws.store.events()[-1]['kind']=='deep_run_finished'
    assert 'SECRET_REASONING' not in str(ws.store.events()[-1])


def test_delegated_finish_preserves_attention_interrupt(ws):
    ws.store.set('report_status','running')
    item=SimpleNamespace(id='synthetic',value={'kind':'text_work_interrupt'})
    snapshot=SimpleNamespace(values={},next=('model',),interrupts=[item])
    finish_native_run(ws,snapshot,{'messages':[]},delegated_review=True,native_enabled=True,hierarchical=True)
    assert ws.store.get('checkpoint_resume') is True
    assert ws.store.get('report_status') in ('needs_attention','needs_human')


def test_shared_failure_sets_public_error_and_records_event(ws):
    from report_agent.deep_runtime import fail_native_run
    from report_agent.request_budget import RequestBudgetExceeded
    class Diagnostics:
        def record(self, error, phase): return {'diagnostic_id':'synthetic'}
    ws.store.set('report_status','running')
    fail_native_run(ws,RequestBudgetExceeded('HOST_TECHNICAL_FAILURE_PENDING'),Diagnostics())
    assert ws.store.get('report_status')=='failed'
    assert ws.store.get('report_error')['message']=='HOST_TECHNICAL_FAILURE_PENDING'
    assert ws.store.events()[-1]['kind']=='deep_run_error'
