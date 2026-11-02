"""Large native search returns remain recoverable without weakening source receipts."""
import hashlib
import json
import traceback
from copy import deepcopy

import pytest

from langchain_core.messages import AIMessage

from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.decision_data import deliver_controls
from report_agent.errors import ActionRejected
from test_agent_result_delivery import force_offload, packet, reply
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, call
from test_hierarchical_content import seed
from test_task_supervision import ws


@pytest.mark.parametrize("reference_policy", [True, False])
async def test_large_search_native_offload_preserves_owned_exact_source(ws, monkeypatch, reference_policy):
    seed(ws)
    if reference_policy:
        activate(ws)
    ws.store.set('context_policy', 'stateful-tools-v2')
    manifest = ws.store.manifest
    literal = 'deepcut ' + 'x' * 7500 + ' END'
    source = {'id': 's', 'title': 'Synthetic', 'content': '\n'.join([literal]*10), 'coverage': 'partial'}
    ws.store.set('manifest', {**manifest, 'sources': [source],
        'execution_progress_policy': {'version':1,'window':64,'repeats':3,'after_notice':2},
        'review_interface_profile':'review-interfaces-v4', 'review_execution_mode':'native-reviewer-v2',
        'delegation_prompt_profile':'separate-description-v1', 'operation_identity_profile':'native-tool-runtime-v1',
        'context_policy':'stateful-tools-v2', 'context_projection':'review-materials-v1',
        'review_plan_contract':'work-units-v1', 'review_submission_contract':'task-scope-selectors-v1'})
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.executemany('insert into source_blocks values (?,?,?,?)',
            [('s', i, json.dumps({'page':i+1}), literal) for i in range(10)])
    force_offload(monkeypatch, True, threshold=2000)
    captured = []

    def inspect_search(messages):
        message = reply(messages, 'search_sources')
        shown = packet(message)
        original = ws.store.get('tool_observation:' + shown['observation_ref'])
        raw = json.loads(original['text'])
        assert original['owner'] == 'content:coordinator'
        assert original['sha256'] == hashlib.sha256(original['text'].encode()).hexdigest()
        assert raw['matches'][0]['text'] == literal and raw['total'] == 10
        assert message.artifact['source_material']['public_sha256'] == original['sha256']
        assert not shown['complete_original_in_decision']
        with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_OWNER_OR_CALL_MISMATCH'):
            deliver_controls(ws, 'coordinator', message.model_copy(update={'tool_call_id':'forged'}))
        altered = deepcopy(message.artifact)
        altered['report_public_delivery']['public_digest'] = '0'*64
        with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_VIEW_CHANGED'):
            deliver_controls(ws, 'coordinator', message.model_copy(update={'artifact':altered}))
        ws.store.set('tool_observation:' + shown['observation_ref'], {**original, 'text':'tampered'})
        try:
            with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_ORIGINAL_CHANGED'):
                deliver_controls(ws, 'coordinator', message)
        finally:
            ws.store.set('tool_observation:' + shown['observation_ref'], original)
        captured.append(shown['observation_ref'])
        return invoke('read_tool_observation', observation_ref=shown['observation_ref'],
            offset=0, characters=6000, field_path=['matches', 0, 'text'])

    parts = []
    def inspect_recovery(messages):
        restored = packet(next(m for m in reversed(messages) if getattr(m, 'name', None) == 'read_tool_observation'))
        assert restored['observation_ref'] == captured[0]
        assert restored['text'] == literal[len(''.join(parts)):len(''.join(parts))+6000]
        parts.append(restored['text'])
        if restored['next_offset'] is not None:
            assert restored['complete_field'] is False
            args = {'observation_ref':captured[0], 'offset':restored['next_offset'],
                    'characters':6000, 'field_path':['matches', 0, 'text']}
            return AIMessage(content='', tool_calls=[call('read_tool_observation', args, identity='recovery-next')])
        assert ''.join(parts) == literal and restored['complete_field'] is False
        return AIMessage(content='Selected text recovered; source completeness remains unproven.')

    failures = []
    def checked(fn):
        def call(messages):
            try:
                return fn(messages)
            except Exception:
                failures.append(traceback.format_exc())
                raise
        return call
    driver = Driver(coordinator=[invoke('search_sources', query='deepcut', limit=10, source_id='s'),
                                 checked(inspect_search), checked(inspect_recovery), checked(inspect_recovery)])
    result = await run_report(ws, driver)
    if result['last_error']:
        diagnostic = ws.store.root / 'diagnostics' / 'private' / (result['last_error']['diagnostic_id'] + '.json')
        failures.append(diagnostic.read_text() if diagnostic.exists() else 'no diagnostic')
    assert result['last_error'] is None, {'failures':failures, 'captured':len(captured), 'parts':len(parts)}
    assert len(captured) == 1
    assert not ContentStore(ws.store).list_objects('ReviewRecord')


