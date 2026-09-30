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
from report_agent.tool_argument_feedback import InvalidToolFeedback, diagnostic_messages
from test_deep_runtime import Driver, invoke, call
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


async def test_native_checkpoint_patches_bad_json_without_executing_or_repairing_it(ws, monkeypatch):
    cs, _, _, _, _ = seed(ws)
    before = len(cs.list_objects())
    malformed = AIMessage(content='', invalid_tool_calls=[{
        'id': 'invalid-original', 'name': 'commit_objects',
        'args': '{"operation_id":"bad","objects":[}', 'error': 'Expecting value'}])
    first = Driver(coordinator=[malformed])
    async def historical_end(self, state, runtime):
        return None
    with monkeypatch.context() as patch:
        patch.setattr(InvalidToolFeedback, 'aafter_model', historical_end)
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
        diagnostic = json.loads(errors[0].content)
        assert diagnostic['execution_state'] == 'not_executed'
        assert diagnostic['parser_diagnostic']['character_offset'] == 33
        return invoke('commit_objects', operation_id='corrected-new-call', objects=[node('fresh')])

    resumed = Driver(coordinator=[None, corrected, AIMessage(content='Saved after observed format feedback.')])
    result = await deep_runtime.run_report(ws, resumed)
    assert result['last_error'] is None
    assert len(cs.list_objects()) == before + 1
    with ws.store.connect() as db:
        assert not db.execute('SELECT 1 FROM content_operations WHERE operation_id=?', ('bad',)).fetchone()
        assert db.execute('SELECT 1 FROM content_operations WHERE operation_id=?', ('corrected-new-call',)).fetchone()


def test_diagnostics_only_enrich_native_invalid_call_feedback():
    bad = AIMessage(content='', invalid_tool_calls=[{
        'id': 'bad', 'name': 'commit_objects', 'args': '{"x":}', 'error': 'parse error'}])
    native = ToolMessage(content='Native invalid-call feedback.', tool_call_id='bad', status='error')
    unrelated = ToolMessage(content='Unknown execution outcome.', tool_call_id='other', status='error')
    good = ToolMessage(content='Saved.', tool_call_id='good', status='success')
    original = [bad, native, unrelated, good]
    updated = diagnostic_messages(original)
    assert updated[0] is bad
    assert updated[2] is unrelated and updated[3] is good
    assert native.content == 'Native invalid-call feedback.'
    info = json.loads(updated[1].content)
    assert info['native_feedback'] == native.content
    assert info['parser_diagnostic'] == {'message': 'Expecting value', 'line': 1, 'column': 6, 'character_offset': 5}
    twice = diagnostic_messages(updated)
    assert twice[1].content == updated[1].content


async def test_invalid_call_returns_feedback_in_same_run_and_model_chooses_correction(ws):
    cs, _, _, _, _ = seed(ws)
    before = len(cs.list_objects())
    invalid = AIMessage(content='', invalid_tool_calls=[{
        'id': 'bad-json', 'name': 'commit_objects', 'args': '{"objects":[}', 'error': 'parse error'}])
    def choose(messages):
        feedback = next(m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == 'bad-json')
        assert feedback.status == 'error'
        assert json.loads(feedback.content)['execution_state'] == 'not_executed'
        return invoke('commit_objects', operation_id='chosen-correction', objects=[node('fixed')])
    driver = Driver(coordinator=[invalid, choose, AIMessage(content='Saved.')])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(driver.calls) == 3
    assert len(cs.list_objects()) == before + 1


async def test_valid_sibling_executes_once_and_agent_may_decline_invalid_action(ws):
    cs, _, _, _, _ = seed(ws)
    before = len(cs.list_objects())
    mixed = AIMessage(content='',
        tool_calls=[call('commit_objects', {'operation_id': 'valid-sibling', 'objects': [node('valid')]}, 'valid-call')],
        invalid_tool_calls=[{'id': 'invalid-sibling', 'name': 'commit_objects', 'args': '{', 'error': 'parse error'}])
    def decline(messages):
        outcomes = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
        assert outcomes['valid-call'].status == 'success'
        assert outcomes['invalid-sibling'].status == 'error'
        return AIMessage(content='I will retain the unresolved action; no further tool call.')
    driver = Driver(coordinator=[mixed, decline])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert result['status'] == 'needs_attention'
    assert len(driver.calls) == 2
    assert len(cs.list_objects()) == before + 1
