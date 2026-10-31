"""Prompt-management evidence only: native inputs stay unchanged, no paid calls.

The independent oracle is the configured source file and the captured SDK body,
not a second prompt renderer. These tests do not establish model autonomy.
"""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import SystemMessage

from report_agent.hierarchical_tools import role_prompt
from report_agent.prompt_provenance import (
    AgentPromptBoundary, append_declared_system, bind_wire_payload,
    observe_prompt_request, prompt_call, public_projection,
)
from report_agent.prompt_sources import RULES, load_prompt
from test_hierarchical_content import ws
from test_reviewer_native_profile import native


def captures(store, kind):
    return [store.get(event['data']['capture_key']) for event in store.events()
            if event['kind'] == kind]


def test_role_first_paragraph_is_linked_only_at_task_description(tmp_path, monkeypatch):
    from report_agent import prompt_sources
    first, rest = 'Writer fixture responsibility.', 'Private-to-role detailed fixture.'
    text = first + '\n\n' + rest
    for name in ('agent-writer', 'agent-common'):
        (tmp_path / (name + '.md')).write_text(text, encoding='utf-8')
    monkeypatch.setattr(prompt_sources, 'RULES', tmp_path)
    offered = {'messages': [{'role': 'user', 'content': first}], 'tools': [
        {'function': {'name': 'task', 'description': first,
                      'parameters': {'properties': {'description': {'description': first}}}}},
        {'function': {'name': 'other_tool', 'description': first}}]}
    before = json.dumps(offered)
    manifest = prompt_sources.source_manifest(None, ['agent-writer', 'agent-common'], offered)
    writer, common = manifest['files']
    match, = writer['matched_locations']
    assert match == {'path': 'tools/0/function/description', 'role': 'tool_definition',
                     'match': 'first_paragraph_literal', 'selector': 'first_paragraph',
                     'text_sha256': hashlib.sha256(first.encode()).hexdigest(), 'characters': len(first)}
    assert writer['file_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert writer['offered_match'] == 'first_paragraph_literal'
    assert not common['matched_locations'] and common['offered_match'] == 'not_observed'
    assert manifest['unresolved_sources'] == ['agent-common']
    assert json.dumps(offered) == before


@pytest.mark.parametrize('purpose,source', [
    ('text-work', 'text-work'), ('qualifier-work', 'qualifier-work'),
    ('evidence-analysis', 'evidence-analysis'), ('artifact-analysis', 'artifact-analysis'),
    ('learning-analysis', 'learning-analysis'), ('working_summary', 'working-summary'),
    ('source_vision', 'source-vision'), ('experience_optimizer', 'experience-optimizer'),
])
def test_actual_call_links_source_version_and_same_final_public_input(ws, purpose, source):
    """Purpose is not the shared model-service role; source identity is recoverable."""
    payload = {'model': 'fixture-model', 'messages': [
        {'role': 'system', 'content': load_prompt(source)},
        {'role': 'user', 'content': 'A fixed synthetic task; no new business policy.'}],
        'tools': []}
    before = json.loads(json.dumps(payload))
    with prompt_call(ws.store, purpose, sources=[source], status='exact', offered=payload):
        bind_wire_payload(payload)
        request = httpx.Request('POST', 'https://fixture.invalid/v1/chat/completions', json=payload)
        observe_prompt_request(request, ws.store, 'shared-model-service')
    offered, = captures(ws.store, 'prompt_model_input')
    final, = captures(ws.store, 'prompt_final_http_input')
    manifest = offered['source_manifest']
    entry, = manifest['files']
    assert entry['name'] == source
    assert entry['text_sha256'] == hashlib.sha256(load_prompt(source).encode()).hexdigest()
    assert entry['file_sha256'] == hashlib.sha256((RULES / (source + '.md')).read_bytes()).hexdigest()
    assert ws.store.get(entry['snapshot_key'])['text'] == load_prompt(source)
    assert final['source_manifest'] == manifest
    assert final['call_id'] == offered['call_id']
    assert final['purpose'] == purpose
    assert final['public_input'] == before == payload
    assert final['body_sha256'] == hashlib.sha256(request.content).hexdigest()
    assert manifest['framework_versions']['deepagents'] == '0.7.19'


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
async def test_native_role_capture_names_exact_sources_without_changing_system(ws, role):
    native(ws)
    expected = role_prompt(role)
    names = ['agent-common', 'agent-' + role]
    request = SimpleNamespace(system_message=SystemMessage(expected), messages=[], tools=[])
    request.override = lambda **changes: SimpleNamespace(**{**request.__dict__, **changes})
    seen = []
    async def handler(actual):
        seen.append(actual.system_message.text)
        return 'same-native-result'
    assert await AgentPromptBoundary(ws, role).awrap_model_call(request, handler) == 'same-native-result'
    assert seen == [expected]
    capture, = captures(ws.store, 'prompt_model_input')
    files = {entry['name']: entry for entry in capture['source_manifest']['files']}
    assert set(names) <= files.keys()
    for name in names:
        assert files[name]['text_sha256'] == hashlib.sha256(load_prompt(name).encode()).hexdigest()


def test_unknown_source_is_an_explicit_gap_not_a_fake_file_or_transport_veto(ws):
    payload = {'messages': [{'role': 'user', 'content': 'Fixture only.'}]}
    with prompt_call(ws.store, 'custom_fixture', sources=['not-a-packaged-prompt'], offered=payload):
        bind_wire_payload(payload)
        observe_prompt_request(httpx.Request('POST', 'https://fixture.invalid', json=payload), ws.store)
    value, = captures(ws.store, 'prompt_final_http_input')
    assert value['source_manifest']['files'] == []
    assert 'not-a-packaged-prompt' in value['source_manifest']['unresolved_sources']
    assert value['status'] == 'unexplained'
    assert value['public_input'] == payload


def test_source_version_is_captured_at_call_entry_and_can_be_recovered(ws, monkeypatch, tmp_path):
    import report_agent.prompt_sources as sources
    source = tmp_path / 'fixture-source.md'
    source.write_text('First configured instruction.\n', encoding='utf-8')
    monkeypatch.setattr(sources, 'RULES', tmp_path)
    payload = {'messages': [{'role': 'system', 'content': sources.load_prompt('fixture-source')}]}
    with prompt_call(ws.store, 'fixture', sources=['fixture-source'], offered=payload):
        source.write_text('A later edit is not the already offered source.\n', encoding='utf-8')
        bind_wire_payload(payload)
        observe_prompt_request(httpx.Request('POST', 'https://fixture.invalid', json=payload), ws.store)
    first, = captures(ws.store, 'prompt_model_input')
    final, = captures(ws.store, 'prompt_final_http_input')
    assert final['source_manifest'] == first['source_manifest']
    entry, = first['source_manifest']['files']
    assert entry['text_sha256'] == hashlib.sha256(b'First configured instruction.\n').hexdigest()
    assert ws.store.get(entry['snapshot_key'])['text'] == 'First configured instruction.\n'


async def test_declared_dynamic_version_refs_are_audit_metadata_not_wire_instructions(ws):
    native(ws)
    original = role_prompt('coordinator')
    request = SimpleNamespace(system_message=SystemMessage(original), messages=[], tools=[])
    request.override = lambda **changes: SimpleNamespace(**{**request.__dict__, **changes})
    references = {'instruction_refs': [{'id': 'customer-scope', 'version': 2}],
                  'instruction_digest': 'exact-host-packet-digest'}
    current = append_declared_system(request, 'Current fixture authority.',
        'task_context/current_server_bound_state', references=references)
    seen = []
    async def handler(actual):
        seen.append(actual.system_message.content_blocks)
    await AgentPromptBoundary(ws, 'coordinator').awrap_model_call(current, handler)
    assert seen == [[*([{'type': 'text', 'text': original}] if original else []),
                     {'type': 'text', 'text': 'Current fixture authority.'}]]
    value, = captures(ws.store, 'prompt_model_input')
    declared = next(s for s in value['sources'] if s['source'] == 'task_context/current_server_bound_state')
    assert declared['references'] == references
    assert 'customer-scope' not in json.dumps(seen)


def test_private_fields_and_headers_are_not_added_to_source_records(ws):
    payload = {'messages': [{'role': 'assistant', 'content': 'Public fixture answer.',
        'reasoning_content': 'private-canary-not-to-export'}], 'tools': []}
    request = httpx.Request('POST', 'https://fixture.invalid', json=payload,
        headers={'Authorization': 'Bearer secret-header-canary'})
    with prompt_call(ws.store, 'source_vision', sources=['source-vision'], offered=payload):
        bind_wire_payload(payload)
        observe_prompt_request(request, ws.store)
    value, = captures(ws.store, 'prompt_final_http_input')
    text = json.dumps(value)
    assert 'private-canary-not-to-export' not in text
    assert 'secret-header-canary' not in text
    assert value['public_input'] == public_projection(payload)
    assert value['source_manifest']['files']


def test_a_new_file_version_cannot_be_presented_as_the_already_assembled_prompt(ws, monkeypatch, tmp_path):
    import report_agent.prompt_sources as sources
    path = tmp_path / 'fixture-source.md'
    path.write_text('Old instruction actually assembled.', encoding='utf-8')
    payload = {'messages': [{'role': 'system', 'content': path.read_text()}]}
    path.write_text('New instruction not used in this request.', encoding='utf-8')
    monkeypatch.setattr(sources, 'RULES', tmp_path)
    with prompt_call(ws.store, 'fixture', sources=['fixture-source'], offered=payload):
        observe_prompt_request(httpx.Request('POST', 'https://fixture.invalid', json=payload), ws.store)
    value, = captures(ws.store, 'prompt_final_http_input')
    entry, = value['source_manifest']['files']
    assert entry['offered_match'] == 'not_observed'
    assert 'fixture-source' in value['source_manifest']['unresolved_sources']
    assert value['public_input'] == payload


def test_user_quotation_of_new_source_is_not_adoption_by_the_current_system(ws, monkeypatch, tmp_path):
    import report_agent.prompt_sources as sources
    path = tmp_path / 'fixture-source.md'
    path.write_text('New instruction quoted by the user.', encoding='utf-8')
    monkeypatch.setattr(sources, 'RULES', tmp_path)
    payload = {'messages': [{'role':'system', 'content':'Old assembled instruction.'},
                           {'role':'user', 'content':path.read_text()}]}
    with prompt_call(ws.store, 'fixture', sources=['fixture-source'], offered=payload):
        observe_prompt_request(httpx.Request('POST', 'https://fixture.invalid', json=payload), ws.store)
    value, = captures(ws.store, 'prompt_final_http_input')
    entry, = value['source_manifest']['files']
    assert entry['offered_match'] == 'not_observed'
    assert entry['matched_locations'] == [{'path':'messages/1/content', 'role':'user', 'match':'literal'}]
    assert 'fixture-source' in value['source_manifest']['unresolved_sources']


@pytest.mark.parametrize('failure', ['source_read', 'snapshot_write'])
def test_source_snapshot_diagnostics_cannot_turn_a_successful_call_into_a_failure(ws, monkeypatch, failure):
    import report_agent.prompt_sources as sources
    payload = {'messages': [{'role': 'system', 'content': load_prompt('source-vision')}]}
    if failure == 'source_read':
        original = sources.Path.read_bytes
        def read(path):
            if path.name == 'source-vision.md':
                raise PermissionError('Synthetic source diagnostic failure')
            return original(path)
        monkeypatch.setattr(sources.Path, 'read_bytes', read)
    else:
        original = ws.store.set
        def write(key, value):
            if key.startswith('prompt_source:'):
                raise OSError('Synthetic source snapshot failure')
            return original(key, value)
        monkeypatch.setattr(ws.store, 'set', write)
    outcome = None
    with prompt_call(ws.store, 'source_vision', sources=['source-vision'], offered=payload):
        outcome = 'caller success'
        observe_prompt_request(httpx.Request('POST', 'https://fixture.invalid', json=payload), ws.store)
    assert outcome == 'caller success'
    final, = captures(ws.store, 'prompt_final_http_input')
    assert final['source_manifest']['status'] == 'unavailable'
    assert any(e['kind'] == 'prompt_capture_unavailable' for e in ws.store.events())
