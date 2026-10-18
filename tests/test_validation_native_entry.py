"""Host admission and actual native new-turn behavior; no semantic acceptance."""
import importlib
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from test_deep_runtime import Driver


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')

    def denied(*args, **kwargs):
        pytest.fail('Provider/network forbidden in native-entry tests')

    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setattr(deep_runtime, 'configured_model', denied)


@pytest.fixture
def local(tmp_path):
    store = Store(tmp_path/'case')
    store.initialize({'goal': 'Check synthetic class B evidence; retain uncertainty.',
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': 'delegated-reviewer-v1',
        'sources': [{'id': 's', 'title': 'Synthetic rule', 'content': 'Class B allows 75 to 100.',
                     'coverage': 'complete'}]})
    return Workspace(store)


@pytest.fixture
def host(tmp_path, monkeypatch, local):
    area = Path(__file__).resolve().parents[1]/'.analysis/implementation-resumed-20261014'
    monkeypatch.syspath_prepend(str(area))
    harness = importlib.import_module('continue_full_chain_validation17')
    monkeypatch.setattr(harness, 'ROOT', tmp_path)
    monkeypatch.setattr(harness, 'CASE', tmp_path)
    out = tmp_path/'window'
    out.mkdir()
    (tmp_path/'.runs').mkdir()
    monkeypatch.setattr(harness, 'OUT', out)
    monkeypatch.setattr(harness, 'code_hashes', lambda: {'synthetic': 'bound'})
    monkeypatch.setattr(harness, 'load_mixed_services', lambda _: None)
    monkeypatch.setattr(harness, 'TokenBudget', lambda *args: SimpleNamespace(snapshot=lambda: {}))
    calls = []
    state = SimpleNamespace(next=('model',), interrupts=(), values={'messages': ['saved']},
                            config={'configurable': {'thread_id': 'report', 'checkpoint_id': 'saved'}})

    @asynccontextmanager
    async def graph(*args, **kwargs):
        async def get_state(config):
            assert config == {'configurable': {'thread_id': 'report'}}
            return state
        yield SimpleNamespace(aget_state=get_state)

    async def run(ws, **kwargs):
        calls.append(kwargs)
        ws.store.set('report_status', 'completed')

    monkeypatch.setattr(harness, 'project_agent', graph)
    monkeypatch.setattr(harness, 'run_report', run)
    pre = {'code_sha256': {'synthetic': 'bound'}, 'original_terminal_captures': {},
           'role_services': None, 'event_start_sequence': 0, 'authorized_maximum_tokens': 120000000,
           'protected_files': {}, 'objects_before_digest': digest(ContentStore(local.store).list_objects()),
           'budget_amendment': 'synthetic-already-applied'}

    def save():
        harness.base.save_json(out/'preflight.json', pre)
    save()
    return SimpleNamespace(harness=harness, state=state, pre=pre, save=save, calls=calls, out=out)


@pytest.mark.parametrize('mode,pending,interrupts,checkpoint,expected', [
    ('pending', False, False, True, 'PENDING_NATIVE_CONTINUATION_REQUIRED'),
    ('pending', True, True, True, 'PENDING_NATIVE_CONTINUATION_REQUIRED'),
    ('new_turn', True, False, True, 'TERMINAL_NATIVE_THREAD_REQUIRED'),
    ('new_turn', False, True, True, 'TERMINAL_NATIVE_THREAD_REQUIRED'),
    ('new_turn', False, False, False, 'EXISTING_NATIVE_THREAD_REQUIRED'),
    ('invalid', False, False, True, 'UNKNOWN_NATIVE_ENTRY_MODE'),
])
async def test_wrong_entry_never_registers_or_dispatches(host, mode, pending, interrupts, checkpoint, expected):
    host.state.next = ('model',) if pending else ()
    host.state.interrupts = ('pending-interrupt',) if interrupts else ()
    if not checkpoint:
        host.state.values = {}
        host.state.config['configurable'].pop('checkpoint_id')
    host.pre['native_mode'] = mode
    host.save()
    with pytest.raises(AssertionError, match=expected):
        await host.harness.execute(native_mode=mode)
    assert not host.calls and not (host.out/'started.json').exists()


async def test_unbound_new_turn_never_registers_or_dispatches(host):
    host.state.next = ()
    with pytest.raises(AssertionError, match='NATIVE_MODE_DIFFERS_FROM_PREFLIGHT'):
        await host.harness.execute(native_mode='new_turn')
    assert not host.calls and not (host.out/'started.json').exists()


@pytest.mark.parametrize('mode', ['pending', 'new_turn'])
async def test_bound_mode_uses_normal_entry_once_and_captures_truth(host, mode):
    if mode == 'new_turn':
        host.state.next = ()
        host.pre['native_mode'] = mode
    # The default pending path also accepts historical preflights without a mode field.
    host.save()
    await host.harness.execute(**({'native_mode': mode} if mode == 'new_turn' else {}))
    assert len(host.calls) == 1 and host.calls[0]['decision_only'] is False
    receipt = host.harness.base.read(host.out/'started.json')
    assert receipt['native_mode'] == mode
    assert ('payload=None' in receipt['entrypoint']) == (mode == 'pending')
    assert receipt['native']['checkpoint_id'] == 'saved'
    result = host.harness.base.read(host.out/'result.json')
    assert result['semantic_acceptance'] is False and result['http_attempts'] == 0
    with pytest.raises(AssertionError, match='CONTINUATION_ALREADY_REGISTERED_INSPECT_ONLY'):
        await host.harness.execute(native_mode=mode)
    assert len(host.calls) == 1


async def test_completed_real_graph_gets_new_project_view_without_losing_history(local):
    driver = Driver(coordinator=[AIMessage(content='Prior turn preserved; review incomplete.'),
                                AIMessage(content='New feedback observed; no acceptance claimed.')])
    first = await deep_runtime.run_report(local, driver)
    assert first['last_error'] is None, first
    async with deep_runtime.project_agent(local, driver) as agent:
        before = await agent.aget_state({'configurable': {'thread_id': 'report'}})
    assert before.values and not before.next and not before.interrupts
    old_messages = [m.model_dump() for m in before.values['messages']]
    old_checkpoint = before.config['configurable']['checkpoint_id']
    feedback = local.store.add_feedback('Synthetic factual clarification: existing authority remains unchanged.')
    second = await deep_runtime.run_report(local, driver)
    assert second['last_error'] is None, second
    async with deep_runtime.project_agent(local, driver) as agent:
        after = await agent.aget_state({'configurable': {'thread_id': 'report'}})
    assert after.config['configurable']['thread_id'] == 'report'
    assert after.config['configurable']['checkpoint_id'] != old_checkpoint
    assert not after.next and not after.interrupts
    # Framework HumanMessages may have id=None; do not collapse them into an ID map.
    now = [m.model_dump() for m in after.values['messages']]
    assert now[:len(old_messages)] == old_messages
    new_users = [m for m in after.values['messages'][len(old_messages):] if isinstance(m, HumanMessage)]
    assert len(new_users) == 1 and 'existing authority remains unchanged' in new_users[0].content
    actual = driver.calls[-1][2]
    assert any(m.content == 'Prior turn preserved; review incomplete.' for m in actual)
    assert feedback['id'] in str(actual) and 'existing authority remains unchanged' in str(actual)
    starts = [e['data'] for e in local.store.events() if e['kind'] == 'deep_run_started']
    assert starts[-1] == {'resume': False, 'native_checkpoint': True}
    assert local.store.get('content_final_review') is None
