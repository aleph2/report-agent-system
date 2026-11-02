"""Large public captures move off SQLite without weakening identity or redaction."""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent import prompt_provenance as provenance
from report_agent.errors import ActionRejected
from report_agent.store import Store, digest, encode


def capture_events(store, kind):
    return [event['data'] for event in store.events() if event['kind'] == kind]


def test_large_prompt_capture_is_external_but_logical_digest_and_shape_are_unchanged(tmp_path):
    store = Store(tmp_path)
    text = 'Synthetic prompt context; ' * 12000
    offered = {'model': 'fixture', 'messages': [{'role': 'user', 'content': text}], 'tools': []}
    with provenance.prompt_call(store, 'writer', status='exact', offered=offered):
        pass
    event, = capture_events(store, 'prompt_model_input')
    captured = store.get(event['capture_key'])
    assert captured['public_input'] == offered
    assert event['capture_key'] == 'prompt_capture:' + digest(captured)
    with store.connect() as db:
        raw, = db.execute('SELECT value FROM state WHERE key=?', (event['capture_key'],)).fetchone()
    assert len(raw.encode()) < len(text.encode()) // 10
    assert text not in raw
    assert any(path.is_file() for path in (tmp_path / 'blobs').rglob('*'))


def test_legacy_inline_capture_reads_without_rewriting_history(tmp_path):
    store = Store(tmp_path)
    captured = {'purpose': 'writer', 'call_id': 'historical', 'status': 'exact',
        'public_input': {'messages': [{'role': 'user', 'content': 'Historical capture'}]}}
    key = 'prompt_capture:' + digest(captured)
    with store.connect() as db:
        db.execute('INSERT INTO state VALUES (?,?)', (key, encode(captured)))
    assert store.get(key) == captured
    with store.connect() as db:
        assert db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()[0] == encode(captured)


def test_external_capture_preserves_wire_identity_and_response_fact(tmp_path):
    store = Store(tmp_path)
    payload = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'same call ' * 16000}],
        'tools': [{'type': 'function', 'function': {'name': 'read_source', 'parameters': {'type': 'object'}}}]}
    request = httpx.Request('POST', 'https://fixture.invalid/v1/chat/completions', json=payload)
    request.extensions['report_token_budget'] = (None, 'attempt-test')
    with provenance.prompt_call(store, 'writer', status='exact', offered=payload) as call:
        provenance.bind_wire_payload(payload)
        provenance.admit_prompt_request(request)
        provenance.observe_prompt_request(request)
        final = store.get(call['final_captures'][0])
        assert final['public_input'] == payload
        assert final['body_sha256'] == hashlib.sha256(request.content).hexdigest()
        assert final['final_tool_schema_sha256'] == digest(payload['tools'])
        assert final['attempt_id'] == 'attempt-test'
        provenance.progress_response_fact(store, call,
            SimpleNamespace(result=[AIMessage(id='response-test', content='Done',
                response_metadata={'finish_reason': 'stop'})]), [])
    event, = capture_events(store, 'prompt_response_fact')
    fact = store.get(event['capture_key'])
    assert fact['completed'] is True
    assert fact['final_capture_refs'] == call['final_captures']
    # Existing execution-progress queries require these facts to stay queryable.
    with store.connect() as db:
        assert db.execute("SELECT json_extract(value,'$.ai_message_id') FROM state WHERE key=?",
            (event['capture_key'],)).fetchone()[0] == 'response-test'


def test_capture_files_do_not_save_private_reasoning_or_image_payload(tmp_path):
    store = Store(tmp_path)
    secret = 'synthetic-private-reasoning-do-not-store'
    image = 'data:image/png;base64,SYNTHETIC_IMAGE_DO_NOT_STORE'
    payload = {'messages': [{'role': 'assistant', 'content': 'public ' * 20000,
        'reasoning_content': secret}, {'role': 'user', 'content': [{'type': 'image_url',
            'image_url': {'url': image}}]}]}
    with provenance.prompt_call(store, 'writer', offered=payload):
        pass
    captured = store.get(capture_events(store, 'prompt_model_input')[0]['capture_key'])
    assert captured['public_input'] == provenance.public_projection(payload)
    for path in (tmp_path / 'blobs').rglob('*'):
        if path.is_file():
            raw = path.read_bytes()
            assert secret.encode() not in raw and image.encode() not in raw


def test_corrupt_external_capture_is_not_returned_as_valid_evidence(tmp_path):
    store = Store(tmp_path)
    with provenance.prompt_call(store, 'writer', offered={'messages': [{'role': 'user',
            'content': 'Synthetic capture ' * 20000}]}):
        pass
    key = capture_events(store, 'prompt_model_input')[0]['capture_key']
    files = [path for path in (tmp_path / 'blobs').rglob('*') if path.is_file()]
    assert files, 'Capture must be externalized for this check'
    for path in files:
        path.write_bytes(b'corrupt')
    with pytest.raises((ActionRejected, ValueError), match='(?i)(hash|sha256|integrity|corrupt)'):
        store.get(key)


def test_valid_blob_from_another_capture_cannot_satisfy_original_capture_key(tmp_path):
    store = Store(tmp_path)
    for text in ('first ' * 20000, 'second ' * 20000):
        with provenance.prompt_call(store, 'writer', offered={'messages': [{'role': 'user', 'content': text}]}):
            pass
    first, second = capture_events(store, 'prompt_model_input')
    with store.connect() as db:
        raw1 = json.loads(db.execute('SELECT value FROM state WHERE key=?', (first['capture_key'],)).fetchone()[0])
        raw2 = json.loads(db.execute('SELECT value FROM state WHERE key=?', (second['capture_key'],)).fetchone()[0])
        raw1['capture_blob'] = raw2['capture_blob']
        db.execute('UPDATE state SET value=? WHERE key=?', (encode(raw1), first['capture_key']))
    with pytest.raises((ActionRejected, ValueError), match='(?i)(hash|sha256|digest|integrity|mismatch)'):
        store.get(first['capture_key'])
