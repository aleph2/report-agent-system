"""Native schema feedback and checkpoint recovery, with no external model calls."""
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import TypeAdapter, ValidationError

from report_agent import deep_runtime
from report_agent.content_inputs import CommitObject
from report_agent.hierarchical_tools import content_tools
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import ws, seed


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    def forbidden(*args, **kwargs):
        pytest.fail('NETWORK_FORBIDDEN')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'send', forbidden)


def node(key):
    return {'client_key': key, 'type': 'ContentNode', 'payload': {
        'kind': 'block', 'body': {'text': 'A source-grounded test paragraph.'},
        'qualifiers': {}, 'claim_kind': 'fact'}}


def test_public_tool_schema_exposes_existing_shapes(ws):
    function = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'commit_objects')
    schema = convert_to_openai_tool(StructuredTool.from_function(function))
    text = json.dumps(schema)
    for required in ('requirement_refs', 'Requirement', 'SourceArtifact', 'claim_kind',
                     'adopted_during_generation', 'client_key', 'qualifiers', 'oneOf'):
        assert required in text
    assert 'source IDs or SourceArtifact refs are not Requirement refs' in text


@pytest.mark.parametrize('field,value', [('kind', 'cover'), ('qualifiers', ['note'])])
def test_invalid_payload_types_exposed_before_execution(field, value):
    obj = node('block')
    obj['payload'][field] = value
    with pytest.raises(ValidationError):
        TypeAdapter(CommitObject).validate_python(obj)


async def test_batch_refs_survive_native_tool_validation(ws):
    cs, _, _, _, _ = seed(ws)
    before = len(cs.list_objects())
    objects = [node('parent'), node('child'), {'client_key': 'link', 'type': 'Relation', 'payload': {
        'subject_ref': {'client_key': 'parent'}, 'object_ref': {'client_key': 'child'},
        'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'}}]
    driver = Driver(coordinator=[invoke('commit_objects', operation_id='batch-test', objects=objects), AIMessage(content='Saved.')])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None
    assert len(cs.list_objects()) == before + 3
    relation = cs.list_objects('Relation')[-1]['payload']
    assert relation['subject_ref']['type'] == relation['object_ref']['type'] == 'ContentNode'


async def test_native_checkpoint_patches_bad_json_without_executing_or_repairing_it(ws):
    cs, _, _, _, _ = seed(ws)
    before = len(cs.list_objects())
    malformed = AIMessage(content='', invalid_tool_calls=[{
        'id': 'invalid-original', 'name': 'commit_objects',
        'args': '{"operation_id":"bad","objects":[}', 'error': 'Expecting value'}])
    first = Driver(coordinator=[malformed])
    stopped = await deep_runtime.run_report(ws, first)
    assert stopped['status'] == 'needs_attention'
    assert len(cs.list_objects()) == before

    def corrected(messages):
        originals = [m for m in messages if isinstance(m, AIMessage) and m.invalid_tool_calls]
        assert originals[-1].invalid_tool_calls[0]['args'] == malformed.invalid_tool_calls[0]['args']
        errors = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == 'invalid-original']
        assert len(errors) == 1
        assert errors[0].status == 'error'
        assert 'malformed or truncated' in errors[0].content
        return invoke('commit_objects', operation_id='corrected-new-call', objects=[node('fresh')])

    resumed = Driver(coordinator=[None, corrected, AIMessage(content='Saved after observed format feedback.')])
    result = await deep_runtime.run_report(ws, resumed)
    assert result['last_error'] is None
    assert len(cs.list_objects()) == before + 1
    with ws.store.connect() as db:
        assert not db.execute('SELECT 1 FROM content_operations WHERE operation_id=?', ('bad',)).fetchone()
        assert db.execute('SELECT 1 FROM content_operations WHERE operation_id=?', ('corrected-new-call',)).fetchone()
