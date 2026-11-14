"""Review-only until the first frozen regression finishes; native protocol controls."""
import asyncio
from copy import deepcopy
import json

import pytest
from deepagents.backends import StateBackend
from deepagents.middleware.subagents import SubAgentMiddleware, CompiledSubAgent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt.tool_node import ToolNode, ToolCallRequest
from langgraph.graph import StateGraph, MessagesState, START, END

from report_agent.deep_runtime import BusinessBoundary, run_report
from report_agent.content_store import ContentStore
from report_agent.content_tasks import task_tool
from test_single_reviewer import ws, offline, seed, new_path, review_assignment
from test_deep_runtime import Driver, invoke, call, observation


def registered_task():
    def unused_child(state):
        raise AssertionError('This control must not run a subagent')
    middleware = SubAgentMiddleware(backend=StateBackend(), subagents=[CompiledSubAgent(
        name='reviewer', description='Inspect the assigned saved objects',
        runnable=RunnableLambda(unused_child))])
    return next(t for t in middleware.tools if t.name == 'task')


def retain(request, **value):
    request.node.user_properties.append(('native_task_boundary', json.dumps(value, sort_keys=True)))


def business_ledger(ws):
    with ws.store.connect() as db:
        return {table: sorted(tuple(row) for row in db.execute('SELECT * FROM ' + table))
                for table in ('content_operations', 'content_observations')}


async def native_node(node, state):
    # ToolNode requires the framework's actual graph Runtime/config injection.
    graph = StateGraph(MessagesState)
    graph.add_node('tools', node)
    graph.add_edge(START, 'tools')
    graph.add_edge('tools', END)
    result = await graph.compile().ainvoke(state)
    return {'messages': [m for m in result['messages'] if isinstance(m, ToolMessage)]}


@pytest.mark.parametrize('privileged_looking', [False, True])
async def test_unregistered_task_keeps_real_native_unknown_feedback_and_no_business_work(ws, privileged_looking, request):
    new_path(ws)
    args = {'subagent_type': 'writer', 'description': 'An unregistered task is not permission'}
    if privileged_looking:
        args.update(review_requirements='not a list', permissions=['publish'], operation_id='unknown-call')
    action = call('task', args, 'native-unregistered-task')
    original = deepcopy(action)
    state = {'messages': [HumanMessage(content='Inspect available capabilities'), AIMessage(content='', tool_calls=[action])]}
    baseline = await native_node(ToolNode([]), state)
    retain(request, boundary='real_native_unknown_baseline', original_call=original,
           messages=[m.model_dump() for m in baseline['messages']])
    cs = ContentStore(ws.store)
    before = cs.list_objects()
    ledger_before = business_ledger(ws)
    handler_calls = []
    boundary = BusinessBoundary(ws, 'coordinator')
    async def wrapped(request, handler):
        assert request.tool is None
        assert request.tool_call == original
        async def native(next_request):
            handler_calls.append(deepcopy(next_request.tool_call))
            return await handler(next_request)
        return await boundary.awrap_tool_call(request, native)
    result = await native_node(ToolNode([], awrap_tool_call=wrapped), state)
    actual, = result['messages']
    expected, = baseline['messages']
    retain(request, boundary='real_native_unknown_through_business_boundary',
           actual=actual.model_dump(), native_handler_calls=handler_calls,
           business_objects_before=before, business_objects_after=cs.list_objects(),
           business_ledger_before=ledger_before, business_ledger_after=business_ledger(ws))
    assert (actual.content, actual.status, actual.name, actual.tool_call_id) == (
        expected.content, expected.status, expected.name, expected.tool_call_id)
    assert actual.status == 'error'
    assert handler_calls == [original] and action == original
    assert cs.list_objects() == before
    assert business_ledger(ws) == ledger_before
    assert cs.list_objects('DelegatedTask') == []
    assert not any(e['kind'] == 'native_tool_schema_error' for e in ws.store.events())


