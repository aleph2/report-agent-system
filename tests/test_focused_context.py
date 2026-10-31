"""Opt-in context projection: current controls plus exact owned recovery."""
import json
from copy import deepcopy
from collections import Counter

import pytest
import httpx
from langchain_core.messages import AIMessage, ToolMessage
from report_agent.task_context import TaskContext, read_observation
from report_agent.summary_recovery import capture, recovery_tool
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.store import encode
from test_hierarchical_content import ws, seed
from test_progress_retention import activate as v2, presented


def activate(ws):
    v2(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'context_projection': 'focused-v1'})


def capability_message():
    value = {'ok': True, 'receipt_id': 'business-observation', 'result': {
        'version': 'layout-fixture', 'engine_digest': 'unchanged-engine',
        'directory_refresh': {'available': False, 'requires': ['missing dependency']},
        'revision_budget': {'remaining': 2}, 'boundaries': 'No content rewrite.',
        'controls': {'properties': {
            'styles': {'$ref': '#/$defs/Styles'},
            'margin': {'type': 'number', 'default': 12, 'minimum': 0}},
            '$defs': {'Styles': {'description': '中文🙂限制。'*5000}}},
        'changes': ['Original change history']}}
    return ToolMessage(encode(value), name='read_layout_capabilities',
        tool_call_id='caps', id='caps-result')


def pair(message, args=None):
    return [AIMessage('', tool_calls=[{'id': message.tool_call_id, 'name': message.name,
        'args': args or {}, 'type': 'tool_call'}]), message]


def test_layout_projection_keeps_controls_and_recovers_exact_original(ws):
    activate(ws)
    middleware = TaskContext(ws, 'coordinator')
    original = capability_message()
    shown = middleware.bound_result(original)
    assert len(shown.content) < len(original.content) // 2
    value = json.loads(shown.content)
    assert value['result']['directory_refresh']['available'] is False
    assert value['result']['revision_budget'] == {'remaining': 2}
    assert value['result']['version'] == 'layout-fixture'
    assert 'styles' in shown.content and 'missing dependency' in shown.content
    ref = shown.additional_kwargs['report_observation_ref']
    chunks, offset = [], 0
    while True:
        page = read_observation(ws, 'coordinator', ref, offset, 6000)
        chunks.append(page['text'])
        if page['next_offset'] is None:
            break
        assert not page['complete_tool_result']
        offset = page['next_offset']
    assert ''.join(chunks) == original.content
    capture(ws, 'coordinator', pair(shown))
    saved = recovery_tool(ws, 'coordinator')()['observations'][0]
    assert saved['observation_ref'] == ref and saved['tool'] == original.name


async def test_short_recovery_pointer_survives_both_visible_and_cleared_history(ws):
    activate(ws); seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    original = ToolMessage('Exact object metadata', name='read_object_index',
        tool_call_id='index', id='index-result')
    messages = pair(original, {'offset': 0, 'limit': 20})
    capture(ws, 'coordinator', messages)
    context = await presented(middleware, messages)
    assert context['received_returns']['recent'][0]['call_id'] == 'index'
    assert context['received_returns']['recent'][0]['delivery']['compacted_message_range']['complete_tool_result']
    assert recovery_tool(ws, 'coordinator')()['total'] == 1
    changed = deepcopy(messages)
    changed[-1] = changed[-1].model_copy(update={'content': 'Preview only',
        'additional_kwargs': {'report_preview_cleared': True}})
    context = await presented(middleware, changed)
    assert context['received_returns']['recent'][0]['call_id'] == 'index'
    assert context['received_returns']['recent'][0]['observation_ref']


@pytest.mark.parametrize('change', ['status', 'range', 'body', 'call_args'])
async def test_same_call_id_does_not_certify_equivalent_delivery(ws, change):
    activate(ws); seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    original = ToolMessage('Exact requested data', name='read_object_index', tool_call_id='same')
    messages = pair(original, {'offset': 0, 'limit': 20})
    capture(ws, 'coordinator', messages)
    altered = deepcopy(messages)
    if change == 'status':
        altered[-1].status = 'error'
    elif change == 'range':
        altered[-1].additional_kwargs = {'report_observation_delivery': {'offset': 0, 'end': 3,
            'complete_tool_result': False}}
    elif change == 'body':
        altered[-1].content = 'Offloaded: /file/path'
    else:
        altered[0].tool_calls[0]['args']['offset'] = 20
    context = await presented(middleware, altered)
    assert context['received_returns']['recent'][0]['call_id'] == 'same'


