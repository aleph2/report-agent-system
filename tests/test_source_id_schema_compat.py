"""Source tool schemas remain stable for historical discovery profiles."""
import json
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.deep_runtime import business_tools
from report_agent.store import Store
from report_agent.tool_discovery import bind_profile
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case


@pytest.mark.parametrize('profile', [None, 'agent-search-v1', 'agent-search-v2'])
def test_schema_is_versioned_by_bound_discovery_profile(tmp_path, profile):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic', 'sources': [
        {'id': 'source', 'title': 'Source', 'content': 'test', 'coverage': 'complete'}]})
    bind_profile(store, profile)
    tool = next(t for t in business_tools(Workspace(store), 'coordinator', None, None)
                if getattr(t, '__name__', None) == 'read_source_page')
    got = convert_to_openai_tool(StructuredTool.from_function(tool))
    golden = json.loads((Path(__file__).parent / 'fixtures/delegation-prompt-full-role-v1.json').read_text())
    expected = next(t for t in golden['tools'] if t['function']['name'] == 'read_source_page')
    if profile == 'agent-search-v2':
        expected['function']['parameters']['properties']['source_id']['description'] = (
            'Exact source catalog ID from project_status or an authorized SourceArtifact payload.source_id; '
            'not SourceArtifact.ref.id.')
    assert got == expected


def test_manifest_without_bound_profile_cannot_enable_new_schema(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic', 'tool_discovery_profile': 'agent-search-v2', 'sources': [
        {'id': 'source', 'title': 'Source', 'content': 'test', 'coverage': 'complete'}]})
    tool = next(t for t in business_tools(Workspace(store), 'coordinator', None, None)
                if getattr(t, '__name__', None) == 'read_source_page')
    got = convert_to_openai_tool(StructuredTool.from_function(tool))
    assert 'description' not in got['function']['parameters']['properties']['source_id']


async def test_fresh_v2_sdk_wire_preserves_schema_and_correctable_error(case):
    import httpx
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.prompt_provenance import public_projection
    from report_agent.store import digest
    from test_bounded_review import Model
    from test_prompt_native_sdk_inputs import completion

    cs, *_ = case
    store = cs.store
    store.set('manifest', {**store.manifest, 'tool_discovery_profile': 'agent-search-v2'})
    workspace = Workspace(store)
    models, wires = {}, []

    def factory(role):
        if role == 'text_tool':
            return Model('synthetic')
        if role in models:
            return models[role]
        client = model_async_client(store, role)
        def transport(request):
            body = json.loads(request.content)
            wires.append((role, body))
            assert role == 'coordinator'
            step = len(wires) - 1
            if step == 0:
                return completion(request, '', ('search_tools', {'query': 'read_source_page'}))
            if step in (1, 3):
                if step == 3:
                    contents = [m.get('content', '') for m in body['messages'] if m['role'] == 'tool']
                    assert any('SOURCE_NOT_IN_PROJECT' in str(x) and 'SourceArtifact.ref.id' in str(x) for x in contents)
                return completion(request, '', ('select_tools', {'names': ['read_source_page']}))
            if step in (2, 4):
                tool = next(t for t in body['tools'] if t['function']['name'] == 'read_source_page')
                desc = tool['function']['parameters']['properties']['source_id']['description']
                assert 'SourceArtifact.ref.id' in desc
                return completion(request, '', ('read_source_page', {'source_id': 'wrong-object-id' if step == 2 else 's'}))
            return completion(request, 'done')
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False, http_async_client=client,
            max_retries=0, disable_streaming=True)
        return models[role]

    try:
        result = await deep_runtime.run_report(workspace, factory)
        assert result['last_error'] is None, result['last_error']
        assert len(wires) == 6
        events = [e for e in store.events() if e['kind'] == 'prompt_final_http_input']
        captures = [store.get(e['data']['capture_key']) for e in events]
        assert [c['final_tool_schema_sha256'] for c in captures] == [
            digest(public_projection(body)['tools']) for _, body in wires]
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()



async def test_v2_reopen_rejects_changed_source_schema(case, monkeypatch):
    from report_agent import deep_runtime
    from report_agent.errors import ActionRejected
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver

    cs, *_ = case
    store = cs.store
    store.set('manifest', {**store.manifest, 'tool_discovery_profile': 'agent-search-v2'})
    workspace = Workspace(store)
    async with deep_runtime.project_agent(workspace, Driver(coordinator=[])):
        pass
    original = deep_runtime.business_tools

    def changed(ws, role, knowledge, text_model):
        tools = original(ws, role, knowledge, text_model)
        if role == 'coordinator':
            tool = next(t for t in tools if getattr(t, '__name__', None) == 'read_source_page')
            tool.__annotations__['source_id'] = str
        return tools

    monkeypatch.setattr(deep_runtime, 'business_tools', changed)
    reopened = Workspace(Store(store.root))
    with pytest.raises(ActionRejected, match='TOOL_DISCOVERY_REGISTRY_MISMATCH'):
        async with deep_runtime.project_agent(reopened, Driver(coordinator=[])):
            pass
