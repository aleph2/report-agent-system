"""Actual middleware integration, with the SDK network replaced by MockTransport."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

from report_agent.deep_runtime import BusinessBoundary
from report_agent.hierarchical_tools import content_tools
from report_agent.native_operation_tools import native_write_tools
from test_deliverable_declaration_v4 import case
from test_review_message_entry import setup, assignment, bound
from test_review_message import message
import httpx
import json
from openai import AsyncOpenAI
from report_agent.deepseek_strict import StrictCodec
from report_agent.store import encode


async def sdk_request(request, value, strict, requests, tool_name='submit_review'):
    function = next(convert_to_openai_tool(t)['function'] for t in request.tools
                    if convert_to_openai_tool(t)['function']['name'] == tool_name)
    values = value if isinstance(value, list) else [value]
    calls = []
    for index, item in enumerate(values):
        args = StrictCodec(function).encode(item) if strict else item
        calls.append({'id': 'live-save-'+str(index) if isinstance(value, list) else 'live-save', 'type': 'function',
            'function': {'name': function['name'], 'arguments': json.dumps(args)}})
    async def handle(wire):
        requests.append(json.loads(wire.content))
        return httpx.Response(200, json={'id': 'offline-live-save', 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': 'tool_calls',
            'message': {'role': 'assistant', 'content': '', 'tool_calls': calls}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    async def admit(wire):
        from report_agent.prompt_provenance import admit_prompt_request
        admit_prompt_request(wire)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), event_hooks={'request': [admit]}) as client:
        async with AsyncOpenAI(api_key='offline', base_url='https://model.invalid/beta', http_client=client) as sdk:
            request.model.async_client = sdk.chat.completions
            from contextlib import nullcontext
            from report_agent.prompt_provenance import prompt_call, _CALL
            with (nullcontext() if _CALL.get() is not None else prompt_call(None, 'reviewer')):
                return ModelResponse(result=[await request.model.bind_tools(request.tools).ainvoke(
                    [request.system_message, *request.messages])])


@pytest.mark.parametrize('strict', [False, True])
async def test_live_request_sdk_and_native_tool_save(case, monkeypatch, strict):
    from report_agent import live_messages
    from report_agent.content_store import ContentStore
    from report_agent.deep_models import GLMChatOpenAI
    from report_agent.review_message import validate_message_binding
    cs, output, criteria = setup(case)
    checked = []
    def validate(contents, db, actor, binding):
        validate_message_binding(contents, db, actor, binding)
        checked.append(db.in_transaction)
    monkeypatch.setattr('report_agent.review_message.validate_message_binding', validate)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        tools = native_write_tools(ws, 'reviewer', [t for t in content_tools(ws, 'reviewer')
            if t.__name__ in {'submit_review', live_messages.CHECK_TOOL}])
        model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta',
                             deepseek_strict=strict)
        try:
            request = ModelRequest(model=model, tools=tools, state={'messages': []},
                system_message=SystemMessage(content='Original role retained.'),
                messages=[HumanMessage(content='Perform the assigned check.')])
            middleware = BusinessBoundary(ws, 'reviewer')
            requests = []
            async def model_handler(changed):
                function = next(convert_to_openai_tool(t)['function'] for t in changed.tools
                                if getattr(t, 'name', None) == live_messages.CHECK_TOOL)
                assert 'review' not in function['parameters']['properties']
                assert any(getattr(t, 'name', None) == 'submit_review' for t in changed.tools)
                return await sdk_request(changed, message(), strict, requests)
            response = await middleware.awrap_model_call(request, model_handler)
            answer, = response.result
            graph = StateGraph(MessagesState)
            graph.add_node('tools', ToolNode(tools, awrap_tool_call=middleware.awrap_tool_call))
            graph.add_edge(START, 'tools'); graph.add_edge('tools', END)
            result = await graph.compile().ainvoke({'messages': [answer]})
            assert result['messages'][-1].status == 'success'
            record, = cs.list_objects('ReviewRecord')
            assert record['payload']['items'][0]['reason'] == message()['assessment']
            assert record['payload']['items'][0]['observations'][0]['receipt_id'] == receipt
            assert True in checked
            assert live_messages.current_review_binding(ws, actor) is None
            assert len(requests) == 1
            system = requests[0]['messages'][0]['content']
            packet = json.loads(system[-1]['text'])
            assert receipt not in encode(packet) and actor.id not in encode(packet)
            assert packet['actual_read_receipts'][0]['read']['objects'][0]['object_type'] == 'ContentNode'
            assert 'review' not in answer.tool_calls[0]['args']
        finally:
            model.root_client.close()
            await model.root_async_client.close()


def test_offer_guard_rejects_changed_wire_before_dispatch(case):
    from report_agent import live_messages
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, _, _):
        tools = native_write_tools(ws, 'reviewer', [t for t in content_tools(ws, 'reviewer')
            if t.__name__ in {'submit_review', live_messages.CHECK_TOOL}])
        class Request(SimpleNamespace):
            def override(self, **values):
                return Request(**{**vars(self), **values})
        changed, offer = live_messages.prepare_request(ws, 'reviewer', Request(tools=tools,
            messages=[], system_message=SystemMessage(content='Original')))
        wire = {'tools': [convert_to_openai_tool(t) for t in changed.tools],
                'messages': [{'role': 'system', 'content': changed.system_message.content_blocks}]}
        with live_messages.model_offer(offer):
            live_messages.validate_wire(wire, strict=False)
            for field in ('messages', 'tools'):
                corrupted = deepcopy(wire); corrupted[field] = []
                with pytest.raises(Exception, match='MESSAGE_CONTRACT_WIRE_MISMATCH'):
                    live_messages.validate_wire(corrupted, strict=False)


def test_receipt_directory_is_metadata_not_duplicate_material(case):
    from report_agent.live_messages import _receipt_label
    from report_agent.content_store import ContentStore
    large_body = 'FAKE_BODY_MUST_NOT_REPEAT_' * 10000
    value = {'objects': [{'ref': {'type': 'ContentNode', 'id': 'internal-id', 'version': 7},
                         'payload': {'kind': 'paragraph', 'title': 'Risk controls', 'body': large_body}}],
             'total': 1, 'next_offset': None}
    result = _receipt_label(ContentStore(case[0].store), value)
    text = encode(result)
    assert len(text) < 500
    assert 'internal-id' not in text and large_body[:200] not in text
    assert result['objects'][0]['label_preview'] == 'Risk controls'


def test_same_named_materials_receive_distinct_short_scopes(case):
    from report_agent.live_messages import _receipt_label
    from report_agent.content_store import ContentStore
    resources = {}
    obj = {'ref': {'type': 'ContentNode', 'id': 'first-internal-id', 'version': 1},
           'payload': {'title': 'Same risk table', 'kind': 'paragraph'}}
    first = _receipt_label(ContentStore(case[0].store), {'objects': [obj]}, resources)
    other = deepcopy(obj); other['ref']['id'] = 'second-internal-id'
    second = _receipt_label(ContentStore(case[0].store), {'objects': [other]}, resources)
    repeated = _receipt_label(ContentStore(case[0].store), {'objects': [obj]}, resources)
    assert first == repeated
    assert first['objects'][0]['material_scope'] != second['objects'][0]['material_scope']
    assert 'internal-id' not in encode([first, second])


@pytest.mark.parametrize('strict', [False, True])
async def test_co_flat_task_runs_real_sdk_and_original_delegation(case, strict):
    from deepagents.backends import StateBackend
    from deepagents.middleware.subagents import SubAgentMiddleware, CompiledSubAgent
    from langchain_core.runnables import RunnableLambda
    from langchain_core.messages import AIMessage
    from report_agent import live_messages
    from report_agent.deep_models import GLMChatOpenAI
    from report_agent.workspace import Workspace
    from test_co_review_message import setup_message
    from test_native_task_error_boundary import native_node
    cs, binding, _, criteria, snapshot, word, excel = setup_message(case)
    ws = Workspace(cs.store)
    assert not [t for t in cs.list_objects('DelegatedTask') if t['payload']['role'] == 'reviewer']
    previous_tasks = len(cs.list_objects('DelegatedTask'))
    child = RunnableLambda(lambda state: {'messages': [AIMessage('Assigned check remains unperformed.')]})
    middleware = SubAgentMiddleware(backend=StateBackend(), subagents=[CompiledSubAgent(
        name=role, description='Perform assigned work.', runnable=child) for role in ('reviewer','writer','layout')])
    tool = next(t for t in middleware.tools if t.name == 'task')
    model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta',
                         deepseek_strict=strict)
    try:
        request = ModelRequest(model=model, tools=[tool], state={'messages': []},
            system_message=SystemMessage(content='Original coordinator role.'),
            messages=[HumanMessage(content='Choose the needed comparison.')])
        boundary = BusinessBoundary(ws, 'coordinator')
        requests = []
        async def handler(changed):
            packet = json.loads(changed.system_message.content_blocks[-1]['text'])
            resources = packet['resource_scopes']
            exports = [r for r in resources if r['object_type'] == 'ExportArtifact']
            assert len(exports) == 2
            snapshot_scope = exports[0]['snapshot_scope']
            assert snapshot_scope == exports[1]['snapshot_scope']
            standards = [r['scope'] for r in resources if r['object_type'] == 'Criterion']
            value = {'subagent_type': 'reviewer', 'description': 'Compare the exact two exports; preserve uncertainty.',
                'snapshot_scope': snapshot_scope, 'commission_criterion_scopes': standards,
                'criterion_scopes': [standards[0]], 'review_scope': 'targeted',
                'target_scope': snapshot_scope, 'assessment_kind': 'export',
                'artifact_scopes': [r['scope'] for r in exports]}
            return await sdk_request(changed, value, strict, requests, tool_name='task')
        answer, = (await boundary.awrap_model_call(request, handler)).result
        node = ToolNode([tool], awrap_tool_call=boundary.awrap_tool_call)
        result = await native_node(node, {'messages': [HumanMessage('Delegate.'), answer]})
        assert result['messages'][-1].status == 'success'
        tasks = cs.list_objects('DelegatedTask')
        assert len(tasks) == previous_tasks + 1
        assert tasks[-1]['payload']['review_snapshot_ref'] == snapshot
        assert set(encode(r) for r in tasks[-1]['payload']['review_requirements'][0]['artifact_refs']) == {encode(word), encode(excel)}
        assert tasks[-1]['payload']['review_commission_basis']['criterion_refs'] == sorted(criteria, key=lambda r:(r['type'],r['id'],r['version']))
        assert not cs.list_objects('ReviewRecord')  # Delegation alone is not real review completion.
        assert len(requests) == 1 and 'review' not in answer.tool_calls[0]['args']
    finally:
        model.root_client.close()
        await model.root_async_client.close()


def live_tools(ws):
    return native_write_tools(ws, 'reviewer', [t for t in content_tools(ws, 'reviewer')
        if t.__name__ in {'submit_review', 'submit_review'}])


def live_graph(ws, tools, saver=None, interrupt=False):
    graph = StateGraph(MessagesState)
    graph.add_node('tools', ToolNode(tools, awrap_tool_call=BusinessBoundary(ws, 'reviewer').awrap_tool_call))
    graph.add_edge(START, 'tools'); graph.add_edge('tools', END)
    return graph.compile(checkpointer=saver, interrupt_before=['tools'] if interrupt else None)


async def live_answer(ws, tools, assessment='Real synthetic assessment.'):
    from report_agent.deep_models import GLMChatOpenAI
    model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta')
    try:
        request = ModelRequest(model=model, tools=tools, state={'messages': []},
            system_message=SystemMessage(content='Original reviewer role.'), messages=[HumanMessage(content='Check.')])
        requests = []
        async def handler(changed):
            return await sdk_request(changed, message(assessment=assessment), False, requests)
        answer, = (await BusinessBoundary(ws, 'reviewer').awrap_model_call(request, handler)).result
        assert len(requests) == 1
        return answer
    finally:
        model.root_client.close()
        await model.root_async_client.close()


@pytest.mark.parametrize('fault', ['missing-link', 'changed-args', 'changed-receipt', 'foreign-task'])
async def test_live_binding_failures_do_not_save(case, fault):
    from report_agent import live_messages
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria, 'task-a')) as (ws, actor, receipt):
        tools = live_tools(ws)
        answer = await live_answer(ws, tools)
        if fault == 'missing-link':
            with cs.store.connect() as db:
                db.execute("DELETE FROM state WHERE key LIKE 'message_call:%'")
        elif fault == 'changed-args':
            answer.tool_calls[0]['args']['assessment'] = 'Changed intent.'
        elif fault == 'changed-receipt':
            with cs.store.connect() as db:
                db.execute('UPDATE content_observations SET data=? WHERE id=?', ('{}', receipt))
        if fault == 'foreign-task':
            with bound(cs, assignment(output, criteria, 'task-b')):
                result = await live_graph(ws, tools).ainvoke({'messages': [answer]})
        else:
            result = await live_graph(ws, tools).ainvoke({'messages': [answer]})
        assert result['messages'][-1].status == 'error'
        assert not cs.list_objects('ReviewRecord')
        assert live_messages.current_review_binding(ws, actor) is None


async def test_live_concurrent_tasks_keep_own_receipts_and_ids(case):
    import asyncio
    from report_agent import live_messages
    from report_agent.workspace import Workspace
    cs, output, criteria = setup(case)
    tools = live_tools(Workspace(cs.store))
    graph = live_graph(Workspace(cs.store), tools)
    async def run(key, index):
        with bound(cs, assignment(output, criteria, key, criterion_index=index)) as (ws, actor, receipt):
            answer = await live_answer(ws, tools, key)
            # A later read must not reinterpret indexes already returned by the model.
            cs.read_context(actor, output['refs']['a-body'])
            result = await graph.ainvoke({'messages': [answer]})
            assert result['messages'][-1].status == 'success'
            replay = await graph.ainvoke({'messages': [answer]})
            assert replay['messages'][-1].status == 'success'
            assert live_messages.current_review_binding(ws, actor) is None
            return actor, receipt
    owners = await asyncio.gather(run('first', 0), run('second', 1))
    assert len(cs.list_objects('ReviewRecord')) == 2
    for actor, receipt in owners:
        record, = [r for r in cs.list_objects('ReviewRecord') if r['owner_id'] == actor.id]
        assert record['payload']['items'][0]['observations'][0]['receipt_id'] == receipt


async def test_live_checkpoint_resumes_in_new_process_without_model(case, tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent import live_messages
    cs, output, criteria = setup(case)
    call = assignment(output, criteria, 'resume-real-binding')
    checkpoint = tmp_path / 'checkpoint.db'
    config = {'configurable': {'thread_id': 'live-resume'}}
    with bound(cs, call) as (ws, _, _):
        tools = live_tools(ws)
        answer = await live_answer(ws, tools)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint)) as saver:
            graph = live_graph(ws, tools, saver, interrupt=True)
            await graph.ainvoke({'messages': [answer]}, config)
            assert (await graph.aget_state(config)).next == ('tools',)
        assert not cs.list_objects('ReviewRecord')
    args = tmp_path / 'resume.json'
    args.write_text(json.dumps({'workspace': str(cs.store.root), 'call': call, 'checkpoint': str(checkpoint)}))
    script = Path(__file__).parent / 'support/resume_live_review_message.py'
    completed = subprocess.run([sys.executable, '-B', str(script), str(args)],
                               env=os.environ.copy(), capture_output=True, text=True, timeout=40)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {'status': 'success', 'records': 1, 'model_calls': 0}
    assert len(cs.list_objects('ReviewRecord')) == 1


@pytest.mark.parametrize('profile', ['legacy-v1', 'concise-v1'])
@pytest.mark.parametrize('strict', [False, True])
async def test_final_prompt_boundary_preserves_the_offered_flat_schema(case, profile, strict):
    from report_agent import live_messages
    from report_agent.deep_models import GLMChatOpenAI
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.prompt_sources import load_prompt, context_source
    from report_agent.prompt_provenance import AgentPromptBoundary
    from report_agent.review_scope_selectors import CONTRACT as SELECTORS
    cs, output, criteria = setup(case)
    cs.store.set('manifest', {**cs.store.manifest,
        'report_prompt_profile': profile, 'report_expression_profile': 'reader-expression-v2'})
    with bound(cs, assignment(output, criteria)) as (ws, _, _):
        tools = live_tools(ws)
        text = role_prompt('reviewer', interface_profile='review-interfaces-v4',
            expression_profile='reader-expression-v2', prompt_profile=profile,
            review_submission_contract=SELECTORS) + '\n' + load_prompt(context_source('reviewer', 'review-interfaces-v4', profile))
        model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta', deepseek_strict=strict)
        try:
            request = ModelRequest(model=model, tools=tools, state={'messages': []},
                system_message=SystemMessage(content=text), messages=[HumanMessage(content='Check assigned material.')])
            requests = []
            async def final(changed):
                return await sdk_request(changed, message(), strict, requests)
            async def provenance(changed):
                return await AgentPromptBoundary(ws, 'reviewer').awrap_model_call(changed, final)
            answer, = (await BusinessBoundary(ws, 'reviewer').awrap_model_call(request, provenance)).result
            assert len(requests) == 1
            actual = requests[0]
            assert sum(t['function']['name'] == 'submit_review' for t in actual['tools']) == 1
            system_text = encode(actual['messages'][0]['content'])
            assert 'submit_review_check' not in system_text
            assert 'CheckResult.remaining' not in system_text
            assert 'finding_type' in next(t['function']['parameters']['properties'] for t in actual['tools'] if t['function']['name'] == 'submit_review')
            assert 'scope' in system_text
            assert answer.tool_calls[0]['name'] == 'submit_review'
        finally:
            model.root_client.close()
            await model.root_async_client.close()


async def test_association_write_failure_never_repeats_the_sdk_request(case, monkeypatch):
    from report_agent import live_messages
    cs, output, criteria = setup(case)
    original = live_messages._once
    sent = []
    original_sdk = sdk_request
    async def observe_sdk(request, value, strict, requests, **kwargs):
        sent.append(requests)
        return await original_sdk(request, value, strict, requests, **kwargs)
    monkeypatch.setattr(__import__(__name__, fromlist=['sdk_request']), 'sdk_request', observe_sdk)
    def fail_link(store, key, value):
        if key.startswith('message_call:'):
            raise OSError('Synthetic association persistence failure')
        return original(store, key, value)
    with bound(cs, assignment(output, criteria)) as (ws, actor, _):
        monkeypatch.setattr(live_messages, '_once', fail_link)
        with pytest.raises(OSError, match='association persistence'):
            await live_answer(ws, live_tools(ws))
        assert len(sent) == 1 and len(sent[0]) == 1
        assert not cs.list_objects('ReviewRecord')
        assert live_messages.current_review_binding(ws, actor) is None


async def test_cancelled_tool_clears_binding_without_another_model_call(case, monkeypatch):
    import asyncio
    from langgraph.errors import NodeCancelledError
    from report_agent import live_messages
    from report_agent.content_store import ContentStore
    cs, output, criteria = setup(case)
    original = ContentStore.submit_review
    def cancelled(*args, **kwargs):
        raise asyncio.CancelledError('Offline cancellation before original save begins.')
    with bound(cs, assignment(output, criteria)) as (ws, actor, _):
        tools = live_tools(ws)
        answer = await live_answer(ws, tools)
        graph = live_graph(ws, tools)
        monkeypatch.setattr(ContentStore, 'submit_review', cancelled)
        with pytest.raises(NodeCancelledError):
            await graph.ainvoke({'messages': [answer]})
        assert live_messages.current_review_binding(ws, actor) is None
        assert not cs.list_objects('ReviewRecord')
        monkeypatch.setattr(ContentStore, 'submit_review', original)
        result = await graph.ainvoke({'messages': [answer]})
        assert result['messages'][-1].status == 'success'
        assert len(cs.list_objects('ReviewRecord')) == 1


async def test_native_source_receipts_keep_real_source_and_block_selection(case):
    from report_agent import live_messages
    from report_agent.deep_runtime import business_tools
    from report_agent.deep_models import GLMChatOpenAI
    cs, output, criteria = setup(case)
    cs.store.set('manifest', {**cs.store.manifest,
        'sources': [*cs.store.manifest['sources'], {'id': 'second-private-key', 'title': 'Source',
            'content': 'Another fake source. ' * 500, 'coverage': 'complete'}]})
    with bound(cs, assignment(output, criteria)) as (ws, actor, _):
        read = next(f for f in business_tools(ws, 'reviewer', None, None) if f.__name__ == 'read_source_page')
        observations = []
        for index, (source, offset) in enumerate([('s', 0), ('second-private-key', 0), ('second-private-key', 1)]):
            result = read(source, offset=offset, limit=1, runtime=SimpleNamespace(tool_call_id='source-read-'+str(index)))
            observations.append(json.loads(result.content)['receipt_id'])
        model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta')
        try:
            tools = live_tools(ws)
            request = ModelRequest(model=model, tools=tools, state={'messages': []},
                system_message=SystemMessage(content='Original reviewer role.'), messages=[HumanMessage(content='Compare actual source selections.')])
            sent = []
            async def handler(changed):
                packet = json.loads(changed.system_message.content_blocks[-1]['text'])
                directory = [x['read'] for x in packet['actual_read_receipts'][1:]]
                assert all(x['read_kind'] == 'source_material' for x in directory)
                first, second, third = [x['materials'][0] for x in directory]
                assert first['material_scope'] != second['material_scope']
                assert second['material_scope'] == third['material_scope']
                assert first['selection']['ordinals'] == second['selection']['ordinals'] == [0]
                assert third['selection']['ordinals'] == [1]
                assert second['selection']['units'] == 'zero-based text blocks'
                assert second['coverage']['next_offset'] is not None
                assert 'second-private-key' not in encode(packet)
                assert not any(receipt in encode(packet) for receipt in observations)
                return await sdk_request(changed, message(evidence_indexes=[0, 1, 2, 3]), False, sent)
            answer, = (await BusinessBoundary(ws, 'reviewer').awrap_model_call(request, handler)).result
            result = await live_graph(ws, tools).ainvoke({'messages': [answer]})
            assert result['messages'][-1].status == 'success'
            record, = cs.list_objects('ReviewRecord')
            assert {o['receipt_id'] for o in record['payload']['items'][0]['observations']} >= set(observations)
            assert len(sent) == 1
        finally:
            model.root_client.close()
            await model.root_async_client.close()


def test_current_reviewer_has_one_flat_contract_and_rejects_old_payload(case):
    from pydantic import ValidationError
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, _, _):
        tools = live_tools(ws)
        tool, = [t for t in tools if t.name == 'submit_review']
        schema = tool.tool_call_schema.model_json_schema()
        assert 'review' not in schema['properties']
        assert schema['additionalProperties'] is False
        with pytest.raises(ValidationError):
            tool.tool_call_schema.model_validate({'review': {'items': []}})
        with pytest.raises(ValidationError):
            tool.tool_call_schema.model_validate({**message(), 'review': {'items': []}})


def test_current_co_has_no_nested_review_or_unvalidated_extra_fields():
    from deepagents.backends import StateBackend
    from deepagents.middleware.subagents import SubAgentMiddleware, CompiledSubAgent
    from langchain_core.runnables import RunnableLambda
    from pydantic import ValidationError
    from report_agent.content_tasks import task_tool
    middleware = SubAgentMiddleware(backend=StateBackend(), subagents=[CompiledSubAgent(
        name=role, description='Assigned work.', runnable=RunnableLambda(lambda state: state))
        for role in ('reviewer', 'writer', 'layout')])
    original = next(t for t in middleware.tools if t.name == 'task')
    tool = task_tool(original, review_profile='native-reviewer-v2', interface_profile='review-interfaces-v4')
    schema = tool.tool_call_schema.model_json_schema()
    assert 'review' not in schema['properties']
    assert schema['additionalProperties'] is False
    for name in ('snapshot_scope', 'commission_criterion_scopes', 'criterion_scopes', 'artifact_scopes'):
        assert schema['properties'][name]['description']
    with pytest.raises(ValidationError):
        tool.tool_call_schema.model_validate({'subagent_type': 'reviewer', 'description': 'Check.', 'review': {}})
    with pytest.raises(ValidationError):
        tool.tool_call_schema.model_validate({'subagent_type': 'writer', 'description': 'Write.', 'ignored': None})


@pytest.mark.parametrize('strict', [False, True])
async def test_multiple_findings_in_one_response_keep_evidence_and_survive_later_pass(case, strict):
    from report_agent.deep_models import GLMChatOpenAI
    from report_agent.review_status import read_status
    cs, output, criteria = setup(case)
    with bound(cs, assignment(output, criteria)) as (ws, actor, receipt):
        source = cs.list_objects('SourceArtifact')[0]['ref']
        extra_receipt = cs.read_context(actor, source)['receipt_id']
        tools = live_tools(ws)
        model = GLMChatOpenAI(model='deepseek-flash', api_key='offline', base_url='https://model.invalid/beta', deepseek_strict=strict)
        try:
            request = ModelRequest(model=model, tools=tools, state={'messages': []},
                system_message=SystemMessage(content='Current reviewer role.'), messages=[HumanMessage(content='Save actual judgments.')])
            actual = []
            common = dict(verdict='not_satisfied', finding_type='confirmed_defect', finding_locator_state='located',
                finding_impact='Changes the stated risk.', finding_needed_outcome='Correct against actual source.')
            values = [message(**common, finding_description='First actual defect.', evidence_indexes=[0]),
                      message(**common, finding_description='Second actual defect.', evidence_indexes=[0, 1]),
                      message(assessment='Later positive assessment does not withdraw prior defects.')]
            async def handler(changed):
                return await sdk_request(changed, values, strict, actual)
            answer, = (await BusinessBoundary(ws, 'reviewer').awrap_model_call(request, handler)).result
            assert len(answer.tool_calls) == 3 and len(actual) == 1
            result = await live_graph(ws, tools).ainvoke({'messages': [answer]})
            assert all(m.status == 'success' for m in result['messages'][-3:])
            records = cs.list_objects('ReviewRecord')
            assert len(records) == 3
            defects = [r for r in records if r['payload']['items'][0]['findings']]
            assert len(defects) == 2
            assert defects[0]['payload']['items'][0]['observations'][0]['receipt_id'] == receipt
            assert {o['receipt_id'] for o in defects[1]['payload']['items'][0]['observations']} == {receipt, extra_receipt}
            status = read_status(cs, records[0]['payload']['snapshot_ref'], limit=100)
            text = encode(status)
            assert 'First actual defect.' in text and 'Second actual defect.' in text
            assert all(r['ref']['id'] in text for r in defects)
        finally:
            model.root_client.close()
            await model.root_async_client.close()
