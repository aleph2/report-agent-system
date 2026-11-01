"""Native selector ON/OFF contract, with no provider calls or report generation.

The scripted structured response substitutes only the provider response. The
installed LLMToolSelectorMiddleware must perform selection and native dispatch.
These tests establish mechanics, never the quality or economy of a chosen set.
"""
import json
import socket

import pytest
from langchain.agents.middleware.tool_selection import LLMToolSelectorMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda

from report_agent import deep_runtime
from report_agent.errors import ActionRejected
from report_agent.prompt_provenance import _CALL
from test_deep_runtime import Driver, ScriptedChat, invoke, observation
from test_task_supervision import ws


@pytest.fixture(autouse=True)
def no_external_socket(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    def denied(*args, **kwargs):
        pytest.fail('External sockets are forbidden; SDK cases must use MockTransport.')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def literals(schema):
    names = []
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('const'), str):
                names.append(value['const'])
            if isinstance(value.get('enum'), list):
                names.extend(x for x in value['enum'] if isinstance(x, str))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(schema)
    return list(dict.fromkeys(names))


class SelectionChat(ScriptedChat):
    def bind(self, **kwargs):
        # Native create_agent uses bind rather than bind_tools for an empty set.
        self.driver.bindings.setdefault(self.role, []).append([])
        return self

    def with_structured_output(self, schema, **kwargs):
        async def choose(messages, config=None):
            credential = _CALL.get()
            record = {'role': self.role, 'schema': schema, 'kwargs': kwargs,
                      'messages': list(messages), 'config': config,
                      'credential': credential}
            self.driver.selections.append(record)
            index = sum(r['role'] == self.role for r in self.driver.selections) - 1
            answers = self.driver.selection_scripts.get(self.role, [])
            answer = answers[index] if index < len(answers) else []
            if callable(answer):
                answer = answer(schema)
            return answer if isinstance(answer, dict) else {'tools': answer}
        return RunnableLambda(choose)


class SelectionDriver(Driver):
    def __init__(self, *, selections=None, **scripts):
        super().__init__(**scripts)
        self.selections = []
        self.selection_scripts = selections or {}

    def __call__(self, role):
        self.created.append(role)
        return SelectionChat(role=role, driver=self)


def configure(ws, mode):
    ws.store.set('manifest', {**ws.store.manifest, 'tool_selection_mode': mode,
        'context_policy': 'stateful-tools-v2', 'review_execution_mode': 'native-reviewer-v2',
        'review_interface_profile': 'review-interfaces-v4',
        'delegation_prompt_profile': 'separate-description-v1',
        'operation_identity_profile': 'native-tool-runtime-v1'})


def text(messages):
    return '\n'.join(m.text if hasattr(m, 'text') else str(m.get('content', '')) for m in messages)


@pytest.mark.parametrize('mode', ['off', 'on'])
async def test_selector_mode_uses_native_component_and_same_legal_catalog(ws, monkeypatch, mode):
    configure(ws, mode)
    native_calls = []
    original = LLMToolSelectorMiddleware.awrap_model_call
    async def spy(self, request, handler):
        native_calls.append((self, list(request.tools)))
        return await original(self, request, handler)
    monkeypatch.setattr(LLMToolSelectorMiddleware, 'awrap_model_call', spy)
    driver = SelectionDriver(selections={'coordinator': [['project_status']]},
                             coordinator=[AIMessage(content='End this offline decision.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Inspect current status.')]})
    actual = {f['name'] for f in driver.bindings['coordinator'][-1]}
    assert 'search_tools' not in actual
    if mode == 'off':
        assert not native_calls and not driver.selections
        assert {'project_status', 'task', 'ls'} <= actual
    else:
        assert len(native_calls) == 1 and len(driver.selections) == 1
        middleware, catalog = native_calls[0]
        assert middleware.max_tools is None and not middleware.always_include
        assert actual == {'project_status'}
        permitted = {t.name for t in catalog}
        assert set(literals(driver.selections[0]['schema'])) == permitted
        assert {'project_status', 'task', 'ls'} <= permitted
        assert 'search_tools' not in permitted


async def test_on_keeps_every_legal_choice_above_old_five_or_ten_limits(ws):
    configure(ws, 'on')
    chosen = []
    def choose(schema):
        chosen.extend(literals(schema)[:13])
        assert len(chosen) == 13  # Fixture checks the actual authorized catalog.
        return chosen
    driver = SelectionDriver(selections={'coordinator': [choose]},
                             coordinator=[AIMessage(content='No tool use required by this fixture.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Select relevant capabilities.')]})
    assert set(f['name'] for f in driver.bindings['coordinator'][-1]) == set(chosen)
    assert len(driver.selections) == 1 and len(driver.calls) == 1


