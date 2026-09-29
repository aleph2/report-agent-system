"""Offline wire, canonical projection and SDK transport tests; no credentials/network."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
from jsonschema.exceptions import ValidationError as SchemaError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_deepseek_flat_probe import (
    BASE, PLAN, URL, OpenAI, httpx, payload_for, read, request_observer, validate_public,
)


def flat_public():
    public = read(BASE / 'max/response.json')
    raw = json.loads(public['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
    for row in raw['criteria']:
        if row['passed']:
            row['gap'] = ''
    public['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(raw, ensure_ascii=False)
    return public, raw


def test_predeclared_control_differences():
    requests = [payload_for(item) for item in PLAN]
    assert all(r['messages'] == requests[0]['messages'] and r['max_tokens'] == 131072 for r in requests)
    assert requests[1] == requests[2]
    a = deepcopy(requests[0])
    a['tools'] = requests[1]['tools']
    assert a == requests[1]
    b = deepcopy(requests[2])
    b['reasoning_effort'] = 'max'
    assert b == requests[3]


def test_only_empty_pass_gap_is_projected():
    public, expected_raw = flat_public()
    payload = payload_for(PLAN[1])
    ids = [r['name'] for r in expected_raw['criteria']]
    raw, canonical, changes = validate_public(public, payload, ids, 'flat')
    assert raw == expected_raw
    assert canonical == read(BASE / 'max/output.json')
    assert len(changes) == sum(r['passed'] for r in raw['criteria'])


@pytest.mark.parametrize('change', ['nonempty_pass_gap', 'missing_fail_gap', 'contradictory_status', 'duplicate_id'])
def test_invalid_results_never_normalized_into_success(change):
    public, raw = flat_public()
    ids = [r['name'] for r in raw['criteria']]
    if change == 'nonempty_pass_gap':
        raw['criteria'][0]['gap'] = 'A real unresolved issue.'
    elif change == 'missing_fail_gap':
        del raw['criteria'][1]['gap']
    elif change == 'contradictory_status':
        raw['criteria'][0]['status'] = 'not_satisfied'
    else:
        raw['criteria'][1]['name'] = ids[0]
    public['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(raw)
    with pytest.raises((ValueError, SchemaError)):
        validate_public(public, payload_for(PLAN[1]), ids, 'flat')


@pytest.mark.parametrize('item_index', [0, 1])
def test_sdk_sends_expected_url_strict_schema_and_preserves_bad_json(tmp_path, item_index):
    payload = payload_for(PLAN[item_index])
    invalid = '{"text":"an "unescaped" quote"}'
    captures = []
    def handle(request):
        captures.append(json.loads(request.read()))
        assert str(request.url) == URL
        return httpx.Response(200, json={
            'id': 'offline-response', 'object': 'chat.completion', 'created': 0,
            'model': 'deepseek-flash',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'offline-tool', 'type': 'function',
                                'function': {'name': 'GraderResponse', 'arguments': invalid}}]}}],
        })
    audit = tmp_path / 'outgoing.json'
    with httpx.Client(transport=httpx.MockTransport(handle),
                      event_hooks={'request': [request_observer(payload, audit)]}) as transport:
        with OpenAI(base_url='https://api.deepseek.com/beta', api_key='offline-placeholder',
                    http_client=transport, max_retries=0) as client:
            request = deepcopy(payload)
            thinking = request.pop('thinking')
            response = client.chat.completions.create(**request, extra_body={'thinking': thinking})
    assert captures == [payload]
    assert response.choices[0].message.tool_calls[0].function.arguments == invalid
    evidence = read(audit)
    assert evidence['correct_url'] and evidence['json_equals_frozen']
    assert evidence['strict_flags'] == [True]
    assert 'offline-placeholder' not in audit.read_text()
    assert set(evidence) == {'observed', 'url', 'correct_url', 'body_sha256', 'json_equals_frozen', 'strict_flags'}
