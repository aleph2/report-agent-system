"""Native write registration, error feedback and mechanical replay proof."""
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.repetition_guard import KnownWriteRepetition
from test_bounded_review import Model
from test_deep_runtime import Driver, call, observation
from test_hierarchical_content import seed
from test_native_operation_identity import activate
from test_native_write_identity import dispatch, heading
from test_task_supervision import ws, offline
from test_text_work import writer_call


def registered(workspace, role):
    return {getattr(t, 'name', None) or t.__name__: t
            for t in deep_runtime.business_tools(workspace, role, None, Model('unused'))}


async def test_native_replay_proof_resolves_persisted_call_but_never_coalesces_new_intent(ws):
    activate(ws)
    raw = call('commit_objects', heading(), 'persisted-call')
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        result = await dispatch(registered(ws, 'writer')['commit_objects'], raw['id'], raw['args'])
        guard = KnownWriteRepetition(ws, 'writer')
        proof = guard.trusted(actor, raw)
        assert proof is not None and proof['response'] == result
        assert 'operation_id' not in raw['args']
        prepared = {'key': (actor.id, 'invocation', 'instructions', 'human'), 'proof': proof}
        guard.after_model(prepared, SimpleNamespace(result=[AIMessage('', id='same', tool_calls=[raw])]))
        assert prepared['key'] in guard.armed
        guard.armed.clear()
        fresh = {**raw, 'id': 'new-intent'}
        guard.after_model(prepared, SimpleNamespace(result=[AIMessage('', id='new', tool_calls=[fresh])]))
        assert not guard.armed and guard.trusted(actor, fresh) is None


async def test_boundary_reports_same_system_id_as_stored_atomic_failure(ws):
    seed(ws)
    activate(ws)
    def inspect_failure(messages):
        failed = observation(messages, 'freeze_snapshot')
        assert failed['receipt_id'].startswith('native:freeze_snapshot:')
        return AIMessage('', tool_calls=[call('get_operation_receipt',
            {'operation_id': failed['receipt_id']}, 'query-failure')])
    def inspect_receipt(messages):
        receipt = observation(messages, 'get_operation_receipt')
        assert receipt['state'] == 'known_failure'
        assert receipt['response']['receipt_id'].startswith('native:freeze_snapshot:')
        return AIMessage('Known failure retained; no acceptance.')
    driver = Driver(coordinator=[AIMessage('', tool_calls=[call('freeze_snapshot', {
        'root_ref': {'type': 'ContentNode', 'id': 'missing', 'version': 1},
        'refs': [{'type': 'ContentNode', 'id': 'missing', 'version': 1}]}, 'failed-freeze')]),
        inspect_failure, inspect_receipt])
    result = await deep_runtime.run_report(ws, lambda role: Model('unused') if role == 'text_tool' else driver(role))
    assert result['last_error'] is None, result


def test_native_bounded_reviewer_registration_keeps_legacy_reviewer_filter(ws):
    activate(ws)
    functions = registered(ws, 'reviewer')
    assert 'submit_review' not in functions
    assert 'correct_own_review' not in functions
    assert 'perform_assigned_review' in functions