def source_message(ws):
    from report_agent.catalog import Catalog
    from report_agent.hierarchical_tools import actor_for
    from report_agent.source_materials import issue, block_material
    from langchain_core.messages import ToolMessage
    seed(ws)
    ws.store.set('context_policy', 'stateful-tools-v2')
    value = Catalog(ws.store).read('s', 0, 1)
    text = json.dumps(value, ensure_ascii=False)
    receipt = issue(ws, actor_for('coordinator'), 'read_source_page', text, block_material(value))
    return ToolMessage(text, name='read_source_page', tool_call_id='source-call',
                       artifact={'source_material': receipt})


def test_small_source_without_profile_keeps_original_and_binds_only_server_metadata(ws):
    from report_agent.task_context import TaskContext
    from test_agent_result_delivery import wire_text
    message = source_message(ws)
    middleware = TaskContext(ws, 'coordinator')
    shown = middleware.bound_result(message)
    public = json.loads(shown.content)
    assert public['metadata'] == json.loads(message.content)
    assert public['complete_original_in_decision'] is True
    assert ws.store.manifest.get('decision_data_policy') is None
    assert shown.artifact['source_material'] == message.artifact['source_material']
    assert middleware.bound_result(shown) == shown
    wire = json.loads(wire_text(shown))
    assert json.loads(wire['content']) == public
    assert 'artifact' not in wire and 'additional_kwargs' not in wire
    assert ws.store.get('tool_observation:' + public['observation_ref'])['text'] == message.content


@pytest.mark.parametrize('change', ['text', 'receipt', 'source_metadata', 'tool'])
def test_binding_without_profile_refuses_tampered_original_or_receipt(ws, change):
    from report_agent.task_context import TaskContext
    message = source_message(ws)
    if change == 'text':
        message = message.model_copy(update={'content': 'Changed source contents'})
    elif change == 'tool':
        message = message.model_copy(update={'name': 'search_sources'})
    else:
        artifact = deepcopy(message.artifact)
        artifact['source_material']['receipt' if change == 'receipt' else 'public_sha256'] = '0' * 64
        message = message.model_copy(update={'artifact': artifact})
    with pytest.raises(ActionRejected, match='SOURCE_MATERIAL_'):
        TaskContext(ws, 'coordinator').bound_result(message)


@pytest.mark.parametrize('change', ['call', 'status', 'binding_hash', 'stored_text'])
def test_bound_source_without_profile_keeps_existing_delivery_integrity_checks(ws, change):
    from report_agent.task_context import TaskContext
    message = TaskContext(ws, 'coordinator').bound_result(source_message(ws))
    if change == 'call':
        message = message.model_copy(update={'tool_call_id': 'wrong-call'})
    elif change == 'status':
        message = message.model_copy(update={'status': 'error'})
    elif change == 'binding_hash':
        artifact = deepcopy(message.artifact)
        artifact['report_public_delivery']['public_digest'] = '0' * 64
        message = message.model_copy(update={'artifact': artifact})
    else:
        ref = message.artifact['report_public_delivery']['observation_ref']
        original = ws.store.get('tool_observation:' + ref)
        ws.store.set('tool_observation:' + ref, {**original, 'text': 'Changed stored original'})
    with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_'):
        deliver_controls(ws, 'coordinator', message)


