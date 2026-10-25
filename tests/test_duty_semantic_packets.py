"""Synthetic paired packet integrity through configured SDK + MockTransport.

The returned fake sentences validate transport/parser preservation only. They do
not prove that a real model would preserve technical uncertainty.
"""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from report_agent.content_models import ContentNode
from report_agent.deep_models import configured_model
from report_agent.store import Store, digest
from report_agent.text_work import output_contract
from report_agent.text_work_revision import QualifierOutput
from report_agent.workspace import Workspace
from duty_probe_semantic_packets import (ASSESS_OBJECTIVE, CASES, INITIAL, KNOWN,
    REVISION_OBJECTIVES, UNKNOWN, capture_semantic, semantic_fake_response)
from test_bounded_deadline import close_model


def record(request, value):
    request.node.user_properties.append(('semantic_packet_evidence', json.dumps(value, ensure_ascii=False)))


def material_objects(packet):
    return [e['object'] for e in packet['evidence'] if 'object' in e]


def normalize_dynamic(packet, observed):
    """Replace only concrete generated identities, never arbitrary UUID/text values.

    Timestamp/hash metadata is returned separately as permitted variation; source
    content and technical payload fields are still compared in full.
    """
    replacements = {}
    for i, obj in enumerate(observed['source_originals']):
        replacements[obj['ref']['id']] = f'original-{i}'
        replacements[obj['owner_id']] = 'original-owner'
    for name in ('saved_calculation', 'original_node'):
        obj = observed.get(name)
        if obj:
            replacements[obj['ref']['id']] = name
            replacements[obj['owner_id']] = 'writer-owner'
            if obj.get('task_id'):
                replacements[obj['task_id']] = 'writer-task'
    replacements[packet['actor']['id']] = 'writer-owner'
    if packet['actor'].get('task_id'):
        replacements[packet['actor']['task_id']] = 'writer-task'
    if observed.get('calculation'):
        replacements[observed['calculation']['receipt_id']] = 'owned-calculation-receipt'
    allowed_metadata = set()
    for index, entry in enumerate(packet['evidence']):
        obj = entry.get('object')
        if obj is None:
            continue
        base = ('evidence', index, 'object')
        assert obj['payload_digest'] == digest(obj['payload'])
        allowed_metadata.update({base + ('created_at',), base + ('payload_digest',)})
        if obj['ref']['type'] == 'SourceArtifact':
            payload = obj['payload']
            # These fixtures are supplied text, not uploaded files with a separate file hash.
            assert payload['file_digest'] == digest(payload['content'])
            assert payload['source_metadata']['text_digest'] == digest(payload['content'])
            allowed_metadata.update({base + ('payload', 'file_digest'),
                                     base + ('payload', 'source_metadata', 'text_digest')})
    ignored = []

    def walk(value, path=()):
        if isinstance(value, dict):
            output = {}
            for k, v in value.items():
                if path + (k,) in allowed_metadata:
                    ignored.append({'path': list(path + (k,)), 'value': v})
                    output[k] = '<recorded-metadata>'
                else:
                    output[k] = walk(v, path + (k,))
            return output
        if isinstance(value, list):
            return [walk(v, path + (i,)) for i, v in enumerate(value)]
        if isinstance(value, str):
            for original, symbolic in sorted(replacements.items(), key=lambda item: -len(item[0])):
                value = value.replace(original, symbolic)
        return value
    return walk(deepcopy(packet)), ignored


def differences(a, b, path=()):
    if type(a) is not type(b):
        return [list(path)]
    if isinstance(a, dict):
        assert a.keys() == b.keys(), (path, a.keys(), b.keys())
        return [p for k in a for p in differences(a[k], b[k], path + (k,))]
    if isinstance(a, list):
        assert len(a) == len(b), path
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in differences(x, y, path + (i,))]
    return [] if a == b else [list(path)]