async def test_no_selected_tools_does_not_restore_search_core_or_previous_choices(ws):
    configure(ws, 'on')
    driver = SelectionDriver(selections={'coordinator': [['project_status'], []]}, coordinator=[
        invoke('project_status'), AIMessage(content='No further capability needed.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Read the current state once.')]})
    assert {f['name'] for f in driver.bindings['coordinator'][0]} == {'project_status'}
    assert driver.bindings['coordinator'][-1] == []
    assert len(driver.selections) == len(driver.calls) == 2


async def test_default_mode_is_off_without_a_selector_or_new_tool(ws):
    assert 'tool_selection_mode' not in ws.store.manifest
    driver = SelectionDriver(coordinator=[AIMessage(content='Offline default control arm.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Use the existing authorized tools.') ]})
    assert driver.selections == []
    offered = {f['name'] for f in driver.bindings['coordinator'][-1]}
    assert {'task', 'project_status'} <= offered and 'search_tools' not in offered


async def test_omitted_task_is_rejected_before_registration_or_child_execution(ws):
    from report_agent.content_store import ContentStore
    configure(ws, 'on')
    def finish(messages):
        error = observation(messages, 'task')
        assert error.get('code') == 'TOOL_NOT_OFFERED' and error.get('execution_state') == 'not_executed'
        assert not ContentStore(ws.store).list_objects('DelegatedTask')
        return AIMessage(content='No task has been registered or replayed.')
    driver = SelectionDriver(selections={'coordinator': [[], []]}, coordinator=[
        invoke('task', subagent_type='writer', description='Must not be dispatched without a current definition.'), finish])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Choose available actions.') ]})
    assert not any(role == 'writer' for role, _, _ in driver.calls)
    assert not ContentStore(ws.store).list_objects('DelegatedTask')


async def test_missed_tool_is_not_executed_then_reselection_requires_a_new_call(ws):
    configure(ws, 'on')
    def blocked(messages):
        result = observation(messages, 'project_status')
        assert result.get('ok') is False and result.get('code') == 'TOOL_NOT_OFFERED'
        assert result.get('execution_state') == 'not_executed'
        assert 'sources' not in result
        return AIMessage(content='', tool_calls=[{'name': 'project_status', 'args': {},
            'id': 'new-status-decision', 'type': 'tool_call'}])
    def finish(messages):
        result = observation(messages, 'project_status')
        assert result.get('code') != 'TOOL_NOT_OFFERED'
        return AIMessage(content='The new decision was executed once.')
    driver = SelectionDriver(selections={'coordinator': [[], ['project_status'], []]},
                             coordinator=[invoke('project_status'), blocked, finish])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Inspect state if needed.')]})
    assert len(driver.selections) == len(driver.calls) == 3
    calls = [c for _, _, messages in driver.calls[-1:] for m in messages if isinstance(m, AIMessage)
             for c in m.tool_calls if c['name'] == 'project_status']
    assert len(calls) == 2 and calls[0]['id'] != calls[1]['id']
    assert driver.bindings['coordinator'][-1] == []


@pytest.mark.parametrize('choice', ['fabricated_tool', 'submit_review'])
async def test_selector_cannot_invent_or_expand_coordinator_permissions(ws, choice):
    configure(ws, 'on')
    driver = SelectionDriver(selections={'coordinator': [[choice]]},
                             coordinator=[AIMessage(content='Must not reach the business model.')])
    with pytest.raises(ValueError, match='invalid tools'):
        await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Use only permitted capabilities.')]})
    assert len(driver.selections) == 1 and driver.calls == []