def test_projection_is_opt_in_and_fixed_for_the_middleware_instance(ws):
    v2(ws)
    legacy = TaskContext(ws, 'coordinator')
    original = capability_message()
    assert legacy.bound_result(original) is original
    activate(ws)
    focused = TaskContext(ws, 'coordinator')
    ws.store.set('manifest', {k: v for k, v in ws.store.manifest.items() if k != 'context_projection'})
    assert focused.bound_result(original).content != original.content
    assert legacy.bound_result(original) is original


def test_projection_write_failure_retains_the_original_message(ws, monkeypatch):
    activate(ws)
    middleware = TaskContext(ws, 'coordinator')
    original = capability_message()
    import report_agent.task_context as context
    monkeypatch.setattr(context, 'save_observation', lambda *a: (_ for _ in ()).throw(OSError('disk failure')))
    assert middleware.bound_result(original) is original


def test_existing_execution_requires_explicit_migration_not_silent_projection(ws):
    v2(ws)
    ws.store.event('deep_model_request', {'role': 'coordinator'})
    ws.store.set('manifest', {**ws.store.manifest, 'context_projection': 'focused-v1'})
    with pytest.raises(ActionRejected, match='PROJECTION.*FRESH'):
        TaskContext(ws, 'coordinator')


@pytest.mark.parametrize('change', ['receiving_actor', 'receiving_task'])
async def test_record_scope_mismatch_never_hides_a_return(ws, change):
    activate(ws); seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    original = ToolMessage('Exact metadata', name='read_object_index', tool_call_id='scoped')
    messages = pair(original)
    records = capture(ws, 'coordinator', messages)
    records[0][change] = 'foreign-task'
    from report_agent.summary_recovery import key
    ws.store.set(key(ws, 'coordinator'), records)
    context = await presented(middleware, messages)
    assert context['received_returns']['recent'][0]['call_id'] == 'scoped'


async def test_failed_pointer_projection_falls_back_to_the_existing_index(ws, monkeypatch):
    activate(ws); seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    messages = pair(ToolMessage('Exact metadata', name='read_object_index', tool_call_id='index'))
    capture(ws, 'coordinator', messages)
    import report_agent.summary_recovery as recovery
    original = recovery.current_returns
    def fail(*args, **kwargs):
        if kwargs.get('focused'):
            raise RuntimeError('pointer projection failed')
        return original(*args, **kwargs)
    monkeypatch.setattr(recovery, 'current_returns', fail)
    context = await presented(middleware, messages)
    assert context['received_returns']['recent'][0]['call_id'] == 'index'
    assert any(e['kind'] == 'context_projection_gap' for e in ws.store.events())


async def test_capture_io_failure_does_not_clear_a_visible_return(ws, monkeypatch):
    activate(ws)
    middleware = TaskContext(ws, 'coordinator')
    messages = pair(capability_message())
    import report_agent.summary_recovery as recovery
    def fail(*args, **kwargs):
        raise OSError('capture unavailable')
    monkeypatch.setattr(recovery, 'capture', fail)
    before = deepcopy(messages)
    assert await middleware.abefore_model({'messages': messages}, None) is None
    assert messages == before


def test_focused_projection_does_not_weaken_original_integrity_or_owner_checks(ws):
    activate(ws)
    middleware = TaskContext(ws, 'coordinator')
    shown = middleware.bound_result(capability_message())
    modified = shown.model_copy(update={'content': shown.content.replace('missing dependency', 'available')})
    with pytest.raises(ActionRejected, match='CAPABILITY_PROJECTION_UNVERIFIED'):
        capture(ws, 'coordinator', pair(modified))
    ref = shown.additional_kwargs['report_observation_ref']
    record = ws.store.get('tool_observation:' + ref)
    record['text'] += 'tampered'
    ws.store.set('tool_observation:' + ref, record)
    with pytest.raises(ActionRejected, match='INTEGRITY'):
        read_observation(ws, 'coordinator', ref)


async def test_compacted_capability_directory_keeps_conditions_and_exact_old_version(ws):
    from langchain_core.messages import HumanMessage
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    activate(ws); seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    shown = middleware.bound_result(capability_message())
    capture(ws, 'coordinator', pair(shown))
    reopened = Workspace(Store(ws.store.root))
    context = await presented(TaskContext(reopened, 'coordinator'), [HumanMessage('Historical notes only.')])
    record = context['received_returns']['recent'][0]
    assert record['decision_metadata']['directory_refresh']['available'] is False
    assert record['decision_metadata']['revision_budget']['remaining'] == 2
    assert record['decision_metadata']['version'] == 'layout-fixture'
    assert 'styles' in record['decision_metadata']['controls']['directory']
    assert recovery_tool(reopened, 'coordinator')()['observations'][0]['observation_ref'] == record['observation_ref']


