"""Small explicit changes from the reviewed actual03 remediation plan."""
import json
import os

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent.model_config import load_mixed_services, bind_role_services
from report_agent.deep_models import configured_model
from report_agent.prompt_sources import load_prompt
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_role_generation_config import configured, close_sync
from test_prompt_native_sdk_inputs import completion
from test_task_supervision import ws

SETTING = 'REPORT_REVIEWER_REASONING_EFFORT'


async def test_reviewer_only_high_binds_and_reaches_sdk_without_co_override(configured, monkeypatch):
    store, path = configured
    monkeypatch.delenv('REPORT_COORDINATOR_REASONING_EFFORT', raising=False)
    monkeypatch.delenv(SETTING, raising=False)
    path.write_text(path.read_text() + SETTING + '=high\n')
    load_mixed_services(path)
    bind_role_services(store)
    assert store.get('role_generation') is not None
    assert store.get('role_generation')['reviewer']['reasoning_effort'] == 'high'
    sent = {}
    for role in ('coordinator', 'reviewer', 'text_tool', 'writer', 'layout'):
        model = configured_model(store, role)
        async def receive(request, role=role):
            sent[role] = json.loads(request.content)
            return completion(request)
        model.http_async_client._transport = httpx.MockTransport(receive)
        model.http_async_client._mounts.clear()
        try:
            await model.ainvoke([HumanMessage('Offline role configuration check.')])
        finally:
            await model.http_async_client.aclose()
            close_sync(model)
    assert sent['reviewer']['reasoning_effort'] == 'high'
    assert sent['reviewer']['max_tokens'] == 65536
    assert sent['coordinator']['reasoning_effort'] == sent['text_tool']['reasoning_effort'] == 'max'
    assert sent['writer']['reasoning_effort'] == sent['layout']['reasoning_effort'] == 'high'
    monkeypatch.setenv(SETTING, 'max')
    with pytest.raises(RuntimeError, match='GENERATION.*FRESH'):
        bind_role_services(store)


def test_invalid_reviewer_override_does_not_mutate_environment(configured, monkeypatch):
    _, path = configured
    monkeypatch.delenv(SETTING, raising=False)
    path.write_text(path.read_text() + SETTING + '=maximum\n')
    before = dict(os.environ)
    with pytest.raises(ValueError, match='REASONING_EFFORT_INVALID'):
        load_mixed_services(path)
    assert dict(os.environ) == before


def test_reviewer_override_cannot_reinterpret_old_executed_case(configured, monkeypatch):
    store, _ = configured
    monkeypatch.delenv(SETTING, raising=False)
    bind_role_services(store)
    store.event('deep_model_request', {'role': 'reviewer'})
    monkeypatch.setenv(SETTING, 'high')
    with pytest.raises(RuntimeError, match='GENERATION.*FRESH'):
        bind_role_services(store)
    assert store.get('role_generation') is None


def test_v4_word_help_exposes_existing_exact_declaration_path(case):
    from report_agent.hierarchical_tools import content_tools
    from langchain_core.tools import StructuredTool
    functions = content_tools(Workspace(case[0].store), 'coordinator')
    function = next(t for t in functions if getattr(t, '__name__', None) == 'export_content_snapshot')
    tool = StructuredTool.from_function(function)
    assert 'exactly one' in tool.description.lower()
    assert 'member_refs' in tool.description
    assert tool.description == load_prompt('export-content-snapshot-v4').strip()
    schema = tool.tool_call_schema.model_json_schema()
    assert {'snapshot_ref', 'deliverable'} <= schema['properties'].keys()
    assert 'exactly one' in tool.description.lower()
    assert 'member_refs' in tool.description
    from report_agent.prompt_sources import source_manifest
    from langchain_core.utils.function_calling import convert_to_openai_tool
    manifest = source_manifest(case[0].store, ['export-content-snapshot-v4'],
        {'tools': [convert_to_openai_tool(tool)]})
    assert manifest['unresolved_sources'] == []
    assert manifest['files'][0]['offered_match'] == 'trimmed_literal'


async def test_writer_rejects_missing_typed_sources_then_succeeds_with_explicit_refs(ws):
    from report_agent.content_tasks import delegated_task
    from report_agent.text_work import produce
    from report_agent.errors import ActionRejected
    from test_prepared_material import setup, Model, payload, writer_call
    _, source = setup(ws)
    model = Model(json.dumps(payload(source)))
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        with pytest.raises(ActionRejected, match='SOURCE_POOL_EMPTY'):
            await produce(ws, actor, model, 'missing-binding', 'Use '+source['id'],
                'Evidence', source_selections=[{'source_id': 's'}])
        assert not model.calls  # First rejection is local, before the text producer.
        corrected = await produce(ws, actor, model, 'explicit-binding', 'Retain actual evidence',
            'Evidence', source_selections=[{'source_id': 's'}], source_version_refs=[source])
        assert corrected['text_work_id'] and len(model.calls) == 1