@pytest.mark.parametrize('reason', ['Use the saved export, not the render.', 'Need the original source comparison, not a new export.'])
async def test_selector_gets_effective_public_semantics_not_only_recent_codes(ws, reason):
    configure(ws, 'on')
    goal = 'CURRENT_TASK: verify the current commissioned output.'
    ws.store.set('manifest', {**ws.store.manifest, 'goal': goal})
    action = 'PUBLIC_ACTION_INTENT: resolve the reported reference type before choosing a tool.'
    # Keep this projection test below the real summarizer threshold; compaction
    # and preservation of root intent have their own native test below.
    source = 'SOURCE_BODY_MUST_NOT_ENTER_SELECTOR_' * 50
    private = 'PRIVATE_REASONING_MUST_NOT_ENTER_SELECTOR'
    history = [HumanMessage(content='Current direct task clarification.'),
               AIMessage(content=action, additional_kwargs={'reasoning_content': private})]
    for i in range(10):
        history += [AIMessage(content='', tool_calls=[{'name': 'project_status', 'args': {},
                    'id': f'prior-{i}', 'type': 'tool_call'}]),
                    ToolMessage(json.dumps({'ok': False, 'code': 'RESOURCE_KIND_MISMATCH',
                        'execution_state': 'not_executed', 'body': source,
                        'diagnostic': {'reason': reason if i == 0 else 'Later same-status observation.',
                                       'parameter_path': ['target_ref'], 'allowed_types': ['ExportArtifact']}}),
                        name='project_status', tool_call_id=f'prior-{i}', status='error')]
    step = sum(isinstance(m, AIMessage) for m in history)
    driver = SelectionDriver(selections={'coordinator': [[]]},
                             coordinator=[AIMessage(content='unused')] * step + [AIMessage(content='Offline end.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': history})
    assert len(driver.selections) == 1
    selected = text(driver.selections[0]['messages'])
    assert goal in selected and 'Current direct task clarification.' in selected
    assert action in selected and reason in selected and 'allowed_types' in selected
    assert source[:100] not in selected and private not in selected
    # Selector-specific synthetic Human input must not replace business history.
    main_text = text(driver.calls[0][2])
    assert action in main_text and source[:100] in main_text
    visible = iter(driver.calls[0][2])
    for original in history:
        assert any(m.type == original.type and m.content == original.content
            and getattr(m, 'tool_calls', []) == getattr(original, 'tool_calls', [])
            and getattr(m, 'tool_call_id', None) == getattr(original, 'tool_call_id', None)
            for m in visible), 'Original business messages must remain an ordered subsequence'


async def test_child_selector_uses_bound_assignment_and_current_correction_without_cross_role_tools(ws):
    configure(ws, 'on')
    objective = 'BOUND_WRITER_TASK: retain the commissioned original condition.'
    driver = SelectionDriver(selections={'coordinator': [['task'], []], 'writer': [[]]},
        coordinator=[invoke('task', subagent_type='writer', description=objective), AIMessage(content='Co received the child result.')],
        writer=[AIMessage(content='Child returned only its assigned result.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Coordinate one bounded writing task.')]})
    children = [r for r in driver.selections if r['role'] == 'writer']
    assert len(children) == 1
    child = children[0]
    assert objective in text(child['messages'])
    assert 'submit_review' not in literals(child['schema'])
    assert 'task' not in literals(child['schema'])
    assert child['credential'] is not None and child['credential']['purpose'] == 'tool_selector:writer'
    assert driver.bindings['writer'][-1] == []


async def test_selection_attempts_have_separate_prompt_credentials_and_never_enter_main_history(ws):
    configure(ws, 'on')
    driver = SelectionDriver(selections={'coordinator': [{'malformed': []}, []]},
                             coordinator=[AIMessage(content='Continue after a structured-response retry.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Choose only if useful.')]})
    assert len(driver.selections) == 2 and len(driver.calls) == 1
    for record in driver.selections:
        assert record['credential'] is not None
        assert record['credential']['purpose'] == 'tool_selector:coordinator'
    assert 'malformed' not in text(driver.calls[0][2])
    captures = [e['data'] for e in ws.store.events() if e['kind'] == 'prompt_model_input']
    assert any(c['purpose'] == 'tool_selector:coordinator' for c in captures)
    assert any(c['purpose'] == 'coordinator' for c in captures)


async def test_native_malformed_response_exhaustion_is_explicit_without_full_catalog_fallback(ws):
    configure(ws, 'on')
    driver = SelectionDriver(selections={'coordinator': [{'malformed': []}, {'still_malformed': []}]},
        coordinator=[AIMessage(content='The business model must not run after native failure.')])
    with pytest.raises(ValueError):
        await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Choose authorized tools.')]})
    assert len(driver.selections) == 2 and not driver.calls
    assert all(r['credential']['purpose'] == 'tool_selector:coordinator' for r in driver.selections)


@pytest.mark.parametrize('bad_mode', ['ON', 'on-with-core', 1])
async def test_invalid_experiment_mode_is_rejected_before_model_calls(ws, bad_mode):
    configure(ws, bad_mode)
    driver = SelectionDriver(coordinator=[AIMessage(content='Must not be requested.')])
    with pytest.raises((ValueError, ActionRejected), match='TOOL_SELECTION_MODE'):
        deep_runtime.build_agent(ws, driver, None)
    assert not driver.calls and not driver.selections