async def test_lower_permission_unknown_task_does_not_reach_native_handler_or_create_grants(ws, request):
    new_path(ws)
    cs = ContentStore(ws.store)
    before = cs.list_objects()
    ledger_before = business_ledger(ws)
    action = call('task', {'subagent_type': 'writer', 'description': 'No delegation authority'}, 'writer-unknown-task')
    original = deepcopy(action)
    boundary = BusinessBoundary(ws, 'writer')
    reached = []
    async def wrapped(request, handler):
        assert request.tool is None
        async def native(next_request):
            reached.append(next_request)
            return await handler(next_request)
        return await boundary.awrap_tool_call(request, native)
    result = await native_node(ToolNode([], awrap_tool_call=wrapped), {'messages': [AIMessage(content='', tool_calls=[action])]})
    message, = result['messages']
    error = json.loads(message.content)
    retain(request, boundary='lower_permission_unknown_task', original_call=original,
           actual=message.model_dump(), native_handler_calls=len(reached),
           business_objects_before=before, business_objects_after=cs.list_objects(),
           business_ledger_before=ledger_before, business_ledger_after=business_ledger(ws))
    assert message.status == 'error' and error['code'] == 'FORBIDDEN'
    assert reached == [] and action == original
    assert cs.list_objects() == before and cs.list_objects('DelegatedTask') == []
    assert business_ledger(ws) == ledger_before


