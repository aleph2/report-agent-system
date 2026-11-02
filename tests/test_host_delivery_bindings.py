"""AC9: final moved controls keep request, instruction and provenance bindings.

Real TaskContext/BusinessBoundary/AgentPromptBoundary, SDK serializer and mock
transport; no service calls. Existing fixtures supply authentic saved scopes.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.deep_models import GLMChatOpenAI
from report_agent.deep_runtime import BusinessBoundary
from report_agent.hierarchical_tools import content_tools, role_prompt
from report_agent.live_messages import tool_binding, validate_wire
from report_agent.model_recovery import canonical_input
from report_agent.native_operation_tools import native_write_tools
from report_agent.prompt_provenance import (AgentPromptBoundary, PromptCompositionError,
    admit_prompt_request, append_declared_system, observe_prompt_request)
from report_agent.task_context import TaskContext
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_request_state_delivery_regression import encoded, live_packet, wire_text


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        pytest.fail('AC9 is offline; only SDK MockTransport is permitted')
    monkeypatch.setattr(socket.socket, 'connect', refused)


@contextmanager
def commission(case, role):
    if role == 'coordinator':
        from test_co_review_message import setup_message
        cs, _, value, *_ = setup_message(case)
        def task(description: str, subagent_type: str) -> str:
            """Native delegation fixture; validation must not execute this task."""
            raise AssertionError('This test validates binding, not business execution')
        yield Workspace(cs.store), [StructuredTool.from_function(task)], value, cs
    else:
        from test_review_message_entry import setup, assignment, bound
        from test_review_message import message
        cs, output, criteria = setup(case)
        with bound(cs, assignment(output, criteria)) as (ws, _, _):
            tools = native_write_tools(ws, role, [t for t in content_tools(ws, role)
                if t.__name__ == 'submit_review'])
            yield ws, tools, message(), cs


def change_tail(wire, change):
    changed = deepcopy(wire)
    index, packet = live_packet(changed)
    change(packet)
    changed['messages'][index]['content'] = '[host-observations]\n' + encoded(packet)
    return changed


class Invocation(SimpleNamespace):
    def override(self, **values):
        return Invocation(**{**vars(self), **values})


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
@pytest.mark.parametrize('strict', [False, True])
async def test_final_offer_matches_current_system_and_moved_controls_and_refuses_stale_wire(case, monkeypatch, role, strict):
    from report_agent import task_context
    from report_agent.deepseek_strict import StrictCodec
    original_exact = task_context.exact_task_context
    budget = {'execution_resources': {'reserved_http_attempts': 0},
              'execution_token_resources': {'recorded_tokens': 0}}
    monkeypatch.setattr(task_context, 'exact_task_context', lambda ws, r: {
        **original_exact(ws, r), **deepcopy(budget)})
    with commission(case, role) as (ws, tools, value, cs):
        ws.store.set('context_policy', 'stateful-tools-v1')
        wires, canonical, answers, encoded_arguments = [], [], [], []
        tool_name = 'task' if role == 'coordinator' else 'submit_review'
        async def admit(request):
            admit_prompt_request(request)
            observe_prompt_request(request, ws.store, role)
        async def transport(request):
            wire = json.loads(request.content)
            # This is the active final offer used by the real adapter, not a
            # reconstructed test offer or a modified store receipt.
            validate_wire(wire, strict=strict)
            wires.append(wire)
            canonical.append(canonical_input(wire))
            for corrupt in (
                change_tail(wire, lambda p: p['moved_blocks'][0].update(text='tampered current scope')),
                change_tail(wire, lambda p: p.update(actor_id='another-actor')),
                change_tail(wire, lambda p: p['moved_blocks'].reverse()),
            ):
                with pytest.raises(PromptCompositionError, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
                    validate_wire(corrupt, strict=strict)
            removed = deepcopy(wire)
            removed['messages'].pop()
            with pytest.raises(PromptCompositionError, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
                validate_wire(removed, strict=strict)
            changed_schema = deepcopy(wire)
            next(t for t in changed_schema['tools'] if t['function']['name'] == tool_name)['function']['description'] += ' changed'
            with pytest.raises(PromptCompositionError, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
                validate_wire(changed_schema, strict=strict)
            only_counters = change_tail(wire, lambda p: p['current_execution_observations'].update(
                execution_resources={'reserved_http_attempts': 777}, execution_token_resources={'recorded_tokens': 888}))
            validate_wire(only_counters, strict=strict)  # Semantic offer excludes only the two counters.
            if len(wires) == 3:
                with pytest.raises(PromptCompositionError, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
                    validate_wire(wires[0], strict=strict)
            call = {'id': f'ac9-{role}-{len(wires)}', 'type': 'function', 'function': {
                'name': tool_name, 'arguments': json.dumps(encoded_arguments[-1])}}
            return httpx.Response(200, request=request, json={'id': 'offline-ac9', 'object': 'chat.completion',
                'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
                    'message': {'role': 'assistant', 'content': '', 'tool_calls': [call]}}],
                'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport), event_hooks={'request': [admit]}) as client:
            model = GLMChatOpenAI(model='deepseek-flash', api_key='offline-only',
                base_url='https://offline.invalid/beta' if strict else 'https://offline.invalid/v1', http_async_client=client,
                deepseek_strict=strict, use_responses_api=False, max_retries=0, disable_streaming=True)
            try:
                for turn in range(3):
                    budget['execution_resources']['reserved_http_attempts'] = turn
                    budget['execution_token_resources']['recorded_tokens'] = turn * 10
                    # First two assemblages differ only in volatile counters
                    # and local offer nonce. Third changes semantic controls.
                    label = 'same-controls' if turn < 2 else 'new-controls'
                    history = [HumanMessage(content='Use the exact current authorized scope and genuine prior reads.')]
                    request = ModelRequest(model=model, tools=tools, messages=history, state={'messages': history},
                        system_message=SystemMessage(content=role_prompt(role, interface_profile='review-interfaces-v4')))
                    async def business(changed):
                        async def declared(bound):
                            bound = append_declared_system(bound, encoded({'current_review_plan': label}),
                                'native_todos/current_child_state')
                            async def sdk(outgoing):
                                function = next(convert_to_openai_tool(t)['function'] for t in outgoing.tools
                                                if getattr(t, 'name', None) == tool_name)
                                encoded_arguments.append(StrictCodec(function).encode(value) if strict else value)
                                answer = await model.bind_tools(outgoing.tools).ainvoke([
                                    outgoing.system_message, *outgoing.messages])
                                return ModelResponse(result=[answer])
                            return await AgentPromptBoundary(ws, role).awrap_model_call(bound, sdk)
                        return await BusinessBoundary(ws, role).awrap_model_call(changed, declared)
                    response = await TaskContext(ws, role).awrap_model_call(request, business)
                    answer = next(m for m in response.result if getattr(m, 'tool_calls', None))
                    answers.append(answer)
                    call = answer.tool_calls[0]
                    with tool_binding(ws, role, Invocation(tool_call=call, state={'messages': [answer]})) as accepted:
                        assert accepted.tool_call['name'] == tool_name
                    if turn:
                        forged = answer.model_copy(update={'additional_kwargs': {
                            **answer.additional_kwargs, 'message_contract_offer': answers[0].additional_kwargs['message_contract_offer']}})
                        with pytest.raises(Exception, match='MESSAGE_CONTRACT_CALL_UNBOUND'):
                            with tool_binding(ws, role, Invocation(tool_call=call, state={'messages': [forged]})):
                                pytest.fail('An old offer cannot authenticate this response/call')
                assert len(wires) == 3
                assert canonical[0] == canonical[1], 'Local offer nonce must not become canonical wire salt'
                assert canonical[1] != canonical[2], 'Changed semantic moved blocks remain in recovery identity'
                assert wires[0]['messages'][0] == wires[1]['messages'][0] == wires[2]['messages'][0]
                assert all(live_packet(wire)[0] == len(wire['messages']) - 1 for wire in wires)
                assert len({a.additional_kwargs['message_contract_offer'] for a in answers}) == 3
                assert not cs.list_objects('ReviewRecord'), 'Wire binding does not perform a check or save'
            finally:
                model.root_client.close()
                await model.root_async_client.close()


async def test_current_instruction_and_progress_receipts_capture_actual_final_moved_controls(case):
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate, release
    from report_agent.prompt_sources import load_prompt
    cs, *_ = case
    ws = Workspace(cs.store)
    ws.store.set('context_policy', 'stateful-tools-v2')
    ws.store.set('manifest', {**ws.store.manifest, 'execution_progress_policy': {
        'version': 1, 'window': 3, 'repeats': 2, 'after_notice': 2}})
    configure_report(ws.store, 'ac9-current-report')
    instruction = candidate(ws, text='CURRENT_INSTRUCTION_TAIL: preserve all uncertainty and original permissions.')
    release(ws, instruction)
    progress = load_prompt('repetition-notice') + '\nCURRENT_PROGRESS_NOTICE'
    references = {'episode_id': 'ac9-episode', 'notice_id': 'ac9-notice', 'family': 'fixture'}
    files = ['repetition-notice']
    wires = []
    async def admit(request):
        admit_prompt_request(request)
        observe_prompt_request(request, ws.store, 'coordinator')
    def transport(request):
        wires.append(json.loads(request.content))
        return httpx.Response(200, request=request, json={'id': 'offline-instruction', 'object': 'chat.completion',
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'Offline successful handler; quality not assessed.'}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport), event_hooks={'request': [admit]}) as client:
        model = GLMChatOpenAI(model='deepseek-flash', api_key='offline-only',
            base_url='https://offline.invalid/v1', http_async_client=client,
            max_retries=0, use_responses_api=False, disable_streaming=True)
        try:
            history = [HumanMessage(content='Apply the released instruction to this current request.')]
            request = ModelRequest(model=model, tools=[], messages=history, state={'messages': history},
                system_message=SystemMessage(content=role_prompt('coordinator', interface_profile='review-interfaces-v4')))
            async def declare(changed):
                changed = append_declared_system(changed, progress, 'execution_progress/repetition',
                                                  references=references, files=files)
                async def sdk(final):
                    return ModelResponse(result=[await model.ainvoke([final.system_message, *final.messages])])
                return await AgentPromptBoundary(ws, 'coordinator').awrap_model_call(changed, sdk)
            response = await TaskContext(ws, 'coordinator').awrap_model_call(request, declare)
            answer = next(m for m in response.result if m.type == 'ai')
            assert len(wires) == 1
            wire = wires[0]
            assert progress not in wire_text(wire['messages'][0])
            _, packet = live_packet(wire)
            block = next(b for b in packet['moved_blocks'] if b['source'] == 'execution_progress/repetition')
            assert block['text'] == progress and block['references'] == references
            assert block['files'] == files and block['placement'] == 'tail'
            offered = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_context_offered']
            assert len(offered) == 1
            saved = ws.store.get('prompt_context_snapshot:' + offered[0]['snapshot_id'])
            assert saved['scoped_instructions']['effective'] == [instruction]
            assert 'CURRENT_INSTRUCTION_TAIL' in encoded(saved['messages'])
            assert 'CURRENT_PROGRESS_NOTICE' in encoded(saved['messages'])
            outcomes = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_context_response_received']
            assert len(outcomes) == 1 and outcomes[0]['call_id'] == offered[0]['call_id']
            capture_event, = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_final_http_input']
            capture = ws.store.get(capture_event['capture_key'])
            source = next(s for s in capture['sources'] if s['source'] == 'execution_progress/repetition')
            assert source['references'] == references and source['files'] == files and source['placement'] == 'tail'
            state_source = next(s for s in capture['sources'] if s['source'] == 'task_context/current_server_bound_state')
            assert state_source['references']['instruction_refs'] == [instruction['ref']]
            fact, = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
                     if e['kind'] == 'prompt_response_fact']
            assert fact['completed'] is True and fact['call_id'] == capture['call_id']
            assert fact['purpose'] == 'coordinator' and fact['ai_message_id'] == answer.id
            assert fact['final_capture_refs'] == [capture_event['capture_key']]
            notice, = fact['notices']
            assert all(notice[key] == value for key, value in references.items())
            assert notice['capture_ref'] == capture_event['capture_key']
            assert notice['text_sha256'] == hashlib.sha256(progress.encode()).hexdigest()
            assert not any(e['kind'] == 'prompt_context_outcome_unknown' for e in ws.store.events())
        finally:
            model.root_client.close()
            await model.root_async_client.close()


async def test_local_offer_without_success_is_not_recorded_as_delivered_instruction_or_check(case):
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate, release
    from test_deep_runtime import Driver
    cs, *_ = case
    ws = Workspace(cs.store)
    ws.store.set('context_policy', 'stateful-tools-v2')
    ws.store.set('manifest', {**ws.store.manifest, 'execution_progress_policy': {
        'version': 1, 'window': 3, 'repeats': 2, 'after_notice': 2}})
    configure_report(ws.store, 'ac9-failed-current-report')
    instruction = candidate(ws, text='CURRENT_FAILED_REQUEST_INSTRUCTION')
    release(ws, instruction)
    history = [HumanMessage(content='Only actual delivery/response may produce completion evidence.')]
    request = ModelRequest(model=Driver()('coordinator'), tools=[], messages=history, state={'messages': history},
        system_message=SystemMessage(content=role_prompt('coordinator', interface_profile='review-interfaces-v4')))
    async def declared(changed):
        changed = append_declared_system(changed, 'CURRENT_UNSENT_PROGRESS', 'execution_progress/repetition')
        async def fail_before_http(outgoing):
            raise RuntimeError('synthetic failure before physical dispatch')
        return await AgentPromptBoundary(ws, 'coordinator').awrap_model_call(changed, fail_before_http)
    with pytest.raises(RuntimeError, match='synthetic failure before physical dispatch'):
        await TaskContext(ws, 'coordinator').awrap_model_call(request, declared)
    events = ws.store.events()
    offered = [e['data'] for e in events if e['kind'] == 'prompt_context_offered']
    unknown = [e['data'] for e in events if e['kind'] == 'prompt_context_outcome_unknown']
    assert len(offered) == len(unknown) == 1 and offered[0]['call_id'] == unknown[0]['call_id']
    assert not any(e['kind'] in {'prompt_context_response_received', 'prompt_final_http_input'} for e in events)
    facts = [ws.store.get(e['data']['capture_key']) for e in events if e['kind'] == 'prompt_response_fact']
    assert not any(fact['completed'] or fact['notices'] for fact in facts)
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('model_name,strict', [('glm-5.3', False), ('deepseek-flash', True)])
async def test_real_sdk_complete_tool_batch_precedes_current_host_controls_and_tail(case, tmp_path, model_name, strict):
    """Offline protocol shape, not proof that either service accepts the request."""
    from importlib.metadata import version
    from langgraph.prebuilt import ToolNode
    from report_agent.store import encode
    from test_native_task_error_boundary import native_node
    from test_request_state_delivery_regression import deliver
    cs, *_ = case
    ws = Workspace(cs.store)
    ws.store.set('context_policy', 'stateful-tools-v1')
    initial, _, _ = await deliver(ws, [HumanMessage(content='Keep exact tool-result associations and current authority.')])
    def read_fixture() -> str:
        """Return synthetic text for this offline batch-shape fixture only."""
        return 'Unchanged synthetic tool result.'
    tool = StructuredTool.from_function(read_fixture)
    reasoning = 'SYNTHETIC_REASONING_FIELD_CANARY_NOT_MODEL_GENERATED'
    action = AIMessage(content='', additional_kwargs={'reasoning_content': reasoning}, tool_calls=[
        {'name': tool.name, 'args': {}, 'id': f'prior-call-{i}', 'type': 'tool_call'} for i in range(2)])
    executed = await native_node(ToolNode([tool]), {'messages': [action]})
    assert len([m for m in executed['messages'] if m.type == 'tool']) == 2
    history = [*initial, action, *executed['messages']]
    ws.store.add_feedback('Current complete condition requires one new host frame after this tool batch.')
    captured = []
    def transport(request):
        wire = json.loads(request.content)
        captured.append(wire)
        return httpx.Response(200, request=request, json={'id': 'offline-shape', 'object': 'chat.completion',
            'model': model_name, 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'Offline shape response only.'}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = GLMChatOpenAI(model=model_name, api_key='offline-only',
            base_url='https://offline.invalid/beta' if strict else 'https://offline.invalid/v1',
            http_async_client=client, deepseek_strict=strict, max_retries=0,
            use_responses_api=False, disable_streaming=True)
        try:
            request = ModelRequest(model=model, tools=[tool], messages=history, state={'messages': history},
                system_message=SystemMessage(content=role_prompt('coordinator', interface_profile='review-interfaces-v4')))
            async def sdk(final):
                return ModelResponse(result=[await model.bind_tools(final.tools).ainvoke([
                    final.system_message, *final.messages])])
            async def final_boundary(projected):
                return await AgentPromptBoundary(ws, 'coordinator').awrap_model_call(projected, sdk)
            await TaskContext(ws, 'coordinator').awrap_model_call(request, final_boundary)
            assert len(captured) == 1
            wire = captured[0]
            messages = wire['messages']
            assert messages[0]['role'] == 'system' and sum(m['role'] == 'system' for m in messages) == 1
            position = next(i for i, m in enumerate(messages) if m.get('tool_calls'))
            prior = messages[position]
            assert prior['reasoning_content'] == reasoning
            assert [c['id'] for c in prior['tool_calls']] == ['prior-call-0', 'prior-call-1']
            results = messages[position + 1:position + 3]
            assert [m['role'] for m in results] == ['tool', 'tool']
            assert [m['tool_call_id'] for m in results] == ['prior-call-0', 'prior-call-1']
            assert all(m['content'] == 'Unchanged synthetic tool result.' for m in results)
            new_controls = [i for i, m in enumerate(messages) if wire_text(m).startswith('[host-state]')]
            assert new_controls[-1] > position + 2
            assert live_packet(wire)[0] == len(messages) - 1
            assert wire_text(messages[-1]).startswith('[host-observations]')
            assert 'input' not in wire and 'model' in wire and wire['tools'][0]['type'] == 'function'
            # Metadata only: do not export body text or even the synthetic
            # reasoning canary. This is not a server/provider acceptance test.
            metadata = {'model_fixture': model_name, 'strict': strict,
                'langchain_openai': version('langchain-openai'), 'openai': version('openai'),
                'system_content_type': type(messages[0]['content']).__name__,
                'roles': [m['role'] for m in messages], 'tool_call_ids': [m['tool_call_id'] for m in results],
                'host_state_positions': new_controls, 'tail_position': len(messages) - 1,
                'reasoning_field_preserved': True, 'service_acceptance_verified': False}
            (tmp_path / 'provider-shape.json').write_text(encode(metadata), encoding='utf-8')
        finally:
            model.root_client.close()
            await model.root_async_client.close()


def selection_proof_response(ws, offer, names, *, role):
    """Construct a persisted native-selection receipt, not a finalized offer."""
    from report_agent.store import digest
    from uuid import uuid4
    name = 'task' if role == 'coordinator' else 'submit_review'
    answer = AIMessage(content='', tool_calls=[{'id': 'unoffered-sensitive-call',
        'name': name, 'args': {}, 'type': 'tool_call'}])
    proof = {'actor_id': offer['owner'][1], 'task_id': offer['owner'][2],
             'names': names, 'calls_digest': digest(answer.tool_calls)}
    key = 'tool_selection_offer:' + uuid4().hex
    answer.additional_kwargs['report_tool_selection_offer'] = key
    return answer, proof, key


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
@pytest.mark.parametrize('fault', ['selected-unfinalized', 'missing-proof', 'foreign-root',
    'foreign-actor', 'foreign-task', 'mutated-calls', 'mixed-sensitive-calls'])
def test_unfinalized_offer_cannot_use_missing_foreign_or_conflicting_selection_proof(case, role, fault):
    from report_agent.live_messages import prepare_request, bind_response, _once
    from report_agent.errors import ActionRejected
    from report_agent.store import digest
    with commission(case, role) as (ws, tools, value, cs):
        ws.store.set('manifest', {**ws.store.manifest, 'tool_selection_mode': 'on'})
        request = ModelRequest(model=None, tools=tools, state={'messages': []},
            system_message=SystemMessage(role_prompt(role)), messages=[])
        _, offer = prepare_request(ws, role, request)
        assert offer is not None and 'prompt_call_id' not in offer
        name = 'task' if role == 'coordinator' else 'submit_review'
        answer, proof, key = selection_proof_response(ws, offer, [], role=role)
        if fault == 'selected-unfinalized':
            proof['names'] = [name]
        elif fault == 'foreign-root':
            offer = deepcopy(offer)
            offer['owner'][0] += '-another-workspace'
        elif fault == 'foreign-actor':
            proof['actor_id'] += '-another-actor'
        elif fault == 'foreign-task':
            proof['task_id'] = 'another-task' if proof['task_id'] is None else proof['task_id'] + '-another-task'
        elif fault == 'mutated-calls':
            answer.tool_calls[0]['args'] = {'unexpected': 'changed after proof'}
        elif fault == 'mixed-sensitive-calls':
            other = 'submit_review' if name == 'task' else 'task'
            answer.tool_calls.append({'id': 'selected-but-unbound-call', 'name': other,
                                      'args': {}, 'type': 'tool_call'})
            proof.update(names=[other], calls_digest=digest(answer.tool_calls))
        if fault != 'missing-proof':
            _once(ws.store, key, proof)
        before = deepcopy(cs.list_objects('DelegatedTask'))
        with pytest.raises(ActionRejected, match='MESSAGE_CONTRACT_OFFER_UNAVAILABLE'):
            bind_response(ws, offer, ModelResponse(result=[answer]))
        assert cs.list_objects('DelegatedTask') == before
        assert 'message_contract_offer' not in answer.additional_kwargs


@pytest.mark.parametrize('role', ['coordinator', 'reviewer'])
async def test_same_owner_persisted_omission_reaches_tool_not_offered_without_execution(case, role):
    from report_agent.live_messages import prepare_request, bind_response, _once
    with commission(case, role) as (ws, tools, value, cs):
        request = ModelRequest(model=None, tools=tools, state={'messages': []},
            system_message=SystemMessage(role_prompt(role)), messages=[])
        _, offer = prepare_request(ws, role, request)
        assert offer is not None and 'prompt_call_id' not in offer
        ws.store.set('manifest', {**ws.store.manifest, 'tool_selection_mode': 'on'})
        answer, proof, key = selection_proof_response(ws, offer, [], role=role)
        _once(ws.store, key, proof)
        before = deepcopy(cs.list_objects('DelegatedTask'))
        bind_response(ws, offer, ModelResponse(result=[answer]))
        async def must_not_execute(request):
            pytest.fail('An omitted sensitive call must not bind, register, dispatch or replay')
        result = await BusinessBoundary(ws, role).awrap_tool_call(Invocation(
            tool_call=answer.tool_calls[0], runtime=SimpleNamespace(state={'messages': [answer]})), must_not_execute)
        assert result.status == 'error' and result.tool_call_id == answer.tool_calls[0]['id']
        error = json.loads(result.content)
        assert error['code'] == 'TOOL_NOT_OFFERED' and error['execution_state'] == 'not_executed'
        assert cs.list_objects('DelegatedTask') == before
        assert 'message_contract_offer' not in answer.additional_kwargs


@pytest.mark.parametrize('native', [False, True], ids=['bounded-coordinator', 'native-coordinator'])
async def test_real_build_agent_final_boundary_includes_original_todo_in_same_sdk_call(tmp_path, monkeypatch, native):
    """Actual assembly/SDK wire, preserving Todo; no real endpoint or report."""
    from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT
    from langchain_core.messages import messages_from_dict
    from langchain_openai.chat_models.base import _convert_message_to_dict
    from report_agent import deep_runtime
    from report_agent.live_messages import semantic_messages
    from report_agent.prompt_provenance import _CALL, public_projection
    from report_agent.prompt_sources import native_reviewer
    from report_agent.store import digest
    from test_task_supervision import ws as native_fixture
    from test_decision_data import activate
    from test_selector_experiment_contract import configure
    from test_deep_runtime import Driver

    ws = native_fixture.__wrapped__(tmp_path)
    ws.store.set('knowledge_enabled', False)
    if native:
        configure(ws, 'off')  # Existing complete supported v4 profile, not a hand-built middleware list.
    else:
        activate(ws)  # The affected bounded-tool profile used by the R5 cases.
    assert native_reviewer(ws.store) is native
    wires = []
    async def admit(request):
        admit_prompt_request(request)
        observe_prompt_request(request, ws.store, 'coordinator')
    async def transport(request):
        call = _CALL.get()
        wires.append({'call_id':call['call_id'] if call else None,
            'purpose':call['purpose'] if call else None, 'body':json.loads(request.content)})
        return httpx.Response(200, json={'id':'offline-build-boundary', 'object':'chat.completion',
            'created':1, 'model':'deepseek-v4.1-flash-1017',
            'choices':[{'index':0, 'finish_reason':'stop', 'message':{
                'role':'assistant', 'content':'Offline assembly check; no report acceptance.'}}],
            'usage':{'prompt_tokens':1, 'completion_tokens':1, 'total_tokens':2}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport), event_hooks={'request':[admit]}) as client:
        model = GLMChatOpenAI(model='deepseek-v4.1-flash-1017', api_key='offline-only',
            base_url='https://offline.invalid/v1', http_async_client=client, deepseek_strict=False,
            use_responses_api=False, disable_streaming=True, max_retries=0)
        unused = Driver()
        try:
            graph = deep_runtime.build_agent(ws, lambda role: model if role == 'coordinator' else unused(role), None)
            result = await graph.ainvoke({'messages':[HumanMessage(content='Inspect this synthetic request only.')]})
            assert len(wires) == 1 and not unused.calls
            sent = wires[0]
            assert sent['call_id'] and sent['purpose'] == 'coordinator'
            body = sent['body']
            systems = [m for m in body['messages'] if m['role'] == 'system']
            assert len(systems) == 1
            content = systems[0]['content']
            blocks = content if isinstance(content, list) else [content]
            texts = [b.get('text','') if isinstance(b,dict) else b for b in blocks]
            assert sum(t.count(WRITE_TODOS_SYSTEM_PROMPT) for t in texts) == 1, 'Todo guidance must not be removed or duplicated'
            assert sum(t['function']['name'] == 'write_todos' for t in body['tools']) == 1

            offered = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_model_input'
                       and e['data'].get('call_id') == sent['call_id']]
            assert len(offered) == 1
            captured = ws.store.get(offered[0]['capture_key'])
            assert captured['call_id'] == sent['call_id'] and captured['purpose'] == 'coordinator'
            public = captured['public_input']
            original_messages = [SystemMessage(content=public['messages'][0]['content']),
                *messages_from_dict([{'type':m['type'], 'data':m} for m in public['messages'][1:]])]
            expected_messages = [_convert_message_to_dict(m) for m in original_messages]
            assert public_projection(body['messages']) == public_projection(expected_messages), 'Final boundary preceded a later middleware System change'
            assert public_projection(body['tools']) == public['tools']
            actor, = [part['references']['actor_id'] for part in captured['sources']
                      if part['source'] == 'task_context/current_server_bound_state' and part.get('references',{}).get('actor_id')]
            _, tail = live_packet(body)
            assert tail['actor_id'] == actor and tail['role'] == 'coordinator'
            final_refs = {e['data']['capture_key'] for e in ws.store.events() if e['kind'] == 'prompt_final_http_input'
                          and e['data'].get('call_id') == sent['call_id']}
            assert final_refs
            assert all(ws.store.get(ref)['public_input'] == public_projection(body) for ref in final_refs)
            answer = next(m for m in reversed(result['messages']) if isinstance(m, AIMessage))
            if native:
                offer = ws.store.get(answer.additional_kwargs['message_contract_offer'])
                assert offer['prompt_call_id'] == sent['call_id']
                assert offer['owner'][0] == str(ws.store.root.resolve()) and offer['owner'][1] == actor
                assert offer['request_messages_digest'] == digest(semantic_messages(body))
                directory, = [p for p in tail['moved_blocks'] if p['source'] == 'field_dictionary/current_request']
                assert json.loads(directory['text']) == offer['packet']
            else:
                assert 'message_contract_offer' not in answer.additional_kwargs  # Do not invent v4 offers for the bounded protocol.
        finally:
            model.root_client.close()
            await model.root_async_client.close()