def test_non_source_and_error_returns_without_profile_are_unchanged(ws):
    from report_agent.task_context import TaskContext
    from langchain_core.messages import ToolMessage
    seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    for message in (ToolMessage('Plain result', name='search_sources', tool_call_id='plain'),
                    ToolMessage('Error result', name='search_sources', tool_call_id='error', status='error')):
        assert middleware.bound_result(message) is message


@pytest.mark.parametrize('interrupted', [False, True], ids=['returned-child', 'protocol-interruption'])
async def test_current_real_profile_writer_sdk_reopens_same_owner_without_replaying_search(ws, monkeypatch, interrupted):
    """Actual SDK/ToolNode, synthetic source, current real host's explicit profile.

    Provider replies are scripted locally; this proves reuse mechanics, not that
    a live model will choose the most efficient continuation.
    """
    from collections import Counter
    import httpx
    from langchain_core.messages import HumanMessage
    from report_agent import deep_runtime
    from report_agent.errors import ActionForbidden
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.task_context import read_observation
    from report_agent.content_tasks import delegated_task
    from test_prompt_native_sdk_inputs import completion
    from test_deep_runtime import call
    from report_agent.prompt_sources import validate_report_prompt_profile, validate_review_plan_contract

    seed(ws)
    literal = 'deepcut ' + 'x' * 7500 + ' END'
    operational = dict(content_contract='hierarchical-review-v1', coverage_contract='object-coverage-v1',
        review_entrypoint='delegated-reviewer-v1', review_execution_mode='native-reviewer-v2',
        delegation_prompt_profile='separate-description-v1', context_policy='stateful-tools-v2',
        review_interface_profile='review-interfaces-v4', operation_identity_profile='native-tool-runtime-v1',
        content_input_profile='relation-endpoints-v2', report_expression_profile='reader-expression-v2',
        context_projection='review-materials-v1', history_projection_profile='exact-history-v1',
        tool_discovery_profile='agent-search-v2', review_submission_contract='task-scope-selectors-v1')
    ws.store.set('manifest', dict(operational, synthetic=True, goal='Continue the same saved producer work.',
        sources=[dict(id='s', title='Synthetic', content='\n'.join([literal]*10), coverage='partial')]))
    ws.store.set('knowledge_enabled', False)
    assert validate_report_prompt_profile(ws.store.manifest) == 'legacy-v1'
    assert validate_review_plan_contract(ws.store.manifest) is None
    for key in ('decision_data_policy', 'execution_progress_policy', 'report_prompt_profile'):
        assert key not in ws.store.manifest
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.executemany('insert into source_blocks values (?,?,?,?)',
            [('s', i, json.dumps({'page':i+1}), literal) for i in range(10)])
    force_offload(monkeypatch, True, threshold=2000)
    phase, models, steps, wires, refs = [0], {}, Counter(), [], []
    config = {'configurable': {'thread_id': 'report'}, 'recursion_limit':100}
    original_ws = ws

    def tool_value(body, name):
        value = next(m['content'] for m in reversed(body['messages'])
                     if m['role'] == 'tool' and m.get('name', name) == name)
        return json.loads(value if isinstance(value, str) else value[-1]['text'])

    def respond(request, text='', tool=None):
        result = completion(request, text, tool)
        data = json.loads(result.content)
        if tool:
            data['choices'][0]['message']['tool_calls'][0]['id'] += '-'+str(phase[0])
        return httpx.Response(200, json=data)

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(original_ws.store, role)
        async def transport(request):
            body = json.loads(request.content)
            wires.append((phase[0], role, body))
            step = steps[(phase[0], role)]; steps[(phase[0], role)] += 1
            if role == 'coordinator':
                if step == 0:
                    args = dict(subagent_type='writer', description='Continue retained source work; no acceptance claimed.')
                    if phase[0]:
                        from support.task_state_contract import moved_blocks
                        packets = [json.loads(part['text']) for part in moved_blocks(body['messages'])
                                   if part['source'] == 'field_dictionary/current_request']
                        dictionary, = [p for p in packets if p.get('tool')=='task' and 'resource_scopes' in p]
                        entries = [r for r in dictionary['resource_scopes'] if r.get('role')=='writer']
                        assert len(entries)==1
                        args['resume_task_scope'] = entries[0]['scope']
                    return respond(request, tool=('task',args))
                return respond(request, 'Retained source work; independent review remains outstanding.')
            assert role=='writer'
            if phase[0]==0:
                if step==0:
                    return respond(request, tool=('search_sources',dict(query='deepcut',limit=10,source_id='s')))
                shown=tool_value(body,'search_sources')
                saved=original_ws.store.get('tool_observation:'+shown['observation_ref'])
                assert json.loads(saved['text'])['matches'][0]['text']==literal
                assert shown['complete_original_in_decision'] is False
                refs.append(shown['observation_ref'])
                if interrupted:
                    raise httpx.RemoteProtocolError('Synthetic transport interruption after saved source return')
                return respond(request,'Source return retained; drafting remains incomplete.')
            if step==0:
                return respond(request, tool=('read_summary_observations',{}))
            if step==1:
                index=tool_value(body,'read_summary_observations')
                assert any(r['observation_ref']==refs[0] for r in index['observations'])
                return respond(request, tool=('read_tool_observation',dict(observation_ref=refs[0],
                    offset=0,characters=6000,field_path=['matches',0,'text'])))
            value=tool_value(body,'read_tool_observation')
            assert value['text']==literal[:6000] and value['complete_field'] is False
            return respond(request,'Recovered exact saved source portion; remaining reading is explicit.')
        client._transport=httpx.MockTransport(transport);client._mounts.clear()
        model_name='glm-5.3' if role in {'writer','layout'} else 'deepseek-v4.1-flash-1017'
        models[role]=GLMChatOpenAI(model=model_name,api_key='offline-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True,
            reasoning_effort='high',max_tokens=65536)
        return models[role]

    try:
        async with deep_runtime.project_agent(ws,factory) as agent:
            failure=None
            try:
                await agent.ainvoke({'messages':[HumanMessage('Retain source work.')]},config)
            except Exception as error:
                failure=error
            if not interrupted:
                assert failure is None, failure
            else:
                assert failure is not None or any(e['kind']=='content_delegation_failed' for e in ws.store.events())
        contents=ContentStore(ws.store)
        task,=contents.list_objects('DelegatedTask')
        owner='content:writer:'+task['ref']['id']
        saved=ws.store.get('tool_observation:'+refs[0])
        assert saved['owner']==owner
        original_reservation=ws.store.get('native_delegation:fixture-task-0')
        assert original_reservation['state']==('reserved' if interrupted else 'returned')
        reopened=Workspace(Store(ws.store.root));phase[0]=1
        async with deep_runtime.project_agent(reopened,factory) as agent:
            await agent.ainvoke({'messages':[HumanMessage('Continue the preserved producer work; do not restart.')]},config)
        tasks=ContentStore(reopened.store).list_objects('DelegatedTask')
        assert len(tasks)==1 and tasks[0]==task
        assert reopened.store.get('tool_observation:'+refs[0])==saved
        assert reopened.store.get('native_delegation:fixture-task-0')==original_reservation
        assert reopened.store.get('native_delegation:fixture-task-1')['state']=='returned'
        assert steps[(1,'writer')]==3
        assert len([m for _,role,body in wires if role=='writer'
                    for m in body['messages'] if m['role']=='tool' and m.get('tool_call_id')=='fixture-search_sources-0'])==1
        with delegated_task(reopened,'coordinator',call('task',dict(subagent_type='writer',description='Different producer'),identity='other-writer')):
            with pytest.raises(ActionForbidden,match='observation owner'):
                read_observation(reopened,'writer',refs[0],0,1)
    finally:
        for model in models.values():
            await model.root_async_client.close();model.root_client.close()