@pytest.mark.parametrize('family', ['classification', 'qualifier-revision'])
async def test_semantic_pair_uses_native_full_material_and_one_variable(tmp_path, monkeypatch, request, family):
    for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'synthetic-key'}.items():
        monkeypatch.setenv('REPORT_TEXT_TOOL_' + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    cases = CASES[:2] if family == 'classification' else CASES[2:]
    captured = []
    records = []
    try:
        for case in cases:
            folder = tmp_path / case
            store = Store(folder / 'workspace')
            store.initialize({'goal': 'Synthetic probe', 'content_contract': 'hierarchical-review-v1',
                              'review_entrypoint': 'delegated-reviewer-v1',
                              'sources': [{'id': 's', 'title': 'Synthetic initialization',
                                           'content': 'Synthetic fixture initialization.', 'coverage': 'complete'}]})
            workspace = Workspace(store)
            model = configured_model(store, 'text_tool')
            wires = []
            fake = semantic_fake_response(case)

            async def transport(request):
                wire = json.loads(request.content)
                wires.append(wire)
                return httpx.Response(200, json={'id': 'offline-semantic', 'object': 'chat.completion',
                    'created': 1, 'model': wire['model'], 'choices': [{'index': 0, 'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': json.dumps(fake, ensure_ascii=False)}}],
                    'usage': {'prompt_tokens': 19, 'completion_tokens': 1, 'total_tokens': 20}})

            await model.http_async_client._transport.aclose()
            model.http_async_client._transport = httpx.MockTransport(transport)
            model.http_async_client._mounts = {}
            try:
                result = await capture_semantic(workspace, case, folder, model)
            finally:
                await close_model(model)
                (folder / 'wire-requests.json').write_text(json.dumps(wires, ensure_ascii=False, indent=2), 'utf-8')
            observed = result['observations']
            native = observed['independent_candidate_input']
            assert len(wires) == 1 and observed['injected_service_calls'] == 1
            assert wires[0]['messages'][-1]['content'] == native[-1][1]
            assert wires[0]['messages'][0]['content'] == native[0][1]
            packet = json.loads(native[-1][1])
            objects = material_objects(packet)
            for original in observed['source_originals'][1:]:
                assert original in objects, 'Every selected full SourceArtifact must reach the independent service.'
            assert result['tool_result']['payloads'] == [result['tool_result']['payload']]
            if family == 'classification':
                assert packet['objective'] == ASSESS_OBJECTIVE
                assert packet['output_schema'] == output_contract(ContentNode, 1)
                assert observed['saved_calculation'] in objects
                assert observed['saved_calculation']['payload']['result']['total'] == '85'
                assert observed['calculation']['result']['terms'] == [['5', '17']]
                assert result['tool_result']['payload'] == fake
                assert observed['synthetic_fixture_calls'] == 0
            else:
                assert packet['objective'] == REVISION_OBJECTIVES[case]
                assert packet['output_schema'] == output_contract(QualifierOutput, 1)
                assert observed['original_node'] in objects
                assert result['tool_result']['payload'] == {**INITIAL, **fake}
                assert observed['synthetic_fixture_calls'] == 1
            normal, metadata = normalize_dynamic(packet, observed)
            captured.append(normal)
            records.append({'case': case, 'folder': str(folder), 'wire_requests': len(wires),
                'full_independent_input': native, 'normalized_packet': normal,
                'recorded_variable_metadata': metadata, 'actual_tool_result': result['tool_result'],
                'candidate_adopted': observed['candidate_adopted']})
        changed = differences(*captured)
        if family == 'classification':
            # Source IDs/digests may change with payload identity; evidence itself
            # must differ only in the one declared geological description.
            assert len(changed) == 1, changed
            at = changed[0]
            first, second = captured
            for key in at:
                first, second = first[key], second[key]
            assert (first, second) == (KNOWN, UNKNOWN), changed
        else:
            assert changed == [['objective']], changed
        records.append({'actual_material_difference_paths': changed})
    finally:
        record(request, {'family': family, 'records': records, 'live_calls': 0,
                         'semantic_acceptance': False, 'application_changes': 0})