async def test_final_native_sdk_contains_focused_directory_and_current_state(ws):
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from test_prompt_native_sdk_inputs import completion
    activate(ws); seed(ws)
    models, wires, calls = {}, [], Counter()
    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        async def transport(request):
            body = json.loads(request.content)
            wires.append((role, body)); step = calls[role]; calls[role] += 1
            assert role == 'coordinator'
            if step == 0:
                return completion(request, '', ('read_layout_capabilities', {}))
            return completion(request, 'Capabilities observed; review remains incomplete.')
        client._transport = httpx.MockTransport(transport); client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result['last_error'] is None, result
        last = wires[-1][1]
        shown = json.loads(next(m['content'] for m in last['messages'] if m['role'] == 'tool'))
        assert 'directory' in shown['result']['controls']
        assert 'directory_refresh' in shown['result'] and 'revision_budget' in shown['result']
        assert shown['exact_recovery']['tool'] == 'read_tool_observation'
        record = ws.store.get('tool_observation:' + shown['observation_ref'])
        assert 'properties' in json.loads(record['text'])['result']['controls']
        assert len(shown['result']['controls']['directory']) == len(json.loads(record['text'])['result']['controls']['properties'])
        assert len(json.dumps(shown, ensure_ascii=False)) < len(record['text'])
        assert len(wires) == 2
    finally:
        for model in models.values():
            await model.root_async_client.close(); model.root_client.close()


async def test_later_message_cleanup_cannot_remove_the_current_exact_recovery_pointer(ws):
    from types import SimpleNamespace
    from langchain_core.messages import SystemMessage
    activate(ws); seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    messages = pair(ToolMessage('Exact original data', name='read_object_index', tool_call_id='later'))
    original = capture(ws, 'coordinator', messages)[0]
    request = SimpleNamespace(messages=messages, system_message=SystemMessage('Role authority.'))
    request.override = lambda **kw: SimpleNamespace(**{**request.__dict__, **kw})
    final = []
    async def later_handler(value):
        value.messages = [m.model_copy(update={'content': 'Body offloaded after context assembly.'})
            if isinstance(m, ToolMessage) else m for m in value.messages]
        final.append(value)
        return AIMessage('Synthetic output.')
    await middleware.awrap_model_call(request, later_handler)
    state = json.loads(final[0].system_message.content[-1]['text'])['current_task']
    pointer = state['received_returns']['recent'][0]
    assert pointer['observation_ref'] == original['observation_ref']
    assert pointer['sha256'] == original['sha256']
    assert pointer['recovery_index']['tool'] == 'read_summary_observations'


def test_pointer_projection_reduces_metadata_without_losing_delivery_controls(ws):
    from report_agent.summary_recovery import current_returns
    activate(ws)
    for number in range(10):
        message = ToolMessage('Exact return '+str(number), name='read_object_index',
            tool_call_id='page-'+str(number))
        capture(ws, 'coordinator', pair(message, {'offset': number, 'limit': 20}))
    legacy = current_returns(ws, 'coordinator')
    focused = current_returns(ws, 'coordinator', focused=True)
    assert len(encode(focused)) < len(encode(legacy))
    assert focused['total'] == legacy['total'] == 10
    for before, after in zip(legacy['recent'], focused['recent']):
        for field in ('observation_ref', 'sha256', 'status', 'selection', 'receiving_actor',
                      'receiving_task', 'invocation'):
            assert before.get(field) == after.get(field)
        for field in ('preview_cleared', 'original_delivery', 'compacted_message_range'):
            assert before['delivery'].get(field) == after['delivery'].get(field)
        assert after['delivery_is_historical']
    print(json.dumps({'legacy_state_chars': len(encode(legacy)),
        'focused_state_chars': len(encode(focused)), 'records': 10}))


