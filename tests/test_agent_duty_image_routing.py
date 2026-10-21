"""Default filesystem modality routing through native Writer/Layout and SDK.

Only provider responses and the parent delegation are fake. Each role uses its
actual configured GLM client, platform filesystem tools, application middleware
and SDK serialization. No original data, external network or application repair.
The compatibility assertion is deliberately RED if a text-only client receives
an image; keeping that failure is the purpose of this regression.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import zlib

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_runtime
from report_agent.deep_models import configured_model
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_agent_duty_trace_cases import action, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver
from test_duty_optimizer_adapter import no_external_network
from test_hierarchical_content import seed
from test_task_supervision import ws


ROOT = Path(__file__).resolve().parents[1]
PNG_BASE64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE'
              'QVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')
FINAL = 'Scratch-file routing probe complete. No report or engineering acceptance.'


def source_hashes():
    paths = [Path(__file__), *sorted((ROOT / 'src').rglob('*.py'))]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verified_fixture_png():
    """Validate every chunk and the one RGBA scanline before using test data."""
    data = base64.b64decode(PNG_BASE64, validate=True)
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    chunks, offset = [], 8
    while offset < len(data):
        length = struct.unpack('!I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        crc = struct.unpack('!I', data[offset + 8 + length:offset + 12 + length])[0]
        assert len(body) == length and zlib.crc32(kind + body) & 0xffffffff == crc
        chunks.append((kind, body))
        offset += length + 12
    assert offset == len(data) and [c[0] for c in chunks] == [b'IHDR', b'IDAT', b'IEND']
    assert struct.unpack('!2I5B', chunks[0][1]) == (1, 1, 8, 6, 0, 0, 0)
    assert zlib.decompress(chunks[1][1]) == b'\x00\xff\x00\x00\xff' and chunks[2][1] == b''
    return data


@pytest.mark.parametrize('role,kind', [('writer', 'text'), ('writer', 'image'),
    ('layout', 'text'), ('layout', 'image')],
    ids=['text-control', 'png-text-only-client', 'layout-text-control', 'layout-png-text-only-client'])
async def test_native_writer_filesystem_respects_text_only_model(ws, monkeypatch, request, role, kind):
    # Keep the historical Writer node IDs; Layout is a new pair, not a recount.
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1',
                       'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_' + role.upper() + '_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    monkeypatch.setenv('REPORT_SDK_RETRIES', '5')
    monkeypatch.setenv('REPORT_CONNECT_RETRIES', '0')
    ws.store.set('manifest', {**ws.store.manifest,
        'goal': 'Inspect the synthetic scratch-file transport. No substantive report writing.'})
    activate(ws)
    folder = Path(os.environ.get('REPORT_IMAGE_ROUTING_OUT', str(ws.store.root / 'captures'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    dump(folder / 'source-hashes-before.json', before)
    filename = '/synthetic.png' if kind == 'image' else '/synthetic.txt'
    content = PNG_BASE64 if kind == 'image' else 'Synthetic scratch text: retain every character.'
    png_bytes = verified_fixture_png()
    exchanges, native_calls, parent = [], [], {}
    layout_fixture, content_store = None, None
    if role == 'layout':
        # Explicit synthetic authorization fixture, not a model-produced report.
        content_store, _, _, snapshot, _ = seed(ws)
        layout_fixture = {'snapshot_ref': snapshot, 'originals': content_store.list_objects()}
    model = configured_model(ws.store, role)

    async def provider(http_request):
        assert str(http_request.url) == 'https://offline.invalid/v1/chat/completions'
        wire = json.loads(http_request.content)
        assert wire['model'] == 'glm-5.3'
        names = {t['function']['name'] for t in wire['tools']}
        assert {'write_file', 'read_file'} <= names
        step = len(exchanges)
        assert step < 3, 'Unexpected call beyond the finite write/read/final script'
        if step == 0:
            tool = ('write_file', 'write-scratch', {'file_path': filename, 'content': content})
        elif step == 1:
            tool = ('read_file', 'read-scratch', {'file_path': filename})
        else:
            tool = None
        message = {'role': 'assistant', 'content': '' if tool else FINAL}
        if tool:
            name, call_id, args = tool
            message['tool_calls'] = [{'id': call_id, 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args)}}]
        response = {'id': 'image-route-mock-' + str(step), 'object': 'chat.completion',
            'created': 1, 'model': 'glm-5.3', 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if tool else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
        exchanges.append({'wire': wire, 'response': response})
        dump(folder / 'mock-exchanges.json', exchanges)
        return httpx.Response(200, json=response)

    await model.http_async_client._transport.aclose()
    model.http_async_client._transport = httpx.MockTransport(provider)
    model.http_async_client._mounts = {}

    def receive_parent(messages):
        parent['task_return'] = tool_reply(messages, 'routing-' + role).model_dump()
        return AIMessage(content='Synthetic transport observation only.')

    task_args = {'subagent_type': role,
        'description': 'Inspect the synthetic scratch file using the available filesystem tools.'}
    if layout_fixture:
        task_args['layout_snapshot_ref'] = layout_fixture['snapshot_ref']
    coordinator = Driver(coordinator=[action('task', 'routing-' + role, **task_args), receive_parent])
    unused = Driver()
    selected = traced_model(model, role, native_calls)

    def factory(requested_role):
        if requested_role == 'coordinator':
            return coordinator(requested_role)
        if requested_role == role:
            return selected
        return unused(requested_role)

    requests = RequestBudget(3)
    tokens = TokenBudget(ws.store.root / 'isolated-image-routing-budget.db', 10000, {'glm-5.3': 1000})
    runtime, error, checkpoint_reads = None, None, []
    try:
        with request_budget(requests), token_budget(tokens):
            runtime = await deep_runtime.run_report(ws, factory)
        async with AsyncSqliteSaver.from_conn_string(str(ws.store.root / 'checkpoints.db')) as saver:
            async for checkpoint in saver.alist(None, limit=1000):
                for message in checkpoint.checkpoint.get('channel_values', {}).get('messages', []):
                    if (getattr(message, 'tool_call_id', None) == 'read-scratch'
                            and getattr(message, 'type', None) == 'tool'):
                        checkpoint_reads.append(message.model_dump())
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        await model.http_async_client.aclose()
        await model.root_async_client.close()
        model.root_client.close()
        dump(folder / 'capture.json', {'role': role, 'kind': kind, 'filename': filename, 'input_content': content,
            'layout_authorization_fixture': layout_fixture,
            'layout_originals_unchanged': all(content_store.read(o['ref']) == o for o in layout_fixture['originals']) if layout_fixture else None,
            'layout_saved_tasks': content_store.list_objects('DelegatedTask') if layout_fixture else None,
            'original_png_sha256': hashlib.sha256(png_bytes).hexdigest(),
            'native_calls': native_calls, 'mock_exchanges': exchanges, 'parent': parent,
            'original_checkpoint_read_messages': checkpoint_reads,
            'runtime': runtime, 'error': error, 'request_budget': requests.snapshot(),
            'token_budget': tokens.snapshot(), 'application_source_unchanged': source_hashes() == before,
            'provider_is_mock': True, 'external_network_calls': 0,
            'limits': ['Synthetic parent and provider actions; no real-model semantic behavior.',
                'File content enters state only through the actual public write_file tool.',
                'Layout only: a saved synthetic snapshot explicitly grants the native task scope; no guard is bypassed.',
                'No host-injected files, upload API, original customer image or vision fallback.']})
        dump(folder / 'source-hashes-after.json', source_hashes())
        request.node.user_properties.append(('image_routing_capture', str(folder)))

    assert error is None and runtime['status'] == 'completed', (error, runtime)
    assert source_hashes() == before and not unused.calls
    if layout_fixture:
        assert all(content_store.read(o['ref']) == o for o in layout_fixture['originals'])
        tasks = content_store.list_objects('DelegatedTask')
        assert len(tasks) == 1 and tasks[0]['owner_id'] == 'content:coordinator'
        assert tasks[0]['payload']['role'] == 'layout'
        assert tasks[0]['payload']['layout_snapshot_ref'] == layout_fixture['snapshot_ref']
    assert len(exchanges) == len(native_calls) == requests.count == 3
    assert tokens.snapshot()['recorded_tokens'] == 6
    assert tokens.snapshot()['reserved_or_unknown_upper_bounds'] == 0
    assert tokens.snapshot()['attempt_states'] == {'settled': 3}
    native_reads = [m['data'] for m in native_calls[-1]['messages'][0]
                    if m['type'] == 'tool' and m['data']['tool_call_id'] == 'read-scratch']
    assert len(native_reads) == 1 and native_reads[0]['status'] == 'success'
    wire_reads = [m for m in exchanges[-1]['wire']['messages']
                  if m['role'] == 'tool' and m['tool_call_id'] == 'read-scratch']
    assert len(wire_reads) == 1
    image_urls = [b['image_url']['url'] for e in exchanges for m in e['wire']['messages']
                  if isinstance(m.get('content'), list) for b in m['content'] if b.get('type') == 'image_url']
    if kind == 'text':
        assert content in wire_reads[0]['content']
        assert isinstance(native_reads[0]['content'], str)
    else:
        # The historical diagnostic required an image on the wire and then
        # prohibited it. Preserve the valid read witness in original checkpoint
        # state, independently of the model-specific transmitted view.
        blocks = [block for message in checkpoint_reads if isinstance(message['content'], list)
                  for block in message['content'] if isinstance(block, dict) and block.get('type') == 'image']
        assert blocks and all(base64.b64decode(block['base64'], validate=True) == png_bytes for block in blocks)
        if not image_urls:
            notice = str(wire_reads[0]['content'])
            assert filename in notice and 'was not attached' in notice and 'does not support image' in notice, notice
    # Stable capability oracle: GLM-5.3 accepts text only. Do not relax this
    # assertion to count exact transmission as successful model compatibility.
    assert image_urls == [], 'TEXT_ONLY_MODEL_RECEIVED_IMAGE: default read_file bypasses the vision-tool boundary'