@pytest.mark.parametrize('selected_name', ['project_status', 'task'])
async def test_actual_sdk_selector_retry_and_business_calls_share_budget_and_public_trace(ws, tmp_path, selected_name):
    """MockTransport checks packaging/accounting, not Aliyun protocol support."""
    import httpx
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.token_budget import TokenBudget, token_budget
    configure(ws, 'on')
    models, wires, purposes = {}, [], []
    budget = TokenBudget(tmp_path / 'finance' / 'budget.db', 1000, {'glm-5.3': 100})
    old_unknown = budget.reserve('glm-5.3')
    with budget.connect() as db:
        old_row = db.execute('SELECT * FROM attempts WHERE id=?', (old_unknown,)).fetchone()
    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        async def transport(request):
            wire = json.loads(request.content)
            credential = _CALL.get()
            assert credential is not None
            purpose = credential['purpose']
            wires.append(wire); purposes.append(purpose)
            assert wire['model'] == 'glm-5.3'
            assert request.url.host == 'offline.invalid'
            if purpose == 'tool_selector:coordinator':
                selected = {'malformed': []} if purposes.count(purpose) == 1 else {'tools': [selected_name]}
                # Accept either installed adapter encoding; do not alter its global method.
                if wire.get('response_format', {}).get('type') == 'json_schema':
                    message = {'role': 'assistant', 'content': json.dumps(selected)}
                else:
                    function = wire['tools'][0]['function']['name']
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                        'id': 'selection-' + str(len(wires)), 'type': 'function',
                        'function': {'name': function, 'arguments': json.dumps(selected)}}]}
            else:
                assert purpose == 'coordinator'
                assert {t['function']['name'] for t in wire.get('tools', [])} == {selected_name}
                if selected_name == 'task':
                    fields = wire['tools'][0]['function']['parameters']['properties']
                    assert {'resume_task_scope', 'snapshot_scope', 'commission_criterion_scopes', 'review_scope'} <= fields.keys()
                message = {'role': 'assistant', 'content': 'No report was produced by this fixture.'}
            return httpx.Response(200, json={'id': 'offline-' + str(len(wires)), 'model': 'glm-5.3',
                'choices': [{'index': 0, 'message': message,
                             'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}],
                'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10,
                          'prompt_tokens_details': {'cached_tokens': 3}}})
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='offline-key-canary',
            base_url='https://offline.invalid/v1', use_responses_api=False, max_retries=0,
            http_async_client=client, disable_streaming=True)
        return models[role]
    try:
        with token_budget(budget):
            await deep_runtime.build_agent(ws, factory, None).ainvoke({'messages': [HumanMessage(content='Inspect current status if useful.')]})
        assert purposes == ['tool_selector:coordinator', 'tool_selector:coordinator', 'coordinator']
        actual = budget.snapshot()
        assert actual['recorded_tokens'] == 30  # Cached tokens are a subset, not an added cost.
        assert actual['reserved_or_unknown_upper_bounds'] == 100
        assert actual['attempt_states']['settled'] == 3
        captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
                    if e['kind'] == 'prompt_final_http_input']
        assert [c['purpose'] for c in captures] == purposes
        assert all(c['expected_wire_available'] for c in captures)
        assert len({c['call_id'] for c in captures}) == 2  # One logical selector with a native parse retry.
        assert 'offline-key-canary' not in json.dumps(captures)
        with budget.connect() as db:
            assert db.execute('SELECT * FROM attempts WHERE id=?', (old_unknown,)).fetchone() == old_row
    finally:
        for model in models.values():
            await model.http_async_client.aclose()
            if model.http_client is not None:
                model.http_client.close()