async def test_native_compaction_reopen_and_late_cleanup_keep_exact_pointer_on_final_sdk(ws, monkeypatch):
    """One checkpoint execution, native compaction, reopened Store, actual SDK wire.

    Synthetic summary/replies and tool selection prove mechanics, not autonomy.
    Only the test trigger and a deliberately late cleanup are installed fixtures.
    """
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableLambda
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.working_summary import WorkingSummary
    from test_prompt_native_sdk_inputs import completion

    activate(ws); cs, _, _, _, _ = seed(ws)
    ws.store.add_feedback('Independent review remains pending; no acceptance has been established.')
    summary_inputs, cleaned, wires, models = [], [], [], {}
    original_workspace = ws

    async def summarize(prompt):
        summary_inputs.append(str(prompt))
        return AIMessage('Historical fixture notes only; original review is still incomplete.')

    class LateCleanupSummary(WorkingSummary):
        async def awrap_model_call(self, request, handler):
            async def cleanup_then_continue(value):
                if any(m.additional_kwargs.get('lc_source') == 'summarization' for m in value.messages):
                    # Run after TaskContext assembled its pointer. Do not alter
                    # persisted history or invent a product cleanup policy.
                    value = value.override(messages=[m.model_copy(update={
                        'content': 'Late fixture cleanup removed this visible tool body.'})
                        if isinstance(m, ToolMessage) else m for m in value.messages])
                    cleaned.append(True)
                return await handler(value)
            return await super().awrap_model_call(request, cleanup_then_continue)

    monkeypatch.setattr('report_agent.working_summary.working_summary', lambda model, store, role:
        LateCleanupSummary(model=RunnableLambda(summarize), store=store, role=role,
            trigger=('messages', 7), keep=('messages', 1), token_counter=lambda messages: len(messages),
            trim_tokens_to_summarize=None))

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(original_workspace.store, role)
        async def transport(request):
            body = json.loads(request.content); wires.append(body)
            assert role == 'coordinator'
            steps = [
                ('write_file', {'file_path': '/retained.txt', 'content': 'Exact qualifier 中文🙂. '*1200}),
                ('read_file', {'file_path': '/retained.txt'}),
                ('read_layout_capabilities', {})]
            step = len(wires)-1
            response = completion(request, 'No independent review has been completed.',
                steps[step] if step < len(steps) else None)
            data = json.loads(response.content)
            if step < len(steps):
                data['choices'][0]['message']['tool_calls'][0]['id'] += '-'+str(step)
            return httpx.Response(200, json=data)
        client._transport = httpx.MockTransport(transport); client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    config = {'configurable': {'thread_id': 'focused-compaction-reopen'}}
    try:
        async with deep_runtime.project_agent(ws, factory) as agent:
            for step in range(3):
                await agent.ainvoke({'messages': [HumanMessage('Retain exact evidence and unfinished review.')]} if step == 0 else None,
                    config, interrupt_after=['tools'])
            checkpoint = await agent.aget_state(config)
            assert checkpoint.next and len(wires) == 3 and not summary_inputs
        before = next(r for r in recovery_tool(ws, 'coordinator')()['observations'] if r['tool'] == 'read_file')
        original = ws.store.get('tool_observation:'+before['observation_ref'])
        reopened = Workspace(Store(ws.store.root))
        async with deep_runtime.project_agent(reopened, factory) as agent:
            resumed = await agent.aget_state(config)
            assert resumed.values['messages'] == checkpoint.values['messages']
            await agent.ainvoke(None, config)
            final_checkpoint = await agent.aget_state(config)
        assert len(summary_inputs) == len(cleaned) == 1 and len(wires) == 4
        assert 'Exact qualifier' in summary_inputs[0]
        assert any(m.additional_kwargs.get('lc_source') == 'summarization'
            for m in final_checkpoint.values['messages'])
        visible = encode(wires[-1]['messages'])
        assert 'Late fixture cleanup removed' in visible and 'Exact qualifier' not in visible
        marker = '{"current_task":'
        blocks = [m['content'] for m in wires[-1]['messages'] if m['role'] == 'system']
        text = '\n'.join(b if isinstance(b, str) else '\n'.join(x.get('text', '') for x in b) for b in blocks)
        context, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1].lstrip())
        assert context['received_returns']['projection'] == 'focused-v1'
        pointer = next(r for r in context['received_returns']['recent'] if r['tool'] == 'read_file')
        for field in ('call_id', 'observation_ref', 'sha256', 'receiving_actor', 'receiving_task', 'status', 'selection'):
            assert pointer[field] == before[field]
        for field in ('preview_cleared', 'original_delivery', 'compacted_message_range'):
            assert pointer['delivery'].get(field) == before['delivery'].get(field)
        assert pointer['delivery']['original_delivery']['complete_tool_result'] is False
        assert pointer['delivery']['compacted_message_range']['end'] == 6000
        assert pointer['recovery_index']['tool'] == 'read_summary_observations'
        assert pointer['delivery_is_historical'] and pointer['sha256'] == original['sha256']
        assert 'Independent review remains pending' in visible
        assert context['review_tasks']['total'] == 0 and not cs.list_objects('ReviewRecord')
        restored, offset = [], 0
        while True:
            page = read_observation(reopened, 'coordinator', pointer['observation_ref'], offset, 6000)
            restored.append(page['text'])
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        assert ''.join(restored) == original['text']
        assert original['owner'] == pointer['receiving_actor']
        assert recovery_tool(reopened, 'coordinator')()['total'] >= 3
    finally:
        for model in models.values():
            await model.root_async_client.close(); model.root_client.close()