@pytest.mark.parametrize('failure', [asyncio.CancelledError, TypeError, RuntimeError])
async def test_registered_task_preserves_cancellation_and_records_known_failures(ws, failure, request):
    new_path(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    tool = registered_task()
    action = call('task', review_assignment(snapshot, refs), 'registered-failure')
    original = deepcopy(action)
    task_tool(tool).tool_call_schema.model_validate(action['args'])
    native_request = ToolCallRequest(tool_call=action, tool=tool,
        state={'messages': [HumanMessage(content='Check assigned content'), AIMessage(content='', tool_calls=[action])]}, runtime=None)
    reached = []
    async def fail_handler(next_request):
        reached.append(next_request.tool_call)
        assert next_request.tool is tool
        assert next_request.tool_call['id'] == original['id']
        raise failure('Synthetic handler failure')
    if failure is asyncio.CancelledError:
        with pytest.raises(failure):
            await BusinessBoundary(ws, 'coordinator').awrap_tool_call(native_request, fail_handler)
    else:
        from hashlib import sha256
        from report_agent.token_budget import TokenBudget,CampaignRunBudget,token_budget
        ledger=TokenBudget(ws.store.root/'known-failure-ledger.db',1000,{'m':40})
        for _ in range(2):ledger.settle(ledger.reserve('m'),None)
        with ledger.connect() as db:holds=[list(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]
        budget=CampaignRunBudget(ledger.path,'known-only',maximum_tokens=500,aggregate_tokens=1000,model_bounds={'m':40},
            authority_sha256='a'*64,preserved_holds=holds,guard_sha256=sha256(b'').hexdigest())
        before=budget.snapshot()
        with token_budget(budget):
            result=await BusinessBoundary(ws,'coordinator').awrap_tool_call(native_request,fail_handler)
        assert result.status=='error' and json.loads(result.content)['code']=='DELEGATED_EXECUTION_FAILED'
        assert budget.snapshot()==before
        with ledger.connect() as db:assert [list(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]==holds
    retain(request, boundary='registered_native_schema_handler_failure', failure=failure.__name__,
           original_call=original, actual_native_handler_calls=reached,
           unchanged_original_call=action==original,
           events=[e['kind'] for e in ws.store.events()])
    assert len(reached) == 1 and action == original
    assert sum(e['kind']=='content_delegation_failed' for e in ws.store.events())==int(failure is not asyncio.CancelledError)
    assert cs.list_objects('ReviewRecord') == []


@pytest.mark.parametrize('variant', ['artifact', 'combined', 'outer-string', 'malformed-element', 'unrelated', 'multiple-review-fields'])
async def test_native_task_schema_feedback_retains_domain_and_all_native_errors_without_dispatch(ws, variant, request):
    new_path(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    args = review_assignment(snapshot, refs)
    if variant in {'artifact', 'combined', 'multiple-review-fields'}:
        args['review_requirements'][0]['artifact_refs'] = [refs['claim']]
    if variant in {'combined', 'unrelated'}:
        args['description'] = 17
    if variant == 'outer-string':
        args['review_requirements'] = 'not a list'
    if variant == 'malformed-element':
        args['review_requirements'] = [17]
    if variant == 'multiple-review-fields':
        args['review_requirements'][0]['scope_id'] = 17
    original = deepcopy(args)
    first = invoke('task', **args)
    original_call = deepcopy(first.tool_calls)
    before = cs.list_objects()
    before_ledger = business_ledger(ws)
    observed = []
    def select_invalid_task(messages):
        nonlocal before, before_ledger
        # Measure after normal graph initialization, before this actual call.
        before = cs.list_objects()
        before_ledger = business_ledger(ws)
        return first
    def retain_error(messages):
        public = observation(messages, 'task')
        observed.append(public.get('metadata', public))
        return AIMessage(content='Retain the actual rejection; no dispatch or retry')
    driver = Driver(coordinator=[select_invalid_task, retain_error])
    result = await run_report(ws, driver)
    retain(request, boundary='actual_native_coordinator_schema_feedback', variant=variant,
           original_args=original, actual_feedback=observed, runtime_result=result,
           actual_model_roles=[role for role, _, _ in driver.calls],
           business_objects_before=before, business_objects_after=cs.list_objects(),
           business_ledger_before=before_ledger, business_ledger_after=business_ledger(ws))
    assert result['last_error'] is None, result
    assert args == original and first.tool_calls == original_call
    assert len(observed) == 1
    payload = observed[0]
    domain = variant not in {'outer-string', 'unrelated'}
    if domain:
        assert payload['code'] == 'INVALID_REVIEW_REQUIREMENTS'
        assert 'ReviewRequirement' in payload['message']
        assert payload['native_validation']['code'] == 'NATIVE_TOOL_VALIDATION_ERROR'
        assert payload['domain_validation_errors']
        if variant != 'malformed-element':
            assert 'literal_error' in payload['message'] and 'artifact_refs.0.type' in payload['message']
        errors = payload['native_schema_errors']
        assert all('input' not in e and 'ctx' not in e for e in errors + payload['domain_validation_errors'])
        if variant == 'combined':
            assert any(e['loc'] == ['description'] for e in errors)
            assert any(e['loc'] == ['review_requirements', 0, 'artifact_refs', 0, 'type'] for e in errors)
        if variant == 'multiple-review-fields':
            assert any(e['loc'] == ['review_requirements', 0, 'scope_id'] for e in errors)
            assert any(e['loc'] == ['review_requirements', 0, 'artifact_refs', 0, 'type'] for e in errors)
            assert any(e['loc'] == ['scope_id'] for e in payload['domain_validation_errors'])
            assert any(e['loc'] == ['artifact_refs', 0, 'type'] for e in payload['domain_validation_errors'])
        diagnostic = payload['native_validation']
    else:
        assert payload['code'] == 'NATIVE_TOOL_VALIDATION_ERROR'
        assert 'domain_validation_errors' not in payload
        diagnostic = payload
        assert ('review_requirements' if variant == 'outer-string' else 'description') in diagnostic['diagnostic']
    native_events = [e['data'] for e in ws.store.events() if e['kind'] == 'native_tool_schema_error']
    assert any(e['error_digest'] == diagnostic['native_error_digest'] for e in native_events)
    assert cs.list_objects() == before and cs.list_objects('DelegatedTask') == []
    assert business_ledger(ws) == before_ledger
    assert cs.list_objects('ReviewRecord') == []
    assert all(role == 'coordinator' for role, _, _ in driver.calls)
    assert not any(e['kind'] == 'content_delegation_returned' for e in ws.store.events())