async def test_successful_tool_message_body_is_not_selector_intent(ws):
    configure(ws, 'on')
    body = 'SUCCESSFUL_SOURCE_BODY_CANARY_' * 80
    prior = [HumanMessage(content='Choose the next authorized action.'),
        AIMessage(content='', tool_calls=[{'name': 'read_source_page', 'args': {'source_id': 's'},
                                          'id': 'prior-success', 'type': 'tool_call'}]),
        ToolMessage(json.dumps({'ok': True, 'message': body, 'body': body,
            'diagnostic': {'reason': body}, 'result': {'text': body}}),
            name='read_source_page', tool_call_id='prior-success', status='success')]
    driver = SelectionDriver(selections={'coordinator': [[]]},
        coordinator=[AIMessage(content='unused previous turn'), AIMessage(content='Offline next decision.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': prior})
    assert len(driver.selections) == 1 and len(driver.calls) == 1
    selected = text(driver.selections[0]['messages'])
    assert 'read_source_page' in selected and 'success' in selected
    assert 'SUCCESSFUL_SOURCE_BODY_CANARY_' not in selected
    assert body in text(driver.calls[0][2])  # The business Agent retains its actual observation.


async def test_native_validation_input_echo_is_excluded_but_structured_recovery_semantics_survive(ws):
    from pydantic import ValidationError
    from report_agent.co_review_message import CoTaskMessage
    from report_agent.message_fields import validate_message
    from report_agent.tool_argument_feedback import compact_native_tool_error
    configure(ws, 'on')
    body = 'PRIVATE_INPUT_VALUE_CANARY'
    args = {'subagent_type': 'writer', 'description': [body]}
    with pytest.raises(ValidationError) as invalid:
        CoTaskMessage.model_validate(args)
    assert body in str(invalid.value)
    raw = ToolMessage("Error invoking tool 'task' with error: " + str(invalid.value),
                      name='task', tool_call_id='native-validation', status='error')
    native = compact_native_tool_error(raw, ws.store, args=args, schema=CoTaskMessage)
    value = json.loads(native.content)
    assert isinstance(value['diagnostic'], str) and body in value['diagnostic']
    with pytest.raises(ActionRejected) as structured_error:
        validate_message(CoTaskMessage, args)
    structured = json.loads(native.content)
    structured['diagnostic'] = structured_error.value.diagnostic
    reason = 'The task objective must be a string; choose the existing assignment before resuming.'
    structured['diagnostic'].update(reason=reason, allowed_types=['string'], parameter_path=['description'],
                                    input_value=args, body=body)
    structured['diagnostic']['fields'][0]['input_value'] = body
    structured['message'] = str(invalid.value)
    prior = [HumanMessage(content='Correct only after inspecting the actual validation result.'),
        AIMessage(content='', tool_calls=[{'name': 'task', 'args': args,
                                          'id': 'native-validation', 'type': 'tool_call'}]), native,
        AIMessage(content='', tool_calls=[{'name': 'task', 'args': args,
                                          'id': 'structured-validation', 'type': 'tool_call'}]),
        ToolMessage(json.dumps(structured), name='task', tool_call_id='structured-validation', status='error')]
    driver = SelectionDriver(selections={'coordinator': [[]]},
        coordinator=[AIMessage(content='unused')] * 2 + [AIMessage(content='Offline correction decision.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': prior})
    assert len(driver.selections) == 1
    selected = text(driver.selections[0]['messages'])
    assert body not in selected
    assert reason in selected and 'allowed_types' in selected and 'parameter_path' in selected
    assert 'root_contract' in selected and 'required_keys' in selected and 'allowed_keys' in selected
    assert 'fields' in selected and 'definition' in selected
    context = json.loads(next(m.text for m in driver.selections[0]['messages'] if isinstance(m, HumanMessage)))
    errors = [r for r in context['public_action_observations'] if r.get('tool') == 'task']
    assert len(errors) == 2 and all(r['execution_state'] == 'not_established' for r in errors)
    assert body in text(driver.calls[0][2])  # Do not hide original error/arguments from the business Agent.


async def test_resumed_child_selector_keeps_original_assignment_and_current_correction_without_changing_grants(ws):
    from langchain.agents.middleware.types import ModelRequest, ModelResponse
    from langchain_core.messages import SystemMessage
    from langchain_core.tools import StructuredTool
    from report_agent.content_tasks import delegated_task
    from report_agent.content_store import ContentStore
    from report_agent.task_context import TaskContext
    from report_agent.tool_selection import NativeToolSelection
    configure(ws, 'on')
    original = 'Keep the original commissioned writing condition. ' * 70 + 'ORIGINAL_TASK_TAIL'
    with delegated_task(ws, 'coordinator', {'id': 'source-writer', 'args': {
            'subagent_type': 'writer', 'description': original}}) as (_, actor):
        task_ref = {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1}
    cs = ContentStore(ws.store)
    before = cs.read(task_ref)
    correction = 'Correct only the selected title while retaining all original conditions.'
    with delegated_task(ws, 'coordinator', {'id': 'resume-writer', 'args': {
            'subagent_type': 'writer', 'description': correction,
            'resume_content_task_id': task_ref['id']}}):
        middleware = NativeToolSelection(ws, 'writer')
        read_state = StructuredTool.from_function(TaskContext(ws, 'writer').tools[0])
        driver = SelectionDriver(selections={'writer': [[]]})
        history = [HumanMessage(content='Current public correction, not a replacement commission.')]
        request = ModelRequest(model=driver('writer'), tools=[read_state], state={'messages': history},
            system_message=SystemMessage(content='Writer role retained.'), messages=history)
        business = []
        async def handler(changed):
            business.append(changed)
            return ModelResponse(result=[AIMessage(content='No tool or write executed.')])
        await middleware.awrap_model_call(request, handler)
    assert len(driver.selections) == 1 and len(business) == 1
    context = json.loads(next(m.text for m in driver.selections[0]['messages'] if isinstance(m, HumanMessage)))
    assert context['assignment']['goal'] == original and context['assignment']['role'] == 'writer'
    assert correction in json.dumps(context['current_invocation'])
    assert business[0].messages == history and business[0].tools == []
    assert cs.read(task_ref) == before


async def test_root_intent_survives_actual_native_summary_and_checkpoint_reopen_without_replaying_history(ws, monkeypatch):
    from langchain_core.runnables import RunnableLambda
    from langgraph.checkpoint.memory import InMemorySaver
    from report_agent.working_summary import WorkingSummary
    configure(ws, 'on')
    original = 'CURRENT_DIRECT_ROOT_INTENT: retain the uncertainty. ' * 35 + 'ROOT_INTENT_TAIL'
    summary_inputs = []
    async def summarize(prompt):
        summary_inputs.append(str(prompt))
        return AIMessage(content='Model-generated historical notes; no current user instructions are repeated here.')
    monkeypatch.setattr('report_agent.working_summary.working_summary', lambda model, store, role, **options:
        WorkingSummary(model=RunnableLambda(summarize), store=store, role=role,
            trigger=('messages', 7), keep=('messages', 3), token_counter=lambda messages: len(messages),
            trim_tokens_to_summarize=None))
    history = [HumanMessage(content=original, id='original-direct-user')]
    for i in range(4):
        history += [AIMessage(content='', tool_calls=[{'name': 'project_status', 'args': {},
                    'id': f'old-status-{i}', 'type': 'tool_call'}]),
                    ToolMessage(json.dumps({'ok': True, 'status': 'ready'}),
                        name='project_status', tool_call_id=f'old-status-{i}')]
    turns = []
    def choose(messages):
        turns.append(messages)
        return invoke('project_status') if len(turns) == 1 else AIMessage(content='Offline terminal decision.')
    driver = SelectionDriver(selections={'coordinator': [['project_status'], [], [], []]},
                             coordinator=[choose] * 20)
    checkpoint = InMemorySaver()
    config = {'configurable': {'thread_id': 'root-intent-summary-fixture'}}
    agent = deep_runtime.build_agent(ws, driver, checkpoint)
    await agent.ainvoke({'messages': history}, config)
    saved = await agent.aget_state(config)
    assert summary_inputs and original in summary_inputs[0]
    assert any(m.additional_kwargs.get('lc_source') == 'summarization' for m in saved.values['messages'])
    assert all(m.id != 'original-direct-user' for m in saved.values['messages'])
    assert len(driver.selections) == 2 and len(driver.calls) == 2
    for selection in driver.selections:
        context = json.loads(next(m.text for m in selection['messages'] if isinstance(m, HumanMessage)))
        assert context['current_user_task'] == original
    # A new middleware instance must use retained native state, not an instance cache.
    reopened = deep_runtime.build_agent(ws, driver, checkpoint)
    await reopened.ainvoke({'messages': []}, config)
    assert len(driver.selections) == 3
    context = json.loads(next(m.text for m in driver.selections[-1]['messages'] if isinstance(m, HumanMessage)))
    assert context['current_user_task'] == original
    latest = 'LATEST_DIRECT_ROOT_CLARIFICATION: use the revised question without changing permissions.'
    await reopened.ainvoke({'messages': [HumanMessage(content=latest)]}, config)
    assert len(driver.selections) == 4
    context = json.loads(next(m.text for m in driver.selections[-1]['messages'] if isinstance(m, HumanMessage)))
    assert context['current_user_task'] == latest
    assert all(not any(isinstance(m, HumanMessage) and m.text == original for m in messages)
               for _, _, messages in driver.calls), 'Retain root intent without reinjecting its old Human message'
