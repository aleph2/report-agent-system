"""Transport and native validation tests; no model-quality evidence."""
import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.tool_transport import decode_object_arguments
from test_deep_runtime import Driver, invoke, observation, events
from test_hierarchical_content import ws, seed, review_item, submission


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    def denied(*a, **k):
        pytest.fail('NETWORK_FORBIDDEN')
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)


SCHEMA = {'$defs': {'Ref': {'type': 'object'}}, 'properties': {
    'ref': {'anyOf': [{'$ref': '#/$defs/Ref'}, {'type': 'null'}]},
    'text': {'anyOf': [{'type': 'object'}, {'type': 'string'}]},
    'unknown': {}, 'missing': {'$ref': '#/$defs/Missing'}}}


@pytest.mark.parametrize('value', ['[]', '1', 'null', '"{}"', "{'id':1}",
    '<parameter>1</parameter>', '{"a":1} trailing', '{"a":1,"a":2}',
    '{"a":{"x":1,"x":2}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'])
def test_ambiguous_or_nonobject_json_not_repaired(value):
    args = {'ref': value}
    assert decode_object_arguments(args, SCHEMA) == (args, [])


def test_schema_driven_once_only_no_mutation():
    args = {k: '{"id":"x","nested":"{}"}' for k in ('ref', 'text', 'unknown', 'missing', 'extra')}
    before = deepcopy(args)
    decoded, fields = decode_object_arguments(args, SCHEMA)
    assert fields == ['ref']
    assert decoded['ref'] == {'id': 'x', 'nested': '{}'}
    assert all(decoded[k] == before[k] for k in args if k != 'ref')
    assert args == before


async def test_native_review_transport_preserves_actor_receipt_and_idempotency(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    captured = {}
    def save(messages):
        receipt = observation(messages, 'read_context')['receipt_id']
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], receipt))
        captured['review'] = data
        return invoke('submit_review', operation_id='same-review', review=json.dumps(data))
    def repeat(messages):
        captured['saved'] = observation(messages, 'submit_review')
        return invoke('submit_review', operation_id='same-review', review=captured['review'])
    def verify(messages):
        assert observation(messages, 'submit_review') == captured['saved']
        return AIMessage(content='Saved scoped test review.')
    driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Inspect synthetic claim.'),
                                 AIMessage(content='Done.')],
        reviewer=[invoke('read_context', target_ref=json.dumps(refs['claim'])), save, repeat, verify])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    records = cs.list_objects('ReviewRecord')
    assert len(records) == 1
    assert records[0]['owner_id'].startswith('content:reviewer:')
    assert [e['fields'] for e in events(ws, 'deep_tool_argument_decoded')] == [['target_ref'], ['review']]
    raw = [e for e in events(ws, 'deep_tool_start') if e['tool'] == 'submit_review']
    assert isinstance(raw[0]['arguments']['review'], str)
    assert isinstance(raw[1]['arguments']['review'], dict)


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
    cs, actor, refs, snapshot, _ = seed(ws)
    data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
    if fault == 'missing':
        del data['items']
    elif fault == 'unknown':
        data['owner_id'] = 'content:coordinator'
    elif fault == 'wrong_version_type':
        data['snapshot_ref'] = {**snapshot, 'version': '1'}
    elif fault == 'missing_version':
        data['snapshot_ref'] = {**snapshot, 'version': 999}
    elif fault == 'foreign_receipt':
        data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
    def rejected(messages):
        msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
        assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
        return AIMessage(content='Rejected; no review saved.')
    driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                 AIMessage(content='Done.')],
        reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert cs.list_objects('ReviewRecord') == []
